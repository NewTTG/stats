"""Visibilité et droits sur les événements.

Un événement public se voit dès qu'il a au moins une cellule dans le périmètre autorisé ; un événement
privé, par son créateur seul. Chacun voit toujours les siens. Tout utilisateur crée des événements et
modifie ceux qu'il voit ; la visibilité se règle par le créateur.
"""

from django.db.models import Q

from apps.comptes.acces import cellules_autorisees, voit_tout_le_reseau
from apps.referentiel.models import Cellule

from . import mobiles
from .models import Evenement


def evenements_visibles(user, queryset=None):
    queryset = Evenement.objects.all() if queryset is None else queryset
    if not user.is_authenticated or not user.is_active:
        return queryset.none()
    siens = Q(cree_par=user)
    if voit_tout_le_reseau(user):
        return queryset.filter(Q(public=True) | siens)
    noms = set().union(*(cellules_autorisees(user, techno) or set() for techno in ("LTE", "WCDMA")))
    if not noms:
        return queryset.filter(siens)
    rattachements = list(Cellule.objects.filter(nom__in=noms).values_list(
        "secteur__site__code_site", "secteur__code"))
    sites = {site for site, _ in rattachements if site}
    secteurs = {secteur for _, secteur in rattachements if secteur}
    # Les listes sont des JSONField : filtrage portable PostgreSQL / SQLite,
    # sans une requête supplémentaire pour chaque événement.
    ids = [pk for pk, cs, ss, sc, dep in queryset.filter(public=True).values_list(
               "pk", "cellules", "sites", "secteurs", "deploiements")
           if noms.intersection(cs) or sites.intersection(ss) or secteurs.intersection(sc)
           or noms.intersection(mobiles.cellules(dep or {}))]
    return queryset.filter(Q(pk__in=ids) | siens)


def peut_choisir_visibilite(user, evenement) -> bool:
    """Public / privé : à la création, puis par le créateur (un ancien événement sans créateur
    revient à celui qui l'enregistre)."""
    return evenement.pk is None or evenement.cree_par_id in (None, user.pk)


def peut_supprimer(user, evenement) -> bool:
    return evenement.cree_par_id == user.pk or user.has_perm("evenements.delete_evenement")
