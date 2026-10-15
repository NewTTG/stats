"""Accueil : indicateurs réels du périmètre autorisé, sans données inventées."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlencode

from psycopg.errors import ConnectionTimeout
from sqlalchemy.exc import SQLAlchemyError

from .catalogue import catalogue
from .forms import champs_depuis_requete
from .recherche.affichage import conversion, formater, valeur
from .requete import RequeteKpi
from .service import RequeteRefusee, completer, preparer as preparer_requete
from .source import (
    MESSAGE_BASE_INDISPONIBLE, BaseKpiNonConfiguree, dernieres_heures, est_demo,
    infos_demo, moteur_kpi,
)
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


def preparer(aujourd_hui, selection="24h"):
    """Contexte léger : aucune lecture des tables KPI pour ouvrir la page."""
    selection = selection if selection in ("24h", "hier", "aujourdhui", "7j") else "24h"
    fin = aujourd_hui if selection == "aujourdhui" else aujourd_hui - timedelta(days=1)
    derniere = infos_demo().get("fin") if selection != "24h" and est_demo() else None
    ancienne = bool(derniere and derniere < fin)
    if ancienne:
        fin = derniere
    debut = fin - timedelta(days=6) if selection == "7j" else fin
    return {"selection": selection, "debut": debut, "fin": fin, "ancienne": ancienne,
           "partielle": selection == "aujourdhui" and not ancienne,
           "cartes": [], "graphiques": [], "avertissements": [], "periodes": []}


def _delai_depasse(exc) -> bool:
    return isinstance(getattr(exc, "orig", None), ConnectionTimeout)


def _lancer(lots, parallele):
    """(sorties, None) ou (None, erreur SQL) pour chaque lot de calculs, dans l'ordre.

    En parallèle, chaque lot a son fil et sa connexion du pool : un serveur injoignable
    fait attendre un seul délai de connexion, pas un par techno. Séquentiellement (SQLite :
    fichier local de démonstration, ou base en mémoire à connexion unique), les lots
    restants ne sont pas tentés après un délai de connexion dépassé.
    """
    def lancer(calculs):
        try:
            return [calcul() for calcul in calculs], None
        except SQLAlchemyError as exc:
            return None, exc

    if parallele and len(lots) > 1:
        with ThreadPoolExecutor(max_workers=len(lots)) as pool:
            return list(pool.map(lancer, lots))
    sorties = []
    for calculs in lots:
        if sorties and sorties[-1][1] is not None and _delai_depasse(sorties[-1][1]):
            sorties.append(sorties[-1])
        else:
            sorties.append(lancer(calculs))
    return sorties


def construire(user, aujourd_hui, selection="24h"):
    ctx = preparer(aujourd_hui, selection)
    selection, debut, fin = ctx["selection"], ctx["debut"], ctx["fin"]
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
    par_techno, requetes, preparees, delai = {}, {}, [], False
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
            resultat, calculs = preparer_requete(req, user, engine)
        except (RequeteRefusee, SQLAlchemyError) as exc:
            if _delai_depasse(exc):  # technos suivantes non tentées : un seul délai d'attente
                delai = True
                break
            log.warning("Tableau de bord : source %s indisponible", techno, exc_info=True)
            ctx["avertissements"].append(f"{techno} : les indicateurs sont momentanément indisponibles.")
            continue
        preparees.append((techno, req, heures, resultat, calculs))

    # Lectures LTE et WCDMA simultanées : la page attend la plus longue, pas leur somme.
    sorties = _lancer([calculs for *_, calculs in preparees], parallele=engine.dialect.name == "postgresql")
    for (techno, req, heures, resultat, _), (sortie, exc) in zip(preparees, sorties):
        if exc is not None:
            if _delai_depasse(exc):
                delai = True
            else:
                log.warning("Tableau de bord : source %s indisponible", techno, exc_info=exc)
                ctx["avertissements"].append(f"{techno} : les indicateurs sont momentanément indisponibles.")
            continue
        for s in sortie:
            completer(resultat, s)
        ctx["avertissements"].extend(resultat.avertissements)
        par_techno.update((r.techno, r) for r in resultat.par_techno)
        requetes[techno] = req
        if heures:
            ctx["periodes"].append({"techno": "4G" if techno == "LTE" else "3G",
                                    "debut": heures[0], "fin": heures[-1], "nombre": len(heures)})
    if delai:
        log.warning("Tableau de bord : délai de connexion à la base KPI dépassé. "
                    "Vérifier KPI_DB_HOST/KPI_DB_PORT, le réseau/VPN et PostgreSQL.")
        if par_techno:
            ctx["avertissements"].append(MESSAGE_BASE_INDISPONIBLE)
        else:
            ctx["message"] = MESSAGE_BASE_INDISPONIBLE
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
        ctx.setdefault("message", "Aucune donnée accessible pour cette période. Vous pouvez toujours préparer un rapport.")
    return ctx
