"""Accueil : valeurs réelles, filtrage des droits, dates et états indisponibles."""
from datetime import date

import pytest
from django.contrib.auth.models import User

from apps.kpi.dashboard import construire
from .test_service import base_kpi, referentiel, lecteur_paita  # noqa: F401

pytestmark = pytest.mark.django_db


def test_dashboard_respecte_perimetre(referentiel, base_kpi, lecteur_paita, monkeypatch):
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: base_kpi)
    monkeypatch.setattr('apps.kpi.dashboard.est_demo', lambda: False)
    d = construire(lecteur_paita, date(2026, 9, 3))
    assert len(d['cartes']) == 1
    assert d['cartes'][0]['texte'] == '100,00'
    assert d['graphiques'][0]['valeurs'] == [100, 100]
    assert d['fin'] == date(2026, 9, 2)


def test_dashboard_sans_droits():
    d = construire(User.objects.create_user('sans-perimetre'), date(2026, 9, 3))
    assert d['cartes'] == [] and d['graphiques'] == [] and d['message']


def test_demo_ancienne_signalee(referentiel, base_kpi, lecteur_paita, monkeypatch):
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: base_kpi)
    monkeypatch.setattr('apps.kpi.dashboard.est_demo', lambda: True)
    monkeypatch.setattr('apps.kpi.dashboard.infos_demo', lambda: {'fin': date(2026, 9, 2)})
    d = construire(lecteur_paita, date(2026, 10, 12), '7j')
    assert d['ancienne'] and d['debut'] == date(2026, 8, 27) and d['fin'] == date(2026, 9, 2)


def test_journee_courante_partielle(referentiel, base_kpi, lecteur_paita, monkeypatch):
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: base_kpi)
    monkeypatch.setattr('apps.kpi.dashboard.est_demo', lambda: False)
    d = construire(lecteur_paita, date(2026, 9, 2), 'aujourdhui')
    assert d['partielle'] and d['debut'] == d['fin'] == date(2026, 9, 2)
