"""Analyse d'un événement (brief §6) : créneaux de l'événement contre les mêmes jours
et heures des N semaines précédentes, sur les cellules autorisées de l'utilisateur.

Toutes les valeurs sont des ratios de sommes. Pour un KPI additif (volume, trafic),
la référence est la moyenne des semaines, pas leur somme ; pour un KPI « pic », la
moyenne des pics hebdomadaires, pas leur maximum.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
from django.utils import timezone
from sqlalchemy.exc import SQLAlchemyError

from apps.comptes.acces import cellules_autorisees, kpis_autorises
from apps.kpi.catalogue import DefinitionKpi, catalogue, kpis_principaux
from apps.kpi.moteur import agreger
from apps.kpi.service import colonnes_utilisees
from apps.kpi.source import lire
from apps.referentiel.models import Cellule
from apps.referentiel.secteurs import secteurs_a_la_date

from . import detection, mobiles
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
    # Valeurs de l'événement par site et par cellule (courbes « par site » / « par cellule »).
    par_site: dict[str, list] = field(default_factory=dict)
    par_cellule: dict[str, list] = field(default_factory=dict)


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
    reference_libelle: str = ""


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


def _assembler(*morceaux: pd.DataFrame) -> pd.DataFrame:
    """Concatène l'événement et sa référence. Un morceau vide (période sans données) est écarté :
    ses colonnes « object » convertiraient sinon les mesures en texte (pandas >= 2.1)."""
    colonnes = list(dict.fromkeys(c for m in morceaux for c in m.columns))
    pleins = [m for m in morceaux if len(m)] or list(morceaux[:1])
    return pd.concat(pleins, ignore_index=True).reindex(columns=colonnes)


def _valeurs(df: pd.DataFrame, kpis: list[DefinitionKpi], par: list[str], ref_kpis=None):
    """``par`` non vide. (valeurs événement, référence, valeurs par semaine de référence), indexées par ``par``."""
    codes = [k.code for k in kpis]
    evt, ref = df[df["semaine"] == 0], df[df["semaine"] > 0]
    vide = pd.DataFrame(columns=codes)
    valeurs = agreger(evt, kpis, par)[codes] if len(evt) else vide
    if not len(ref) or ref_kpis == []:
        return valeurs, vide, pd.DataFrame(columns=codes, index=pd.MultiIndex.from_arrays([[]] * (len(par) + 1)))
    ref_kpis = kpis if ref_kpis is None else ref_kpis
    hebdo = agreger(ref, ref_kpis, [*par, "semaine"]).reindex(columns=codes)
    reference = agreger(ref, ref_kpis, par).reindex(columns=codes)
    additifs = [k.code for k in ref_kpis if k.additif]
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


def _detail(evt, kpis, par: str, instants) -> dict[str, dict[str, list]]:
    """KPI -> {site ou cellule -> valeurs horaires de l'événement}."""
    if evt.empty:
        return {}
    valeurs = agreger(evt, kpis, [par, "instant"])
    resultat = {}
    for k in kpis:
        if k.code not in valeurs:
            continue
        tableau = valeurs[k.code].unstack(par).reindex(instants)
        resultat[k.code] = {str(nom): _liste(tableau[nom]) for nom in sorted(tableau.columns, key=str)}
    return resultat


def _courbes(df, kpis, instants, sites: dict[str, str], ref_kpis=None) -> list[Courbe]:
    if df.empty:
        return []
    valeurs, reference, hebdo = _valeurs(df, kpis, ["instant"], ref_kpis)
    evt = df[df["semaine"] == 0]
    par_site = _detail(evt.assign(site=evt["cellule"].map(sites)), kpis, "site", instants)
    par_cellule = _detail(evt, kpis, "cellule", instants)
    courbes = []
    for k in kpis:
        semaines = hebdo[k.code].unstack("semaine") if len(hebdo) else pd.DataFrame(index=instants)
        courbes.append(Courbe(
            kpi=k,
            evenement=_liste(valeurs[k.code].reindex(instants)) if k.code in valeurs else [None] * len(instants),
            reference=_liste(reference[k.code].reindex(instants)) if k.code in reference else [None] * len(instants),
            ref_min=_liste(semaines.min(axis=1).reindex(instants)),
            ref_max=_liste(semaines.max(axis=1).reindex(instants)),
            par_site=par_site.get(k.code, {}),
            par_cellule=par_cellule.get(k.code, {}),
        ))
    return courbes


def analyser(evenement: Evenement, user, engine, niveau: str = "secteur", creneaux=None,
             reference=None, archive=None, archive_reference=None) -> Analyse:
    """``creneaux`` : période choisie à l'affichage (heure locale) ; à défaut, créneaux mémorisés."""
    if niveau not in NIVEAUX:
        raise AnalyseImpossible(f"Niveau inconnu : {niveau}")
    if creneaux is None:
        creneaux = [(_local(c.debut), _local(c.fin)) for c in evenement.creneaux.all()]
    creneaux = sorted((_local(d), _local(f)) for d, f in creneaux)
    if not creneaux:
        raise AnalyseImpossible("Choisissez la période à analyser.")

    from . import archives

    reglages = SimpleNamespace(**archive.donnees["reglages"]) if archive else ReglagesAnomalies.courant()
    cat = ({c: DefinitionKpi(**k) for c, k in archive.donnees["catalogue"].items()}
           if archive else catalogue())
    # Sans liste : KPI principaux (ni causes ni composants de composites, sélectionnables explicitement).
    demandes = set(cat) if archive else set(evenement.kpis or kpis_principaux(cat))
    autorises = kpis_autorises(user, demandes & set(cat))
    n = 1 if reference is not None else evenement.semaines_reference
    fenetres = [(s, i, debut - timedelta(weeks=s), fin - timedelta(weeks=s))
                for s in range(1 if reference is not None else n + 1)
                for i, (debut, fin) in enumerate(creneaux)]
    instants = _instants(creneaux)
    analyse = Analyse(evenement=evenement, niveau=niveau, creneaux=creneaux, semaines=n)
    analyse.reference_libelle = (archives.libelle(reference) if reference is not None else
        f"Mêmes jours et heures des {n} semaines précédentes : " + " ; ".join(
            archives.libelle([(d - timedelta(weeks=s), f - timedelta(weeks=s)) for d, f in creneaux])
            for s in range(1, n + 1)))
    if reference is not None:
        duree = lambda plages: sum((f - d for d, f in plages), timedelta())
        if duree(creneaux) != duree(reference):
            analyse.avertissements.append(
                f"Durées différentes : événement {duree(creneaux).total_seconds() / 3600:g} h, "
                f"référence {duree(reference).total_seconds() / 3600:g} h. "
                "Les volumes sont des totaux bruts, sans normalisation de durée.")
        analyse.avertissements.append("Courbes alignées par rang d'heure dans chaque période ; les heures absentes restent vides.")
    if demandes - autorises:
        analyse.avertissements.append("Certains KPI ne vous sont pas autorisés et ne sont pas affichés.")

    for techno in ("LTE", "WCDMA"):
        kpis = [cat[c] for c in cat if c in autorises and cat[c].techno == techno]
        cellules = (archive.donnees["technos"].get(techno, {}).get("cellules", [])
                    if archive else evenement.noms_cellules(techno))
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
        df = (archives.lire(archive, techno, cellules, creneaux) if archive else
              _lire_fenetres(engine, techno, colonnes, cellules, fenetres))
        premier_jour = min(debut for debut, _ in creneaux).date()
        entites = _entites(techno, niveau, cellules, premier_jour)
        sites = entites if niveau == "site" else _entites(techno, "site", cellules, premier_jour)
        if evenement.deploiements:  # remorques : disposition déclarée dans l'événement
            deploiements = evenement.deploiements
            entites.update((c, e) for c, e in mobiles.entites(deploiements, techno, niveau).items() if c in entites)
            sites.update((c, e) for c, e in mobiles.entites(deploiements, techno, "site").items() if c in sites)
        if archive:
            figes = archive.donnees["technos"].get(techno, {}).get("entites", {})
            entites = {c: figes.get(niveau, {}).get(c, c) for c in cellules}
            sites = {c: figes.get("site", {}).get(c, c) for c in cellules}
        df = df.assign(entite=df["cellule"].map(entites))
        mobiles_connues = set(Cellule.objects.filter(techno=techno, secteur__site__mobile=True)
                              .values_list("nom", flat=True)) | set(evenement.cellules_deployees(techno))
        if archive:
            mobiles_connues |= set(mobiles.cellules(archive.donnees["deploiements"], techno))
        if reference is None:
            if archive:
                # Seuls les créneaux de l'édition sont figés. La moyenne hebdomadaire est une référence vivante.
                try:
                    historique = (_lire_fenetres(engine, techno, colonnes,
                        [c for c in cellules if c not in mobiles_connues], [f for f in fenetres if f[0] > 0])
                        if engine is not None else df.iloc[:0].copy())
                except SQLAlchemyError:
                    historique = df.iloc[:0].copy()
                    analyse.avertissements.append("Source indisponible : référence hebdomadaire en N/D, données de l'édition conservées.")
                historique = historique.assign(entite=historique["cellule"].map(entites))
                df = _assembler(df, historique)
            else:
                df = df[(df["semaine"] == 0) | ~df["cellule"].isin(mobiles_connues)].copy()

        axe = instants
        ref_kpis = None
        if reference is not None:
            ref_cellules = (archive_reference.donnees["technos"].get(techno, {}).get("cellules", [])
                            if archive_reference else cellules)
            if not archive_reference:
                ref_cellules = [c for c in ref_cellules if c not in mobiles_connues]
            if permises is not None:
                ref_cellules = [c for c in ref_cellules if c in permises]
            if set(ref_cellules) != set(cellules):
                analyse.avertissements.append(f"{techno} : périmètres différents, {len(cellules)} cellule(s) "
                                              f"dans l'événement et {len(ref_cellules)} en référence.")
            try:
                ref = (archives.lire(archive_reference, techno, ref_cellules, reference) if archive_reference else
                       _lire_fenetres(engine, techno, colonnes, ref_cellules,
                                     [(0, i, d, f) for i, (d, f) in enumerate(reference)])
                       if engine is not None else df.iloc[:0].copy())
            except SQLAlchemyError:
                if not archive:
                    raise
                ref = df.iloc[:0].copy()
                analyse.avertissements.append("Source indisponible : référence en N/D, données de l'édition conservées.")
            if archive_reference:
                mapping = archive_reference.donnees["technos"].get(techno, {}).get("entites", {}).get(niveau, {})
            else:
                mapping = entites
            ref = ref.assign(entite=ref["cellule"].map(mapping), semaine=1)
            # Un axe ordinal commun conserve également les heures supplémentaires de la référence.
            ref_instants = _instants(reference)
            axe = list(range(max(len(instants), len(ref_instants))))
            df["instant"] = df["horodatage"].map({v: i for i, v in enumerate(instants)})
            ref["instant"] = ref["horodatage"].map({v: i for i, v in enumerate(ref_instants)})
            df = _assembler(df, ref)
            for colonne in colonnes:
                if colonne not in df:
                    df[colonne] = float("nan")
            if archive_reference:
                disponibles = set(archive_reference.donnees["catalogue"])
                if set(k.code for k in kpis) - disponibles:
                    analyse.avertissements.append(f"{techno} : les KPI absents de l'édition de référence restent en N/D côté référence.")
                ref_kpis = [DefinitionKpi(**archive_reference.donnees["catalogue"][k.code]) for k in kpis if k.code in disponibles]
        if archive and engine is None and not archive_reference:
            analyse.avertissements.append("Source indisponible ou non configurée : référence en N/D, données de l'édition conservées.")

        valeurs, moyennes, hebdo = _valeurs(df.assign(tout="Global"), kpis, ["tout"], ref_kpis)
        synthese = []
        for k in kpis:
            v = valeurs[k.code].iloc[0] if len(valeurs) else None
            r = moyennes[k.code].iloc[0] if len(moyennes) else None
            semaines = list(hebdo[k.code]) if len(hebdo) else []
            synthese.append(LigneSynthese(k, detection._nombre(v), detection._nombre(r), detection.ecart_significatif(
                k, v, r, semaines, reglages.ecart_sigma, reglages.ecart_pct)))

        evt = df[df["semaine"] == 0]
        presence = set(zip(evt["cellule"], evt["creneau"]))
        sans = detection.anomalies_sans_donnees(techno, entites, presence, len(creneaux))
        par_entite = _valeurs(df, kpis, ["entite"], ref_kpis)
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
            instants=([f"Heure {i + 1}" for i in axe] if reference is not None else
                      [i.strftime(FORMAT_INSTANT) for i in instants]),
            courbes=_courbes(df, kpis, axe, sites, ref_kpis),
            cellules_sans_donnees=sorted(c for c in cellules if c not in set(evt["cellule"])),
        ))

    if not analyse.par_techno:
        analyse.avertissements.append("Aucune cellule de l'événement n'est accessible avec vos droits.")
    analyse.anomalies.sort(key=detection.Anomalie.cle_tri)
    analyse.classement = detection.classement(analyse.anomalies)
    return analyse
