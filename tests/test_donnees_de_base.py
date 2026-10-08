"""Formules des données de base vérifiées sur les extraits CSV (docs/donnees_de_base.md)."""

from functools import lru_cache

import pandas as pd
import pytest
from django.conf import settings

from apps.kpi.catalogue import charger_catalogue
from apps.kpi.moteur import agreger


@lru_cache
def _csv(nom):
    return pd.read_csv(settings.BASE_DIR / f"{nom}.csv", sep=";")


@lru_cache
def _cat():
    return charger_catalogue(settings.KPI_CATALOGUE_PATH)


def _kpis(codes):
    return [_cat()[c] for c in codes]


def _causes(parent):
    return [k for k in _cat().values() if k.decomposition_de == parent]


@pytest.mark.parametrize("fichier", ["lte_cell_hour", "lte_cell_day"])
def test_causes_drop_lte_somment_au_total(fichier):
    df = _csv(fichier)
    causes = _causes("lte_erab_drop")
    assert len(causes) == 7
    res = agreger(df, [_cat()["lte_erab_drop"], *causes], par=[]).iloc[0]
    assert sum(res[k.code] for k in causes) == pytest.approx(res["lte_erab_drop"], abs=1e-3)


def test_causes_drop_3g_partielles():
    """Les causes 3G publiées n'expliquent qu'une partie des coupures (reste « non ventilé »)."""
    df = _csv("wcdma_cell_day")
    causes = _causes("wcdma_cs_drop")
    res = agreger(df, [_cat()["wcdma_cs_drop"], *causes], par=[]).iloc[0]
    part = sum(res[k.code] for k in causes) / res["wcdma_cs_drop"]
    assert 0.3 < part < 0.8


@pytest.mark.parametrize("fichier, code, publie", [
    ("lte_cell_day", "lte_acces", "PssrLte_p"),
    ("wcdma_cell_day", "wcdma_cssr_cs", "CssrSp_p"),
    ("wcdma_cell_day", "wcdma_cssr_ps", "CssrPs_p"),
    ("wcdma_cell_hour", "wcdma_cssr_cs", "CssrSp_p"),
])
def test_taux_acces_composite_egal_au_publie_par_cellule(fichier, code, publie):
    df = _csv(fichier)
    cle = df.columns[0]
    par_cellule = agreger(df, _kpis([code]), par=[cle])[code]
    ecart = (par_cellule - df.set_index(cle)[publie]).abs().dropna()
    assert len(ecart) > 500  # extrait horaire à 0h : peu de cellules avec des appels
    assert ecart.median() < 0.1


def test_disponibilite_lte_plafonnee():
    df = _csv("lte_cell_day")
    assert df["CellAvaibilityD_p"].max() > 100  # anomalie de la source
    par_cellule = agreger(df, _kpis(["lte_cell_availability"]), par=["EutranCell_Id"])
    assert par_cellule["lte_cell_availability"].max() <= 100


def test_volumes_appels_sms():
    w, lte = _csv("wcdma_cell_day"), _csv("lte_cell_day")
    res = agreger(w, _kpis(["wcdma_appels_voix", "wcdma_tentatives_voix", "wcdma_sms"]), par=[]).iloc[0]
    assert res["wcdma_appels_voix"] == w["NbrSpeechCalls"].sum()
    assert res["wcdma_tentatives_voix"] >= res["wcdma_appels_voix"]
    assert res["wcdma_sms"] == w["ReqSms"].sum()
    csfb = agreger(lte, _kpis(["lte_csfb_appels"]), par=[])["lte_csfb_appels"].iloc[0]
    assert csfb == lte["CsfbRelVolWcdma_nb"].sum() + lte["CsfbRelVolGsm_nb"].sum()
