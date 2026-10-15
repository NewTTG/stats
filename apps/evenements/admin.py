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
    list_display = ["nom", "type", "public", "cree_par", "premier_creneau", "nb_creneaux", "semaines_reference"]
    list_filter = [CreneauxFilter, "type", "public"]
    search_fields = ["nom", "description"]
    ouverture_modale = False  # fiche : page de l'application (ci-dessous), pas une fenêtre de l'administration

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
    """Une seule ligne : pas de liste, une carte de l'onglet « KPI : noms et seuils » (kpi/admin.py) ouvre
    la fiche en fenêtre."""

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not ReglagesAnomalies.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def _page_kpi(self, request):
        from apps.kpi.models import SeuilKpi

        modele_kpi = self.admin_site._registry.get(SeuilKpi)
        if modele_kpi and modele_kpi.has_view_or_change_permission(request):
            return reverse("admin:kpi_seuilkpi_changelist", current_app=self.admin_site.name)
        return None

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            return super().changelist_view(request, extra_context)  # refus de Django
        reglages = ReglagesAnomalies.courant()
        return HttpResponseRedirect(self._page_kpi(request) or reverse(
            "admin:evenements_reglagesanomalies_change", args=[reglages.pk], current_app=self.admin_site.name))

    def response_change(self, request, obj):
        reponse = super().response_change(request, obj)
        page_kpi = self._page_kpi(request)
        if page_kpi and isinstance(reponse, HttpResponseRedirect) and "_continue" not in request.POST:
            return HttpResponseRedirect(page_kpi)  # retour à la carte des réglages
        return reponse
