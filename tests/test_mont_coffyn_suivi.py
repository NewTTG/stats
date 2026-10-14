"""Régression : Mont Coffyn, détails ciblés et signalements exploitables."""
from datetime import date
from urllib.parse import urlencode

import pytest
from django.contrib.auth.models import User
from django.http import QueryDict
from django.urls import reverse

from apps.comptes import suivi
from apps.comptes.models import Perimetre
from apps.kpi.recherche import Contexte, avec_parametres
from apps.kpi.recherche.regles import interpreter
from apps.kpi.recherche.texte import Correspondeur, Texte
from apps.referentiel.models import Site
from .test_recherche_regles import ref_recherche
from .test_recherche_vues import admin

pytestmark = pytest.mark.django_db
J = date(2026, 10, 14)
PHRASE = 'pourrais savoir si le site de mont coffyn est saturé ?'


@pytest.fixture
def coffyn(ref_recherche):
    # Conserve les cellules de la fixture pour tester aussi les droits d'accès.
    Site.objects.filter(code_site='NOU001').update(nom='MONT_COFFYN', nom_lte='MONT_COFFYNbb')


@pytest.mark.parametrize('nom', ['mont coffyn', 'Mont-Coffyn', 'MONT_COFFYN', 'MONT_COFFYNbb'])
def test_nom_complet_du_site(coffyn, nom):
    i = interpreter(PHRASE.replace('mont coffyn', nom) + ' ce mois-ci', J, Contexte.pour(None))
    assert i.complete
    assert i.params['perimetre'] == {'type': 'site', 'valeurs': ['NOU001']}
    assert i.params['techno'] == ['LTE']
    assert i.params['periode'] == {'debut': date(2026, 10, 1), 'fin': J}
    assert i.demande.intentions == ['congestion']
    assert i.non_compris == []


def test_choix_ce_mois_ci_conserve_coffyn(coffyn):
    ctx = Contexte.pour(None)
    i = interpreter(PHRASE, J, ctx)
    assert [q.champ for q in i.questions] == ['periode']
    option = next(o for o in i.questions[0].options if o.libelle == 'Ce mois-ci')
    i = avec_parametres(i, QueryDict(urlencode(option.params, doseq=True)), ctx, J)
    assert i.complete and not i.non_compris
    assert i.params['perimetre'] == {'type': 'site', 'valeurs': ['NOU001']}


@pytest.mark.parametrize('nom', ['Mont-Dore', "mont d’or", "mont d or"])
def test_mont_dore_reste_reconnu(coffyn, nom):
    i = interpreter(f'congestion {nom} ce mois-ci', J, Contexte.pour(None))
    assert i.complete and i.params['perimetre'] == {'type': 'commune', 'valeurs': ['MONT DORE']}


def test_alias_ne_capture_pas_le_mot_mont_seul():
    c = Correspondeur()
    c.ajouter('mont d or', 'Mont-Dore')
    assert not c.trouver(Texte('mont coffyn'))
    assert c.trouver(Texte("mont d'or"))[0][1] == ['Mont-Dore']


def test_site_complet_avant_commune_incluse(coffyn):
    i = interpreter('congestion la foa village hier', J, Contexte.pour(None))
    assert i.params['perimetre'] == {'type': 'site', 'valeurs': ['FOA001']}


@pytest.mark.parametrize('nom', ['mont coffyn', 'mont inconnu'])
def test_site_hors_perimetre_ou_inconnu_pose_une_question(coffyn, nom):
    lecteur = User.objects.create_user('lecteur')
    Perimetre.objects.create(nom='Païta', communes=['PAITA']).utilisateurs.add(lecteur)
    i = interpreter(f'le site de {nom} est saturé ce mois-ci', J, Contexte.pour(lecteur))
    assert not i.complete
    assert any(q.champ == 'perimetre' for q in i.questions)
    assert not any(o.params.get('perimetre_valeurs') == ['NOU001'] for q in i.questions for o in q.options)
    assert 'perimetre' not in i.params


def test_detail_selection_avant_historique_et_sans_autre_demande(admin):
    user = User.objects.get(username='admin')
    parent = suivi.commencer(user, 'recherche', 'Question initiale unique', {})
    selection = suivi.commencer(user, 'recherche', PHRASE, {'periode': ['mois_courant']}, parent)
    selection.interpretation = {'non_compris': ['coffyn'], 'compris': [{'libelle': 'Mont-Dore'}]}
    selection.save(update_fields=['interpretation'])
    suivi.commencer(user, 'recherche', 'Demande sans rapport avec ce parcours', {})
    response = admin.get(reverse('admin:comptes_demandesuivie_change', args=[selection.pk]))
    html = response.content.decode()
    assert response.status_code == 200
    assert html.index(f'id="etape-{selection.pk}"') < html.index('class="suivi-historique"')
    assert html.count(f'id="etape-{selection.pk}"') == 1
    assert '<details class="suivi-historique">' in html
    assert 'Demande sans rapport avec ce parcours' not in html
    texte = response.context['texte_transmission']
    assert PHRASE in texte and 'coffyn' in texte and 'Mont-Dore' in texte
    assert 'Vérifier les mots non reconnus' in texte and 'Comportement attendu' in texte
    selection.refresh_from_db()
    assert selection.interpretation['compris'] == [{'libelle': 'Mont-Dore'}]  # trace immuable


def test_selection_visible_au_dela_de_trente_etapes(admin):
    user = User.objects.get(username='admin')
    parent = suivi.commencer(user, 'recherche', 'Début du parcours', {})
    selection = parent
    for n in range(33):
        selection = suivi.commencer(user, 'recherche', f'Étape {n}', {}, selection)
    url = reverse('admin:comptes_demandesuivie_change', args=[selection.pk])
    for params in ({}, {'page': 2}, {'page': 'invalide'}):
        response = admin.get(url, params)
        html = response.content.decode()
        assert html.count(f'id="etape-{selection.pk}"') == 1
        assert html.index(f'id="etape-{selection.pk}"') < html.index('class="suivi-historique"')
        assert response.context['nombre_etapes'] == 34


def test_signalement_echappe_et_limite_a_la_selection(admin):
    user = User.objects.get(username='admin')
    d = suivi.commencer(user, 'recherche', '</textarea><script>alert(1)</script>', {})
    response = admin.get(reverse('admin:comptes_demandesuivie_change', args=[d.pk]))
    assert '<script>alert(1)</script>' not in response.content.decode()
    assert '&lt;/textarea&gt;' in response.content.decode()
    assert response.context['pistes'] == []
    assert 'suivi-historique' not in response.content.decode()
