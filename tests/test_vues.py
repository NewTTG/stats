import pytest
from django.contrib.auth.models import User

from apps.comptes.models import JournalAudit

from .test_service import base_kpi, referentiel  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

PARAMS = {
    "techno": "LTE", "perimetre_type": "commune", "perimetre_valeurs": "NOUMEA",
    "debut": "2026-09-01", "fin": "2026-09-02", "granularite_temps": "jour",
    "granularite_espace": "site", "fenetre_horaire": "journee", "kpis": ["lte_rrc_setup_sr"],
}


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin"))
    return client


def test_connexion_requise(client):
    assert client.get("/").status_code == 302


def test_formulaire_vierge(client_admin):
    r = client_admin.get("/")
    assert r.status_code == 200 and "Nouvelle requête" in r.content.decode()


def test_resultat_et_audit(client_admin, referentiel, base_kpi, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.kpi.views.moteur_kpi", lambda: base_kpi)
    r = client_admin.get("/", PARAMS)
    html = r.content.decode()
    assert "SITE_AAA" in html and "01/09/2026" in html
    assert JournalAudit.objects.filter(action="requete_kpi").count() == 1


def test_base_kpi_non_configuree(client_admin, referentiel, settings):  # noqa: F811
    from apps.kpi.source import moteur_kpi
    moteur_kpi.cache_clear()
    settings.KPI_DB = {**settings.KPI_DB, "host": ""}
    r = client_admin.get("/", PARAMS)
    assert "Base KPI non configurée" in r.content.decode()
    moteur_kpi.cache_clear()
