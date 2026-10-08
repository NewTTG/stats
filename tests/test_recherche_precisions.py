"""Interprétation : qualificatifs voix / data (M1), appels et durée (m2), semaine ISO et
« nb d'appels » (m3), lieux mal orthographiés ou génériques (M2)."""

from datetime import date

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import Perimetre
from apps.kpi.recherche import Contexte, avec_parametres
from apps.kpi.recherche.regles import interpreter

from .test_recherche_regles import J, causes, ctx, existants, ref_recherche  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

# Le qualificatif précise l'intention drop / accès présente au lieu d'ouvrir Appels / Trafic.
QUALIFICATIFS = [
    ("taux de coupure voix à Nouméa hier", ["wcdma_cs_drop"]),
    ("taux de coupure data 4G hier", ["lte_erab_drop"]),
    ("taux de coupure data 3G hier", ["wcdma_ps_drop"]),
    ("drop data 3G hier", ["wcdma_ps_drop"]),
    ("drop voix hier", ["wcdma_cs_drop"]),
    ("coupures des appels 3G à Koné hier", ["wcdma_cs_drop"]),
    ("coupures voix et data 3G hier", ["wcdma_cs_drop", "wcdma_ps_drop"]),
    ("taux d'accès data hier", ["lte_acces", "wcdma_cssr_ps"]),
    ("taux d'accès voix hier", ["wcdma_cssr_cs"]),
    ("accès internet 3G hier", ["wcdma_cssr_ps"]),
    ("échecs d'appels voix hier", ["wcdma_cssr_cs"]),
    ("débit data 4G hier", ["lte_dl_user_thp"]),
    ("durée moyenne des appels hier", ["wcdma_duree_appel"]),
    ("durée des communications 3G hier", ["wcdma_duree_appel"]),
    ("trafic voix hier", ["wcdma_speech_traffic"]),
    ("causes des coupures voix 3G hier", ["wcdma_cs_drop", *causes("wcdma_cs_drop")]),
]


@pytest.mark.parametrize("phrase,kpis", QUALIFICATIFS, ids=[q for q, _ in QUALIFICATIFS])
def test_qualificatifs(ctx, phrase, kpis):  # noqa: F811
    assert interpreter(phrase, J, ctx).params["kpis"] == existants(*kpis)


@pytest.mark.parametrize("phrase", ["appels hier", "nb d'appels à Koné hier", "nombre d'appels hier",
                                    "Appels et SMS à Lifou hier"])
def test_appels_complets(ctx, phrase):  # noqa: F811
    i = interpreter(phrase, J, ctx)
    attendus = existants("wcdma_appels_voix", "wcdma_speech_traffic", "wcdma_duree_appel", "lte_csfb_appels")
    assert i.params["kpis"][:len(attendus)] == attendus and not i.non_compris


def test_volume_data_reste_du_trafic(ctx):  # noqa: F811
    assert interpreter("volume data 4G hier", J, ctx).params["kpis"] == ["lte_payload_dl"]
    assert interpreter("drop 4G et volume data hier", J, ctx).params["kpis"] == ["lte_erab_drop", "lte_payload_dl"]


@pytest.mark.parametrize("phrase,debut,fin", [
    ("drop 4G semaine 38", date(2026, 9, 14), date(2026, 9, 20)),
    ("drop 4G en semaine 2", date(2026, 1, 5), date(2026, 1, 11)),
    ("drop 4G semaine 50", date(2025, 12, 8), date(2025, 12, 14)),  # à venir : année précédente
    ("drop 4G S38 2025", date(2025, 9, 15), date(2025, 9, 21)),
])
def test_semaine_iso(ctx, phrase, debut, fin):  # noqa: F811
    p = interpreter(phrase, J, ctx).params["periode"]
    assert (p["debut"], p["fin"]) == (debut, fin)


# ------------------------------------------------------------------ lieux approchés (M2)

@pytest.mark.parametrize("phrase,texte,options", [
    ("drop 4G à Nouméaa hier", "Nouméaa", ["Nouméa", "Tout le réseau"]),
    ("drop 4G Koumak hier", "Koumak", ["Koumac", "Tout le réseau"]),
    ("débit 4G Pita hier", "Pita", ["Païta", "Tout le réseau"]),
    ("drop 4G agence telecomm hier", "agence telecomm", ["AGENCE_TELECOM (NOU001)", "Tout le réseau"]),
])
def test_lieu_mal_orthographie(ctx, phrase, texte, options):  # noqa: F811
    i = interpreter(phrase, J, ctx)
    assert "perimetre" not in i.params and not i.complete
    q = i.questions[0]
    assert q.champ == "perimetre" and q.texte == f"Lieu non reconnu : « {texte} ». Vouliez-vous dire… ?"
    assert [o.libelle for o in q.options] == options
    assert q.options[-1].params == {"perimetre_type": "global", "perimetre_valeurs": ""}


def test_lieu_approche_avec_un_autre_lieu(ctx, rf):  # noqa: F811
    i = interpreter("drop 4G Nouméa et Pitaa hier", J, ctx)
    q = i.questions[0]
    assert [o.libelle for o in q.options] == ["Païta", "Ignorer « Pitaa »"]
    assert q.options[0].params == {"perimetre_type": "commune", "perimetre_valeurs": "NOUMEA, PAITA"}
    assert q.options[1].params == {"perimetre_type": "commune", "perimetre_valeurs": "NOUMEA"}
    i = avec_parametres(i, rf.get("/", q.options[0].params).GET, ctx, J)
    assert i.complete and i.params["perimetre"]["valeurs"] == ["NOUMEA", "PAITA"]


def test_mot_generique_d_evenement(ctx):  # noqa: F811
    i = interpreter("drop 4G foire hier", J, ctx)
    q = i.questions[0]
    assert q.champ == "perimetre" and [o.libelle for o in q.options] == [
        "Foire de Koumac", "Foire de Ponerihouen", "Foire de Ponérihouen"]


def test_lieu_inconnu_place_comme_un_lieu(ctx):  # noqa: F811
    i = interpreter("drop 4G à Zorglub hier", J, ctx)
    q = i.questions[0]
    assert q.texte.startswith("Lieu non reconnu : « Zorglub »") and [o.libelle for o in q.options] == ["Tout le réseau"]
    assert q.saisie == "texte"


@pytest.mark.parametrize("phrase", ["drop 4G hier par site", "débit 4G sur le réseau hier", "drop 3G partout hier",
                                    "drop 4G hier", "taux de coupure voix hier"])
def test_pas_de_faux_positif(ctx, phrase):  # noqa: F811
    i = interpreter(phrase, J, ctx)
    assert i.complete and i.params["perimetre"] == {"type": "global", "valeurs": []}


def test_mots_inconnus_ordinaires_restent_non_compris(ctx):  # noqa: F811
    i = interpreter("blablabla zorglub", J, ctx)
    assert i.non_compris == ["blablabla", "zorglub"] and all(q.champ != "perimetre" for q in i.questions)


def test_approche_dans_le_perimetre_seulement(ref_recherche):  # noqa: F811
    lecteur = User.objects.create_user("lec")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"]).utilisateurs.add(lecteur)
    ctx = Contexte.pour(lecteur)
    q = interpreter("drop 4G à Koumak hier", J, ctx).questions[0]
    assert [o.libelle for o in q.options] == ["Tout le réseau"]  # Koumac hors périmètre : jamais proposé
    q = interpreter("drop 4G à Pita hier", J, ctx).questions[0]
    assert [o.libelle for o in q.options] == ["Païta", "Tout le réseau"]
