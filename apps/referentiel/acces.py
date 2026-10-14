"""Droits sur les pages Réseau de l'application (sites, secteurs, cellules).

Consultation : comptes qui voient tout le réseau, ou qui gèrent le référentiel ou les événements
(la carte des événements montre déjà le référentiel). Déclaration, modification, suppression :
droits Django du modèle ``Site`` (attribués aux groupes dans l'administration).
"""

from apps.comptes.acces import voit_tout_le_reseau

DROITS_CONSULTATION = ("referentiel.view_site", "referentiel.change_site", "referentiel.add_site",
                       "evenements.add_evenement", "evenements.change_evenement")


def peut_consulter(user) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    return voit_tout_le_reseau(user) or any(user.has_perm(d) for d in DROITS_CONSULTATION)


def peut_modifier(user) -> bool:
    return user.is_authenticated and user.has_perm("referentiel.change_site")


def peut_declarer(user) -> bool:
    return user.is_authenticated and user.has_perm("referentiel.add_site")


def peut_supprimer(user, site) -> bool:
    """Seul un site déclaré dans l'application se supprime ici (les autres viennent du xlsx)."""
    return site.manuel and user.is_authenticated and user.has_perm("referentiel.delete_site")


def contexte_reseau(request):
    """Processeur de contexte : lien « Réseau » du menu."""
    user = getattr(request, "user", None)
    return {"acces_reseau": bool(user) and peut_consulter(user)}
