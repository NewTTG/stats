"""Accueil : liste des lieux sous le champ, choix des données et options d'affichage (Chromium)."""
import json
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_recherche_regles import ref_recherche  # noqa: F401  (fixtures)
from tests.test_recherche_vues import admin, base_recherche  # noqa: F401

pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.django_db


@pytest.fixture
def accueil(admin, base_recherche):  # noqa: F811
    html = admin.get("/").content.decode()
    from django.contrib.staticfiles import finders
    with pw.sync_playwright() as p:
        executable = shutil.which("chromium") or p.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip("Installer Chromium avec playwright install chromium")
        browser = p.chromium.launch(executable_path=executable, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        erreurs = []
        page.on("pageerror", lambda erreur: erreurs.append(str(erreur)))

        def servir(route):
            chemin = urlsplit(route.request.url).path
            if chemin.startswith("/static/"):
                fichier = finders.find(chemin.removeprefix("/static/"))
                if fichier:
                    type_ = mimetypes.guess_type(fichier)[0] or "text/plain"
                    route.fulfill(path=fichier, content_type=type_ + "; charset=utf-8")
                    return
            if chemin == "/":
                route.fulfill(body=html, content_type="text/html; charset=utf-8")
            elif chemin.startswith("/suggestions"):
                route.fulfill(body=json.dumps({"lieux": [{"type": "site", "valeur": "KON001",
                                                          "libelle": "Koné Centre (KON001)"}]}),
                              content_type="application/json")
            else:
                route.fulfill(status=204)
        page.route("**/*", servir)
        page.goto("http://stats.test/")
        yield page
        browser.close()
    assert not erreurs


def test_liste_des_lieux_sous_le_champ(accueil):
    page = accueil
    champ, liste = page.locator("#lieu"), page.locator("#lieu-propositions")
    champ.click()
    assert liste.is_visible() and champ.get_attribute("aria-expanded") == "true"
    boite_champ, boite_liste = champ.bounding_box(), liste.bounding_box()
    assert boite_liste["y"] >= boite_champ["y"] + boite_champ["height"]  # sous le champ, même largeur
    assert abs(boite_liste["width"] - boite_champ["width"]) < 2
    ligne = liste.locator("li").first.bounding_box()["height"]
    assert liste.locator("li").count() > 6 and boite_liste["height"] < ligne * 6 + 12  # ~5 lignes, défilement
    assert liste.evaluate("l => l.scrollHeight > l.clientHeight")

    champ.fill("kon")
    assert liste.locator("li").first.locator(".valeur").inner_text().startswith("Koné")
    champ.press("ArrowDown")
    champ.press("Enter")
    assert champ.input_value() == "Koné" and not liste.is_visible()
    champ.type(" et koum")
    liste.locator("li", has_text="Koumac").first.click()
    assert champ.input_value() == "Koné et Koumac"
    champ.press("Escape")
    assert not liste.is_visible()

    champ.fill("KON0")
    page.wait_for_selector("#lieu-propositions li:has-text('KON001')")
    assert liste.locator("li", has_text="KON001").locator(".type").inner_text() == "Site"


def test_donnees_suivent_la_periode_et_les_heures(accueil):
    page = accueil
    jour, heure = page.locator('input[name="donnees"][value="jour"]'), page.locator('input[name="donnees"][value="heure"]')
    assert jour.is_checked()  # 7 derniers jours
    page.locator(".choix-periode label", has_text="Hier").click()
    assert heure.is_checked()
    page.locator(".choix-periode label", has_text="30").click()
    assert jour.is_checked()

    page.locator("details.options-affichage > summary").click()
    page.select_option("#o-heures", "18-22")
    assert heure.is_checked()
    page.locator(".choix-donnees label", has_text="Journalières").click()
    assert page.locator("#o-heures").input_value() == ""

    grille = page.locator(".options-grille").bounding_box()
    resume = page.locator("details.options-affichage > summary").bounding_box()
    assert grille["y"] > resume["y"] + resume["height"] - 1  # sous le titre, pas à côté
    selects = [page.locator(s).bounding_box() for s in ("#o-temps", "#o-espace", "#o-heures")]
    assert len({round(b["y"]) for b in selects}) == 1  # sur une ligne


def test_donnees_non_envoyees_si_non_choisies(accueil):
    page = accueil
    with page.expect_request(lambda r: "intention=" in r.url) as requete:
        page.locator(".actions-constructeur button").click()
    assert "donnees=" not in requete.value.url
    page.go_back()
    page.locator(".choix-donnees label", has_text="Horaires").click()
    with page.expect_request(lambda r: "intention=" in r.url) as requete:
        page.locator(".actions-constructeur button").click()
    assert "donnees=heure" in requete.value.url
