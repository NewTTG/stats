from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from pydantic import ValidationError

from apps.comptes.acces import kpis_autorises
from apps.evenements.analyse import NIVEAUX
from apps.evenements.models import Evenement
from apps.kpi.catalogue import catalogue
from apps.kpi.forms import RequeteForm, champs_depuis_requete
from apps.kpi.recherche.dates import preset
from apps.kpi.requete import RequeteKpi

from .lancement import lancer
from .models import Rapport, RapportPlanifie
from .planification import lancer_planifie


def _requete(donnees, user) -> RequeteKpi | None:
    """Requête KPI transmise par les champs du formulaire de requête (None : invalide)."""
    form = RequeteForm(donnees, kpis_visibles=kpis_autorises(user, set(catalogue())))
    try:
        return RequeteKpi(**form.vers_requete()) if form.is_valid() else None
    except (ValueError, ValidationError):
        return None


def _titre(req: RequeteKpi) -> str:
    return f"KPI {'/'.join(req.techno)} — {', '.join(req.perimetre.valeurs) or 'réseau'}"


@login_required
@require_POST
def rapport_requete(request):
    """PowerPoint d'une requête KPI : mêmes paramètres que l'écran de requête."""
    req = _requete(request.POST, request.user)
    if req is None:
        messages.error(request, "Impossible de créer le rapport : paramètres de requête invalides.")
        return redirect("kpi:requete")
    titre = f"{_titre(req)} — {req.periode.debut:%d/%m/%Y}-{req.periode.fin:%d/%m/%Y}"
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
                  {"rapports": rapports, "rafraichir": any(r.en_cours for r in rapports),
                   "planifies": RapportPlanifie.objects.filter(utilisateur=request.user)})


class PlanificationForm(forms.ModelForm):
    class Meta:
        model = RapportPlanifie
        fields = ["titre", "periode", "format", "frequence", "jour_semaine", "heure"]
        help_texts = {"periode": "Recalculée à chaque lancement (ex. semaine dernière = lundi à dimanche "
                                 "précédents).",
                      "jour_semaine": "Pour un rapport hebdomadaire."}


def _periode_probable(req: RequeteKpi, jour) -> str:
    """Période relative correspondant aux dates de la requête (7 derniers jours à défaut)."""
    for code, _ in RapportPlanifie.PERIODES:
        p = preset(code, jour)
        if (p.debut, p.fin) == (req.periode.debut, req.periode.fin):
            return code
    return "7j"


@login_required
def enregistrer(request):
    """Enregistre la requête affichée comme rapport, relancé à la demande ou planifié."""
    donnees = request.POST if request.method == "POST" else request.GET
    req = _requete(donnees, request.user)
    if req is None:
        messages.error(request, "Impossible d'enregistrer ce rapport : paramètres de requête invalides.")
        return redirect("kpi:requete")
    if request.method == "POST":
        form = PlanificationForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.utilisateur = request.user
            plan.requete = req.model_dump(mode="json", exclude={"periode"})
            plan.planifier()
            plan.save()
            messages.success(request, f"Rapport « {plan.titre} » enregistré"
                             + (f" : {plan.description_frequence.lower()}." if plan.planifie else "."))
            return redirect("rapports:liste")
    else:
        form = PlanificationForm(initial={"titre": _titre(req)[:150],
                                          "periode": _periode_probable(req, timezone.localdate())})
    return render(request, "rapports/enregistrer.html", {
        "form": form, "requete": req,
        "requete_params": [(k, v if isinstance(v, list) else [v]) for k, v in champs_depuis_requete(req).items()],
    })


def _plan(request, pk) -> RapportPlanifie:
    return get_object_or_404(RapportPlanifie, pk=pk, utilisateur=request.user)


@login_required
@require_POST
def planifie_lancer(request, pk):
    plan = _plan(request, pk)
    rapport = lancer_planifie(plan)
    messages.success(request, f"Rapport {rapport.get_format_display()} « {plan.titre} » en cours de génération.")
    return redirect("rapports:liste")


@login_required
@require_POST
def planifie_basculer(request, pk):
    plan = _plan(request, pk)
    plan.actif = not plan.actif
    plan.planifier()
    plan.save(update_fields=["actif", "prochain_lancement"])
    messages.success(request, f"Rapport « {plan.titre} » {'réactivé' if plan.actif else 'suspendu'}.")
    return redirect("rapports:liste")


@login_required
@require_POST
def planifie_supprimer(request, pk):
    plan = _plan(request, pk)
    plan.delete()
    messages.success(request, f"Rapport « {plan.titre} » supprimé (les fichiers déjà générés sont conservés).")
    return redirect("rapports:liste")


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
