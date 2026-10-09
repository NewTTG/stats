"""Accès sans compte : chaque navigateur reçoit une session « visiteur » (cookie de session).

Le visiteur est un utilisateur Django créé à la première visite (``visiteur-xxxxxxxx``,
groupe Analyste, sans mot de passe) : son historique de recherches et ses rapports lui
restent propres tant que le cookie est conservé. L'administration reste réservée aux
comptes avec mot de passe (``/connexion``). Désactivable par ``ACCES_ANONYME=0``.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group
from django.utils import timezone

PREFIXE = "visiteur-"
GROUPE = "Analyste"
# Pages jamais ouvertes en visiteur : administration, connexion, fichiers statiques.
CHEMINS_EXCLUS = ("/admin", "/connexion", "/deconnexion", "/static", "/favicon.ico")
BACKEND = "django.contrib.auth.backends.ModelBackend"


def est_visiteur(user) -> bool:
    return user.is_authenticated and user.username.startswith(PREFIXE) and not user.has_usable_password()


def creer_visiteur():
    User = get_user_model()
    while True:
        nom = f"{PREFIXE}{secrets.token_hex(4)}"
        if not User.objects.filter(username=nom).exists():
            break
    user = User(username=nom, first_name="Visiteur")
    user.set_unusable_password()
    user.save()
    user.groups.add(Group.objects.get_or_create(name=GROUPE)[0])
    return user


def contexte_visiteur(request):
    """Processeur de contexte : en-tête « session de ce navigateur » au lieu du nom d'utilisateur."""
    return {"visiteur": est_visiteur(request.user) if hasattr(request, "user") else False}


class VisiteurAnonymeMiddleware:
    """Ouvre une session visiteur à la première page vue (GET) d'un navigateur sans session.

    Seulement sur GET : un formulaire envoyé avec une session expirée ne crée pas de visiteur
    (le jeton CSRF changerait en cours de requête) ; la page d'accueil le fera ensuite.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.ACCES_ANONYME and not request.path.startswith(CHEMINS_EXCLUS):
            user = request.user
            if not user.is_authenticated:
                if request.method == "GET":
                    login(request, creer_visiteur(), backend=BACKEND)
            elif est_visiteur(user) and (user.last_login is None
                                         or timezone.now() - user.last_login > timedelta(days=1)):
                # Dernière activité (au jour près), pour purger les visiteurs disparus ; le cookie
                # est prolongé d'autant (un an après la dernière visite, pas après la première).
                get_user_model().objects.filter(pk=user.pk).update(last_login=timezone.now())
                request.session.modified = True
        return self.get_response(request)
