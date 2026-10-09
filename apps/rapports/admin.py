from django.contrib import admin

from .models import Rapport, RapportPlanifie


@admin.register(Rapport)
class RapportAdmin(admin.ModelAdmin):
    list_display = ["cree_le", "titre", "utilisateur", "format", "statut"]
    list_filter = ["statut", "nature", "format"]
    readonly_fields = [f.name for f in Rapport._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(RapportPlanifie)
class RapportPlanifieAdmin(admin.ModelAdmin):
    list_display = ["titre", "utilisateur", "periode", "format", "frequence", "actif", "prochain_lancement"]
    list_filter = ["frequence", "actif", "format"]
    readonly_fields = ["prochain_lancement", "dernier_lancement", "cree_le"]

    def save_model(self, request, obj, form, change):
        obj.planifier()
        super().save_model(request, obj, form, change)
