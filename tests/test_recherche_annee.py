"""Année courante en langage libre, sans perdre les critères de coupure réseau."""
from datetime import date

import pytest

from apps.kpi.recherche.dates import extraire_periode
from apps.kpi.recherche.regles import interpreter
from apps.kpi.recherche.texte import Texte
from tests.test_recherche_regles import ctx, ref_recherche

pytestmark = pytest.mark.django_db
J = date(2026, 10, 14)


@pytest.mark.parametrize('expression', [
    "dans l'année", 'dans l’année', "sur l'année", "pour l'année", "pendant l'année",
    "durant l'année", "au cours de l'année", 'dans cette année', 'cette année',
    "dans l'année en cours", "sur l'année courante", "l'année en cours",
    "depuis le début de l'année",
])
def test_coupure_reseau_annee_courante(ctx, expression):
    i = interpreter(f'coupure réseau mobile {expression}', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['periode'] == {'debut': date(2026, 1, 1), 'fin': J}
    assert i.params['techno'] == ['LTE', 'WCDMA']
    assert i.params['kpis'] == ['lte_erab_drop', 'wcdma_cs_drop', 'wcdma_ps_drop']
    assert i.params['perimetre'] == {'type': 'global', 'valeurs': []}
    assert i.params['granularite_temps'] == 'mois'
    assert i.params['granularite_espace'] == 'global'
    assert i.params['fenetre_horaire'] == 'journee'


@pytest.mark.parametrize('expression,debut,fin', [
    ("dans l'année dernière", date(2025, 1, 1), date(2025, 12, 31)),
    ("sur l'année passée", date(2025, 1, 1), date(2025, 12, 31)),
    ("pendant l'année précédente", date(2025, 1, 1), date(2025, 12, 31)),
    ("dans l'année 2024", date(2024, 1, 1), date(2024, 12, 31)),
    ("sur l'année 2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("pour l'année 2026", date(2026, 1, 1), J),
])
def test_annee_precisee_prime(ctx, expression, debut, fin):
    i = interpreter(f'coupure réseau mobile {expression}', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['periode'] == {'debut': debut, 'fin': fin}


@pytest.mark.parametrize('jour', [date(2027, 1, 1), date(2028, 2, 29), date(2026, 12, 31)])
def test_limites_annee(jour):
    texte = Texte("coupure dans l'année")
    periode, notes = extraire_periode(texte, jour)
    assert (periode.debut, periode.fin) == (date(jour.year, 1, 1), jour)
    assert not notes and texte.non_compris() == ['coupure']


def test_depuis_janvier_conserve_fin_a_hier(ctx):
    i = interpreter('coupure réseau mobile depuis janvier', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['periode'] == {'debut': date(2026, 1, 1), 'fin': date(2026, 10, 13)}


@pytest.mark.parametrize('expression', ["dans l'année prochaine", "sur l'année suivante"])
def test_annee_future_non_remplacee_par_courante(ctx, expression):
    i = interpreter(f'coupure réseau mobile {expression}', J, ctx)
    assert not i.complete
    assert any(q.champ == 'periode' for q in i.questions)


def test_annee_conserve_autres_criteres(ctx):
    i = interpreter("coupure data 3G Nouméa dans l'année par site le soir", J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['techno'] == ['WCDMA']
    assert i.params['kpis'] == ['wcdma_ps_drop']
    assert i.params['perimetre'] == {'type': 'commune', 'valeurs': ['NOUMEA']}
    assert i.params['granularite_espace'] == 'site'
    assert i.params['fenetre_horaire'] == '18-22'
