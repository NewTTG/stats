"""Chargement et validation du catalogue KPI (YAML versionné)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class Seuils(BaseModel):
    alerte: float | None = None
    critique: float | None = None


class DefinitionKpi(BaseModel):
    code: str
    libelle: str
    techno: Literal["LTE", "WCDMA"]
    unite: str
    categorie: Literal[
        "debit", "trafic", "accessibilite", "retainability", "congestion", "mobilite", "disponibilite"
    ]
    # Expressions pandas (DataFrame.eval) évaluées ligne à ligne sur les colonnes source.
    numerateur: str
    denominateur: str | None = None  # None => KPI additif (somme simple)
    facteur: float = 1.0
    sens: Literal["haut_est_mieux", "bas_est_mieux"]
    seuils: Seuils = Seuils()
    # exact : compteurs bruts ; reconstruit : dénominateur déduit d'un ratio publié ;
    # approx : pondération de substitution, à remplacer par les compteurs bruts.
    qualite: Literal["exact", "reconstruit", "approx"] = "exact"
    note: str | None = None

    def statut(self, valeur: float | None) -> str:
        """« critique », « alerte » ou « » selon les seuils et le sens du KPI."""
        if valeur is None or self.seuils.alerte is None:
            return ""
        def franchi(seuil):
            return valeur <= seuil if self.sens == "haut_est_mieux" else valeur >= seuil

        if self.seuils.critique is not None and franchi(self.seuils.critique):
            return "critique"
        return "alerte" if franchi(self.seuils.alerte) else ""


def charger_catalogue(chemin: Path) -> dict[str, DefinitionKpi]:
    with open(chemin, encoding="utf-8") as f:
        brut = yaml.safe_load(f)
    kpis = [DefinitionKpi(**k) for k in brut["kpis"]]
    codes = [k.code for k in kpis]
    doublons = {c for c in codes if codes.count(c) > 1}
    if doublons:
        raise ValueError(f"codes KPI en double : {sorted(doublons)}")
    return {k.code: k for k in kpis}


@lru_cache
def catalogue() -> dict[str, DefinitionKpi]:
    from django.conf import settings

    return charger_catalogue(settings.KPI_CATALOGUE_PATH)
