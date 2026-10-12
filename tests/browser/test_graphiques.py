"""Interactions réelles ECharts. Facultatif : pip install playwright ; playwright install chromium.

Exécution : pytest tests/browser/test_graphiques.py (ou Chromium système installé).
"""
import json
import shutil
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def navigateur():
    with pw.sync_playwright() as p:
        executable = shutil.which("chromium") or p.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip("Installer Chromium avec playwright install chromium")
        browser = p.chromium.launch(executable_path=executable, args=["--no-sandbox"])
        yield browser
        browser.close()


@pytest.fixture
def page(navigateur):
    page = navigateur.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    erreurs = []
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    cles = [f"2026-10-12T{h:02}:00:00" for h in range(3)]
    kpi = {"titre": "Coupure data 3G", "unite": "%", "zero": True,
           "seuils": {"alerte": .15, "critique": .3},
           "series": [{"nom": "Réseau", "valeurs": [.1, .2, .25]}]}
    sources = {
        "courbes-a": {"periodes": ["00h", "01h", "02h"], "periodes_cles": cles, "kpis": [kpi]},
        "courbes-b": {"periodes": ["12/10 02h", "13/10 01h"],
                      "periodes_cles": [cles[2], "2026-10-13T01:00:00"], "kpis": [dict(kpi, titre="Autre technologie", series=[{"nom": "Réseau", "valeurs": [.2, None]}])]},
        "causes": {"titre": "Causes", "par": "période", "unite": "%", "axe": ["12/10 00h", "12/10 02h"],
                   "periodes_cles": [cles[0], cles[2]], "series": [{"nom": "Radio", "valeurs": [.1, .2]}]},
        "spatial": {"titre": "Sites", "par": "entité", "unite": "%", "axe": ["Site A", "Site B"],
                    "series": [{"nom": "Radio", "valeurs": [.1, .2]}]},
        "dashboard-data": [{"titre": "Trafic", "unite": "Go", "periodes": ["00:00", "01:00", "02:00"],
                            "periodes_cles": cles, "valeurs": [1, 2, 3]}],
        "evenement": {"instants": ["12/10 00h", "12/10 01h"], "kpis": [{"titre": "Événement", "unite": "%", "evenement": [1, 2], "reference": [2, 3], "min": [1, 2], "max": [3, 4]}]},
    }
    html = '<body class="workspace"><main style="max-width:1100px;margin:auto">'
    for ident, data in sources.items():
        html += f'<script id="{ident}" type="application/json">{json.dumps(data)}</script>'
    html += '<div class="graphiques" data-source="courbes-a"></div><div class="graphiques" data-source="courbes-b"></div>'
    html += '<div><div class="graphique graphique-causes" data-source="causes"></div></div>'
    html += '<div><div class="graphique graphique-causes" data-source="spatial"></div></div>'
    html += '<div><div class="dashboard-chart" data-index="0"></div></div><div class="graphiques courbes" data-source="evenement"></div></main></body>'
    page.set_content(html)
    for name in ("app", "workspace"):
        page.add_style_tag(path=str(RACINE / f"static/css/{name}.css"))
    for name in ("vendor/echarts-5.6.0.min.js", "js/kpi.js"):
        page.add_script_tag(path=str(RACINE / f"static/{name}"))
    yield page
    page.close()
    assert not erreurs


def option(page, selector):
    return page.locator(selector).evaluate("e => echarts.getInstanceByDom(e).getOption()")


def clic_periode(page, selector, index):
    div = page.locator(selector)
    div.scroll_into_view_if_needed()
    point = div.evaluate("""(e, i) => {
        const g = echarts.getInstanceByDom(e);
        const r = g.getModel().getComponent('grid').coordinateSystem.getRect();
        return [g.convertToPixel({xAxisIndex:0}, i), r.y + r.height/2];
    }""", index)
    rect = div.bounding_box()
    page.mouse.click(rect["x"] + point[0], rect["y"] + point[1])


def test_selection_synchronisee_et_reset(page):
    a = '.graphiques[data-source="courbes-a"] .graphique'
    b = '.graphiques[data-source="courbes-b"] .graphique'
    clic_periode(page, a, 2)
    pw.expect(page.locator("dialog")).to_have_count(0)
    assert option(page, a)["series"][0]["markPoint"]["data"][0]["coord"] == [2, .25]
    assert option(page, b)["series"][0]["markPoint"]["data"][0]["coord"] == [0, .2]
    bars = option(page, '[data-source="causes"]')["series"][0]["data"]
    assert bars[0]["itemStyle"]["opacity"] < bars[1]["itemStyle"]["opacity"]
    assert option(page, ".dashboard-chart")["series"][0]["markPoint"]["data"][0]["coord"] == [2, 3]
    # Une autre heure remplace la sélection ; la même étiquette sur un autre jour ne correspond pas.
    clic_periode(page, a, 1)
    assert option(page, b)["series"][0]["markPoint"]["data"] == []
    clic_periode(page, a, 1)
    assert option(page, a)["series"][0]["markPoint"]["data"] == []
    assert len(option(page, a)["series"][0]["markLine"]["data"]) == 2  # seuils conservés
    assert option(page, a)["series"][0]["lineStyle"]["opacity"] == 1
    # Cliquer directement le libellé de l'heure sélectionne aussi sans popup.
    div = page.locator(a)
    div.scroll_into_view_if_needed()
    point = div.evaluate("""e => {
        const g = echarts.getInstanceByDom(e);
        const r = g.getModel().getComponent('grid').coordinateSystem.getRect();
        return [g.convertToPixel({xAxisIndex:0}, 1), r.y + r.height + 14];
    }""")
    rect = div.bounding_box()
    page.mouse.click(rect["x"] + point[0], rect["y"] + point[1])
    assert option(page, a)["series"][0]["markPoint"]["data"][0]["coord"] == [1, .2]
    pw.expect(page.locator("dialog")).to_have_count(0)
    # Les courbes sans symboles (tableau de bord) restent cliquables.
    clic_periode(page, ".dashboard-chart", 1)
    assert option(page, a)["series"][0]["markPoint"]["data"] == []


def test_popup_clavier_fermeture_et_mobile(page):
    bouton = page.get_by_role("button", name="Agrandir : Coupure data 3G", exact=True)
    bouton.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog")
    pw.expect(dialog).to_be_visible()
    assert [d["value"] for d in option(page, ".graphique-popup-canvas")["series"][0]["data"]] == [.1, .2, .25]
    page.locator("dialog select").select_option("1")
    assert option(page, '.graphiques[data-source="courbes-a"] .graphique')["series"][0]["markPoint"]["data"]
    page.keyboard.press("Escape")
    pw.expect(dialog).not_to_be_visible()
    pw.expect(bouton).to_be_focused()
    bouton.click()
    page.get_by_role("button", name="Fermer le graphique agrandi").click()
    pw.expect(dialog).not_to_be_visible()
    bouton.click()
    page.mouse.click(2, 2)
    pw.expect(dialog).not_to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    bouton.click()
    page.wait_for_timeout(160)
    bounds = dialog.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
    assert page.locator(".graphique-popup-canvas canvas").bounding_box()["width"] > 300
    page.keyboard.press("Escape")
    page.locator('.graphiques[data-source="courbes-a"] select').select_option("1")
    assert option(page, '.graphiques[data-source="courbes-a"] .graphique')["series"][0]["markPoint"]["data"] == []
    # Un clic dans le fond du graphique donne aussi accès à l'agrandissement.
    div = page.locator('.graphiques[data-source="courbes-a"] .graphique')
    div.click(position={"x": div.bounding_box()["width"] - 5, "y": 5})
    pw.expect(dialog).to_be_visible()


def test_evenement_et_entites(page):
    page.locator(".courbes select").select_option("1")
    series = option(page, ".courbes .graphique")["series"]
    assert series[0]["lineStyle"]["opacity"] == series[1]["lineStyle"]["opacity"] == 0
    assert series[0]["markPoint"]["data"] == []
    assert series[3]["markPoint"]["data"][0]["coord"] == [1, 2]
    page.get_by_role("button", name="Agrandir : Événement", exact=True).click()
    page.get_by_role("button", name="Effacer la sélection", exact=True).last.click()
    assert option(page, ".courbes .graphique")["series"][3]["markPoint"]["data"] == []
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Agrandir : Sites · par entité", exact=True).click()
    pw.expect(page.get_by_role("dialog")).to_be_visible()
    assert option(page, ".graphique-popup-canvas")["series"][0]["data"] == [.1, .2]
