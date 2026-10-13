import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Min
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe
from sqlalchemy.exc import SQLAlchemyError

from apps.comptes.models import JournalAudit
from apps.comptes import suivi
from apps.kpi.source import BaseKpiNonConfiguree, MESSAGE_BASE_INDISPONIBLE, moteur_kpi
from apps.rapports.contenu import LIBELLES_REGLE

from .analyse import NIVEAUX, AnalyseImpossible, analyser
from .models import Evenement
from .acces import evenements_visibles

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
