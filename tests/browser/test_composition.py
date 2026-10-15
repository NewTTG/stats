"""Parcours des éditeurs et du choix de graphiques dans Chromium."""
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.test import RequestFactory
from django.views.i18n import JavaScriptCatalog

from apps.kpi.composition import initialiser_bibliotheque
from apps.kpi.models import Graphique, ModeleRapport
from tests.test_recherche_regles import ref_recherche  # noqa: F401
from tests.test_recherche_vues import admin, base_recherche  # noqa: F401

pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.django_db


def navigateur(html, verifier, mobile=False):
    i18n = JavaScriptCatalog.as_view()(RequestFactory().get("/admin/jsi18n/")).content
    with pw.sync_playwright() as p:
        exe = shutil.which("chromium") or p.chromium.executable_path
        if not Path(exe).exists(): pytest.skip("Chromium absent")
        browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390 if mobile else 1440, "height": 1000})
        erreurs = []
        page.on("pageerror", lambda e: erreurs.append(str(e)))
        def servir(route):
            chemin = urlsplit(route.request.url).path
            fichier = finders.find(chemin.removeprefix("/static/")) if chemin.startswith("/static/") else None
            if chemin == "/admin/jsi18n/":
                route.fulfill(body=i18n, content_type="application/javascript")
            elif fichier:
                route.fulfill(path=fichier, content_type=mimetypes.guess_type(fichier)[0] or "text/plain")
            else:
                route.fulfill(body=html, content_type="text/html; charset=utf-8")
        page.route("**/*", servir)
        page.goto("http://stats.test/")
        verifier(page)
        assert not erreurs
        browser.close()


@pytest.mark.parametrize("mobile", [False, True])
def test_editeur_graphique_apercu(admin, mobile):
    initialiser_bibliotheque()
    g = Graphique.objects.get(code="lte_volume_dl")
    html = admin.get(reverse("admin:kpi_graphique_change", args=[g.pk])).content.decode()
    def verifier(page):
        page.wait_for_function("window.echarts && echarts.getInstanceByDom(document.getElementById('apercu-graphique'))")
        assert page.locator("#apercu-message").inner_text() == "Aperçu fictif · 2 séries"
        page.locator('[name="series-0-type"]').select_option("aire")
        option = page.locator("#apercu-graphique").evaluate("e => echarts.getInstanceByDom(e).getOption()")
        assert option["series"][0]["type"] == "line" and option["series"][0]["areaStyle"]
        assert option["series"][1]["yAxisIndex"] == 1
        assert page.locator("#apercu-message").inner_text() == "Aperçu fictif · 2 séries"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    navigateur(html, verifier, mobile)


def test_editeur_rapport_recherche_et_ordre(admin):
    initialiser_bibliotheque()
    r = ModeleRapport.objects.get(code="rapport_detail_trafic")
    html = admin.get(reverse("admin:kpi_modelerapport_change", args=[r.pk])).content.decode()
    def verifier(page):
        search = page.get_by_role("searchbox", name="Rechercher un graphique, 3G, 4G, un thème…")
        search.fill("volume et débit cellule DL")
        assert page.locator("#id_graphes > div:visible").count() == 1
        search.fill("")
        first = page.locator('#id_graphes input:checked').first.input_value()
        second = page.locator('#id_graphes input:checked').nth(1).input_value()
        page.locator('#id_graphes > div').filter(has=page.locator('input[value="' + second + '"]')).get_by_role("button", name="Monter").click()
        assert page.locator('#id_graphes input:checked').first.input_value() == second
        values = page.locator("form#modelerapport_form").evaluate("f => new FormData(f).getAll('graphes')")
        assert values[:2] == [second, first]
    navigateur(html, verifier)


def test_accueil_selection_graphique_seul_et_modele(admin, base_recherche):
    html = admin.get("/").content.decode()
    def verifier(page):
        # Le constructeur est dans un tiroir sur l'accueil.
        page.locator('#constructeur').evaluate("f => {let d=f.closest('dialog'); if(d && !d.open) d.showModal();}")
        form = page.locator("#constructeur")
        data = form.evaluate("f => new FormData(f).getAll('graphes')")
        assert data == []  # le modèle conserve aussi ses indicateurs complémentaires
        form.locator('input[name="intention"][value=""]').check()
        form.locator("[data-choix-graphiques]").evaluate("e => e.open=true")
        form.locator("[data-recherche-graphes]").fill("Volume et débit cellule DL")
        form.locator('input[name="graphes"][value="lte_volume_dl"]').check()
        assert form.locator('input[name="graphiques_personnalises"]').is_checked()
        with page.expect_request(lambda r: r.is_navigation_request()) as req:
            form.get_by_role("button", name="Afficher le rapport").click()
        params = parse_qs(urlsplit(req.value.url).query)
        assert params["graphes"] == ["lte_volume_dl"]
        assert params["graphiques_personnalises"] == ["1"]
    navigateur(html, verifier)
