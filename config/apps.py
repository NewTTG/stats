"""Configurations d'applications propres au projet (référencées dans INSTALLED_APPS).

Module léger, chargé avant le registre des modèles : aucun import de modèle ici.
Le site d'administration lui-même est dans ``config/admin.py``.
"""

from django.contrib.admin.apps import AdminConfig
from django_q.apps import DjangoQConfig


class AdminStatsConfig(AdminConfig):
    """Administration Django avec le site du projet (ordre des sections, tableau de bord)."""

    default_site = "config.admin.AdminStats"


class TachesDeFondConfig(DjangoQConfig):
    """django-q2 sous un nom français ; le label reste ``django_q`` (migrations inchangées)."""

    verbose_name = "Tâches de fond"
