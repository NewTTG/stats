import math

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from pydantic import ValidationError

from apps.comptes.acces import kpis_autorises
from apps.comptes.models import JournalAudit

from .catalogue import catalogue
from .export_excel import construire as construire_excel
from .forms import RequeteForm
from .requete import RequeteKpi
from .service import RequeteRefusee, executer
from .source import BaseKpiNonConfiguree, moteur_kpi
from .statut import statut

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMAT_PERIODE = {"heure": "%d/%m/%Y %Hh", "jour": "%d/%m/%Y", "semaine": "sem. du %d/%m/%Y", "mois": "%m/%Y"}
# Au-delà, une courbe par entité devient illisible : on garde les premières.
SERIES_MAX = 12


def _valeur(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _lignes(res_techno, granularite_temps):
    lignes = []
    for (periode, entite), valeurs in res_techno.table.iterrows():
        cellules = []
        for k in res_techno.kpis:
            v = _valeur(valeurs[k.code])
            cellules.append({"valeur": v, "statut": statut(k, v)})
        lignes.append({"periode": periode.strftime(FORMAT_PERIODE[granularite_temps]), "entite": entite,
                       "valeurs": cellules})
    return lignes


def _synthese(res_techno):
    return [{"kpi": k, "valeur": (v := _valeur(res_techno.synthese_globale.get(k.code))), "statut": statut(k, v)}
            for k in res_techno.kpis]


def donnees_graphiques(res_techno, granularite_temps):
    """Données ECharts : un graphique par KPI, une série par entité."""
    table = res_techno.table
    if table.empty:
        return {"periodes": [], "kpis": [], "tronque": False}
    periodes = sorted(table.index.get_level_values("periode").unique())
    entites = list(dict.fromkeys(table.index.get_level_values("entite")))
    tronque = len(entites) > SERIES_MAX
    graphiques = []
    for k in res_techno.kpis:
        series = []
        for e in entites[:SERIES_MAX]:
            valeurs = table.xs(e, level="entite")[k.code].reindex(periodes)
            series.append({"nom": str(e), "valeurs": [_valeur(v) for v in valeurs]})
        graphiques.append({"titre": f"{k.libelle} ({k.unite})", "seuils": k.seuils.model_dump(), "series": series})
    return {
        "periodes": [p.strftime(FORMAT_PERIODE[granularite_temps]) for p in periodes],
        "kpis": graphiques,
        "tronque": tronque,
    }


@login_required
def requete(request):
    visibles = kpis_autorises(request.user, set(catalogue()))
    params = request.GET.copy()
    export = params.pop("export", [None])[0] == "xlsx"
    form = RequeteForm(params or None, kpis_visibles=visibles)
    contexte = {"form": form}

    if form.is_bound and form.is_valid():
        try:
            req = RequeteKpi(**form.vers_requete())
            JournalAudit.objects.create(utilisateur=request.user,
                                        action="export_excel" if export else "requete_kpi",
                                        requete=req.model_dump(mode="json"))
            resultat = executer(req, request.user, moteur_kpi())
            if export:
                reponse = HttpResponse(construire_excel(resultat), content_type=XLSX)
                nom = f"kpi_{req.periode.debut:%Y%m%d}_{req.periode.fin:%Y%m%d}.xlsx"
                reponse["Content-Disposition"] = f'attachment; filename="{nom}"'
                return reponse
            contexte["resultat"] = resultat
            requete_export = request.GET.copy()
            requete_export["export"] = "xlsx"
            contexte["lien_export"] = "?" + requete_export.urlencode()
            contexte["requete_params"] = list(params.lists())  # rapport PowerPoint (POST)
            contexte["blocs"] = [{"res": r,
                                  "lignes": _lignes(r, req.granularite_temps),
                                  "synthese": _synthese(r),
                                  "graphiques": donnees_graphiques(r, req.granularite_temps),
                                  "id_graphiques": f"graphiques-{r.techno}"}
                                 for r in resultat.par_techno]
        except ValidationError as e:
            contexte["erreur"] = "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())
        except (RequeteRefusee, BaseKpiNonConfiguree) as e:
            contexte["erreur"] = str(e)
    return render(request, "kpi/requete.html", contexte)
