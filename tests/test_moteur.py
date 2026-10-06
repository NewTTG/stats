"""Règle d'agrégation : ratio de sommes, jamais moyenne de ratios (brief §4)."""

import math

import numpy as np
import pandas as pd
import pytest

from apps.kpi.catalogue import DefinitionKpi
from apps.kpi.moteur import agreger

DROP = DefinitionKpi(
    code="drop", libelle="Drop", techno="LTE", unite="%", categorie="retainability",
    numerateur="drops", denominateur="releases", facteur=100, sens="bas_est_mieux",
)
VOLUME = DefinitionKpi(
    code="vol", libelle="Volume", techno="LTE", unite="Mo", categorie="trafic",
    numerateur="volume", sens="haut_est_mieux",
)
DEBIT = DefinitionKpi(
    code="thp", libelle="Débit", techno="LTE", unite="Mbps", categorie="debit",
    numerateur="volume", denominateur="volume / thp_kbps", facteur=0.001, sens="haut_est_mieux",
)


def test_ratio_de_sommes_et_non_moyenne_de_ratios():
    # Cellule A : 1 drop / 1000 releases (0,1 %) ; cellule B : 5 / 10 (50 %).
    df = pd.DataFrame({"cell": ["A", "B"], "drops": [1, 5], "releases": [1000, 10]})
    res = agreger(df, [DROP], par=[])
    attendu = 6 / 1010 * 100
    assert res["drop"].iloc[0] == pytest.approx(attendu)
    assert res["drop"].iloc[0] != pytest.approx((0.1 + 50) / 2)


def test_agregation_temporelle_puis_spatiale_est_coherente():
    df = pd.DataFrame({
        "cell": ["A", "A", "B", "B"],
        "heure": [18, 19, 18, 19],
        "drops": [1, 0, 3, 2],
        "releases": [100, 50, 10, 40],
    })
    par_cellule = agreger(df, [DROP], par=["cell"])
    assert par_cellule.loc["A", "drop"] == pytest.approx(1 / 150 * 100)
    assert par_cellule.loc["B", "drop"] == pytest.approx(5 / 50 * 100)
    # Ré-agréger les sommes par cellule redonne le global exact.
    glob = agreger(df, [DROP], par=[])["drop"].iloc[0]
    assert glob == pytest.approx(6 / 200 * 100)
    assert glob == pytest.approx(par_cellule["drop__num"].sum() / par_cellule["drop__den"].sum() * 100)


def test_kpi_additif():
    df = pd.DataFrame({"cell": ["A", "B", "B"], "volume": [1.5, 2.0, 3.0]})
    res = agreger(df, [VOLUME], par=["cell"])
    assert res.loc["B", "vol"] == pytest.approx(5.0)


def test_debit_reconstruit_pondere_par_le_temps():
    # A : 1000 Mo à 10 000 kbps ; B : 10 Mo à 1 000 kbps.
    df = pd.DataFrame({"volume": [1000.0, 10.0], "thp_kbps": [10_000.0, 1_000.0]})
    res = agreger(df, [DEBIT], par=[])["thp"].iloc[0]
    temps = 1000 / 10_000 + 10 / 1_000
    assert res == pytest.approx(1010 / temps * 0.001)


def test_absence_de_donnees_distincte_de_zero():
    df = pd.DataFrame({
        "cell": ["A", "A", "B"],
        "drops": [np.nan, np.nan, 0],
        "releases": [np.nan, np.nan, 100],
    })
    res = agreger(df, [DROP], par=["cell"])
    assert math.isnan(res.loc["A", "drop"])  # pas de données
    assert res.loc["B", "drop"] == 0  # valeur nulle réelle


def test_denominateur_nul_donne_nan():
    df = pd.DataFrame({"drops": [0], "releases": [0]})
    assert math.isnan(agreger(df, [DROP], par=[])["drop"].iloc[0])


def test_debit_nul_ne_produit_pas_inf():
    df = pd.DataFrame({"volume": [0.0, 10.0], "thp_kbps": [0.0, 1_000.0]})
    assert agreger(df, [DEBIT], par=[])["thp"].iloc[0] == pytest.approx(1.0)
