"""Événements : règles de détection, analyse contre référence, droits, import des clusters."""

from datetime import datetime

import pandas as pd
import pytest
import sqlalchemy as sa
from django.contrib.auth.models import User
from django.utils import timezone

from apps.comptes.models import Perimetre
from apps.evenements import detection
from apps.evenements.analyse import AnalyseImpossible, analyser
from apps.evenements.clusters import importer_clusters
from apps.evenements.models import Creneau, Evenement
from apps.kpi.catalogue import DefinitionKpi, catalogue
from apps.kpi.models import SeuilKpi

from apps.kpi.service import cellules_du_perimetre

from .test_service import analyste, referentiel, requete  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

RRC = DefinitionKpi(code="rrc", libelle="RRC", techno="LTE", unite="%", categorie="accessibilite",
                    numerateur="s", denominateur="a", facteur=100, sens="haut_est_mieux",
                    seuils={"alerte": 98, "critique": 95})
DROP = DefinitionKpi(code="drop", libelle="Drop", techno="LTE", unite="%", categorie="retainability",
                     numerateur="d", denominateur="r", facteur=100, sens="bas_est_mieux")


# ------------------------------------------------------------------ règles isolées

def test_ecart_significatif_sens_et_pourcentage():
    assert detection.ecart_significatif(RRC, 70, 99, [99, 98.5, 99.5], sigma=2, pct=20)
    assert not detection.ecart_significatif(RRC, 99, 70, [70, 71], sigma=2, pct=20)  # amélioration
    # Taux de succès : écart lu sur le taux d'échec (1 % -> 10 % = +900 %), plus le brut (-9 %).
    assert detection.ecart_significatif(RRC, 90, 99, [99, 98.5], sigma=2, pct=20)
    assert not detection.ecart_significatif(RRC, 98.9, 99, [99, 98.5, 99.2], sigma=2, pct=20)  # échecs +10 %
    assert detection.ecart_significatif(DROP, 3, 1, [1, 1.1], sigma=2, pct=20)


def test_ecart_significatif_ecarts_types():
    # -25 % mais référence très dispersée : moins de 2 écarts-types -> pas significatif.
    assert not detection.ecart_significatif(DROP, 1.25, 1, [0.2, 1.8, 1.0], sigma=2, pct=20)
    # Une seule semaine ou semaines identiques : seul le critère en % s'applique.
    assert detection.ecart_significatif(DROP, 1.25, 1, [1], sigma=2, pct=20)
    assert detection.ecart_significatif(DROP, 1.25, 1, [1, 1], sigma=2, pct=20)
    assert not detection.ecart_significatif(DROP, None, 1, [1], sigma=2, pct=20)


def test_anomalies_seuils():
    valeurs = pd.DataFrame({"rrc": [99.0, 97.0, 90.0, float("nan")]}, index=["A", "B", "C", "D"])
    res = detection.anomalies_seuils("LTE", valeurs, [RRC])
    assert [(a.entite, a.gravite) for a in res] == [("B", "alerte"), ("C", "critique")]


def test_anomalies_sans_donnees():
    res = detection.anomalies_sans_donnees("LTE", {"c1": "S1", "c2": "S2", "c3": "S3"},
                                           {("c1", 0), ("c1", 1), ("c2", 1)}, nb_creneaux=2)
    assert [(a.entite, a.gravite) for a in res] == [("S2", "alerte"), ("S3", "critique")]
    assert "créneau(x) 1" in res[0].message


def test_anomalies_saturation():
    horaire = pd.DataFrame({"cellule": ["c1"] * 3 + ["c2"] * 2, "instant": [1, 2, 3, 1, 2],
                            "prb": [95, 95, 50, 95, 99], "debit": [5, 20, 5, 4, 3]})
    res = detection.anomalies_saturation("LTE", horaire, {"c1": "S1"}, "prb", "debit", 90, 10)
    assert [(a.entite, a.gravite) for a in res] == [("S1", "alerte"), ("c2", "critique")]
    assert "1 h" in res[0].message and "2 h" in res[1].message


def test_classement():
    a = [detection.Anomalie("critique", "seuil", "LTE", "S1", "", RRC),
         detection.Anomalie("alerte", "ecart", "LTE", "S2", "", RRC),
         detection.Anomalie("alerte", "saturation", "LTE", "S2", ""),
         detection.Anomalie("alerte", "sans_donnees", "LTE", "S2", "")]
    c = detection.classement(a)
    assert [(e["entite"], e["score"]) for e in c] == [("S1", 3), ("S2", 3)]
    assert c[1]["kpis"] == ["Données absentes", "RRC", "Saturation"]


# ------------------------------------------------------------------ analyse complète

def _ligne(cell, jour, heure):
    w = (jour - 1) // 7  # semaine du mois : 4 = événement (29-30/09), s = 4 - w ailleurs
    s = 4 - w
    ligne = {"EutranCell_Id": cell, "DateHour": datetime(2026, 9, jour, heure), "pmRrcConnEstabAtt": 100,
             "pmRrcConnEstabSucc": 99 if s % 2 else 98, "PayloadDl_mB": 10.0 + s,
             "UserThpDl_kbps": 30000.0, "PrbVectUsageDl_p": 40.0}
    if w == 4:
        ligne["PayloadDl_mB"] = 20.0
        ligne["pmRrcConnEstabSucc"] = 50 if cell == "AAAe1" else 99
        if cell == "AAAe2":
            ligne.update(PrbVectUsageDl_p=95.0, UserThpDl_kbps=5000.0)
    return ligne


@pytest.fixture
def base_horaire():
    """1er-30/09, 17h-22h. BBBe1 absente le 30/09, BBBe2 jamais présente."""
    lignes = [_ligne(c, j, h) for j in range(1, 31) for h in range(17, 23)
              for c in ("AAAe1", "AAAe2", "BBBe1") if not (c == "BBBe1" and j == 30)]
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    pd.DataFrame(lignes).to_sql("lte_cell_hour", engine, index=False)
    return engine


@pytest.fixture
def evenement(referentiel):  # noqa: F811
    e = Evenement.objects.create(nom="Foire", sites=["AAA100"], cellules=["BBBe1", "BBBe2", "INCONNUE"],
                                 kpis=["lte_rrc_setup_sr", "lte_payload_dl", "lte_prb_dl_util", "lte_dl_user_thp"])
    for jour, fin in ((29, 21), (30, 20)):
        Creneau.objects.create(evenement=e, debut=timezone.make_aware(datetime(2026, 9, jour, 18)),
                               fin=timezone.make_aware(datetime(2026, 9, jour, fin)))
    return e


def _synthese(analyse, code):
    return next(s for s in analyse.par_techno[0].synthese if s.kpi.code == code)


def test_analyse_synthese_ratio_de_sommes(evenement, base_horaire, analyste):  # noqa: F811
    a = analyser(evenement, analyste, base_horaire)
    lte = a.par_techno[0]
    assert lte.nb_cellules == 4 and lte.cellules_sans_donnees == ["BBBe2"]
    rrc = _synthese(a, "lte_rrc_setup_sr")
    # Événement : 13 lignes (9 le 29/09 de 18h à 21h, 4 le 30/09 de 18h à 20h), AAAe1 à 50 %.
    assert rrc.valeur == pytest.approx((5 * 50 + 8 * 99) / 1300 * 100)
    assert rrc.reference == pytest.approx(98.5)
    assert rrc.statut == "critique"
    vol = _synthese(a, "lte_payload_dl")
    assert vol.valeur == pytest.approx(13 * 20)
    assert vol.reference == pytest.approx(15 * 12.5)  # moyenne des semaines, pas leur somme


def test_analyse_courbes(evenement, base_horaire, analyste):  # noqa: F811
    lte = analyser(evenement, analyste, base_horaire).par_techno[0]
    assert lte.instants == ["29/09 18h", "29/09 19h", "29/09 20h", "30/09 18h", "30/09 19h"]
    vol = next(c for c in lte.courbes if c.kpi.code == "lte_payload_dl")
    assert vol.evenement[0] == pytest.approx(60) and vol.evenement[3] == pytest.approx(40)
    assert vol.reference[0] == pytest.approx(3 * 12.5)
    assert (vol.ref_min[0], vol.ref_max[0]) == (pytest.approx(33), pytest.approx(42))


def test_analyse_anomalies(evenement, base_horaire, analyste):  # noqa: F811
    a = analyser(evenement, analyste, base_horaire)
    trouvees = {(x.regle, x.entite, x.gravite) for x in a.anomalies}
    assert ("seuil", "AAA1001", "critique") in trouvees  # RRC 50 %
    assert ("ecart", "AAA1001", "critique") in trouvees
    assert ("saturation", "AAA1002", "critique") in trouvees
    assert ("sans_donnees", "BBB2001", "alerte") in trouvees  # absente du 2e créneau
    assert ("sans_donnees", "BBB2002", "critique") in trouvees
    assert a.anomalies[0].gravite == "critique"
    # AAA1002 : saturation + seuils et écarts PRB / débit (5 critiques) devant AAA1001 (RRC).
    assert [c["entite"] for c in a.classement[:2]] == ["AAA1002", "AAA1001"]

    par_site = analyser(evenement, analyste, base_horaire, niveau="site")
    assert {x.entite for x in par_site.anomalies} == {"SITE_AAA", "SITE_BBB"}


def test_seuils_regles_dans_l_admin(evenement, base_horaire, analyste):  # noqa: F811
    SeuilKpi.synchroniser()
    assert SeuilKpi.objects.get(code="lte_rrc_setup_sr").alerte == 98
    SeuilKpi.objects.filter(code="lte_rrc_setup_sr").update(alerte=40, critique=30)
    assert catalogue()["lte_rrc_setup_sr"].statut(80) == ""
    a = analyser(evenement, analyste, base_horaire)
    assert not any(x.regle == "seuil" and x.kpi.code == "lte_rrc_setup_sr" for x in a.anomalies)


def test_lecteur_restreint(evenement, base_horaire):
    u = User.objects.create_user("lec")
    Perimetre.objects.create(nom="Paita", communes=["PAITA"]).utilisateurs.add(u)
    a = analyser(evenement, u, base_horaire)
    assert a.par_techno[0].nb_cellules == 2
    assert {x.entite for x in a.anomalies} <= {"BBB2001", "BBB2002"}
    assert any("hors de votre périmètre" in m for m in a.avertissements)


def test_sans_creneau(referentiel, base_horaire, analyste):  # noqa: F811
    e = Evenement.objects.create(nom="Vide", cellules=["AAAe1"])
    with pytest.raises(AnalyseImpossible):
        analyser(e, analyste, base_horaire)


def test_perimetre_evenement_dans_une_requete(evenement):
    req = requete(perimetre={"type": "evenement", "valeurs": ["Foire"]})
    assert cellules_du_perimetre(req, "LTE") == ["AAAe1", "AAAe2", "BBBe1", "BBBe2"]


def test_cellules_inconnues_signalees(evenement):
    assert evenement.cellules_inconnues() == ["INCONNUE"]


# ------------------------------------------------------------------ import des clusters

def test_import_clusters(tmp_path):
    chemin = tmp_path / "ref.xlsx"
    pd.DataFrame({
        "Cluster": ["Foire", "Foire", "Concert ", "Concert"],
        "RBS": ["X"] * 4, "Trigramme": ["AAA"] * 4,
        "Cellule": ["AAAe1", "AAA1001A", "BBBe1", "BBBe1"],
        "Type": ["Day", "Day", "Concert", "Concert"],
    }).to_excel(chemin, sheet_name="Cluster", index=False)
    Evenement.objects.create(nom="Foire", description="déjà là")
    crees, ignores = importer_clusters(chemin)
    assert crees == ["Concert"] and ignores == ["Foire"]
    concert = Evenement.objects.get(nom="Concert")
    assert concert.cellules == ["BBBe1"] and concert.type == "Concert"
    assert not concert.creneaux.exists()
    assert Evenement.objects.get(nom="Foire").description == "déjà là"
