from django.contrib import admin

from .models import Cellule, ImportReferentiel, Secteur, Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["code_site", "nom", "trigramme", "commune", "region", "nb_secteurs", "bascule_4_secteurs"]
    list_filter = ["region", "commune"]
    search_fields = ["code_site", "nom", "trigramme", "nom_lte", "nom_wcdma"]


@admin.register(Secteur)
class SecteurAdmin(admin.ModelAdmin):
    list_display = ["code", "site", "numero"]
    search_fields = ["code", "site__nom"]


@admin.register(Cellule)
class CelluleAdmin(admin.ModelAdmin):
    list_display = ["nom", "techno", "secteur", "porteuse", "secteur_avant"]
    list_filter = ["techno"]
    search_fields = ["nom"]


@admin.register(ImportReferentiel)
class ImportReferentielAdmin(admin.ModelAdmin):
    list_display = ["date", "fichier", "auteur", "nb_sites", "nb_secteurs"]
    readonly_fields = [f.name for f in ImportReferentiel._meta.fields] + ["ajouts", "suppressions", "anomalies"]

    def has_add_permission(self, request):
        return False  # historique tenu par « manage.py import_referentiel » (rappel sur le tableau de bord)
