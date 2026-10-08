"""Filtres de gabarit de l'application KPI."""

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def coupure(valeur) -> str:
    """Nom d'entité coupable après chaque « _ » (« GREEN_<wbr>ACRE_<wbr>BT ») : sur petit
    écran, la coupure tombe entre deux parties du nom, jamais au milieu d'un mot."""
    return mark_safe(escape(str(valeur)).replace("_", "_<wbr>"))
