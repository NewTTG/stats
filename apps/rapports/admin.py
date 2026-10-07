from django.contrib import admin

from .models import Rapport


@admin.register(Rapport)
class RapportAdmin(admin.ModelAdmin):
    list_display = ["cree_le", "titre", "utilisateur", "format", "statut"]
    list_filter = ["statut", "nature", "format"]
    readonly_fields = [f.name for f in Rapport._meta.fields]

    def has_add_permission(self, request):
        return False
