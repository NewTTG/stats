"""Requêtes réelles PostgreSQL : STATS_TEST_POSTGRES_URL pour activer ces tests.

Tables TEMP uniquement : aucune table persistante n'est modifiée.
"""
import os
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from apps.kpi.source import dernieres_heures


@pytest.fixture
def postgres():
    url = os.environ.get('STATS_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('STATS_TEST_POSTGRES_URL absent : test PostgreSQL facultatif')
    engine = sa.create_engine(url, poolclass=sa.pool.StaticPool)
    with engine.begin() as conn:
        for table, cellule in [('lte_cell_hour', 'EutranCell_Id'), ('wcdma_cell_hour', 'CellWcdma')]:
            conn.execute(sa.text(f'CREATE TEMP TABLE {table} ("DateHour" timestamp, "{cellule}" text)'))
            conn.execute(sa.text(f'CREATE INDEX ON {table} ("DateHour", "{cellule}")'))
            fin = datetime(2026, 10, 14, 16)
            # Deux cellules par heure, trous, une cellule plus récente hors périmètre,
            # et une cellule n'ayant des données que dans l'historique ancien.
            lignes = [{'heure': fin - timedelta(hours=i), 'cellule': c}
                      for i in range(36) if i not in (1, 4, 7)
                      for c in ('AUTORISEE', 'AUTRE')]
            lignes += [{'heure': fin + timedelta(hours=3), 'cellule': 'AUTRE'},
                       {'heure': fin - timedelta(days=100), 'cellule': 'ANCIENNE'},
                       {'heure': None, 'cellule': 'AUTORISEE'}]
            conn.execute(sa.text(f'INSERT INTO {table} VALUES (:heure, :cellule)'), lignes)
    try:
        yield engine
    finally:
        engine.dispose()  # supprime aussi les tables TEMP


@pytest.mark.parametrize('techno,table,col', [
    ('LTE', 'lte_cell_hour', 'EutranCell_Id'),
    ('WCDMA', 'wcdma_cell_hour', 'CellWcdma'),
])
@pytest.mark.parametrize('cellules', [None, ['AUTORISEE'], ['ANCIENNE'], ['INCONNUE'], [], ['AUTORISEE', 'AUTRE']])
def test_heures_indexees_identiques_a_distinct(postgres, settings, techno, table, col, cellules):
    settings.KPI_CACHE_ENABLED = False
    filtre = f' AND "{col}" IN :cellules' if cellules is not None else ''
    query = sa.text(f'SELECT DISTINCT "DateHour" FROM {table} WHERE "DateHour" IS NOT NULL{filtre} '
                    'ORDER BY "DateHour" DESC LIMIT 24')
    params = {}
    if cellules is not None:
        query = query.bindparams(sa.bindparam('cellules', expanding=True, type_=sa.String()))
        params['cellules'] = cellules
    with postgres.connect() as conn:
        attendues = sorted(conn.execute(query, params).scalars())
    assert dernieres_heures(postgres, techno, cellules) == attendues


def test_heures_postgres_table_vide(postgres, settings):
    settings.KPI_CACHE_ENABLED = False
    with postgres.begin() as conn:
        conn.execute(sa.text('DELETE FROM lte_cell_hour'))
    assert dernieres_heures(postgres, 'LTE', None) == []
