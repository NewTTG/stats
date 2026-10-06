"""Référentiel réseau importé depuis le fichier xlsx (onglets Site_File / Cell_File).

Le xlsx n'est jamais interrogé en direct : il est chargé ici par
``manage.py import_referentiel`` (phase 1), chaque import étant versionné.
"""

from django.conf import settings
from django.db import models


class ImportReferentiel(models.Model):
    date = models.DateTimeField(auto_now_add=True)
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    fichier = models.CharField(max_length=255)
    nb_sites = models.PositiveIntegerField(default=0)
    nb_secteurs = models.PositiveIntegerField(default=0)
    ajouts = models.JSONField(default=list, blank=True)
    suppressions = models.JSONField(default=list, blank=True)
    anomalies = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "import du référentiel"
        verbose_name_plural = "imports du référentiel"

    def __str__(self):
        return f"{self.fichier} ({self.date:%Y-%m-%d %H:%M})"


class Site(models.Model):
    code_site = models.CharField("code site", max_length=16, unique=True)
    trigramme = models.CharField(max_length=8, db_index=True)
    nom = models.CharField(max_length=64)
    commune = models.CharField(max_length=64, db_index=True)
    region = models.CharField("région", max_length=32, blank=True)
    nom_wcdma = models.CharField("nom RBS 3G", max_length=64, blank=True)
    nom_lte = models.CharField("nom ERBS", max_length=64, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    type_zone = models.CharField("type de zone", max_length=16, blank=True)

    class Meta:
        ordering = ["code_site"]

    def __str__(self):
        return f"{self.nom} ({self.code_site})"


class Secteur(models.Model):
    code = models.CharField(max_length=16, unique=True)  # <codeSite><n° secteur>
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="secteurs")
    numero = models.PositiveSmallIntegerField("n° secteur")
    azimut = models.SmallIntegerField(null=True, blank=True)
    province = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Cellule(models.Model):
    """Cellule radio rattachée à un secteur (dérivée des conventions de nommage)."""

    TECHNOS = [("LTE", "LTE"), ("WCDMA", "WCDMA")]

    nom = models.CharField(max_length=32)
    techno = models.CharField(max_length=8, choices=TECHNOS)
    secteur = models.ForeignKey(Secteur, null=True, on_delete=models.SET_NULL, related_name="cellules")
    porteuse = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [("techno", "nom")]
        ordering = ["techno", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.techno})"
