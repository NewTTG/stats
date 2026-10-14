from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from .models import Cellule, ImportReferentiel, Secteur, Site
from .rechargement import (RechargementImpossible, base_kpi_disponible, fichier_courant, peut_recharger,
                           recharger)


class RattachementFilter(admin.SimpleListFilter):
    """Cellules sans secteur : noms non reconnus ou trigramme absent de Site_File."""

    title = "rattachement"
    parameter_name = "rattachement"

    def lookups(self, request, model_admin):
        return [("oui", "Rattachées à un secteur"), ("non", "Non rattachées")]

    def queryset(self, request, queryset):
        if self.value() == "oui":
            return queryset.filter(secteur__isnull=False)
        if self.value() == "non":
            return queryset.filter(secteur__isnull=True)
        return queryset


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["code_site", "nom", "trigramme", "commune", "region", "nb_secteurs", "bascule_4_secteurs"]
    list_filter = ["region", "commune"]
    search_fields = ["code_site", "nom", "trigramme", "nom_lte", "nom_wcdma"]
    search_help_text = "Code site, nom, trigramme ou nom 3G / 4G."
    list_per_page = 50


@admin.register(Secteur)
class SecteurAdmin(admin.ModelAdmin):
    list_display = ["code", "site", "numero", "nb_cellules"]
    list_select_related = ["site"]
    search_fields = ["code", "site__nom"]
    search_help_text = "Code secteur ou nom du site."
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(nb=Count("cellules"))

    @admin.display(description="cellules", ordering="nb")
    def nb_cellules(self, obj):
        return obj.nb


@admin.register(Cellule)
class CelluleAdmin(admin.ModelAdmin):
    list_display = ["nom", "techno", "site", "secteur", "porteuse", "secteur_avant"]
    list_filter = ["techno", RattachementFilter]
    list_select_related = ["secteur__site", "secteur_avant"]
    search_fields = ["nom", "secteur__site__code_site"]
    search_help_text = "Nom de cellule ou code site."
    list_per_page = 50

    @admin.display(description="site", ordering="secteur__site__code_site")
    def site(self, obj):
        return obj.secteur.site.code_site if obj.secteur else "—"


class RechargementForm(forms.Form):
    fichier = forms.FileField(
        label="Nouvelle version du xlsx", required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
        help_text="Facultatif : sans fichier, le xlsx de référence actuel est relu.")
    cellules_kpi = forms.BooleanField(
        label="Mettre à jour les cellules depuis la base KPI", required=False,
        help_text="Toutes les cellules de l'historique journalier ; décoché, les cellules restent inchangées.")
    bascules = forms.BooleanField(
        label="Détecter les passages de 3 à 4 secteurs", required=False,
        help_text="Renseigne seulement les dates encore vides.")

    def clean_fichier(self):
        fichier = self.cleaned_data["fichier"]
        if fichier and not fichier.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Fichier .xlsx attendu.")
        return fichier


def _liste(valeurs, vide="Aucun"):
    if not valeurs:
        return vide
    return format_html('<ul class="liste-import">{}</ul>', format_html_join("", "<li>{}</li>", ((v,) for v in valeurs)))


@admin.register(ImportReferentiel)
class ImportReferentielAdmin(admin.ModelAdmin):
    list_display = ["date", "fichier", "auteur", "nb_sites", "nb_secteurs", "nb_ajouts", "nb_suppressions",
                    "nb_anomalies"]
    list_select_related = ["auteur"]
    list_per_page = 30
    actions = None  # historique conservé : pas de suppression groupée
    fields = ["date", "fichier", "auteur", "nb_sites", "nb_secteurs", "liste_ajouts", "liste_suppressions",
              "liste_anomalies"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False  # imports créés par le rechargement (ci-dessous) ou « manage.py import_referentiel »

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="ajouts")
    def nb_ajouts(self, obj):
        return len(obj.ajouts)

    @admin.display(description="suppressions")
    def nb_suppressions(self, obj):
        return len(obj.suppressions)

    @admin.display(description="anomalies")
    def nb_anomalies(self, obj):
        return len(obj.anomalies)

    @admin.display(description="ajouts (sites puis secteurs)")
    def liste_ajouts(self, obj):
        return _liste(obj.ajouts)

    @admin.display(description="suppressions (sites puis secteurs)")
    def liste_suppressions(self, obj):
        return _liste(obj.suppressions, "Aucune")

    @admin.display(description="anomalies")
    def liste_anomalies(self, obj):
        return _liste(obj.anomalies, "Aucune")

    def get_urls(self):
        return [path("recharger/", self.admin_site.admin_view(self.recharger_view),
                     name="referentiel_importreferentiel_recharger")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        kpi = base_kpi_disponible()
        fichier = fichier_courant()
        form = RechargementForm(initial={"cellules_kpi": kpi, "bascules": kpi})
        if not kpi:
            form.fields["cellules_kpi"].disabled = form.fields["bascules"].disabled = True
        contexte = {
            "title": "Référentiel réseau", "titre_page": "Référentiel réseau",
            "etat": {
                "sites": Site.objects.count(),
                "secteurs": Secteur.objects.count(),
                "cellules_lte": Cellule.objects.filter(techno="LTE").count(),
                "cellules_wcdma": Cellule.objects.filter(techno="WCDMA").count(),
                "non_rattachees": Cellule.objects.filter(secteur__isnull=True).count(),
                "quatre_secteurs": Site.objects.filter(bascule_4_secteurs__isnull=False).count(),
                "dernier": ImportReferentiel.objects.select_related("auteur").first(),
            },
            "fichier_courant": fichier.name if fichier else None,
            "base_kpi": kpi,
            "peut_recharger": peut_recharger(request.user),
            "form_rechargement": form,
            **(extra_context or {}),
        }
        return super().changelist_view(request, contexte)

    def recharger_view(self, request):
        liste = reverse("admin:referentiel_importreferentiel_changelist", current_app=self.admin_site.name)
        if request.method != "POST" or not peut_recharger(request.user):
            raise PermissionDenied
        form = RechargementForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, " ".join(e for erreurs in form.errors.values() for e in erreurs))
            return HttpResponseRedirect(liste)
        donnees = form.cleaned_data
        try:
            imp, bascules = recharger(request.user, donnees["fichier"], donnees["cellules_kpi"], donnees["bascules"])
        except RechargementImpossible as e:
            messages.error(request, str(e))
            return HttpResponseRedirect(liste)
        detail = reverse("admin:referentiel_importreferentiel_change", args=[imp.pk],
                         current_app=self.admin_site.name)
        messages.success(request, format_html(
            "Référentiel rechargé depuis {} : {} sites, {} secteurs, {} ajouts, {} suppressions. "
            '<a href="{}">Voir le détail</a>', imp.fichier, imp.nb_sites, imp.nb_secteurs, len(imp.ajouts),
            len(imp.suppressions), detail))
        if bascules is not None:
            messages.info(request, f"Passages à 4 secteurs : {bascules} nouvelle(s) date(s) renseignée(s).")
        if imp.anomalies:
            messages.warning(request, f"{len(imp.anomalies)} anomalie(s) à examiner dans le détail de l'import.")
        return HttpResponseRedirect(liste)
