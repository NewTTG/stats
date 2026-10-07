import pandas as pd
from django.conf import settings

from apps.kpi.catalogue import charger_catalogue
from apps.kpi.moteur import agreger


def test_catalogue_valide():
    cat = charger_catalogue(settings.KPI_CATALOGUE_PATH)
    assert "lte_dl_user_thp" in cat
    assert all(k.code == code for code, k in cat.items())


def test_expressions_du_catalogue_evaluables():
    """Chaque expression ne référence que des colonnes existantes (données synthétiques)."""
    cat = charger_catalogue(settings.KPI_CATALOGUE_PATH)
    colonnes = {
        "LTE": ["PayloadDl_mB", "UserThpDl_kbps", "PayloadUl_mB", "UserThpUl_kbps",
                "pmRrcConnEstabSucc", "pmRrcConnEstabAtt", "ErabDropRate_p", "ErabEstabSucc_nb",
                "PrbVectUsageDl_p", "HoIntraSucc_p", "pmHoPrepAttLteIntraF", "CellAvaibilityD_p"],
        "WCDMA": ["PayloadPsHs_mb", "UserThpHs_kbps", "SpeechTrafficDay_erlg", "RabDropCs_p",
                  "NbrSpeechCalls", "Avaibility_p", "CssrSp_p", "NbrSpeechCallsAtt", "CssrPs_p", "ReqPs"],
    }
    for techno, cols in colonnes.items():
        df = pd.DataFrame({c: [10.0, 20.0] for c in cols})
        kpis = [k for k in cat.values() if k.techno == techno]
        res = agreger(df, kpis, par=[])
        for k in kpis:
            assert pd.notna(res[k.code].iloc[0]), k.code
