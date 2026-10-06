"""Modèle de requête unique (brief §5) : formulaire, futur parseur NL et API produisent cet objet."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Techno = Literal["LTE", "WCDMA"]
TypePerimetre = Literal[
    "global", "commune", "site", "trigramme", "cellule", "secteur", "evenement", "zone_personnalisee"
]
GranulariteTemps = Literal["heure", "jour", "semaine", "mois"]
GranulariteEspace = Literal["global", "commune", "site", "secteur", "cellule"]
TypeComparaison = Literal["aucune", "periode_precedente", "meme_periode_annee_n-1", "reference_personnalisee"]


class Perimetre(BaseModel):
    type: TypePerimetre
    valeurs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valeurs_requises(self):
        if self.type != "global" and not self.valeurs:
            raise ValueError("au moins une valeur est requise pour ce type de périmètre")
        return self


class Periode(BaseModel):
    debut: date
    fin: date

    @model_validator(mode="after")
    def _ordre(self):
        if self.fin < self.debut:
            raise ValueError("la fin de période précède le début")
        return self


class Comparaison(BaseModel):
    type: TypeComparaison = "aucune"
    reference: Periode | None = None

    @model_validator(mode="after")
    def _reference(self):
        if self.type == "reference_personnalisee" and self.reference is None:
            raise ValueError("une période de référence est requise")
        return self


class RequeteKpi(BaseModel):
    techno: list[Techno] = Field(min_length=1)
    perimetre: Perimetre
    periode: Periode
    granularite_temps: GranulariteTemps = "jour"
    granularite_espace: GranulariteEspace = "global"
    # "18-22", "7-20", "journee" ou "heure_chargee"
    fenetre_horaire: str = "journee"
    kpis: list[str] = Field(min_length=1)
    comparaison: Comparaison = Field(default_factory=Comparaison)

    @model_validator(mode="after")
    def _fenetre(self):
        f = self.fenetre_horaire
        if f in ("journee", "heure_chargee"):
            return self
        try:
            debut, fin = (int(x) for x in f.split("-"))
        except ValueError:
            raise ValueError(f"fenêtre horaire invalide : {f!r}") from None
        if not (0 <= debut < fin <= 24):
            raise ValueError(f"fenêtre horaire invalide : {f!r}")
        return self
