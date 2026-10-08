"""Chargement et validation du catalogue KPI (YAML versionné)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


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
    numerateur: str | None = None
    denominateur: str | None = None  # None => KPI additif (somme simple)
    # KPI composite : produit des ratios de sommes des KPI listés (même techno, non composites),
    # calculé après agrégation puis multiplié par ``facteur``. Exclusif de numerateur / denominateur.
    produit_de: list[str] | None = None
    # KPI « cause » : part du KPI parent due à une cause (même pondération que le parent).
    decomposition_de: str | None = None
    # Borne haute appliquée ligne à ligne au numérateur (ex. disponibilité publiée > 100 %).
    plafond: float | None = None
    facteur: float = 1.0
    sens: Literal["haut_est_mieux", "bas_est_mieux"]
    seuils: Seuils = Seuils()
    # exact : compteurs bruts ; reconstruit : dénominateur déduit d'un ratio publié ;
    # approx : pondération de substitution, à remplacer par les compteurs bruts.
    qualite: Literal["exact", "reconstruit", "approx"] = "exact"
    note: str | None = None
    # Définitions résolues de ``produit_de`` (renseignées au chargement du catalogue).
    composants: list["DefinitionKpi"] = Field(default_factory=list, exclude=True, repr=False)

    @model_validator(mode="after")
    def _formule(self):
        if self.produit_de is not None:
            if self.numerateur is not None or self.denominateur is not None:
                raise ValueError(f"{self.code} : produit_de exclut numerateur / denominateur")
            if len(self.produit_de) < 2:
                raise ValueError(f"{self.code} : produit_de demande au moins deux KPI")
        elif self.numerateur is None:
            raise ValueError(f"{self.code} : numerateur ou produit_de requis")
        return self

    @property
    def additif(self) -> bool:
        """KPI sommé tel quel (volume, nombre d'appels...), sans dénominateur."""
        return self.denominateur is None and self.produit_de is None

    @property
    def formule(self) -> str:
        """Formule lisible (exports, documentation)."""
        if self.produit_de:
            return " × ".join(self.produit_de)
        if self.denominateur is None:
            return f"Σ {self.numerateur}"
        return f"Σ ({self.numerateur}) / Σ ({self.denominateur})"

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
    par_code = {k.code: k for k in kpis}
    for k in kpis:
        if k.decomposition_de is not None:
            parent = par_code.get(k.decomposition_de)
            if parent is None or parent.techno != k.techno:
                raise ValueError(f"{k.code} : decomposition_de inconnu ou d'une autre techno")
        if k.produit_de is None:
            continue
        for code in k.produit_de:
            composant = par_code.get(code)
            if composant is None or composant.techno != k.techno or composant.produit_de is not None:
                raise ValueError(f"{k.code} : composant {code!r} inconnu, d'une autre techno ou composite")
            if composant.additif:
                raise ValueError(f"{k.code} : composant {code!r} additif (un ratio est attendu)")
        k.composants = [par_code[c] for c in k.produit_de]
    return par_code


@lru_cache
def catalogue_yaml() -> dict[str, DefinitionKpi]:
    """Catalogue tel que défini dans le YAML versionné."""
    from django.conf import settings

    return charger_catalogue(settings.KPI_CATALOGUE_PATH)


def catalogue() -> dict[str, DefinitionKpi]:
    """Catalogue YAML, avec les seuils réglés dans l'admin (table ``SeuilKpi``)."""
    from .models import SeuilKpi

    base = catalogue_yaml()
    reglages = {s.code: s for s in SeuilKpi.objects.filter(code__in=list(base))}
    return {
        code: k.model_copy(update={"seuils": Seuils(alerte=r.alerte, critique=r.critique)}) if (r := reglages.get(code)) else k
        for code, k in base.items()
    }
