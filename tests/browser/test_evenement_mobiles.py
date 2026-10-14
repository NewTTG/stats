"""Édition d'un événement : remorques disponibles en tête, la remorque ajoutée prend le focus."""
from pathlib import Path
import mimetypes
import re
import shutil
from urllib.parse import urlsplit

import pytest
from django.urls import reverse

from tests.test_service import referentiel  # noqa: F401  (fixture)
from tests.test_sites_mobiles import client_admin, remorque  # noqa: F401  (fixtures)

pw = pytest.importorskip('playwright.sync_api')

pytestmark = pytest.mark.django_db


@pytest.fixture
def page_edition(client_admin, remorque):  # noqa: F811
    html = client_admin.get(reverse('evenements:nouveau')).content.decode()
    url_reseau = re.search(r'data-reseau="([^"]+)"', html).group(1)
    reseau = client_admin.get(url_reseau).content
    from django.contrib.staticfiles import finders
    with pw.sync_playwright() as p:
        executable = shutil.which('chromium') or p.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip('Installer Chromium avec playwright install chromium')
        browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        erreurs = []
        page.on('pageerror', lambda erreur: erreurs.append(str(erreur)))

        def servir(route):
            chemin = urlsplit(route.request.url).path
            if chemin.startswith('/static/'):
                fichier = finders.find(chemin.removeprefix('/static/'))
                if fichier:
                    content_type = mimetypes.guess_type(fichier)[0] or 'text/plain'
                    route.fulfill(path=fichier, content_type=content_type + '; charset=utf-8')
                    return
            if chemin == '/evenement/':
                route.fulfill(body=html, content_type='text/html; charset=utf-8')
            elif chemin == urlsplit(url_reseau).path:
                route.fulfill(body=reseau, content_type='application/json')
            else:
                route.fulfill(status=404)
        page.route('**/*', servir)
        page.goto('http://evenement.test/evenement/')
        yield page
        browser.close()
    assert not erreurs


def test_remorque_ajoutee_visible_et_focalisee(page_edition):
    page = page_edition
    selection = page.locator('[data-selection]')
    assert selection.locator(':scope > *').first.get_attribute('class') == 'ev-mobiles-dispo'
    page.locator('[data-deployer="1RM128"]').click()
    carte = selection.locator('[data-mobile="1RM128"]')
    assert carte.is_visible()
    assert page.evaluate('document.activeElement.dataset.depLat') == '1RM128'
    assert carte.evaluate('''el => { const r = el.getBoundingClientRect();
                                     return r.top >= 0 && r.top < window.innerHeight; }''')
