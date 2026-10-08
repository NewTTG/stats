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


# ------------------------------------------------- KPI composites, causes, plafond

def _catalogue(tmp_path, kpis):
    import yaml

    from apps.kpi.catalogue import charger_catalogue

    chemin = tmp_path / "catalogue.yaml"
    chemin.write_text(yaml.safe_dump({"kpis": kpis}, allow_unicode=True), encoding="utf-8")
    return charger_catalogue(chemin)


RRC = {"code": "rrc", "libelle": "RRC", "techno": "WCDMA", "unite": "%", "categorie": "accessibilite",
       "numerateur": "rrc_succ", "denominateur": "rrc_att", "facteur": 100, "sens": "haut_est_mieux"}
RAB = {"code": "rab", "libelle": "RAB", "techno": "WCDMA", "unite": "%", "categorie": "accessibilite",
       "numerateur": "rab_succ", "denominateur": "rab_att", "facteur": 100, "sens": "haut_est_mieux"}
CSSR = {"code": "cssr", "libelle": "Accès", "techno": "WCDMA", "unite": "%", "categorie": "accessibilite",
        "produit_de": ["rrc", "rab"], "facteur": 100, "sens": "haut_est_mieux"}


def test_composite_produit_des_ratios_de_sommes(tmp_path):
    cat = _catalogue(tmp_path, [RRC, RAB, CSSR])
    # A : RRC 50/100, RAB 50/50 ; B : RRC 10/10, RAB 1/10.
    df = pd.DataFrame({"cell": ["A", "B"], "rrc_succ": [50, 10], "rrc_att": [100, 10],
                       "rab_succ": [50, 1], "rab_att": [50, 10]})
    res = agreger(df, [cat["cssr"]], par=[])["cssr"].iloc[0]
    attendu = (60 / 110) * (51 / 60) * 100
    assert res == pytest.approx(attendu)
    produits_par_ligne = [0.5 * 1.0, 1.0 * 0.1]
    assert res != pytest.approx(np.mean(produits_par_ligne) * 100)  # pas une moyenne de produits
    assert not cat["cssr"].additif


def test_composite_avec_ses_composants_demandes(tmp_path):
    cat = _catalogue(tmp_path, [RRC, RAB, CSSR])
    df = pd.DataFrame({"rrc_succ": [9], "rrc_att": [10], "rab_succ": [8], "rab_att": [10]})
    res = agreger(df, [cat["rrc"], cat["cssr"], cat["rab"]], par=[]).iloc[0]
    assert res["rrc"] == pytest.approx(90) and res["rab"] == pytest.approx(80)
    assert res["cssr"] == pytest.approx(72)


def test_composite_colonnes_utilisees(tmp_path):
    from apps.kpi.service import colonnes_utilisees

    cat = _catalogue(tmp_path, [RRC, RAB, CSSR])
    assert colonnes_utilisees([cat["cssr"]]) == ["rab_att", "rab_succ", "rrc_att", "rrc_succ"]


@pytest.mark.parametrize("modif, message", [
    ({"produit_de": ["rrc", "inconnu"]}, "inconnu"),
    ({"produit_de": ["rrc", "vol"]}, "additif"),
    ({"produit_de": ["rrc", "rab"], "numerateur": "x"}, "exclut"),
    ({"produit_de": ["rrc"]}, "au moins deux"),
])
def test_composite_invalide(tmp_path, modif, message):
    vol = {"code": "vol", "libelle": "Vol", "techno": "WCDMA", "unite": "Mo", "categorie": "trafic",
           "numerateur": "v", "sens": "haut_est_mieux"}
    with pytest.raises(ValueError, match=message):
        _catalogue(tmp_path, [RRC, RAB, vol, {**CSSR, **modif}])


def test_decomposition_parent_inconnu(tmp_path):
    cause = {**RRC, "code": "cause", "decomposition_de": "absent"}
    with pytest.raises(ValueError, match="decomposition_de"):
        _catalogue(tmp_path, [RRC, cause])


def test_plafond_ligne_a_ligne():
    dispo = DefinitionKpi(code="dispo", libelle="Dispo", techno="LTE", unite="%", categorie="disponibilite",
                          numerateur="dispo_p", denominateur="1", plafond=100, sens="haut_est_mieux")
    df = pd.DataFrame({"dispo_p": [248.0, 50.0]})
    assert agreger(df, [dispo], par=[])["dispo"].iloc[0] == pytest.approx(75)


def test_reference_evenement_composite_non_additive(tmp_path):
    """Référence d'un composite = ratio de sommes sur les semaines, pas la moyenne des semaines."""
    from apps.evenements.analyse import _valeurs

    cat = _catalogue(tmp_path, [RRC, RAB, CSSR])
    df = pd.DataFrame({
        "cell": ["A"] * 3, "semaine": [0, 1, 2],
        "rrc_succ": [10, 10, 100], "rrc_att": [10, 20, 100],
        "rab_succ": [10, 10, 100], "rab_att": [10, 10, 100],
    })
    _, reference, _ = _valeurs(df, [cat["cssr"]], ["cell"])
    assert reference.loc["A", "cssr"] == pytest.approx(110 / 120 * 100)
