import logging
from functools import lru_cache

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import path, reverse

from .catalogue import LIBELLES_CATEGORIE, catalogue_yaml, colonnes_utilisees
from .models import ColonneKpi, SeuilKpi
from .source import BaseKpiNonConfiguree

journal = logging.getLogger(__name__)

SENS = {"haut_est_mieux": "↑ plus haut est mieux", "bas_est_mieux": "↓ plus bas est mieux"}


@admin.register(SeuilKpi)
class SeuilKpiAdmin(admin.ModelAdmin):
    list_display = ["code", "libelle", "techno", "unite", "sens", "alerte", "critique", "modifie_le"]
    list_editable = ["alerte", "critique"]
    list_filter = []
    readonly_fields = ["code", "modifie_le"]
    fields = ["code", "alerte", "critique", "modifie_le"]
    actions = ["retablir"]

    def changelist_view(self, request, extra_context=None):
        if self.has_view_or_change_permission(request):
            SeuilKpi.synchroniser()
        return super().changelist_view(request, extra_context)

    def has_add_permission(self, request):
        return False

    def _kpi(self, obj):
        return catalogue_yaml().get(obj.code)

    @admin.display(description="libellé")
    def libelle(self, obj):
        return k.libelle if (k := self._kpi(obj)) else "Absent du catalogue"

    @admin.display(description="techno")
    def techno(self, obj):
        return k.techno if (k := self._kpi(obj)) else ""

    @admin.display(description="unité")
    def unite(self, obj):
        return k.unite if (k := self._kpi(obj)) else ""

    @admin.display(description="sens")
    def sens(self, obj):
        return SENS.get(k.sens, "") if (k := self._kpi(obj)) else ""

    @admin.action(description="Rétablir les seuils du catalogue YAML")
    def retablir(self, request, queryset):
        cat = catalogue_yaml()
        for s in queryset:
            if s.code in cat:
                s.alerte, s.critique = cat[s.code].seuils.alerte, cat[s.code].seuils.critique
                s.save()
        messages.success(request, f"{queryset.count()} seuil(s) rétabli(s).")


@lru_cache
def usages_colonnes() -> dict[tuple[str, str], list[str]]:
    """(techno, colonne) -> libellés des KPI du catalogue YAML dont les formules la citent."""
    usages = {}
    for k in catalogue_yaml().values():
        for nom in colonnes_utilisees(k):
            usages.setdefault((k.techno, nom), []).append(k.libelle)
    return usages


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
        return [("kpi", "Utilisée par un KPI"), ("libre", "Utilisée par aucun KPI")]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        filtre = Q(pk__in=[])
        for techno, nom in usages_colonnes():
            filtre |= Q(techno=techno, nom=nom)
        return queryset.filter(filtre) if self.value() == "kpi" else queryset.exclude(filtre)


class ColonneListeForm(forms.ModelForm):
    """Saisie dans la liste : champs resserrés pour garder une ligne par colonne."""

    class Meta:
        model = ColonneKpi
        fields = ["libelle", "categorie", "description"]
        widgets = {
            "libelle": forms.TextInput(attrs={"size": 26, "placeholder": "Nom affiché"}),
            "description": forms.Textarea(attrs={"rows": 1, "cols": 36, "placeholder": "Description"}),
        }


@admin.register(ColonneKpi)
class ColonneKpiAdmin(admin.ModelAdmin):
    list_display = ["nom", "donnees", "libelle", "categorie", "description", "utilisee_par"]
    list_display_links = ["nom"]
    sortable_by = ["nom", "libelle", "categorie"]
    list_editable = ["libelle", "categorie", "description"]
    list_filter = ["techno", CategorieFilter, NommageFilter, UsageFilter, "presente"]
    search_fields = ["nom", "libelle", "description"]
    list_per_page = 100
    readonly_fields = ["nom", "techno", "tables", "type_donnees", "utilisee_par", "presente", "vue_le", "modifie_le"]
    fieldsets = [
        (None, {"fields": ["nom", "techno", "tables", "type_donnees", "utilisee_par"]}),
        ("Pour les utilisateurs", {"fields": ["libelle", "categorie", "description"]}),
        ("Suivi", {"fields": ["presente", "vue_le", "modifie_le"]}),
    ]

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
        return ", ".join(usages_colonnes().get((obj.techno, obj.nom), [])) or "—"

    @admin.display(description="données")
    def donnees(self, obj):
        return f"{obj.techno} · {obj.tables if obj.presente else 'absente de la base'}"
