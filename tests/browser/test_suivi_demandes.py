"""Affichage ciblé, historique et copie sur HTTP (sans API presse-papiers)."""
from pathlib import Path
import mimetypes
import shutil
from urllib.parse import urlsplit

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from apps.comptes import suivi
from tests.test_recherche_vues import admin

pw = pytest.importorskip('playwright.sync_api')

pytestmark = pytest.mark.django_db


@pytest.fixture
def page_suivi(admin):
    user = User.objects.get(username='admin')
    parent = suivi.commencer(user, 'recherche', 'Première question du parcours', {})
    d = suivi.commencer(user, 'recherche', 'pourrais savoir si le site de mont coffyn est saturé ?', {}, parent)
    d.interpretation = {'compris': [{'libelle': 'Mont-Dore', 'defaut': False}], 'non_compris': ['coffyn']}
    d.save(update_fields=['interpretation'])
    html = admin.get(reverse('admin:comptes_demandesuivie_change', args=[d.pk])).content.decode()
    from django.contrib.staticfiles import finders
    # Démarrer Playwright après les lectures Django et l'arrêter avant le rollback.
    with pw.sync_playwright() as p:
        executable = shutil.which('chromium') or p.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip('Installer Chromium avec playwright install chromium')
        browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
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
            if chemin == '/demande/':
                route.fulfill(body=html, content_type='text/html; charset=utf-8')
            else:
                route.fulfill(status=404)
        page.route('**/*', servir)
        page.goto('http://suivi.test/demande/')
        yield page
        browser.close()
    assert not erreurs


def test_detail_et_historique_replie(page_suivi):
    page = page_suivi
    assert page.locator('.suivi-etape:visible').count() == 1
    assert page.locator('.suivi-etape.selectionnee').is_visible()
    page.locator('.suivi-historique > summary').click()
    assert page.locator('.suivi-etape:visible').count() == 2
    assert page.locator('.suivi-historique a').first.is_visible()


def test_detail_mobile_sans_debordement(page_suivi):
    page = page_suivi
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.locator('.suivi-etape.selectionnee').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


@pytest.mark.parametrize('mode', ['moderne', 'absent', 'refuse', 'echec'])
def test_copie_du_texte_edite_et_repli_http(page_suivi, mode):
    page = page_suivi
    page.evaluate('''mode => {
      Object.defineProperty(navigator, 'clipboard', {configurable: true, value:
        mode === 'absent' ? undefined : {writeText: async texte => {
          if (mode !== 'moderne') throw new Error('Refus');
          window.texteCopie = texte;
        }}});
      document.execCommand = commande => {
        if (mode === 'echec') return false;
        window.texteCopie = document.activeElement.value;
        return commande === 'copy';
      };
    }''', mode)
    texte = 'Comportement attendu : reconnaître Mont Coffyn.'
    page.locator('#texte-transmission').fill(texte)
    page.locator('[data-copier-demande]').click()
    if mode != 'echec':
        assert page.evaluate('window.texteCopie') == texte
        assert 'Texte copié' in page.locator('[role="status"]').inner_text()
    else:
        assert 'Ctrl+C' in page.locator('[role="status"]').inner_text()
        assert page.locator('#texte-transmission').evaluate('(e) => e.selectionEnd - e.selectionStart') == len(texte)
    assert page.locator('[data-copier-demande]').is_enabled()


def test_copie_http_native(page_suivi):
    page = page_suivi
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true})")
    page.locator('#texte-transmission').fill('Dro 3G Nouméa semaine dernière')
    page.locator('[data-copier-demande]').click()
    assert 'Texte copié' in page.locator('[data-statut-copie]').inner_text()
