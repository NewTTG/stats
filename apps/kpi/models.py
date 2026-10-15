from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .catalogue import LIBELLES_CATEGORIE


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


class ColonneKpi(models.Model):
    """Colonne de mesure d'une table de la base KPI, décrite pour les utilisateurs.

    Les lignes sont créées et tenues à jour par ``synchroniser`` (lecture du schéma de la base KPI) ;
    libellé, catégorie et description se règlent dans l'admin. Une colonne qui disparaît de la base
    est conservée (``presente`` à faux) avec sa description.
    """

    TECHNOS = [("LTE", "4G (LTE)"), ("WCDMA", "3G (WCDMA)")]

    techno = models.CharField(max_length=8, choices=TECHNOS)
    nom = models.CharField("colonne", max_length=128, help_text="Nom de la colonne dans la base KPI.")
    libelle = models.CharField("nom affiché", max_length=120, blank=True,
                               help_text="Nom présenté aux utilisateurs à la place du nom technique.")
    categorie = models.CharField("catégorie", max_length=32, blank=True, choices=list(LIBELLES_CATEGORIE.items()))
    description = models.TextField(blank=True, help_text="Ce que mesure la colonne, unité, précautions d'usage.")
    type_donnees = models.CharField("type", max_length=64, blank=True)
    tables = models.CharField("données", max_length=32, blank=True,
                              help_text="Tables où la colonne existe : jour, heure.")
    presente = models.BooleanField("présente en base", default=True)
    vue_le = models.DateTimeField("dernière lecture de la base", null=True, blank=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        ordering = ["techno", "nom"]
        constraints = [models.UniqueConstraint(fields=["techno", "nom"], name="colonne_kpi_unique")]
        verbose_name = "colonne de la base KPI"
        verbose_name_plural = "colonnes de la base KPI"

    def __str__(self):
        return f"{self.nom} ({self.techno})"

    @property
    def nom_affiche(self):
        return self.libelle or self.nom

    @classmethod
    def synchroniser(cls, engine=None) -> dict:
        """Relit les colonnes des tables KPI : ajoute les nouvelles, met à jour type et tables,
        marque absentes celles qui ont disparu. Libellés, catégories et descriptions sont conservés.

        Catégorie d'une nouvelle colonne : celle des KPI du catalogue qui l'utilisent, si elle est unique.
        """
        from .catalogue import catalogue_yaml, colonnes_utilisees
        from .source import colonnes_base, moteur_kpi

        lues = colonnes_base(engine or moteur_kpi())
        categories = {}
        for k in catalogue_yaml().values():
            for nom in colonnes_utilisees(k):
                categories.setdefault((k.techno, nom), set()).add(k.categorie)

        maintenant = timezone.now()
        existantes = {(c.techno, c.nom): c for c in cls.objects.all()}
        nouvelles, modifiees = [], []
        for techno, colonnes in lues.items():
            for nom, info in colonnes.items():
                tables = ", ".join(r for r in ("jour", "heure") if r in info["tables"])
                colonne = existantes.get((techno, nom))
                if colonne is None:
                    cats = categories.get((techno, nom), set())
                    nouvelles.append(cls(techno=techno, nom=nom, type_donnees=info["type"][:64], tables=tables,
                                         categorie=next(iter(cats)) if len(cats) == 1 else "", vue_le=maintenant))
                    continue
                colonne.type_donnees, colonne.tables = info["type"][:64], tables
                colonne.presente, colonne.vue_le = True, maintenant
                modifiees.append(colonne)
        cls.objects.bulk_create(nouvelles)
        # bulk_update n'applique pas auto_now : « modifié le » reste la date de la dernière saisie.
        cls.objects.bulk_update(modifiees, ["type_donnees", "tables", "presente", "vue_le"], batch_size=500)
        vues = {(c.techno, c.nom) for c in nouvelles + modifiees}
        disparues = [c.pk for cle, c in existantes.items() if cle not in vues and c.presente]
        cls.objects.filter(pk__in=disparues).update(presente=False)
        return {"lues": len(vues), "nouvelles": len(nouvelles), "disparues": len(disparues)}
