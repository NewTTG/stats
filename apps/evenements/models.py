"""Événements (brief §6) : cellules concernées, créneaux, période de référence."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.referentiel.models import Cellule


class Evenement(models.Model):
    """Les cellules sont désignées par leurs noms (comme les périmètres) : un nouvel
    import du référentiel recrée les ``Cellule`` sans perdre les événements."""

    nom = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=32, blank=True, help_text="Étiquette libre, ex. Concert, Journée, Foire.")
    sites = models.JSONField("codes site", default=list, blank=True)
    secteurs = models.JSONField(default=list, blank=True)
    cellules = models.JSONField(default=list, blank=True)
    # Liste blanche de codes KPI ; vide = tous les KPI du catalogue.
    kpis = models.JSONField("KPI analysés", default=list, blank=True)
    semaines_reference = models.PositiveSmallIntegerField(
        "semaines de référence", default=4, validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Chaque créneau est comparé aux mêmes jour et heures des N semaines précédentes.")
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+", verbose_name="créé par")
    cree_le = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "événement"

    def __str__(self):
        return self.nom

    def noms_cellules(self, techno: str) -> list[str]:
        """Cellules de l'événement pour une techno (sites + secteurs + cellules listés)."""
        filtre = Q(secteur__site__code_site__in=self.sites) | Q(secteur__code__in=self.secteurs) | Q(nom__in=self.cellules)
        return sorted(Cellule.objects.filter(filtre, techno=techno).values_list("nom", flat=True))

    def cellules_inconnues(self) -> list[str]:
        connues = set(Cellule.objects.filter(nom__in=self.cellules).values_list("nom", flat=True))
        return sorted(set(self.cellules) - connues)


class Creneau(models.Model):
    evenement = models.ForeignKey(Evenement, on_delete=models.CASCADE, related_name="creneaux")
    debut = models.DateTimeField("début")
    fin = models.DateTimeField()

    class Meta:
        ordering = ["debut"]
        verbose_name = "créneau"
        verbose_name_plural = "créneaux"

    def __str__(self):
        return f"{self.debut:%d/%m/%Y %H:%M} → {self.fin:%d/%m/%Y %H:%M}"

    def clean(self):
        if self.debut and self.fin and self.fin <= self.debut:
            raise ValidationError({"fin": "La fin doit suivre le début."})


class ReglagesAnomalies(models.Model):
    """Paramètres de détection (une seule ligne, modifiable dans l'admin)."""

    ecart_sigma = models.FloatField("écart : nombre d'écarts-types", default=2.0)
    ecart_pct = models.FloatField("écart : % minimal par rapport à la référence", default=20.0)
    saturation_prb = models.FloatField("saturation : PRB DL au-dessus de (%)", default=90.0)
    saturation_debit = models.FloatField("saturation : débit DL en dessous de (Mbps)", default=10.0)

    class Meta:
        verbose_name = verbose_name_plural = "réglages de détection d'anomalies"

    def __str__(self):
        return "Réglages de détection"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def courant(cls) -> "ReglagesAnomalies":
        return cls.objects.get_or_create(pk=1)[0]
