import pytest
from pydantic import ValidationError

from apps.kpi.requete import RequeteKpi

BASE = {
    "techno": ["LTE"],
    "perimetre": {"type": "commune", "valeurs": ["NOUMEA"]},
    "periode": {"debut": "2026-09-01", "fin": "2026-09-30"},
    "granularite_temps": "jour",
    "granularite_espace": "secteur",
    "fenetre_horaire": "18-22",
    "kpis": ["lte_dl_user_thp"],
    "comparaison": {"type": "periode_precedente"},
}


def test_requete_exemple_du_brief():
    r = RequeteKpi(**BASE)
    assert r.periode.fin.day == 30


@pytest.mark.parametrize("modif", [
    {"periode": {"debut": "2026-09-30", "fin": "2026-09-01"}},
    {"fenetre_horaire": "22-18"},
    {"fenetre_horaire": "soir"},
    {"perimetre": {"type": "commune", "valeurs": []}},
    {"kpis": []},
    {"techno": ["5G"]},
    {"comparaison": {"type": "reference_personnalisee"}},
])
def test_requetes_invalides(modif):
    with pytest.raises(ValidationError):
        RequeteKpi(**{**BASE, **modif})
