"""Lancement d'un ``Rapport`` en tâche de fond (journalisé)."""

import logging

from django_q.tasks import async_task
from django.utils import timezone

from apps.comptes.models import JournalAudit

from .models import Rapport

journal = logging.getLogger(__name__)


def lancer(rapport: Rapport):
    JournalAudit.objects.create(utilisateur=rapport.utilisateur, action=f"rapport_{rapport.nature}_{rapport.format}",
                                requete=rapport.parametres)
    try:
        async_task("apps.rapports.taches.generer", rapport.pk, task_name=f"rapport-{rapport.pk}")
    except Exception:
        journal.exception("Impossible de mettre le rapport %s en file d'attente", rapport.pk)
        rapport.statut = "erreur"
        rapport.message = "La génération du rapport n'a pas pu démarrer. Veuillez réessayer plus tard."
        rapport.termine_le = timezone.now()
        rapport.save(update_fields=["statut", "message", "termine_le"])
        return False
    return True
