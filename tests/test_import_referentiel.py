"""Import du référentiel sur un xlsx synthétique."""

import pandas as pd
import pytest
from django.core.management import call_command

from apps.referentiel.importation import importer
from apps.referentiel.models import Cellule, ImportReferentiel, Secteur, Site

pytestmark = pytest.mark.django_db

SITES = pd.DataFrame({
    "codeSite": ["AAA100", "BBB200", "AAA101", "QUA300", "DEP400", "LEB500"],
    "Trigramme": ["AAA", "BBB", "AAA", "QUA", "DEP", "LEB"],
    "siteName": ["ALPHA", "BRAVO", "ALPHA_BIS", "QUATRO", "DEPORTE", "LEBRIS"],
    "commune": ["NOUMEA", "PAITA", "NOUMEA", "KONE", "NOUMEA", "PAITA"],
    "region": ["SUD", "SUD", "SUD", "NORD", "SUD", "SUD"],
    "latWgs84": [-22.2, -22.1, -22.3, -21.0, -22.2, -22.1],
    "lonWgs84": [166.4, 166.3, 166.5, 164.8, 166.4, 166.3],
    "nbSect": [3, 2, 1, 4, 2, 3],
})
SECTEURS = pd.DataFrame({
    "cells": ["AAA1001", "AAA1002", "AAA1003", "BBB2001", "BBB2002", "BBB2001",
              "ZZZ9991", "AAA1011", "QUA3001", "QUA3004", "DEP4004", "DEP4005",
              "LEB5001", "LEB5002", "LEB5003", "LEB5004"],
    "codeSite": ["AAA100"] * 3 + ["BBB200"] * 3 + ["ZZZ999", "AAA101", "QUA300", "QUA300"]
                + ["DEP400"] * 2 + ["LEB500"] * 4,
    "azimut": [0, 120, 240, 90, 270, 90, 0, 0, 0, 270, 0, 180, 0, 90, 180, 270],
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
    lte.write_text('"EutranCell_Id";"ERBS_Id"\n"AAAe1";"X"\n"AAAe13";"X"\n"BBBe2";"X"\n"BBBe3";"X"\n'
                   '"AAAe4";"X"\n"DEPe4";"X"\n"DEPe15";"X"\n"LEBe4";"X"\n"QUAe4";"X"\n')
    wcdma = tmp_path / "wcdma.csv"
    wcdma.write_text('"CellWcdma";"SiteWcdma"\n"AAA100B";"X"\n"AAA100E";"X"\n"QUA300D";"X"\n"QUA300M";"X"\n'
                     '"DEP400D";"X"\n"LEB500D";"X"\n')
    return [lte, wcdma]


def test_import_sites_et_secteurs(referentiel):
    imp = importer(referentiel)
    assert Site.objects.count() == 6
    assert Secteur.objects.count() == 14
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
    assert lte["QUAe4"].secteur.code == "QUA3004"


def test_secteurs_equivalents(referentiel, exports):
    """Site à 3 secteurs : 4 = 1, 5 = 2 ; site à 4 secteurs déclaré par Cell_File : 4 = 4."""
    importer(referentiel, exports)
    lte = {c.nom: c for c in Cellule.objects.filter(techno="LTE")}
    wcdma = {c.nom: c for c in Cellule.objects.filter(techno="WCDMA")}
    # couche supplémentaire : AAAe4 = AAAe1
    assert lte["AAAe4"].secteur.code == "AAA1001"
    # site déporté (trigramme propre) : secteurs 4 / 5 du référentiel = secteurs 1 / 2
    assert Secteur.objects.get(code="DEP4004").numero == 1
    assert Secteur.objects.get(code="DEP4005").numero == 2
    assert lte["DEPe4"].secteur.code == wcdma["DEP400D"].secteur.code == "DEP4004"
    assert lte["DEPe15"].secteur.code == "DEP4005" and lte["DEPe15"].porteuse == 2
    # 4 secteurs sans cellule M (secteurs 1 à 4 dans Cell_File, nbSect = 3)
    assert lte["LEBe4"].secteur.code == wcdma["LEB500D"].secteur.code == "LEB5004"


def test_secteur_equivalent_en_double(referentiel, tmp_path):
    chemin = tmp_path / "doublon.xlsx"
    secteurs = pd.concat([SECTEURS, pd.DataFrame({"cells": ["BBB2004"], "codeSite": ["BBB200"], "azimut": [0]})])
    with pd.ExcelWriter(chemin) as w:
        SITES.to_excel(w, sheet_name="Site_File", index=False)
        secteurs.to_excel(w, sheet_name="Cell_File", index=False)
    imp = importer(chemin)
    assert any("BBB2004 ignoré : équivalent de BBB2001" in a for a in imp.anomalies)
    assert not Secteur.objects.filter(code="BBB2004").exists()


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
    assert "6 sites, 14 secteurs" in capsys.readouterr().out
