"""Export Excel : onglets, valeurs de synthèse (ratio de sommes) et seuils."""

from io import BytesIO

import pytest
from openpyxl import load_workbook

from apps.kpi.catalogue import catalogue
from apps.kpi.export_excel import construire
from apps.kpi.service import executer

from .test_service import analyste, base_kpi, referentiel, requete  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


def test_statut_selon_sens_et_seuils():
    rrc, drop = catalogue()["lte_rrc_setup_sr"], catalogue()["lte_erab_drop"]
    assert rrc.statut(99.5) == "" and rrc.statut(97) == "alerte" and rrc.statut(90) == "critique"
    assert drop.statut(0.5) == "" and drop.statut(1.5) == "alerte" and drop.statut(3) == "critique"
    assert rrc.statut(None) == "" and catalogue()["lte_payload_dl"].statut(1) == ""


def test_synthese_ratio_de_sommes_sur_la_periode(referentiel, base_kpi, analyste):  # noqa: F811
    res = executer(requete(), analyste, base_kpi).par_techno[0]
    assert res.synthese_globale["lte_rrc_setup_sr"] == pytest.approx(1059 * 4 / (1160 * 4) * 100)
    assert res.synthese_globale["lte_payload_dl"] == pytest.approx(160.0)


def test_classeur(referentiel, base_kpi, analyste):  # noqa: F811
    req = requete(perimetre={"type": "commune", "valeurs": ["PAITA", "NOUMEA"]}, granularite_espace="site")
    wb = load_workbook(BytesIO(construire(executer(req, analyste, base_kpi))))
    assert wb.sheetnames == ["Paramètres", "Synthèse LTE", "Données LTE", "Définitions"]

    synthese = list(wb["Synthèse LTE"].iter_rows(values_only=True))
    ensemble = synthese[1]
    assert ensemble[0] == "Ensemble du périmètre"
    assert ensemble[1] == pytest.approx(1009 * 4 / (1110 * 4) * 100)  # RRC, ratio de sommes
    assert wb["Synthèse LTE"]["B2"].fill.fgColor.rgb.endswith("F8C4C4")  # critique : < 95 %
    assert {l[0] for l in synthese[2:]} == {"SITE_AAA", "SITE_BBB"}
    assert len(list(wb["Données LTE"].iter_rows())) == 1 + 2 * 2  # 2 jours × 2 sites
    parametres = dict(wb["Paramètres"].iter_rows(values_only=True))
    assert parametres["Cellules LTE sans donnée"] == "BBBe2"
