from django.contrib import admin

from .models import JournalAudit, Perimetre


@admin.register(Perimetre)
class PerimetreAdmin(admin.ModelAdmin):
    list_display = ["nom"]
    filter_horizontal = ["utilisateurs", "groupes"]


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    list_display = ["date", "utilisateur", "action"]
    list_filter = ["action"]
    readonly_fields = ["date", "utilisateur", "action", "requete"]
