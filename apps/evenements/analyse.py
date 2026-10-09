"""Analyse d'un événement (brief §6) : créneaux de l'événement contre les mêmes jours
et heures des N semaines précédentes, sur les cellules autorisées de l'utilisateur.

Toutes les valeurs sont des ratios de sommes. Pour un KPI additif (volume, trafic),
la référence est la moyenne des semaines, pas leur somme ; pour un KPI « pic », la
moyenne des pics hebdomadaires, pas leur maximum.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd
from django.utils import timezone

from apps.comptes.acces import cellules_autorisees, kpis_autorises
from apps.kpi.catalogue import DefinitionKpi, catalogue, kpis_principaux
from apps.kpi.moteur import agreger
from apps.kpi.service import colonnes_utilisees
from apps.kpi.source import lire
from apps.referentiel.models import Cellule
from apps.referentiel.secteurs import secteurs_a_la_date

from . import detection
from .models import Evenement, ReglagesAnomalies

NIVEAUX = {"secteur": "Secteur", "site": "Site"}
FORMAT_INSTANT = "%d/%m %Hh"
KPI_PRB, KPI_DEBIT = "lte_prb_dl_util", "lte_dl_user_thp"


class AnalyseImpossible(ValueError):
    """Message affichable expliquant pourquoi l'analyse ne peut pas être lancée."""


@dataclass
class LigneSynthese:
    kpi: DefinitionKpi
    valeur: float | None
    reference: float | None
    significatif: bool

    @property
    def ecart_pct(self):
        return detection.ecart_pct(self.valeur, self.reference)

    @property
    def statut(self) -> str:
        statut = self.kpi.statut(self.valeur)
        return statut or ("alerte" if self.significatif else "")


@dataclass
class Courbe:
    kpi: DefinitionKpi
    evenement: list
    reference: list
    ref_min: list
    ref_max: list


@dataclass
class AnalyseTechno:
    techno: str
    kpis: list[DefinitionKpi]
    nb_cellules: int
    synthese: list[LigneSynthese]
    instants: list[str]
    courbes: list[Courbe]
    cellules_sans_donnees: list[str]


@dataclass
class Analyse:
    evenement: Evenement
    niveau: str
    creneaux: list[tuple[datetime, datetime]]
    semaines: int
    par_techno: list[AnalyseTechno] = field(default_factory=list)
    anomalies: list[detection.Anomalie] = field(default_factory=list)
    classement: list[dict] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


def _local(dt: datetime) -> datetime:
    """Horodatages de la base KPI : heure locale sans fuseau."""
    return timezone.localtime(dt).replace(tzinfo=None) if timezone.is_aware(dt) else dt


def _plages_de_jours(fenetres) -> list[tuple]:
    """Fusionne les jours couverts par les fenêtres en plages contiguës (une lecture par plage)."""
    jours = sorted({(debut + timedelta(days=i)).date()
                    for _, _, debut, fin in fenetres
                    for i in range((fin - timedelta(microseconds=1)).date().toordinal() - debut.date().toordinal() + 1)})
    plages = []
    for j in jours:
        if plages and j == plages[-1][1] + timedelta(days=1):
            plages[-1][1] = j
        else:
            plages.append([j, j])
    return [tuple(p) for p in plages]


def _lire_fenetres(engine, techno, colonnes, cellules, fenetres) -> pd.DataFrame:
    """Lignes horaires de chaque fenêtre, avec ``semaine`` (0 = événement), ``creneau``
    et ``instant`` (heure ramenée sur l'événement)."""
    lu = [lire(engine, techno, "heure", colonnes, debut, fin, cellules) for debut, fin in _plages_de_jours(fenetres)]
    brut = pd.concat(lu, ignore_index=True) if lu else pd.DataFrame()
    morceaux = []
    for semaine, creneau, debut, fin in fenetres:
        if brut.empty:
            break
        m = brut[(brut["horodatage"] >= debut) & (brut["horodatage"] < fin)]
        morceaux.append(m.assign(semaine=semaine, creneau=creneau,
                                 instant=m["horodatage"] + pd.Timedelta(weeks=semaine)))
    if not morceaux:
        return pd.DataFrame(columns=["cellule", "horodatage", *colonnes, "semaine", "creneau", "instant"])
    return pd.concat(morceaux, ignore_index=True)


def _valeurs(df: pd.DataFrame, kpis: list[DefinitionKpi], par: list[str]):
    """``par`` non vide. (valeurs événement, référence, valeurs par semaine de référence), indexées par ``par``."""
    codes = [k.code for k in kpis]
    evt, ref = df[df["semaine"] == 0], df[df["semaine"] > 0]
    vide = pd.DataFrame(columns=codes)
    valeurs = agreger(evt, kpis, par)[codes] if len(evt) else vide
    if not len(ref):
        return valeurs, vide, pd.DataFrame(columns=codes, index=pd.MultiIndex.from_arrays([[]] * (len(par) + 1)))
    hebdo = agreger(ref, kpis, [*par, "semaine"])[codes]
    reference = agreger(ref, kpis, par)[codes]
    additifs = [k.code for k in kpis if k.additif]
    if additifs:
        moyennes = hebdo[additifs].groupby(level=list(range(len(par)))).mean()
        reference[additifs] = moyennes.reindex(reference.index)
    return valeurs, reference, hebdo


def _entites(techno: str, niveau: str, cellules: list[str], jour) -> dict[str, str]:
    if niveau == "secteur":  # disposition des secteurs le jour de l'événement
        connues = secteurs_a_la_date(techno, jour)
    else:
        connues = dict(Cellule.objects.filter(techno=techno, nom__in=cellules).values_list("nom", "secteur__site__nom"))
    return {c: connues.get(c) or c for c in cellules}  # non rattachée : son propre nom


def _instants(creneaux) -> list[pd.Timestamp]:
    heures = set()
    for debut, fin in creneaux:
        h = pd.Timestamp(debut).floor("h")
        while h < fin:
            heures.add(h)
            h += pd.Timedelta(hours=1)
    return sorted(heures)


def _liste(serie: pd.Series) -> list:
    return [None if pd.isna(v) else round(float(v), 4) for v in serie]


def _courbes(df, kpis, instants) -> list[Courbe]:
    if df.empty:
        return []
    valeurs, reference, hebdo = _valeurs(df, kpis, ["instant"])
    courbes = []
    for k in kpis:
        semaines = hebdo[k.code].unstack("semaine") if len(hebdo) else pd.DataFrame(index=instants)
        courbes.append(Courbe(
            kpi=k,
            evenement=_liste(valeurs[k.code].reindex(instants)) if k.code in valeurs else [None] * len(instants),
            reference=_liste(reference[k.code].reindex(instants)) if k.code in reference else [None] * len(instants),
            ref_min=_liste(semaines.min(axis=1).reindex(instants)),
            ref_max=_liste(semaines.max(axis=1).reindex(instants)),
        ))
    return courbes


def analyser(evenement: Evenement, user, engine, niveau: str = "secteur") -> Analyse:
    if niveau not in NIVEAUX:
        raise AnalyseImpossible(f"Niveau inconnu : {niveau}")
    creneaux = [(_local(c.debut), _local(c.fin)) for c in evenement.creneaux.all()]
    if not creneaux:
        raise AnalyseImpossible("Aucun créneau défini pour cet événement : à renseigner dans l'administration.")

    reglages = ReglagesAnomalies.courant()
    cat = catalogue()
    # Sans liste : KPI principaux (ni causes ni composants de composites, sélectionnables explicitement).
    demandes = set(evenement.kpis or kpis_principaux(cat))
    autorises = kpis_autorises(user, demandes & set(cat))
    n = evenement.semaines_reference
    fenetres = [(s, i, debut - timedelta(weeks=s), fin - timedelta(weeks=s))
                for s in range(n + 1) for i, (debut, fin) in enumerate(creneaux)]
    instants = _instants(creneaux)
    analyse = Analyse(evenement=evenement, niveau=niveau, creneaux=creneaux, semaines=n)
    if demandes - autorises:
        analyse.avertissements.append("Certains KPI ne vous sont pas autorisés et ne sont pas affichés.")

    for techno in ("LTE", "WCDMA"):
        kpis = [cat[c] for c in cat if c in autorises and cat[c].techno == techno]
        cellules = evenement.noms_cellules(techno)
        if not kpis or not cellules:
            continue
        permises = cellules_autorisees(user, techno)
        if permises is not None:
            hors = len(set(cellules) - permises)
            cellules = [c for c in cellules if c in permises]
            if hors:
                analyse.avertissements.append(f"{techno} : {hors} cellule(s) hors de votre périmètre ignorée(s).")
            if not cellules:
                continue

        colonnes = colonnes_utilisees(kpis)
        df = _lire_fenetres(engine, techno, colonnes, cellules, fenetres)
        entites = _entites(techno, niveau, cellules, min(debut for debut, _ in creneaux).date())
        df = df.assign(entite=df["cellule"].map(entites))

        valeurs, reference, hebdo = _valeurs(df.assign(tout="Global"), kpis, ["tout"])
        synthese = []
        for k in kpis:
            v = valeurs[k.code].iloc[0] if len(valeurs) else None
            r = reference[k.code].iloc[0] if len(reference) else None
            semaines = list(hebdo[k.code]) if len(hebdo) else []
            synthese.append(LigneSynthese(k, detection._nombre(v), detection._nombre(r), detection.ecart_significatif(
                k, v, r, semaines, reglages.ecart_sigma, reglages.ecart_pct)))

        evt = df[df["semaine"] == 0]
        presence = set(zip(evt["cellule"], evt["creneau"]))
        sans = detection.anomalies_sans_donnees(techno, entites, presence, len(creneaux))
        par_entite = _valeurs(df, kpis, ["entite"])
        analyse.anomalies += detection.anomalies_seuils(techno, par_entite[0], kpis)
        analyse.anomalies += detection.anomalies_ecarts(techno, *par_entite, kpis,
                                                        reglages.ecart_sigma, reglages.ecart_pct)
        analyse.anomalies += sans
        codes = {k.code for k in kpis}
        if KPI_PRB in codes and KPI_DEBIT in codes and len(evt):
            k_sat = [cat[KPI_PRB], cat[KPI_DEBIT]]
            horaire = agreger(evt, k_sat, ["cellule", "instant"])[[KPI_PRB, KPI_DEBIT]].reset_index()
            analyse.anomalies += detection.anomalies_saturation(
                techno, horaire, entites, KPI_PRB, KPI_DEBIT, reglages.saturation_prb, reglages.saturation_debit)

        analyse.par_techno.append(AnalyseTechno(
            techno=techno, kpis=kpis, nb_cellules=len(cellules), synthese=synthese,
            instants=[i.strftime(FORMAT_INSTANT) for i in instants],
            courbes=_courbes(df, kpis, instants),
            cellules_sans_donnees=sorted(c for c in cellules if c not in set(evt["cellule"])),
        ))

    if not analyse.par_techno:
        analyse.avertissements.append("Aucune cellule de l'événement n'est accessible avec vos droits.")
    analyse.anomalies.sort(key=detection.Anomalie.cle_tri)
    analyse.classement = detection.classement(analyse.anomalies)
    return analyse
