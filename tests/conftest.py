import pytest


@pytest.fixture(autouse=True)
def sans_reseau(monkeypatch):
    """Aucun appel réseau réel pendant les tests (API IA comprise) : urlopen doit être simulé."""
    def interdit(*args, **kwargs):
        raise RuntimeError("appel réseau interdit pendant les tests")

    monkeypatch.setattr("urllib.request.urlopen", interdit)
