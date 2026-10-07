"""Historique des rapports générés en tâche de fond (django-q2)."""

from django.conf import settings
from django.db import models


class Rapport(models.Model):
    NATURES = [("requete", "Requête KPI"), ("evenement", "Événement")]
    FORMATS = [("pptx", "PowerPoint"), ("xlsx", "Excel")]
    STATUTS = [("en_attente", "En attente"), ("en_cours", "En cours"), ("termine", "Terminé"), ("erreur", "Erreur")]

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rapports")
    titre = models.CharField(max_length=200)
    nature = models.CharField(max_length=16, choices=NATURES)
    format = models.CharField(max_length=8, choices=FORMATS)
    parametres = models.JSONField(default=dict)
    statut = models.CharField(max_length=16, choices=STATUTS, default="en_attente")
    fichier = models.FileField(upload_to="rapports/%Y/%m/", blank=True)
    message = models.TextField(blank=True)
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    termine_le = models.DateTimeField("terminé le", null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self):
        return self.titre

    @property
    def en_cours(self) -> bool:
        return self.statut in ("en_attente", "en_cours")
