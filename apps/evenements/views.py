from django.contrib.auth.decorators import login_required
from django.db.models import Count, Min
from django.shortcuts import get_object_or_404, render

from apps.comptes.models import JournalAudit
from apps.kpi.source import BaseKpiNonConfiguree, moteur_kpi
from apps.rapports.contenu import LIBELLES_REGLE

from .analyse import NIVEAUX, AnalyseImpossible, analyser
from .models import Evenement



@login_required
def liste(request):
    evenements = Evenement.objects.annotate(nb_creneaux=Count("creneaux"), debut=Min("creneaux__debut"))
    dates = sorted((e for e in evenements if e.debut), key=lambda e: e.debut, reverse=True)
    sans_date = [e for e in evenements if not e.debut]
    return render(request, "evenements/liste.html", {"evenements": dates, "sans_date": sans_date})


def _graphiques(res):
    return {"instants": res.instants, "kpis": [
        {"titre": f"{c.kpi.libelle} ({c.kpi.unite})", "unite": c.kpi.unite, "seuils": c.kpi.seuils.model_dump(),
         "evenement": c.evenement, "reference": c.reference, "min": c.ref_min, "max": c.ref_max}
        for c in res.courbes]}


@login_required
def detail(request, pk):
    evenement = get_object_or_404(Evenement, pk=pk)
    niveau = request.GET.get("niveau", "secteur")
    if niveau not in NIVEAUX:
        niveau = "secteur"
    contexte = {"evenement": evenement, "niveau": niveau, "niveaux": NIVEAUX, "regles": LIBELLES_REGLE}
    try:
        analyse = analyser(evenement, request.user, moteur_kpi(), niveau=niveau)
        JournalAudit.objects.create(utilisateur=request.user, action="analyse_evenement",
                                    requete={"evenement": evenement.pk, "niveau": niveau})
        contexte["analyse"] = analyse
        contexte["blocs"] = [{"res": r, "graphiques": _graphiques(r), "id": f"courbes-{r.techno}"}
                             for r in analyse.par_techno]
    except (AnalyseImpossible, BaseKpiNonConfiguree) as e:
        contexte["erreur"] = str(e)
    return render(request, "evenements/detail.html", contexte)
