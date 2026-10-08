"""Exécution d'une ``RequeteKpi`` : périmètre -> cellules -> lecture -> agrégation."""

import re
from datetime import date
from dataclasses import dataclass, field

import pandas as pd
from django.db.models import Q

from apps.comptes.acces import cellules_autorisees, kpis_autorises
from apps.referentiel.models import Cellule

from .catalogue import DefinitionKpi, catalogue
from .moteur import agreger, ratios_simples
from .requete import RequeteKpi
from .source import lire

NON_RATTACHEE = "(non rattachée)"
# Bornes de période : au-delà, message clair plutôt qu'une lecture démesurée (ou une erreur).
DATE_MIN, DATE_MAX = date(2000, 1, 1), date(2100, 12, 31)
JOURS_MAX = {"heure": 400, "jour": 3660}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class RequeteRefusee(ValueError):
    """Requête valide syntaxiquement mais non exécutable (message affichable)."""


@dataclass
class ResultatTechno:
    techno: str
    kpis: list[DefinitionKpi]
    table: pd.DataFrame  # index (periode, entite), une colonne par code KPI
    cellules_demandees: int
    cellules_sans_donnees: list[str] = field(default_factory=list)
    # index entite : KPI agrégés sur toute la période (somme des num / somme des den)
    synthese: pd.DataFrame | None = None
    # KPI sur tout le périmètre et toute la période (ratio de sommes), par code KPI
    synthese_globale: dict[str, float] = field(default_factory=dict)


@dataclass
class Resultat:
    requete: RequeteKpi
    par_techno: list[ResultatTechno]
    avertissements: list[str] = field(default_factory=list)


def colonnes_utilisees(kpis: list[DefinitionKpi]) -> list[str]:
    noms = set()
    for k in ratios_simples(kpis):
        for expr in (k.numerateur, k.denominateur or ""):
            noms.update(_IDENT.findall(expr))
    return sorted(noms)


def cellules_du_perimetre(requete: RequeteKpi, techno: str) -> list[str] | None:
    """Cellules désignées par le périmètre demandé (None = tout le réseau)."""
    p = requete.perimetre
    valeurs = [v.strip() for v in p.valeurs if v.strip()]
    if p.type == "global":
        return None
    filtres = {
        "commune": Q(secteur__site__commune__in=[v.upper() for v in valeurs]),
        "site": Q(secteur__site__code_site__in=valeurs) | Q(secteur__site__nom__in=valeurs),
        "trigramme": Q(secteur__site__trigramme__in=valeurs),
        "secteur": Q(secteur__code__in=valeurs),
        "cellule": Q(nom__in=valeurs),
    }
    if p.type == "evenement":
        from apps.evenements.models import Evenement

        evenements = list(Evenement.objects.filter(nom__in=valeurs))
        inconnus = set(valeurs) - {e.nom for e in evenements}
        if inconnus:
            raise RequeteRefusee(f"Événement(s) inconnu(s) : {', '.join(sorted(inconnus))}")
        return sorted({c for e in evenements for c in e.noms_cellules(techno)})
    if p.type not in filtres:
        raise RequeteRefusee(f"Le périmètre « {p.type} » n'est pas encore disponible.")
    return sorted(Cellule.objects.filter(filtres[p.type], techno=techno).values_list("nom", flat=True))


def _intersecter(demandees: list[str] | None, autorisees: set[str] | None) -> list[str] | None:
    if autorisees is None:
        return demandees
    if demandees is None:
        return sorted(autorisees)
    return sorted(set(demandees) & autorisees)


def _fenetre(df: pd.DataFrame, fenetre: str) -> pd.DataFrame:
    if fenetre == "journee":
        return df
    debut, fin = (int(x) for x in fenetre.split("-"))
    heures = df["horodatage"].dt.hour
    return df[(heures >= debut) & (heures < fin)]


def _periode(horodatage: pd.Series, granularite: str) -> pd.Series:
    if granularite == "heure":
        return horodatage.dt.floor("h")
    jours = horodatage.dt.normalize()
    if granularite == "jour":
        return jours
    if granularite == "semaine":
        return jours - pd.to_timedelta(jours.dt.weekday, unit="D")
    return jours.dt.to_period("M").dt.to_timestamp()


def _entites(techno: str, granularite: str) -> dict[str, str]:
    """Cellule -> libellé de l'entité spatiale d'agrégation."""
    champ = {
        "secteur": "secteur__code",
        "site": "secteur__site__nom",
        "commune": "secteur__site__commune",
    }.get(granularite)
    if champ is None:
        return {}
    return {nom: valeur or NON_RATTACHEE for nom, valeur in Cellule.objects.filter(techno=techno).values_list("nom", champ)}


def verifier_periode(requete: RequeteKpi, resolution: str):
    """Refuse une période hors bornes ou trop longue pour la résolution lue (message affichable)."""
    p = requete.periode
    if p.debut < DATE_MIN or p.fin > DATE_MAX:
        raise RequeteRefusee(f"Période hors limites : choisissez des dates entre {DATE_MIN:%d/%m/%Y} "
                             f"et {DATE_MAX:%d/%m/%Y}.")
    jours = (p.fin - p.debut).days + 1
    if jours > JOURS_MAX[resolution]:
        if resolution == "heure":
            raise RequeteRefusee(
                f"Période trop longue pour un calcul horaire ({jours} jours, {JOURS_MAX['heure']} au plus) : "
                "choisissez un pas journalier (ou plus long) en journée complète, ou une période plus courte.")
        raise RequeteRefusee(f"Période trop longue ({jours} jours, {JOURS_MAX['jour']} au plus, soit 10 ans) : "
                             "choisissez une période plus courte.")


def couverture_donnees(df: pd.DataFrame, debut: date, fin: date) -> str | None:
    """Avertissement si les données lues ne couvrent pas toute la période demandée.

    Calculé d'après les horodatages réellement lus (vaut pour PostgreSQL comme pour la démo).
    """
    demande = f"du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"
    if df.empty:
        return f"aucune donnée sur la période demandée ({demande})."
    premier, dernier = df["horodatage"].min().date(), df["horodatage"].max().date()
    if premier > debut or dernier < fin:
        return (f"données disponibles du {premier:%d/%m/%Y} au {dernier:%d/%m/%Y} seulement "
                f"(période demandée : {demande}).")
    return None


def executer(requete: RequeteKpi, user, engine) -> Resultat:
    cat = catalogue()
    inconnus = [c for c in requete.kpis if c not in cat]
    if inconnus:
        raise RequeteRefusee(f"KPI inconnus : {', '.join(inconnus)}")
    if requete.fenetre_horaire == "heure_chargee":
        raise RequeteRefusee("La fenêtre « heure chargée » n'est pas encore disponible.")
    if requete.comparaison.type != "aucune":
        raise RequeteRefusee("La comparaison de périodes n'est pas encore disponible.")

    autorises = kpis_autorises(user, set(requete.kpis))
    refuses = set(requete.kpis) - autorises
    resultat = Resultat(requete=requete, par_techno=[])
    if refuses:
        resultat.avertissements.append(f"KPI non autorisés ignorés : {', '.join(sorted(refuses))}")

    resolution = "heure" if requete.granularite_temps == "heure" or requete.fenetre_horaire != "journee" else "jour"
    verifier_periode(requete, resolution)

    for techno in requete.techno:
        kpis = [cat[c] for c in requete.kpis if c in autorises and cat[c].techno == techno]
        if not kpis:
            continue
        cellules = _intersecter(cellules_du_perimetre(requete, techno), cellules_autorisees(user, techno))
        if cellules is not None and not cellules:
            resultat.avertissements.append(f"{techno} : aucune cellule accessible dans ce périmètre.")
            continue

        df = lire(engine, techno, resolution, colonnes_utilisees(kpis),
                  requete.periode.debut, requete.periode.fin, cellules)
        couverture = couverture_donnees(df, requete.periode.debut, requete.periode.fin)
        if couverture:
            resultat.avertissements.append(f"{techno} : {couverture}")
        df = _fenetre(df, requete.fenetre_horaire)

        sans_donnees = sorted(set(cellules) - set(df["cellule"])) if cellules is not None else []

        df = df.assign(periode=_periode(df["horodatage"], requete.granularite_temps))
        if requete.granularite_espace == "global":
            df = df.assign(entite="Global")
        elif requete.granularite_espace == "cellule":
            df = df.assign(entite=df["cellule"])
        else:
            correspondance = _entites(techno, requete.granularite_espace)
            df = df.assign(entite=df["cellule"].map(correspondance).fillna(NON_RATTACHEE))

        codes = [k.code for k in kpis]
        if len(df):
            table = agreger(df, kpis, par=["periode", "entite"])[codes]
            synthese = agreger(df, kpis, par=["entite"])[codes]
            globale = agreger(df, kpis, par=[])[codes].iloc[0].to_dict()
        else:
            table = synthese = pd.DataFrame(columns=codes)
            globale = dict.fromkeys(codes, float("nan"))
        resultat.par_techno.append(ResultatTechno(
            techno=techno,
            kpis=kpis,
            table=table,
            cellules_demandees=len(cellules) if cellules is not None else df["cellule"].nunique(),
            cellules_sans_donnees=sans_donnees,
            synthese=synthese,
            synthese_globale=globale,
        ))
    return resultat
