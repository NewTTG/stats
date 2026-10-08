import re
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
    ("evenement", "Événement(s) — nom"),
]
FENETRES = [("journee", "Journée complète"), ("18-22", "18h – 22h"), ("7-20", "7h – 20h")]
GRAN_TEMPS = [("jour", "Jour"), ("heure", "Heure"), ("semaine", "Semaine"), ("mois", "Mois")]
GRAN_ESPACE = [("global", "Global"), ("commune", "Commune"), ("site", "Site"),
               ("secteur", "Secteur"), ("cellule", "Cellule")]
_PLAGE = re.compile(r"^(\d{1,2})-(\d{1,2})$")


def _hier():
    return date.today() - timedelta(days=1)


def fenetre_personnalisee(valeur) -> bool:
    """Plage « H-H » valide hors des fenêtres proposées (ex. « 6-12 » issue d'une recherche)."""
    m = _PLAGE.match(str(valeur or ""))
    return bool(m) and 0 <= int(m[1]) < int(m[2]) <= 24 and valeur not in dict(FENETRES)


class RequeteForm(forms.Form):
    techno = forms.MultipleChoiceField(
        label="Technologie", choices=[("LTE", "4G LTE"), ("WCDMA", "3G WCDMA")],
        widget=forms.CheckboxSelectMultiple, initial=["LTE"])
    perimetre_type = forms.ChoiceField(label="Périmètre", choices=PERIMETRES, initial="commune")
    perimetre_valeurs = forms.CharField(
        label="Valeurs", required=False, help_text="Séparées par des virgules, ex. NOUMEA, DUMBEA")
    debut = forms.DateField(label="Du", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                            initial=lambda: _hier() - timedelta(days=6))
    fin = forms.DateField(label="Au", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), initial=_hier)
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
        # Plage horaire issue d'une recherche en langage libre (ex. « 6-12 ») : acceptée telle quelle.
        fenetre = self.data.get("fenetre_horaire") if self.is_bound else self.initial.get("fenetre_horaire")
        if fenetre_personnalisee(fenetre):
            debut, fin = fenetre.split("-")
            self.fields["fenetre_horaire"].choices = [*FENETRES, (fenetre, f"{debut}h – {fin}h")]

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


def champs_depuis_requete(req) -> dict:
    """Champs du formulaire équivalents à une ``RequeteKpi`` (rapport PowerPoint, liens)."""
    return {
        "techno": list(req.techno),
        "perimetre_type": req.perimetre.type,
        "perimetre_valeurs": ", ".join(req.perimetre.valeurs),
        "debut": req.periode.debut.isoformat(),
        "fin": req.periode.fin.isoformat(),
        "granularite_temps": req.granularite_temps,
        "granularite_espace": req.granularite_espace,
        "fenetre_horaire": req.fenetre_horaire,
        "kpis": list(req.kpis),
    }


def champs_depuis_params(params: dict) -> dict:
    """Pré-remplissage du formulaire avancé à partir d'une interprétation (même incomplète)."""
    initial = {}
    if params.get("techno"):
        initial["techno"] = list(params["techno"])
    if params.get("kpis"):
        initial["kpis"] = list(params["kpis"])
    if params.get("perimetre"):
        initial["perimetre_type"] = params["perimetre"]["type"]
        initial["perimetre_valeurs"] = ", ".join(params["perimetre"]["valeurs"])
    if params.get("periode"):
        initial["debut"] = params["periode"]["debut"]
        initial["fin"] = params["periode"]["fin"]
    for cle in ("granularite_temps", "granularite_espace", "fenetre_horaire"):
        if params.get(cle):
            initial[cle] = params[cle]
    return initial
