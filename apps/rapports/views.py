from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe, require_http_methods
from pydantic import ValidationError

from apps.comptes import suivi
from apps.comptes.acces import kpis_autorises
from apps.evenements import periode
from apps.evenements.analyse import NIVEAUX
from apps.evenements.models import Evenement
from apps.evenements.acces import evenements_visibles
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
    return f"KPI {'/'.join(req.techno)} : {', '.join(req.perimetre.valeurs) or 'réseau'}"


@login_required
@require_POST
def rapport_requete(request):
    """Rapport d'une requête KPI : mêmes paramètres que l'écran de requête."""
    fmt = request.POST.get("format", "pptx")
    if fmt not in dict(Rapport.FORMATS):
        raise Http404
    req = _requete(request.POST, request.user)
    if req is None:
        champs = ('format', 'kpis', 'debut', 'fin', 'heures', 'perimetre_type', 'perimetre_valeurs')
        params = {k: request.POST.getlist(k) for k in champs if k in request.POST}
        demande = suivi.commencer(request.user, 'rapport', 'Rapport non créé', params,
                                   suivi.origine(request.user, request.POST.get('suivi')))
        suivi.terminer(demande, 'erreur', 'Impossible de créer le rapport : paramètres de requête invalides.')
        messages.error(request, "Impossible de créer le rapport : paramètres de requête invalides.")
        return redirect("kpi:requete")
    titre = f"{_titre(req)} : {req.periode.debut:%d/%m/%Y}-{req.periode.fin:%d/%m/%Y}"
    rapport = Rapport.objects.create(utilisateur=request.user, titre=titre[:200], nature="requete", format=fmt,
                                     parametres={"requete": req.model_dump(mode="json")})
    if lancer(rapport, parent=suivi.origine(request.user, request.POST.get("suivi"))):
        messages.success(request, f"Rapport {rapport.get_format_display()} en cours de génération.")
    else:
        messages.error(request, rapport.message)
    return redirect("rapports:liste")


@login_required
@require_POST
def rapport_evenement(request, pk):
    evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    niveau = request.POST.get("niveau", "secteur")
    fmt = request.POST.get("format", "pptx")
    if niveau not in NIVEAUX or fmt not in dict(Rapport.FORMATS):
        raise Http404
    # Période affichée sur la page de l'événement ; à défaut, ses créneaux mémorisés.
    try:
        creneaux = periode.lire(request.POST.getlist("debut"), request.POST.getlist("fin")) or periode.memorises(evenement)
    except periode.PeriodeInvalide as e:
        messages.error(request, str(e))
        return redirect("evenements:detail", evenement.pk)
    quand = f" du {creneaux[0][0]:%d/%m/%Y}" if creneaux else ""
    rapport = Rapport.objects.create(
        utilisateur=request.user, titre=f"{evenement.nom}{quand} : par {niveau}"[:200], nature="evenement", format=fmt,
        parametres={"evenement": evenement.pk, "niveau": niveau,
                    "creneaux": [[d.isoformat(), f.isoformat()] for d, f in creneaux]})
    if lancer(rapport, parent=suivi.origine(request.user, request.POST.get("suivi"))):
        messages.success(request, f"Rapport {rapport.get_format_display()} en cours de génération.")
    else:
        messages.error(request, rapport.message)
    return redirect("rapports:liste")


@login_required
@require_safe
def liste(request):
    tous = Rapport.objects.filter(utilisateur=request.user)
    plans = RapportPlanifie.objects.filter(utilisateur=request.user)
    recherche = request.GET.get("recherche", "").strip()[:150]
    fmt = request.GET.get("format", "")
    rapports = tous
    if recherche:
        rapports = rapports.filter(titre__icontains=recherche)
        plans = plans.filter(titre__icontains=recherche)
    if fmt in dict(Rapport.FORMATS):
        rapports = rapports.filter(format=fmt)
        plans = plans.filter(format=fmt)
    else:
        fmt = ""
    rapports = rapports[:50]
    return render(request, "rapports/liste.html",
                  {"rapports": rapports, "rafraichir": any(r.en_cours for r in rapports),
                   "planifies": plans, "recherche": recherche, "format_filtre": fmt,
                   "formats": Rapport.FORMATS, "nb_fichiers": tous.count(),
                   "nb_prets": tous.filter(statut="termine").count(),
                   "nb_attente": tous.filter(statut__in=("en_attente", "en_cours")).count(),
                   "nb_planifies": RapportPlanifie.objects.filter(utilisateur=request.user, actif=True).exclude(frequence="aucune").count()})


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
@require_http_methods(["GET", "HEAD", "POST"])
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
            # Les créneaux fixes de l'accueil ne s'appliquent pas à une période relative.
            plan.requete = req.model_dump(mode="json", exclude={"periode", "heures"})
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
    try:
        rapport = lancer_planifie(plan)
    except (ValueError, TypeError, KeyError):
        messages.error(request, "Ce rapport enregistré est invalide. Enregistrez-le à nouveau depuis une recherche.")
        return redirect("rapports:liste")
    if rapport.statut == "erreur":
        messages.error(request, rapport.message)
    else:
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
@require_safe
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
