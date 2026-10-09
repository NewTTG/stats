"""Rapports enregistrés : période recalculée à chaque lancement, lancements planifiés.

``lancer_dus`` est appelée toutes les 15 minutes par le worker django-q2 (tâche
« rapports-planifies », créée par migration) ou par ``manage.py lancer_rapports_planifies``.
"""

import logging
from datetime import date, datetime

from django.utils import timezone

from apps.kpi.recherche.dates import preset
from apps.kpi.requete import RequeteKpi

from .lancement import lancer
from .models import Rapport, RapportPlanifie

log = logging.getLogger(__name__)


def requete_du(plan: RapportPlanifie, jour: date) -> tuple[RequeteKpi, str]:
    """Requête enregistrée, sur la période relative calculée au ``jour`` donné, et son libellé."""
    periode = preset(plan.periode, jour)
    requete = RequeteKpi(**{**plan.requete, "periode": {"debut": periode.debut, "fin": periode.fin}})
    return requete, f"{periode.libelle}, {periode.debut:%d/%m/%Y}-{periode.fin:%d/%m/%Y}"


def lancer_planifie(plan: RapportPlanifie, maintenant: datetime | None = None) -> Rapport:
    maintenant = maintenant or timezone.now()
    requete, libelle = requete_du(plan, timezone.localtime(maintenant).date())
    rapport = Rapport.objects.create(
        utilisateur=plan.utilisateur, titre=f"{plan.titre} — {libelle}"[:200], nature="requete", format=plan.format,
        parametres={"requete": requete.model_dump(mode="json")}, planification=plan)
    plan.dernier_lancement = maintenant
    plan.save(update_fields=["dernier_lancement"])
    lancer(rapport)
    return rapport


def lancer_dus(maintenant: datetime | None = None) -> int:
    """Lance les rapports planifiés arrivés à échéance ; un seul lancement par rapport, même
    après une interruption du worker (pas de rattrapage des échéances manquées)."""
    maintenant = maintenant or timezone.now()
    lances = 0
    for plan in RapportPlanifie.objects.filter(actif=True, prochain_lancement__lte=maintenant):
        plan.planifier(maintenant)
        plan.save(update_fields=["prochain_lancement"])
        try:
            lancer_planifie(plan, maintenant)
        except Exception:  # noqa: BLE001 — un rapport en échec ne bloque pas les suivants
            log.exception("échec du lancement du rapport planifié %s", plan.pk)
            continue
        lances += 1
    return lances
