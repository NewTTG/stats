import re

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import path, reverse

from apps.kpi.catalogue import catalogue_yaml, kpis_principaux
from apps.referentiel.models import Cellule, Site

from .models import Creneau, Evenement, ReglagesAnomalies

_SEPARATEURS = re.compile(r"[\s,;]+")
LIBELLES_TECHNO = {"LTE": "4G (LTE)", "WCDMA": "3G (WCDMA)"}
LIBELLES_CATEGORIE = {"debit": "Débit", "trafic": "Trafic", "accessibilite": "Accessibilité",
                      "retainability": "Coupures", "congestion": "Congestion", "mobilite": "Mobilité",
                      "disponibilite": "Disponibilité"}


class ListeCodes(forms.CharField):
    """Liste JSON transmise en champ caché (codes séparés par des virgules), tenue par la carte."""

    widget = forms.HiddenInput

    def prepare_value(self, value):
        return ",".join(value) if isinstance(value, list) else value

    def to_python(self, value):
        return list(dict.fromkeys(v for v in _SEPARATEURS.split(value or "") if v))


class EvenementForm(forms.ModelForm):
    sites = ListeCodes(required=False)
    secteurs = ListeCodes(required=False)
    cellules = ListeCodes(required=False)
    kpis = forms.MultipleChoiceField(required=False, label="KPI analysés", widget=forms.CheckboxSelectMultiple)
    kpis_choisis = forms.BooleanField(required=False, label="Choisir les KPI analysés")

    class Meta:
        model = Evenement
        fields = ["nom", "type", "description", "sites", "secteurs", "cellules", "semaines_reference", "kpis"]
        widgets = {
            "nom": forms.TextInput(attrs={"placeholder": "Ex. Foire de Bourail 2026", "autocomplete": "off"}),
            "type": forms.TextInput(attrs={"placeholder": "Concert, Foire, Journée…", "list": "types-evenement",
                                           "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Facultatif : lieu, organisateur, affluence attendue…"}),
            "semaines_reference": forms.NumberInput(attrs={"min": 1, "max": 12}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kpis"].choices = [(code, k.libelle) for code, k in catalogue_yaml().items()]
        self.fields["kpis_choisis"].initial = bool(self.instance.kpis)

    def clean(self):
        donnees = super().clean()
        if not any(donnees.get(champ) for champ in ("sites", "secteurs", "cellules")):
            self.add_error("sites", "Choisissez au moins un site, un secteur ou une cellule.")
        if not donnees.get("kpis_choisis"):
            donnees["kpis"] = []  # liste vide : l'analyse retient les KPI principaux
        elif not donnees.get("kpis") and "kpis" not in self.errors:
            self.add_error("kpis", "Cochez au moins un KPI, ou revenez aux KPI principaux.")
        return donnees


class CreneauForm(forms.ModelForm):
    """Début et fin en un seul champ date + heure (sélecteur du navigateur), heure de Nouméa."""

    debut = forms.DateTimeField(label="Début", widget=forms.DateTimeInput(
        attrs={"type": "datetime-local", "step": 60}, format="%Y-%m-%dT%H:%M"))
    fin = forms.DateTimeField(label="Fin", widget=forms.DateTimeInput(
        attrs={"type": "datetime-local", "step": 60}, format="%Y-%m-%dT%H:%M"))

    class Meta:
        model = Creneau
        fields = ["debut", "fin"]


class CreneauInline(admin.TabularInline):
    model = Creneau
    form = CreneauForm

    def get_extra(self, request, obj=None, **kwargs):
        # Une ligne vide tant que l'événement n'a aucun créneau.
        return 0 if obj and obj.creneaux.exists() else 1


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


def reseau_pour_carte() -> dict:
    """Sites (coordonnées), secteurs (azimut) et cellules du référentiel, pour la carte de sélection."""
    sites = {s.pk: {"code": s.code_site, "nom": s.nom, "commune": s.commune, "trigramme": s.trigramme,
                    "lat": s.latitude, "lon": s.longitude, "secteurs": []}
             for s in Site.objects.order_by("code_site")}
    secteurs, libres = {}, []
    for c in Cellule.objects.select_related("secteur").order_by("secteur__numero", "techno", "porteuse", "nom"):
        if c.secteur is None or c.secteur.site_id not in sites:
            libres.append([c.nom, c.techno])
            continue
        if c.secteur_id not in secteurs:
            secteurs[c.secteur_id] = {"code": c.secteur.code, "numero": c.secteur.numero,
                                      "azimut": c.secteur.azimut, "cellules": []}
            sites[c.secteur.site_id]["secteurs"].append(secteurs[c.secteur_id])
        secteurs[c.secteur_id]["cellules"].append([c.nom, c.techno])
    return {"sites": [s for s in sites.values() if s["secteurs"]], "libres": libres}


def groupes_kpi(coches: list[str]) -> list[dict]:
    """KPI du catalogue par techno puis catégorie (cases à cocher du formulaire)."""
    cat = catalogue_yaml()
    groupes = {}
    for code, k in cat.items():
        techno = groupes.setdefault(k.techno, {"titre": LIBELLES_TECHNO[k.techno], "categories": {}})
        techno["categories"].setdefault(LIBELLES_CATEGORIE.get(k.categorie, k.categorie), []).append(
            {"code": code, "libelle": k.libelle, "coche": code in coches, "cause": bool(k.decomposition_de)})
    return [{"titre": g["titre"], "categories": list(g["categories"].items())} for g in groupes.values()]


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    form = EvenementForm
    inlines = [CreneauInline]
    list_display = ["nom", "type", "premier_creneau", "nb_creneaux", "semaines_reference"]
    list_filter = [CreneauxFilter, "type"]
    search_fields = ["nom", "description"]
    fields = ["nom", "type", "description", "sites", "secteurs", "cellules", "semaines_reference", "kpis",
              "kpis_choisis"]
    # Formulaire en pleine page (carte, créneaux, KPI) : templates/admin/evenements/evenement/edition.html.
    template_edition = "admin/evenements/evenement/edition.html"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("creneaux")

    def get_urls(self):
        return [path("reseau.json", self.admin_site.admin_view(self.reseau_json),
                     name="evenements_evenement_reseau")] + super().get_urls()

    def reseau_json(self, request):
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise PermissionDenied
        return JsonResponse(reseau_pour_carte(), json_dumps_params={"ensure_ascii": False, "separators": (",", ":")})

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        formulaire = context["adminform"].form
        modifiable = add or self.has_change_permission(request, obj)
        if modifiable:
            coches = formulaire["kpis"].value() or (obj.kpis if obj else []) or []
            context.update({
                "url_reseau": reverse("admin:evenements_evenement_reseau", current_app=self.admin_site.name),
                "carte_tuiles": settings.CARTE_TUILES_URL,
                "carte_attribution": settings.CARTE_TUILES_ATTRIBUTION,
                "types_existants": sorted(set(Evenement.objects.exclude(type="").values_list("type", flat=True))),
                "groupes_kpi": groupes_kpi(coches if formulaire["kpis_choisis"].value() else
                                           kpis_principaux(catalogue_yaml())),
                "nb_kpis_principaux": len(kpis_principaux(catalogue_yaml())),
                "kpis_choisis": bool(formulaire["kpis_choisis"].value()),
                "creneaux": context["inline_admin_formsets"][0].formset,
            })
        reponse = super().render_change_form(request, context, add, change, form_url, obj)
        if modifiable:
            reponse.template_name = self.template_edition
        return reponse

    def save_model(self, request, obj, form, change):
        if not obj.cree_par_id:
            obj.cree_par = request.user
        super().save_model(request, obj, form, change)

    def _vers_analyse(self, request, obj):
        return HttpResponseRedirect(reverse("evenements:detail", args=[obj.pk])) if "_analyse" in request.POST else None

    def response_add(self, request, obj, post_url_continue=None):
        return self._vers_analyse(request, obj) or super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        return self._vers_analyse(request, obj) or super().response_change(request, obj)

    @admin.display(description="premier créneau")
    def premier_creneau(self, obj):
        creneaux = list(obj.creneaux.all())
        return creneaux[0] if creneaux else "À compléter"

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
