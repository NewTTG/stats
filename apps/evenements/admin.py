import re

from django import forms
from django.contrib import admin
from django.db.models import Exists, OuterRef

from .models import Creneau, Evenement, ReglagesAnomalies

_SEPARATEURS = re.compile(r"[\s,;]+")


class ListeTexte(forms.CharField):
    """Liste JSON saisie comme texte (virgules, espaces ou retours à la ligne)."""

    widget = forms.Textarea(attrs={"rows": 3, "cols": 80})

    def prepare_value(self, value):
        return ", ".join(value) if isinstance(value, list) else value

    def to_python(self, value):
        return [v for v in _SEPARATEURS.split(value or "") if v]


class EvenementForm(forms.ModelForm):
    sites = ListeTexte(required=False, help_text="Codes site : toutes leurs cellules sont incluses.")
    secteurs = ListeTexte(required=False, help_text="Codes secteur (code site + n°), ex. ZIZ1792.")
    cellules = ListeTexte(required=False, help_text="Noms de cellules LTE ou WCDMA, ex. ZIZe3, ZIZ179C.")
    kpis = ListeTexte(required=False, label="KPI analysés", help_text="Codes KPI ; vide = tous.")

    class Meta:
        model = Evenement
        fields = "__all__"

    def clean_kpis(self):
        from apps.kpi.catalogue import catalogue_yaml

        inconnus = [c for c in self.cleaned_data["kpis"] if c not in catalogue_yaml()]
        if inconnus:
            raise forms.ValidationError(f"KPI inconnus : {', '.join(inconnus)}")
        return self.cleaned_data["kpis"]


class CreneauInline(admin.TabularInline):
    model = Creneau
    extra = 1


class CreneauxFilter(admin.SimpleListFilter):
    """« Sans créneau » : événements à compléter (lien du tableau de bord de l'administration)."""

    title = "créneaux"
    parameter_name = "creneaux"

    def lookups(self, request, model_admin):
        return [("avec", "Avec créneau"), ("sans", "Sans créneau (à compléter)")]

    def queryset(self, request, queryset):
        a_un_creneau = Exists(Creneau.objects.filter(evenement=OuterRef("pk")))
        if self.value() == "avec":
            return queryset.filter(a_un_creneau)
        if self.value() == "sans":
            return queryset.filter(~a_un_creneau)
        return queryset


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    form = EvenementForm
    inlines = [CreneauInline]
    list_display = ["nom", "type", "premier_creneau", "nb_creneaux", "semaines_reference"]
    list_filter = [CreneauxFilter, "type"]
    search_fields = ["nom", "description"]
    readonly_fields = ["resolution", "cree_par", "cree_le"]
    fieldsets = [
        (None, {"fields": ["nom", "type", "description"]}),
        ("Cellules concernées", {"fields": ["sites", "secteurs", "cellules", "resolution"]}),
        ("Analyse", {"fields": ["semaines_reference", "kpis"]}),
        ("Suivi", {"fields": ["cree_par", "cree_le"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("creneaux")

    def save_model(self, request, obj, form, change):
        if not obj.cree_par_id:
            obj.cree_par = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="premier créneau")
    def premier_creneau(self, obj):
        creneaux = list(obj.creneaux.all())
        return creneaux[0] if creneaux else "— à compléter —"

    @admin.display(description="créneaux")
    def nb_creneaux(self, obj):
        return len(obj.creneaux.all())

    @admin.display(description="cellules retenues")
    def resolution(self, obj):
        if not obj.pk:
            return "—"
        lte, wcdma = obj.noms_cellules("LTE"), obj.noms_cellules("WCDMA")
        texte = f"{len(lte)} LTE, {len(wcdma)} WCDMA"
        inconnues = obj.cellules_inconnues()
        if inconnues:
            texte += f" — absentes du référentiel : {', '.join(inconnues)}"
        return texte


@admin.register(ReglagesAnomalies)
class ReglagesAnomaliesAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not ReglagesAnomalies.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        ReglagesAnomalies.courant()
        return super().changelist_view(request, extra_context)
