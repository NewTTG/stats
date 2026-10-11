"""Périmètres d'accès et journal d'audit (brief §7)."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


class Perimetre(models.Model):
    """Ensemble de communes / sites / cellules autorisé pour des utilisateurs ou groupes.

    Un utilisateur sans périmètre (et non analyste/admin) ne voit rien : le filtrage
    est appliqué côté serveur dans la couche d'accès aux données.
    """

    nom = models.CharField(max_length=128, unique=True)
    utilisateurs = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="perimetres")
    groupes = models.ManyToManyField(Group, blank=True, related_name="perimetres")
    communes = models.JSONField(default=list, blank=True)
    sites = models.JSONField("codes site", default=list, blank=True)
    cellules = models.JSONField(default=list, blank=True)
    # Liste blanche de codes KPI ; vide = tous les KPI du catalogue.
    kpis_autorises = models.JSONField("KPI autorisés", default=list, blank=True)

    class Meta:
        verbose_name = "périmètre d'accès"
        verbose_name_plural = "périmètres d'accès"

    def __str__(self):
        return self.nom


class JournalAudit(models.Model):
    date = models.DateTimeField(auto_now_add=True, db_index=True)
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    requete = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "entrée du journal d'audit"
        verbose_name_plural = "journal d'audit"
