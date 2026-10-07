"""Règles de détection d'anomalies (brief §6) : fonctions isolées, sans accès base.

Chaque règle reçoit des valeurs déjà agrégées (ratio de sommes) et renvoie des
``Anomalie``. Les seuils viennent du catalogue et de ``ReglagesAnomalies``.
"""

import math
from dataclasses import dataclass
from statistics import mean, stdev

import pandas as pd

from apps.kpi.catalogue import DefinitionKpi

ORDRE_GRAVITE = {"critique": 0, "alerte": 1}


@dataclass
class Anomalie:
    gravite: str  # « critique » ou « alerte »
    regle: str  # seuil, ecart, sans_donnees, saturation
    techno: str
    entite: str
    message: str
    kpi: DefinitionKpi | None = None
    valeur: float | None = None
    reference: float | None = None

    @property
    def ecart_pct(self) -> float | None:
        return ecart_pct(self.valeur, self.reference)

    def cle_tri(self):
        ecart = abs(self.ecart_pct) if self.ecart_pct is not None else 0
        return (ORDRE_GRAVITE[self.gravite], -ecart, self.techno, self.entite)


def _nombre(v) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def ecart_pct(valeur, reference) -> float | None:
    valeur, reference = _nombre(valeur), _nombre(reference)
    if valeur is None or reference is None or reference == 0:
        return None
    return (valeur - reference) / abs(reference) * 100


def _degradation(kpi: DefinitionKpi, valeur: float, reference: float) -> bool:
    return valeur < reference if kpi.sens == "haut_est_mieux" else valeur > reference


def ecart_significatif(kpi: DefinitionKpi, valeur, reference, hebdo: list, sigma: float, pct: float) -> bool:
    """Dégradation par rapport à la référence : plus de ``pct`` % ET plus de ``sigma`` écarts-types.

    ``hebdo`` : valeurs de chaque semaine de référence. Avec moins de deux semaines
    (ou des semaines identiques), seul le critère en % s'applique.
    """
    valeur, reference = _nombre(valeur), _nombre(reference)
    if valeur is None or reference is None or not _degradation(kpi, valeur, reference):
        return False
    ecart = ecart_pct(valeur, reference)
    if ecart is None or abs(ecart) < pct:
        return False
    semaines = [v for v in map(_nombre, hebdo) if v is not None]
    if len(semaines) < 2 or stdev(semaines) == 0:
        return True
    return abs(valeur - mean(semaines)) > sigma * stdev(semaines)


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def anomalies_seuils(techno: str, valeurs: pd.DataFrame, kpis: list[DefinitionKpi]) -> list[Anomalie]:
    """Dépassement du seuil absolu du catalogue. ``valeurs`` : index entité, une colonne par KPI."""
    res = []
    for entite, ligne in valeurs.iterrows():
        for k in kpis:
            v = _nombre(ligne.get(k.code))
            statut = k.statut(v)
            if statut:
                seuil = k.seuils.critique if statut == "critique" else k.seuils.alerte
                res.append(Anomalie(statut, "seuil", techno, str(entite),
                                    f"{k.libelle} {_fmt(v)} {k.unite} (seuil {statut} {_fmt(seuil)})", k, v))
    return res


def anomalies_ecarts(techno: str, valeurs: pd.DataFrame, references: pd.DataFrame, hebdo: pd.DataFrame,
                     kpis: list[DefinitionKpi], sigma: float, pct: float) -> list[Anomalie]:
    """Écart significatif à la référence, par entité.

    ``valeurs`` / ``references`` : index entité ; ``hebdo`` : index (entité, semaine).
    Un écart de plus du double du seuil en % est critique.
    """
    res = []
    for entite, ligne in valeurs.iterrows():
        if entite not in references.index:
            continue
        semaines = hebdo.xs(entite, level=0) if entite in hebdo.index.get_level_values(0) else hebdo.iloc[0:0]
        for k in kpis:
            v, ref = ligne.get(k.code), references.at[entite, k.code]
            if ecart_significatif(k, v, ref, list(semaines[k.code]) if k.code in semaines else [], sigma, pct):
                e = ecart_pct(v, ref)
                gravite = "critique" if abs(e) >= 2 * pct else "alerte"
                res.append(Anomalie(gravite, "ecart", techno, str(entite),
                                    f"{k.libelle} {_fmt(v)} {k.unite} contre {_fmt(ref)} {k.unite} en référence ({e:+.0f} %)",
                                    k, _nombre(v), _nombre(ref)))
    return res


def anomalies_sans_donnees(techno: str, entites: dict[str, str], presence: set[tuple[str, int]],
                           nb_creneaux: int) -> list[Anomalie]:
    """Cellule sans aucune ligne sur un créneau. ``presence`` : couples (cellule, n° de créneau).

    Critique si la cellule n'a de données sur aucun créneau, alerte sinon.
    """
    res = []
    for cellule, entite in sorted(entites.items()):
        manquants = [i for i in range(nb_creneaux) if (cellule, i) not in presence]
        if not manquants:
            continue
        if len(manquants) == nb_creneaux:
            res.append(Anomalie("critique", "sans_donnees", techno, entite,
                                f"Cellule {cellule} : aucune donnée pendant l'événement"))
        else:
            liste = ", ".join(str(i + 1) for i in manquants)
            res.append(Anomalie("alerte", "sans_donnees", techno, entite,
                                f"Cellule {cellule} : pas de données sur le(s) créneau(x) {liste}"))
    return res


def anomalies_saturation(techno: str, horaire: pd.DataFrame, entites: dict[str, str], prb: str, debit: str,
                         seuil_prb: float, seuil_debit: float) -> list[Anomalie]:
    """Heures où la PRB DL dépasse ``seuil_prb`` alors que le débit DL est sous ``seuil_debit``.

    ``horaire`` : colonnes ``cellule``, ``instant``, ``prb``, ``debit`` (valeurs par cellule-heure).
    Critique si la moitié au moins des heures mesurées de la cellule sont saturées.
    """
    res = []
    for cellule, lignes in horaire.groupby("cellule", sort=True):
        mesurees = lignes[[prb, debit]].notna().all(axis=1)
        saturees = mesurees & (lignes[prb] > seuil_prb) & (lignes[debit] < seuil_debit)
        n = int(saturees.sum())
        if not n:
            continue
        gravite = "critique" if n * 2 >= int(mesurees.sum()) else "alerte"
        res.append(Anomalie(gravite, "saturation", techno, entites.get(cellule, cellule),
                            f"Cellule {cellule} : {n} h saturée(s) (PRB DL > {_fmt(seuil_prb)} % "
                            f"et débit DL < {_fmt(seuil_debit)} Mbps)"))
    return res


def classement(anomalies: list[Anomalie], limite: int = 10) -> list[dict]:
    """Entités les plus dégradées : 3 points par anomalie critique, 1 par alerte."""
    par_entite: dict[tuple[str, str], dict] = {}
    for a in anomalies:
        e = par_entite.setdefault((a.techno, a.entite), {"techno": a.techno, "entite": a.entite,
                                                         "critiques": 0, "alertes": 0, "kpis": set()})
        e["critiques" if a.gravite == "critique" else "alertes"] += 1
        e["kpis"].add(a.kpi.libelle if a.kpi else {"sans_donnees": "Données absentes",
                                                   "saturation": "Saturation"}.get(a.regle, a.regle))
    lignes = [{**e, "score": 3 * e["critiques"] + e["alertes"], "kpis": sorted(e["kpis"])}
              for e in par_entite.values()]
    return sorted(lignes, key=lambda e: (-e["score"], e["techno"], e["entite"]))[:limite]
