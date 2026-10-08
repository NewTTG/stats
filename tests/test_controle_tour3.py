"""Non-régression du contrôle indépendant (tour 3) : vocabulaire technique (S1, RRC,
E-RAB, PRB), technos implicites, sigles jamais pris pour un lieu, jours de la semaine,
« depuis », périmètre restreint, niveau de comparaison, affichage mobile."""

import re
from datetime import date

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import Perimetre
from apps.evenements.models import Evenement
from apps.kpi.recherche import Contexte, avec_parametres
from apps.kpi.recherche import lieux as module_lieux
from apps.kpi.recherche.dates import jour_passe
from apps.kpi.recherche.regles import interpreter
from apps.kpi.recherche.texte import Texte
from apps.referentiel.models import Cellule, Secteur, Site

from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixture)
from .test_recherche_vues import base_recherche  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

SITES_T3 = [  # code, trigramme, nom, nom 3G, nom 4G, commune, région
    ("VOH001", "VOH", "VOH_VILLAGE", "", "", "VOH", "NORD"),
    ("POM001", "POM", "POUM_VILLAGE", "", "", "POUM", "NORD"),
    ("POI001", "POI", "POINDIMIE_CENTRE", "", "", "POINDIMIE", "NORD"),
    ("PUE001", "PUE", "POUEBO_VILLAGE", "", "", "POUEBO", "NORD"),
    ("KON552", "KON", "KONE", "KONE", "KONEe", "KONE", "NORD"),
    ("ACR584", "ACR", "GREEN_ACRE_BT", "POUEMBOUTbb", "POUEMBOUTbb", "KONE", "NORD"),
    ("PIM123", "PIM", "PIC_MARTIN", "PIC_MARTIN", "PIC_MARTINbb", "PAITA", "GRD NEA 1"),
    ("TEN471", "TEN", "TENE", "", "", "BOURAIL", "SUD"),
    ("PPA555", "PPA", "PIC_310", "PIC310_PAOUTA", "PIC310_PAOUTAe", "POUEMBOUT", "NORD"),
]


@pytest.fixture
def ref_t3(ref_recherche):  # noqa: F811
    for code, trig, nom, nom_wcdma, nom_lte, commune, region in SITES_T3:
        site = Site.objects.create(code_site=code, trigramme=trig, nom=nom, nom_wcdma=nom_wcdma, nom_lte=nom_lte,
                                   commune=commune, region=region)
        for n in (1, 2):
            secteur = Secteur.objects.create(code=f"{code}{n}", site=site, numero=n)
            Cellule.objects.create(nom=f"{code}L{n}", techno="LTE", secteur=secteur)
            Cellule.objects.create(nom=f"{code}{'AB'[n - 1]}", techno="WCDMA", secteur=secteur)
    Evenement.objects.create(nom="Foire de Bourail", sites=["TEN471"])
    Evenement.objects.create(nom="Foire de Pouembout", sites=["ACR584"])


@pytest.fixture
def ctx3(ref_t3):
    return Contexte.pour(None)


def _periode(i):
    p = i.params.get("periode")
    return (p["debut"], p["fin"]) if p else None


# ------------------------------------------------------------------ R1 : S1, RRC, E-RAB, PRB, semaine ISO

def test_s1_est_l_interface_pas_la_semaine_1(ctx3):
    i = interpreter("taux de succès S1 4G Voh hier", J, ctx3)
    assert i.params["kpis"] == ["lte_s1_sig_sr"] and i.params["techno"] == ["LTE"]
    assert _periode(i) == (date(2026, 10, 7), date(2026, 10, 7))
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["VOH"]}
    assert i.non_compris == [] and i.complete
    # Sans techno : S1 implique la 4G.
    i = interpreter("signalisation S1 Voh hier", J, ctx3)
    assert i.params["kpis"] == ["lte_s1_sig_sr"] and i.non_compris == []


@pytest.mark.parametrize("phrase", ["drop 4G Nouméa semaine 38", "drop 4G Nouméa sem. 38", "drop 4G Nouméa sem 38",
                                    "drop 4G Nouméa la semaine 38"])
def test_semaine_iso_ecrite(ctx3, phrase):
    assert _periode(interpreter(phrase, J, ctx3)) == (date(2026, 9, 14), date(2026, 9, 20))


@pytest.mark.parametrize("phrase", ["drop 4G Nouméa S38", "drop 4G Nouméa s1"])
def test_s_suivi_d_un_nombre_n_est_pas_une_semaine(ctx3, phrase):
    i = interpreter(phrase, J, ctx3)
    assert _periode(i) is None and any(q.champ == "periode" for q in i.questions)


def test_succes_rrc(ctx3):
    i = interpreter("succès RRC 3G Poindimié hier", J, ctx3)
    assert i.params["kpis"] == ["wcdma_rrc_cs_sr", "wcdma_rrc_ps_sr"] and i.non_compris == []
    i = interpreter("taux de succès RRC 4G Koné hier", J, ctx3)
    assert i.params["kpis"] == ["lte_rrc_setup_sr"] and i.non_compris == []


def test_succes_seul_n_est_pas_incompris(ctx3):
    i = interpreter("taux de succès 4G Koné hier", J, ctx3)
    assert i.non_compris == [] and [q.champ for q in i.questions] == ["kpis"]


def test_drop_e_rab_par_secteur_en_4g_seulement(ctx3):
    i = interpreter("drop E-RAB par secteur au site KON552 hier", J, ctx3)
    assert i.params["techno"] == ["LTE"] and i.params["kpis"] == ["lte_erab_drop"]
    assert i.params["granularite_espace"] == "secteur"
    assert i.params["perimetre"] == {"type": "site", "valeurs": ["KON552"]}
    assert i.non_compris == [] and i.complete
    i = interpreter("drop erab Koné hier", J, ctx3)
    assert i.params["kpis"] == ["lte_erab_drop"]
    i = interpreter("taux de succès E-RAB Koné hier", J, ctx3)
    assert i.params["kpis"] == ["lte_init_erab_sr"] and i.non_compris == []


def test_prb_dl_heure_chargee_congestion_4g_seule(ctx3):
    i = interpreter("PRB DL heure chargée Nouméa hier", J, ctx3)
    assert i.params["kpis"] == ["lte_prb_dl_util"] and i.params["techno"] == ["LTE"]
    assert i.non_compris == []


@pytest.mark.parametrize("phrase,technos", [
    ("CSSR Koné hier", ["WCDMA"]),
    ("taux d'accès HSUPA Koné hier", ["WCDMA"]),
    ("taux d'accès RAB Koné hier", ["WCDMA"]),
    ("erlang Koné hier", ["WCDMA"]),
    ("taux d'accès E-RAB Koné hier", ["LTE"]),
    ("appels CSFB Koné hier", ["LTE"]),
    ("congestion PRB Koné hier", ["LTE"]),
    ("taux d'accès CQI Koné hier", ["LTE"]),
    ("drop E-RAB 3G Koné hier", ["WCDMA"]),  # techno explicite prioritaire
])
def test_technos_implicites(ctx3, phrase, technos):
    i = interpreter(phrase, J, ctx3)
    assert i.params["techno"] == technos, i.params
    assert i.non_compris == []


# ------------------------------------------------------------------ R3 : sigles jamais pris pour un lieu

SIGLES = ["HSDPA", "HSUPA", "HSPA", "CSSR", "RRC", "RAB", "PRB", "CQI", "CSFB", "VoLTE", "E-RAB", "ERAB", "S1", "KPI",
          "DL", "UL", "LTE", "WCDMA", "UMTS", "SMS", "Erlang", "MME", "eNB", "RNC", "HO", "IRAT"]


@pytest.mark.parametrize("sigle", SIGLES)
def test_sigle_jamais_un_lieu(ctx3, sigle):
    i = interpreter(f"débit 3G {sigle} La Foa hier", J, ctx3)
    assert not any(q.champ == "perimetre" for q in i.questions), [q.texte for q in i.questions]
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["LA FOA"]}
    assert sigle not in i.non_compris
    lieux, ambiguites, _notes = ctx3.lieux.resoudre(Texte(sigle))  # chemin IA : lieu renvoyé tel quel
    assert lieux == [] and ambiguites == []


def test_debit_3g_hsdpa_samedi_dernier(ctx3):
    i = interpreter("débit 3G HSDPA La Foa samedi dernier", J, ctx3)
    assert i.complete and i.non_compris == [] and i.notes == []
    assert i.params["kpis"] == ["wcdma_hs_user_thp"]
    assert _periode(i) == (date(2026, 10, 3), date(2026, 10, 3))


# ------------------------------------------------------------------ R2 : jours de la semaine, « depuis », week-end

@pytest.mark.parametrize("phrase,attendu", [
    ("drop 4G Koné samedi dernier", date(2026, 10, 3)),  # samedi de cette semaine pas encore passé
    ("drop 4G Koné samedi", date(2026, 10, 3)),
    ("drop 4G Koné jeudi", date(2026, 10, 1)),  # jamais aujourd'hui (jeudi 8)
    ("drop 4G Koné jeudi dernier", date(2026, 10, 1)),
    ("drop 4G Koné mardi", date(2026, 10, 6)),
    ("drop 4G Koné mardi dernier", date(2026, 10, 6)),
    ("drop 4G Koné lundi dernier", date(2026, 10, 5)),
    ("drop 4G Koné le vendredi", date(2026, 10, 2)),
    ("drop 4G Koné dimanche passé", date(2026, 10, 4)),
    ("drop 4G Koné lundi 14 septembre", date(2026, 9, 14)),
])
def test_jours_de_la_semaine(ctx3, phrase, attendu):
    i = interpreter(phrase, J, ctx3)
    assert _periode(i) == (attendu, attendu)
    assert i.non_compris == [] and i.params["granularite_temps"] == "heure"


def test_jour_passe_jamais_aujourd_hui_ni_futur():
    for n in range(14):
        aujourdhui = date(2026, 10, 1 + n)
        for jour in range(7):
            d = jour_passe(jour, aujourdhui)
            assert d.weekday() == jour and 1 <= (aujourdhui - d).days <= 7


@pytest.mark.parametrize("phrase,debut,gt", [
    ("évolution mensuelle du débit 4G Nouméa depuis septembre", date(2026, 9, 1), "mois"),
    ("drop 4G Koné depuis le 15/09", date(2026, 9, 15), "jour"),
    ("drop 4G Koné depuis le 15 septembre", date(2026, 9, 15), "jour"),
    ("drop 4G Koné depuis lundi", date(2026, 10, 5), "jour"),
    ("drop 4G Koné depuis le 1er", date(2026, 10, 1), "jour"),
    ("drop 4G Koné depuis 2025", date(2025, 1, 1), "mois"),
])
def test_depuis_jusqu_a_hier(ctx3, phrase, debut, gt):
    i = interpreter(phrase, J, ctx3)
    assert _periode(i) == (debut, date(2026, 10, 7))
    assert i.params["granularite_temps"] == gt and i.non_compris == []
    assert i.puce("periode").libelle.startswith("Depuis ")


@pytest.mark.parametrize("phrase", ["drop 4G Koné ce week-end", "drop 4G Koné le week-end dernier",
                                    "drop 4G Koné le dernier week-end", "drop 4G Koné ce weekend"])
def test_week_end(ctx3, phrase):
    assert _periode(interpreter(phrase, J, ctx3)) == (date(2026, 10, 3), date(2026, 10, 4))


def test_week_end_dernier_un_dimanche(ctx3):
    dimanche = date(2026, 10, 11)
    assert _periode(interpreter("drop 4G Koné ce week-end", dimanche, ctx3)) == (date(2026, 10, 10), dimanche)
    assert _periode(interpreter("drop 4G Koné le week-end dernier", dimanche, ctx3)) == (
        date(2026, 10, 3), date(2026, 10, 4))


# ------------------------------------------------------------------ mineur : comparaison -> par commune

@pytest.mark.parametrize("phrase,niveau", [
    ("comparaison drop 3G Koumac et Poum hier", "commune"),
    ("comparer le drop 3G de Koumac et Poum hier", "commune"),
    ("drop 3G Koumac vs Poum hier", "commune"),
    ("drop 3G Koumac et Poum hier", "commune"),  # plusieurs communes citées
    ("comparaison drop 4G Province Nord hier", "commune"),
    ("comparer drop 4G KON552 et ACR584 hier", "site"),
    ("comparaison drop 3G Koumac et Poum par site hier", "site"),  # niveau explicite prioritaire
    ("drop 3G Koumac hier", "global"),
])
def test_comparaison_par_commune(ctx3, phrase, niveau):
    i = interpreter(phrase, J, ctx3)
    assert i.params["granularite_espace"] == niveau
    assert i.non_compris == []


# ------------------------------------------------------------------ R4 : lieu hors périmètre (lecteur restreint)

@pytest.fixture
def lecteur_kone(ref_t3):
    lecteur = User.objects.create_user("lecteur_kone")
    Perimetre.objects.create(nom="Koné", communes=["KONE"]).utilisateurs.add(lecteur)
    return lecteur


@pytest.fixture
def ctx_lecteur(lecteur_kone):
    return Contexte.pour(lecteur_kone)


def _question_lieu(i):
    return next((q for q in i.questions if q.champ == "perimetre"), None)


@pytest.mark.parametrize("phrase,texte", [
    ("drop 4G au CHT hier", "CHT"),  # trigramme hors périmètre
    ("débit 4G CHT hier", "CHT"),
    ("carnaval drop 4G hier", "carnaval"),  # mot d'événement hors périmètre
    ("débit 4G PIM123 hier", "PIM123"),  # code de site hors périmètre
    ("débit 4G PIM999 hier", "PIM999"),  # code inexistant : même message
    ("drop 4G Dumbea hier", "Dumbea"),  # commune hors périmètre
    ("drop 4G à Zorglub hier", "Zorglub"),  # lieu inexistant
    ("drop 4G Foire de Bourail", "Foire de Bourail"),  # événement hors périmètre
    ("drop 4G fête de Bourail hier", "fête de Bourail"),  # pas d'événement : la commune emporte « fête de »
    ("débit 4G PIC MARTIN hier", "PIC MARTIN"),  # nom de site en deux mots
    ("débit 4G pic martin hier", "pic martin"),
    ("drop 4G Pouembou hier", "Pouembou"),  # jamais GREEN_ACRE_BT (nom 3G POUEMBOUTbb)
    ("drop 4G Nouméaa hier", "Nouméaa"),
    ("débit 3G HSDPA La Foa samedi dernier", "La Foa"),  # article du nom de commune compris
    ("drop 4G foire de La Foa hier", "foire de La Foa"),
])
def test_lecteur_lieu_demande_hors_perimetre(ctx_lecteur, phrase, texte):
    i = interpreter(phrase, J, ctx_lecteur)
    q = _question_lieu(i)
    assert q is not None, (phrase, i.params, i.notes)
    assert q.texte == f"« {texte} » n'est pas dans votre périmètre."
    assert [o.libelle for o in q.options] == ["Voir mon périmètre (Koné)"]
    assert q.options[0].params == {"perimetre_type": "global", "perimetre_valeurs": ""}
    assert "perimetre" not in i.params and not i.complete  # aucun calcul silencieux
    assert not any("PIM123" in n or "Bourail" in n for n in i.notes)


def test_lecteur_voir_mon_perimetre_puis_calcul(ctx_lecteur, rf):
    i = interpreter("drop 4G Dumbea hier", J, ctx_lecteur)
    option = _question_lieu(i).options[0]
    i = avec_parametres(i, rf.get("/", option.params).GET, ctx_lecteur, J)
    assert i.complete and i.params["perimetre"] == {"type": "global", "valeurs": []}


def test_lecteur_lieu_hors_perimetre_avec_un_lieu_autorise(ctx_lecteur):
    i = interpreter("drop 4G Koné et Dumbéa hier", J, ctx_lecteur)
    q = _question_lieu(i)
    assert q.texte == "« Dumbéa » n'est pas dans votre périmètre."
    assert [o.libelle for o in q.options] == ["Ignorer « Dumbéa »", "Voir mon périmètre (Koné)"]
    assert q.options[0].params == {"perimetre_type": "commune", "perimetre_valeurs": "KONE"}


def test_lecteur_lieux_autorises_inchanges(ctx_lecteur):
    assert interpreter("drop 4G Koné hier", J, ctx_lecteur).params["perimetre"] == {"type": "commune",
                                                                                    "valeurs": ["KONE"]}
    assert interpreter("drop 4G site KON552 hier", J, ctx_lecteur).params["perimetre"] == {
        "type": "site", "valeurs": ["KON552"]}
    assert interpreter("drop 4G Foire de Pouembout", J, ctx_lecteur).params["perimetre"] == {
        "type": "evenement", "valeurs": ["Foire de Pouembout"]}
    i = interpreter("drop 4G hier", J, ctx_lecteur)
    assert i.complete and i.params["perimetre"] == {"type": "global", "valeurs": []}


def test_foire_seule_une_seule_proposition(ctx_lecteur):
    q = _question_lieu(interpreter("débit 4G foire hier", J, ctx_lecteur))
    assert q.texte == "« foire » : vouliez-vous dire « Foire de Pouembout » ?"


def test_sans_restriction_code_inconnu_lieu_non_reconnu(ctx3):
    i = interpreter("débit 4G PIM999 hier", J, ctx3)
    q = _question_lieu(i)
    assert q.texte == "Lieu non reconnu : « PIM999 ». Précisez le lieu ou choisissez tout le réseau."
    assert [o.libelle for o in q.options] == ["Tout le réseau"]
    assert interpreter("débit 4G PIM123 hier", J, ctx3).params["perimetre"] == {"type": "site", "valeurs": ["PIM123"]}
    assert interpreter("drop 4G Foire de Bourail", J, ctx3).params["perimetre"] == {
        "type": "evenement", "valeurs": ["Foire de Bourail"]}
    for phrase in ("top10 drop 4G Nouméa hier", "drop 4G à 18h00 Nouméa hier"):  # pas des codes
        assert _question_lieu(interpreter(phrase, J, ctx3)) is None


def test_vue_lecteur_question_hors_perimetre(client, base_recherche):  # noqa: F811
    lecteur = User.objects.create_user("lec3")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"]).utilisateurs.add(lecteur)
    client.force_login(lecteur)
    for q, texte in [("drop 4G au CHT hier", "CHT"), ("carnaval drop 4G hier", "carnaval")]:
        html = client.get("/", {"q": q}).content.decode()
        assert f"« {texte} » n&#x27;est pas dans votre périmètre." in html
        assert "Voir mon périmètre (Païta)" in html and "Synthèse sur la période" not in html
        for interdit in ("CHT801", "CHT_1", "Carnaval de Nouméa", "NOU001"):
            assert interdit not in html, interdit


# ------------------------------------------------------------------ mineurs : Konee, PIC MARTIN, seuils

def test_konee_commune_ou_site(ctx3, ctx_lecteur):
    for ctx in (ctx3, ctx_lecteur):
        q = _question_lieu(interpreter("drop 4G Konee hier", J, ctx))
        assert q.texte == "Plusieurs lieux correspondent à « Konee » : lequel ?"
        assert [o.libelle for o in q.options] == ["Koné", "KONE (KON552)"]  # la commune d'abord
    assert interpreter("drop 4G Kone hier", J, ctx3).params["perimetre"] == {"type": "commune", "valeurs": ["KONE"]}


@pytest.mark.parametrize("phrase", ["débit 4G PIC MARTIN hier", "débit 4G PIC_MARTIN hier",
                                    "débit 4G pic martin hier", "débit 4G Pic Martin hier"])
def test_nom_de_site_en_plusieurs_mots(ctx3, phrase):
    i = interpreter(phrase, J, ctx3)
    assert i.params["perimetre"] == {"type": "site", "valeurs": ["PIM123"]} and i.non_compris == []


def test_approche_communes_avant_sites(ctx3):
    assert module_lieux.SEUIL_APPROCHE_SITES >= 0.85
    q = _question_lieu(interpreter("drop 4G Pouembou hier", J, ctx3))
    libelles = [o.libelle for o in q.options]
    assert libelles[0] == "Pouembout" and "GREEN_ACRE_BT (ACR584)" not in libelles


# ------------------------------------------------------------------ R5 : tableaux à 375 px

def test_css_colonne_figee_etroite_sur_petit_ecran(settings):
    css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
    bloc = re.search(r"@media \(max-width: 600px\) \{(.*?)\n\}", css, re.S)
    assert bloc, "règle ≤ 600 px absente"
    regle = bloc[1]
    assert ".table-defil table td:first-child" in regle
    assert "white-space: normal" in regle and "max-width: 40vw" in regle and "width: 6.5rem" in regle
    assert ".hors-mobile { display: none; }" in regle and ".sur-mobile { display: inline; }" in regle
    assert re.search(r"^\.sur-mobile \{ display: none; \}", css, re.M)  # caché hors petit écran


def test_tableau_detaille_entite_dans_la_colonne_figee(client, base_recherche):  # noqa: F811
    client.force_login(User.objects.create_superuser("admin3"))
    html = client.get("/", {"q": "drop 4G par site à Nouméa hier"}).content.decode()
    assert '<th scope="col">Période<span class="sur-mobile"> · entité</span></th>' in html
    assert '<th scope="col" class="hors-mobile">Entité</th>' in html
    assert re.search(r'<td>[^<]+<span class="sur-mobile entite-ligne">[^<]+</span></td><td class="hors-mobile">', html)
