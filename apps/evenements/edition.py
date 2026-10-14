"""Création / modification d'un événement (pages /evenements/nouveau/ et /<pk>/modifier/) : formulaire,
données de la carte de sélection, KPI proposés. La période analysée se choisit à l'affichage (``periode``)."""

import re

from django import forms

from apps.kpi.catalogue import catalogue_yaml, kpis_principaux
from apps.referentiel.models import Cellule, Secteur, Site

from .models import Evenement

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


def zone_pour_carte(evenement: Evenement) -> dict:
    """Sites de l'événement (coordonnées) et leurs seuls secteurs actifs, entiers ou en partie,
    pour la carte de la page de l'événement."""
    incluses = set(evenement.noms_cellules("LTE")) | set(evenement.noms_cellules("WCDMA"))
    ids = set(Cellule.objects.filter(nom__in=incluses, secteur__isnull=False).values_list("secteur_id", flat=True))
    totaux = {}
    for secteur_id, nom in Cellule.objects.filter(secteur_id__in=ids).values_list("secteur_id", "nom"):
        totaux.setdefault(secteur_id, [0, 0])
        totaux[secteur_id][0] += 1
        totaux[secteur_id][1] += nom in incluses
    sites = {}
    for sect in Secteur.objects.filter(pk__in=ids).select_related("site").order_by("site__code_site", "numero"):
        site = sites.setdefault(sect.site_id, {"code": sect.site.code_site, "nom": sect.site.nom,
                                               "lat": sect.site.latitude, "lon": sect.site.longitude, "secteurs": []})
        total, actives = totaux.get(sect.pk, [0, 0])
        site["secteurs"].append({"code": sect.code, "numero": sect.numero, "azimut": sect.azimut,
                                 "etat": "choisi" if actives == total else "partiel",
                                 "cellules": f"{actives}/{total}"})
    places = [s for s in sites.values() if s["lat"] is not None and s["lon"] is not None]
    return {"sites": places, "sans_position": len(sites) - len(places),
            "nb_secteurs": len(ids), "nb_cellules": len(incluses)}


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
