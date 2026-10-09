"""Lancement d'un ``Rapport`` en tâche de fond (journalisé)."""

from django_q.tasks import async_task

from apps.comptes.models import JournalAudit

from .models import Rapport


def lancer(rapport: Rapport):
    JournalAudit.objects.create(utilisateur=rapport.utilisateur, action=f"rapport_{rapport.nature}_{rapport.format}",
                                requete=rapport.parametres)
    async_task("apps.rapports.taches.generer", rapport.pk, task_name=f"rapport-{rapport.pk}")
