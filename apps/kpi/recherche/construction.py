"""D'une ``Demande`` (comprise par les règles, l'IA ou les paramètres) à une ``Interpretation``.

Ajoute les valeurs par défaut, déduit les KPI des intentions, prépare les puces et les
questions. Les paramètres explicites (réponses aux questions, puces modifiées)
priment sur le texte.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from apps.comptes.acces import kpis_autorises

from ..catalogue import DefinitionKpi, catalogue
from .dates import (LIBELLES_ESPACE, LIBELLES_TEMPS, PRESETS, Periode, granularite_par_defaut, libelle_fenetre,
                    preset)
from .interpretation import GLOBAL, Demande, Interpretation, Lieu, Option, Puce, Question
from .lieux import ResolveurLieux
from .vocabulaire import LIBELLES_TECHNO, TECHNOS, causes_de, kpis_intention, vocabulaire

TYPES_PERIMETRE = ("global", "commune", "site", "trigramme", "cellule", "secteur", "evenement")
GRANULARITES_TEMPS = ("heure", "jour", "semaine", "mois")
GRANULARITES_ESPACE = ("global", "commune", "site", "secteur", "cellule")
# Paramètres GET explicites reconnus (priment sur le texte).
PARAMETRES = ("techno", "kpis", "intention", "perimetre_type", "perimetre_valeurs", "periode", "debut", "fin",
              "granularite_temps", "granularite_espace", "fenetre_horaire")
QUESTION_PERIODE = ["hier", "7j", "semaine_derniere", "mois_dernier", "mois_courant"]


@dataclass
class Contexte:
    """KPI visibles et lieux accessibles de l'utilisateur."""

    catalogue: dict[str, DefinitionKpi]
    lieux: ResolveurLieux
    user: Any = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def pour(cls, user=None) -> "Contexte":
        cat = catalogue()
        if user is not None:
            visibles = kpis_autorises(user, set(cat))
            cat = {c: k for c, k in cat.items() if c in visibles}
        return cls(catalogue=cat, lieux=ResolveurLieux(user), user=user)


def _ordre_technos(codes: list[str], cat) -> list[str]:
    return list(dict.fromkeys(cat[c].techno for c in codes if c in cat))


def kpis_de(demande: Demande, cat: dict) -> tuple[list[str], list[str]]:
    """Codes KPI de la demande (explicites, ou déduits des intentions) et notes."""
    voc = vocabulaire()
    notes = []
    if demande.kpis:
        codes = [c for c in demande.kpis if c in cat]
        if demande.techno:
            filtres = [c for c in codes if cat[c].techno in demande.techno]
            codes = filtres or codes
    else:
        intentions = list(demande.intentions)
        if demande.causes and not intentions:
            intentions = ["drop"]
        codes = []
        for code in intentions:
            intention = voc.intentions[code]
            technos = [t for t in TECHNOS if t in demande.techno] if demande.techno else intention.technos_defaut
            trouves = kpis_intention(intention, technos, cat)
            if not trouves and demande.techno:
                notes.append(f"Aucun KPI « {intention.libelle} » en "
                             f"{' / '.join(LIBELLES_TECHNO[t] for t in demande.techno)}.")
            codes += trouves
    if demande.causes and codes:
        avec = [(c, causes_de(c, cat)) for c in codes]
        if any(causes for _, causes in avec):
            codes = [x for c, causes in avec if causes for x in (c, *causes)]
        else:
            notes.append("Pas de décomposition par cause pour ces KPI.")
    return list(dict.fromkeys(codes)), notes


def _libelle_kpis(demande: Demande, codes: list[str], cat) -> str:
    voc = vocabulaire()
    if demande.intentions and not demande.kpis:
        libelle = " + ".join(voc.intentions[i].libelle for i in demande.intentions)
    elif demande.causes and not demande.kpis:
        libelle = "Drop"
    else:
        principaux = [c for c in codes if not cat[c].decomposition_de]
        libelle = ", ".join(cat[c].libelle for c in principaux[:2])
        if len(principaux) > 2:
            libelle += f" + {len(principaux) - 2}"
    nb_causes = sum(1 for c in codes if cat[c].decomposition_de)
    if nb_causes:
        libelle += f" · {nb_causes} causes"
    return libelle


def _libelle_periode(p: Periode) -> str:
    if p.debut == p.fin:
        dates = f"{p.debut:%d/%m/%Y}"
    elif p.debut.year == p.fin.year:
        dates = f"{p.debut:%d/%m} → {p.fin:%d/%m/%Y}"
    else:
        dates = f"{p.debut:%d/%m/%Y} → {p.fin:%d/%m/%Y}"
    return f"{p.libelle} · {dates}" if p.libelle and not p.libelle.startswith(("Du ", "Le ")) else dates


def _libelle_mon_perimetre(contexte: Contexte) -> str:
    """« Voir mon périmètre (Koné) », « Voir mon périmètre (Koné, Voh…) »."""
    voc = vocabulaire()
    communes = [voc.libelle_commune(c) for c in contexte.lieux.communes_visibles]
    if not communes:
        return "Voir mon périmètre"
    liste = ", ".join(communes[:2]) + ("…" if len(communes) > 2 else "")
    return f"Voir mon périmètre ({liste})"


def niveau_comparaison(demande: Demande) -> str | None:
    """Niveau spatial implicite d'une comparaison de lieux.

    Plusieurs communes citées (« Koumac et Poum ») ou « comparaison / comparer / vs » avec
    des communes -> par commune ; « comparer » des sites -> par site.
    """
    lieux = [lieu for lieu in demande.lieux if lieu.type != "global"]
    types = {lieu.type for lieu in lieux}
    nb_valeurs = sum(len(lieu.valeurs) for lieu in lieux)
    if types == {"commune"} and (len(lieux) >= 2 or (demande.comparaison and nb_valeurs >= 2)):
        return "commune"
    if demande.comparaison and types and types <= {"site", "commune", "trigramme"} and nb_valeurs >= 2:
        return "site"
    return None


def _periode_evenement(lieu: Lieu) -> Periode | None:
    from apps.evenements.models import Creneau

    creneaux = list(Creneau.objects.filter(evenement__nom__in=lieu.valeurs))
    if not creneaux:
        return None
    from django.utils import timezone

    debut = min(timezone.localtime(c.debut).date() for c in creneaux)
    fin = max(timezone.localtime(c.fin).date() for c in creneaux)
    return Periode(debut, fin, "Période de l'événement")


def construire(demande: Demande, contexte: Contexte, aujourdhui: date, *, source="regles",
               non_compris=None, notes=None) -> Interpretation:
    cat = contexte.catalogue
    voc = vocabulaire()
    interp = Interpretation(source=source, non_compris=list(non_compris or []), notes=list(notes or []),
                            demande=demande)
    params = interp.params

    # Lieu
    lieu = contexte.lieux.combiner(demande.lieux) if demande.lieux else GLOBAL
    if demande.ambiguites:
        a = demande.ambiguites[0]
        restreint = contexte.lieux.restreint
        options = [Option(c.libelle, contexte.lieux.combiner([*demande.lieux, c]).params, detail=c.detail)
                   for c in a.candidats]
        if a.hors_perimetre or a.non_reconnu:
            # Jamais de repli silencieux : on propose, l'utilisateur choisit.
            if demande.lieux:
                options.append(Option(f"Ignorer « {a.texte} »", lieu.params, detail=lieu.libelle))
            if restreint:
                options.append(Option(_libelle_mon_perimetre(contexte), GLOBAL.params,
                                      detail="toutes vos communes"))
            elif not demande.lieux:
                options.append(Option("Tout le réseau", GLOBAL.params, detail="périmètre autorisé"))
            if a.candidats:
                texte = f"Lieu non reconnu : « {a.texte} ». Vouliez-vous dire… ?"
            elif restreint:
                # Même message qu'il existe ailleurs ou non : rien n'est révélé hors périmètre.
                texte = f"« {a.texte} » n'est pas dans votre périmètre."
            else:
                texte = f"Lieu non reconnu : « {a.texte} ». Précisez le lieu ou choisissez tout le réseau."
        elif len(a.candidats) == 1:
            texte = f"« {a.texte} » : vouliez-vous dire « {a.candidats[0].libelle} » ?"
        else:
            texte = f"Plusieurs lieux correspondent à « {a.texte} » : lequel ?"
        interp.questions.append(Question("perimetre", texte, options, saisie="texte"))
    else:
        params["perimetre"] = {"type": lieu.type, "valeurs": list(lieu.valeurs)}

    # KPI
    codes, notes_kpi = kpis_de(demande, cat)
    interp.notes += notes_kpi
    if codes:
        params["kpis"] = codes
        params["techno"] = _ordre_technos(codes, cat)
    else:
        technos = demande.techno or list(TECHNOS)
        options = [Option(i.libelle, {"intention": i.code}) for i in voc.familles
                   if kpis_intention(i, technos if demande.techno else i.technos_defaut, cat)]
        interp.questions.append(Question("kpis", "Que voulez-vous voir ?", options))

    # Période (un événement daté fournit la sienne)
    periode = demande.periode
    if periode is None and lieu.type == "evenement" and not demande.ambiguites:
        periode = _periode_evenement(lieu)
    if periode:
        params["periode"] = {"debut": periode.debut, "fin": periode.fin}
    else:
        options = [Option(PRESETS[c], {"periode": c}) for c in QUESTION_PERIODE]
        interp.questions.append(Question("periode", "Sur quelle période ?", options, saisie="dates"))

    # Fenêtre horaire
    fenetre = demande.fenetre or "journee"
    if demande.heure_chargee or fenetre == "heure_chargee":
        interp.notes.append("L'heure chargée n'est pas encore calculée par le moteur : journée complète utilisée.")
        fenetre = "journee"
    params["fenetre_horaire"] = fenetre

    # Granularités
    temps = demande.granularite_temps or (granularite_par_defaut(periode.jours) if periode else None)
    if temps:
        params["granularite_temps"] = temps
    compare = None if demande.granularite_espace or demande.classement else niveau_comparaison(demande)
    espace = demande.granularite_espace or ("site" if demande.classement else compare or "global")
    params["granularite_espace"] = espace

    # Puces (ce qui a été compris, modifiable)
    if codes:
        technos = params["techno"]
        interp.compris.append(Puce("techno", " + ".join(LIBELLES_TECHNO[t] for t in technos),
                                   defaut=not demande.techno))
        interp.compris.append(Puce("kpis", _libelle_kpis(demande, codes, cat),
                                   titre=" · ".join(cat[c].libelle for c in codes)))
    if "perimetre" in params:
        interp.compris.append(Puce("perimetre", lieu.libelle, titre=lieu.detail,
                                   defaut=not demande.lieux and not demande.global_demande))
    if periode:
        interp.compris.append(Puce("periode", _libelle_periode(periode),
                                   titre=f"Du {periode.debut:%d/%m/%Y} au {periode.fin:%d/%m/%Y}"))
    if temps:
        interp.compris.append(Puce("granularite_temps", LIBELLES_TEMPS[temps], defaut=not demande.granularite_temps))
    interp.compris.append(Puce("granularite_espace", LIBELLES_ESPACE[espace],
                               defaut=not demande.granularite_espace and not demande.classement and not compare))
    interp.compris.append(Puce("fenetre_horaire", demande.fenetre_libelle or libelle_fenetre(fenetre),
                               defaut=not demande.fenetre))
    interp.notes = list(dict.fromkeys(interp.notes))
    return interp


# ------------------------------------------------------------------ paramètres explicites

def _date_iso(valeur: str) -> date | None:
    try:
        return date.fromisoformat(valeur)
    except (TypeError, ValueError):
        return None


def _fenetre_valide(f: str) -> bool:
    if f in ("journee", "heure_chargee"):
        return True
    try:
        debut, fin = (int(x) for x in f.split("-"))
    except ValueError:
        return False
    return 0 <= debut < fin <= 24


def parametres_explicites(get) -> dict:
    """Paramètres GET explicites présents et non vides (listes pour techno / kpis / intention)."""
    sortie = {}
    for cle in PARAMETRES:
        if cle in ("techno", "kpis", "intention"):
            valeurs = [v for v in get.getlist(cle) if v]
            if valeurs:
                sortie[cle] = valeurs
        elif get.get(cle, "") != "" or (cle == "perimetre_valeurs" and cle in get):
            sortie[cle] = get.get(cle).strip()
    return sortie


def appliquer(demande: Demande | None, explicites: dict, contexte: Contexte, aujourdhui: date) -> tuple[Demande, list[str]]:
    """Demande modifiée par les paramètres explicites (qui priment sur le texte)."""
    d = replace(demande) if demande else Demande()
    notes = []
    voc = vocabulaire()
    if "techno" in explicites:
        technos = [t for t in TECHNOS if t in explicites["techno"]]
        if technos:
            d.techno = technos
    if "intention" in explicites:
        intentions = [i for i in explicites["intention"] if i in voc.intentions]
        if intentions:
            d.intentions, d.kpis = intentions, []
    if "kpis" in explicites:
        codes = [c for c in explicites["kpis"] if c in contexte.catalogue]
        if codes:
            d.kpis, d.intentions, d.causes = codes, [], False
            d.techno = []
    type_p = explicites.get("perimetre_type")
    if type_p in TYPES_PERIMETRE:
        valeurs = [v.strip() for v in explicites.get("perimetre_valeurs", "").split(",") if v.strip()]
        if type_p == "global" or not valeurs:
            d.lieux, d.global_demande = [], True
        else:
            if type_p == "commune":
                valeurs = [v.upper() for v in valeurs]
                libelle = " + ".join(voc.libelle_commune(v) for v in valeurs)
            else:
                libelle = ", ".join(valeurs)
            d.lieux = [Lieu(type_p, tuple(valeurs), libelle)]
        d.ambiguites = []
    code = explicites.get("periode")
    if code and code in PRESETS:
        d.periode = preset(code, aujourdhui)
    elif "debut" in explicites or "fin" in explicites:
        debut, fin = _date_iso(explicites.get("debut")), _date_iso(explicites.get("fin"))
        debut, fin = debut or fin, fin or debut
        if debut and fin:
            if fin < debut:
                debut, fin = fin, debut
            d.periode = Periode(debut, fin, f"Du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}")
        else:
            notes.append("Dates saisies non valides : format attendu AAAA-MM-JJ.")
    if explicites.get("granularite_temps") in GRANULARITES_TEMPS:
        d.granularite_temps = explicites["granularite_temps"]
    if explicites.get("granularite_espace") in GRANULARITES_ESPACE:
        d.granularite_espace = explicites["granularite_espace"]
        d.classement = False
    f = explicites.get("fenetre_horaire")
    if f and _fenetre_valide(f):
        d.fenetre, d.fenetre_libelle = f, None
        d.heure_chargee = f == "heure_chargee"
    return d, notes
