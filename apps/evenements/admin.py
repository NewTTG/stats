from django.contrib import admin
from django.db.models import Exists, OuterRef
from django.http import HttpResponseRedirect
from django.urls import reverse

from .models import Creneau, Evenement, ReglagesAnomalies


class CreneauInline(admin.TabularInline):
    model = Creneau
    extra = 0


class CreneauxFilter(admin.SimpleListFilter):
    """Événements avec ou sans période mémorisée (la période se choisit aussi à l'affichage)."""

    title = "créneaux"
    parameter_name = "creneaux"

    def lookups(self, request, model_admin):
        return [("avec", "Avec période mémorisée"), ("sans", "Sans période mémorisée")]

    def queryset(self, request, queryset):
        a_un_creneau = Exists(Creneau.objects.filter(evenement=OuterRef("pk")))
        if self.value() == "avec":
            return queryset.filter(a_un_creneau)
        if self.value() == "sans":
            return queryset.filter(~a_un_creneau)
        return queryset


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    inlines = [CreneauInline]
    list_display = ["nom", "type", "premier_creneau", "nb_creneaux", "semaines_reference"]
    list_filter = [CreneauxFilter, "type"]
    search_fields = ["nom", "description"]

    # Création et modification : pages de l'application (/evenements/), avec la carte des secteurs.
    # L'administration garde la liste, la suppression en lot et la consultation seule.
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("creneaux")

    def add_view(self, request, form_url="", extra_context=None):
        if self.has_add_permission(request):
            return HttpResponseRedirect(reverse("evenements:nouveau"))
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj is not None and self.has_change_permission(request, obj):
            return HttpResponseRedirect(reverse("evenements:modifier", args=[obj.pk]))
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.display(description="premier créneau")
    def premier_creneau(self, obj):
        creneaux = list(obj.creneaux.all())
        return creneaux[0] if creneaux else "À choisir à l'ouverture"

    @admin.display(description="créneaux")
    def nb_creneaux(self, obj):
        return len(obj.creneaux.all())


@admin.register(ReglagesAnomalies)
class ReglagesAnomaliesAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return super().has_add_permission(request) and not ReglagesAnomalies.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if self.has_view_or_change_permission(request):
            ReglagesAnomalies.courant()
        return super().changelist_view(request, extra_context)
