"""Recherche IA (Groq, API compatible OpenAI) : appels simulés, jamais de réseau réel."""

import io
import json
import socket
import urllib.error

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import JournalAudit, Perimetre
from apps.kpi.recherche import Contexte
from apps.kpi.recherche.ia import NOTE_REPLI, interpreter

from .test_recherche_regles import J, ctx, ref_recherche  # noqa: F401  (fixtures)
from .test_recherche_vues import admin, base_recherche  # noqa: F401

pytestmark = pytest.mark.django_db

CLE_TEST = "cle-de-test"


class Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def reponse_modele(contenu) -> Reponse:
    if not isinstance(contenu, str):
        contenu = json.dumps(contenu)
    return Reponse(json.dumps({"choices": [{"message": {"role": "assistant", "content": contenu}}]}).encode())


@pytest.fixture
def groq(settings, monkeypatch):
    """Simule l'API : ``groq.reponse`` (contenu JSON du modèle) ou ``groq.erreur`` (exception)."""
    settings.GROQ_API_KEY = CLE_TEST
    settings.GROQ_MODEL = "llama-3.3-70b-versatile"
    settings.GROQ_TIMEOUT = 10

    class Faux:
        reponse = None
        erreur = None
        appels = []

        def __call__(self, requete, timeout=None):
            self.appels.append((requete, timeout))
            if self.erreur:
                raise self.erreur
            return reponse_modele(self.reponse)

    faux = Faux()
    faux.appels = []
    monkeypatch.setattr("apps.kpi.recherche.ia.urllib.request.urlopen", faux)
    return faux


SUCCES = {"techno": ["LTE"], "kpis": ["lte_erab_drop"], "perimetre": {"type": "commune", "valeurs": ["Nouméa"]},
          "periode": {"debut": "2026-09-28", "fin": "2026-10-04"}, "granularites": {"temps": None, "espace": "site"},
          "fenetre": "18-22", "manquants": []}


def test_succes(ctx, groq):  # noqa: F811
    groq.reponse = SUCCES
    i = interpreter("les coupures 4G le soir à Nouméa la semaine dernière, par site", J, ctx)
    assert i.source == "ia" and i.complete and not i.notes
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["NOUMEA"]}  # re-résolu localement
    assert i.params["kpis"] == ["lte_erab_drop"] and i.params["techno"] == ["LTE"]
    assert i.params["granularite_espace"] == "site" and i.params["granularite_temps"] == "jour"
    assert i.params["fenetre_horaire"] == "18-22"

    requete, timeout = groq.appels[0]
    assert requete.full_url == "https://api.groq.com/openai/v1/chat/completions" and timeout == 10
    assert requete.get_header("Authorization") == f"Bearer {CLE_TEST}"
    corps = json.loads(requete.data)
    assert corps["model"] == "llama-3.3-70b-versatile" and corps["temperature"] == 0
    assert corps["response_format"] == {"type": "json_object"}
    systeme, utilisateur = corps["messages"]
    systeme = systeme["content"]
    assert utilisateur == {"role": "user", "content": "les coupures 4G le soir à Nouméa la semaine dernière, par site"}
    assert "2026-10-08" in systeme and "lte_drop_radio" in systeme and "cause de lte_erab_drop" in systeme
    assert "jamais de SQL" in systeme
    assert "SELECT" not in systeme  # aucune donnée ni requête SQL envoyée


def test_question_si_periode_manquante_et_lieu_ambigu(ctx, groq):  # noqa: F811
    groq.reponse = {**SUCCES, "perimetre": {"type": "trigramme", "valeurs": ["CHT"]}, "periode": None,
                    "manquants": ["periode"]}
    i = interpreter("débit 4G CHT", J, ctx)
    assert i.source == "ia" and [q.champ for q in i.questions] == ["perimetre", "periode"]


def test_lieu_et_kpi_inventes(ctx, groq):  # noqa: F811
    groq.reponse = {**SUCCES, "kpis": ["lte_erab_drop", "kpi_invente"],
                    "perimetre": {"type": "commune", "valeurs": ["Atlantis"]}}
    i = interpreter("drop à Atlantis", J, ctx)
    assert i.params["kpis"] == ["lte_erab_drop"] and any("kpi_invente" in n for n in i.notes)
    # Lieu inventé : question (jamais de calcul silencieux sur tout le réseau).
    q = next(q for q in i.questions if q.champ == "perimetre")
    assert "« Atlantis »" in q.texte and [o.libelle for o in q.options] == ["Tout le réseau"]
    assert "perimetre" not in i.params


def test_lecteur_restreint_lieu_hors_perimetre(ref_recherche, groq):  # noqa: F811
    lecteur = User.objects.create_user("lec")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"], kpis_autorises=["lte_dl_user_thp"]).utilisateurs.add(lecteur)
    groq.reponse = {**SUCCES, "perimetre": {"type": "site", "valeurs": ["NOU001"]}}
    i = interpreter("drop sur NOU001", J, Contexte.pour(lecteur))
    q = next(q for q in i.questions if q.champ == "perimetre")  # hors périmètre : question, pas de calcul
    assert q.texte == "« NOU001 » n'est pas dans votre périmètre." and "perimetre" not in i.params
    assert [o.libelle for o in q.options] == ["Voir mon périmètre (Païta)"]
    assert "lte_erab_drop" not in i.params.get("kpis", [])  # KPI non autorisé ignoré
    assert "lte_erab_drop" not in json.loads(groq.appels[0][0].data)["messages"][0]["content"]


@pytest.mark.parametrize("erreur", [
    urllib.error.HTTPError("https://api.groq.com", 401, "Unauthorized", {}, None),
    socket.timeout("timed out"),
    TimeoutError("timed out"),
    urllib.error.URLError("proxy 403"),
], ids=["http-401", "socket-timeout", "timeout", "url-error"])
def test_echec_reseau_repli_sur_les_regles(ctx, groq, erreur):  # noqa: F811
    groq.erreur = erreur
    i = interpreter("drop 3G à Nouméa la semaine dernière", J, ctx)
    assert i.source == "regles" and i.notes[0] == NOTE_REPLI
    assert i.complete and i.params["kpis"] == ["wcdma_cs_drop", "wcdma_ps_drop"]


@pytest.mark.parametrize("contenu", ["pas du json", "[1, 2]", json.dumps({**SUCCES, "fenetre": "soir"}),
                                     json.dumps({**SUCCES, "perimetre": {"type": "planete", "valeurs": ["x"]}})],
                         ids=["texte", "liste", "fenetre-illisible", "type-inconnu"])
def test_reponse_invalide_repli_sur_les_regles(ctx, groq, contenu):  # noqa: F811
    groq.reponse = contenu
    i = interpreter("drop 3G à Nouméa la semaine dernière", J, ctx)
    assert i.source == "regles" and NOTE_REPLI in i.notes


def test_validation_pydantic_echec_repli(ctx, groq, monkeypatch):  # noqa: F811
    groq.reponse = SUCCES

    def refus(**kwargs):
        raise ValueError("requête invalide")

    monkeypatch.setattr("apps.kpi.recherche.ia.RequeteKpi", refus)
    i = interpreter("drop 4G Nouméa la semaine dernière", J, ctx)
    assert i.source == "regles" and NOTE_REPLI in i.notes


def test_sans_cle_pas_d_appel(ctx, settings):  # noqa: F811
    settings.GROQ_API_KEY = ""
    i = interpreter("drop 3G à Nouméa la semaine dernière", J, ctx)  # urlopen interdit (conftest)
    assert i.source == "regles" and NOTE_REPLI in i.notes


def test_case_visible_seulement_avec_cle(admin, base_recherche, settings):  # noqa: F811
    assert 'name="ia"' not in admin.get("/").content.decode()
    settings.GROQ_API_KEY = CLE_TEST
    html = admin.get("/").content.decode()
    assert 'name="ia"' in html and "Recherche IA" in html


def test_vue_recherche_ia(admin, base_recherche, groq):  # noqa: F811
    groq.reponse = SUCCES
    html = admin.get("/", {"q": "les coupures 4G le soir à Nouméa la semaine dernière", "ia": "1"}).content.decode()
    assert "✨ Interprété par l'IA" in html and "Synthèse sur la période" in html
    assert 'name="ia" value="1" checked' in html
    trace = JournalAudit.objects.get(action="recherche_kpi").requete
    assert trace["ia"] is True and trace["source"] == "ia"

    groq.erreur = urllib.error.HTTPError("https://api.groq.com", 503, "Indisponible", {}, None)
    html = admin.get("/", {"q": "drop 3G à Nouméa la semaine dernière", "ia": "1"}).content.decode()
    assert NOTE_REPLI in html and "Règles locales" in html and "Synthèse sur la période" in html


def test_ia_non_demandee_pas_d_appel(admin, base_recherche, groq):  # noqa: F811
    admin.get("/", {"q": "drop 3G à Nouméa la semaine dernière"})
    assert groq.appels == []
