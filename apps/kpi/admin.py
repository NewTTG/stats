import logging
from functools import lru_cache

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from .catalogue import LIBELLES_CATEGORIE, catalogue_yaml, colonnes_utilisees
from .models import SENS, ColonneKpi, SeuilKpi
from .source import BaseKpiNonConfiguree

journal = logging.getLogger(__name__)

class TechnoKpiFilter(admin.SimpleListFilter):
    title = "techno"
    parameter_name = "techno"

    def lookups(self, request, model_admin):
        return ColonneKpi.TECHNOS

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        codes = [c for c, k in catalogue_yaml().items() if k.techno == self.value()]
        return queryset.filter(code__in=codes)


class KpiListeForm(forms.ModelForm):
    """Saisie dans la liste des KPI : nom obligatoire, champs resserrés."""

    class Meta:
        model = SeuilKpi
        fields = ["libelle", "categorie", "description", "alerte", "critique"]
        widgets = {
            "libelle": forms.TextInput(attrs={"size": 26, "placeholder": "Nom affiché"}),
            "description": forms.Textarea(attrs={"rows": 1, "cols": 30, "placeholder": "Description"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["libelle"].required = self.fields["categorie"].required = True


class KpiForm(KpiListeForm):
    class Meta(KpiListeForm.Meta):
        widgets = {}


@admin.register(SeuilKpi)
class SeuilKpiAdmin(admin.ModelAdmin):
    form = KpiForm
    list_display = ["code", "libelle", "categorie", "description", "unite", "alerte", "critique"]
    list_display_links = ["code"]
    list_editable = ["libelle", "categorie", "description", "alerte", "critique"]
    list_filter = [TechnoKpiFilter, "categorie"]
    search_fields = ["code", "libelle", "description"]
    sortable_by = ["code", "libelle", "categorie"]
    list_per_page = 200
    readonly_fields = ["code", "nom_catalogue", "techno", "unite", "sens", "formule", "colonnes", "modifie_le"]
    fieldsets = [
        (None, {"fields": ["code", "techno", "unite", "sens", "formule", "colonnes"]}),
        ("Pour les utilisateurs", {"fields": ["libelle", "nom_catalogue", "categorie", "description"]}),
        ("Seuils", {"fields": ["alerte", "critique"]}),
        ("Suivi", {"fields": ["modifie_le"]}),
    ]
    actions = ["retablir"]

    def changelist_view(self, request, extra_context=None):
        if self.has_view_or_change_permission(request):
            SeuilKpi.synchroniser()
        contexte = {"title": "KPI : noms et seuils", "titre_page": "KPI : noms et seuils",
                    "detection": self._detection(request), **(extra_context or {})}
        return super().changelist_view(request, contexte)

    def _detection(self, request):
        """Carte « Détection d'anomalies » : réglages (une seule ligne) et lien de modification, selon les droits."""
        from apps.evenements.models import ReglagesAnomalies

        modele_admin = self.admin_site._registry.get(ReglagesAnomalies)
        if modele_admin is None or not modele_admin.has_view_or_change_permission(request):
            return None
        reglages = ReglagesAnomalies.courant()
        return {"reglages": reglages, "modifiable": modele_admin.has_change_permission(request, reglages),
                "url": reverse("admin:evenements_reglagesanomalies_change", args=[reglages.pk],
                               current_app=self.admin_site.name)}

    def get_changelist_form(self, request, **kwargs):
        return KpiListeForm

    def has_add_permission(self, request):
        return False

    def _kpi(self, obj):
        return catalogue_yaml().get(obj.code)

    @admin.display(description="nom dans le catalogue")
    def nom_catalogue(self, obj):
        return k.libelle if (k := self._kpi(obj)) else "Absent du catalogue"

    @admin.display(description="techno")
    def techno(self, obj):
        return k.techno if (k := self._kpi(obj)) else ""

    @admin.display(description="unité")
    def unite(self, obj):
        return k.unite if (k := self._kpi(obj)) else ""

    @admin.display(description="sens")
    def sens(self, obj):
        return dict(SENS).get(k.sens, "") if (k := self._kpi(obj)) else ""

    @admin.display(description="formule")
    def formule(self, obj):
        return k.formule if (k := self._kpi(obj)) else ""

    @admin.display(description="colonnes de la base")
    def colonnes(self, obj):
        if (k := self._kpi(obj)) is None:
            return ""
        noms = sorted({n for c in (k.composants or [k]) for n in colonnes_utilisees(c)})
        lignes = ColonneKpi.objects.filter(techno=k.techno, nom__in=noms)
        liens = {c.nom: reverse("admin:kpi_colonnekpi_change", args=[c.pk], current_app=self.admin_site.name)
                 for c in lignes}
        return format_html_join(", ", "{}", ((format_html('<a href="{}">{}</a>', liens[n], n) if n in liens else n,)
                                             for n in noms)) or "—"

    @admin.action(description="Rétablir les valeurs du catalogue YAML (nom, catégorie, description, seuils)")
    def retablir(self, request, queryset):
        cat = catalogue_yaml()
        for s in queryset:
            if s.code in cat:
                s.retablir(cat[s.code])
                s.save()
        messages.success(request, f"{queryset.count()} KPI rétabli(s).")


@lru_cache
def usages_colonnes() -> dict[tuple[str, str], list[str]]:
    """(techno, colonne) -> codes des KPI du catalogue YAML dont les formules la citent."""
    usages = {}
    for k in catalogue_yaml().values():
        for nom in colonnes_utilisees(k):
            usages.setdefault((k.techno, nom), []).append(k.code)
    return usages


def liens_kpi(admin_site) -> dict[str, str]:
    """Code -> lien HTML vers la fiche du KPI (nom affiché réglé dans l'admin)."""
    SeuilKpi.synchroniser()
    return {s.code: format_html('<a href="{}">{}</a>', reverse("admin:kpi_seuilkpi_change", args=[s.pk],
                                                              current_app=admin_site.name), s.libelle or s.code)
            for s in SeuilKpi.objects.all()}


class CategorieFilter(admin.SimpleListFilter):
    title = "catégorie"
    parameter_name = "categorie"

    def lookups(self, request, model_admin):
        return [("aucune", "Non classée"), *LIBELLES_CATEGORIE.items()]

    def queryset(self, request, queryset):
        if self.value() == "aucune":
            return queryset.filter(categorie="")
        return queryset.filter(categorie=self.value()) if self.value() else queryset


class NommageFilter(admin.SimpleListFilter):
    title = "nom affiché"
    parameter_name = "nommee"

    def lookups(self, request, model_admin):
        return [("non", "À nommer"), ("oui", "Nommée")]

    def queryset(self, request, queryset):
        if self.value() == "non":
            return queryset.filter(libelle="")
        return queryset.exclude(libelle="") if self.value() == "oui" else queryset


class UsageFilter(admin.SimpleListFilter):
    title = "usage"
    parameter_name = "usage"

    def lookups(self, request, model_admin):
        return [("kpi", "Utilisée par un KPI"), ("libre", "Utilisée par aucun KPI"),
                ("proposee", "Proposée aux utilisateurs")]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        if self.value() == "proposee":
            return queryset.filter(proposee=True)
        filtre = Q(pk__in=[])
        for techno, nom in usages_colonnes():
            filtre |= Q(techno=techno, nom=nom)
        return queryset.filter(filtre) if self.value() == "kpi" else queryset.exclude(filtre)


class ColonneListeForm(forms.ModelForm):
    """Saisie dans la liste : champs resserrés pour garder une ligne par colonne."""

    class Meta:
        model = ColonneKpi
        fields = ["libelle", "categorie", "description", "proposee", "calcul"]
        widgets = {
            "libelle": forms.TextInput(attrs={"size": 26, "placeholder": "Nom affiché"}),
            "description": forms.Textarea(attrs={"rows": 1, "cols": 36, "placeholder": "Description"}),
        }


@admin.register(ColonneKpi)
class ColonneKpiAdmin(admin.ModelAdmin):
    list_display = ["nom", "donnees", "libelle", "categorie", "description", "proposee", "calcul", "utilisee_par"]
    list_display_links = ["nom"]
    sortable_by = ["nom", "libelle", "categorie", "proposee"]
    list_editable = ["libelle", "categorie", "description", "proposee", "calcul"]
    list_filter = ["techno", CategorieFilter, NommageFilter, UsageFilter, "presente"]
    search_fields = ["nom", "libelle", "description"]
    list_per_page = 100
    readonly_fields = ["nom", "techno", "tables", "type_donnees", "utilisee_par", "presente", "vue_le", "modifie_le"]
    fieldsets = [
        (None, {"fields": ["nom", "techno", "tables", "type_donnees", "utilisee_par"]}),
        ("Pour les utilisateurs", {"fields": ["libelle", "categorie", "description"]}),
        ("Indicateur dans l'application", {
            "fields": ["proposee", "calcul", "unite", "sens"],
            "description": "Une colonne proposée devient un indicateur que les utilisateurs choisissent dans "
                           "l'application, sous son nom affiché, à côté des KPI du catalogue."}),
        ("Suivi", {"fields": ["presente", "vue_le", "modifie_le"]}),
    ]

    def get_list_display(self, request):
        # Liens vers les KPI lus une seule fois par page (et non une requête par ligne).
        liens = liens_kpi(self.admin_site)

        @admin.display(description="utilisée par")
        def utilisee_par(obj):
            codes = usages_colonnes().get((obj.techno, obj.nom), [])
            return format_html_join(", ", "{}", ((liens.get(c, c),) for c in codes)) or "—"

        return [utilisee_par if nom == "utilisee_par" else nom for nom in self.list_display]

    def has_add_permission(self, request):
        return False  # les colonnes viennent de la base KPI (« Relire la base KPI »)

    def get_changelist_form(self, request, **kwargs):
        return ColonneListeForm

    def get_urls(self):
        return [path("relire/", self.admin_site.admin_view(self.relire_view),
                     name="kpi_colonnekpi_relire")] + super().get_urls()

    def _relire(self, request):
        try:
            bilan = ColonneKpi.synchroniser()
        except BaseKpiNonConfiguree:
            messages.warning(request, "Base KPI non configurée : colonnes non lues.")
        except Exception as e:  # base injoignable, droits insuffisants...
            journal.exception("Lecture des colonnes de la base KPI impossible")
            messages.error(request, f"Lecture de la base KPI impossible : {e.__class__.__name__}.")
        else:
            texte = f"{bilan['lues']} colonne(s) lue(s) dans la base KPI"
            if bilan["nouvelles"]:
                texte += f", {bilan['nouvelles']} nouvelle(s)"
            if bilan["disparues"]:
                texte += f", {bilan['disparues']} absente(s) désormais"
            messages.success(request, texte + ".")

    def relire_view(self, request):
        if request.method != "POST" or not self.has_change_permission(request):
            raise PermissionDenied
        self._relire(request)
        return HttpResponseRedirect(reverse("admin:kpi_colonnekpi_changelist", current_app=self.admin_site.name))

    def changelist_view(self, request, extra_context=None):
        # Première ouverture : lecture automatique ; ensuite, à la demande (base distante, parfois lente).
        if request.method == "GET" and self.has_change_permission(request) and not ColonneKpi.objects.exists():
            self._relire(request)
        colonnes = ColonneKpi.objects.filter(presente=True)
        contexte = {
            "title": "Colonnes de la base KPI", "titre_page": "Colonnes de la base KPI",
            "etat": {
                "lte": colonnes.filter(techno="LTE").count(),
                "wcdma": colonnes.filter(techno="WCDMA").count(),
                "a_nommer": colonnes.filter(libelle="").count(),
                "non_classees": colonnes.filter(categorie="").count(),
                "absentes": ColonneKpi.objects.filter(presente=False).count(),
                "vue_le": ColonneKpi.objects.order_by("-vue_le").values_list("vue_le", flat=True).first(),
            },
            "peut_relire": self.has_change_permission(request),
            **(extra_context or {}),
        }
        return super().changelist_view(request, contexte)

    @admin.display(description="utilisée par")
    def utilisee_par(self, obj):
        liens = liens_kpi(self.admin_site)
        codes = usages_colonnes().get((obj.techno, obj.nom), [])
        return format_html_join(", ", "{}", ((liens.get(c, c),) for c in codes)) or "—"

    @admin.display(description="données")
    def donnees(self, obj):
        return f"{obj.techno} · {obj.tables if obj.presente else 'absente de la base'}"
