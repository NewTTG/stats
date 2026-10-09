"""Import du référentiel sur un xlsx synthétique (Site_File seul ; Cell_File ignoré)."""

import pandas as pd
import pytest
from django.core.management import call_command

from apps.referentiel.importation import importer
from apps.referentiel.models import Cellule, ImportReferentiel, Secteur, Site

pytestmark = pytest.mark.django_db

SITES = pd.DataFrame({
    "codeSite": ["AAA100", "BBB200", "AAA101", "QUA300", "DEP400", "LEB500", "MDO600"],
    "Trigramme": ["AAA", "BBB", "AAA", "QUA", "DEP", "LEB", "MDO"],
    "siteName": ["ALPHA", "BRAVO", "ALPHA_BIS", "QUATRO", "DEPORTE", "LEBRIS", "MONT_DO"],
    "commune": ["NOUMEA", "PAITA", "NOUMEA", "KONE", "NOUMEA", "PAITA", "MONT DORE"],
    "region": ["SUD", "SUD", "SUD", "NORD", "SUD", "SUD", "SUD"],
    "latWgs84": [-22.2, -22.1, -22.3, -21.0, -22.2, -22.1, -22.3],
    "lonWgs84": [166.4, 166.3, 166.5, 164.8, 166.4, 166.3, 166.5],
    "nbSect": [3, 2, 1, 3, 2, 3, 4],
})
# Cell_File volontairement incohérent : il ne doit pas être lu.
CELL_FILE = pd.DataFrame({"cells": ["AAA1004", "ZZZ9991"], "codeSite": ["AAA100", "ZZZ999"]})
LTE = ["AAAe1", "AAAe13", "AAAe4", "BBBe2", "DEPe4", "DEPe15", "LEBe1", "LEBe2", "LEBe3", "LEBe4", "LEBe14",
       "MDOe1", "MDOe4", "QUAe1", "QUAe4", "ZZZe1"]
WCDMA = ["AAA100B", "AAA100E", "BBB201A", "QUA300D", "QUA300M", "DEP400D", "LEB500D", "MDO600D", "MDO600E",
         "YYY900A"]


@pytest.fixture
def referentiel(tmp_path):
    chemin = tmp_path / "ref.xlsx"
    with pd.ExcelWriter(chemin) as w:
        SITES.to_excel(w, sheet_name="Site_File", index=False)
        CELL_FILE.to_excel(w, sheet_name="Cell_File", index=False)
    return chemin


@pytest.fixture
def exports(tmp_path):
    lte = tmp_path / "lte.csv"
    lte.write_text('"EutranCell_Id";"ERBS_Id"\n' + "".join(f'"{n}";"X"\n' for n in LTE))
    wcdma = tmp_path / "wcdma.csv"
    wcdma.write_text('"CellWcdma";"SiteWcdma"\n' + "".join(f'"{n}";"X"\n' for n in WCDMA))
    return [lte, wcdma]


def _cellules(techno):
    return {c.nom: c for c in Cellule.objects.filter(techno=techno).select_related("secteur", "secteur_avant")}


def test_import_sites_seuls(referentiel):
    imp = importer(referentiel)
    assert Site.objects.count() == 7
    assert Site.objects.get(code_site="MDO600").nom == "MONT_DO"
    # sans exports de cellules : aucun secteur (Cell_File n'est pas lu)
    assert Secteur.objects.count() == 0 and imp.nb_secteurs == 0


def test_rattachement_des_cellules(referentiel, exports):
    imp = importer(referentiel, exports)
    lte = _cellules("LTE")
    assert lte["AAAe13"].secteur.code == "AAA1003" and lte["AAAe13"].porteuse == 2
    # trigramme partagé : le premier site du fichier (AAA100) fait foi
    assert lte["AAAe1"].secteur.site.code_site == "AAA100"
    assert any("trigramme AAA partagé" in a for a in imp.anomalies)
    # trigramme absent de Site_File : signalé, cellule conservée sans rattachement
    assert lte["ZZZe1"].secteur is None
    assert any("trigramme ZZZ" in a for a in imp.anomalies)

    wcdma = _cellules("WCDMA")
    assert (wcdma["AAA100E"].porteuse, wcdma["AAA100E"].secteur.code) == (2, "AAA1002")
    # codeSite absent de Site_File : rattaché par le trigramme
    assert wcdma["BBB201A"].secteur.code == "BBB2001"
    assert any("BBB201" in a and "trigramme" in a for a in imp.anomalies)
    assert wcdma["YYY900A"].secteur is None
    # secteurs déduits des cellules seulement
    assert not Secteur.objects.filter(code__in=["AAA1004", "ZZZ9991"]).exists()


def test_secteurs_equivalents(referentiel, exports):
    """Site à 3 secteurs : e4 = e1, D = secteur 1 ; site déporté : e4 / e5 = secteurs 1 / 2."""
    importer(referentiel, exports)
    lte, wcdma = _cellules("LTE"), _cellules("WCDMA")
    assert lte["AAAe4"].secteur.code == "AAA1001" and lte["AAAe4"].secteur_avant is None
    assert lte["DEPe4"].secteur.code == wcdma["DEP400D"].secteur.code == "DEP4001"
    assert lte["DEPe15"].secteur.code == "DEP4002" and lte["DEPe15"].porteuse == 2


@pytest.mark.parametrize("site,lte4,wcdma_d", [
    ("QUA300", "QUAe4", "QUA300D"),   # cellule 3G M
    ("LEB500", "LEBe4", "LEB500D"),   # porteuse LTE e1..e4
    ("MDO600", "MDOe4", "MDO600D"),   # nbSect = 4
])
def test_sites_a_4_secteurs(referentiel, exports, site, lte4, wcdma_d):
    """4 secteurs : D et e4 = secteur 4, et secteur 1 avant le passage à 4 secteurs."""
    imp = importer(referentiel, exports)
    lte, wcdma = _cellules("LTE"), _cellules("WCDMA")
    for cellule in (lte[lte4], wcdma[wcdma_d]):
        assert (cellule.secteur.code, cellule.secteur_avant.code) == (f"{site}4", f"{site}1")
    assert any(f"site {site} : 4 secteurs" in a for a in imp.anomalies)


def test_lettres_d_avant_bascule(referentiel, exports):
    """E, F… n'existent qu'en 3 secteurs : secteur d'avant, sans bascule."""
    importer(referentiel, exports)
    e = _cellules("WCDMA")["MDO600E"]
    assert (e.secteur.code, e.porteuse, e.secteur_avant) == ("MDO6002", 2, None)
    assert _cellules("WCDMA")["QUA300M"].secteur.code == "QUA3004"


def test_date_de_bascule_conservee(referentiel, exports):
    importer(referentiel, exports)
    Site.objects.filter(code_site="MDO600").update(bascule_4_secteurs="2025-03-01")
    imp = importer(referentiel, exports)
    assert str(Site.objects.get(code_site="MDO600").bascule_4_secteurs) == "2025-03-01"
    assert any("MDO600 : 4 secteurs depuis le 01/03/2025" in a for a in imp.anomalies)


def test_reimport_versionne(referentiel, exports, tmp_path):
    importer(referentiel, exports)
    reduit = tmp_path / "reduit.xlsx"
    with pd.ExcelWriter(reduit) as w:
        SITES[SITES.codeSite != "BBB200"].to_excel(w, sheet_name="Site_File", index=False)
    imp = importer(reduit, exports)
    assert ImportReferentiel.objects.count() == 2
    assert {"BBB200", "BBB2001", "BBB2002"} <= set(imp.suppressions)
    assert imp.ajouts == []
    assert not Site.objects.filter(code_site="BBB200").exists()


def test_commande(referentiel, exports, capsys):
    call_command("import_referentiel", str(referentiel), "--cellules", *map(str, exports))
    assert "7 sites, " in capsys.readouterr().out
