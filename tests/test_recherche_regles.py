"""Recherche en langage libre, interprétation par règles : phrases -> interprétation attendue.

Référentiel synthétique, date figée au jeudi 8 octobre 2026.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import yaml
from django.conf import settings
from django.contrib.auth.models import User

from apps.comptes.models import Perimetre
from apps.evenements.models import Creneau, Evenement
from apps.kpi.catalogue import catalogue_yaml
from apps.kpi.recherche import Contexte, avec_parametres
from apps.kpi.recherche.regles import interpreter
from apps.kpi.recherche.texte import normaliser
from apps.referentiel.models import Cellule, Secteur, Site

pytestmark = pytest.mark.django_db

J = date(2026, 10, 8)  # jeudi
SITES = [  # code, trigramme, nom, commune, région
    ("NOU001", "NOU", "AGENCE_TELECOM", "NOUMEA", "NEA"),
    ("NOU002", "NOV", "BAIE_DES_CITRONS", "NOUMEA", "NEA"),
    ("MER001", "MER", "PLAGE_MER", "NOUMEA", "NEA"),
    ("PAI001", "PAI", "MAIRIE_PAITA", "PAITA", "GRD NEA 1"),
    ("DUM001", "DUM", "DUMBEA_MAIRIE", "DUMBEA", "GRD NEA 1"),
    ("CHT801", "CHT", "CHTe", "DUMBEA", "GRD NEA 1"),
    ("CHT802", "CHT", "CHT_1", "DUMBEA", "GRD NEA 1"),
    ("CHT803", "CHT", "CHT_2", "DUMBEA", "GRD NEA 1"),
    ("MDO001", "MDO", "BOULARI", "MONT DORE", "GRD NEA 1"),
    ("KON001", "KON", "KONE_CENTRE", "KONE", "NORD"),
    ("KOU001", "KMC", "KOUMAC_VILLAGE", "KOUMAC", "NORD"),
    ("PON001", "PNH", "PONERIHOUEN", "PONERIHOUEN", "NORD"),
    ("KAA001", "KGM", "KAALA_BT", "KAALA GOMEN", "NORD"),
    ("LIF001", "LIF", "CHEPENEHE", "LIFOU", "ILES"),
    ("MAR001", "MRE", "TADINE", "MARE", "ILES"),
    ("IDP001", "IDP", "KUTO", "ILE DES PINS", "SUD"),
    ("FOA001", "FOA", "LA_FOA_VILLAGE", "LA FOA", "SUD"),
]


@pytest.fixture
def ref_recherche():
    for code, trig, nom, commune, region in SITES:
        site = Site.objects.create(code_site=code, trigramme=trig, nom=nom, commune=commune, region=region)
        for n in (1, 2):
            secteur = Secteur.objects.create(code=f"{code}{n}", site=site, numero=n)
            Cellule.objects.create(nom=f"{code}L{n}", techno="LTE", secteur=secteur)
            Cellule.objects.create(nom=f"{code}{'AB'[n - 1]}", techno="WCDMA", secteur=secteur)
    Evenement.objects.create(nom="Foire de Ponerihouen", sites=["PON001"])
    Evenement.objects.create(nom="Foire de Ponérihouen", sites=["PON001"])
    Evenement.objects.create(nom="Foire de Koumac", sites=["KOU001"])
    carnaval = Evenement.objects.create(nom="Carnaval de Nouméa", sites=["NOU001"])
    tz = ZoneInfo(settings.TIME_ZONE)
    Creneau.objects.create(evenement=carnaval, debut=datetime(2026, 8, 15, 18, tzinfo=tz),
                           fin=datetime(2026, 8, 15, 23, tzinfo=tz))


@pytest.fixture
def ctx(ref_recherche):
    return Contexte.pour(None)


def existants(*codes):
    """Codes présents dans le catalogue (un code ajouté plus tard au YAML reste optionnel)."""
    cat = catalogue_yaml()
    return [c for c in codes if c in cat]


def causes(parent):
    return [c for c, k in catalogue_yaml().items() if k.decomposition_de == parent]


def d(texte):
    jour, mois, *annee = texte.split("/")
    return date(int(annee[0]) if annee else 2026, int(mois), int(jour))


# (phrase, attendu) — seules les clés indiquées sont vérifiées.
#   techno, kpis (liste exacte), kpis_inclus, perimetre (type, valeurs), periode (début, fin),
#   gt / ge (granularités), fenetre, questions (champs), non_compris, note (extrait d'une note)
CAS = [
    ("Drop 3G à Nouméa la semaine dernière",
     dict(techno=["WCDMA"], kpis=["wcdma_cs_drop", "wcdma_ps_drop"], perimetre=("commune", ["NOUMEA"]),
          periode=("28/09", "04/10"), gt="jour", ge="global", questions=[])),
    ("Taux d'accès 4G à Païta en septembre",
     dict(techno=["LTE"], kpis=["lte_acces"], perimetre=("commune", ["PAITA"]), periode=("01/09", "30/09"),
          gt="jour", questions=[])),
    ("Causes de coupure 4G à Koné hier",
     dict(techno=["LTE"], kpis=["lte_erab_drop", *causes("lte_erab_drop")], perimetre=("commune", ["KONE"]),
          periode=("07/10", "07/10"), gt="heure", questions=[])),
    ("Appels et SMS à Lifou ce mois-ci",
     dict(techno=["WCDMA", "LTE"], kpis=existants("wcdma_appels_voix", "wcdma_speech_traffic", "wcdma_duree_appel",
                                                 "lte_csfb_appels",
                                                 "wcdma_sms"),
          perimetre=("commune", ["LIFOU"]), periode=("01/10", "08/10"), questions=[])),
    ("Débit 4G par site à Dumbéa les 7 derniers jours",
     dict(techno=["LTE"], kpis=["lte_dl_user_thp"], perimetre=("commune", ["DUMBEA"]), periode=("01/10", "07/10"),
          gt="jour", ge="site", questions=[])),
    ("débit 4G CHT", dict(kpis=["lte_dl_user_thp"], questions=["perimetre", "periode"])),
    ("taux d'accès 4G Païta", dict(kpis=["lte_acces"], perimetre=("commune", ["PAITA"]), questions=["periode"])),
    ("blabla truc", dict(questions=["kpis", "periode"], non_compris=["blabla", "truc"],
                         perimetre=("global", []))),
    ("foire de ponérihouen", dict(questions=["perimetre", "kpis", "periode"])),
    ("Causes des drops 3G à Maré le mois dernier",
     dict(techno=["WCDMA"], kpis=["wcdma_cs_drop", *causes("wcdma_cs_drop")], perimetre=("commune", ["MARE"]),
          periode=("01/09", "30/09"))),
    ("drop data 3G Mont-Dore hier",
     dict(kpis=["wcdma_ps_drop"], perimetre=("commune", ["MONT DORE"]), periode=("07/10", "07/10"))),
    ("appels coupés à l'île des pins avant-hier",
     dict(techno=["WCDMA"], kpis=["wcdma_cs_drop"], perimetre=("commune", ["ILE DES PINS"]),
          periode=("06/10", "06/10"))),
    ("congestion le soir à La Foa du 1er au 15 septembre",
     dict(kpis=["lte_prb_dl_util"], perimetre=("commune", ["LA FOA"]), fenetre="18-22", periode=("01/09", "15/09"),
          gt="jour")),
    ("disponibilité réseau 3G aujourd'hui",
     dict(kpis=["wcdma_cell_availability"], perimetre=("global", []), periode=("08/10", "08/10"), gt="heure",
          questions=[])),
    ("pires sites drop 4G nord la semaine dernière",
     dict(kpis=["lte_erab_drop"], ge="site", perimetre=("commune", ["KAALA GOMEN", "KONE", "KOUMAC", "PONERIHOUEN"]))),
    ("handover 4G Kaala-Gomen 18h-22h hier",
     dict(kpis=["lte_ho_intra_sr"], perimetre=("commune", ["KAALA GOMEN"]), fenetre="18-22", non_compris=[])),
    ("drop 4G heure chargée Koumac hier",
     dict(kpis=["lte_erab_drop"], fenetre="journee", note="heure chargée", questions=[])),
    ("volume data 4G par semaine les 3 derniers mois",
     dict(kpis=["lte_payload_dl"], gt="semaine", perimetre=("global", []), periode=("10/07", "07/10"))),
    ("SMS 4G hier", dict(questions=["kpis"], note="SMS")),
    ("trafic voix 3G à Nouméa le 14/09",
     dict(kpis=["wcdma_speech_traffic"], periode=("14/09", "14/09"), gt="heure")),
    ("débit 4G le 14 septembre 2025 à Koné", dict(periode=("14/09/2025", "14/09/2025"))),
    ("drop du 01/09 au 15/09 à Païta",
     dict(techno=["LTE", "WCDMA"], kpis=["lte_erab_drop", "wcdma_cs_drop", "wcdma_ps_drop"],
          periode=("01/09", "15/09"))),
    ("accès data 3G Lifou cette semaine",
     dict(kpis=["wcdma_cssr_ps"], perimetre=("commune", ["LIFOU"]), periode=("05/10", "08/10"))),
    ("échec d'appel Nouméa hier", dict(techno=["WCDMA"], kpis=["wcdma_cssr_cs"])),
    ("débit 4G par heure Païta mois dernier", dict(gt="heure", periode=("01/09", "30/09"))),
    ("débit 4G journalier à Païta en 2025", dict(gt="jour", periode=("01/01/2025", "31/12/2025"))),
    ("trafic 4G Nouméa mensuel cette année", dict(gt="mois", periode=("01/01", "08/10"))),
    ("drop 4G le week-end du 14 septembre à Dumbéa", dict(periode=("12/09", "13/09"), gt="heure")),
    ("drop 4G en juillet", dict(periode=("01/07", "31/07"), perimetre=("global", []))),
    ("drop 4G en novembre", dict(periode=("01/11/2025", "30/11/2025"), gt="jour")),
    ("débit 4G sur la cellule NOU001L1 hier", dict(perimetre=("cellule", ["NOU001L1"]))),
    ("drop 4G secteur NOU0012 hier", dict(perimetre=("secteur", ["NOU0012"]))),
    ("drop 3G site PAI001 hier", dict(perimetre=("site", ["PAI001"]), techno=["WCDMA"])),
    ("débit 4G agence telecom hier", dict(perimetre=("site", ["NOU001"]))),
    ("drop 4G Grand Nouméa hier",
     dict(perimetre=("commune", ["DUMBEA", "MONT DORE", "NOUMEA", "PAITA"]))),
    ("drop 4G au carnaval", dict(perimetre=("evenement", ["Carnaval de Nouméa"]), periode=("15/08", "15/08"),
                                 gt="heure", questions=[])),
    ("débit 4G Nouméa et Païta hier", dict(perimetre=("commune", ["NOUMEA", "PAITA"]))),
    ("débit 4G Païta et site NOU002 hier", dict(perimetre=("site", ["PAI001", "NOU002"]))),
    ("top 10 cellules drop 4G Nouméa hier", dict(ge="cellule", kpis=["lte_erab_drop"])),
    ("drop 4G partout hier", dict(perimetre=("global", []), questions=[])),
    ("drop 4G entre 7h et 20h hier", dict(fenetre="7-20")),
    ("débit ul 4G Nouméa hier", dict(kpis=["lte_ul_user_thp"])),
    ("erlang 3G Koné la semaine dernière", dict(kpis=["wcdma_speech_traffic"], periode=("28/09", "04/10"))),
    ("pourquoi ça coupe à Koné en 4G hier", dict(kpis=["lte_erab_drop", *causes("lte_erab_drop")])),
    ("drop 4G Nouméa hier par commune", dict(ge="commune", gt="heure")),
    ("drop umts Nouméa hier", dict(techno=["WCDMA"])),
    ("drop lte Nouméa hier", dict(techno=["LTE"], kpis=["lte_erab_drop"])),
    ("débit 4G Nouméa du 28 septembre au 3 octobre", dict(periode=("28/09", "03/10"))),
    ("drop 4G Nouméa 2026-09-14", dict(periode=("14/09", "14/09"))),
    ("drop 4G Nouméa le 30 février", dict(questions=["periode"], note="non valide")),
    ("drop 4G mer hier", dict(perimetre=("global", []), non_compris=["mer"])),
    ("drop 4G MER hier", dict(perimetre=("site", ["MER001"]))),
    ("drop 4G pendant la foire à Koumac hier", dict(perimetre=("evenement", ["Foire de Koumac"]))),
    ("Foire de Koumac débit 4G", dict(perimetre=("evenement", ["Foire de Koumac"]), questions=["periode"])),
    ("congestion Nouméa hier en soirée", dict(techno=["LTE"], fenetre="18-22")),
    # Lieu inconnu du référentiel : question (jamais de repli silencieux sur tout le réseau).
    ("dispo des sites à Thio hier", dict(kpis=["lte_cell_availability", "wcdma_cell_availability"],
                                         non_compris=[], questions=["perimetre"])),
]


@pytest.mark.parametrize("phrase,attendu", CAS, ids=[c[0] for c in CAS])
def test_phrases(ctx, phrase, attendu):
    i = interpreter(phrase, J, ctx)
    p = i.params
    if "techno" in attendu:
        assert p.get("techno") == attendu["techno"]
    if "kpis" in attendu:
        assert p.get("kpis") == attendu["kpis"]
    if "perimetre" in attendu:
        type_, valeurs = attendu["perimetre"]
        assert p["perimetre"]["type"] == type_
        assert sorted(p["perimetre"]["valeurs"]) == sorted(valeurs)
    if "periode" in attendu:
        assert (p["periode"]["debut"], p["periode"]["fin"]) == tuple(d(x) for x in attendu["periode"])
    if "gt" in attendu:
        assert p.get("granularite_temps") == attendu["gt"]
    if "ge" in attendu:
        assert p.get("granularite_espace") == attendu["ge"]
    if "fenetre" in attendu:
        assert p.get("fenetre_horaire") == attendu["fenetre"]
    if "questions" in attendu:
        assert [q.champ for q in i.questions] == attendu["questions"]
        assert i.complete == (not attendu["questions"])
    if "non_compris" in attendu:
        assert i.non_compris == attendu["non_compris"]
    if "note" in attendu:
        assert any(attendu["note"] in n for n in i.notes), i.notes
    assert i.source == "regles"


def test_au_moins_quarante_phrases():
    assert len(CAS) >= 40


def test_ambiguite_trigramme(ctx):
    i = interpreter("débit 4G CHT hier", J, ctx)
    q = i.questions[0]
    assert q.champ == "perimetre" and "CHT" in q.texte
    assert [o.params for o in q.options] == [
        {"perimetre_type": "site", "perimetre_valeurs": "CHT801"},
        {"perimetre_type": "site", "perimetre_valeurs": "CHT802"},
        {"perimetre_type": "site", "perimetre_valeurs": "CHT803"},
        {"perimetre_type": "trigramme", "perimetre_valeurs": "CHT"},
    ]
    assert "Dumbéa" in q.options[0].detail


def test_reponse_a_une_question_par_parametre(ctx, rf):
    i = interpreter("taux d'accès 4G Païta", J, ctx)
    assert not i.complete
    option = next(o for o in i.questions[0].options if o.libelle == "7 derniers jours")
    i = avec_parametres(i, rf.get("/", option.params).GET, ctx, J)
    assert i.complete and i.params["periode"] == {"debut": date(2026, 10, 1), "fin": date(2026, 10, 7)}
    assert i.params["granularite_temps"] == "jour"  # défaut recalculé sur la nouvelle période


def test_parametres_explicites_priment(ctx, rf):
    i = interpreter("drop 3G à Nouméa la semaine dernière", J, ctx)
    get = rf.get("/", {"techno": "LTE", "debut": "2026-09-01", "fin": "2026-09-02", "perimetre_type": "commune",
                       "perimetre_valeurs": "paita", "granularite_espace": "site"}).GET
    i = avec_parametres(i, get, ctx, J)
    assert i.params["techno"] == ["LTE"] and i.params["kpis"] == ["lte_erab_drop"]  # intention gardée
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["PAITA"]}
    assert i.params["periode"] == {"debut": date(2026, 9, 1), "fin": date(2026, 9, 2)}
    assert i.params["granularite_temps"] == "heure" and i.params["granularite_espace"] == "site"
    i = avec_parametres(i, rf.get("/", {"kpis": ["wcdma_sms", "inconnu"]}).GET, ctx, J)
    assert i.params["kpis"] == ["wcdma_sms"] and i.params["techno"] == ["WCDMA"]


def test_option_kpi_par_famille(ctx, rf):
    i = interpreter("Nouméa hier", J, ctx)
    q = next(q for q in i.questions if q.champ == "kpis")
    assert [o.libelle for o in q.options] == ["Bilan complet", "Drop", "Taux d'accès", "Débit", "Trafic data", "Appels",
                                              "SMS", "Disponibilité", "Congestion", "Utilisateurs connectés"]
    i = avec_parametres(i, rf.get("/", q.options[1].params).GET, ctx, J)
    assert i.complete and i.params["kpis"] == ["lte_erab_drop", "wcdma_cs_drop", "wcdma_ps_drop"]


def test_puces(ctx):
    i = interpreter("Causes de coupure 4G à Koné hier", J, ctx)
    puces = {p.champ: p for p in i.compris}
    assert puces["techno"].libelle == "4G"
    assert puces["kpis"].libelle.startswith("Drop") and "causes" in puces["kpis"].libelle
    assert puces["perimetre"].libelle == "Koné"
    assert puces["periode"].libelle == "Hier · 07/10/2026"
    assert puces["granularite_temps"].libelle == "par heure" and puces["granularite_temps"].defaut
    i = interpreter("drop 4G hier", J, ctx)
    assert i.puce("perimetre").libelle == "Tout le réseau autorisé" and i.puce("perimetre").defaut


def test_normalisation():
    assert normaliser("L'Île-des-Pins à Nouméa, 18h-22h !") == "l ile des pins a noumea 18h-22h"
    assert normaliser("Mont-Dore — avant-hier") == "mont dore avant hier"


def test_lecteur_restreint_sans_fuite_de_lieux(ref_recherche):
    lecteur = User.objects.create_user("lec")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"]).utilisateurs.add(lecteur)
    ctx = Contexte.pour(lecteur)
    assert ctx.lieux.communes_visibles == ["PAITA"]
    # Lieu hors périmètre : question, jamais de calcul silencieux sur le périmètre (tour 3, R4),
    # et même message qu'un lieu inexistant : rien n'est révélé.
    for phrase, texte in [("drop 4G à Nouméa hier", "Nouméa"), ("débit 4G CHT hier", "CHT"),
                          ("débit 4G à Koumak hier", "Koumak"), ("drop 4G à agence telecom hier", "agence"),
                          ("drop 4G à Zorglub hier", "Zorglub"), ("drop 4G au carnaval hier", "carnaval")]:
        i = interpreter(phrase, J, ctx)
        q = next(q for q in i.questions if q.champ == "perimetre")
        assert q.texte == f"« {texte} » n'est pas dans votre périmètre.", phrase
        assert [o.libelle for o in q.options] == ["Voir mon périmètre (Païta)"], phrase
        assert "perimetre" not in i.params and not i.complete
    assert {s["valeur"] for s in ctx.lieux.suggestions("")} == {"PAITA"}
    assert ctx.lieux.suggestions("cht") == []
    assert interpreter("drop 4G site PAI001 hier", J, ctx).params["perimetre"] == {"type": "site", "valeurs": ["PAI001"]}


def test_vocabulaire_sans_causes_en_dur():
    """Les causes viennent du catalogue (decomposition_de), jamais du vocabulaire."""
    with open(settings.RECHERCHE_VOCABULAIRE_PATH, encoding="utf-8") as f:
        voc = yaml.safe_load(f)
    cat = catalogue_yaml()
    optionnels = {"wcdma_duree_appel"}  # ajouté au catalogue par ailleurs
    for intention in voc["intentions"].values():
        for codes in intention["kpis"].values():
            for code in codes:
                assert code in cat or code in optionnels, code
                assert code not in cat or not cat[code].decomposition_de, code
