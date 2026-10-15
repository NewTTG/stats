"""Éditeurs sans code : séries d'un graphique, contenu et visibilité d'un rapport."""
from django import forms
from django.contrib import admin
from django.forms.models import BaseInlineFormSet
from django.urls import reverse
from django.utils.html import format_html

from .catalogue import catalogue
from .composition import graphiques_configures, initialiser_bibliotheque
from .models import Graphique, ModeleRapport, SerieGraphique


def choix_kpis(cat):
    return [(c, f"{'4G' if k.techno == 'LTE' else '3G'} · {k.libelle} ({k.unite})")
            for c, k in sorted(cat.items(), key=lambda item: (item[1].techno, item[1].libelle))]


class SerieForm(forms.ModelForm):
    kpi = forms.ChoiceField(label="Indicateur")

    class Meta:
        model = SerieGraphique
        fields = ["kpi", "type", "axe", "ordre"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kpi"].choices = [("", "Choisir un indicateur…"), *choix_kpis(catalogue())]


class SeriesFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        series = [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not series:
            raise forms.ValidationError("Choisissez au moins un indicateur pour ce graphique.")
        codes = [s["kpi"] for s in series]
        if len(codes) != len(set(codes)):
            raise forms.ValidationError("Un indicateur ne peut figurer qu’une fois dans le graphique.")
        cat = catalogue()
        if len({cat[c].techno for c in codes}) != 1:
            raise forms.ValidationError("Utilisez une seule technologie par graphique (3G ou 4G).")
        for axe in ("gauche", "droite"):
            unites = {cat[s["kpi"]].unite for s in series if s["axe"] == axe}
            # Les compteurs de tentatives, appels et contextes partagent une échelle de nombres.
            nombres = {"nombre", "appels", "tentatives", "contextes", "E-RAB"}
            if unites <= nombres:
                continue
            if len(unites) > 1:
                raise forms.ValidationError(f"L’axe {axe} mélange plusieurs unités ({', '.join(sorted(unites))}). "
                                            "Placez les indicateurs d’une autre unité sur l’autre axe.")


class SerieInline(admin.TabularInline):
    model = SerieGraphique
    form = SerieForm
    formset = SeriesFormSet
    extra = 0
    min_num = 1
    fields = ["kpi", "type", "axe", "ordre"]

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("kpi.view_graphique") or self.has_change_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("kpi.change_graphique")

    def has_add_permission(self, request, obj=None):
        return self.has_change_permission(request, obj) or request.user.has_perm("kpi.add_graphique")

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


class BibliothequeAdmin(admin.ModelAdmin):
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if self.has_change_permission(request) or self.has_add_permission(request):
            initialiser_bibliotheque()
        return super().changeform_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        if self.has_change_permission(request):
            initialiser_bibliotheque()
        return super().changelist_view(request, extra_context)

    def has_delete_permission(self, request, obj=None):
        return False  # retirer un graphique d'un rapport conserve les autres usages


@admin.register(Graphique)
class GraphiqueAdmin(BibliothequeAdmin):
    list_display = ["titre", "theme", "technologie", "nombre_series", "utilisation"]
    list_filter = ["theme"]
    search_fields = ["titre", "series__kpi"]
    fields = ["titre", "theme"]
    inlines = [SerieInline]
    change_form_template = "admin/kpi/graphique/edition.html"
    change_list_template = "admin/kpi/graphique/liste.html"
    save_as = True

    def get_list_display(self, request):
        cat = catalogue()
        rapports = list(ModeleRapport.objects.all())

        @admin.display(description="Technologie")
        def technologie(obj):
            return " / ".join(sorted({"4G" if cat[s.kpi].techno == "LTE" else "3G"
                                      for s in obj.series.all() if s.kpi in cat}))

        @admin.display(description="Rapports")
        def utilisation(obj):
            return ", ".join(r.titre for r in rapports if obj.code in r.graphes) or "À ajouter à un rapport"

        return ["titre", "theme", technologie, "nombre_series", utilisation]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("series")

    @admin.display(description="Technologie")
    def technologie(self, obj):
        cat = catalogue()
        return " / ".join(sorted({"4G" if cat[s.kpi].techno == "LTE" else "3G"
                                  for s in obj.series.all() if s.kpi in cat}))

    @admin.display(description="Séries")
    def nombre_series(self, obj):
        return len(obj.series.all())

    @admin.display(description="Rapports")
    def utilisation(self, obj):
        return ", ".join(r.titre for r in ModeleRapport.objects.all() if obj.code in r.graphes) or "À ajouter à un rapport"

    def render_change_form(self, request, context, *args, **kwargs):
        context["title"] = "Configurer le graphique"
        context["indicateurs_apercu"] = {c: {"nom": k.libelle, "unite": k.unite, "techno": k.techno}
                                         for c, k in catalogue().items()}
        return super().render_change_form(request, context, *args, **kwargs)


class RapportForm(forms.ModelForm):
    graphes = forms.MultipleChoiceField(label="Graphiques du rapport", required=False,
                                       widget=forms.CheckboxSelectMultiple)
    kpis = forms.MultipleChoiceField(label="Indicateurs complémentaires", required=False,
                                    widget=forms.CheckboxSelectMultiple,
                                    help_text="Cartes et courbes individuelles, en complément des graphiques choisis.")

    class Meta:
        model = ModeleRapport
        fields = ["titre", "description", "accueil", "ordre", "graphes", "kpis"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.definitions = graphiques_configures()
        par_code = {g.code: g for g in self.definitions.graphes}
        # Les cases sélectionnées apparaissent dans l'ordre enregistré.
        ordre = self.data.getlist("graphes") if self.is_bound else self.instance.graphes
        codes = list(dict.fromkeys([*ordre, *par_code]))
        self.fields["graphes"].choices = [(c, f"{'4G' if par_code[c].techno == 'LTE' else '3G'} · {par_code[c].titre}")
                                          for c in codes if c in par_code]
        self.fields["kpis"].choices = choix_kpis(catalogue())

    def clean(self):
        cleaned = super().clean()
        for champ in ("graphes", "kpis"):
            if champ in cleaned:
                cleaned[champ] = list(dict.fromkeys(cleaned[champ]))
        if not cleaned.get("graphes") and not cleaned.get("kpis"):
            raise forms.ValidationError("Ajoutez au moins un graphique ou un indicateur au rapport.")
        return cleaned


@admin.register(ModeleRapport)
class ModeleRapportAdmin(BibliothequeAdmin):
    form = RapportForm
    list_display = ["titre", "accueil", "ordre", "contenu", "ouvrir"]
    list_editable = ["accueil", "ordre"]
    search_fields = ["titre", "description"]
    list_filter = ["accueil"]
    change_form_template = "admin/kpi/modelerapport/edition.html"
    change_list_template = "admin/kpi/modelerapport/liste.html"
    fields = ["titre", "description", "accueil", "ordre", "graphes", "kpis"]
    save_as = True

    @admin.display(description="Contenu")
    def contenu(self, obj):
        return f"{len(obj.graphes)} graphiques · {len(obj.kpis)} indicateurs complémentaires"

    @admin.display(description="Consulter")
    def ouvrir(self, obj):
        return format_html('<a href="{}?q=&intention={}&periode=7j">Voir le rapport ↗</a>',
                           reverse("kpi:requete"), obj.code)

    def render_change_form(self, request, context, *args, **kwargs):
        context["title"] = "Composer le rapport"
        context["graphiques_details"] = {g.code: {"theme": self.form_theme(g), "series": len(g.series)}
                                        for g in graphiques_configures().graphes}
        return super().render_change_form(request, context, *args, **kwargs)

    @staticmethod
    def form_theme(g):
        from .models import THEMES_GRAPHES
        return dict(THEMES_GRAPHES)[g.theme]
