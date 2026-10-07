"""Tâche django-q2 : génère le fichier d'un ``Rapport``, avec les droits de son auteur."""

import logging
import re
import unicodedata

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.evenements.analyse import AnalyseImpossible, analyser
from apps.evenements.models import Evenement
from apps.kpi.requete import RequeteKpi
from apps.kpi.service import RequeteRefusee, executer
from apps.kpi.source import BaseKpiNonConfiguree, moteur_kpi

from .contenu import pptx_evenement, pptx_requete, xlsx_evenement
from .models import Rapport

log = logging.getLogger(__name__)


def _nom_fichier(rapport: Rapport) -> str:
    ascii_ = unicodedata.normalize("NFKD", rapport.titre).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_).strip("_")[:60] or "rapport"
    return f"{base}_{timezone.localtime():%Y%m%d_%H%M}.{rapport.format}"


def contenu(rapport: Rapport) -> bytes:
    p, user = rapport.parametres, rapport.utilisateur
    if rapport.nature == "requete":
        return pptx_requete(executer(RequeteKpi(**p["requete"]), user, moteur_kpi()))
    evenement = Evenement.objects.get(pk=p["evenement"])
    analyse = analyser(evenement, user, moteur_kpi(), niveau=p.get("niveau", "secteur"))
    return (pptx_evenement if rapport.format == "pptx" else xlsx_evenement)(analyse)


def generer(rapport_id: int):
    rapport = Rapport.objects.select_related("utilisateur").get(pk=rapport_id)
    rapport.statut = "en_cours"
    rapport.save(update_fields=["statut"])
    try:
        rapport.fichier.save(_nom_fichier(rapport), ContentFile(contenu(rapport)), save=False)
        rapport.statut, rapport.message = "termine", ""
    except (RequeteRefusee, AnalyseImpossible, BaseKpiNonConfiguree, Evenement.DoesNotExist) as e:
        rapport.statut, rapport.message = "erreur", str(e) or "Événement supprimé."
    except Exception as e:  # noqa: BLE001 — l'erreur est affichée dans l'historique
        log.exception("échec du rapport %s", rapport_id)
        rapport.statut, rapport.message = "erreur", f"Erreur inattendue : {e}"
    rapport.termine_le = timezone.now()
    rapport.save()
