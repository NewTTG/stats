import math

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from pydantic import ValidationError

from apps.comptes.acces import kpis_autorises
from apps.comptes.models import JournalAudit

from .catalogue import catalogue
from .forms import RequeteForm
from .requete import RequeteKpi
from .service import RequeteRefusee, executer
from .source import BaseKpiNonConfiguree, moteur_kpi

FORMAT_PERIODE = {"heure": "%d/%m/%Y %Hh", "jour": "%d/%m/%Y", "semaine": "sem. du %d/%m/%Y", "mois": "%m/%Y"}


def _statut(kpi, valeur):
    if valeur is None or kpi.seuils.alerte is None:
        return ""
    pire = (lambda v, s: v <= s) if kpi.sens == "haut_est_mieux" else (lambda v, s: v >= s)
    if kpi.seuils.critique is not None and pire(valeur, kpi.seuils.critique):
        return "critique"
    return "alerte" if pire(valeur, kpi.seuils.alerte) else ""


def _lignes(res_techno, granularite_temps):
    lignes = []
    for (periode, entite), valeurs in res_techno.table.iterrows():
        cellules = []
        for k in res_techno.kpis:
            v = valeurs[k.code]
            v = None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
            cellules.append({"valeur": v, "statut": _statut(k, v)})
        lignes.append({"periode": periode.strftime(FORMAT_PERIODE[granularite_temps]), "entite": entite,
                       "valeurs": cellules})
    return lignes


@login_required
def requete(request):
    visibles = kpis_autorises(request.user, set(catalogue()))
    form = RequeteForm(request.GET or None, kpis_visibles=visibles)
    contexte = {"form": form}

    if form.is_bound and form.is_valid():
        try:
            req = RequeteKpi(**form.vers_requete())
            JournalAudit.objects.create(utilisateur=request.user, action="requete_kpi",
                                        requete=req.model_dump(mode="json"))
            resultat = executer(req, request.user, moteur_kpi())
            contexte["resultat"] = resultat
            contexte["blocs"] = [{"res": r, "lignes": _lignes(r, req.granularite_temps)}
                                 for r in resultat.par_techno]
        except ValidationError as e:
            contexte["erreur"] = "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
        except (RequeteRefusee, BaseKpiNonConfiguree) as e:
            contexte["erreur"] = str(e)
    return render(request, "kpi/requete.html", contexte)
