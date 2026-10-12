"""Cache réel : expiration, limites, concurrence et isolation des résultats."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Event
from unittest.mock import Mock

import pandas as pd
import pytest
import sqlalchemy as sa
from django.core.management import call_command
from django.contrib.auth.models import User

from apps.kpi.cache import memoriser, ouvrir
from apps.kpi.models import SeuilKpi
from apps.kpi.service import executer
from apps.kpi.source import identite_source
from apps.referentiel.models import Site
from tests.test_service import analyste, lecteur_paita, referentiel, base_kpi, requete


@pytest.fixture
def fichier_kpi(base_kpi, tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'kpi.sqlite3'}")
    for table in ('lte_cell_hour', 'lte_cell_day'):
        with base_kpi.connect() as conn:
            df = pd.DataFrame(conn.execute(sa.text(f'SELECT * FROM {table}')).mappings())
        df.to_sql(table, engine, index=False)
    yield engine
    engine.dispose()


def test_expiration_fixe_et_copie_independante(settings, monkeypatch):
    horloge = [1000.0]
    monkeypatch.setattr('diskcache.core.time.time', lambda: horloge[0])
    settings.KPI_CACHE_TTL = 300
    calcul = Mock(return_value={'donnees': [42]})
    memoriser('test', {}, calcul)['donnees'].append(99)
    horloge[0] = 1299
    assert memoriser('test', {}, calcul) == {'donnees': [42]}
    assert calcul.call_count == 1
    horloge[0] = 1301
    memoriser('test', {}, calcul)
    assert calcul.call_count == 2  # consulter n'a pas prolongé le TTL


def test_erreur_de_calcul_non_memorisee():
    calcul = Mock(side_effect=[ValueError('source'), 42])
    with pytest.raises(ValueError, match='source'):
        memoriser('test', {}, calcul)
    assert memoriser('test', {}, calcul) == 42
    assert memoriser('test', {}, calcul) == 42
    assert calcul.call_count == 2


@pytest.mark.parametrize('parametre', ['KPI_CACHE_ENABLED', 'KPI_CACHE_TTL', 'KPI_CACHE_MAX_BYTES'])
def test_desactivation(settings, parametre):
    setattr(settings, parametre, 0)
    calcul = Mock(return_value=42)
    assert [memoriser('test', {}, calcul) for _ in range(2)] == [42, 42]
    assert calcul.call_count == 2
    assert not settings.KPI_CACHE_DIR.exists()


def test_cache_indisponible_ne_bloque_pas(settings, tmp_path):
    fichier = tmp_path / 'fichier'
    fichier.write_text('pas un répertoire')
    settings.KPI_CACHE_DIR = fichier / 'cache'
    assert memoriser('test', {}, lambda: 42) == 42


def test_cache_corrompu_et_echec_ecriture(monkeypatch):
    assert memoriser('test', {}, lambda: 42) == 42
    with ouvrir() as cache:
        cle = next(iter(cache))
        cache.set(cle, b'invalide')
    calcul = Mock(return_value=43)
    assert memoriser('test', {}, calcul) == 43
    with ouvrir() as cache:
        cache.clear()
    monkeypatch.setattr('diskcache.Cache.set', Mock(side_effect=OSError('disque plein')))
    assert memoriser('test', {}, calcul) == 43


def test_resultat_trop_gros_non_stocke(settings):
    settings.KPI_CACHE_ITEM_MAX_BYTES = 10
    calcul = Mock(return_value='x' * 100)
    assert [memoriser('test', {}, calcul) for _ in range(2)] == ['x' * 100] * 2
    assert calcul.call_count == 2
    with ouvrir() as cache:
        assert len(cache) == 0


def test_budget_disque_et_eviction_lru(settings):
    settings.KPI_CACHE_MAX_BYTES = 240_000
    calculs = [Mock(return_value=bytes([i]) * 90_000) for i in range(3)]
    for i in (0, 1, 0, 2, 0):
        memoriser('test', {'i': i}, calculs[i])
    assert calculs[0].call_count == 1  # le résultat récemment consulté est conservé
    with ouvrir() as cache:
        assert cache.volume() <= settings.KPI_CACHE_MAX_BYTES
        assert len(cache) == 2
    memoriser('test', {'i': 1}, calculs[1])
    assert calculs[1].call_count == 2


def test_concurrence_un_seul_calcul():
    entre, terminer = Event(), Event()
    def calculer():
        entre.set()
        assert terminer.wait(5)
        return {'valeur': 42}
    calcul = Mock(side_effect=calculer)
    with ThreadPoolExecutor(max_workers=4) as pool:
        premier = pool.submit(memoriser, 'test', {}, calcul)
        assert entre.wait(5)
        autres = [pool.submit(memoriser, 'test', {}, calcul) for _ in range(3)]
        terminer.set()
        resultats = [f.result(timeout=5) for f in [premier, *autres]]
    assert resultats == [{'valeur': 42}] * 4
    assert calcul.call_count == 1
    assert resultats[0] is not resultats[1]


def test_attente_bornee_du_verrou(settings):
    settings.KPI_CACHE_WAIT_SECONDS = 0.02
    entre, terminer = Event(), Event()
    def calculer():
        entre.set()
        assert terminer.wait(5)
        return 42
    with ThreadPoolExecutor(max_workers=1) as pool:
        premier = pool.submit(memoriser, 'test', {}, calculer)
        assert entre.wait(5)
        try:
            assert memoriser('test', {}, lambda: 43) == 43
        finally:
            terminer.set()
        assert premier.result(timeout=5) == 42


def test_partage_et_verrou_entre_processus(settings, tmp_path):
    code = '''
import os, time
from pathlib import Path
from apps.kpi.cache import memoriser

def calculer():
    with Path(os.environ['COMPTEUR_TEST']).open('a') as f:
        f.write('calcul\\n')
    time.sleep(0.4)
    return 42
assert memoriser('processus', {}, calculer) == 42
'''
    env = dict(os.environ, DJANGO_SETTINGS_MODULE='config.settings',
               KPI_CACHE_DIR=str(settings.KPI_CACHE_DIR), COMPTEUR_TEST=str(tmp_path / 'compteur'))
    processus = [subprocess.Popen([sys.executable, '-c', code], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    try:
        for p in processus:
            sortie, erreur = p.communicate(timeout=20)
            assert p.returncode == 0, erreur
    finally:
        for p in processus:
            if p.poll() is None:
                p.kill()
                p.wait()
    assert (tmp_path / 'compteur').read_text().splitlines() == ['calcul']


def test_commande_et_purge():
    calcul = Mock(return_value=42)
    memoriser('test', {}, calcul)
    sortie = StringIO()
    call_command('cache_kpi', stdout=sortie)
    assert '1 résultat(s)' in sortie.getvalue()
    call_command('cache_kpi', '--vider', stdout=StringIO())
    memoriser('test', {}, calcul)
    assert calcul.call_count == 2


@pytest.mark.django_db
def test_service_reutilise_entre_utilisateurs_et_garde_les_droits(
        referentiel, fichier_kpi, analyste, lecteur_paita, monkeypatch):
    from apps.kpi import service
    lire = Mock(wraps=service.lire)
    monkeypatch.setattr(service, 'lire', lire)
    premier = executer(requete(), analyste, fichier_kpi)
    autre = User.objects.create_user('autre', is_superuser=True)
    second = executer(requete(), autre, fichier_kpi)
    pd.testing.assert_frame_equal(premier.par_techno[0].table, second.par_techno[0].table)
    assert lire.call_count == 1
    restreint = executer(requete(granularite_espace='cellule'), lecteur_paita, fichier_kpi)
    assert set(restreint.par_techno[0].table.index.get_level_values('entite')) == {'BBBe1'}
    assert [k.code for k in restreint.par_techno[0].kpis] == ['lte_rrc_setup_sr']
    assert lire.call_count == 2
    lecteur_paita.is_active = False
    lecteur_paita.save()
    assert executer(requete(), lecteur_paita, fichier_kpi).par_techno == []
    analyste.groups.clear()
    assert executer(requete(), analyste, fichier_kpi).par_techno == []
    assert lire.call_count == 2


@pytest.mark.django_db
def test_invalidation_referentiel_seuils_et_source(referentiel, fichier_kpi, analyste, monkeypatch):
    from apps.kpi import service
    lire = Mock(wraps=service.lire)
    monkeypatch.setattr(service, 'lire', lire)
    req = requete(granularite_espace='site')
    executer(req, analyste, fichier_kpi)
    executer(req, analyste, fichier_kpi)
    assert lire.call_count == 1
    Site.objects.filter(code_site='AAA100').update(nom='NOUVEAU')
    res = executer(req, analyste, fichier_kpi)
    assert 'NOUVEAU' in res.par_techno[0].table.index.get_level_values('entite')
    assert lire.call_count == 2
    SeuilKpi.objects.update_or_create(code='lte_rrc_setup_sr', defaults={'alerte': 97, 'critique': 92})
    res = executer(req, analyste, fichier_kpi)
    assert res.par_techno[0].kpis[0].seuils.alerte == 97
    assert lire.call_count == 3
    with fichier_kpi.begin() as conn:
        conn.execute(sa.text('UPDATE lte_cell_day SET PayloadDl_mB = 0'))
    res = executer(req, analyste, fichier_kpi)
    assert res.par_techno[0].synthese_globale['lte_payload_dl'] == 0
    assert lire.call_count == 4


def test_sources_memoire_et_fichiers_distinctes(tmp_path):
    assert identite_source(sa.create_engine('sqlite://')) is None
    engines = [sa.create_engine(f'sqlite:///{tmp_path / nom}') for nom in ('a.db', 'b.db')]
    for e in engines:
        with e.begin() as conn:
            conn.execute(sa.text('CREATE TABLE test (a INTEGER)'))
    assert identite_source(engines[0]) != identite_source(engines[1])
    for e in engines:
        e.dispose()


def test_changer_ttl_invalide_les_resultats(settings):
    calcul = Mock(return_value=42)
    memoriser('test', {}, calcul)
    settings.KPI_CACHE_TTL = 10
    memoriser('test', {}, calcul)
    assert calcul.call_count == 2


def test_calcul_plus_long_que_ttl_non_stocke(settings, monkeypatch):
    from types import SimpleNamespace
    settings.KPI_CACHE_TTL = 1
    monkeypatch.setattr('apps.kpi.cache.time', SimpleNamespace(monotonic=Mock(side_effect=[0, 2])))
    assert memoriser('test', {}, lambda: 42) == 42
    with ouvrir() as cache:
        assert len(cache) == 0


@pytest.mark.django_db
def test_bascule_secteur_et_retrait_perimetre_invalident_le_cache(
        referentiel, fichier_kpi, analyste, lecteur_paita):
    from datetime import date
    from apps.comptes.models import Perimetre
    from apps.referentiel.models import Cellule, Secteur
    req = requete(granularite_espace='secteur')
    executer(req, analyste, fichier_kpi)
    Cellule.objects.filter(nom='AAAe2').update(secteur_avant=Secteur.objects.get(code='AAA1001'))
    Site.objects.filter(code_site='AAA100').update(bascule_4_secteurs=date(2026, 9, 2))
    res = executer(req, analyste, fichier_kpi).par_techno[0]
    assert res.table.loc[(pd.Timestamp('2026-09-01'), 'AAA1001'), 'lte_payload_dl'] == 40
    assert (pd.Timestamp('2026-09-01'), 'AAA1002') not in res.table.index
    assert executer(requete(), lecteur_paita, fichier_kpi).par_techno
    Perimetre.objects.filter(nom='Paita').update(communes=[])
    assert executer(requete(), lecteur_paita, fichier_kpi).par_techno == []


def test_source_sqlite_wal_invalidee(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text('PRAGMA journal_mode=WAL'))
            conn.execute(sa.text('CREATE TABLE test (a INTEGER)'))
            conn.commit()
            avant = identite_source(engine)
            conn.execute(sa.text('INSERT INTO test VALUES (42)'))
            conn.commit()
            assert identite_source(engine) != avant
    finally:
        engine.dispose()
