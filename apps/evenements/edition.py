"""Création / modification d'un événement (pages /evenements/nouveau/ et /<pk>/modifier/) : formulaire,
données de la carte de sélection, KPI proposés. La période analysée se choisit à l'affichage (``periode``)."""

import json
import re

from django import forms
from django.db.models import Count

from apps.kpi.catalogue import catalogue_yaml, kpis_principaux
from apps.referentiel.models import Cellule, Secteur, Site

from . import mobiles
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


class Deploiements(forms.CharField):
    """Remorques déployées (JSON en champ caché), tenues par la liste de la zone couverte."""

    widget = forms.HiddenInput

    def prepare_value(self, value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, dict) else value

    def to_python(self, value):
        return mobiles.normaliser(value)


class EvenementForm(forms.ModelForm):
    sites = ListeCodes(required=False)
    secteurs = ListeCodes(required=False)
    cellules = ListeCodes(required=False)
    deploiements = Deploiements(required=False)
    kpis = forms.MultipleChoiceField(required=False, label="KPI analysés", widget=forms.CheckboxSelectMultiple)
    kpis_choisis = forms.BooleanField(required=False, label="Choisir les KPI analysés")
    # Absent de l'envoi : visibilité inchangée (public pour un nouvel événement).
    public = forms.TypedChoiceField(label="Visibilité", required=False, empty_value=None,
                                    choices=[("public", "Public"), ("prive", "Privé")],
                                    coerce=lambda valeur: valeur == "public")

    class Meta:
        model = Evenement
        fields = ["nom", "type", "description", "public", "sites", "secteurs", "cellules", "deploiements",
                  "semaines_reference", "kpis"]
        widgets = {
            "nom": forms.TextInput(attrs={"placeholder": "Ex. Foire de Bourail 2026", "autocomplete": "off"}),
            "type": forms.TextInput(attrs={"placeholder": "Concert, Foire, Journée…", "list": "types-evenement",
                                           "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Lieu, organisateur, affluence attendue…"}),
            "semaines_reference": forms.NumberInput(attrs={"min": 1, "max": 12}),
        }

    def __init__(self, *args, visibilite: bool = True, **kwargs):
        """``visibilite`` : public / privé se choisit (création, ou par le créateur)."""
        super().__init__(*args, **kwargs)
        self.fields["kpis"].choices = [(code, k.libelle) for code, k in catalogue_yaml().items()]
        self.fields["kpis_choisis"].initial = bool(self.instance.kpis)
        if visibilite:
            self.initial["public"] = "public" if self.instance.public else "prive"
        else:
            del self.fields["public"]

    def clean_public(self):
        public = self.cleaned_data.get("public")
        return self.instance.public if public is None else public

    def clean(self):
        donnees = super().clean()
        deployes = set(donnees.get("deploiements") or {})
        if deployes:  # une remorque déployée ne compte que par sa disposition déclarée
            secteurs = dict(Secteur.objects.filter(site__code_site__in=deployes).values_list("code", "site__code_site"))
            hors = set(Cellule.objects.filter(nom__in=donnees.get("cellules") or [],
                                              secteur__site__code_site__in=deployes).values_list("nom", flat=True))
            donnees["sites"] = [c for c in donnees.get("sites") or [] if c not in deployes]
            donnees["secteurs"] = [c for c in donnees.get("secteurs") or [] if c not in secteurs]
            donnees["cellules"] = [c for c in donnees.get("cellules") or [] if c not in hors]
        if not any(donnees.get(champ) for champ in ("sites", "secteurs", "cellules", "deploiements")):
            self.add_error("sites", "Choisissez au moins un site, un secteur ou une cellule.")
        if not donnees.get("kpis_choisis"):
            donnees["kpis"] = []  # liste vide : l'analyse retient les KPI principaux
        elif not donnees.get("kpis") and "kpis" not in self.errors:
            self.add_error("kpis", "Cochez au moins un KPI, ou revenez aux KPI principaux.")
        return donnees


def reseau_pour_carte(permises: set[str] | None = None) -> dict:
    """Sites (coordonnées), secteurs (azimut) et cellules du référentiel, pour la carte de sélection.
    ``permises`` : cellules autorisées (None = tout le réseau) ; seuls leurs sites sont proposés.

    Sites mobiles : sans position (elle se déclare dans l'événement), même sans cellule connue."""
    toutes = permises is None
    sites = {s.pk: {"code": s.code_site, "nom": s.nom, "commune": s.commune, "trigramme": s.trigramme,
                    "lat": None if s.mobile else s.latitude, "lon": None if s.mobile else s.longitude,
                    "mobile": s.mobile, "secteurs": []}
             for s in Site.objects.order_by("code_site")}
    sans_cellule = Secteur.objects.filter(site__mobile=True, cellules__isnull=True)
    if not toutes:
        sans_cellule = sans_cellule.none()
    for sect in sans_cellule.order_by("numero"):
        # Secteur d'une remorque sans cellule : proposé quand même pour la déclaration.
        sites[sect.site_id]["secteurs"].append({"code": sect.code, "numero": sect.numero, "azimut": sect.azimut,
                                                "cellules": []})
    secteurs, libres = {}, []
    cellules = Cellule.objects.select_related("secteur")
    if not toutes:
        cellules = cellules.filter(nom__in=permises)
    for c in cellules.order_by("secteur__numero", "techno", "porteuse", "nom"):
        if c.secteur is None or c.secteur.site_id not in sites:
            libres.append([c.nom, c.techno])
            continue
        if c.secteur_id not in secteurs:
            secteurs[c.secteur_id] = {"code": c.secteur.code, "numero": c.secteur.numero,
                                      "azimut": c.secteur.azimut, "cellules": []}
            sites[c.secteur.site_id]["secteurs"].append(secteurs[c.secteur_id])
        secteurs[c.secteur_id]["cellules"].append([c.nom, c.techno])
    for site in sites.values():
        site["secteurs"].sort(key=lambda sec: sec["numero"])
    return {"sites": [s for s in sites.values() if s["secteurs"] or (s["mobile"] and toutes)], "libres": libres}


def zone_pour_carte(evenement: Evenement) -> dict:
    """Sites de l'événement (coordonnées) et leurs seuls secteurs actifs, entiers ou en partie,
    pour la carte de la page de l'événement ; remorques à la position et selon la disposition déclarées.
    ``nb_secteurs`` : secteurs du site (un seul à 0° : omni)."""
    deploiements = evenement.deploiements or {}
    deployees = set(evenement.cellules_deployees())
    incluses = (set(evenement.noms_cellules("LTE")) | set(evenement.noms_cellules("WCDMA"))) - deployees
    ids = set(Cellule.objects.filter(nom__in=incluses, secteur__isnull=False)
              .exclude(secteur__site__code_site__in=list(deploiements)).values_list("secteur_id", flat=True))
    totaux = {}
    for secteur_id, nom in Cellule.objects.filter(secteur_id__in=ids).values_list("secteur_id", "nom"):
        totaux.setdefault(secteur_id, [0, 0])
        totaux[secteur_id][0] += 1
        totaux[secteur_id][1] += nom in incluses
    sites = {}
    secteurs = Secteur.objects.filter(pk__in=ids).select_related("site").annotate(nb=Count("site__secteurs"))
    for sect in secteurs.order_by("site__code_site", "numero"):
        site = sites.setdefault(sect.site.code_site, {
            "code": sect.site.code_site, "nom": sect.site.nom, "lat": sect.site.latitude,
            "lon": sect.site.longitude, "mobile": False, "nb_secteurs": sect.nb, "secteurs": []})
        total, actives = totaux.get(sect.pk, [0, 0])
        site["secteurs"].append({"code": sect.code, "numero": sect.numero, "azimut": sect.azimut,
                                 "etat": "choisi" if actives == total else "partiel",
                                 "cellules": f"{actives}/{total}"})
    noms = dict(Site.objects.filter(code_site__in=list(deploiements)).values_list("code_site", "nom"))
    nb_secteurs = len(ids)
    for code, dep in sorted(deploiements.items()):
        nb_secteurs += len(dep["secteurs"])
        sites[code] = {"code": code, "nom": noms.get(code, code), "lat": dep.get("lat"), "lon": dep.get("lon"),
                       "mobile": True, "nb_secteurs": len(dep["secteurs"]), "secteurs": [
                           {"code": f"{code}{s['numero']}", "numero": s["numero"], "azimut": s["azimut"],
                            "etat": "choisi", "cellules": f"{len(s['cellules'])}/{len(s['cellules'])}"}
                           for s in dep["secteurs"]]}
    places = [s for s in sites.values() if s["lat"] is not None and s["lon"] is not None]
    return {"sites": places, "sans_position": len(sites) - len(places),
            "nb_secteurs": nb_secteurs, "nb_cellules": len(incluses) + len(deployees)}


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
