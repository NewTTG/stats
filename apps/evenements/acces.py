"""Visibilité des événements : au moins une cellule dans le périmètre autorisé."""

from apps.comptes.acces import cellules_autorisees, voit_tout_le_reseau
from apps.referentiel.models import Cellule

from .models import Evenement


def evenements_visibles(user, queryset=None):
    queryset = Evenement.objects.all() if queryset is None else queryset
    if voit_tout_le_reseau(user):
        return queryset
    noms = set().union(*(cellules_autorisees(user, techno) or set() for techno in ("LTE", "WCDMA")))
    if not noms:
        return queryset.none()
    rattachements = list(Cellule.objects.filter(nom__in=noms).values_list(
        "secteur__site__code_site", "secteur__code"))
    sites = {site for site, _ in rattachements if site}
    secteurs = {secteur for _, secteur in rattachements if secteur}
    # Les listes sont des JSONField : filtrage portable PostgreSQL / SQLite,
    # sans une requête supplémentaire pour chaque événement.
    ids = [pk for pk, cs, ss, sc in queryset.values_list("pk", "cellules", "sites", "secteurs")
           if noms.intersection(cs) or sites.intersection(ss) or secteurs.intersection(sc)]
    return queryset.filter(pk__in=ids)
