"""Accueil : « Mes dernières recherches » robuste à toute entrée d'audit (B1)."""

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import JournalAudit

from .test_recherche_regles import ref_recherche  # noqa: F401  (fixtures)
from .test_recherche_vues import admin, base_recherche  # noqa: F401

pytestmark = pytest.mark.django_db


def test_accueil_apres_reponse_a_une_question(admin, base_recherche):  # noqa: F811
    """Paramètres en listes (intention, techno, kpis) dans l'audit : plus d'erreur 500."""
    r = admin.get("/", {"q": "Nouméa hier", "intention": "drop"})
    assert r.status_code == 200 and "Synthèse sur la période" in r.content.decode()
    admin.get("/", {"q": "Nouméa hier", "techno": ["LTE", "WCDMA"], "kpis": ["lte_erab_drop", "wcdma_cs_drop"]})
    r = admin.get("/")
    html = r.content.decode()
    assert r.status_code == 200 and "Mes dernières recherches" in html
    # Rapport ou indicateurs choisis : entrées libellées par leurs puces, chacune rejoue ses paramètres.
    assert "<span>Drop · Nouméa · Hier</span>" in html and "intention=drop" in html
    assert "<span>Taux de coupure E-RAB, Taux de coupure appels voix (3G) · Nouméa · Hier</span>" in html
    assert "kpis=lte_erab_drop" in html
    # Même libellé : une seule entrée, la plus récente (tour 4 : dédoublonnage).
    admin.get("/", {"q": "Nouméa hier", "intention": "drop", "granularite_temps": "jour"})
    html = admin.get("/").content.decode()
    assert html.count("<span>Drop · Nouméa · Hier</span>") == 1 and "granularite_temps=jour" in html


def test_recherche_depuis_l_accueil_sans_lieu(admin, base_recherche):  # noqa: F811
    """Rapport type sur tout le réseau (lieu vide) : libellé des puces, relancé sur sa période relative."""
    r = admin.get("/", {"q": "", "intention": "drop", "periode": "hier"})
    assert r.status_code == 200 and "Synthèse sur la période" in r.content.decode()
    html = admin.get("/").content.decode()
    assert "<span>Drop · Tout le réseau autorisé · Hier</span>" in html
    assert 'href="?q=&amp;intention=drop&amp;periode=hier"' in html


def test_recherche_vide(admin, base_recherche):  # noqa: F811
    admin.get("/", {"q": "Nouméa hier", "intention": "drop"})
    r = admin.get("/", {"q": ""})
    assert r.status_code == 200 and "Quel rapport" in r.content.decode()


@pytest.mark.parametrize("trace", [
    [], "texte", 7, {"q": 3}, {"q": "drop 4G hier", "parametres": "x"},
    {"q": "drop 4G hier", "parametres": {"kpis": [{"a": 1}], "techno": ["LTE"]}},
    {"q": "drop 4G hier", "ia": True, "requete": {"techno": ["GSM"]}},
    {"requete": {"techno": ["LTE"], "kpis": []}}, {"techno": "LTE"},
])
def test_entrees_d_audit_malformees_ignorees(admin, base_recherche, trace):  # noqa: F811
    utilisateur = User.objects.get(username="admin")
    for action in ("recherche_kpi", "requete_kpi"):
        JournalAudit.objects.create(utilisateur=utilisateur, action=action, requete=trace)
    JournalAudit.objects.create(utilisateur=utilisateur, action="recherche_kpi",
                                requete={"q": "débit 4G Païta hier", "parametres": {"techno": ["LTE"]}})
    r = admin.get("/")
    assert r.status_code == 200 and "débit 4G Païta hier" in r.content.decode()


def test_recherche_ia_rejouee_sans_appel_ia(admin, base_recherche):  # noqa: F811
    """Une recherche IA récente se rejoue avec sa requête résolue, sans ia=1 (pas de nouvel appel)."""
    utilisateur = User.objects.get(username="admin")
    requete = {"techno": ["LTE"], "perimetre": {"type": "commune", "valeurs": ["PAITA"]},
               "periode": {"debut": "2026-10-01", "fin": "2026-10-02"}, "kpis": ["lte_erab_drop"]}
    JournalAudit.objects.create(utilisateur=utilisateur, action="recherche_kpi",
                                requete={"q": "coupures 4G Païta", "ia": True, "source": "ia", "requete": requete})
    html = admin.get("/").content.decode()
    assert "✨ coupures 4G Païta" in html
    assert "perimetre_valeurs=PAITA" in html and "debut=2026-10-01" in html and "ia=1" not in html
