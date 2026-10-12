"""Accueil : indicateurs réels du périmètre autorisé, sans données inventées."""

import logging
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy.exc import SQLAlchemyError

from .catalogue import catalogue
from .recherche.affichage import conversion, formater, valeur
from .requete import RequeteKpi
from .service import RequeteRefusee, executer
from .source import BaseKpiNonConfiguree, est_demo, infos_demo, moteur_kpi
from apps.comptes.acces import kpis_autorises

log = logging.getLogger(__name__)
INDICATEURS = [
    ("lte_payload_dl", "Volume data descendant", "Trafic 4G", "data"),
    ("lte_rrc_conn_max", "Utilisateurs connectés", "Pic simultané · 4G", "utilisateurs"),
    ("lte_dl_user_thp", "Débit descendant", "Débit moyen · 4G", "data"),
    ("lte_acces", "Taux d’accès", "Accessibilité · 4G", "qualite"),
]


def construire(user, aujourd_hui, selection="hier"):
    selection = selection if selection in ("hier", "aujourdhui", "7j") else "hier"
    fin = aujourd_hui if selection == "aujourdhui" else aujourd_hui - timedelta(days=1)
    derniere = infos_demo().get("fin") if est_demo() else None
    ancienne = bool(derniere and derniere < fin)
    if ancienne:
        fin = derniere
    debut = fin - timedelta(days=6) if selection == "7j" else fin
    ctx = {"selection": selection, "debut": debut, "fin": fin, "ancienne": ancienne,
           "partielle": selection == "aujourdhui" and not ancienne,
           "cartes": [], "graphiques": [], "avertissements": []}
    cat = catalogue()
    visibles = kpis_autorises(user, set(cat))
    indicateurs = [i for i in INDICATEURS if i[0] in visibles]
    # Autres KPI accessibles si le périmètre ne contient pas les indicateurs par défaut.
    if not indicateurs:
        indicateurs = [(c, cat[c].libelle, cat[c].techno, "qualite") for c in sorted(visibles)[:4]]
    if not indicateurs:
        ctx["message"] = "Aucun indicateur accessible dans votre périmètre. Contactez votre administrateur."
        return ctx
    req = RequeteKpi(techno=list(dict.fromkeys(cat[i[0]].techno for i in indicateurs)),
                     perimetre={"type": "global"}, periode={"debut": debut, "fin": fin},
                     granularite_temps="jour" if selection == "7j" else "heure",
                     kpis=[i[0] for i in indicateurs])
    try:
        resultat = executer(req, user, moteur_kpi())
    except (BaseKpiNonConfiguree, RequeteRefusee, SQLAlchemyError):
        log.warning("Tableau de bord : source KPI indisponible", exc_info=True)
        ctx["message"] = "Les indicateurs sont momentanément indisponibles. Vous pouvez toujours préparer un rapport."
        return ctx
    ctx["avertissements"] = resultat.avertissements
    par_techno = {r.techno: r for r in resultat.par_techno}
    for code, titre, detail, icone in indicateurs:
        res = par_techno.get(cat[code].techno)
        if res is None:
            continue
        k = cat[code]
        v = valeur(res.synthese_globale.get(code))
        texte, unite = formater(v, k.unite)
        lien = "?" + urlencode({"q": "", "kpis": code, "techno": k.techno,
                               "debut": debut.isoformat(), "fin": fin.isoformat(),
                               "granularite_temps": req.granularite_temps})
        ctx["cartes"].append({"titre": titre, "detail": detail, "icone": icone,
                              "texte": texte, "unite": unite, "statut": k.statut(v),
                              "approx": k.qualite == "approx", "note": k.note, "lien": lien})
        if not res.table.empty:
            # La requête impose le regroupement global : une seule entité autorisée.
            serie = res.table.droplevel("entite")
            diviseur, unite_graphe = conversion(k.unite, v)
            ctx["graphiques"].append({"code": code, "titre": titre, "unite": unite_graphe,
                "periodes": [p.strftime("%d/%m" if selection == "7j" else "%H:%M") for p in serie.index],
                "valeurs": [None if valeur(n) is None else float(n) / diviseur for n in serie[code]],
                "lien": lien})
    if not ctx["cartes"]:
        ctx["message"] = "Aucune cellule accessible dans votre périmètre. Contactez votre administrateur."
    return ctx
