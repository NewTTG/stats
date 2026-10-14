"""Déclaration et modification d'un site dans l'application (page Réseau) : le site, ses secteurs
(azimut) et ses cellules, enregistrés ensemble.

Un site déclaré ici (``manuel``) est conservé par les rechargements du référentiel ; un site lu
dans le xlsx peut être corrigé, mais le prochain rechargement reprend le fichier (sauf le
marqueur « site mobile »). Une cellule retirée d'un site devient « non rattachée » : elle reste
connue, avec son historique KPI.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Cellule, Secteur, Site

MAX_SECTEURS = 9


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["code_site", "nom", "trigramme", "commune", "region", "latitude", "longitude", "mobile"]
        labels = {"nom": "Nom", "commune": "Commune", "region": "Région", "latitude": "Latitude",
                  "longitude": "Longitude", "trigramme": "Trigramme"}
        help_texts = {"code_site": "Identifiant unique, repris par les événements et les périmètres.",
                      "trigramme": "Préfixe des cellules 4G (ex. 1RM pour 1RMe1)."}
        widgets = {
            "code_site": forms.TextInput(attrs={"placeholder": "Ex. 2RM129", "autocomplete": "off", "spellcheck": "false"}),
            "nom": forms.TextInput(attrs={"placeholder": "Ex. REMORQUE_2", "autocomplete": "off"}),
            "trigramme": forms.TextInput(attrs={"placeholder": "Ex. 2RM", "autocomplete": "off", "spellcheck": "false"}),
            "latitude": forms.NumberInput(attrs={"step": "any", "placeholder": "-22.2758"}),
            "longitude": forms.NumberInput(attrs={"step": "any", "placeholder": "166.4580"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # code repris par les événements : il ne change plus
            self.fields["code_site"].disabled = True
        self.fields["commune"].required = True

    def clean_code_site(self):
        code = self.cleaned_data["code_site"].strip().upper()
        if not code.isalnum():
            raise ValidationError("Lettres et chiffres seulement.")
        return code

    def clean_trigramme(self):
        return self.cleaned_data["trigramme"].strip().upper()

    def clean_commune(self):
        return self.cleaned_data["commune"].strip().upper()

    def clean(self):
        donnees = super().clean()
        lat, lon = donnees.get("latitude"), donnees.get("longitude")
        if lat is not None and not -90 <= lat <= 90:
            self.add_error("latitude", "Entre -90 et 90.")
        if lon is not None and not -180 <= lon <= 180:
            self.add_error("longitude", "Entre -180 et 180.")
        if (lat is None) != (lon is None) and not self.errors:
            self.add_error("longitude", "Renseignez la latitude et la longitude, ou aucune des deux.")
        return donnees


class SecteurForm(forms.Form):
    numero = forms.IntegerField(label="N°", min_value=1, max_value=MAX_SECTEURS)
    azimut = forms.IntegerField(label="Azimut (°)", min_value=0, max_value=359, required=False)


class CelluleForm(forms.Form):
    nom = forms.CharField(label="Cellule", max_length=32)
    techno = forms.ChoiceField(label="Techno", choices=[("LTE", "4G"), ("WCDMA", "3G")], initial="LTE")
    secteur = forms.IntegerField(label="Secteur", min_value=1, max_value=MAX_SECTEURS)
    porteuse = forms.IntegerField(label="Porteuse", min_value=1, max_value=9, initial=1)

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()


class BaseSecteurs(forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        numeros = [f.cleaned_data["numero"] for f in self.forms if f.cleaned_data and not self._should_delete_form(f)]
        if len(numeros) != len(set(numeros)):
            raise ValidationError("Chaque secteur a un numéro différent.")
        if not numeros:
            raise ValidationError("Déclarez au moins un secteur.")

    def numeros(self) -> set[int]:
        return {f.cleaned_data["numero"] for f in self.forms if f.cleaned_data and not self._should_delete_form(f)}


class BaseCellules(forms.BaseFormSet):
    def __init__(self, *args, site=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.site = site

    def lignes(self) -> list[dict]:
        return [f.cleaned_data for f in self.forms if f.cleaned_data and not self._should_delete_form(f)]

    def clean(self):
        if any(self.errors):
            return
        cles = [(c["techno"], c["nom"]) for c in self.lignes()]
        if len(cles) != len(set(cles)):
            raise ValidationError("Une cellule est déclarée deux fois.")
        ailleurs = Cellule.objects.filter(secteur__isnull=False).select_related("secteur__site")
        if self.site is not None and self.site.pk:
            ailleurs = ailleurs.exclude(secteur__site=self.site)
        erreurs = [f"{c.nom} ({c.get_techno_display()}) est déjà rattachée au site {c.secteur.site}."
                   for techno, nom in cles for c in ailleurs.filter(techno=techno, nom=nom)]
        if erreurs:
            raise ValidationError(erreurs)


SecteursFormSet = forms.formset_factory(SecteurForm, formset=BaseSecteurs, extra=0, can_delete=True,
                                        max_num=MAX_SECTEURS, validate_max=True)
CellulesFormSet = forms.formset_factory(CelluleForm, formset=BaseCellules, extra=0, can_delete=True)


def initial(site: Site) -> tuple[list[dict], list[dict]]:
    """Secteurs et cellules actuels du site, pour pré-remplir les formulaires."""
    secteurs = [{"numero": s.numero, "azimut": s.azimut} for s in site.secteurs.order_by("numero")]
    cellules = [{"nom": c.nom, "techno": c.techno, "secteur": c.secteur.numero, "porteuse": c.porteuse}
                for c in Cellule.objects.filter(secteur__site=site).select_related("secteur")
                .order_by("secteur__numero", "techno", "porteuse", "nom")]
    return secteurs, cellules


def valider(site_form, secteurs, cellules) -> bool:
    """Formulaires valides, et chaque cellule rattachée à un secteur déclaré."""
    valides = all([site_form.is_valid(), secteurs.is_valid(), cellules.is_valid()])
    if not valides:
        return False
    numeros = secteurs.numeros()
    absents = sorted({c["secteur"] for c in cellules.lignes()} - numeros)
    if absents:
        cellules._non_form_errors = cellules.error_class(
            [f"Secteur {n} non déclaré : ajoutez-le, ou changez le secteur de ses cellules." for n in absents],
            renderer=cellules.renderer)
        return False
    return True


@transaction.atomic
def enregistrer(site_form, secteurs, cellules) -> Site:
    nouveau = site_form.instance.pk is None
    site = site_form.save(commit=False)
    if nouveau:
        site.manuel = True
    site.nb_secteurs = len(secteurs.numeros())
    site.save()

    par_numero = {}
    for ligne in secteurs.forms:
        if not ligne.cleaned_data or secteurs._should_delete_form(ligne):
            continue
        numero = ligne.cleaned_data["numero"]
        par_numero[numero], _ = Secteur.objects.update_or_create(
            code=f"{site.code_site}{numero}",
            defaults={"site": site, "numero": numero, "azimut": ligne.cleaned_data.get("azimut")})

    voulues = {(c["techno"], c["nom"]): c for c in cellules.lignes()}
    for cellule in Cellule.objects.filter(secteur__site=site):
        if (cellule.techno, cellule.nom) not in voulues:
            cellule.secteur = cellule.secteur_avant = None  # reste connue, non rattachée
            cellule.save(update_fields=["secteur", "secteur_avant"])
    for (techno, nom), c in voulues.items():
        Cellule.objects.update_or_create(techno=techno, nom=nom, defaults={
            "secteur": par_numero[c["secteur"]], "porteuse": c["porteuse"]})
    # Secteur retiré : ses cellules non redéclarées sont déjà détachées.
    Secteur.objects.filter(site=site).exclude(pk__in=[s.pk for s in par_numero.values()]).delete()
    return site
