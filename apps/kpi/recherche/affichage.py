"""Mise en forme d'un résultat pour l'écran : cartes KPI, courbes, causes, classement."""

import math

from ..service import Resultat, ResultatTechno
from .vocabulaire import LIBELLES_TECHNO

FORMAT_PERIODE = {"heure": "%d/%m %Hh", "jour": "%d/%m", "semaine": "sem. %d/%m", "mois": "%m/%Y"}
FORMAT_PERIODE_TABLE = {"heure": "%d/%m/%Y %Hh", "jour": "%d/%m/%Y", "semaine": "sem. du %d/%m/%Y", "mois": "%m/%Y"}
SERIES_MAX = 12  # barres empilées par entité
SERIES_PIRES = 6  # courbes : entités les plus dégradées
CLASSEMENT_MAX = 10
LIGNES_MAX = 2000
# Cause négligeable : moins de 0,1 % des coupures (même seuil dans le texte affiché).
PART_NEGLIGEABLE = 0.1
NOMS_TECHNO = {"LTE": "4G · LTE", "WCDMA": "3G · WCDMA"}
ESPACE_FINE = " "  # séparateur de milliers (espace fine insécable)


def valeur(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _fr(nombre: float, decimales: int) -> str:
    return f"{nombre:,.{decimales}f}".replace(",", ESPACE_FINE).replace(".", ",")


def conversion(unite: str, reference) -> tuple[float, str]:
    """(diviseur, unité affichée) : les volumes en Mo passent en Go / To selon la valeur de
    référence. Appliquée à l'identique à la carte, aux courbes et au classement d'un KPI."""
    reference = valeur(reference)
    if unite == "Mo" and reference is not None:
        for seuil, nom in ((1e6, "To"), (1e3, "Go")):
            if abs(reference) >= seuil * 10:
                return seuil, nom
    return 1.0, unite


def formater(v, unite: str, diviseur: float | None = None) -> tuple[str, str]:
    """(valeur lisible, unité) : « 1,2 » « To », « 99,63 » « % », « 12 450 » « appels »."""
    v = valeur(v)
    if v is None:
        return "—", unite
    if diviseur is None:
        diviseur, affichee = conversion(unite, v)
    else:
        affichee = conversion(unite, diviseur * 10)[1] if diviseur != 1 else unite
    v = v / diviseur
    if affichee in ("Go", "To"):
        return _fr(v, 1 if abs(v) < 1000 else 0), affichee
    if unite == "%":
        return _fr(v, 2), affichee
    if unite in ("Mbps", "s"):
        return _fr(v, 2 if abs(v) < 10 else 1), affichee
    if abs(v) >= 100 or float(v).is_integer():
        return _fr(v, 0), affichee
    return _fr(v, 2), affichee


def _court(libelle: str) -> str:
    """« Coupures E-RAB : perte radio du mobile » -> « Perte radio du mobile »."""
    if " : " in libelle:
        libelle = libelle.split(" : ", 1)[1]
    return libelle[:1].upper() + libelle[1:]


def conversions(res: ResultatTechno) -> dict[str, tuple[float, str]]:
    return {k.code: conversion(k.unite, res.synthese_globale.get(k.code)) for k in res.kpis}


def _taille(texte: str) -> str:
    """Classe de taille de la grande valeur d'une carte (les grands nombres sont réduits)."""
    if len(texte) > 12:
        return "tres-longue"
    return "longue" if len(texte) > 8 else ""


def cartes(res: ResultatTechno, conv=None) -> list[dict]:
    conv = conv or conversions(res)
    sortie = []
    for k in res.kpis:
        if k.decomposition_de and any(p.code == k.decomposition_de for p in res.kpis):
            continue  # affichée dans la décomposition par cause
        v = valeur(res.synthese_globale.get(k.code))
        texte, unite = formater(v, k.unite, conv[k.code][0])
        statut = k.statut(v)
        seuils = []
        if k.seuils.alerte is not None:
            seuils.append(f"alerte {formater(k.seuils.alerte, k.unite)[0]}")
        if k.seuils.critique is not None:
            seuils.append(f"critique {formater(k.seuils.critique, k.unite)[0]}")
        sortie.append({"kpi": k, "valeur": v, "texte": texte, "unite": unite, "taille": _taille(texte),
                       "statut": statut or ("ok" if v is not None and k.seuils.alerte is not None else ""),
                       "seuils": " · ".join(seuils), "approx": k.qualite == "approx"})
    return sortie


def _qualite(k) -> bool:
    """KPI de qualité (pas un volume, un nombre d'appels ou une durée) : classable en « dégradé »."""
    return k.categorie != "trafic"


def _pires(res: ResultatTechno, k, nombre: int) -> list:
    """Entités les plus dégradées pour ``k`` (les plus chargées pour un volume)."""
    serie = res.synthese[k.code].dropna() if res.synthese is not None and k.code in res.synthese else None
    if serie is None or serie.empty:
        return []
    return list(serie.sort_values(ascending=k.sens == "haut_est_mieux" and _qualite(k)).index[:nombre])


def graphiques(res: ResultatTechno, granularite_temps: str, conv=None) -> dict:
    """Courbes par KPI (hors causes) : une série par entité ; au-delà de quelques entités,
    seules les plus dégradées (ou les plus chargées) sont tracées. Même unité que la carte."""
    conv = conv or conversions(res)
    table = res.table
    if table.empty:
        return {"periodes": [], "kpis": [], "tronque": False}
    periodes = sorted(table.index.get_level_values("periode").unique())
    entites = list(dict.fromkeys(table.index.get_level_values("entite")))
    tronque = len(entites) > SERIES_PIRES
    graphes = []
    for k in res.kpis:
        if k.decomposition_de:
            continue
        diviseur, unite = conv[k.code]
        choisies = (_pires(res, k, SERIES_PIRES) or entites[:SERIES_PIRES]) if tronque else entites
        series = []
        for e in choisies:
            serie = table.xs(e, level="entite")[k.code].reindex(periodes)
            series.append({"nom": str(e),
                           "valeurs": [None if (x := valeur(v)) is None else round(x / diviseur, 6) for v in serie]})
        graphes.append({"code": k.code, "titre": k.libelle, "unite": unite, "seuils": k.seuils.model_dump(),
                        "zero": k.additif or k.sens == "bas_est_mieux", "series": series})
    format_periode = FORMAT_PERIODE[granularite_temps]
    if granularite_temps == "heure" and len({p.date() for p in periodes}) == 1:
        format_periode = "%Hh"
    return {"periodes": [p.strftime(format_periode) for p in periodes], "kpis": graphes, "tronque": tronque,
            "nombre": SERIES_PIRES}


def causes(res: ResultatTechno, granularite_temps: str, granularite_espace: str) -> list[dict]:
    """Décomposition par cause de chaque KPI parent demandé avec ses causes.

    Les causes ont la même pondération que le parent : elles s'additionnent. Le reste
    (parent − Σ causes), s'il est positif, est affiché « Non ventilé ».
    """
    sortie = []
    for parent in res.kpis:
        liste = [k for k in res.kpis if k.decomposition_de == parent.code]
        if not liste:
            continue
        total = valeur(res.synthese_globale.get(parent.code))
        if total is None:
            continue
        barres = [{"libelle": _court(k.libelle), "valeur": valeur(res.synthese_globale.get(k.code)) or 0.0}
                  for k in liste]
        reste = total - sum(b["valeur"] for b in barres)
        if reste > max(1e-9, 1e-6 * abs(total)):
            barres.append({"libelle": "Non ventilé", "valeur": reste, "non_ventile": True})
        barres.sort(key=lambda b: b["valeur"], reverse=True)
        for b in barres:
            b["part"] = 100 * b["valeur"] / total if total else 0.0
            b["texte"] = formater(b["valeur"], parent.unite)[0]
        negligeables = [b["libelle"] for b in barres if b["part"] < PART_NEGLIGEABLE and not b.get("non_ventile")]
        visibles = [b for b in barres if b["part"] >= PART_NEGLIGEABLE or b.get("non_ventile")]

        # Barres empilées : par période (vue globale) ou par entité (autres niveaux).
        if granularite_espace == "global":
            table = res.table.droplevel("entite") if not res.table.empty else res.table
            axe = [p.strftime(FORMAT_PERIODE[granularite_temps]) for p in table.index]
        else:
            table = res.synthese.sort_values(parent.code, ascending=False).head(SERIES_MAX)
            axe = [str(e) for e in table.index]
        series = [{"nom": _court(k.libelle), "valeurs": [round(valeur(v) or 0.0, 4) for v in table[k.code]]}
                  for k in liste]
        if any(b.get("non_ventile") for b in barres):
            restes = []
            for _, ligne in table.iterrows():
                t = valeur(ligne[parent.code])
                restes.append(None if t is None else round(max(t - sum(valeur(ligne[k.code]) or 0 for k in liste), 0), 4))
            series.append({"nom": "Non ventilé", "valeurs": restes})
        sortie.append({"parent": parent, "total": total, "total_texte": formater(total, parent.unite)[0],
                       "barres": visibles, "negligeables": negligeables, "id": f"causes-{res.techno}-{parent.code}",
                       "seuil_negligeable": _fr(PART_NEGLIGEABLE, 1),
                       "non_ventile": any(b.get("non_ventile") for b in barres),
                       "graphique": {"titre": parent.libelle, "unite": parent.unite, "axe": axe, "series": series,
                                     "barres": [{"libelle": b["libelle"], "valeur": round(b["valeur"], 4),
                                                 "part": round(b["part"], 1)} for b in barres],
                                     "par": "période" if granularite_espace == "global" else "entité"}})
    return sortie


def classement(res: ResultatTechno, conv=None) -> list[dict]:
    """Entités les plus dégradées, pour les KPI de qualité seulement (pas les volumes,
    nombres d'appels ou durées, qui ne se « dégradent » pas)."""
    if res.synthese is None or res.synthese.empty or len(res.synthese) < 2:
        return []
    conv = conv or conversions(res)
    sortie = []
    for k in res.kpis:
        if k.decomposition_de or not _qualite(k):
            continue
        serie = res.synthese[k.code].dropna()
        if serie.empty:
            continue
        tri = serie.sort_values(ascending=k.sens == "haut_est_mieux").head(CLASSEMENT_MAX)
        maximum = max(abs(serie).max(), 1e-12)
        diviseur = conv[k.code][0]
        lignes = []
        for entite, v in tri.items():
            lignes.append({"entite": entite, "valeur": v, "texte": ESPACE_FINE.join(formater(v, k.unite, diviseur)),
                           "statut": k.statut(valeur(v)), "largeur": round(100 * abs(v) / maximum, 1)})
        sortie.append({"kpi": k, "lignes": lignes, "total": len(serie), "titre": "Les plus dégradés"})
    return sortie


def lignes_table(res: ResultatTechno, granularite_temps: str) -> tuple[list[dict], int]:
    """Lignes du tableau détaillé (``LIGNES_MAX`` au plus) et nombre total de lignes."""
    lignes = []
    for i, ((periode, entite), valeurs) in enumerate(res.table.iterrows()):
        if i >= LIGNES_MAX:
            break
        lignes.append({"periode": periode.strftime(FORMAT_PERIODE_TABLE[granularite_temps]), "entite": entite,
                       "valeurs": [{"valeur": (v := valeur(valeurs[k.code])), "statut": k.statut(v)}
                                   for k in res.kpis]})
    return lignes, len(res.table)


def blocs(resultat: Resultat) -> list[dict]:
    req = resultat.requete
    sortie = []
    for res in resultat.par_techno:
        conv = conversions(res)
        lignes, total = lignes_table(res, req.granularite_temps)
        sortie.append({
            "res": res,
            "nom": NOMS_TECHNO.get(res.techno, res.techno),
            "court": LIBELLES_TECHNO.get(res.techno, res.techno),
            "cartes": cartes(res, conv),
            "graphiques": graphiques(res, req.granularite_temps, conv),
            "id_graphiques": f"graphiques-{res.techno}",
            "causes": causes(res, req.granularite_temps, req.granularite_espace),
            "classement": classement(res, conv) if req.granularite_espace != "global" else [],
            "lignes": lignes,
            "lignes_total": total,
            "lignes_tronquees": total > len(lignes),
            "lignes_total_texte": _fr(total, 0),
            "lignes_texte": _fr(len(lignes), 0),
            "espace": req.granularite_espace,
        })
    return sortie
