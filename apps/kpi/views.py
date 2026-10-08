"""Écran de recherche KPI.

- barre de recherche en langage libre (``?q=…``, ``&ia=1`` pour l'interprétation IA) ;
  les paramètres explicites (réponses aux questions, puces modifiées) priment sur le
  texte ; sans état : l'URL suffit à rejouer (et partager) une recherche ;
- formulaire structuré (« Recherche avancée ») : ses paramètres GET historiques
  continuent de fonctionner ;
- exports Excel (``export=xlsx``) et rapport PowerPoint depuis tout résultat.
"""

import json
import logging
import math
import re
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from pydantic import ValidationError

from apps.comptes.acces import kpis_autorises, voit_tout_le_reseau
from apps.comptes.models import JournalAudit

from .catalogue import catalogue
from .export_excel import construire as construire_excel
from .forms import FENETRES, GRAN_ESPACE, GRAN_TEMPS, PERIMETRES, RequeteForm, champs_depuis_params, champs_depuis_requete
from .recherche import Contexte, affichage, avec_parametres, interpreter
from .recherche.construction import PARAMETRES, construire, parametres_explicites
from .recherche.dates import PRESETS, libelle_fenetre
from .recherche.ia import disponible as ia_disponible
from .recherche.interpretation import Demande
from .recherche.vocabulaire import LIBELLES_TECHNO, vocabulaire
from .requete import RequeteKpi
from .service import RequeteRefusee, executer
from .source import BaseKpiNonConfiguree, est_demo, infos_demo, moteur_kpi

journal = logging.getLogger(__name__)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMAT_PERIODE = {"heure": "%d/%m/%Y %Hh", "jour": "%d/%m/%Y", "semaine": "sem. du %d/%m/%Y", "mois": "%m/%Y"}
# Au-delà, une courbe par entité devient illisible : on garde les premières.
SERIES_MAX = 12
CHAMPS_FORMULAIRE = ("techno", "perimetre_type", "perimetre_valeurs", "debut", "fin", "granularite_temps",
                     "granularite_espace", "fenetre_horaire", "kpis")
# Paramètres remplacés par chaque éditeur de puce / réponse à une question.
REMPLACES = {
    "techno": ("techno", "kpis"),
    "kpis": ("kpis", "intention", "techno"),
    "perimetre": ("perimetre_type", "perimetre_valeurs"),
    "periode": ("periode", "debut", "fin"),
    "granularite_temps": ("granularite_temps",),
    "granularite_espace": ("granularite_espace",),
    "fenetre_horaire": ("fenetre_horaire",),
}
LIBELLES_CHAMP = {"techno": "Techno", "kpis": "KPI", "perimetre": "Lieu", "periode": "Période",
                  "granularite_temps": "Pas", "granularite_espace": "Niveau", "fenetre_horaire": "Heures"}
LIBELLES_CATEGORIE = {"debit": "Débit", "trafic": "Trafic", "accessibilite": "Accessibilité",
                      "retainability": "Coupures", "congestion": "Congestion", "mobilite": "Mobilité",
                      "disponibilite": "Disponibilité"}


def contexte_global(request):
    """Processeur de contexte : bandeau « données de démonstration » sur toutes les pages."""
    if not est_demo():
        return {"donnees_demo": False}
    infos = infos_demo()
    return {"donnees_demo": True, "demo_debut": infos.get("debut"), "demo_fin": infos.get("fin")}


def _valeur(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def donnees_graphiques(res_techno, granularite_temps):
    """Données de graphiques : un graphique par KPI, une série par entité (rapports PowerPoint)."""
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


# ------------------------------------------------------------------ liens et éditeurs

def _paires(get, retirer=()) -> list[tuple[str, str]]:
    """Paramètres courants (q, ia, paramètres explicites) sauf ceux à remplacer."""
    garder = ("q", "ia", *PARAMETRES)
    return [(k, v) for k, valeurs in get.lists() if k in garder and k not in retirer for v in valeurs if v != ""]


def _lien(get, params: dict, retirer=()) -> str:
    paires = _paires(get, retirer=(*retirer, *params))
    for k, v in params.items():
        paires += [(k, x) for x in (v if isinstance(v, list | tuple) else [v])]
    return "?" + urlencode(paires)


def _kpis_par_techno(cat, codes_choisis, technos_demandees=()):
    """Panneau de la puce KPI : technos demandées d'abord, KPI cochés en tête de chaque techno."""
    groupes = []
    ordre = [t for t in technos_demandees if t in ("LTE", "WCDMA")] + [t for t in ("LTE", "WCDMA")
                                                                      if t not in technos_demandees]
    for techno in ordre:
        kpis = [k for k in cat.values() if k.techno == techno]
        if not kpis:
            continue
        par_categorie = {}
        coches = [k for k in kpis if k.code in codes_choisis]
        if coches:
            par_categorie["Sélection actuelle"] = []
        for k in coches + [k for k in kpis if k.code not in codes_choisis]:
            categorie = "Sélection actuelle" if k.code in codes_choisis else LIBELLES_CATEGORIE.get(k.categorie, k.categorie)
            par_categorie.setdefault(categorie, []).append(
                {"code": k.code, "libelle": k.libelle, "unite": k.unite, "cause": bool(k.decomposition_de),
                 "coche": k.code in codes_choisis})
        groupes.append({"techno": techno, "nom": LIBELLES_TECHNO[techno], "categories": par_categorie.items()})
    return groupes


def _exemples(user, aujourdhui) -> list[str]:
    """Exemples de l'accueil : lieux du périmètre d'un lecteur restreint (m10) ; en
    démonstration, « hier » remplacé par le dernier jour disponible si la base est ancienne."""
    voc = vocabulaire()
    exemples = list(voc.exemples)
    if not voit_tout_le_reseau(user):
        visibles = [voc.libelle_commune(c) for c in Contexte.pour(user).lieux.communes_visibles]
        connues = sorted({voc.libelle_commune(c) for c in voc.communes}, key=len, reverse=True)
        sortie = []
        for n, e in enumerate(exemples):
            cite = next((c for c in connues if c in e), None)
            if cite and visibles:
                e = e.replace(cite, visibles[n % len(visibles)])
            elif cite:
                e = e.replace(f" à {cite}", "").replace(cite, "")
            sortie.append(e)
        exemples = sortie
    derniere = (infos_demo() or {}).get("fin") if est_demo() else None
    if isinstance(derniere, date):
        if derniere < aujourdhui - timedelta(days=1):
            exemples = [re.sub(r"\bhier\b", f"le {derniere:%d/%m/%Y}", e) for e in exemples]
    return exemples


def _parametres_resolus(q: str, params: dict):
    """Paramètres GET équivalents à l'interprétation (sans ``ia``) : après une recherche IA,
    les liens (puces, questions, export) rejouent la requête résolue sans rappeler le modèle."""
    from django.http import QueryDict

    get = QueryDict(mutable=True)
    get["q"] = q
    if params.get("kpis"):
        get.setlist("kpis", list(params["kpis"]))
    if params.get("perimetre"):
        get["perimetre_type"] = params["perimetre"]["type"]
        get["perimetre_valeurs"] = ", ".join(params["perimetre"]["valeurs"])
    if params.get("periode"):
        get["debut"] = params["periode"]["debut"].isoformat()
        get["fin"] = params["periode"]["fin"].isoformat()
    for cle in ("granularite_temps", "granularite_espace", "fenetre_horaire"):
        if params.get(cle):
            get[cle] = params[cle]
    return get


def _edition(get, interp, contexte: Contexte) -> dict:
    """Puces modifiables (formulaires GET) et questions (liens d'options)."""
    params = interp.params
    puces = []
    for p in interp.compris:
        puces.append({"puce": p, "champ_libelle": LIBELLES_CHAMP.get(p.champ, p.champ),
                      "caches": _paires(get, retirer=REMPLACES.get(p.champ, ()))})
    questions = []
    for q in interp.questions:
        questions.append({"question": q,
                          "options": [{"option": o, "lien": _lien(get, o.params, REMPLACES.get(q.champ, ()))}
                                      for o in q.options],
                          "caches": _paires(get, retirer=REMPLACES.get(q.champ, ()))})
    periode = params.get("periode") or {}
    fenetres = list(FENETRES)
    if params.get("fenetre_horaire") and params["fenetre_horaire"] not in dict(fenetres):
        fenetres.append((params["fenetre_horaire"], libelle_fenetre(params["fenetre_horaire"])))
    lieux = contexte.lieux
    return {
        "puces": puces,
        "questions": questions,
        "edition": {
            "technos": [(t, LIBELLES_TECHNO[t], t in params.get("techno", [])) for t in ("LTE", "WCDMA")],
            "kpis": _kpis_par_techno(contexte.catalogue, set(params.get("kpis", [])), params.get("techno", [])),
            "perimetre_types": PERIMETRES,
            "perimetre": params.get("perimetre") or {"type": "global", "valeurs": []},
            "perimetre_valeurs": ", ".join((params.get("perimetre") or {}).get("valeurs", [])),
            "suggestions": lieux.suggestions("", limite=200),
            "presets": [(c, PRESETS[c]) for c in ("hier", "7j", "semaine_derniere", "mois_dernier", "mois_courant", "30j")],
            "debut": periode.get("debut"),
            "fin": periode.get("fin"),
            "gran_temps": GRAN_TEMPS,
            "gran_espace": GRAN_ESPACE,
            "fenetres": fenetres,
        },
    }


def _requete_tracee(r: dict) -> RequeteKpi | None:
    req = r.get("requete", r)
    try:
        return RequeteKpi(**req) if isinstance(req, dict) else None
    except (ValidationError, TypeError, ValueError):
        return None


def _entree_recente(action: str, r) -> tuple[str, str, dict] | None:
    """(texte affiché, clé de dédoublonnage, paramètres du lien) d'une entrée d'audit, ou None."""
    r = r if isinstance(r, dict) else {}
    q = r.get("q") if isinstance(r.get("q"), str) else ""
    if action == "recherche_kpi" and q.strip():
        q = q.strip()[:300]
        parametres = r.get("parametres") if isinstance(r.get("parametres"), dict) else {}
        parametres = {k: v for k, v in parametres.items()
                      if k in PARAMETRES and (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v)))}
        requete = _requete_tracee(r) if r.get("ia") else None
        # Recherche IA : on rejoue la requête résolue (pas de nouvel appel au modèle).
        params = {"q": q, **(champs_depuis_requete(requete) if requete else parametres)}
        cle = json.dumps(["q", q.lower(), params], sort_keys=True, ensure_ascii=False)
        return q, cle, params
    requete = _requete_tracee(r)
    if requete is None:
        return None
    lieu = ", ".join(requete.perimetre.valeurs) or "réseau"
    texte = (f"{' + '.join(LIBELLES_TECHNO.get(t, t) for t in requete.techno)} · {len(requete.kpis)} KPI · {lieu} · "
             f"{requete.periode.debut:%d/%m} → {requete.periode.fin:%d/%m/%Y}")
    return texte, json.dumps(["f", texte]), champs_depuis_requete(requete)


def _recherches_recentes(user, nombre=6) -> list[dict]:
    """Dernières recherches de l'utilisateur (journal d'audit), sans doublon.

    Robuste à toute entrée malformée : une entrée illisible est ignorée, jamais d'erreur 500.
    """
    vues, sortie = set(), []
    for e in JournalAudit.objects.filter(utilisateur=user, action__in=("recherche_kpi", "requete_kpi"))[:60]:
        try:
            entree = _entree_recente(e.action, e.requete)
        except Exception:  # entrée d'audit inattendue : ignorée
            journal.warning("Entrée d'audit %s illisible pour « Mes dernières recherches »", e.pk, exc_info=True)
            continue
        if entree is None or entree[1] in vues:
            continue
        texte, cle, params = entree
        vues.add(cle)
        sortie.append({"texte": texte, "lien": "?" + urlencode(params, doseq=True), "date": e.date,
                       "ia": bool((e.requete or {}).get("ia")) if isinstance(e.requete, dict) else False})
        if len(sortie) >= nombre:
            break
    return sortie


def _message_validation(e: ValidationError) -> str:
    return "; ".join(err["msg"].removeprefix("Value error, ") for err in e.errors())


# ------------------------------------------------------------------ vues

@login_required
def requete(request):
    get = request.GET.copy()
    export = get.pop("export", [None])[0] == "xlsx"
    visibles = kpis_autorises(request.user, set(catalogue()))
    aujourdhui = timezone.localdate()
    q = get.get("q", "").strip()[:300]
    ia_ok = ia_disponible()
    ia = ia_ok and get.get("ia") == "1"
    explicites = parametres_explicites(get)
    ctx = {"q": q, "ia": ia, "ia_disponible": ia_ok}
    req, interp = None, None

    if "q" in get and (q or explicites):
        ctx["mode"] = "recherche"
        contexte = Contexte.pour(request.user)
        interp = (interpreter(q, aujourdhui, contexte, ia=ia) if q
                  else construire(Demande(), contexte, aujourdhui))
        interp = avec_parametres(interp, get, contexte, aujourdhui)
        ctx["interp"] = interp
        if get.get("ia") == "1":  # liens : requête résolue, sans nouvel appel IA
            get = _parametres_resolus(q, interp.params)
        ctx["form"] = RequeteForm(initial=champs_depuis_params(interp.params), kpis_visibles=visibles)
        ctx.update(_edition(get, interp, contexte))
        if interp.complete:
            try:
                req = RequeteKpi(**interp.params)
            except ValidationError as e:
                ctx["erreur"] = _message_validation(e)
    elif any(k in get for k in CHAMPS_FORMULAIRE):
        ctx["mode"] = "avance"
        ctx["avance_ouvert"] = True
        form = ctx["form"] = RequeteForm(get, kpis_visibles=visibles)
        if form.is_valid():
            try:
                req = RequeteKpi(**form.vers_requete())
            except ValidationError as e:
                ctx["erreur"] = _message_validation(e)
    else:
        ctx["mode"] = "accueil"
        ctx["form"] = RequeteForm(kpis_visibles=visibles)
        ctx["recentes"] = _recherches_recentes(request.user)
        ctx["exemples"] = _exemples(request.user, aujourdhui)

    if req is not None:
        if ctx["mode"] == "recherche":
            action = "export_excel" if export else "recherche_kpi"
            trace = {"q": q, "ia": ia, "source": interp.source, "parametres": explicites,
                     "requete": req.model_dump(mode="json")}
        else:
            action = "export_excel" if export else "requete_kpi"
            trace = req.model_dump(mode="json")
        JournalAudit.objects.create(utilisateur=request.user, action=action, requete=trace)
        try:
            resultat = executer(req, request.user, moteur_kpi())
        except (RequeteRefusee, BaseKpiNonConfiguree) as e:
            ctx["erreur"] = str(e)
        else:
            if export:
                reponse = HttpResponse(construire_excel(resultat), content_type=XLSX)
                nom = f"kpi_{req.periode.debut:%Y%m%d}_{req.periode.fin:%Y%m%d}.xlsx"
                reponse["Content-Disposition"] = f'attachment; filename="{nom}"'
                return reponse
            ctx["resultat"] = resultat
            ctx["requete"] = req
            puce = interp.puce("perimetre") if interp else None
            ctx["resume_lieu"] = puce.libelle if puce else (", ".join(req.perimetre.valeurs) or "tout le réseau autorisé")
            nombre = interp.demande.classement_nombre if interp and interp.demande else None
            ctx["blocs"] = affichage.blocs(resultat, nombre)
            ctx["lien_export"] = "?" + urlencode([*get.lists(), ("export", ["xlsx"])], doseq=True)
            ctx["requete_params"] = [(k, v if isinstance(v, list) else [v])
                                     for k, v in champs_depuis_requete(req).items()]  # rapport PowerPoint (POST)
            if est_demo() and voit_tout_le_reseau(request.user):  # incidents : noms de sites
                ctx["demo_infos"] = infos_demo()
    return render(request, "kpi/recherche.html", ctx)


@login_required
def suggestions(request):
    """Autocomplétion légère : lieux accessibles (communes, sites, événements) et exemples."""
    q = request.GET.get("q", "")[:100]
    lieux = Contexte.pour(request.user).lieux.suggestions(q, limite=15)
    exemples = [e for e in vocabulaire().exemples if not q or q.lower() in e.lower()]
    return JsonResponse({"lieux": lieux, "exemples": exemples})
