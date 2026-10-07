"""Statut d'une valeur KPI vis-à-vis de ses seuils (écran et exports)."""

from .catalogue import DefinitionKpi


def statut(kpi: DefinitionKpi, valeur: float | None) -> str:
    """'' (normal), 'alerte' ou 'critique'."""
    if valeur is None or kpi.seuils.alerte is None:
        return ""
    pire = (lambda v, s: v <= s) if kpi.sens == "haut_est_mieux" else (lambda v, s: v >= s)
    if kpi.seuils.critique is not None and pire(valeur, kpi.seuils.critique):
        return "critique"
    return "alerte" if pire(valeur, kpi.seuils.alerte) else ""
