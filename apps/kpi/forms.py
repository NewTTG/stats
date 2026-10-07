from datetime import date, timedelta

from django import forms

from .catalogue import catalogue

PERIMETRES = [
    ("global", "Tout le réseau autorisé"),
    ("commune", "Commune(s)"),
    ("site", "Site(s) — code ou nom"),
    ("trigramme", "Trigramme(s)"),
    ("secteur", "Secteur(s)"),
    ("cellule", "Cellule(s)"),
]
FENETRES = [("journee", "Journée complète"), ("18-22", "18h – 22h"), ("7-20", "7h – 20h")]
GRAN_TEMPS = [("jour", "Jour"), ("heure", "Heure"), ("semaine", "Semaine"), ("mois", "Mois")]
GRAN_ESPACE = [("global", "Global"), ("commune", "Commune"), ("site", "Site"),
               ("secteur", "Secteur"), ("cellule", "Cellule")]


def _hier():
    return date.today() - timedelta(days=1)


class RequeteForm(forms.Form):
    techno = forms.MultipleChoiceField(
        label="Technologie", choices=[("LTE", "4G LTE"), ("WCDMA", "3G WCDMA")],
        widget=forms.CheckboxSelectMultiple, initial=["LTE"])
    perimetre_type = forms.ChoiceField(label="Périmètre", choices=PERIMETRES, initial="commune")
    perimetre_valeurs = forms.CharField(
        label="Valeurs", required=False, help_text="Séparées par des virgules, ex. NOUMEA, DUMBEA")
    debut = forms.DateField(label="Du", widget=forms.DateInput(attrs={"type": "date"}),
                            initial=lambda: _hier() - timedelta(days=6))
    fin = forms.DateField(label="Au", widget=forms.DateInput(attrs={"type": "date"}), initial=_hier)
    granularite_temps = forms.ChoiceField(label="Pas de temps", choices=GRAN_TEMPS, initial="jour")
    granularite_espace = forms.ChoiceField(label="Niveau", choices=GRAN_ESPACE, initial="global")
    fenetre_horaire = forms.ChoiceField(label="Fenêtre horaire", choices=FENETRES, initial="journee")
    kpis = forms.MultipleChoiceField(label="KPI", widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, kpis_visibles=None, **kwargs):
        super().__init__(*args, **kwargs)
        cat = catalogue()
        codes = [c for c in cat if kpis_visibles is None or c in kpis_visibles]
        self.fields["kpis"].choices = [(c, f"{cat[c].techno} · {cat[c].libelle} ({cat[c].unite})") for c in codes]
        self.fields["kpis"].initial = [c for c in codes if cat[c].techno == "LTE"][:3]

    def vers_requete(self) -> dict:
        d = self.cleaned_data
        return {
            "techno": d["techno"],
            "perimetre": {"type": d["perimetre_type"],
                          "valeurs": [v.strip() for v in d["perimetre_valeurs"].split(",") if v.strip()]},
            "periode": {"debut": d["debut"], "fin": d["fin"]},
            "granularite_temps": d["granularite_temps"],
            "granularite_espace": d["granularite_espace"],
            "fenetre_horaire": d["fenetre_horaire"],
            "kpis": d["kpis"],
        }
