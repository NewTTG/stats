"""Graphiques thématiques des rapports « 4G détaillée » dans Chromium : barres, barres empilées et
courbes sur deux axes, un graphique par entité (liste). Facultatif : pip install playwright."""
import mimetypes
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_recherche_regles import ref_recherche  # noqa: F401  (fixtures)
from tests.test_recherche_vues import admin, base_recherche  # noqa: F401

pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.django_db


def _page_resultat(admin, params, appel):  # noqa: F811
    html = admin.get("/", params).content.decode()
    from django.contrib.staticfiles import finders
    with pw.sync_playwright() as p:
        executable = shutil.which("chromium") or p.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip("Installer Chromium avec playwright install chromium")
        browser = p.chromium.launch(executable_path=executable, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1000}, reduced_motion="reduce")
        erreurs = []
        page.on("pageerror", lambda erreur: erreurs.append(str(erreur)))

        def servir(route):
            chemin = urlsplit(route.request.url).path
            fichier = finders.find(chemin.removeprefix("/static/")) if chemin.startswith("/static/") else None
            if fichier:
                type_ = mimetypes.guess_type(fichier)[0] or "text/plain"
                route.fulfill(path=fichier, content_type=type_ + "; charset=utf-8")
            elif chemin == "/":
                route.fulfill(body=html, content_type="text/html; charset=utf-8")
            else:
                route.fulfill(status=204)
        page.route("**/*", servir)
        page.goto("http://stats.test/")
        appel(page)
        browser.close()
    assert not erreurs


def _option(page, selecteur):
    return page.locator(selecteur).evaluate("e => echarts.getInstanceByDom(e).getOption()")


def test_graphiques_par_theme_et_par_site(admin, base_recherche):  # noqa: F811
    def verifier(page):
        zone = page.locator("[data-graphes-themes]")
        graphes = zone.locator(".graphique")
        assert graphes.count() == 14  # thème Trafic et charge
        assert zone.locator("h4").all_inner_texts() == ["TRAFIC ET CHARGE"]
        # « Volume et débit cellule DL » : volume en barres à gauche, débit en courbe à droite.
        volume = page.locator('.graphique[aria-label="Volume et débit cellule DL"]')
        option = _option(page, '.graphique[aria-label="Volume et débit cellule DL"]')
        assert [s["type"] for s in option["series"]] == ["bar", "line"]
        assert [s["yAxisIndex"] for s in option["series"]] == [0, 1]
        assert [a["name"] for a in option["yAxis"]] == ["Mo", "Mbps"] or option["yAxis"][0]["name"] in ("Go", "To")
        motifs = _option(page, '.graphique[aria-label="Connexions RRC par motif"]')
        assert {s.get("stack") for s in motifs["series"]} == {"pile"}
        # Un graphique par site : la liste change les données de tous les graphiques.
        choix = page.locator("[data-graphes-entite]")
        assert choix.locator("option").count() > 1
        avant = option["series"][0]["data"]
        choix.select_option(index=1)
        apres = _option(page, '.graphique[aria-label="Volume et débit cellule DL"]')["series"][0]["data"]
        assert apres != avant
        if os.environ.get("CAPTURE_GRAPHES"):
            volume.scroll_into_view_if_needed()
            page.screenshot(path=os.environ["CAPTURE_GRAPHES"], full_page=True)

    _page_resultat(admin, {"q": "Nouméa", "intention": "rapport_lte_trafic", "periode": "semaine_derniere",
                           "granularite_espace": "site"}, verifier)
