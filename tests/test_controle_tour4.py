"""Non-régression du contrôle indépendant (tour 4 du développement, constats « tour 5 ») :
classement « les plus chargés », oracle des noms de sites pour un lecteur restreint,
sigles indisponibles, mots capitalisés, rapprochements, granularités, messages, mobile,
écart significatif des taux de succès."""

import re

import pytest
from django.contrib.auth.models import User

from apps.kpi.recherche import Contexte
from apps.kpi.recherche.regles import interpreter

from .test_controle_tour3 import _question_lieu, ctx3, ctx_lecteur, lecteur_kone, ref_t3  # noqa: F401
from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixture)
from .test_recherche_vues import base_recherche  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def _nombre(texte: str) -> float:
    return float(re.sub(r"[\s  ]", "", texte).replace(",", "."))


def _classement(html: str, titre: str) -> list[float]:
    bloc = re.search(rf"{re.escape(titre)}</h3>(.*?)</table>", html, re.S)
    assert bloc, f"classement « {titre} » absent"
    return [_nombre(v) for v in re.findall(r'<td class="val">([\d\s  ,]+)', bloc[1])]


# ------------------------------------------------------------------ MAJEUR 1 : « les plus chargés »

def test_top_sites_les_plus_charges_interpretation(ctx3):  # noqa: F811
    i = interpreter("top 10 des sites les plus chargés en trafic data à Nouméa la semaine dernière", J, ctx3)
    assert i.complete and i.non_compris == []
    assert i.params["granularite_espace"] == "site" and i.params["kpis"] == ["lte_payload_dl", "wcdma_payload_hs"]
    assert i.demande.classement and i.demande.classement_nombre == 10


@pytest.mark.parametrize("phrase,niveau,nombre", [
    ("top 5 des pires secteurs en drop 4G à Nouméa hier", "secteur", 5),
    ("les 3 sites les plus chargés en appels à Koné hier", "site", 3),
    ("les 10 cellules 4G avec le pire débit montant à Païta hier", "cellule", 10),
    ("les sites avec le plus de trafic à Nouméa hier", "site", None),
])
def test_top_n_et_les_n(ctx3, phrase, niveau, nombre):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    assert i.params["granularite_espace"] == niveau and i.demande.classement
    assert i.demande.classement_nombre == nombre and i.non_compris == []


def test_vue_classement_les_plus_charges_decroissant(base_recherche, client):  # noqa: F811
    client.force_login(User.objects.create_superuser("admin4"))
    html = client.get("/", {"q": "top 10 des sites les plus chargés en trafic data à Nouméa la semaine dernière"}
                      ).content.decode()
    assert "Classement par site" in html and "Les plus dégradés — Volume" not in html
    valeurs = _classement(html, "Les plus chargés — Volume DL")
    assert 2 <= len(valeurs) <= 10 and valeurs == sorted(valeurs, reverse=True)
    html = client.get("/", {"q": "top 2 des sites les plus chargés en trafic data à Nouméa la semaine dernière"}
                      ).content.decode()
    valeurs = _classement(html, "Les plus chargés — Volume DL")
    assert len(valeurs) == 2 and valeurs[0] >= valeurs[1]
    # Qualité : toujours « les plus dégradés » ; durée moyenne d'appel : jamais classée.
    html = client.get("/", {"q": "drop 4G et durée moyenne des appels par site à Nouméa la semaine dernière"}
                      ).content.decode()
    assert "Les plus dégradés — Taux de coupure E-RAB" in html and "— Durée" not in html


# ------------------------------------------------------------------ MAJEUR 2 : pas d'oracle sur les noms de sites

# Mots tirés de noms de sites (et d'événements) hors du périmètre du lecteur, et mots inventés.
MOTS_ORACLE = ["tindu", "einstein", "magenta", "ravel", "pepiniere", "koutio", "tontouta", "carnaval", "diginova"]
TEMOINS = ["xylophone", "zorglub"]


@pytest.fixture
def lecteur_paita(base_recherche, client):  # noqa: F811
    from apps.comptes.models import Perimetre
    from apps.evenements.models import Evenement
    from apps.referentiel.models import Site

    for code, nom in [("TND063", "TINDU"), ("EIN001", "EINSTEIN"), ("MAG001", "MAGENTA_PLAGE"), ("RAV001", "RAVEL"),
                      ("PEP001", "PEPINIERE"), ("KTO001", "KOUTIO"), ("TON001", "TONTOUTA_AERO")]:
        Site.objects.create(code_site=code, trigramme=code[:3], nom=nom, commune="NOUMEA", region="NEA")
    Evenement.objects.create(nom="Diginova", sites=["NOU001"])
    lecteur = User.objects.create_user("lec_oracle")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"]).utilisateurs.add(lecteur)
    client.force_login(lecteur)
    return client


def _page(client, phrase, mot):
    html = client.get("/", {"q": phrase}).content.decode()
    html = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", html)
    return html.replace(mot, "MOT").replace(mot.capitalize(), "MOT")


@pytest.mark.parametrize("modele,capitalise", [
    ("drop 4G {} hier", False), ("drop 4G {} Païta hier", False), ("drop 4G à {} hier", False),
    ("drop 4G {} hier", True), ("drop 4G à {} hier", True), ("débit 4G Païta {} la semaine dernière", False),
], ids=["seul", "avec-commune", "apres-a", "capitalise", "capitalise-apres-a", "fin"])
def test_lecteur_aucun_oracle_sur_les_noms(lecteur_paita, modele, capitalise):
    """Réponse HTML identique, au mot près, pour un nom de site / d'événement hors périmètre
    et pour un mot inventé (xylophone, zorglub)."""
    pages = {}
    for mot in MOTS_ORACLE + TEMOINS:
        pages[mot] = _page(lecteur_paita, modele.format(mot.capitalize() if capitalise else mot), mot)
    reference = pages["xylophone"]
    if " à " in modele:  # placé comme un lieu : même question, quel que soit le mot
        assert "« MOT » n&#x27;est pas dans votre périmètre." in reference
    else:  # sinon : mot non compris, calcul sur le périmètre
        assert re.search(r'class="mot"[^>]*>MOT<', reference) and "Synthèse sur la période" in reference
    assert pages["zorglub"] == reference
    for mot in MOTS_ORACLE:
        assert pages[mot] == reference, f"« {mot} » ne répond pas comme un mot inconnu ({modele})"


def test_lecteur_sources_publiques_et_formes_de_code(ctx_lecteur):  # noqa: F811
    for phrase, texte in [("drop 4G Province Sud hier", "Province Sud"), ("drop 4G Koumak hier", "Koumak"),
                          ("drop 4G à Pita hier", "Pita"), ("drop 4G TND063 hier", "TND063"),
                          ("drop 4G XYZ999 hier", "XYZ999"), ("drop 4G QQQ hier", "QQQ"), ("drop 4G CHT hier", "CHT")]:
        q = _question_lieu(interpreter(phrase, J, ctx_lecteur))
        assert q and q.texte == f"« {texte} » n'est pas dans votre périmètre.", phrase
    # Un trigramme en minuscules, comme un mot inconnu : jamais d'après son existence.
    assert interpreter("drop 4G cht hier", J, ctx_lecteur).non_compris == ["cht"]
    assert interpreter("drop 4G qqq hier", J, ctx_lecteur).non_compris == ["qqq"]


# ------------------------------------------------------------------ mineurs : capitales, rapprochements

@pytest.mark.parametrize("phrase,mot", [
    ("Drop 4G Nouméa hier Urgent", "Urgent"), ("drop 4G Nouméa hier Tendance", "Tendance"),
    ("drop 4G Nouméa Brousse hier", "Brousse"), ("drop 4G Nouméa hier Cordialement", "Cordialement"),
    ("drop 4G Nouméa hier Xylophone", "Xylophone"),
])
def test_mot_capitalise_sans_preposition_non_compris(ctx3, phrase, mot):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    assert _question_lieu(i) is None and i.params["perimetre"] == {"type": "commune", "valeurs": ["NOUMEA"]}
    assert mot in i.non_compris


@pytest.mark.parametrize("phrase", ["drop 4G à Xylophone hier", "drop 4G de Xylophone hier",
                                    "drop 4G pour Xylophone hier"])
def test_mot_capitalise_apres_preposition_de_lieu(ctx3, phrase):  # noqa: F811
    q = _question_lieu(interpreter(phrase, J, ctx3))
    assert q and q.texte.startswith("Lieu non reconnu : « Xylophone »")


def test_faux_rapprochements(ctx3):  # noqa: F811
    from apps.evenements.models import Evenement

    Evenement.objects.create(nom="Contrôle pic drop Koné", sites=["KON552"])
    ctx = Contexte.pour(None)
    i = interpreter("drop 4G près du marché de Nouméa hier", J, ctx)
    assert _question_lieu(i) is None and i.params["perimetre"] == {"type": "commune", "valeurs": ["NOUMEA"]}
    i = interpreter("drop 4G Koné contre Pouembout la semaine dernière", J, ctx)
    assert _question_lieu(i) is None
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["KONE", "POUEMBOUT"]}
    assert i.params["granularite_espace"] == "commune"
    i = interpreter("drop 4G Maree hier", J, ctx)  # nom de 4 lettres : jamais approché
    assert not any(o.libelle == "Maré" for q in i.questions for o in q.options)


# ------------------------------------------------------------------ mineurs : vocabulaire et granularités

@pytest.mark.parametrize("phrase,sigle", [
    ("Nouméa SINR hier", "SINR"), ("RSRP Nouméa hier", "RSRP"), ("Nouméa RSRP hier", "RSRP"),
    ("BLER 4G Nouméa hier", "BLER"), ("MIMO Nouméa hier", "MIMO"), ("RSRQ Nouméa hier", "RSRQ"),
    ("CQI Nouméa hier", "CQI"), ("VoLTE Nouméa hier", "VoLTE"),
])
def test_kpi_indisponible_note_et_lieu_garde(ctx3, phrase, sigle):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    assert f"KPI « {sigle} » non disponible dans les données." in i.notes
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["NOUMEA"]} and _question_lieu(i) is None
    assert sigle not in i.non_compris


@pytest.mark.parametrize("phrase,libelle", [("drop 2G Nouméa hier", "2G"), ("drop GSM Nouméa hier", "2G (GSM)"),
                                            ("drop EDGE Nouméa hier", "2G (EDGE)")])
def test_2g_absente_puis_technos_disponibles(ctx3, phrase, libelle):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    assert f"La {libelle} n'est pas dans les données : technologies disponibles, 4G et 3G." in i.notes
    assert i.params["techno"] == ["LTE", "WCDMA"] and i.complete and _question_lieu(i) is None


@pytest.mark.parametrize("phrase,semaine", [
    ("drop 4G Nouméa en S40", 40), ("drop 4G Nouméa la S 40", 40), ("drop 4G Nouméa s.40 2026", 40),
    ("drop 4G Nouméa pendant la S38", 38), ("drop 4G Nouméa sem. 40", 40), ("drop 4G Nouméa semaine 40", 40),
    ("drop 4G Nouméa S40", None),  # sans contexte de date : pas une semaine
    ("drop 4G Nouméa en S1", None),  # « S1 » reste l'interface S1
])
def test_semaine_s_avec_contexte_de_date(ctx3, phrase, semaine):  # noqa: F811
    from datetime import date as d

    p = interpreter(phrase, J, ctx3).params.get("periode")
    if semaine is None:
        assert p is None
    else:
        lundi = d.fromisocalendar(2026, semaine, 1)
        assert (p["debut"], p["fin"]) == (lundi, d.fromisocalendar(2026, semaine, 7))
    assert interpreter("drop 4G Nouméa S1 hier", J, ctx3).params["kpis"] == ["lte_erab_drop", "lte_s1_sig_sr"]


def test_taux_d_echec_rrc_sans_composite(ctx3):  # noqa: F811
    i = interpreter("quel est le taux d'échec RRC en 3G à Koné depuis lundi", J, ctx3)
    assert i.params["kpis"] == ["wcdma_rrc_cs_sr", "wcdma_rrc_ps_sr"] and i.non_compris == []


@pytest.mark.parametrize("phrase,niveau", [
    ("utilisation PRB DL des secteurs du site PIM123 le 2 octobre", "secteur"),
    ("drop 4G des cellules du site KON552 hier", "cellule"),
    ("disponibilité des sites 3G de Koné la semaine dernière", "site"),
    ("les 10 cellules 4G avec le pire débit montant à Païta ce mois-ci", "cellule"),
    ("drop 4G au site KON552 hier", "global"),  # « au site X » : un lieu, pas un niveau
])
def test_niveau_des_sites_secteurs_cellules(ctx3, phrase, niveau):  # noqa: F811
    assert interpreter(phrase, J, ctx3).params["granularite_espace"] == niveau
