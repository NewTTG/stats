"""Non-régression du contrôle final (tour 6) : « sud » sans Mont-Dore ni Païta (région
majoritaire), « appels CSFB et SMS » (techno déduite d'un sigle vs techno citée)."""

import pytest

from apps.kpi.recherche import Contexte
from apps.kpi.recherche.regles import interpreter
from apps.referentiel.models import Cellule, Secteur, Site

from .test_controle_tour3 import _question_lieu, ctx3, ctx_lecteur, lecteur_kone, ref_t3  # noqa: F401
from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

SITES_T6 = [  # code, commune, région : Mont-Dore et Païta à cheval sur GRD NEA 1 et SUD
    ("PAI901", "PAITA", "SUD"),
    ("MDO901", "MONT DORE", "SUD"),
    ("MDO902", "MONT DORE", "GRD NEA 1"),
    ("THI001", "THIO", "SUD"),
]


def _creer_sites(sites):
    for code, commune, region in sites:
        site = Site.objects.create(code_site=code, trigramme=code[:3], nom=f"SITE_{code}", commune=commune,
                                   region=region)
        secteur = Secteur.objects.create(code=f"{code}1", site=site, numero=1)
        Cellule.objects.create(nom=f"{code}L1", techno="LTE", secteur=secteur)
        Cellule.objects.create(nom=f"{code}A", techno="WCDMA", secteur=secteur)


@pytest.fixture
def ref_t6(ref_t3):  # noqa: F811
    _creer_sites(SITES_T6)


@pytest.fixture
def ctx6(ref_t6):
    return Contexte.pour(None)


@pytest.fixture
def ctx6_lecteur(ref_t6, lecteur_kone):  # noqa: F811
    return Contexte.pour(lecteur_kone)


def _communes(i):
    p = i.params["perimetre"]
    assert p["type"] == "commune", p
    return set(p["valeurs"])


# ------------------------------------------------------------------ mineur 1 : « sud »

def test_sud_sans_mont_dore_ni_paita(ctx6):
    sud = _communes(interpreter("drop 3G Sud le 6 octobre", J, ctx6))
    assert "PAITA" not in sud and "MONT DORE" not in sud
    assert {"LA FOA", "BOURAIL", "ILE DES PINS", "THIO"} <= sud


def test_sud_et_grand_noumea_partagent_la_province_sud(ctx6):
    sud = _communes(interpreter("drop 3G Sud le 6 octobre", J, ctx6))
    gn = _communes(interpreter("drop 3G Grand Nouméa le 6 octobre", J, ctx6))
    province = _communes(interpreter("drop 3G Province Sud le 6 octobre", J, ctx6))
    assert gn == {"NOUMEA", "DUMBEA", "MONT DORE", "PAITA"}
    assert not sud & gn
    assert sud | gn == province


def test_egalite_de_sites_ordre_alphabetique(ref_t3):  # noqa: F811
    """Mont-Dore : 1 site GRD NEA 1, 1 site SUD -> « GRD NEA 1 » (premier dans l'ordre alphabétique)."""
    _creer_sites([("MDO901", "MONT DORE", "SUD")])
    ctx = Contexte.pour(None)
    assert "MONT DORE" not in _communes(interpreter("drop 3G Sud le 6 octobre", J, ctx))
    assert "MONT DORE" in _communes(interpreter("drop 3G Grand Nouméa le 6 octobre", J, ctx))


def test_sud_hors_perimetre_pour_le_lecteur_de_kone(ctx6_lecteur):
    q = _question_lieu(interpreter("drop 4G sud le 6 octobre", J, ctx6_lecteur))
    assert q and q.texte == "« sud » n'est pas dans votre périmètre."


# ------------------------------------------------------------------ mineur 2 : CSFB et SMS

def test_appels_csfb_et_sms(ctx6):
    i = interpreter("appels CSFB et SMS à Thio semaine 38", J, ctx6)
    assert "lte_csfb_appels" in i.params["kpis"] and "wcdma_sms" in i.params["kpis"]
    assert i.params["techno"] == ["LTE", "WCDMA"]
    assert i.notes == [] and i.params["perimetre"] == {"type": "commune", "valeurs": ["THIO"]}


def test_drop_erab_et_sms(ctx6):
    i = interpreter("drop E-RAB et SMS hier", J, ctx6)
    assert "lte_erab_drop" in i.params["kpis"] and "wcdma_sms" in i.params["kpis"]
    assert not any(k.startswith("wcdma_") and k != "wcdma_sms" for k in i.params["kpis"])
    assert i.notes == []


def test_sms_4g_cite_garde_la_note(ctx6):
    i = interpreter("SMS 4G hier", J, ctx6)
    assert "Aucun KPI « SMS » en 4G." in i.notes
    assert "wcdma_sms" not in i.params.get("kpis", [])


def test_techno_citee_inchangee(ctx6):
    i = interpreter("nombre d'appels 3G et CSFB à Koné hier", J, ctx6)
    assert "lte_csfb_appels" in i.params["kpis"] and "wcdma_appels_voix" in i.params["kpis"]
    i = interpreter("taux de succès S1 4G Voh hier", J, ctx6)
    assert i.params["kpis"] == ["lte_s1_sig_sr"] and i.params["techno"] == ["LTE"]
    assert interpreter("drop E-RAB 3G Koné hier", J, ctx6).params["techno"] == ["WCDMA"]


def test_techno_en_parametre_remet_la_techno_citee(ctx6):
    from apps.kpi.recherche.construction import appliquer
    from apps.kpi.recherche.regles import analyser

    d, _nc, _notes = analyser("appels CSFB et SMS à Thio hier", J, ctx6)
    assert d.techno == ["LTE"] and d.techno_implicite
    d2, _ = appliquer(d, {"techno": ["LTE"]}, ctx6, J)
    assert d2.techno == ["LTE"] and not d2.techno_implicite
