"""Non-régression du contrôle indépendant (tour 5 du développement, constats « tour 6 ») :
provinces, « semaine du … », « S40 », vocabulaire (accès RRC, CSFB, appels établis),
résultat vide, cartes d'anomalies."""

import re
from datetime import date

import pytest
from django.contrib.auth.models import User

from apps.kpi.recherche.regles import interpreter

from .test_controle_tour3 import _question_lieu, ctx3, ctx_lecteur, lecteur_kone, ref_t3  # noqa: F401
from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixture)
from .test_recherche_vues import base_recherche  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def _communes(i):
    p = i.params["perimetre"]
    assert p["type"] == "commune", p
    return set(p["valeurs"])


# ------------------------------------------------------------------ MAJEUR : provinces

@pytest.mark.parametrize("phrase", ["drop 3G Province Sud le 6 octobre", "drop 3G province sud le 6 octobre",
                                    "drop 3G dans la Province Sud le 6 octobre", "Province Sud drop 3G le 6 octobre"])
def test_province_sud_avec_le_grand_noumea(ctx3, phrase):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    communes = _communes(i)
    assert {"NOUMEA", "DUMBEA", "PAITA", "MONT DORE", "LA FOA", "ILE DES PINS", "BOURAIL"} <= communes
    assert i.puce("perimetre").libelle == "Province Sud" and i.non_compris == []


def test_province_nord_et_province_des_iles(ctx3):  # noqa: F811
    nord = _communes(interpreter("drop 3G Province Nord le 6 octobre", J, ctx3))
    assert {"KONE", "KOUMAC", "PONERIHOUEN", "KAALA GOMEN", "VOH", "POUM"} <= nord and "NOUMEA" not in nord
    iles = _communes(interpreter("drop 3G Province des Îles le 6 octobre", J, ctx3))
    assert iles == {"LIFOU", "MARE"}


def test_sud_seul_garde_son_sens(ctx3):  # noqa: F811
    """Choix documenté : « sud » seul = « Sud (hors Grand Nouméa) »."""
    i = interpreter("drop 3G Sud le 6 octobre", J, ctx3)
    assert "NOUMEA" not in _communes(i) and "LA FOA" in _communes(i)
    assert i.puce("perimetre").libelle == "Sud (hors Grand Nouméa)"


def test_provinces_pour_le_lecteur(ctx_lecteur):  # noqa: F811
    i = interpreter("drop 4G Province Nord le 6 octobre", J, ctx_lecteur)
    assert i.params["perimetre"] == {"type": "commune", "valeurs": ["KONE"]} and i.complete
    q = _question_lieu(interpreter("drop 4G Province Sud le 6 octobre", J, ctx_lecteur))
    assert q and q.texte == "« Province Sud » n'est pas dans votre périmètre."
    q = _question_lieu(interpreter("drop 4G province des îles le 6 octobre", J, ctx_lecteur))
    assert q and q.texte == "« province des îles » n'est pas dans votre périmètre."


# ------------------------------------------------------------------ mineurs : dates

@pytest.mark.parametrize("phrase,debut,fin", [
    ("drop 4G Nouméa la semaine du 5 octobre", date(2026, 10, 5), date(2026, 10, 8)),  # semaine en cours
    ("drop 4G Nouméa semaine du 05/10", date(2026, 10, 5), date(2026, 10, 8)),
    ("drop 4G Nouméa la semaine du 14/09", date(2026, 9, 14), date(2026, 9, 20)),
    ("drop 4G Nouméa semaine du 1er octobre", date(2026, 9, 28), date(2026, 10, 4)),  # jeudi -> lundi 28/09
    ("drop 4G Nouméa semaine du 16 septembre", date(2026, 9, 14), date(2026, 9, 20)),
    ("drop 4G Nouméa semaine S40", date(2026, 9, 28), date(2026, 10, 4)),
    ("drop 4G Nouméa la semaine S 40", date(2026, 9, 28), date(2026, 10, 4)),
])
def test_semaine_du_et_semaine_s(ctx3, phrase, debut, fin):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    assert (i.params["periode"]["debut"], i.params["periode"]["fin"]) == (debut, fin)
    assert i.non_compris == []


def test_s40_sans_contexte_propose_la_semaine_40(ctx3):  # noqa: F811
    i = interpreter("drop 4G Nouméa S40", J, ctx3)
    q = next(q for q in i.questions if q.champ == "periode")
    assert q.options[0].libelle == "Semaine 40"
    assert q.options[0].params == {"debut": "2026-09-28", "fin": "2026-10-04"}
    assert [o.libelle for o in q.options[1:]][:2] == ["Hier", "7 derniers jours"]
    q = next(q for q in interpreter("drop 4G Nouméa S1", J, ctx3).questions if q.champ == "periode")
    assert q.options[0].libelle == "Hier"  # « S1 » : interface S1, jamais une semaine


# ------------------------------------------------------------------ mineurs : vocabulaire

def test_taux_d_acces_rrc_sans_composite(ctx3):  # noqa: F811
    assert interpreter("taux d'accès RRC 4G à Koné hier", J, ctx3).params["kpis"] == ["lte_rrc_setup_sr"]


def test_appels_3g_et_csfb(ctx3):  # noqa: F811
    i = interpreter("nombre d'appels 3G et CSFB à Koné hier", J, ctx3)
    assert "lte_csfb_appels" in i.params["kpis"] and "wcdma_appels_voix" in i.params["kpis"]
    assert interpreter("drop E-RAB 3G Koné hier", J, ctx3).params["techno"] == ["WCDMA"]  # inchangé


def test_tentatives_et_appels_etablis(ctx3):  # noqa: F811
    i = interpreter("tentatives d'appels voix et appels établis à Koné hier", J, ctx3)
    assert i.params["kpis"] == ["wcdma_tentatives_voix", "wcdma_appels_voix"] and i.non_compris == []


# ------------------------------------------------------------------ mineurs : affichage

def test_resultat_vide_sans_boutons_d_export(base_recherche, client):  # noqa: F811
    client.force_login(User.objects.create_superuser("admin_vide"))
    html = client.get("/", {"q": "drop 4G Nouméa septembre 2025"}).content.decode()  # hors historique
    assert "aucune donnée sur la période demandée" in html
    assert "Exporter Excel" not in html and "Rapport PowerPoint" not in html
    html = client.get("/", {"q": "drop 4G Nouméa la semaine dernière"}).content.decode()
    assert "Exporter Excel" in html and "Rapport PowerPoint" in html


def test_separateur_des_cartes_d_anomalies_en_fin_de_segment(settings):
    css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
    mobile = re.search(r"@media \(max-width: 600px\) \{(.*?)\n\}", css, re.S)[1]
    assert "td.regle::before" not in css
    assert 'table.anomalies td.entite::after { content: "\\00a0·";' in mobile
