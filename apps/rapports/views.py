from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_q.tasks import async_task
from pydantic import ValidationError

from apps.comptes.acces import kpis_autorises
from apps.comptes.models import JournalAudit
from apps.evenements.analyse import NIVEAUX
from apps.evenements.models import Evenement
from apps.kpi.catalogue import catalogue
from apps.kpi.forms import RequeteForm
from apps.kpi.requete import RequeteKpi

from .models import Rapport


def lancer(rapport: Rapport):
    JournalAudit.objects.create(utilisateur=rapport.utilisateur, action=f"rapport_{rapport.nature}_{rapport.format}",
                                requete=rapport.parametres)
    async_task("apps.rapports.taches.generer", rapport.pk, task_name=f"rapport-{rapport.pk}")


@login_required
@require_POST
def rapport_requete(request):
    """PowerPoint d'une requête KPI : mêmes paramètres que l'écran de requête."""
    form = RequeteForm(request.POST, kpis_visibles=kpis_autorises(request.user, set(catalogue())))
    try:
        if not form.is_valid():
            raise ValueError("paramètres de requête invalides")
        req = RequeteKpi(**form.vers_requete())
    except (ValueError, ValidationError):
        messages.error(request, "Impossible de créer le rapport : paramètres de requête invalides.")
        return redirect("kpi:requete")
    p = req.perimetre
    titre = f"KPI {'/'.join(req.techno)} — {', '.join(p.valeurs) or 'réseau'} — {req.periode.debut:%d/%m/%Y}-{req.periode.fin:%d/%m/%Y}"
    rapport = Rapport.objects.create(utilisateur=request.user, titre=titre[:200], nature="requete", format="pptx",
                                     parametres={"requete": req.model_dump(mode="json")})
    lancer(rapport)
    messages.success(request, "Rapport PowerPoint en cours de génération.")
    return redirect("rapports:liste")


@login_required
@require_POST
def rapport_evenement(request, pk):
    evenement = get_object_or_404(Evenement, pk=pk)
    niveau = request.POST.get("niveau", "secteur")
    fmt = request.POST.get("format", "pptx")
    if niveau not in NIVEAUX or fmt not in ("pptx", "xlsx"):
        raise Http404
    rapport = Rapport.objects.create(
        utilisateur=request.user, titre=f"{evenement.nom} — par {niveau}"[:200], nature="evenement", format=fmt,
        parametres={"evenement": evenement.pk, "niveau": niveau})
    lancer(rapport)
    messages.success(request, f"Rapport {rapport.get_format_display()} en cours de génération.")
    return redirect("rapports:liste")


@login_required
def liste(request):
    rapports = Rapport.objects.filter(utilisateur=request.user)[:50]
    return render(request, "rapports/liste.html",
                  {"rapports": rapports, "rafraichir": any(r.en_cours for r in rapports)})


@login_required
def telecharger(request, pk):
    rapport = get_object_or_404(Rapport, pk=pk, utilisateur=request.user, statut="termine")
    try:
        if not rapport.fichier:
            raise FileNotFoundError(rapport.pk)
        fichier = rapport.fichier.open("rb")
    except (FileNotFoundError, OSError):
        # Fichier supprimé ou déplacé (autre serveur, purge du dossier media) : pas d'erreur 500.
        messages.error(request, f"Le fichier du rapport « {rapport.titre} » est introuvable : relancez-le.")
        return redirect("rapports:liste")
    return FileResponse(fichier, as_attachment=True, filename=rapport.fichier.name.rsplit("/", 1)[-1])
