"""Graphiques thématiques (``config/graphes.yaml``) : plusieurs KPI d'une même techno sur un
graphique, en barres, barres empilées ou courbes, sur l'axe principal ou secondaire."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .catalogue import DefinitionKpi


class Serie(BaseModel):
    kpi: str
    type: Literal["barres", "barres_empilees", "ligne", "aire"]
    axe: Literal["gauche", "droite"] = "gauche"


class DefinitionGraphe(BaseModel):
    code: str
    titre: str
    theme: str
    series: list[Serie] = Field(min_length=1)
    techno: str = ""  # renseignée au chargement (techno commune des KPI)

    @property
    def kpis(self) -> list[str]:
        return list(dict.fromkeys(s.kpi for s in self.series))


class Graphes(BaseModel):
    themes: dict[str, str]
    graphes: list[DefinitionGraphe]

    def du_theme(self, theme: str) -> list[DefinitionGraphe]:
        return [g for g in self.graphes if g.theme == theme]

    def kpis_du_theme(self, theme: str, techno: str | None = None) -> list[str]:
        """KPI des graphiques d'un thème (d'une techno), dans l'ordre des graphiques (sans doublon)."""
        return list(dict.fromkeys(c for g in self.du_theme(theme) if techno in (None, g.techno) for c in g.kpis))

    def couverts(self, techno: str, codes) -> list[DefinitionGraphe]:
        """Graphiques de ``techno`` dont tous les KPI sont parmi ``codes``."""
        codes = set(codes)
        return [g for g in self.graphes if g.techno == techno and set(g.kpis) <= codes]


def charger_graphes(chemin: Path, catalogue: dict[str, DefinitionKpi]) -> Graphes:
    with open(chemin, encoding="utf-8") as f:
        brut = yaml.safe_load(f)
    graphes = Graphes(**brut)
    codes = [g.code for g in graphes.graphes]
    doublons = {c for c in codes if codes.count(c) > 1}
    if doublons:
        raise ValueError(f"graphiques en double : {sorted(doublons)}")
    for g in graphes.graphes:
        if g.theme not in graphes.themes:
            raise ValueError(f"graphique {g.code} : thème inconnu {g.theme!r}")
        inconnus = [c for c in g.kpis if c not in catalogue]
        if inconnus:
            raise ValueError(f"graphique {g.code} : KPI inconnus {inconnus}")
        technos = {catalogue[c].techno for c in g.kpis}
        if len(technos) != 1:
            raise ValueError(f"graphique {g.code} : KPI de plusieurs technos {sorted(technos)}")
        if len(g.kpis) != len(g.series):
            raise ValueError(f"graphique {g.code} : KPI cité deux fois")
        g.techno = technos.pop()
    return graphes


@lru_cache
def graphes() -> Graphes:
    from django.conf import settings

    from .catalogue import catalogue_yaml

    return charger_graphes(settings.KPI_GRAPHES_PATH, catalogue_yaml())
