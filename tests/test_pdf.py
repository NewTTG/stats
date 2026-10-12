"""PDF : contenu lisible, rapports planifiés, téléchargement et contrôle d'accès."""
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from pypdf import PdfReader

from apps.evenements.analyse import analyser
from apps.kpi.forms import champs_depuis_requete
from apps.kpi.service import executer
from apps.rapports.models import Rapport, RapportPlanifie
from apps.rapports.pdf import pdf_evenement, pdf_requete
from apps.rapports.planification import lancer_dus

from .test_service import analyste, base_kpi, referentiel, requete  # noqa: F401
from .test_evenements import base_horaire, evenement  # noqa: F401
from .test_rapports_planifies import worker  # noqa: F401

pytestmark = pytest.mark.django_db


def texte(octets):
    reader = PdfReader(BytesIO(octets))
    assert len(reader.pages) >= 1
    return '\n'.join(page.extract_text() for page in reader.pages)


def test_pdf_requete(referentiel, analyste, base_kpi):
    res = executer(requete(perimetre={'type': 'commune', 'valeurs': ['PAITA']}), analyste, base_kpi)
    t = texte(pdf_requete(res))
    assert 'Statistiques KPI réseau' in t and 'Synthèse sur la période' in t
    assert '100' in t and '40' in t and 'BBBe2' in t
    assert 'Annexe' in t and 'Nouméa' in t


def test_pdf_evenement(evenement, base_horaire, analyste):
    t = texte(pdf_evenement(analyser(evenement, analyste, base_horaire)))
    assert 'Foire' in t and 'Synthèse événement / référence' in t
    assert 'Anomalies détectées' in t and 'Référence' in t


def test_pdf_de_bout_en_bout(client, referentiel, analyste, worker):
    client.force_login(analyste)
    r = client.post('/rapports/requete/', {**champs_depuis_requete(requete()), 'format': 'pdf'})
    assert r.status_code == 302
    rapport = Rapport.objects.get()
    assert rapport.format == 'pdf' and rapport.statut == 'termine'
    reponse = client.get(f'/rapports/{rapport.pk}/telecharger/')
    assert reponse['Content-Type'] == 'application/pdf'
    assert 'Statistiques KPI réseau' in texte(b''.join(reponse.streaming_content))
    client.force_login(User.objects.create_user('autre'))
    assert client.get(f'/rapports/{rapport.pk}/telecharger/').status_code == 404


def test_format_invalide(client, analyste):
    client.force_login(analyste)
    assert client.post('/rapports/requete/', {'format': 'html'}).status_code == 404
    assert not Rapport.objects.exists()


def test_pdf_planifie(referentiel, analyste, worker):
    now = datetime(2026, 9, 3, 7, 5, tzinfo=ZoneInfo('Pacific/Noumea'))
    plan = RapportPlanifie.objects.create(utilisateur=analyste, titre='Bilan PDF', format='pdf',
        periode='hier', frequence='quotidienne', prochain_lancement=now,
        requete=requete().model_dump(mode='json', exclude={'periode'}))
    assert lancer_dus(now) == 1
    rapport = Rapport.objects.get(planification=plan)
    assert rapport.format == 'pdf' and rapport.statut == 'termine'
    assert 'Statistiques KPI réseau' in texte(rapport.fichier.read())


def test_filtre_rapports_reste_prive(client, analyste):
    autre = User.objects.create_user('autre-auteur')
    Rapport.objects.create(utilisateur=autre, titre='Confidentiel', nature='requete', format='pdf', statut='termine')
    Rapport.objects.create(utilisateur=analyste, titre='Bilan', nature='requete', format='pdf', statut='en_attente')
    Rapport.objects.create(utilisateur=analyste, titre='Archive', nature='requete', format='xlsx', statut='erreur')
    client.force_login(analyste)
    r = client.get('/rapports/', {'format': 'pdf', 'recherche': 'Bilan'})
    assert r.status_code == 200
    assert r.context['nb_fichiers'] == 2 and r.context['nb_prets'] == 0
    assert [p.titre for p in r.context['rapports']] == ['Bilan']
    assert 'Confidentiel' not in r.content.decode()
