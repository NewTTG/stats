import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Min
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe
from sqlalchemy.exc import SQLAlchemyError

from apps.comptes.models import JournalAudit
from apps.comptes import suivi
from apps.kpi.source import BaseKpiNonConfiguree, MESSAGE_BASE_INDISPONIBLE, moteur_kpi
from apps.rapports.contenu import LIBELLES_REGLE

from .acces import evenements_visibles
from .analyse import NIVEAUX, AnalyseImpossible, analyser
from .edition import EvenementForm, creneaux_formset, groupes_kpi, nb_kpis_principaux, reseau_pour_carte
from .models import Evenement

journal = logging.getLogger(__name__)

@login_required
@require_safe
def liste(request):
    evenements = evenements_visibles(request.user).annotate(nb_creneaux=Count("creneaux"), debut=Min("creneaux__debut"))
    recherche = request.GET.get("recherche", "").strip()[:150]
    if recherche:
        evenements = evenements.filter(nom__icontains=recherche)
    dates = sorted((e for e in evenements if e.debut), key=lambda e: e.debut, reverse=True)
    sans_date = [e for e in evenements if not e.debut]
    return render(request, "evenements/liste.html", {"evenements": dates, "sans_date": sans_date, "recherche": recherche})


def _graphiques(res):
    return {"instants": res.instants, "kpis": [
        {"titre": f"{c.kpi.libelle} ({c.kpi.unite})", "unite": c.kpi.unite, "seuils": c.kpi.seuils.model_dump(),
         "evenement": c.evenement, "reference": c.reference, "min": c.ref_min, "max": c.ref_max}
        for c in res.courbes]}


@login_required
@require_safe
def detail(request, pk):
    evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    statut = 200
    niveau = request.GET.get("niveau", "secteur")
    if niveau not in NIVEAUX:
        niveau = "secteur"
    contexte = {"evenement": evenement, "niveau": niveau, "niveaux": NIVEAUX, "regles": LIBELLES_REGLE}
    demande = suivi.commencer(request.user, 'evenement', evenement.nom,
                              {'evenement': evenement.pk, 'niveau': niveau}) if request.method == 'GET' else None
    contexte['suivi'] = str(demande.pk) if demande else ''
    try:
        analyse = analyser(evenement, request.user, moteur_kpi(), niveau=niveau)
        JournalAudit.objects.create(utilisateur=request.user, action="analyse_evenement",
                                    requete={"evenement": evenement.pk, "niveau": niveau})
        contexte["analyse"] = analyse
        contexte["blocs"] = [{"res": r, "graphiques": _graphiques(r), "id": f"courbes-{r.techno}"}
                             for r in analyse.par_techno]
    except AnalyseImpossible as e:
        contexte["erreur"] = str(e)
    except BaseKpiNonConfiguree as e:
        contexte["erreur"] = str(e) if request.user.is_staff else MESSAGE_BASE_INDISPONIBLE
    except SQLAlchemyError:
        journal.exception("Événement %s : source KPI indisponible", pk)
        contexte["erreur"] = MESSAGE_BASE_INDISPONIBLE
        statut = 503
    except Exception:
        suivi.terminer(demande, 'erreur', 'Erreur inattendue pendant l’analyse de l’événement.')
        raise
    if contexte.get('erreur'):
        suivi.terminer(demande, 'erreur', contexte['erreur'])
    else:
        presentes = sum(r.nb_cellules - len(r.cellules_sans_donnees) for r in analyse.par_techno)
        suivi.terminer(demande, 'reussie' if presentes else 'sans_donnees',
                       resultat={'cellules_avec_donnees': presentes, 'avertissements': analyse.avertissements})
    return render(request, "evenements/detail.html", contexte, status=statut)


# ------------------------------------------------------------------ création / modification

def _exiger(request, droit):
    if not request.user.has_perm(f"evenements.{droit}_evenement"):
        raise PermissionDenied


@login_required
def edition(request, pk=None):
    """Création (``pk`` vide) ou modification d'un événement : zone couverte sur carte, créneaux, KPI."""
    if pk is None:
        _exiger(request, "add")
        evenement = Evenement()
    else:
        _exiger(request, "change")
        evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    donnees = request.POST if request.method == "POST" else None
    formulaire = EvenementForm(donnees, instance=evenement)
    creneaux = creneaux_formset(evenement, donnees)
    if donnees is not None and formulaire.is_valid() and creneaux.is_valid():
        with transaction.atomic():
            evenement = formulaire.save(commit=False)
            if not evenement.cree_par_id:
                evenement.cree_par = request.user
            evenement.save()
            creneaux.instance = evenement
            creneaux.save()
        JournalAudit.objects.create(utilisateur=request.user,
                                    action="creation_evenement" if pk is None else "modification_evenement",
                                    requete={"evenement": evenement.pk, "nom": evenement.nom})
        messages.success(request, f"Événement « {evenement.nom} » enregistré.")
        if "_continuer" in request.POST:
            return redirect("evenements:modifier", evenement.pk)
        return redirect("evenements:detail", evenement.pk)
    return render(request, "evenements/edition.html", {
        "evenement": evenement, "formulaire": formulaire, "creneaux": creneaux,
        "erreurs": donnees is not None,
        "types_existants": sorted(set(Evenement.objects.exclude(type="").values_list("type", flat=True))),
        "groupes_kpi": groupes_kpi(formulaire), "nb_kpis_principaux": nb_kpis_principaux(),
        "kpis_choisis": bool(formulaire["kpis_choisis"].value()),
        "carte_tuiles": settings.CARTE_TUILES_URL, "carte_attribution": settings.CARTE_TUILES_ATTRIBUTION,
        "peut_supprimer": pk is not None and request.user.has_perm("evenements.delete_evenement"),
    })


@login_required
@require_POST
def supprimer(request, pk):
    _exiger(request, "delete")
    evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    JournalAudit.objects.create(utilisateur=request.user, action="suppression_evenement",
                                requete={"evenement": evenement.pk, "nom": evenement.nom})
    evenement.delete()
    messages.success(request, f"Événement « {evenement.nom} » supprimé.")
    return redirect("evenements:liste")


@login_required
@require_safe
def reseau_json(request):
    """Référentiel pour la carte de sélection (sites, secteurs avec azimut, cellules)."""
    if not (request.user.has_perm("evenements.add_evenement") or request.user.has_perm("evenements.change_evenement")):
        raise PermissionDenied
    return JsonResponse(reseau_pour_carte(), json_dumps_params={"ensure_ascii": False, "separators": (",", ":")})
