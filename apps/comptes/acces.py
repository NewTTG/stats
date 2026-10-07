"""Règles d'accès aux données : UNE seule fonction centrale par question (brief §7).

Toute lecture de données KPI passe par ``cellules_autorisees`` et ``kpis_autorises``.
"""

from django.db.models import Q

from apps.referentiel.models import Cellule

from .models import Perimetre

GROUPES_RESEAU_COMPLET = {"Admin", "Analyste"}


def voit_tout_le_reseau(user) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    return user.is_superuser or user.groups.filter(name__in=GROUPES_RESEAU_COMPLET).exists()


def _perimetres(user):
    return Perimetre.objects.filter(Q(utilisateurs=user) | Q(groupes__in=user.groups.all())).distinct()


def cellules_autorisees(user, techno: str) -> set[str] | None:
    """Noms de cellules accessibles ; None = tout le réseau ; ensemble vide = rien."""
    if voit_tout_le_reseau(user):
        return None
    if not user.is_authenticated or not user.is_active:
        return set()
    communes, sites, cellules = set(), set(), set()
    for p in _perimetres(user):
        communes.update(p.communes)
        sites.update(p.sites)
        cellules.update(p.cellules)
    if not (communes or sites or cellules):
        return set()
    filtre = Q(secteur__site__commune__in=communes) | Q(secteur__site__code_site__in=sites) | Q(nom__in=cellules)
    return set(Cellule.objects.filter(filtre, techno=techno).values_list("nom", flat=True))


def kpis_autorises(user, codes: set[str]) -> set[str]:
    """Sous-ensemble de ``codes`` que l'utilisateur peut consulter."""
    if voit_tout_le_reseau(user):
        return set(codes)
    if not user.is_authenticated or not user.is_active:
        return set()
    listes = [p.kpis_autorises for p in _perimetres(user)]
    if not listes:
        return set()
    if any(not liste for liste in listes):  # un périmètre sans liste blanche = tous les KPI
        return set(codes)
    return set(codes) & {c for liste in listes for c in liste}
