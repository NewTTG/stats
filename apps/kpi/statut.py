"""Statut d'une valeur KPI vis-à-vis de ses seuils (écran et exports)."""

from .catalogue import DefinitionKpi


def statut(kpi: DefinitionKpi, valeur: float | None) -> str:
    """'' (normal), 'alerte' ou 'critique' — voir ``DefinitionKpi.statut``.

    Les seuils sont ceux de ``kpi`` : passer une définition issue de ``catalogue()``
    pour tenir compte des réglages faits dans l'admin.
    """
    return kpi.statut(valeur)
