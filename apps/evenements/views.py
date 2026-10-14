import logging
from itertools import zip_longest
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Min
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from sqlalchemy.exc import SQLAlchemyError

from apps.comptes.models import JournalAudit
from apps.comptes import suivi
from apps.comptes.acces import cellules_autorisees, voit_tout_le_reseau
from apps.kpi.source import BaseKpiNonConfiguree, MESSAGE_BASE_INDISPONIBLE, moteur_kpi
from apps.rapports.contenu import LIBELLES_REGLE

from . import acces
from .acces import evenements_visibles
from .analyse import NIVEAUX, AnalyseImpossible, analyser
from . import periode
from .edition import EvenementForm, groupes_kpi, nb_kpis_principaux, reseau_pour_carte, zone_pour_carte
from .models import Creneau, Evenement

journal = logging.getLogger(__name__)

@login_required
@require_safe
def liste(request):
    evenements = evenements_visibles(request.user).annotate(nb_creneaux=Count("creneaux"), debut=Min("creneaux__debut"))
    recherche = request.GET.get("recherche", "").strip()[:150]
    if recherche:
        evenements = evenements.filter(nom__icontains=recherche)
    # Période mémorisée la plus récente d'abord ; sans période, par nom (elle se choisit à l'affichage).
    dates = sorted((e for e in evenements if e.debut), key=lambda e: e.debut, reverse=True)
    sans_date = sorted((e for e in evenements if not e.debut), key=lambda e: e.nom.lower())
    return render(request, "evenements/liste.html", {"evenements": dates + sans_date, "recherche": recherche})


def _graphiques(res):
    return {"instants": res.instants, "kpis": [
        {"titre": f"{c.kpi.libelle} ({c.kpi.unite})", "unite": c.kpi.unite, "seuils": c.kpi.seuils.model_dump(),
         "evenement": c.evenement, "reference": c.reference, "min": c.ref_min, "max": c.ref_max,
         "sites": [{"nom": n, "valeurs": v} for n, v in c.par_site.items()],
         "cellules": [{"nom": n, "valeurs": v} for n, v in c.par_cellule.items()]}
        for c in res.courbes]}


def _periode_demandee(request, evenement):
    """(créneaux, saisie à afficher, erreur) : période de l'adresse, sinon créneaux mémorisés."""
    try:
        creneaux, saisie = periode.lire(request.GET)
    except periode.PeriodeInvalide as e:
        return [], _saisie_brute(request.GET), str(e)
    if not creneaux and not saisie.du and not saisie.detail:
        creneaux = periode.memorises(evenement)
        saisie = periode.saisie(creneaux)
    return creneaux, saisie, None


def _saisie_brute(donnees):
    """Saisie erronée réaffichée telle quelle."""
    if donnees.get("detail"):
        return periode.Saisie(detail=True, lignes=list(zip_longest(
            donnees.getlist("jour"), donnees.getlist("de"), donnees.getlist("a"), fillvalue="")))
    return periode.Saisie(du=donnees.get("du", ""), au=donnees.get("au", ""), de=donnees.get("de", ""),
                          a=donnees.get("a", ""))


@login_required
@require_safe
def detail(request, pk):
    evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    statut = 200
    niveau = request.GET.get("niveau", "secteur")
    if niveau not in NIVEAUX:
        niveau = "secteur"
    creneaux, saisie, erreur_periode = _periode_demandee(request, evenement)
    parametres = periode.parametres(creneaux)
    url = reverse("evenements:detail", args=[evenement.pk])
    contexte = {
        "evenement": evenement, "niveau": niveau, "niveaux": NIVEAUX, "regles": LIBELLES_REGLE,
        "zone": zone_pour_carte(evenement),
        "carte_tuiles": settings.CARTE_TUILES_URL, "carte_attribution": settings.CARTE_TUILES_ATTRIBUTION,
        "creneaux": creneaux, "saisie": saisie, "erreur_periode": erreur_periode,
        "lignes_detail": saisie.lignes or [("", "", "")],
        "heures_debut": periode.HEURES_DEBUT, "heures_fin": periode.HEURES_FIN,
        "periode_url": urlencode(parametres),
        "parametres_periode": parametres,
        "decalages": [(libelle, f"{url}?{urlencode(periode.parametres(periode.decaler(creneaux, mois, jours)) + [('niveau', niveau)])}")
                      for libelle, mois, jours in periode.DECALAGES] if creneaux else [],
        "peut_memoriser": bool(creneaux) and creneaux != periode.memorises(evenement),
    }
    if not creneaux:  # rien à analyser : on demande la période
        return render(request, "evenements/detail.html", contexte)
    trace = {'evenement': evenement.pk, 'niveau': niveau,
             'creneaux': [[d.isoformat(), f.isoformat()] for d, f in creneaux]}
    demande = suivi.commencer(request.user, 'evenement', evenement.nom, trace) if request.method == 'GET' else None
    contexte['suivi'] = str(demande.pk) if demande else ''
    try:
        analyse = analyser(evenement, request.user, moteur_kpi(), niveau=niveau, creneaux=creneaux)
        JournalAudit.objects.create(utilisateur=request.user, action="analyse_evenement", requete=trace)
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


@login_required
@require_POST
def memoriser_periode(request, pk):
    """La période affichée devient celle proposée à la prochaine ouverture de l'événement."""
    evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    try:
        creneaux = periode.lire(request.POST)[0]
    except periode.PeriodeInvalide as e:
        messages.error(request, str(e))
        return redirect("evenements:detail", evenement.pk)
    with transaction.atomic():
        evenement.creneaux.all().delete()
        Creneau.objects.bulk_create([Creneau(evenement=evenement, debut=timezone.make_aware(d), fin=timezone.make_aware(f))
                                     for d, f in creneaux])
    messages.success(request, "Période mémorisée : elle sera proposée à la prochaine ouverture de l'événement.")
    return redirect(f"{reverse('evenements:detail', args=[evenement.pk])}?{urlencode(periode.parametres(creneaux))}")


# ------------------------------------------------------------------ création / modification

@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def edition(request, pk=None):
    """Création (``pk`` vide) ou modification d'un événement : zone couverte sur carte, créneaux, KPI.
    Ouverte à tous : on modifie les événements que l'on voit (cf. ``acces``)."""
    if pk is None:
        evenement = Evenement()
    else:
        evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    donnees = request.POST if request.method == "POST" else None
    formulaire = EvenementForm(donnees, instance=evenement,
                               visibilite=acces.peut_choisir_visibilite(request.user, evenement))
    if donnees is not None and formulaire.is_valid():
        evenement = formulaire.save(commit=False)
        if not evenement.cree_par_id:
            evenement.cree_par = request.user
        evenement.save()
        JournalAudit.objects.create(utilisateur=request.user,
                                    action="creation_evenement" if pk is None else "modification_evenement",
                                    requete={"evenement": evenement.pk, "nom": evenement.nom})
        messages.success(request, f"Événement « {evenement.nom} » enregistré.")
        if "_continuer" in request.POST:
            return redirect("evenements:modifier", evenement.pk)
        return redirect("evenements:detail", evenement.pk)
    return render(request, "evenements/edition.html", {
        "evenement": evenement, "formulaire": formulaire,
        "erreurs": donnees is not None,
        "types_existants": sorted(set(evenements_visibles(request.user).exclude(type="").values_list(
            "type", flat=True))),
        "groupes_kpi": groupes_kpi(formulaire), "nb_kpis_principaux": nb_kpis_principaux(),
        "kpis_choisis": bool(formulaire["kpis_choisis"].value()),
        "carte_tuiles": settings.CARTE_TUILES_URL, "carte_attribution": settings.CARTE_TUILES_ATTRIBUTION,
        "peut_supprimer": pk is not None and acces.peut_supprimer(request.user, evenement),
    })


@login_required
@require_POST
def supprimer(request, pk):
    evenement = get_object_or_404(evenements_visibles(request.user, Evenement.objects.filter(pk=pk)))
    if not acces.peut_supprimer(request.user, evenement):
        raise PermissionDenied
    JournalAudit.objects.create(utilisateur=request.user, action="suppression_evenement",
                                requete={"evenement": evenement.pk, "nom": evenement.nom})
    evenement.delete()
    messages.success(request, f"Événement « {evenement.nom} » supprimé.")
    return redirect("evenements:liste")


@login_required
@require_safe
def reseau_json(request):
    """Référentiel pour la carte de sélection (sites, secteurs avec azimut, cellules), limité au
    périmètre autorisé : la création d'événements est ouverte à tous."""
    permises = None if voit_tout_le_reseau(request.user) else set().union(
        *(cellules_autorisees(request.user, techno) for techno in ("LTE", "WCDMA")))
    return JsonResponse(reseau_pour_carte(permises), json_dumps_params={"ensure_ascii": False, "separators": (",", ":")})
