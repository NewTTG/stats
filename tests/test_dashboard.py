"""Accueil : valeurs réelles, filtrage des droits, dates et états indisponibles."""
from datetime import date, datetime, timedelta
from unittest.mock import Mock

import pandas as pd
import pytest
import sqlalchemy as sa
from django.contrib.auth.models import User
from psycopg.errors import ConnectionTimeout

from apps.kpi.dashboard import construire
from apps.kpi.forms import RequeteForm
from apps.kpi.requete import RequeteKpi
from apps.kpi.service import executer
from apps.kpi.source import dernieres_heures
from .test_service import base_kpi, referentiel, lecteur_paita  # noqa: F401

pytestmark = pytest.mark.django_db


def test_dashboard_respecte_perimetre(referentiel, base_kpi, lecteur_paita, monkeypatch):
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: base_kpi)
    monkeypatch.setattr('apps.kpi.dashboard.est_demo', lambda: False)
    d = construire(lecteur_paita, date(2026, 9, 3), 'hier')
    assert len(d['cartes']) == 1
    assert d['cartes'][0]['texte'] == '100,00'
    assert d['graphiques'][0]['valeurs'] == [100, 100]
    assert d['graphiques'][0]['periodes_cles'] == ['2026-09-02T00:00:00', '2026-09-02T19:00:00']
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


@pytest.fixture
def historique_horaire(monkeypatch):
    engine = sa.create_engine('sqlite://', poolclass=sa.pool.StaticPool)
    # Deux cellules par heure et un trou : prendre 24 lignes ou un jour civil serait faux.
    heures_lte = [datetime(2026, 10, 10, 8) - timedelta(hours=i) for i in range(31) if i != 5]
    heures_3g = [h - timedelta(days=2) for h in heures_lte]
    pd.DataFrame([{'EutranCell_Id': cell, 'DateHour': h, 'PayloadDl_mB': montant}
                  for h in heures_lte for cell, montant in [('AAAe1', 1), ('BBBe1', 2)]]).to_sql(
                      'lte_cell_hour', engine, index=False)
    pd.DataFrame([{'CellWcdma': 'AAAw1', 'DateHour': h, 'PayloadPsHs_mb': 3}
                  for h in heures_3g]).to_sql('wcdma_cell_hour', engine, index=False)
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: engine)
    monkeypatch.setattr('apps.kpi.dashboard.INDICATEURS', [
        ('lte_payload_dl', 'Volume data 4G', '4G', 'data'),
        ('wcdma_payload_hs', 'Volume data 3G', '3G', 'data'),
    ])
    return engine, sorted(heures_lte, reverse=True)[:24], sorted(heures_3g, reverse=True)[:24]


def test_24_heures_disponibles_independantes_et_liens_exacts(historique_horaire, client, monkeypatch):
    engine, heures_lte, heures_3g = historique_horaire
    user = User.objects.create_superuser('admin24h', password='secret')
    d = construire(user, date(2026, 10, 13))
    assert d['selection'] == '24h' and not d['ancienne'] and not d['partielle']
    assert [p['nombre'] for p in d['periodes']] == [24, 24]
    assert [p['fin'] for p in d['periodes']] == [heures_lte[0], heures_3g[0]]
    assert [c['texte'] for c in d['cartes']] == ['72', '72']
    for graphe, heures in zip(d['graphiques'], [heures_lte, heures_3g]):
        assert graphe['periodes_cles'] == [h.isoformat() for h in sorted(heures)]
        assert len(graphe['valeurs']) == 24
        assert graphe['periodes'][0] == min(heures).strftime('%d/%m %H:%M')
        from django.http import QueryDict
        form = RequeteForm(QueryDict(graphe['lien'][1:]))
        assert form.is_valid(), form.errors
        req = RequeteKpi(**form.vers_requete())
        res = executer(req, user, engine).par_techno[0]
        assert res.synthese_globale[graphe['code']] == 72
    # Vérifie l'intégration : accueil par défaut, puis clic sur Analyser.
    client.force_login(user)
    monkeypatch.setattr('apps.kpi.views.moteur_kpi', lambda: engine)
    accueil = client.get('/')
    assert accueil.status_code == 200
    assert accueil.context['dashboard']['selection'] == '24h'
    assert '24 dernières heures disponibles' in accueil.content.decode()
    analyse = client.get('/' + d['graphiques'][0]['lien'])
    assert analyse.status_code == 200
    assert analyse.context['resultat'].par_techno[0].synthese_globale['lte_payload_dl'] == 72
    export = client.get('/' + d['graphiques'][0]['lien'] + '&export=xlsx')
    assert export.status_code == 200
    assert export['Content-Type'].endswith('spreadsheetml.sheet')


def test_24_heures_filtrees_par_droits(referentiel, base_kpi, lecteur_paita, monkeypatch):
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: base_kpi)
    # Une heure plus récente hors du périmètre ne doit pas modifier les bornes affichées.
    with base_kpi.begin() as conn:
        conn.execute(sa.text('INSERT INTO lte_cell_hour VALUES (:cell, :heure, 100, 99, 10)'),
                     {'cell': 'AAAe1', 'heure': '2026-10-12 20:00:00.000000'})
    d = construire(lecteur_paita, date(2026, 10, 13))
    assert d['periodes'][0]['nombre'] == 4
    assert d['periodes'][0]['fin'] == datetime(2026, 9, 2, 19)
    assert d['graphiques'][0]['valeurs'] == [100] * 4
    assert dernieres_heures(base_kpi, 'WCDMA', []) == []


def test_techno_vide_ne_masque_pas_l_autre(historique_horaire):
    engine, _, _ = historique_horaire
    with engine.begin() as conn:
        conn.execute(sa.text('DELETE FROM wcdma_cell_hour'))
    user = User.objects.create_superuser('admin-vide')
    d = construire(user, date(2026, 10, 13))
    assert len(d['cartes']) == 1 and len(d['graphiques']) == 1
    assert d['periodes'][0]['techno'] == '4G'
    assert any('WCDMA' in a for a in d['avertissements'])


def test_source_absente(monkeypatch):
    from apps.kpi.source import BaseKpiNonConfiguree
    def absente():
        raise BaseKpiNonConfiguree('non configurée')
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', absente)
    d = construire(User.objects.create_superuser('admin-source'), date(2026, 10, 13))
    assert d['message'] and not d['cartes'] and not d['graphiques']


@pytest.mark.parametrize('selection', ['24h', 'hier', 'aujourdhui', '7j'])
def test_timeout_connexion_une_seule_tentative(selection, client, monkeypatch, caplog):
    # SQLAlchemy enveloppe réellement le timeout psycopg, comme dans le journal
    # de production ; aucun accès réseau ni attente effective pendant le test.
    connexion = Mock(side_effect=ConnectionTimeout('serveur-prive mot-de-passe-secret'))
    engine = sa.create_engine('postgresql+psycopg://', creator=connexion)
    monkeypatch.setattr('apps.kpi.dashboard.moteur_kpi', lambda: engine)
    client.force_login(User.objects.create_superuser('admin-timeout'))
    try:
        reponse = client.get('/', {'vue': selection})
        assert reponse.status_code == 200
        d = reponse.context['dashboard']
        assert not d['cartes'] and not d['graphiques'] and not d['periodes']
        assert "base de données KPI n'est pas accessible" in d['message']
        assert 'Aucune donnée' not in d['message']
        assert connexion.call_count == 1
        html = reponse.content.decode()
        assert 'serveur-prive' not in html + caplog.text
        assert 'mot-de-passe-secret' not in html + caplog.text
        avertissements = [r for r in caplog.records if r.name == 'apps.kpi.dashboard']
        assert len(avertissements) == 1 and avertissements[0].exc_info is None
        assert 'KPI_DB_HOST/KPI_DB_PORT' in avertissements[0].message
    finally:
        engine.dispose()


def test_timeout_apres_une_techno_preserve_les_donnees_et_reessaie(historique_horaire, monkeypatch):
    engine, _, _ = historique_horaire
    panne = sa.exc.OperationalError(None, None, ConnectionTimeout('connection timeout expired'))
    lecture = Mock(side_effect=[dernieres_heures(engine, 'LTE', None), panne])
    monkeypatch.setattr('apps.kpi.dashboard.dernieres_heures', lecture)
    user = User.objects.create_superuser('admin-panne-partielle')
    d = construire(user, date(2026, 10, 13))
    assert len(d['cartes']) == len(d['graphiques']) == len(d['periodes']) == 1
    assert d['periodes'][0]['techno'] == '4G'
    assert d['cartes'][0]['texte'] == '72'
    assert any("base de données KPI n'est pas accessible" in a for a in d['avertissements'])

    monkeypatch.setattr('apps.kpi.dashboard.dernieres_heures', dernieres_heures)
    d = construire(user, date(2026, 10, 13))
    assert len(d['cartes']) == len(d['graphiques']) == len(d['periodes']) == 2
    assert not d['avertissements']


def test_erreur_sql_lte_ne_masque_pas_wcdma(historique_horaire, caplog):
    engine, _, _ = historique_horaire
    with engine.begin() as conn:
        conn.execute(sa.text('DROP TABLE lte_cell_hour'))
    d = construire(User.objects.create_superuser('admin-table-absente'), date(2026, 10, 13))
    assert len(d['cartes']) == len(d['graphiques']) == len(d['periodes']) == 1
    assert d['periodes'][0]['techno'] == '3G'
    assert any('LTE' in a for a in d['avertissements'])
    assert any(r.exc_info for r in caplog.records if r.name == 'apps.kpi.dashboard')
