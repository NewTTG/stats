"""Moteur de calcul : agrégation en ratio de sommes (brief §4).

Chaque KPI est ramené à un couple (numérateur, dénominateur) par ligne source ;
on somme sur le temps et l'espace, puis on divise. Jamais de moyenne de ratios.
"""

import numpy as np
import pandas as pd

from .catalogue import DefinitionKpi


def _num(col: str) -> str:
    return f"{col}__num"


def _den(col: str) -> str:
    return f"{col}__den"


def _evaluer(df: pd.DataFrame, expression: str) -> pd.Series:
    """Évalue une expression du catalogue ; une division par zéro donne NaN, pas inf."""
    valeur = df.eval(expression)
    if np.isscalar(valeur):
        valeur = pd.Series(valeur, index=df.index)
    return valeur.astype(float).replace([np.inf, -np.inf], np.nan)


def composantes(df: pd.DataFrame, kpis: list[DefinitionKpi]) -> pd.DataFrame:
    """Ajoute les colonnes numérateur / dénominateur de chaque KPI.

    Une ligne dont une composante n'est pas calculable (donnée absente) reste NaN :
    elle est exclue des sommes, ce qui distingue « pas de données » de « valeur nulle ».
    """
    sortie = pd.DataFrame(index=df.index)
    for k in kpis:
        num = _evaluer(df, k.numerateur)
        if k.denominateur is None:
            sortie[_num(k.code)] = num
            sortie[_den(k.code)] = np.where(num.isna(), np.nan, 1.0)
            continue
        den = _evaluer(df, k.denominateur)
        valide = num.notna() & den.notna()
        sortie[_num(k.code)] = num.where(valide)
        sortie[_den(k.code)] = den.where(valide)
    return sortie


def agreger(df: pd.DataFrame, kpis: list[DefinitionKpi], par: list[str]) -> pd.DataFrame:
    """Agrège ``df`` selon les colonnes ``par`` (liste vide => agrégat global).

    Renvoie, pour chaque KPI : la valeur, et les sommes num/den (utiles pour les tests
    et pour ré-agréger sans perte).
    """
    comp = composantes(df, kpis)
    if par:
        comp = pd.concat([df[par], comp], axis=1)
        sommes = comp.groupby(par, dropna=False).sum(min_count=1)
    else:
        sommes = comp.sum(min_count=1).to_frame().T
    for k in kpis:
        num, den = sommes[_num(k.code)], sommes[_den(k.code)]
        if k.denominateur is None:
            sommes[k.code] = num * k.facteur
        else:
            sommes[k.code] = (num / den.replace(0, np.nan)) * k.facteur
    return sommes
