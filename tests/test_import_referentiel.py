"""Import du référentiel sur un xlsx synthétique."""

import pandas as pd
import pytest
from django.core.management import call_command

from apps.referentiel.importation import importer
from apps.referentiel.models import Cellule, ImportReferentiel, Secteur, Site

pytestmark = pytest.mark.django_db

SITES = pd.DataFrame({
    "codeSite": ["AAA100", "BBB200", "AAA101", "QUA300"],
    "Trigramme": ["AAA", "BBB", "AAA", "QUA"],
    "siteName": ["ALPHA", "BRAVO", "ALPHA_BIS", "QUATRO"],
    "commune": ["NOUMEA", "PAITA", "NOUMEA", "KONE"],
    "region": ["SUD", "SUD", "SUD", "NORD"],
    "latWgs84": [-22.2, -22.1, -22.3, -21.0],
    "lonWgs84": [166.4, 166.3, 166.5, 164.8],
    "nbSect": [3, 2, 1, 4],
})
SECTEURS = pd.DataFrame({
    "cells": ["AAA1001", "AAA1002", "AAA1003", "BBB2001", "BBB2002", "BBB2001",
              "ZZZ9991", "AAA1011", "QUA3001", "QUA3004"],
    "codeSite": ["AAA100"] * 3 + ["BBB200"] * 3 + ["ZZZ999", "AAA101", "QUA300", "QUA300"],
    "azimut": [0, 120, 240, 90, 270, 90, 0, 0, 0, 270],
})


@pytest.fixture
def referentiel(tmp_path):
    chemin = tmp_path / "ref.xlsx"
    with pd.ExcelWriter(chemin) as w:
        SITES.to_excel(w, sheet_name="Site_File", index=False)
        SECTEURS.to_excel(w, sheet_name="Cell_File", index=False)
    return chemin


@pytest.fixture
def exports(tmp_path):
    lte = tmp_path / "lte.csv"
    lte.write_text('"EutranCell_Id";"ERBS_Id"\n"AAAe1";"X"\n"AAAe13";"X"\n"BBBe2";"X"\n"BBBe3";"X"\n')
    wcdma = tmp_path / "wcdma.csv"
    wcdma.write_text('"CellWcdma";"SiteWcdma"\n"AAA100B";"X"\n"AAA100E";"X"\n"QUA300D";"X"\n"QUA300M";"X"\n')
    return [lte, wcdma]


def test_import_sites_et_secteurs(referentiel):
    imp = importer(referentiel)
    assert Site.objects.count() == 4
    assert Secteur.objects.count() == 8
    assert Secteur.objects.get(code="AAA1002").numero == 2
    assert any("BBB2001 en double" in a for a in imp.anomalies)
    assert any("ZZZ9991 rejeté" in a for a in imp.anomalies)


def test_rattachement_des_cellules(referentiel, exports):
    imp = importer(referentiel, exports)
    lte = {c.nom: c for c in Cellule.objects.filter(techno="LTE")}
    assert lte["AAAe13"].secteur.code == "AAA1003" and lte["AAAe13"].porteuse == 2
    # trigramme partagé : le premier site du fichier (AAA100) fait foi
    assert lte["AAAe1"].secteur.site.code_site == "AAA100"
    assert any("trigramme AAA partagé" in a for a in imp.anomalies)
    # secteur absent du référentiel : signalé, cellule conservée sans rattachement
    assert lte["BBBe3"].secteur is None
    assert any("BBBe3" in a for a in imp.anomalies)

    wcdma = {c.nom: c for c in Cellule.objects.filter(techno="WCDMA")}
    assert (wcdma["AAA100E"].porteuse, wcdma["AAA100E"].secteur.code) == (2, "AAA1002")
    # site à 4 secteurs (cellule M) : D = secteur 4 porteuse 1, M = secteur 4 porteuse 2
    assert (wcdma["QUA300D"].porteuse, wcdma["QUA300D"].secteur.code) == (1, "QUA3004")
    assert (wcdma["QUA300M"].porteuse, wcdma["QUA300M"].secteur.code) == (2, "QUA3004")


def test_reimport_versionne(referentiel, tmp_path):
    importer(referentiel)
    reduit = tmp_path / "reduit.xlsx"
    with pd.ExcelWriter(reduit) as w:
        SITES[SITES.codeSite != "BBB200"].to_excel(w, sheet_name="Site_File", index=False)
        SECTEURS[SECTEURS.codeSite != "BBB200"].to_excel(w, sheet_name="Cell_File", index=False)
    imp = importer(reduit)
    assert ImportReferentiel.objects.count() == 2
    assert {"BBB200", "BBB2001", "BBB2002"} <= set(imp.suppressions)
    assert imp.ajouts == []
    assert not Site.objects.filter(code_site="BBB200").exists()


def test_commande(referentiel, exports, capsys):
    call_command("import_referentiel", str(referentiel), "--cellules", *map(str, exports))
    assert "4 sites, 8 secteurs" in capsys.readouterr().out
