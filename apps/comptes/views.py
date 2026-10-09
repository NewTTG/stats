"""Page de connexion (/connexion/) : entrée de l'administration quand les statistiques
s'utilisent sans compte (``ACCES_ANONYME``), connexion de tous les comptes sinon."""

from django.conf import settings
from django.contrib.auth.views import LoginView
from django.urls import reverse

from .visiteurs import est_visiteur


class ConnexionView(LoginView):
    def get_default_redirect_url(self):
        """Sans ``next`` : un administrateur arrive sur l'administration (accès sans compte),
        les autres comptes sur la recherche (``LOGIN_REDIRECT_URL``)."""
        if settings.ACCES_ANONYME and self.request.user.is_staff:
            return reverse("admin:index")
        return super().get_default_redirect_url()

    def get_context_data(self, **kwargs):
        contexte = super().get_context_data(**kwargs)
        user = self.request.user
        suite = contexte.get(self.redirect_field_name) or ""
        contexte["acces_anonyme"] = settings.ACCES_ANONYME
        # Compte connecté renvoyé ici depuis /admin/ : il n'a pas accès à l'administration.
        contexte["compte_sans_administration"] = (
            user.is_authenticated and not est_visiteur(user) and not user.is_staff
            and suite.startswith(reverse("admin:index")))
        return contexte
