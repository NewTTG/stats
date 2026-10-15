import re
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .catalogue import LIBELLES_CATEGORIE

SENS = [("haut_est_mieux", "↑ plus haut est mieux"), ("bas_est_mieux", "↓ plus bas est mieux")]

THEMES_GRAPHES = [("trafic", "Trafic et charge"), ("accessibilite", "Accessibilité"),
                  ("integrite", "Débit et qualité radio"), ("retainability", "Coupures"),
                  ("mobilite", "Mobilité")]
TYPES_SERIES = [("ligne", "Courbe"), ("barres", "Barres"),
                ("barres_empilees", "Barres empilées"), ("aire", "Surface")]


class Graphique(models.Model):
    code = models.CharField(max_length=64, unique=True, default=uuid.uuid4, editable=False)
    titre = models.CharField("nom du graphique", max_length=160)
    theme = models.CharField("thème", max_length=32, choices=THEMES_GRAPHES)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "pk"]
        verbose_name = "graphique"

    def __str__(self):
        return self.titre


class SerieGraphique(models.Model):
    graphique = models.ForeignKey(Graphique, on_delete=models.CASCADE, related_name="series")
    kpi = models.CharField("indicateur", max_length=160)
    type = models.CharField("représentation", max_length=24, choices=TYPES_SERIES, default="ligne")
    axe = models.CharField(max_length=8, choices=[("gauche", "Gauche"), ("droite", "Droite")], default="gauche")
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "pk"]
        verbose_name = "série"

    def __str__(self):
        return f"Série {self.ordre + 1}"


class ModeleRapport(models.Model):
    code = models.CharField(max_length=64, unique=True, default=uuid.uuid4, editable=False)
    titre = models.CharField("nom du rapport", max_length=160)
    description = models.TextField(blank=True)
    accueil = models.BooleanField("proposer sur l’accueil", default=True)
    ordre = models.PositiveIntegerField("position sur l’accueil", default=0)
    icone = models.CharField(max_length=32, blank=True, default="sur_mesure")
    # Ordre propre au rapport, indépendant de l'ordre dans la bibliothèque.
    graphes = models.JSONField("graphiques", default=list, blank=True)
    kpis = models.JSONField("indicateurs complémentaires", default=list, blank=True)

    class Meta:
        ordering = ["ordre", "pk"]
        verbose_name = "rapport et accueil"
        verbose_name_plural = "rapports et accueil"

    def __str__(self):
        return self.titre


class SeuilKpi(models.Model):
    """Réglages d'un KPI dans l'admin : nom affiché, catégorie, description et seuils.

    Une ligne par KPI du catalogue YAML, créée avec ses valeurs à l'ouverture de la page d'admin ;
    les valeurs réglées ici remplacent celles du YAML dans toute l'application (``catalogue()``).
    Seuil vide = pas de seuil ; description vide = pas de description.
    """

    code = models.CharField("KPI", max_length=64, unique=True)
    libelle = models.CharField("nom affiché", max_length=120, blank=True,
                               help_text="Nom présenté aux utilisateurs (recherche, résultats, exports, rapports).")
    categorie = models.CharField("catégorie", max_length=32, blank=True, choices=list(LIBELLES_CATEGORIE.items()))
    # None : description du catalogue YAML (lignes créées avant ces réglages).
    description = models.TextField(null=True, blank=True,
                                   help_text="Affichée en info-bulle à côté de la valeur et dans les rapports.")
    alerte = models.FloatField(null=True, blank=True)
    critique = models.FloatField(null=True, blank=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "KPI"
        verbose_name_plural = "KPI"

    def __str__(self):
        return self.libelle or self.code

    @classmethod
    def synchroniser(cls):
        """Crée les lignes manquantes avec les valeurs du catalogue YAML et complète les champs vides."""
        from .catalogue import catalogue_yaml

        cat = catalogue_yaml()
        existants = {s.code: s for s in cls.objects.all()}
        cls.objects.bulk_create([
            cls(code=code, libelle=k.libelle, categorie=k.categorie, description=k.note or "",
                alerte=k.seuils.alerte, critique=k.seuils.critique)
            for code, k in cat.items() if code not in existants
        ])
        a_completer = []
        for code, s in existants.items():
            if code in cat and (not s.libelle or not s.categorie or s.description is None):
                k = cat[code]
                s.libelle, s.categorie = s.libelle or k.libelle, s.categorie or k.categorie
                s.description = (k.note or "") if s.description is None else s.description
                a_completer.append(s)
        cls.objects.bulk_update(a_completer, ["libelle", "categorie", "description"])

    def retablir(self, kpi):
        """Valeurs du catalogue YAML (``kpi``) : nom, catégorie, description et seuils."""
        self.libelle, self.categorie, self.description = kpi.libelle, kpi.categorie, kpi.note or ""
        self.alerte, self.critique = kpi.seuils.alerte, kpi.seuils.critique

    def appliquer(self, kpi):
        """Définition ``kpi`` du YAML avec les réglages de cette ligne."""
        from .catalogue import Seuils

        modifs = {"seuils": Seuils(alerte=self.alerte, critique=self.critique)}
        if self.libelle:
            modifs["libelle"] = self.libelle
        if self.categorie:
            modifs["categorie"] = self.categorie
        if self.description is not None:
            modifs["note"] = self.description.strip() or None
        return kpi.model_copy(update=modifs)

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


# Suffixes des colonnes (docs/schema.md) : unité et calcul proposés par défaut.
SUFFIXES = [("_p", "%", "moyenne"), ("_kbps", "kbps", "moyenne"), ("_mB", "Mo", "somme"), ("_kB", "ko", "somme"),
            ("_erlg", "Erl", "somme"), ("_dBm", "dBm", "moyenne"), ("_dB", "dB", "moyenne"), ("_nb", "nombre", "somme")]
_IDENTIFIANT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TYPES_NON_NUMERIQUES = ("char", "text", "date", "time", "bool", "json")


def unite_et_calcul(nom: str) -> tuple[str, str]:
    """Unité et calcul suggérés d'après le suffixe ; « Max » dans le nom : pic simultané."""
    unite, calcul = next(((u, c) for suffixe, u, c in SUFFIXES if nom.endswith(suffixe)), ("", "somme"))
    return unite, "pic" if "max" in nom.lower() and calcul == "somme" else calcul


class ColonneKpi(models.Model):
    """Colonne de mesure d'une table de la base KPI, décrite pour les utilisateurs.

    Les lignes sont créées et tenues à jour par ``synchroniser`` (lecture du schéma de la base KPI) ;
    libellé, catégorie et description se règlent dans l'admin. Une colonne qui disparaît de la base
    est conservée (``presente`` à faux) avec sa description. Une colonne « proposée aux utilisateurs »
    devient un indicateur de l'application, sous son nom affiché (``definition``).
    """

    TECHNOS = [("LTE", "4G (LTE)"), ("WCDMA", "3G (WCDMA)")]
    CALCULS = [("somme", "Somme"), ("moyenne", "Moyenne"), ("pic", "Pic simultané")]

    techno = models.CharField(max_length=8, choices=TECHNOS)
    nom = models.CharField("colonne", max_length=128, help_text="Nom de la colonne dans la base KPI.")
    libelle = models.CharField("nom affiché", max_length=120, blank=True,
                               help_text="Nom présenté aux utilisateurs à la place du nom technique.")
    categorie = models.CharField("catégorie", max_length=32, blank=True, choices=list(LIBELLES_CATEGORIE.items()))
    description = models.TextField(blank=True, help_text="Ce que mesure la colonne, unité, précautions d'usage.")
    type_donnees = models.CharField("type", max_length=64, blank=True)
    tables = models.CharField("données", max_length=32, blank=True,
                              help_text="Tables où la colonne existe : jour, heure.")
    proposee = models.BooleanField("proposée", default=False,
                                   help_text="Indicateur sélectionnable dans l'application, sous son nom affiché.")
    calcul = models.CharField(max_length=16, blank=True, choices=CALCULS,
                              help_text="Somme : volumes, nombres. Moyenne : taux, débits, niveaux "
                                        "(moyenne des valeurs des cellules). Pic simultané : somme des cellules "
                                        "à chaque instant, puis maximum sur la période.")
    unite = models.CharField("unité", max_length=24, blank=True)
    sens = models.CharField(max_length=16, choices=SENS, default="haut_est_mieux")
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

    @property
    def code(self):
        """Code de l'indicateur dans le catalogue (requêtes, périmètres, rapports enregistrés)."""
        from .catalogue import PREFIXE_COLONNE

        return f"{PREFIXE_COLONNE}{self.techno.lower()}_{self.nom}"

    def clean(self):
        if not self.proposee:
            return
        manques = {champ: "Obligatoire pour proposer la colonne aux utilisateurs."
                   for champ in ("libelle", "categorie", "calcul", "unite") if not getattr(self, champ)}
        if manques:
            raise ValidationError(manques)
        if not self.presente or self.tables != "jour, heure" or not _IDENTIFIANT.match(self.nom):
            raise ValidationError({"proposee": "Seules les colonnes présentes dans les tables journalière "
                                               "et horaire peuvent être proposées."})
        if any(t in self.type_donnees for t in _TYPES_NON_NUMERIQUES):
            raise ValidationError({"proposee": f"Colonne non numérique ({self.type_donnees}) : pas de calcul possible."})

    def definition(self):
        """Indicateur du catalogue correspondant à la colonne (None si incomplète)."""
        from .catalogue import DefinitionKpi

        try:
            self.clean()
        except ValidationError:
            return None
        return DefinitionKpi(
            code=self.code, libelle=self.libelle, techno=self.techno, unite=self.unite, categorie=self.categorie,
            numerateur=self.nom, denominateur="1" if self.calcul == "moyenne" else None,
            agregation="pic" if self.calcul == "pic" else "somme", sens=self.sens,
            note=self.description.strip() or None)

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
                    unite, calcul = unite_et_calcul(nom)
                    nouvelles.append(cls(techno=techno, nom=nom, type_donnees=info["type"][:64], tables=tables,
                                         categorie=next(iter(cats)) if len(cats) == 1 else "",
                                         unite=unite, calcul=calcul, vue_le=maintenant))
                    continue
                colonne.type_donnees, colonne.tables = info["type"][:64], tables
                colonne.presente, colonne.vue_le = True, maintenant
                if not colonne.calcul:  # lignes créées avant le choix du calcul
                    colonne.unite, colonne.calcul = colonne.unite or unite_et_calcul(nom)[0], unite_et_calcul(nom)[1]
                modifiees.append(colonne)
        cls.objects.bulk_create(nouvelles)
        # bulk_update n'applique pas auto_now : « modifié le » reste la date de la dernière saisie.
        cls.objects.bulk_update(modifiees, ["type_donnees", "tables", "presente", "vue_le", "unite", "calcul"],
                                batch_size=500)
        vues = {(c.techno, c.nom) for c in nouvelles + modifiees}
        disparues = [c.pk for cle, c in existantes.items() if cle not in vues and c.presente]
        cls.objects.filter(pk__in=disparues).update(presente=False)
        return {"lues": len(vues), "nouvelles": len(nouvelles), "disparues": len(disparues)}
