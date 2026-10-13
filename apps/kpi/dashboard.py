"""Accueil : indicateurs réels du périmètre autorisé, sans données inventées."""

import logging
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy.exc import SQLAlchemyError

from .catalogue import catalogue
from .forms import champs_depuis_requete
from .recherche.affichage import conversion, formater, valeur
from .requete import RequeteKpi
from .service import RequeteRefusee, executer
from .source import BaseKpiNonConfiguree, dernieres_heures, est_demo, infos_demo, moteur_kpi
from apps.comptes.acces import cellules_autorisees, kpis_autorises

log = logging.getLogger(__name__)
INDICATEURS = [
    ("lte_payload_dl", "Volume data descendant", "Trafic 4G", "data"),
    ("lte_rrc_conn_max", "Utilisateurs connectés", "Pic simultané · 4G", "utilisateurs"),
    ("lte_dl_user_thp", "Débit descendant", "Débit moyen · 4G", "data"),
    ("lte_acces", "Taux d’accès", "Accessibilité · 4G", "qualite"),
    ("wcdma_payload_hs", "Volume data descendant", "Trafic data · 3G", "data"),
    ("wcdma_speech_traffic", "Trafic voix", "Appels voix · 3G", "utilisateurs"),
    ("wcdma_hs_user_thp", "Débit descendant", "Débit moyen · 3G", "data"),
    ("wcdma_cssr_cs", "Taux d’accès voix", "Accessibilité · 3G", "qualite"),
]


def construire(user, aujourd_hui, selection="24h"):
    selection = selection if selection in ("24h", "hier", "aujourdhui", "7j") else "24h"
    fin = aujourd_hui if selection == "aujourdhui" else aujourd_hui - timedelta(days=1)
    derniere = infos_demo().get("fin") if selection != "24h" and est_demo() else None
    ancienne = bool(derniere and derniere < fin)
    if ancienne:
        fin = derniere
    debut = fin - timedelta(days=6) if selection == "7j" else fin
    ctx = {"selection": selection, "debut": debut, "fin": fin, "ancienne": ancienne,
           "partielle": selection == "aujourdhui" and not ancienne,
           "cartes": [], "graphiques": [], "avertissements": [], "periodes": []}
    cat = catalogue()
    visibles = kpis_autorises(user, set(cat))
    indicateurs = [i for i in INDICATEURS if i[0] in visibles]
    # Autres KPI accessibles si le périmètre ne contient pas les indicateurs par défaut.
    if not indicateurs:
        indicateurs = [(c, cat[c].libelle, cat[c].techno, "qualite") for c in sorted(visibles)[:4]]
    if not indicateurs:
        ctx["message"] = "Aucun indicateur accessible dans votre périmètre. Contactez votre administrateur."
        return ctx
    try:
        engine = moteur_kpi()
    except (BaseKpiNonConfiguree, SQLAlchemyError):
        log.warning("Tableau de bord : source KPI indisponible", exc_info=True)
        ctx["message"] = "Les indicateurs sont momentanément indisponibles. Vous pouvez toujours préparer un rapport."
        return ctx
    par_techno, requetes = {}, {}
    for techno in dict.fromkeys(cat[i[0]].techno for i in indicateurs):
        try:
            heures = []
            debut_techno, fin_techno = debut, fin
            if selection == "24h":
                cellules = cellules_autorisees(user, techno)
                heures = dernieres_heures(engine, techno, sorted(cellules) if cellules is not None else None)
                if not heures:
                    ctx["avertissements"].append(f"{techno} : aucune donnée horaire accessible en base.")
                    continue
                debut_techno, fin_techno = heures[0].date(), heures[-1].date()
            req = RequeteKpi(techno=[techno], perimetre={"type": "global"},
                             periode={"debut": debut_techno, "fin": fin_techno}, heures=heures,
                             granularite_temps="jour" if selection == "7j" else "heure",
                             kpis=[i[0] for i in indicateurs if cat[i[0]].techno == techno])
            resultat = executer(req, user, engine)
        except (RequeteRefusee, SQLAlchemyError):
            log.warning("Tableau de bord : source %s indisponible", techno, exc_info=True)
            ctx["avertissements"].append(f"{techno} : les indicateurs sont momentanément indisponibles.")
            continue
        ctx["avertissements"].extend(resultat.avertissements)
        par_techno.update((r.techno, r) for r in resultat.par_techno)
        requetes[techno] = req
        if heures:
            ctx["periodes"].append({"techno": "4G" if techno == "LTE" else "3G",
                                    "debut": heures[0], "fin": heures[-1], "nombre": len(heures)})
    if ctx["periodes"]:
        ctx["debut"] = min(p["debut"].date() for p in ctx["periodes"])
        ctx["fin"] = max(p["fin"].date() for p in ctx["periodes"])
    for code, titre, detail, icone in indicateurs:
        res = par_techno.get(cat[code].techno)
        if res is None:
            continue
        k = cat[code]
        v = valeur(res.synthese_globale.get(code))
        texte, unite = formater(v, k.unite)
        req = requetes[k.techno].model_copy(update={"kpis": [code]})
        lien = "?" + urlencode(champs_depuis_requete(req), doseq=True)
        ctx["cartes"].append({"titre": titre, "detail": detail, "icone": icone,
                              "texte": texte, "unite": unite, "statut": k.statut(v),
                              "approx": k.qualite == "approx", "note": k.note, "lien": lien})
        if not res.table.empty:
            # La requête impose le regroupement global : une seule entité autorisée.
            serie = res.table.droplevel("entite")
            diviseur, unite_graphe = conversion(k.unite, v)
            ctx["graphiques"].append({"code": code, "titre": titre, "unite": unite_graphe,
                "techno": "4G" if k.techno == "LTE" else "3G",
                "periodes": [p.strftime("%d/%m" if selection == "7j" else
                                        "%d/%m %H:%M" if selection == "24h" else "%H:%M") for p in serie.index],
                "periodes_cles": [p.isoformat() for p in serie.index],
                "valeurs": [None if valeur(n) is None else float(n) / diviseur for n in serie[code]],
                "lien": lien})
    if not ctx["cartes"]:
        ctx["message"] = "Aucune donnée accessible pour cette période. Vous pouvez toujours préparer un rapport."
    return ctx
