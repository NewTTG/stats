"""Présentation des traces historiques, sans les modifier ni relancer de recherche."""
import json

from django.utils import timezone


def preparer_etape(etape):
    etape.diagnostic = json.dumps({
        'parametres': etape.parametres, 'interpretation': etape.interpretation,
        'resultat': etape.resultat,
    }, ensure_ascii=False, indent=2)
    etape.reponses = []
    if etape.parent:
        for question in etape.parent.interpretation.get('questions', []):
            for option in question.get('options', []):
                def identique(cle, valeur):
                    envoyees = etape.parametres.get(cle, [])
                    attendues = valeur if isinstance(valeur, list) else [valeur]
                    return [str(v) for v in envoyees] == [str(v) for v in attendues]
                if option.get('params') and all(identique(k, v) for k, v in option['params'].items()):
                    etape.reponses.append(option['libelle'])
    return etape


def pistes_amelioration(demande):
    """Pistes fondées sur la trace ; ce ne sont pas des causes d'erreur établies."""
    pistes = []
    if demande.interpretation.get('non_compris'):
        pistes.append('Vérifier les mots non reconnus : distinguer les formules de politesse '
                      'des noms de sites et vérifier le lieu retenu dans le référentiel.')
    champs = {q.get('champ') for q in demande.interpretation.get('questions', [])}
    if 'perimetre' in champs:
        pistes.append('Vérifier les noms et variantes du lieu demandé ; proposer des lieux accessibles '
                      'sans sélectionner automatiquement un autre site ou une commune.')
    if champs - {'perimetre'}:
        pistes.append('Vérifier que les précisions demandées sont absentes de la phrase et que '
                      'le choix de l’utilisateur conserve les autres critères.')
    if demande.statut == 'erreur':
        pistes.append('Examiner le message et les journaux du traitement avec cet identifiant de demande.')
    if demande.statut == 'sans_donnees':
        pistes.append('Vérifier la disponibilité des données pour le site, la technologie et la période retenus.')
    return pistes


def texte_a_transmettre(demande, pistes):
    lignes = [
        'Demande à améliorer', f'Identifiant : {demande.pk}',
        f'Date : {timezone.localtime(demande.creee_le):%d/%m/%Y %H:%M:%S} (Nouméa)',
        f'Question originale : {demande.texte or "Demande composée avec les filtres"}',
        f'État du traitement : {demande.get_statut_display()}',
    ]
    if demande.reponses:
        lignes.append('Choix repris : ' + ', '.join(demande.reponses))
    lignes += ['', 'Interprétation enregistrée :']
    lignes += ['- ' + p['libelle'] + (' (par défaut)' if p.get('defaut') else '')
               for p in demande.interpretation.get('compris', [])]
    if demande.interpretation.get('non_compris'):
        lignes.append('Mots non reconnus : ' + ', '.join(demande.interpretation['non_compris']))
    for question in demande.interpretation.get('questions', []):
        lignes.append('Précision proposée : ' + question['texte'])
        lignes += ['- ' + o['libelle'] for o in question.get('options', [])]
    if demande.message:
        lignes.append('Message : ' + demande.message)
    lignes += ['', 'Pistes à vérifier (diagnostic à confirmer) :']
    lignes += ['- ' + p for p in pistes] or ['Aucune difficulté détectée automatiquement dans cette trace.']
    lignes += ['', 'Comportement attendu / suggestion :', '[À compléter avant transmission]',
               '', 'Paramètres de la demande :', json.dumps(demande.parametres, ensure_ascii=False, indent=2)]
    return '\n'.join(lignes)
