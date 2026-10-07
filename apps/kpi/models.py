from django.core.exceptions import ValidationError
from django.db import models


class SeuilKpi(models.Model):
    """Seuils d'un KPI réglés dans l'admin ; ils remplacent ceux du catalogue YAML.

    Une ligne par KPI, créée avec les valeurs du YAML à l'ouverture de la page d'admin.
    Seuil vide = pas de seuil.
    """

    code = models.CharField("KPI", max_length=64, unique=True)
    alerte = models.FloatField(null=True, blank=True)
    critique = models.FloatField(null=True, blank=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "seuil KPI"
        verbose_name_plural = "seuils KPI"

    def __str__(self):
        return self.code

    @classmethod
    def synchroniser(cls):
        """Crée les lignes manquantes avec les seuils du catalogue YAML."""
        from .catalogue import catalogue_yaml

        existants = set(cls.objects.values_list("code", flat=True))
        cls.objects.bulk_create([
            cls(code=code, alerte=k.seuils.alerte, critique=k.seuils.critique)
            for code, k in catalogue_yaml().items() if code not in existants
        ])

    def clean(self):
        from .catalogue import catalogue_yaml

        kpi = catalogue_yaml().get(self.code)
        if kpi is None:
            raise ValidationError({"code": "KPI absent du catalogue"})
        if self.critique is not None and self.alerte is None:
            raise ValidationError({"alerte": "Renseigner le seuil d'alerte si un seuil critique est défini."})
        if self.alerte is not None and self.critique is not None:
            if kpi.sens == "haut_est_mieux" and self.critique > self.alerte:
                raise ValidationError({"critique": "Plus haut est mieux : le seuil critique doit être ≤ au seuil d'alerte."})
            if kpi.sens == "bas_est_mieux" and self.critique < self.alerte:
                raise ValidationError({"critique": "Plus bas est mieux : le seuil critique doit être ≥ au seuil d'alerte."})
