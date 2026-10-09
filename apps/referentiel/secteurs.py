"""Secteur d'une cellule à une date donnée.

Un site passé de 3 à 4 secteurs (``Site.bascule_4_secteurs``) change le secteur de
quelques cellules (D, e4…) : avant la bascule, elles comptent dans ``secteur_avant``.
"""

from datetime import date

import pandas as pd

from .models import Cellule


def _lignes(techno: str):
    return Cellule.objects.filter(techno=techno).values_list(
        "nom", "secteur__code", "secteur_avant__code", "secteur__site__bascule_4_secteurs")


def secteurs_a_la_date(techno: str, jour: date | None = None) -> dict[str, str | None]:
    """Cellule -> code du secteur le ``jour`` donné (None : disposition actuelle)."""
    return {nom: avant if avant and bascule and jour and jour < bascule else code
            for nom, code, avant, bascule in _lignes(techno)}


def secteur_par_ligne(df: pd.DataFrame, techno: str) -> pd.Series:
    """Code du secteur de chaque ligne (``cellule``, ``horodatage``) d'une lecture KPI."""
    actuels, avants, bascules = {}, {}, {}
    for nom, code, avant, bascule in _lignes(techno):
        actuels[nom] = code
        if avant and bascule:
            avants[nom], bascules[nom] = avant, pd.Timestamp(bascule)
    codes = df["cellule"].map(actuels)
    if avants and len(df):
        avant_bascule = df["horodatage"] < pd.to_datetime(df["cellule"].map(bascules))
        codes = codes.mask(avant_bascule, df["cellule"].map(avants))
    return codes


def cellules_des_secteurs(techno: str, codes: list[str], debut: date, fin: date) -> list[str]:
    """Cellules ayant appartenu à l'un des secteurs ``codes`` entre ``debut`` et ``fin``."""
    codes = set(codes)
    resultat = set()
    for nom, code, avant, bascule in _lignes(techno):
        if code in codes and (not (avant and bascule) or fin >= bascule):
            resultat.add(nom)
        if avant in codes and bascule and debut < bascule:
            resultat.add(nom)
    return sorted(resultat)
