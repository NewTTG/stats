"""Analyse d'un résultat : congestion mise en avant, bien / mal passé, compteurs proposés.

Demande d'origine : « Fais moi une analyse de la qualité radio sur le weekend du 24 25
septembre sur la commune de Canala par cellule pour mettre en avant la congestion ».
"""

import io
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from pptx import Presentation

from apps.kpi import bilan
from apps.kpi.catalogue import catalogue_yaml
from apps.kpi.recherche import Contexte
from apps.kpi.recherche.regles import interpreter
from apps.kpi.requete import RequeteKpi
from apps.kpi.service import Resultat, ResultatTechno
from apps.rapports.contenu import pptx_requete
from apps.referentiel.models import Cellule, Secteur, Site

from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixtures)
from .test_recherche_vues import _html, admin, base_recherche  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

PHRASE = ("Fais moi une analyse de la qualité radio sur le weekend du 24 25 septembre sur la commune de "
          "Canala par cellule pour mettre en avant la congestion")
HEURES = pd.date_range("2026-09-24 00:00", "2026-09-25 23:00", freq="h")


def _t(texte):
    """Espaces fines insécables (« 80,00 % ») -> espaces simples, pour comparer les textes."""
    return texte.replace("\u202f", " ").replace("\u00a0", " ")


# ------------------------------------------------------------------ interprétation

@pytest.fixture
def canala(ref_recherche):  # noqa: F811
    site = Site.objects.create(code_site="KBO306", trigramme="KBO", nom="KOTABO", commune="CANALA", region="NORD")
    for n in (1, 2, 3):
        secteur = Secteur.objects.create(code=f"KBO306{n}", site=site, numero=n)
        Cellule.objects.create(nom=f"KBOe{n}", techno="LTE", secteur=secteur)
        Cellule.objects.create(nom=f"KBO306{'ABC'[n - 1]}", techno="WCDMA", secteur=secteur)
    return Contexte.pour(None)


def test_demande_d_origine_comprise(canala):
    i = interpreter(PHRASE, J, canala)
    assert i.complete and i.non_compris == []
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["CANALA"]}
    assert (i.params["periode"]["debut"], i.params["periode"]["fin"]) == (date(2026, 9, 24), date(2026, 9, 25))
    assert i.params["granularite_espace"] == "cellule" and i.params["granularite_temps"] == "heure"
    assert i.demande.intentions == ["rapport_qualite", "rapport_congestion"]
    kpis = i.params["kpis"]
    assert {"lte_acces", "lte_erab_drop", "wcdma_cs_drop"} <= set(kpis)  # qualité radio
    assert {"lte_prb_dl_util", "lte_dl_user_thp", "lte_rrc_conn_max", "wcdma_rab_ps_blocage"} <= set(kpis)
    assert i.params["techno"] == ["LTE", "WCDMA"]


@pytest.mark.parametrize("texte, debut, fin", [
    ("congestion Canala le weekend du 24 25 septembre", (24, 9), (25, 9)),
    ("congestion Canala le week-end du 24 et 25 septembre", (24, 9), (25, 9)),
    ("congestion Canala les 24-25 septembre", (24, 9), (25, 9)),
    ("congestion Canala 24/25 septembre", (24, 9), (25, 9)),
    ("congestion Canala du 1er au 15 septembre", (1, 9), (15, 9)),
    ("congestion Canala le week-end du 14 septembre", (12, 9), (13, 9)),  # samedi-dimanche
])
def test_jours_cites_d_un_week_end(canala, texte, debut, fin):
    i = interpreter(texte, J, canala)
    p = i.params["periode"]
    assert (p["debut"], p["fin"]) == (date(2026, *debut[::-1]), date(2026, *fin[::-1]))
    assert i.non_compris == []


@pytest.mark.parametrize("texte", ["analyse de la congestion à Canala hier", "focus congestion Canala hier",
                                   "Canala hier, mettre en avant la congestion"])
def test_analyse_de_congestion(canala, texte):
    i = interpreter(texte, J, canala)
    assert i.demande.intentions == ["rapport_congestion"] and i.non_compris == []
    assert i.params["techno"] == ["LTE", "WCDMA"]


def test_congestion_seule_inchangee(canala):
    i = interpreter("congestion Canala hier", J, canala)
    assert i.params["kpis"] == ["lte_prb_dl_util"]


# ------------------------------------------------------------------ calcul

def _requete(**modifs):
    base = {"techno": ["LTE", "WCDMA"], "perimetre": {"type": "commune", "valeurs": ["CANALA"]},
            "periode": {"debut": date(2026, 9, 24), "fin": date(2026, 9, 25)}, "granularite_temps": "heure",
            "granularite_espace": "cellule",
            "kpis": ["lte_prb_dl_util", "lte_dl_user_thp", "lte_rrc_conn_max", "lte_erab_drop", "wcdma_rab_ps_blocage",
                     "wcdma_cs_drop"]}
    return RequeteKpi(**{**base, **modifs})


def _techno(techno, colonnes: dict[str, dict[str, list]], synthese: dict[str, dict[str, float]], globale, **kw):
    cat = catalogue_yaml()
    codes = list(colonnes)
    entites = list(next(iter(colonnes.values())))
    index = pd.MultiIndex.from_tuples([(h, e) for h in HEURES for e in entites], names=["periode", "entite"])
    table = pd.DataFrame({c: [colonnes[c][e][i] for i in range(len(HEURES)) for e in entites] for c in codes},
                         index=index)
    synth = pd.DataFrame(synthese).rename_axis("entite")[codes]
    return ResultatTechno(techno=techno, kpis=[cat[c] for c in codes], table=table, cellules_demandees=len(entites),
                          synthese=synth, synthese_globale=globale, **kw)


def _soir(valeur_soir, valeur_jour, heures=range(18, 22), jours=(24,)):
    return [valeur_soir if h.hour in heures and h.day in jours else valeur_jour for h in HEURES]


@pytest.fixture
def resultat():
    lte = _techno("LTE", {
        "lte_prb_dl_util": {"KBOe3": _soir(95.0, 40.0), "KBOe1": _soir(30.0, 20.0), "KBOe2": [50.0] * 48},
        "lte_dl_user_thp": {"KBOe3": _soir(2.5, 20.0), "KBOe1": [25.0] * 48, "KBOe2": [15.0] * 48},
        "lte_rrc_conn_max": {"KBOe3": _soir(400, 100), "KBOe1": [50] * 48, "KBOe2": [80] * 48},
        "lte_erab_drop": {"KBOe3": [0.5] * 48, "KBOe1": [0.4] * 48, "KBOe2": [3.0] * 48},
    }, {
        "lte_prb_dl_util": {"KBOe3": 44.6, "KBOe1": 21.7, "KBOe2": 50.0},
        "lte_dl_user_thp": {"KBOe3": 12.0, "KBOe1": 25.0, "KBOe2": 15.0},
        "lte_rrc_conn_max": {"KBOe3": 400, "KBOe1": 50, "KBOe2": 80},
        "lte_erab_drop": {"KBOe3": 0.5, "KBOe1": 0.4, "KBOe2": 3.0},
    }, {"lte_prb_dl_util": 38.8, "lte_dl_user_thp": 15.5, "lte_rrc_conn_max": 530, "lte_erab_drop": 0.9},
        cellules_sans_donnees=["KBOe11"])
    wcdma = _techno("WCDMA", {
        "wcdma_rab_ps_blocage": {"KBO306B": _soir(1.5, 0.0, heures=(19, 20)), "KBO306A": [0.0] * 48},
        "wcdma_cs_drop": {"KBO306B": [0.2] * 48, "KBO306A": [0.3] * 48},
    }, {
        "wcdma_rab_ps_blocage": {"KBO306B": 0.06, "KBO306A": 0.0},
        "wcdma_cs_drop": {"KBO306B": 0.2, "KBO306A": 0.3},
    }, {"wcdma_rab_ps_blocage": 0.03, "wcdma_cs_drop": 0.25})
    return Resultat(requete=_requete(), par_techno=[lte, wcdma])


def test_congestion_par_cellule(resultat):
    b = bilan.analyser(resultat, catalogue_yaml())
    assert b.congestion_sujet
    [c] = b.congestion
    assert (c.entite, c.gravite, c.periodes, c.periodes_critiques, c.periodes_mesurees) == ("KBOe3", "critique", 4, 4, 48)
    assert c.plages == "24/09 18h–22h" and c.pic_quand == "24/09 18h" and _t(c.pic) == "95,00 %"
    impacts = [_t(i) for i in c.impacts]
    assert any(i.startswith("Débit DL utilisateur moyen : 2,50 Mbps à l'heure du pic") and "seuil critique" in i
               for i in impacts)
    assert any("jusqu'à 400 utilisateurs pendant la congestion (pic de la période)" in i for i in impacts)
    constats = [_t(c) for c in b.constats]
    assert constats[0].startswith("4G : 1 cellule sur 3 en congestion (Utilisation PRB DL au-delà de 80,00 %), "
                                    "4 heures-cellule au total. La plus touchée : KBOe3")
    assert "3G : rejets ou blocages dus à la charge : Blocages RAB data sur KBO306B." in constats
    [s] = b.signes
    assert (s.entite, s.periodes, _t(s.maximum), s.plages) == ("KBO306B", 2, "1,50 %", "24/09 19h–21h")


def test_bien_et_mal_passe(resultat):
    b = bilan.analyser(resultat, catalogue_yaml())
    mal = [_t(p.texte) for p in b.mal]
    # La congestion d'abord, puis les signes de charge, puis le reste par gravité.
    assert mal[0].startswith("Utilisation PRB DL (4G) : dans le seuil sur la période (38,80 %), mais 4 heures-cellule")
    assert mal[1].startswith("Blocages RAB data (3G) : 2 heures-cellule avec des rejets sur 1 cellule : KBO306B")
    assert any(t.startswith("Taux de coupure E-RAB (4G) : 0,90 % sur l'ensemble ; 1 cellule au-dessus du seuil "
                            "(1,00 %) sur la période : KBOe2 (3,00 %)") for t in mal)
    assert any(t.startswith("Débit DL utilisateur moyen (4G)") and "sous le seuil" in t for t in mal)
    assert "1 cellule 4G sans aucune donnée : KBOe11." in mal
    bien = [_t(p.texte) for p in b.bien]
    assert bien[0] == ("Utilisation PRB DL (4G) : 38,80 % sur l'ensemble, dans le seuil (80,00 %) ; "
                       "2 cellules sur 3 sans aucun dépassement.")
    assert ("Taux de coupure appels voix (3G) : 0,25 % sur l'ensemble, dans le seuil (1,00 %) pour toutes les "
            "cellules, à chaque période.") in bien
    assert "Toutes les cellules 3G du périmètre (2) ont remonté des données." in bien


def test_compteurs_proposes(resultat):
    b = bilan.analyser(resultat, catalogue_yaml())
    codes = [s.code for s in b.suggestions]
    assert codes and len(codes) <= bilan.SUGGESTIONS_MAX
    assert not set(codes) & set(resultat.requete.kpis)
    assert codes[0] == "lte_rrc_echec_charge"  # 4G d'abord, dans l'ordre de config/bilan.yaml
    assert bilan.analyser(resultat).suggestions == []  # sans catalogue visible : rien


def test_sans_congestion_pas_de_section(resultat):
    sans = Resultat(requete=_requete(kpis=["lte_erab_drop"], techno=["LTE"]),
                    par_techno=[_techno("LTE", {"lte_erab_drop": {"A": [0.5] * 48}}, {"lte_erab_drop": {"A": 0.5}},
                                        {"lte_erab_drop": 0.5})])
    b = bilan.analyser(sans, catalogue_yaml())
    assert not b.congestion_sujet and not b.constats and not b.suggestions
    assert _t(b.bien[0].texte).startswith("Taux de coupure E-RAB (4G) : 0,50 %")


def test_pas_de_congestion_le_dit(resultat):
    calme = Resultat(requete=_requete(kpis=["lte_prb_dl_util"], techno=["LTE"], granularite_espace="global"),
                     par_techno=[_techno("LTE", {"lte_prb_dl_util": {"Global": _soir(60.0, 30.0)}},
                                         {"lte_prb_dl_util": {"Global": 32.5}}, {"lte_prb_dl_util": 32.5})])
    b = bilan.analyser(calme, catalogue_yaml())
    assert [_t(c) for c in b.constats] == ["4G : pas de congestion, Utilisation PRB DL sous 80,00 % à chaque période "
                          "(au plus 60,00 %, le 24/09 18h)."]
    assert b.conseil_cellule and not b.conseil_heure


def test_statuts_vectorises_comme_le_catalogue():
    cat = catalogue_yaml()
    valeurs = pd.Series([np.nan, 0, 79.9, 80, 85, 90, 100, 1, 4.9, 5, 9.99, 10, 50])
    for code in ("lte_prb_dl_util", "lte_dl_user_thp", "lte_erab_drop", "lte_prb_ul_util"):
        k = cat[code]
        attendu = [k.statut(None if pd.isna(v) else float(v)) for v in valeurs]
        assert list(bilan.statuts(valeurs, k)) == attendu


def test_plages():
    h = lambda j, heure: pd.Timestamp(datetime(2026, 9, j, heure))  # noqa: E731
    assert bilan.plages([h(24, 18), h(24, 19), h(24, 21)], "heure") == "24/09 18h–20h, 24/09 21h"
    assert bilan.plages([h(24, 22), h(24, 23)], "heure") == "24/09 22h–24h"
    assert bilan.plages([h(24, 23), h(25, 0), h(25, 1)], "heure") == "24/09 23h → 25/09 2h"
    assert bilan.plages([h(24, 0), h(25, 0), h(27, 0)], "jour") == "24/09–25/09, 27/09"
    assert bilan.plages([h(24, i) for i in range(0, 12, 2)], "heure").endswith("+2 autres")


def test_rapport_powerpoint_avec_analyse(resultat):
    prs = Presentation(io.BytesIO(pptx_requete(resultat)))
    textes = [_t(sh.text_frame.text) for s in prs.slides for sh in s.shapes if sh.has_text_frame]
    assert any(t.startswith("Analyse : congestion") for t in textes)
    assert any("KBOe3 (4G) : 4 h en congestion dont 4 critiques" in t for t in textes)
    assert any(t.startswith("Analyse : ce qui s'est bien passé") for t in textes)


# ------------------------------------------------------------------ écran

def test_ecran_analyse_de_congestion(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "analyse de la congestion à Nouméa par cellule hier"}))
    assert 'id="titre-analyse"' in html and "<h3>Congestion</h3>" in html
    assert html.index('id="titre-analyse"') < html.index('id="titre-synthese"')
    assert "Ce qui ne s&#x27;est pas bien passé" in html or "Ce qui ne s'est pas bien passé" in html
    assert "Autres compteurs utiles pour la congestion" in html and "+ Ajouter" in html
    assert "kpis=lte_rrc_echec_charge" in html  # lien d'ajout : compteurs actuels + celui proposé


def test_ecran_analyse_conseille_le_detail(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "congestion à Nouméa hier"}))
    assert "voir par cellule" in html and "granularite_espace=cellule" in html


def test_ecran_sans_seuil_sans_analyse(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "trafic data 4G à Nouméa hier"}))
    assert 'id="titre-analyse"' not in html
