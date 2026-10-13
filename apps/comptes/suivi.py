"""Trace chaque tentative et relie les précisions explicitement envoyées par l'écran."""
import json
import logging
from dataclasses import asdict
from functools import wraps
from time import monotonic
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from .models import DemandeSuivie

log = logging.getLogger(__name__)


def serialiser(valeur):
    return json.loads(json.dumps(valeur, cls=DjangoJSONEncoder))


def origine(user, identifiant):
    try:
        identifiant = UUID(str(identifiant))
    except (ValueError, TypeError, AttributeError):
        return None
    return DemandeSuivie.objects.filter(pk=identifiant, utilisateur=user).first()


def commencer(user, nature, texte, parametres, parent=None):
    valeurs = dict(utilisateur=user, nature=nature, texte=texte, parametres=serialiser(parametres), parent=parent)
    if parent:
        valeurs['parcours'] = parent.parcours
    return DemandeSuivie.objects.create(**valeurs)


def terminer(demande, statut, message='', resultat=None):
    if demande is None:
        return
    demande.statut = statut
    demande.message = message
    demande.terminee_le = timezone.now()
    demande.duree_ms = max(0, int((demande.terminee_le - demande.creee_le).total_seconds() * 1000))
    if resultat is not None:
        demande.resultat = serialiser(resultat)
    demande.save(update_fields=['statut', 'message', 'terminee_le', 'duree_ms', 'resultat'])


def interpretation(demande, interp):
    if demande is None:
        return
    demande.interpretation = serialiser({
        'source': interp.source, 'compris': [asdict(p) for p in interp.compris],
        'questions': [asdict(q) for q in interp.questions], 'non_compris': interp.non_compris,
        'notes': interp.notes, 'requete': interp.params,
    })
    demande.save(update_fields=['interpretation'])


def suivre_recherche(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from apps.kpi.views import CHAMPS_FORMULAIRE
        from apps.kpi.recherche.construction import PARAMETRES
        demande = None
        recherche = 'q' in request.GET and (request.GET.get('q', '').strip() or
                                            any(k in request.GET for k in PARAMETRES))
        if request.method == 'GET' and (recherche or any(k in request.GET for k in CHAMPS_FORMULAIRE)):
            params = {k: request.GET.getlist(k) for k in ('q', 'ia', 'export', *PARAMETRES, *CHAMPS_FORMULAIRE)
                      if k in request.GET}
            parent = origine(request.user, request.GET.get('suivi'))
            demande = commencer(request.user, 'export' if request.GET.get('export') == 'xlsx' else 'recherche',
                                 request.GET.get('q', '').strip()[:300], params, parent)
        request.demande_suivie = demande
        debut = monotonic()
        try:
            response = view(request, *args, **kwargs)
        except Exception:
            terminer(demande, 'erreur', 'Erreur inattendue pendant le traitement de la demande.')
            log.exception('Échec de la demande %s', demande.pk if demande else '-')
            raise
        if demande:
            DemandeSuivie.objects.filter(pk=demande.pk).update(duree_ms=int((monotonic() - debut) * 1000))
        return response
    return wrapper
