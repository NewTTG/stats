"""Base KPI de démonstration (SQLite) générée à partir des 4 extraits CSV.

Permet d'utiliser l'application sans accès à la base KPI PostgreSQL : mêmes tables,
mêmes noms de colonnes (limitées à celles du catalogue + clés), sur les N derniers jours.

- base par cellule : ligne de l'extrait journalier (sinon de l'extrait horaire) ;
- compteurs : valeur journalière × profil horaire (creux la nuit, pics vers 12 h et
  18-21 h) × bruit ; succès tirés selon une loi binomiale (succès ≤ tentatives) ;
- taux (`_p`) : coupures tirées par cause (Σ causes = total en LTE, ≤ total en WCDMA),
  bornés à [0, 100] ; débits et PRB modulés par la charge ;
- incidents déterministes (graine) : site coupé quelques heures, pic de coupures,
  congestion PRB en soirée ;
- journalier = agrégat de l'horaire (sommes, moyennes pondérées pour les ratios).
"""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


@dataclass(frozen=True)
class Techno:
    nom: str
    cle: str
    site: str
    zone: str
    csv_heure: str
    csv_jour: str
    table_heure: str
    table_jour: str
    volume: str  # compteur principal (cellule « vivante » si > 0)
    disponibilite: str
    prb: str | None = None


TECHNOS = {
    "LTE": Techno("LTE", "EutranCell_Id", "ERBS_Id", "Tac", "lte_cell_hour.csv", "lte_cell_day.csv",
                  "lte_cell_hour", "lte_cell_day", "PayloadDl_mB", "CellAvaibilityD_p", "PrbVectUsageDl_p"),
    "WCDMA": Techno("WCDMA", "CellWcdma", "SiteWcdma", "LAC", "wcdma_cell_hour.csv", "wcdma_cell_day.csv",
                    "wcdma_cell_hour", "wcdma_cell_day", "PayloadPsHs_mb", "Avaibility_p"),
}

# Succès <= tentatives : compteur -> compteur dont il est une fraction (tirage binomial).
CHAINES = {
    "pmRrcConnEstabSucc": "pmRrcConnEstabAtt",
    "pmS1SigConnEstabAtt": "pmRrcConnEstabSucc",
    "pmErabEstabAttInit": "pmS1SigConnEstabAtt",
    "ErabEstabSucc_nb": "pmErabEstabAttInit",
    "ReqCsSucc": "ReqCs",
    "NbrSpeechCalls": "NbrSpeechCallsAtt",
    "ReqPsSucc": "ReqPs",
    "pmNoRabEstablishSuccessPacketInteractive": "pmNoRabEstablishAttemptPacketInteractive",
}
# Taux recalculés à partir des compteurs générés : colonne -> (succès, tentatives).
DERIVES = {"InitErabSuccRate_p": ("ErabEstabSucc_nb", "pmErabEstabAttInit")}
# Taux tirés par loi binomiale sur un compteur (aussi la pondération du journalier).
PONDERATIONS = {
    "ErabDropRate_p": "ErabEstabSucc_nb",
    "ErabDropRateMme_p": "ErabEstabSucc_nb",
    "S1signalingSuccRate_p": "pmS1SigConnEstabAtt",
    "HoIntraSucc_p": "pmHoPrepAttLteIntraF",
    "InitErabSuccRate_p": "pmErabEstabAttInit",
    "RabDropCs_p": "NbrSpeechCalls",
    "RabDropPs_p": "pmNoRabEstablishSuccessPacketInteractive",
}
_CAUSE_LTE = re.compile(r"^ErabDropEnb\w+_p$")
_CAUSE_WCDMA = re.compile(r"^RabDropCs\w+_p$")
# Coupures : total = Σ parts (+ reste non ventilé en WCDMA : les causes publiées n'en
# expliquent qu'environ la moitié).
COUPURES = {"LTE": ("ErabDropRate_p", "ErabDropRateMme_p", _CAUSE_LTE, False),
            "WCDMA": ("RabDropCs_p", None, _CAUSE_WCDMA, True)}
# Débits : moyenne harmonique pondérée par le volume (temps = volume / débit).
DEBITS = {"UserThpDl_kbps": "PayloadDl_mB", "UserThpUl_kbps": "PayloadUl_mB", "UserThpHs_kbps": "PayloadPsHs_mb"}
# Compteurs liés à la voix : plus faibles le week-end.
# Compteurs entiers (nombres d'événements) ; les volumes (_mB, _mb) et Erlangs restent décimaux.
ENTIERS = re.compile(r"^(pm|Req|Nbr)|_nb$")
VOIX = re.compile(r"^(NbrSpeechCalls|ReqCs|ReqSms|SpeechTraffic|CsfbRelVol)")

# Profils horaires (somme = 1) : creux la nuit, pic vers 12 h, pic du soir 18-21 h.
_SEMAINE = np.array([1.6, 1.0, .7, .6, .7, 1.2, 2.4, 3.8, 4.8, 5.0, 5.2, 5.6,
                     6.0, 5.6, 5.0, 4.9, 5.2, 5.8, 6.6, 7.0, 6.9, 6.2, 4.6, 2.9])
_WEEK_END = np.array([2.2, 1.5, 1.0, .8, .7, .8, 1.2, 2.0, 3.2, 4.4, 5.2, 5.8,
                      6.1, 5.9, 5.5, 5.3, 5.4, 5.9, 6.6, 7.1, 7.0, 6.4, 5.0, 3.4])
PROFIL_SEMAINE = _SEMAINE / _SEMAINE.sum()
PROFIL_WEEK_END = _WEEK_END / _WEEK_END.sum()


def _profil(jour: date) -> np.ndarray:
    return PROFIL_WEEK_END if jour.weekday() >= 5 else PROFIL_SEMAINE


def _facteur_week_end(jour: date, voix: bool) -> float:
    if jour.weekday() == 5:
        return .8 if voix else 1.0
    if jour.weekday() == 6:
        return .7 if voix else .95
    return 1.0


@dataclass
class Incident:
    nature: str
    description: str
    techno: str
    cellules: list[str]
    jours: list[date]
    heures: list[int]
    commune: str = ""


@dataclass
class Plan:
    """Cellules de base et incidents à injecter, par techno."""

    bases: dict[str, pd.DataFrame] = field(default_factory=dict)
    incidents: list[Incident] = field(default_factory=list)


# ------------------------------------------------------------------ lecture des CSV

def _nature(colonne: str, base: pd.Series, techno: Techno) -> str:
    if colonne == techno.disponibilite:
        return "dispo"
    if colonne == techno.prb:
        return "charge"
    if colonne.endswith("_kbps"):
        return "debit"
    if colonne.endswith("_p"):
        return "succes" if base.mean() > 50 else "taux"
    return "compteur"


def lire_bases(dossier: Path, colonnes: list[str], cellules_max: int | None = None) -> dict[str, pd.DataFrame]:
    """Une ligne par cellule et par techno : valeurs d'une journée type.

    Cellules mortes (indisponibles et sans trafic dans leur dernier état connu) écartées :
    elles apparaîtront comme « sans données », comme une cellule démontée.
    """
    bases = {}
    for t in TECHNOS.values():
        entete = pd.read_csv(dossier / t.csv_jour, sep=";", nrows=0).columns
        mesures = [c for c in colonnes if c in entete]
        usecols = [t.cle, t.site, t.zone, *mesures]
        types = {t.cle: str, t.site: str}
        jour = pd.read_csv(dossier / t.csv_jour, sep=";", usecols=usecols, dtype=types).drop_duplicates(t.cle)
        heure = pd.read_csv(dossier / t.csv_heure, sep=";", usecols=usecols, dtype=types).drop_duplicates(t.cle)
        compteurs = [c for c in mesures if _nature(c, jour[c], t) == "compteur"]

        # Extrait horaire (0 h) ramené à une journée : division par le poids de minuit.
        heure_j = heure.copy()
        heure_j[compteurs] = heure_j[compteurs] / PROFIL_SEMAINE[0]
        jour, heure_j = jour.set_index(t.cle), heure_j.set_index(t.cle)
        cellules = sorted(set(jour.index) | set(heure_j.index))
        if cellules_max:
            cellules = cellules[:cellules_max]

        actif_j = jour[t.volume] > 0
        actif_h = heure_j[t.volume] > 0
        mediane = jour.loc[actif_j, mesures].median()
        lignes, origine = [], []
        for c in cellules:
            dispo = heure_j.at[c, t.disponibilite] if c in heure_j.index else jour.at[c, t.disponibilite]
            if c in jour.index and actif_j.get(c, False):
                lignes.append(jour.loc[c]), origine.append("jour")
            elif c in heure_j.index and actif_h.get(c, False):
                lignes.append(heure_j.loc[c]), origine.append("heure")
            elif dispo >= 50:  # cellule vivante sans trafic dans les extraits : trafic médian
                ref = jour.loc[c] if c in jour.index else heure_j.loc[c]
                ligne = ref.copy()
                ligne[mesures] = mediane
                lignes.append(ligne), origine.append("mediane")
            # sinon : cellule morte, écartée
        base = pd.DataFrame(lignes)
        base.index.name = t.cle
        base["_origine"] = origine
        base[t.zone] = pd.to_numeric(base[t.zone], errors="coerce").fillna(0).astype(int)
        bases[t.nom] = base
    return bases


def _lisser(taux: pd.Series, poids: pd.Series) -> pd.Series:
    """Rapproche les taux de cellules peu chargées du taux réseau (une journée = peu d'échantillons)."""
    poids = poids.clip(lower=0).fillna(0)
    total = poids.sum()
    if total <= 0:
        return taux.fillna(0)
    reseau = (taux.fillna(0) * poids).sum() / total
    n0 = max(float(poids[poids > 0].median()) if (poids > 0).any() else 1.0, 1.0)
    return (taux.fillna(0) * poids + reseau * n0) / (poids + n0)


# ------------------------------------------------------------------ génération

class Generateur:
    def __init__(self, base: pd.DataFrame, techno: Techno, colonnes: list[str], rng: np.random.Generator):
        self.t = techno
        self.rng = rng
        self.cellules = list(base.index)
        self.n = len(self.cellules)
        self.colonnes = [c for c in colonnes if c in base.columns]
        self.nature = {c: _nature(c, base[c], techno) for c in self.colonnes}
        self.entiers = {c for c in self.colonnes if self.nature[c] == "compteur" and ENTIERS.search(c)}
        self.base = {c: base[c].astype(float).fillna(0).to_numpy() for c in self.colonnes}
        self.sites = base[techno.site].astype(str).to_numpy()
        self.zones = base[techno.zone].to_numpy()

        # Taux de base lissés, en probabilité (0-1).
        self.proba = {}
        total, autre, motif, reste = COUPURES[techno.nom]
        self.parts = [c for c in self.colonnes if motif.match(c)] + ([autre] if autre in self.colonnes else [])
        self.total = total if total in self.colonnes else None
        for c in self.colonnes:
            if self.nature[c] not in ("taux", "succes") or c in DERIVES:
                continue
            poids = base[PONDERATIONS.get(c, self.t.volume)] if PONDERATIONS.get(c, self.t.volume) in base else None
            valeur = base[c].clip(0, 100)
            if self.nature[c] == "succes":
                echec = _lisser(100 - valeur, poids) if poids is not None else 100 - valeur
                self.proba[c] = (1 - echec / 100).clip(0, 1).to_numpy()
            else:
                lisse = _lisser(valeur, poids) if poids is not None else valeur
                self.proba[c] = (lisse / 100).clip(0, 1).to_numpy()
        self.reste = None
        if self.total and reste:
            somme = sum(self.proba[c] for c in self.parts)
            self.reste = np.clip(self.proba[self.total] - somme, 0, 1)
        # Fractions des chaînes succès / tentatives.
        self.fractions = {}
        for enfant, parent in CHAINES.items():
            if enfant in self.base and parent in self.base:
                with np.errstate(divide="ignore", invalid="ignore"):
                    f = np.where(self.base[parent] > 0, self.base[enfant] / self.base[parent], .995)
                self.fractions[enfant] = np.clip(np.nan_to_num(f, nan=.995), 0, 1)

    def _bruit(self, sigma, forme=None):
        return self.rng.lognormal(0, sigma, forme or (self.n, 24))

    def jour(self, jour: date, incidents: list[Incident]) -> dict[str, np.ndarray]:
        """Valeurs horaires (cellules × 24) de toutes les colonnes pour une journée."""
        n, rng = self.n, self.rng
        profil = _profil(jour)
        charge_moyenne = profil * 24  # 1 = heure moyenne
        idx = {c: i for i, c in enumerate(self.cellules)}

        dispo = np.full((n, 24), 100.0)
        pannes = rng.random((n, 24)) < 0.0008
        dispo[pannes] = rng.uniform(0, 95, pannes.sum())
        boost = {c: np.ones((n, 24)) for c in self.parts + ([self.total] if self.total else [])}
        congestion = np.zeros((n, 24), dtype=bool)
        for inc in incidents:
            if inc.techno != self.t.nom or jour not in inc.jours:
                continue
            lignes = [idx[c] for c in inc.cellules if c in idx]
            sel = np.ix_(lignes, inc.heures)
            if inc.nature == "coupure":
                dispo[sel] = 0.0
                avant = [h - 1 for h in inc.heures[:1] if h > 0]
                cible = next((c for c in self.parts if "CellDt" in c), None)
                if avant and cible:
                    boost[cible][np.ix_(lignes, avant)] = 60.0
            elif inc.nature == "drop":
                for c in self.parts:
                    if re.search(r"UeLost|OutOfSync", c):
                        boost[c][sel] = 25.0
                    elif re.search(r"EnbHo|Sho", c):
                        boost[c][sel] = 10.0
            elif inc.nature == "congestion":
                congestion[sel] = True

        v: dict[str, np.ndarray] = {}
        facteur_cellule = self._bruit(.06, (n, 1))
        dispo_f = dispo / 100
        # Compteurs racines : base journalière × profil × bruit (Poisson pour les entiers).
        for c in self.colonnes:
            if self.nature[c] != "compteur" or c in CHAINES:
                continue
            moyenne = (self.base[c][:, None] * profil[None, :] * facteur_cellule
                       * _facteur_week_end(jour, bool(VOIX.match(c))) * self._bruit(.15) * dispo_f)
            v[c] = rng.poisson(moyenne).astype(float) if c in self.entiers else moyenne
        # Succès : fraction binomiale des tentatives (succès <= tentatives).
        for enfant in CHAINES:
            parent = CHAINES[enfant]
            if enfant in self.fractions and parent in v:
                echec = (1 - self.fractions[enfant])[:, None] * self._bruit(.4)
                p = np.clip(1 - echec, 0, 1)
                v[enfant] = rng.binomial(v[parent].astype(np.int64), p).astype(float)
        # Volume réel de l'heure rapporté à l'heure moyenne de la cellule : charge.
        vol = v.get(self.t.volume)
        with np.errstate(divide="ignore", invalid="ignore"):
            charge = vol / (self.base[self.t.volume][:, None] / 24) if vol is not None else charge_moyenne[None, :]
        charge = np.nan_to_num(charge, nan=0.0, posinf=0.0)

        def binomial_taux(c, p, si_vide=0.0):
            """Taux en % : succès (ou coupures) tirés sur le compteur de pondération."""
            poids = v.get(PONDERATIONS.get(c, ""))
            if poids is None:
                return np.clip(p * 100, 0, 100)
            k = rng.binomial(poids.astype(np.int64), np.clip(p, 0, 1))
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(poids > 0, 100 * k / poids, si_vide)

        for c in self.colonnes:
            nat = self.nature[c]
            if nat == "dispo":
                v[c] = dispo.copy()
            elif nat == "debit":
                base = self.base[c][:, None] * np.power(np.maximum(charge_moyenne, .05), -.3)[None, :]
                valeur = base * self._bruit(.15)
                valeur = np.where(congestion, valeur * .25, valeur)
                volume = v.get(DEBITS.get(c, ""), vol)
                v[c] = np.where(volume > 0, valeur, 0.0) if volume is not None else valeur
            elif nat == "charge":
                valeur = self.base[c][:, None] * np.power(np.maximum(charge, 0), .8) * self._bruit(.1)
                valeur = np.where(congestion, rng.uniform(92, 99.5, (n, 24)), valeur)
                v[c] = np.clip(valeur, 0, 100)
            elif nat == "succes" and c not in DERIVES:
                p = 1 - (1 - self.proba[c][:, None]) * self._bruit(.3)
                v[c] = binomial_taux(c, p, si_vide=100.0)
        for c, (succ, att) in DERIVES.items():
            if c in self.colonnes and succ in v and att in v:
                with np.errstate(divide="ignore", invalid="ignore"):
                    v[c] = np.where(v[att] > 0, 100 * v[succ] / v[att], 100.0)
        # Coupures : chaque cause tirée séparément, total = Σ causes (+ reste non ventilé).
        # Plafond ligne à ligne : les coupures d'une cause ne dépassent jamais ce qu'il reste
        # d'E-RAB / d'appels, donc Σ causes <= total <= 100 % sur chaque ligne.
        if self.total:
            poids = v.get(PONDERATIONS[self.total])
            k_total = np.zeros((n, 24))
            restant = poids.copy() if poids is not None else None
            for c in self.parts:
                p = self.proba[c][:, None] * self._bruit(.3) * boost[c] * np.where(congestion, 1.5, 1.0)
                if poids is None:
                    v[c] = np.clip(p * 100, 0, 100)
                    continue
                k = np.minimum(rng.binomial(poids.astype(np.int64), np.clip(p, 0, 1)).astype(float), restant)
                restant -= k
                k_total += k
                with np.errstate(divide="ignore", invalid="ignore"):
                    v[c] = np.where(poids > 0, 100 * k / poids, 0.0)
            if poids is not None:
                if self.reste is not None:
                    p = self.reste[:, None] * self._bruit(.3) * boost[self.total]
                    k_total += np.minimum(rng.binomial(poids.astype(np.int64), np.clip(p, 0, 1)), restant)
                with np.errstate(divide="ignore", invalid="ignore"):
                    v[self.total] = np.where(poids > 0, 100 * k_total / poids, 0.0)
        for c in self.colonnes:  # autres taux (ex. coupures data 3G)
            if c not in v and self.nature[c] == "taux":
                v[c] = binomial_taux(c, self.proba[c][:, None] * self._bruit(.3))
        for c in self.colonnes:
            if c not in v:
                v[c] = np.zeros((n, 24))
            if self.nature[c] in ("taux", "succes", "dispo", "charge"):
                v[c] = np.clip(v[c], 0, 100)
        return v

    def agreger_jour(self, v: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """Journalier = agrégat de l'horaire : sommes, moyennes pondérées des ratios."""
        j = {}
        for c in self.colonnes:
            nat = self.nature[c]
            if nat == "compteur":
                j[c] = v[c].sum(axis=1)
            elif nat == "debit":
                volume = v.get(DEBITS.get(c, ""), v.get(self.t.volume))
                with np.errstate(divide="ignore", invalid="ignore"):
                    temps = np.where(v[c] > 0, volume / v[c], 0.0).sum(axis=1)
                    j[c] = np.where(temps > 0, volume.sum(axis=1) / temps, 0.0)
            elif PONDERATIONS.get(c) in v or (c in self.parts and PONDERATIONS.get(self.total) in v):
                poids = v[PONDERATIONS.get(c) or PONDERATIONS[self.total]]
                total = poids.sum(axis=1)
                with np.errstate(divide="ignore", invalid="ignore"):
                    moyenne = np.where(total > 0, (v[c] * poids).sum(axis=1) / total,
                                       100.0 if nat == "succes" else 0.0)
                j[c] = moyenne
            else:
                j[c] = v[c].mean(axis=1)
        return j


# ------------------------------------------------------------------ incidents

def _sites(bases: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Cellules regroupées par site (référentiel si importé, sinon trigramme)."""
    sites: dict[str, dict] = {}
    try:
        from apps.referentiel.models import Cellule

        lignes = list(Cellule.objects.filter(secteur__isnull=False).values_list(
            "nom", "techno", "secteur__site__code_site", "secteur__site__commune", "secteur__site__nom"))
    except Exception:  # base applicative non migrée : regroupement par trigramme
        lignes = []
    presentes = {t: set(b.index) for t, b in bases.items()}
    if lignes:
        for nom, techno, code, commune, nom_site in lignes:
            if nom in presentes.get(techno, ()):
                s = sites.setdefault(code, {"commune": commune, "nom": nom_site, "LTE": [], "WCDMA": []})
                s[techno].append(nom)
    else:
        for techno, noms in presentes.items():
            for nom in noms:
                code = nom[:3]
                s = sites.setdefault(code, {"commune": "", "nom": code, "LTE": [], "WCDMA": []})
                s[techno].append(nom)
    for s in sites.values():
        s["LTE"].sort(), s["WCDMA"].sort()
    return sites


def _choisir(sites, rng, communes, besoin, techno="LTE"):
    """Un site parmi les 3 plus chargés des communes préférées (visible dans les agrégats)."""
    candidats = [code for code, s in sites.items() if besoin(s) and s["commune"] in communes]
    if not candidats:
        candidats = [code for code, s in sites.items() if besoin(s)]
    if not candidats:
        return None
    candidats = sorted(candidats, key=lambda c: (-sites[c]["volume"][techno], c))[:3]
    return candidats[int(rng.integers(len(candidats)))]


def planifier_incidents(bases, debut: date, fin: date, rng) -> list[Incident]:
    sites = _sites(bases)
    for s in sites.values():
        s["volume"] = {t: float(bases[t].loc[s[t], TECHNOS[t].volume].sum()) if s[t] else 0.0 for t in TECHNOS}

    def borne(j: date) -> date:
        return min(max(j, debut), fin)

    lundi = fin - timedelta(days=fin.weekday())
    incidents = []
    code = _choisir(sites, rng, {"PAITA", "MONT DORE"}, lambda s: s["LTE"] and s["WCDMA"])
    if code:
        s, jour = sites[code], borne(fin - timedelta(days=5))
        heures = list(range(10, 16))
        for techno in ("LTE", "WCDMA"):
            incidents.append(Incident("coupure", f"Site {s['nom']} ({code}, {s['commune']}) coupé le "
                                      f"{jour:%d/%m} de 10 h à 16 h", techno, s[techno], [jour], heures, s["commune"]))
    code = _choisir(sites, rng, {"KONE"}, lambda s: len(s["LTE"]) >= 2)
    if code:
        s, jour = sites[code], borne(fin - timedelta(days=20))
        incidents.append(Incident("drop", f"Pic de coupures 4G sur {s['nom']} ({code}, {s['commune']}) le {jour:%d/%m}",
                                  "LTE", s["LTE"][:6], [jour], list(range(7, 23)), s["commune"]))
    code = _choisir(sites, rng, {"NOUMEA"}, lambda s: len(s["WCDMA"]) >= 2, "WCDMA")
    if code:
        s, jour = sites[code], borne(lundi - timedelta(days=6))
        incidents.append(Incident("drop", f"Pic de coupures voix 3G sur {s['nom']} ({code}, {s['commune']}) "
                                  f"le {jour:%d/%m}", "WCDMA", s["WCDMA"][:6], [jour], list(range(7, 23)), s["commune"]))
    code = _choisir(sites, rng, {"DUMBEA"}, lambda s: len(s["LTE"]) >= 2)
    if code:
        s = sites[code]
        jours = [borne(fin - timedelta(days=i)) for i in range(4, -1, -1)]
        jours = sorted(set(jours))
        incidents.append(Incident("congestion", f"Congestion PRB 4G en soirée (18 h-22 h) sur {s['nom']} "
                                  f"({code}, {s['commune']}) du {jours[0]:%d/%m} au {jours[-1]:%d/%m}",
                                  "LTE", s["LTE"], jours, [18, 19, 20, 21], s["commune"]))
    return incidents


# ------------------------------------------------------------------ écriture SQLite

def _creer_table(conn, table: str, cles: list[tuple[str, str]], colonnes: list[str], entiers: set[str]):
    defs = [f'"{c}" {t}' for c, t in cles] + [f'"{c}" {"INTEGER" if c in entiers else "REAL"}' for c in colonnes]
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(f'CREATE TABLE "{table}" ({", ".join(defs)})')


def _inserer(conn, table: str, noms: list[str], colonnes_valeurs: list[list]):
    marques = ", ".join("?" for _ in noms)
    liste = ", ".join(f'"{c}"' for c in noms)
    conn.executemany(f'INSERT INTO "{table}" ({liste}) VALUES ({marques})', zip(*colonnes_valeurs))


def _valeurs(tableau: np.ndarray, entier: bool) -> list:
    if entier:
        return np.rint(tableau).astype(np.int64).tolist()
    return np.round(tableau, 6).tolist()


def generer(sortie: Path, jours: int = 30, graine: int = 42, fin: date | None = None,
            dossier: Path | None = None, cellules_max: int | None = None, journal=print) -> dict:
    """Génère la base de démonstration ; renvoie un résumé (lignes, incidents, durée)."""
    from apps.kpi.catalogue import catalogue_yaml
    from apps.kpi.service import colonnes_utilisees

    t0 = time.monotonic()
    dossier = Path(dossier or settings.BASE_DIR)
    fin = fin or timezone.localdate() - timedelta(days=1)
    debut = fin - timedelta(days=jours - 1)
    rng = np.random.default_rng(graine)
    colonnes = colonnes_utilisees(list(catalogue_yaml().values()))
    bases = lire_bases(dossier, colonnes, cellules_max)
    incidents = planifier_incidents(bases, debut, fin, rng)

    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    temporaire = sortie.with_suffix(".tmp")
    temporaire.unlink(missing_ok=True)
    conn = sqlite3.connect(temporaire)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    resume = {"debut": debut, "fin": fin, "lignes": {},
              "incidents": list(dict.fromkeys(i.description for i in incidents))}
    jours_liste = [debut + timedelta(days=i) for i in range(jours)]
    heures_txt = [f"{h:02d}:00:00" for h in range(24)]
    for nom, t in TECHNOS.items():
        gen = Generateur(bases[nom], t, colonnes, rng)
        cles_h = [(t.cle, "TEXT"), (t.site, "TEXT"), (t.zone, "INTEGER"), ("DateHour", "TEXT")]
        cles_j = [(t.cle, "TEXT"), (t.site, "TEXT"), (t.zone, "INTEGER"), ("DateDay", "TEXT")]
        _creer_table(conn, t.table_heure, cles_h, gen.colonnes, gen.entiers)
        _creer_table(conn, t.table_jour, cles_j, gen.colonnes, gen.entiers)
        cellules_h = np.repeat(np.array(gen.cellules, dtype=object), 24).tolist()
        sites_h = np.repeat(gen.sites, 24).tolist()
        zones_h = np.repeat(gen.zones, 24).tolist()
        noms_h = [c for c, _ in cles_h] + gen.colonnes
        noms_j = [c for c, _ in cles_j] + gen.colonnes
        n_h = n_j = 0
        for jour in jours_liste:
            v = gen.jour(jour, incidents)
            horodatages = [f"{jour:%Y-%m-%d} {h}" for h in heures_txt] * gen.n
            _inserer(conn, t.table_heure, noms_h, [cellules_h, sites_h, zones_h, horodatages]
                     + [_valeurs(v[c].ravel(), c in gen.entiers) for c in gen.colonnes])
            j = gen.agreger_jour(v)
            _inserer(conn, t.table_jour, noms_j, [gen.cellules, gen.sites.tolist(), gen.zones.tolist(),
                                                  [f"{jour:%Y-%m-%d}"] * gen.n]
                     + [_valeurs(j[c], c in gen.entiers) for c in gen.colonnes])
            n_h += gen.n * 24
            n_j += gen.n
        conn.execute(f'CREATE UNIQUE INDEX "ix_{t.table_heure}" ON "{t.table_heure}" ("DateHour", "{t.cle}")')
        conn.execute(f'CREATE INDEX "ix_{t.table_heure}_cellule" ON "{t.table_heure}" ("{t.cle}", "DateHour")')
        conn.execute(f'CREATE UNIQUE INDEX "ix_{t.table_jour}" ON "{t.table_jour}" ("DateDay", "{t.cle}")')
        conn.execute(f'CREATE INDEX "ix_{t.table_jour}_cellule" ON "{t.table_jour}" ("{t.cle}", "DateDay")')
        conn.commit()
        resume["lignes"][t.table_heure] = n_h
        resume["lignes"][t.table_jour] = n_j
        journal(f"{nom} : {gen.n} cellules, {n_h} lignes horaires, {n_j} lignes journalières")
    conn.execute("CREATE TABLE demo_info (cle TEXT PRIMARY KEY, valeur TEXT)")
    infos = {"genere_le": timezone.localtime().isoformat(timespec="seconds"), "graine": str(graine),
             "debut": debut.isoformat(), "fin": fin.isoformat(),
             "incidents": json.dumps(resume["incidents"], ensure_ascii=False)}
    conn.executemany("INSERT INTO demo_info VALUES (?, ?)", infos.items())
    conn.commit()
    conn.close()
    temporaire.replace(sortie)  # remplacement atomique : l'application ne lit jamais une base partielle
    resume["duree"] = time.monotonic() - t0
    return resume


class Command(BaseCommand):
    help = ("Génère une base KPI de démonstration (SQLite, données synthétiques) à partir des 4 extraits CSV, "
            "utilisée quand KPI_DB_HOST n'est pas renseigné.")

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=30, help="nombre de jours jusqu'à J-1 (défaut 30)")
        parser.add_argument("--sortie", type=Path, default=None,
                            help="fichier SQLite (défaut KPI_DEMO_SQLITE, data/kpi_demo.sqlite3)")
        parser.add_argument("--graine", type=int, default=42, help="graine du générateur aléatoire")
        parser.add_argument("--fin", type=date.fromisoformat, default=None, help="dernier jour (défaut J-1)")
        parser.add_argument("--csv", type=Path, default=None, help="dossier des 4 extraits CSV (défaut racine)")

    def handle(self, jours, sortie, graine, fin, csv, **options):
        if jours < 1 or jours > 400:
            raise CommandError("--jours doit être compris entre 1 et 400")
        sortie = sortie or Path(settings.KPI_DEMO_SQLITE)
        dossier = csv or Path(settings.BASE_DIR)
        for t in TECHNOS.values():
            for nom in (t.csv_heure, t.csv_jour):
                if not (dossier / nom).exists():
                    raise CommandError(f"extrait introuvable : {dossier / nom}")
        resume = generer(sortie, jours=jours, graine=graine, fin=fin, dossier=dossier,
                         journal=lambda m: self.stdout.write(m))
        self.stdout.write("Incidents simulés :")
        for i in resume["incidents"]:
            self.stdout.write(f"  - {i}")
        self.stdout.write(self.style.SUCCESS(
            f"Base de démonstration écrite dans {sortie} ({resume['debut']:%d/%m/%Y} → {resume['fin']:%d/%m/%Y}, "
            f"{resume['duree']:.0f} s)."))
