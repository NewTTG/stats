from django.contrib import admin, messages

from .catalogue import catalogue_yaml
from .models import SeuilKpi

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
        SeuilKpi.synchroniser()
        return super().changelist_view(request, extra_context)

    def has_add_permission(self, request):
        return False

    def _kpi(self, obj):
        return catalogue_yaml().get(obj.code)

    @admin.display(description="libellé")
    def libelle(self, obj):
        return k.libelle if (k := self._kpi(obj)) else "— absent du catalogue —"

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
