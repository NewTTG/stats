"""Création / modification d'un événement (pages publiques /evenements/nouveau/ et /<pk>/modifier/) :
formulaires, données de la carte de sélection, KPI proposés."""

import re

from django import forms
from django.forms import inlineformset_factory

from apps.kpi.catalogue import catalogue_yaml, kpis_principaux
from apps.referentiel.models import Cellule, Site

from .models import Creneau, Evenement

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
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Lieu, organisateur, affluence attendue…"}),
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


def creneaux_formset(evenement: Evenement, data=None):
    """Créneaux de l'événement ; une ligne vide tant qu'il n'en a aucun."""
    vide = evenement.pk is None or not evenement.creneaux.exists()
    classe = inlineformset_factory(Evenement, Creneau, form=CreneauForm, extra=1 if vide else 0, can_delete=True)
    return classe(data, instance=evenement, prefix="creneaux")


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


def groupes_kpi(formulaire: EvenementForm) -> list[dict]:
    """KPI du catalogue par techno puis catégorie ; cochés : la sélection, sinon les KPI principaux."""
    cat = catalogue_yaml()
    if formulaire["kpis_choisis"].value():
        coches = set(formulaire["kpis"].value() or formulaire.instance.kpis or [])
    else:
        coches = set(kpis_principaux(cat))
    groupes = {}
    for code, k in cat.items():
        techno = groupes.setdefault(k.techno, {"titre": LIBELLES_TECHNO[k.techno], "categories": {}})
        techno["categories"].setdefault(LIBELLES_CATEGORIE.get(k.categorie, k.categorie), []).append(
            {"code": code, "libelle": k.libelle, "coche": code in coches, "cause": bool(k.decomposition_de)})
    return [{"titre": g["titre"], "categories": list(g["categories"].items())} for g in groupes.values()]


def nb_kpis_principaux() -> int:
    return len(kpis_principaux(catalogue_yaml()))
