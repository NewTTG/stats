"""Moteur de calcul : agrégation en ratio de sommes (brief §4).

Chaque KPI est ramené à un couple (numérateur, dénominateur) par ligne source ;
on somme sur le temps et l'espace, puis on divise. Jamais de moyenne de ratios.
KPI « pic » (``agregation: pic``) : somme des cellules à chaque horodatage, puis
maximum sur le temps.
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


def ratios_simples(kpis: list[DefinitionKpi]) -> list[DefinitionKpi]:
    """KPI à numérateur / dénominateur à calculer : ceux demandés et les composants
    des KPI composites (``produit_de``), sans doublon."""
    vus: dict[str, DefinitionKpi] = {}
    for k in kpis:
        for c in (k.composants if k.produit_de else [k]):
            vus.setdefault(c.code, c)
    return list(vus.values())


def composantes(df: pd.DataFrame, kpis: list[DefinitionKpi]) -> pd.DataFrame:
    """Ajoute les colonnes numérateur / dénominateur de chaque KPI (composants inclus).

    Une ligne dont une composante n'est pas calculable (donnée absente) reste NaN :
    elle est exclue des sommes, ce qui distingue « pas de données » de « valeur nulle ».
    """
    sortie = pd.DataFrame(index=df.index)
    for k in ratios_simples(kpis):
        num = _evaluer(df, k.numerateur)
        if k.plafond is not None:
            num = num.clip(upper=k.plafond)
        if k.denominateur is None:
            sortie[_num(k.code)] = num
            sortie[_den(k.code)] = np.where(num.isna(), np.nan, 1.0)
            continue
        den = _evaluer(df, k.denominateur)
        valide = num.notna() & den.notna()
        sortie[_num(k.code)] = num.where(valide)
        sortie[_den(k.code)] = den.where(valide)
    return sortie


def _pics(df: pd.DataFrame, comp: pd.DataFrame, pics: list[DefinitionKpi], par: list[str]) -> pd.DataFrame:
    """Numérateurs des KPI « pic » : somme des cellules à chaque horodatage (sum(min_count=1)),
    puis maximum de ces totaux sur les horodatages de chaque groupe ``par``. Un horodatage
    sans donnée est ignoré ; un groupe sans aucune donnée reste NaN."""
    colonnes = [_num(k.code) for k in pics]
    instants = [*par, "horodatage"]
    par_instant = pd.concat([df[instants], comp[colonnes]], axis=1).groupby(instants, dropna=False).sum(min_count=1)
    if par:
        return par_instant.groupby(level=par, dropna=False).max()
    return par_instant.max().to_frame().T


def agreger(df: pd.DataFrame, kpis: list[DefinitionKpi], par: list[str]) -> pd.DataFrame:
    """Agrège ``df`` selon les colonnes ``par`` (liste vide => agrégat global).

    Renvoie, pour chaque KPI : la valeur, et les sommes num/den (utiles pour les tests
    et pour ré-agréger sans perte). Un KPI composite vaut le produit des ratios de sommes
    de ses composants : jamais la moyenne de produits calculés ligne à ligne.
    KPI « pic » : num = pic (voir ``_pics``), den = 1 s'il est défini.
    """
    comp = composantes(df, kpis)
    if par:
        sommes = pd.concat([df[par], comp], axis=1).groupby(par, dropna=False).sum(min_count=1)
    else:
        sommes = comp.sum(min_count=1).to_frame().T
    # Pic : remplace la somme. Sans colonne ``horodatage``, les lignes sont tenues pour
    # simultanées et le pic reste la somme simple ; de même si ``par`` contient l'horodatage
    # (un seul instant par groupe).
    pics = [k for k in ratios_simples(kpis) if k.pic]
    if pics and "horodatage" in df.columns and "horodatage" not in par:
        maxima = _pics(df, comp, pics, par).reindex(sommes.index)
        for k in pics:
            sommes[_num(k.code)] = maxima[_num(k.code)]
            sommes[_den(k.code)] = np.where(maxima[_num(k.code)].isna(), np.nan, 1.0)

    def ratio(k: DefinitionKpi) -> pd.Series:
        return sommes[_num(k.code)] / sommes[_den(k.code)].replace(0, np.nan)

    for k in kpis:
        if k.produit_de:
            valeur = ratio(k.composants[0])
            for c in k.composants[1:]:
                valeur = valeur * ratio(c)
            sommes[k.code] = valeur * k.facteur
        elif k.additif:
            sommes[k.code] = sommes[_num(k.code)] * k.facteur
        else:
            sommes[k.code] = ratio(k) * k.facteur
    return sommes
