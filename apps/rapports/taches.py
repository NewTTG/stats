"""Tâche django-q2 : génère le fichier d'un ``Rapport``, avec les droits de son auteur."""

import logging
import re
import unicodedata

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.evenements.analyse import AnalyseImpossible, analyser
from apps.evenements.models import Evenement
from apps.evenements.acces import evenements_visibles
from apps.kpi.export_excel import construire as construire_excel
from apps.kpi.requete import RequeteKpi
from apps.kpi.service import RequeteRefusee, executer
from apps.kpi.source import BaseKpiNonConfiguree, MESSAGE_BASE_INDISPONIBLE, moteur_kpi

from .contenu import pptx_evenement, pptx_requete, xlsx_evenement
from .models import Rapport
from .pdf import pdf_evenement, pdf_requete

log = logging.getLogger(__name__)


def _nom_fichier(rapport: Rapport) -> str:
    ascii_ = unicodedata.normalize("NFKD", rapport.titre).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_).strip("_")[:60] or "rapport"
    return f"{base}_{timezone.localtime():%Y%m%d_%H%M}.{rapport.format}"


def contenu(rapport: Rapport) -> bytes:
    p, user = rapport.parametres, rapport.utilisateur
    if rapport.nature == "requete":
        resultat = executer(RequeteKpi(**p["requete"]), user, moteur_kpi())
        return {"pptx": pptx_requete, "xlsx": construire_excel, "pdf": pdf_requete}[rapport.format](resultat)
    evenement = evenements_visibles(user, Evenement.objects.filter(pk=p["evenement"])).get()
    analyse = analyser(evenement, user, moteur_kpi(), niveau=p.get("niveau", "secteur"))
    return {"pptx": pptx_evenement, "xlsx": xlsx_evenement, "pdf": pdf_evenement}[rapport.format](analyse)


def generer(rapport_id: int):
    rapport = Rapport.objects.select_related("utilisateur").get(pk=rapport_id)
    rapport.statut = "en_cours"
    rapport.save(update_fields=["statut"])
    try:
        rapport.fichier.save(_nom_fichier(rapport), ContentFile(contenu(rapport)), save=False)
        rapport.statut, rapport.message = "termine", ""
    except BaseKpiNonConfiguree as e:
        rapport.statut = "erreur"
        rapport.message = str(e) if rapport.utilisateur.is_staff else MESSAGE_BASE_INDISPONIBLE
    except (RequeteRefusee, AnalyseImpossible, Evenement.DoesNotExist) as e:
        rapport.statut, rapport.message = "erreur", str(e) or "Événement supprimé."
    except Exception:  # noqa: BLE001 : les détails techniques restent dans les journaux
        log.exception("échec du rapport %s", rapport_id)
        rapport.statut, rapport.message = "erreur", "La génération a échoué. Réessayez ou contactez votre administrateur."
    rapport.termine_le = timezone.now()
    rapport.save()
