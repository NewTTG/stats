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
    # Même texte : une seule entrée, la plus récente (tour 4 : dédoublonnage par texte).
    assert "kpis=lte_erab_drop" in html and "intention=drop" not in html
    assert html.count('href="?q=Noum%C3%A9a+hier') == 1


def test_recherche_vide(admin, base_recherche):  # noqa: F811
    admin.get("/", {"q": "Nouméa hier", "intention": "drop"})
    r = admin.get("/", {"q": ""})
    assert r.status_code == 200 and "Que voulez-vous savoir" in r.content.decode()


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
