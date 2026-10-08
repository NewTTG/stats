import pandas as pd
from django.conf import settings

from apps.kpi.catalogue import charger_catalogue
from apps.kpi.moteur import agreger


def test_catalogue_valide():
    cat = charger_catalogue(settings.KPI_CATALOGUE_PATH)
    assert "lte_dl_user_thp" in cat
    assert all(k.code == code for code, k in cat.items())


def test_expressions_du_catalogue_evaluables():
    """Chaque expression ne référence que des colonnes des tables source (en-têtes des extraits CSV)."""
    cat = charger_catalogue(settings.KPI_CATALOGUE_PATH)
    for techno, fichier in [("LTE", "lte_cell_hour.csv"), ("WCDMA", "wcdma_cell_hour.csv")]:
        colonnes = pd.read_csv(settings.BASE_DIR / fichier, sep=";", nrows=0).columns
        df = pd.DataFrame({c: [10.0, 20.0] for c in colonnes})
        kpis = [k for k in cat.values() if k.techno == techno]
        res = agreger(df, kpis, par=[])
        for k in kpis:
            assert pd.notna(res[k.code].iloc[0]), k.code
