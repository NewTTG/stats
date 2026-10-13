"""Traçabilité de bout en bout, suivi des choix et accès administrateur aux archives."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from sqlalchemy.exc import SQLAlchemyError

from apps.comptes.models import DemandeSuivie
from apps.comptes import suivi
from apps.kpi.recherche import Contexte
from apps.kpi.recherche.regles import interpreter
from apps.referentiel.models import Site
from apps.kpi.recherche.dates import extraire_periode
from apps.kpi.recherche.texte import Texte
from apps.rapports.models import Rapport
from apps.rapports.lancement import lancer
from apps.rapports.taches import generer
from .test_recherche_regles import ref_recherche, J
from .test_recherche_vues import admin, base_recherche, _liens

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('mot', ['auj', 'auj.', 'AUJ', 'ajd', "aujourd’hui"])
def test_abreviations_aujourdhui(mot):
    texte = Texte(f'stats de velodrome {mot}')
    periode, notes = extraire_periode(texte, J)
    assert (periode.debut, periode.fin) == (J, J)
    assert not notes


def test_abreviation_ne_capture_pas_un_nom():
    assert extraire_periode(Texte('stats de aujardin'), J)[0] is None


def test_precision_puis_succes_et_rapport(admin, base_recherche, monkeypatch):
    reponse = admin.get('/', {'q': 'débit 4G Païta'})
    initiale = DemandeSuivie.objects.get()
    assert initiale.statut == 'a_preciser'
    assert initiale.interpretation['questions'][0]['texte'] == 'Sur quelle période ?'
    lien = _liens(reponse.content.decode(), '7 derniers jours')[0]
    assert 'suivi=' in lien
    reponse = admin.get('/' + lien)
    suite = DemandeSuivie.objects.exclude(pk=initiale.pk).get()
    assert suite.parent == initiale and suite.parcours == initiale.parcours
    assert suite.statut == 'reussie' and suite.resultat['lignes'] > 0
    assert initiale.interpretation['questions']  # le succès n’écrase pas la question initiale
    params = {k: v for k, v in reponse.context['requete_params']}
    monkeypatch.setattr('apps.rapports.lancement.async_task', lambda *a, **kw: None)
    assert admin.post('/rapports/requete/', {**params, 'format': 'pdf'}).status_code == 302
    rapport = Rapport.objects.get()
    assert rapport.demande.parent == suite
    assert rapport.demande.parcours == initiale.parcours
    monkeypatch.setattr('apps.rapports.taches.contenu', lambda r: b'%PDF-1.7 test')
    generer(rapport.pk)
    rapport.refresh_from_db()
    assert rapport.statut == 'termine' and rapport.demande.statut == 'reussie'
    html = admin.get(reverse('admin:comptes_demandesuivie_change', args=[suite.pk])).content.decode()
    assert 'Sur quelle période ?' in html and 'Choix repris' in html and '7 derniers jours' in html
    assert 'Télécharger PDF' in html and 'Un résultat a été obtenu' in html


def test_auj_dans_recherche_complete(admin, base_recherche):
    response = admin.get('/', {'q': 'stats de Païta auj.'})
    trace = DemandeSuivie.objects.get()
    assert response.status_code == 200
    assert trace.interpretation['requete']['periode'] == {'debut': J.isoformat(), 'fin': J.isoformat()}
    assert not trace.interpretation['questions']
    assert trace.statut == 'sans_donnees'  # la base synthétique s’arrête à hier


def test_erreurs_et_requetes_invalides(admin, base_recherche, monkeypatch):
    monkeypatch.setattr('apps.kpi.views.executer', lambda *a: (_ for _ in ()).throw(SQLAlchemyError('secret SQL')))
    assert admin.get('/', {'q': 'débit 4G Païta hier'}).status_code == 503
    trace = DemandeSuivie.objects.get()
    assert trace.statut == 'erreur' and 'secret SQL' not in trace.message
    admin.get('/', {'debut': 'invalide', 'fin': '2026-10-08'})
    assert DemandeSuivie.objects.first().statut == 'erreur'


def test_exception_inattendue_tracee(admin, base_recherche, monkeypatch):
    monkeypatch.setattr('apps.kpi.views.interpreter', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('incident')))
    with pytest.raises(RuntimeError):
        admin.get('/', {'q': 'débit Païta'})
    assert DemandeSuivie.objects.get().statut == 'erreur'


def test_export_archive_le_fichier_exact(admin, base_recherche):
    response = admin.get('/', {'q': 'débit 4G Païta hier', 'export': 'xlsx'})
    assert response.status_code == 200
    rapport = Rapport.objects.get()
    assert rapport.format == 'xlsx' and rapport.statut == 'termine'
    assert rapport.demande.nature == 'export' and rapport.demande.statut == 'reussie'
    with rapport.fichier.open('rb') as f:
        assert f.read() == response.content
    dl = admin.get(reverse('admin:rapports_rapport_telecharger', args=[rapport.pk]))
    assert b''.join(dl.streaming_content) == response.content


@pytest.mark.parametrize('identifiant', ['invalide', str(uuid4()), 'autre'])
def test_aucun_rattachement_a_un_autre_utilisateur(admin, base_recherche, identifiant):
    autre = User.objects.create_user('autre')
    origine = suivi.commencer(autre, 'recherche', 'Demande privée', {})
    admin.get('/', {'q': 'débit Païta', 'suivi': str(origine.pk) if identifiant == 'autre' else identifiant})
    nouvelle = DemandeSuivie.objects.exclude(pk=origine.pk).get()
    assert nouvelle.parent_id is None and nouvelle.parcours != origine.parcours


def test_deux_onglets_restent_independants(admin, base_recherche):
    a = admin.get('/', {'q': 'débit Païta'})
    b = admin.get('/', {'q': 'trafic Nouméa'})
    origines = list(DemandeSuivie.objects.order_by('creee_le'))
    for response in (b, a):
        admin.get('/' + _liens(response.content.decode(), '7 derniers jours')[0])
    assert all(d.suites.count() == 1 for d in origines)
    assert origines[0].parcours != origines[1].parcours


def test_file_attente_et_echec_worker(admin, monkeypatch):
    user = User.objects.get(username='admin')
    rapport = Rapport.objects.create(utilisateur=user, titre='Rapport', nature='requete', format='pdf')
    monkeypatch.setattr('apps.rapports.lancement.async_task', lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert lancer(rapport) is False
    assert rapport.demande.statut == 'erreur'
    monkeypatch.setattr('apps.rapports.taches.contenu', lambda r: (_ for _ in ()).throw(RuntimeError()))
    generer(rapport.pk)
    rapport.refresh_from_db()
    assert rapport.demande.statut == 'erreur' and rapport.demande.terminee_le


def test_admin_permissions_filtres_et_compteurs(client):
    user = User.objects.create_user('support', is_staff=True)
    client.force_login(user)
    d = suivi.commencer(user, 'recherche', '<script>alert(1)</script>', {})
    suivi.terminer(d, 'a_preciser')
    suite = suivi.commencer(user, 'recherche', 'Précision', {}, d)
    suivi.terminer(suite, 'reussie')
    suivi.commencer(user, 'recherche', 'Deuxième précision', {}, d)
    detail = reverse('admin:comptes_demandesuivie_change', args=[d.pk])
    liste = reverse('admin:comptes_demandesuivie_changelist')
    assert client.get(detail).status_code == 403
    assert client.get(liste).status_code == 403
    assert b'Suivi des demandes' not in client.get('/admin/').content
    user.user_permissions.add(Permission.objects.get(codename='view_demandesuivie'))
    html = client.get(detail).content.decode()
    assert '&lt;script&gt;' in html and '<script>alert(1)</script>' not in html
    assert client.post(detail, {}).status_code == 403
    stats = client.get('/admin/').context['suivi_stats']
    assert stats['total'] == 3 and stats['a_preciser'] == 0 and stats['reussies'] == 1
    assert client.get(liste, {'suite': 'recuperee'}).context['cl'].result_count == 1
    assert client.get(liste, {'suite': 'sans_suite'}).context['cl'].result_count == 0
    assert client.get(liste, {'statut__exact': 'reussie', 'q': 'support'}).context['cl'].result_count == 1
    assert client.get(liste, {'creee_le__gte': (timezone.now()-timedelta(days=7)).isoformat()}).status_code == 200


def test_fichier_admin_protege_et_introuvable(client):
    user = User.objects.create_user('staff', is_staff=True)
    client.force_login(user)
    rapport = Rapport.objects.create(utilisateur=user, titre='Archive', nature='requete', format='pdf', statut='termine')
    rapport.fichier.save('archive.pdf', ContentFile(b'archive'))
    url = reverse('admin:rapports_rapport_telecharger', args=[rapport.pk])
    user.user_permissions.add(Permission.objects.get(codename='view_demandesuivie'))
    assert client.get(url).status_code == 403
    user.user_permissions.add(Permission.objects.get(codename='view_rapport'))
    assert b''.join(client.get(url).streaming_content) == b'archive'
    rapport.fichier.storage.delete(rapport.fichier.name)
    assert client.get(url).status_code == 404


def test_accueil_et_autocompletion_ne_creent_pas_de_demande(admin, base_recherche):
    admin.get('/')
    admin.get('/suggestions/', {'q': 'Païta'})
    admin.head('/', {'q': 'débit Païta'})
    assert not DemandeSuivie.objects.exists()


def test_phrase_velodrome_exacte(ref_recherche):
    Site.objects.filter(code_site='PAI001').update(nom='VELODROME')
    interp = interpreter('stats de velodrome auj', J, Contexte.pour(None))
    assert interp.complete
    assert interp.params['periode'] == {'debut': J, 'fin': J}
    assert interp.params['perimetre']['valeurs'] == ['PAI001']
    assert len(interp.params['kpis']) > 5
    precis = interpreter('stats du débit velodrome auj', J, Contexte.pour(None))
    assert precis.demande.intentions == ['debit']
