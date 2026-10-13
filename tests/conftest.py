import pytest


@pytest.fixture(autouse=True)
def cache_kpi_isole(settings, tmp_path):
    """Chaque test a son cache ; aucune lecture/écriture dans le cache de l'application."""
    settings.KPI_CACHE_DIR = tmp_path / "cache_kpi"
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture(autouse=True)
def sans_reseau(monkeypatch):
    """Aucun appel réseau réel pendant les tests (API IA comprise) : urlopen doit être simulé."""
    def interdit(*args, **kwargs):
        raise RuntimeError("appel réseau interdit pendant les tests")

    monkeypatch.setattr("urllib.request.urlopen", interdit)
