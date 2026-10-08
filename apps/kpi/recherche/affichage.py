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
NOMS_TECHNO = {"LTE": "4G · LTE", "WCDMA": "3G · WCDMA"}


def valeur(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _fr(nombre: float, decimales: int) -> str:
    texte = f"{nombre:,.{decimales}f}".replace(",", " ").replace(".", ",")
    return texte


def formater(v, unite: str) -> tuple[str, str]:
    """(valeur lisible, unité) : « 1,23 » « To », « 99,63 » « % », « 12 450 » « appels »."""
    v = valeur(v)
    if v is None:
        return "—", unite
    if unite == "Mo":
        for seuil, nom in ((1e6, "To"), (1e3, "Go")):
            if abs(v) >= seuil * 10:
                return _fr(v / seuil, 1 if v / seuil < 1000 else 0), nom
        return _fr(v, 0), unite
    if unite == "%":
        return _fr(v, 2), unite
    if unite in ("Mbps", "s"):
        return _fr(v, 2 if abs(v) < 10 else 1), unite
    if abs(v) >= 100 or float(v).is_integer():
        return _fr(v, 0), unite
    return _fr(v, 2), unite


def _court(libelle: str) -> str:
    """« Coupures E-RAB : perte radio du mobile » -> « Perte radio du mobile »."""
    if " : " in libelle:
        libelle = libelle.split(" : ", 1)[1]
    return libelle[:1].upper() + libelle[1:]


def cartes(res: ResultatTechno) -> list[dict]:
    sortie = []
    for k in res.kpis:
        if k.decomposition_de and any(p.code == k.decomposition_de for p in res.kpis):
            continue  # affichée dans la décomposition par cause
        v = valeur(res.synthese_globale.get(k.code))
        texte, unite = formater(v, k.unite)
        statut = k.statut(v)
        seuils = []
        if k.seuils.alerte is not None:
            seuils.append(f"alerte {formater(k.seuils.alerte, k.unite)[0]}")
        if k.seuils.critique is not None:
            seuils.append(f"critique {formater(k.seuils.critique, k.unite)[0]}")
        sortie.append({"kpi": k, "valeur": v, "texte": texte, "unite": unite,
                       "statut": statut or ("ok" if v is not None and k.seuils.alerte is not None else ""),
                       "seuils": " · ".join(seuils), "approx": k.qualite == "approx"})
    return sortie


def _pires(res: ResultatTechno, k, nombre: int) -> list:
    """Entités les plus dégradées pour ``k`` (les plus chargées pour un volume)."""
    serie = res.synthese[k.code].dropna() if res.synthese is not None and k.code in res.synthese else None
    if serie is None or serie.empty:
        return []
    return list(serie.sort_values(ascending=k.sens == "haut_est_mieux" and not k.additif).index[:nombre])


def graphiques(res: ResultatTechno, granularite_temps: str) -> dict:
    """Courbes par KPI (hors causes) : une série par entité ; au-delà de quelques entités,
    seules les plus dégradées (ou les plus chargées) sont tracées."""
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
        choisies = (_pires(res, k, SERIES_PIRES) or entites[:SERIES_PIRES]) if tronque else entites
        series = []
        for e in choisies:
            serie = table.xs(e, level="entite")[k.code].reindex(periodes)
            series.append({"nom": str(e), "valeurs": [None if (x := valeur(v)) is None else round(x, 4) for v in serie]})
        graphes.append({"code": k.code, "titre": k.libelle, "unite": k.unite, "seuils": k.seuils.model_dump(),
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
        # Causes négligeables (< 0,05 % des coupures) regroupées sur une ligne.
        negligeables = [b["libelle"] for b in barres if b["part"] < 0.05 and not b.get("non_ventile")]
        visibles = [b for b in barres if b["part"] >= 0.05 or b.get("non_ventile")]

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
                       "non_ventile": any(b.get("non_ventile") for b in barres),
                       "graphique": {"titre": parent.libelle, "unite": parent.unite, "axe": axe, "series": series,
                                     "barres": [{"libelle": b["libelle"], "valeur": round(b["valeur"], 4),
                                                 "part": round(b["part"], 1)} for b in barres],
                                     "par": "période" if granularite_espace == "global" else "entité"}})
    return sortie


def classement(res: ResultatTechno) -> list[dict]:
    """Entités les plus dégradées par KPI (ou les plus chargées pour un volume)."""
    if res.synthese is None or res.synthese.empty or len(res.synthese) < 2:
        return []
    sortie = []
    for k in res.kpis:
        if k.decomposition_de:
            continue
        serie = res.synthese[k.code].dropna()
        if serie.empty:
            continue
        croissant = k.sens == "haut_est_mieux" and not k.additif
        tri = serie.sort_values(ascending=croissant).head(CLASSEMENT_MAX)
        maximum = max(abs(serie).max(), 1e-12)
        lignes = []
        for entite, v in tri.items():
            lignes.append({"entite": entite, "valeur": v, "texte": " ".join(formater(v, k.unite)),
                           "statut": k.statut(valeur(v)), "largeur": round(100 * abs(v) / maximum, 1)})
        sortie.append({"kpi": k, "lignes": lignes, "total": len(serie),
                       "titre": "Les plus chargés" if k.additif else "Les plus dégradés"})
    return sortie


def lignes_table(res: ResultatTechno, granularite_temps: str) -> tuple[list[dict], bool]:
    lignes = []
    for i, ((periode, entite), valeurs) in enumerate(res.table.iterrows()):
        if i >= LIGNES_MAX:
            return lignes, True
        lignes.append({"periode": periode.strftime(FORMAT_PERIODE_TABLE[granularite_temps]), "entite": entite,
                       "valeurs": [{"valeur": (v := valeur(valeurs[k.code])), "statut": k.statut(v)}
                                   for k in res.kpis]})
    return lignes, False


def blocs(resultat: Resultat) -> list[dict]:
    req = resultat.requete
    sortie = []
    for res in resultat.par_techno:
        lignes, tronque = lignes_table(res, req.granularite_temps)
        sortie.append({
            "res": res,
            "nom": NOMS_TECHNO.get(res.techno, res.techno),
            "court": LIBELLES_TECHNO.get(res.techno, res.techno),
            "cartes": cartes(res),
            "graphiques": graphiques(res, req.granularite_temps),
            "id_graphiques": f"graphiques-{res.techno}",
            "causes": causes(res, req.granularite_temps, req.granularite_espace),
            "classement": classement(res) if req.granularite_espace != "global" else [],
            "lignes": lignes,
            "lignes_tronquees": tronque,
            "espace": req.granularite_espace,
        })
    return sortie
