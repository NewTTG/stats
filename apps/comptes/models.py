"""Périmètres d'accès et journal d'audit (brief §7)."""

import uuid

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


class DemandeSuivie(models.Model):
    """Une tentative immuable ; les liens de l'écran relient les étapes d'un parcours."""
    NATURES = [('recherche', 'Recherche'), ('export', 'Export Excel'),
               ('evenement', 'Analyse d’événement'), ('rapport', 'Rapport')]
    STATUTS = [('en_cours', 'En cours'), ('a_preciser', 'À préciser'), ('reussie', 'Aboutie'),
               ('sans_donnees', 'Sans données'), ('erreur', 'Échec')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parcours = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='suites')
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    creee_le = models.DateTimeField('créée le', auto_now_add=True, db_index=True)
    terminee_le = models.DateTimeField('terminée le', null=True, blank=True)
    nature = models.CharField(max_length=16, choices=NATURES, default='recherche')
    statut = models.CharField(max_length=16, choices=STATUTS, default='en_cours', db_index=True)
    texte = models.TextField('demande originale', blank=True)
    parametres = models.JSONField('paramètres envoyés', default=dict, blank=True)
    interpretation = models.JSONField('interprétation et suggestions', default=dict, blank=True)
    resultat = models.JSONField('résumé du résultat', default=dict, blank=True)
    message = models.TextField(blank=True)
    duree_ms = models.PositiveIntegerField('durée (ms)', null=True, blank=True)

    class Meta:
        ordering = ['-creee_le']
        verbose_name = 'demande suivie'
        verbose_name_plural = 'suivi des demandes'

    def __str__(self):
        return self.texte or f'{self.get_nature_display()} du {self.creee_le:%d/%m/%Y}'
