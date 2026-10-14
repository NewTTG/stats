"""Batch de phrases indépendantes : fautes, synonymes, périodes et critères conservés."""
from datetime import date

import pytest

from apps.kpi.recherche import avec_parametres
from apps.kpi.recherche.regles import interpreter
from apps.referentiel.models import Site
from tests.test_recherche_regles import ctx, ref_recherche

pytestmark = pytest.mark.django_db
J = date(2026, 10, 14)

# Intention attendue -> expressions réelles ; les résultats KPI sont fixés ci-dessous.
EXPRESSIONS = {
    'drop': ['drop', 'Dro', 'drp', 'dorp', 'dropp', 'drops', 'dros', 'drps', 'dorps',
             'coupure', 'coupre', 'couprue', 'coupuer', 'coupur', 'couppure', 'coupres', 'couprues',
             'coupurs', 'couppures', 'taux de coupure', 'taux de coupures', 'taux de couprue',
             'taux de coupres', 'taux de dro', 'taux de chute', 'taux de déconnexion',
             'déconnexions intempestives', 'interruptions de communication', 'call drops'],
    'acces': ['accès', 'aces', 'accces', 'accee', 'accesibilite', 'accessibilit', 'accessibilitee',
              'taux d’aces', 'taux d accces'],
    'debit': ['débit', 'debi', 'debti', 'deibt', 'debitt', 'debis', 'debtis', 'deibts', 'vitesse',
              'throughput', 'bande passante'],
    'trafic': ['trafic', 'traffic', 'trafc', 'trafi', 'traffc'],
    'volume': ['volum', 'volmue', 'donees', 'donnes', 'traffic data'],
    'appels': ['appels', 'apel', 'appe', 'apels', 'appls', 'appelss'],
    'disponibilite': ['disponibilité', 'disponibilit', 'disponiblite', 'disponbilite', 'disponibilitee',
                     'indisponibilit', 'indisponiblite', 'indisponbilite', 'dispo', 'hors service'],
    'congestion': ['congestion', 'congetion', 'congeston', 'congsetion', 'congestoin', 'saturaton', 'saturatoin'],
}
KPIS = {
    'drop': {'WCDMA': ['wcdma_cs_drop', 'wcdma_ps_drop'], 'LTE': ['lte_erab_drop']},
    'acces': {'WCDMA': ['wcdma_cssr_cs', 'wcdma_cssr_ps'], 'LTE': ['lte_acces']},
    'debit': {'WCDMA': ['wcdma_hs_user_thp'], 'LTE': ['lte_dl_user_thp']},
    'trafic': {'WCDMA': ['wcdma_appels_voix', 'wcdma_sms', 'wcdma_payload_hs'],
               'LTE': ['lte_csfb_appels', 'lte_payload_dl']},
    'volume': {'WCDMA': ['wcdma_payload_hs'], 'LTE': ['lte_payload_dl']},
    'appels': {'WCDMA': ['wcdma_appels_voix', 'wcdma_speech_traffic', 'wcdma_duree_appel'],
               'LTE': ['lte_csfb_appels']},
    'disponibilite': {'WCDMA': ['wcdma_cell_availability'], 'LTE': ['lte_cell_availability']},
    'congestion': {'LTE': ['lte_prb_dl_util']},
}
PERIODES = [
    ('semaine dernière', date(2026, 10, 5), date(2026, 10, 11)),
    ('semine dernière', date(2026, 10, 5), date(2026, 10, 11)),
    ('semiane derneire', date(2026, 10, 5), date(2026, 10, 11)),
    ('mois derneir', date(2026, 9, 1), date(2026, 9, 30)),
]
CAS = [(intention, expression, techno, label, debut, fin)
       for intention, expressions in EXPRESSIONS.items()
       for expression in expressions
       for techno in KPIS[intention]
       for label, debut, fin in PERIODES]


@pytest.mark.parametrize('intention,expression,techno,label,debut,fin', CAS)
def test_batch_fautes_et_synonymes(ctx, intention, expression, techno, label, debut, fin):
    generation = {'LTE': '4G', 'WCDMA': '3G'}[techno]
    i = interpreter(f'{expression} {generation} Nouméa {label}', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['techno'] == [techno]
    assert i.params['kpis'] == KPIS[intention][techno]
    assert i.params['perimetre'] == {'type': 'commune', 'valeurs': ['NOUMEA']}
    assert i.params['periode'] == {'debut': debut, 'fin': fin}
    assert i.params['granularite_temps'] == 'jour'
    assert i.params['granularite_espace'] == 'global'
    assert i.params['fenetre_horaire'] == 'journee'


@pytest.mark.parametrize('expression,kpis', [
    ('dro voix', ['wcdma_cs_drop']), ('taux de couprue des apels', ['wcdma_cs_drop']),
    ('dro data', ['wcdma_ps_drop']), ('taux de coupres data', ['wcdma_ps_drop']),
    ('taux de drop ps', ['wcdma_ps_drop']), ('interruptions de session', ['wcdma_ps_drop']),
    ('taux d aces voix', ['wcdma_cssr_cs']), ('aces data', ['wcdma_cssr_ps']),
    ('debti', ['wcdma_hs_user_thp']), ('volum voix', ['wcdma_speech_traffic']),
    ('dure des apels', ['wcdma_duree_appel']),
])
def test_fautes_expressions_composees(ctx, expression, kpis):
    i = interpreter(f'{expression} 3G Nouméa semaine dernière', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['kpis'] == kpis


@pytest.mark.parametrize('expression,kpis', [
    ('debti ul', ['lte_ul_user_thp']), ('handvoer', ['lte_ho_intra_sr']),
    ('handovr', ['lte_ho_intra_sr']), ('handoer', ['lte_ho_intra_sr']),
    ('utilisaters conectes', ['lte_rrc_conn_max']), ('utilsateurs connctes', ['lte_rrc_conn_max']),
    ('utilisaturs connectes', ['lte_rrc_conn_max']),
])
def test_autres_fautes_composees(ctx, expression, kpis):
    i = interpreter(f'{expression} 4G Nouméa semaine dernière', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['kpis'] == kpis


def test_causes_et_criteres_explicites(ctx):
    i = interpreter('causes de dro voix 3G Nouméa semine dernière par site le soir', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['kpis'][0] == 'wcdma_cs_drop'
    assert len(i.params['kpis']) > 1
    assert i.params['granularite_espace'] == 'site'
    assert i.params['fenetre_horaire'] == '18-22'


def test_precision_periode_conserve_faute_reconnue(ctx, rf):
    i = interpreter('Dro 3G Nouméa par site le soir', J, ctx)
    assert [q.champ for q in i.questions] == ['periode']
    avant = {k: i.params[k] for k in ('techno', 'kpis', 'perimetre', 'granularite_espace', 'fenetre_horaire')}
    option = next(o for o in i.questions[0].options if o.libelle == 'Semaine dernière')
    i = avec_parametres(i, rf.get('/', option.params).GET, ctx, J)
    assert i.complete and all(i.params[k] == v for k, v in avant.items())


@pytest.mark.parametrize('mot', ['dromadaire', 'droplet', 'drou', 'debiteur', 'trafiquants', 'semineville'])
def test_mots_inconnus_non_transformes(ctx, mot):
    i = interpreter(f'{mot} 3G Nouméa semaine dernière', J, ctx)
    assert not i.complete
    assert any(q.champ == 'kpis' for q in i.questions)


@pytest.mark.parametrize('lieu', ['site DEBTI', 'DEBTI', 'site DRO', 'DRO'])
def test_noms_sites_et_trigrammes_preserves(ref_recherche, lieu):
    from apps.kpi.recherche import Contexte
    Site.objects.filter(code_site='PAI001').update(nom='DEBTI', trigramme='DRO')
    i = interpreter(f'drop 3G {lieu} semaine dernière', J, Contexte.pour(None))
    assert i.complete
    assert i.params['kpis'] == ['wcdma_cs_drop', 'wcdma_ps_drop']
    assert i.params['perimetre'] == {'type': 'site', 'valeurs': ['PAI001']}


@pytest.mark.parametrize('semaine', ['semaine', 'semine', 'semiane', 'semanie', 'semain'])
@pytest.mark.parametrize('derniere', ['dernière', 'dernere', 'derneire', 'dernierre'])
@pytest.mark.parametrize('inverse', [False, True])
def test_variantes_semaine_derniere(ctx, semaine, derniere, inverse):
    periode = f'{derniere} {semaine}' if inverse else f'{semaine} {derniere}'
    i = interpreter(f'Dro 3G Nouméa {periode}', J, ctx)
    assert i.complete and not i.non_compris
    assert i.params['periode'] == {'debut': date(2026, 10, 5), 'fin': date(2026, 10, 11)}


@pytest.mark.parametrize('variantes', [
    {'drop': ['dro'], 'debit': ['dro']}, {'drop': ['debit']},
    {'drop': ['dr op']}, {'call drop': ['dro']},
])
def test_configuration_fautes_ambigue_refusee(settings, tmp_path, variantes):
    import yaml
    from apps.kpi.recherche.vocabulaire import charger_vocabulaire
    with open(settings.RECHERCHE_VOCABULAIRE_PATH, encoding='utf-8') as f:
        brut = yaml.safe_load(f)
    brut['variantes_saisie'] = variantes
    chemin = tmp_path / 'vocabulaire.yaml'
    chemin.write_text(yaml.safe_dump(brut), encoding='utf-8')
    with pytest.raises(ValueError, match='variante de saisie'):
        charger_vocabulaire(chemin)
