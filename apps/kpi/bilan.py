"""Analyse d'un résultat : la congestion d'abord, puis ce qui s'est bien et mal passé.

Lit les valeurs déjà calculées (``ResultatTechno`` : table par période et entité, synthèse
par entité et sur tout le périmètre, toutes en ratio de sommes) ; aucune nouvelle lecture
de la base, aucune moyenne de ratios.

- congestion : périodes (heures au pas horaire) où un KPI de congestion franchit son seuil,
  entité par entité (cellule…) ; plages horaires, pic, et ce que montrent au même moment le
  débit, les utilisateurs et les rejets dus à la charge ;
- signes de charge : blocages et rejets dus au manque de ressources (``config/bilan.yaml``) ;
- bien / mal : chaque KPI à seuil, sur la période (périmètre et entités) et période par période ;
- compteurs complémentaires de congestion absents du résultat.
"""

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from .catalogue import DefinitionKpi
from .recherche.affichage import _SUFFIXE_TECHNO, ESPACE_FINE, formater, valeur
from .recherche.vocabulaire import LIBELLES_TECHNO
from .service import Resultat, ResultatTechno

GRAVITES = {"critique": 0, "alerte": 1, "ponctuel": 2}
# Nombre d'éléments cités dans une phrase (entités, plages) avant « … ».
CITES_MAX = 3
PLAGES_MAX = 4
SIGNES_MAX = 10
# Entités en congestion détaillées (plages, impacts) ; les autres sont comptées.
CONGESTION_MAX = 15
SUGGESTIONS_MAX = 8
NIVEAUX = {"cellule": ("cellule", "cellules"), "secteur": ("secteur", "secteurs"), "site": ("site", "sites"),
           "commune": ("commune", "communes")}
TOUS = {"cellule": "toutes les cellules", "secteur": "tous les secteurs", "site": "tous les sites",
        "commune": "toutes les communes"}
UNITES_PERIODE = {"heure": ("h", "h"), "jour": ("jour", "jours"), "semaine": ("semaine", "semaines"),
                  "mois": ("mois", "mois")}


@dataclass
class CongestionEntite:
    """Entité (cellule, site…) dont un KPI de congestion a franchi son seuil."""

    techno: str  # « 4G »
    entite: str
    kpi: DefinitionKpi
    gravite: str  # critique | alerte
    periodes: int  # périodes au-delà du seuil d'alerte
    periodes_critiques: int
    periodes_mesurees: int
    pic: str  # « 97,3 % »
    pic_quand: str  # « 24/09 19h »
    plages: str  # « 24/09 18h–22h, 25/09 19h–21h »
    impacts: list[str] = field(default_factory=list)


@dataclass
class Signe:
    """Rejets ou blocages dus à la charge sur une entité."""

    techno: str
    entite: str
    kpi: DefinitionKpi
    periodes: int
    maximum: str
    plages: str


@dataclass
class Point:
    """Une ligne « bien passé » ou « mal passé »."""

    texte: str
    techno: str = ""
    gravite: str = ""  # critique | alerte | ponctuel ; vide : bien passé
    congestion: bool = False
    signe: bool = False  # signe de charge (rejets, blocages), après les KPI de congestion


@dataclass
class Suggestion:
    code: str
    libelle: str
    techno: str
    raison: str
    lien: str = ""  # renseigné par la vue : résultat avec ce compteur en plus


@dataclass
class Bilan:
    # La demande porte sur la congestion (KPI de congestion ou signes de charge demandés) :
    # section mise en avant, compteurs complémentaires proposés.
    congestion_sujet: bool = False
    constats: list[str] = field(default_factory=list)
    congestion: list[CongestionEntite] = field(default_factory=list)
    congestion_autres: int = 0
    signes: list[Signe] = field(default_factory=list)
    signes_autres: int = 0
    bien: list[Point] = field(default_factory=list)
    mal: list[Point] = field(default_factory=list)
    non_evalues: list[str] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    # Conseils d'affichage : détail par cellule, heure par heure.
    conseil_cellule: bool = False
    conseil_heure: bool = False
    unite_periode: str = "h"
    # Liens renseignés par la vue.
    lien_suggestions: str = ""
    lien_cellule: str = ""
    lien_heure: str = ""

    @property
    def vide(self) -> bool:
        return not (self.constats or self.bien or self.mal or self.suggestions)


# ------------------------------------------------------------------ configuration

@dataclass
class Configuration:
    signes: dict[str, dict[str, float]]  # techno -> code -> plancher
    complements: dict[str, dict[str, str]]  # techno -> code -> raison


def charger_configuration(chemin) -> Configuration:
    with open(chemin, encoding="utf-8") as f:
        brut = yaml.safe_load(f) or {}
    signes = {t: {c: float((d or {}).get("plancher") or 0) for c, d in (codes or {}).items()}
              for t, codes in (brut.get("signes_de_charge") or {}).items()}
    complements = {t: {c: str(r) for c, r in (codes or {}).items()}
                   for t, codes in (brut.get("complements") or {}).items()}
    return Configuration(signes=signes, complements=complements)


@lru_cache
def configuration() -> Configuration:
    from django.conf import settings

    return charger_configuration(settings.KPI_BILAN_PATH)


# ------------------------------------------------------------------ mise en forme

def _texte(v, k: DefinitionKpi) -> str:
    return ESPACE_FINE.join(formater(v, k.unite))


def _pluriel(n: int, mots: tuple[str, str]) -> str:
    return f"{n} {mots[0] if n == 1 else mots[1]}"


def _citer(noms: list[str], maximum: int = CITES_MAX) -> str:
    return ", ".join(noms[:maximum]) + ("…" if len(noms) > maximum else "")


def _quand(p: pd.Timestamp, granularite: str) -> str:
    if granularite == "heure":
        return f"{p:%d/%m} {p.hour}h"
    if granularite == "jour":
        return f"{p:%d/%m}"
    if granularite == "semaine":
        return f"semaine du {p:%d/%m}"
    return f"{p:%m/%Y}"


def plages(periodes, granularite: str) -> str:
    """Périodes consécutives regroupées : « 24/09 18h–22h, 25/09 19h » (fin exclue au pas horaire)."""
    periodes = sorted(periodes)
    if not periodes:
        return ""
    pas = {"heure": pd.Timedelta(hours=1), "jour": pd.Timedelta(days=1)}.get(granularite)
    groupes = [[periodes[0]]]
    for p in periodes[1:]:
        if pas is not None and p - groupes[-1][-1] == pas:
            groupes[-1].append(p)
        else:
            groupes.append([p])
    textes = []
    for g in groupes[:PLAGES_MAX]:
        debut, fin = g[0], g[-1]
        if len(g) == 1:
            textes.append(_quand(debut, granularite))
        elif granularite == "heure":
            fin = fin + pas
            if fin.date() == debut.date() or fin == debut.normalize() + pd.Timedelta(days=1):
                textes.append(f"{debut:%d/%m} {debut.hour}h–{fin.hour or 24}h")
            else:
                textes.append(f"{debut:%d/%m} {debut.hour}h → {fin:%d/%m} {fin.hour}h")
        else:
            textes.append(f"{_quand(debut, granularite)}–{_quand(fin, granularite)}")
    if len(groupes) > PLAGES_MAX:
        textes.append(f"+{len(groupes) - PLAGES_MAX} autres")
    return ", ".join(textes)


# ------------------------------------------------------------------ calcul vectorisé

def statuts(valeurs: pd.Series, k: DefinitionKpi) -> pd.Series:
    """Statut de chaque valeur (« critique », « alerte » ou « »), comme ``DefinitionKpi.statut``."""
    v = pd.to_numeric(valeurs, errors="coerce").to_numpy(dtype=float)
    sortie = np.full(v.shape, "", dtype=object)
    if k.seuils.alerte is None:
        return pd.Series(sortie, index=valeurs.index)
    with np.errstate(invalid="ignore"):
        def franchi(seuil):
            return v <= seuil if k.sens == "haut_est_mieux" else v >= seuil

        sortie[franchi(k.seuils.alerte)] = "alerte"
        if k.seuils.critique is not None:
            sortie[franchi(k.seuils.critique)] = "critique"
    return pd.Series(sortie, index=valeurs.index)


def _par_entite(masque: pd.Series) -> pd.Series:
    """Nombre de périodes vraies par entité (entités à 0 exclues)."""
    n = masque.groupby(level="entite", sort=False).sum().astype(int)
    return n[n > 0]


def _periodes(masque: pd.Series) -> dict[str, list]:
    """Entité -> périodes où le masque est vrai."""
    vrais = masque[masque]
    return {str(e): list(g.index.get_level_values("periode"))
            for e, g in vrais.groupby(level="entite", sort=False)}


def _pire(serie: pd.Series, k: DefinitionKpi):
    """(index, valeur) le plus défavorable de la série."""
    i = serie.idxmin() if k.sens == "haut_est_mieux" else serie.idxmax()
    return i, serie[i]


class _Techno:
    """Résultat d'une techno préparé une fois : valeurs numériques par (période, entité)."""

    def __init__(self, res: ResultatTechno, granularite: str, signes: dict[str, float]):
        self.res, self.granularite, self.signes = res, granularite, signes
        self.techno = LIBELLES_TECHNO.get(res.techno, res.techno)
        self.table = res.table.apply(pd.to_numeric, errors="coerce")
        self.synthese = (res.synthese.apply(pd.to_numeric, errors="coerce")
                         if res.synthese is not None and not res.synthese.empty else pd.DataFrame())

    def colonne(self, code: str) -> pd.Series:
        return self.table[code] if code in self.table else pd.Series(dtype=float)

    def sur_periode(self, code: str) -> pd.Series:
        if code not in self.synthese:
            return pd.Series(dtype=float)
        return self.synthese[code].dropna()

    def detail(self, entites) -> dict[str, pd.DataFrame]:
        """Entité -> valeurs de tous les KPI, indexées par période (entités choisies seulement)."""
        sous = self.table[self.table.index.get_level_values("entite").isin(list(entites))]
        return {str(e): g.droplevel("entite") for e, g in sous.groupby(level="entite", sort=False)}

    def touches(self, k: DefinitionKpi) -> pd.Series:
        """Périodes où un signe de charge compte : seuil d'alerte s'il existe, sinon le plancher."""
        v = self.colonne(k.code)
        if k.seuils.alerte is not None:
            return statuts(v, k) != ""
        return v > self.signes.get(k.code, 0.0)


def kpis_congestion(res: ResultatTechno) -> list[DefinitionKpi]:
    """KPI de congestion à seuil : leur franchissement signale une congestion."""
    return [k for k in res.kpis if k.categorie == "congestion" and k.seuils.alerte is not None
            and not k.decomposition_de]


# ------------------------------------------------------------------ congestion

def _nom(k: DefinitionKpi, techno: str) -> str:
    """« Taux de coupure data (3G) » sans doubler la techno déjà dans le libellé."""
    return f"{_SUFFIXE_TECHNO.sub('', k.libelle)} ({techno})"


def _hors_seuil(k: DefinitionKpi) -> str:
    return "sous le seuil" if k.sens == "haut_est_mieux" else "au-dessus du seuil"


def _cumul(n: int, granularite: str, niveau, global_: bool) -> str:
    """Total de périodes sur plusieurs entités : « 90 heures-cellule », « 12 jours-site »."""
    if global_:
        return _pluriel(n, UNITES_PERIODE[granularite])
    unite = {"heure": "heure", "jour": "jour", "semaine": "semaine", "mois": "mois"}[granularite]
    return f"{n} {unite}{'s' if n > 1 and unite != 'mois' else ''}-{niveau[0]}"


def _impacts(t: _Techno, entite: str, valeurs: pd.DataFrame, periodes, pic, k_congestion: DefinitionKpi) -> list[str]:
    """Ce que montrent les autres KPI du résultat aux périodes de congestion de l'entité."""
    lignes = []
    for k in t.res.kpis:
        if k.code == k_congestion.code or k.code not in valeurs or k.decomposition_de and k.code not in t.signes:
            continue
        serie = valeurs[k.code].dropna()
        pendant = serie[serie.index.isin(periodes)]
        if pendant.empty:
            continue
        sur_periode = t.sur_periode(k.code).get(entite)
        reference = f", contre {_texte(sur_periode, k)} sur toute la période" if sur_periode is not None else ""
        if k.pic and sur_periode is not None:  # pic de la période : un maximum, pas une moyenne
            reference = (" (pic de la période)" if pendant.max() >= sur_periode
                         else f" (pic de la période : {_texte(sur_periode, k)})")
        if k.categorie == "debit" and k.sens == "haut_est_mieux":
            p_bas, bas = _pire(pendant, k)
            au_pic = (f"{_texte(serie[pic], k)} à l'heure du pic, " if pic in serie.index and t.granularite == "heure"
                      else "")
            statut = k.statut(float(bas))
            seuil = k.seuils.critique if statut == "critique" else k.seuils.alerte
            lignes.append(f"{k.libelle} : {au_pic}{_texte(bas, k)} au plus bas ({_quand(p_bas, t.granularite)})"
                          f"{reference}" + (f" ; seuil {statut} ({_texte(seuil, k)}) franchi" if statut else "") + ".")
        elif k.code in t.signes:
            touches = pendant[t.touches(k).xs(entite, level="entite").reindex(pendant.index, fill_value=False)]
            if not touches.empty:
                lignes.append(f"{k.libelle} : jusqu'à {_texte(touches.max(), k)} pendant la congestion "
                              f"({_pluriel(len(touches), UNITES_PERIODE[t.granularite])}){reference}.")
        elif k.pic or k.categorie == "congestion":
            lignes.append(f"{k.libelle} : jusqu'à {_texte(pendant.max(), k)} pendant la congestion{reference}.")
    return lignes


@dataclass
class _Resume:
    """Congestion d'un KPI sur toutes les entités (avant la limite d'affichage)."""

    kpi: DefinitionKpi
    entites: int  # entités en congestion
    mesurees: int  # entités mesurées
    periodes: int  # total des périodes en congestion


def _congestion(t: _Techno) -> tuple[list[CongestionEntite], list[_Resume], int]:
    """Entités en congestion (les plus touchées détaillées), résumé par KPI, nombre non détaillé."""
    sortie, resumes, autres = [], [], 0
    for k in kpis_congestion(t.res):
        v = t.colonne(k.code)
        st = statuts(v, k)
        n = _par_entite(st != "")
        critiques = (st == "critique").groupby(level="entite", sort=False).sum()
        mesurees = int(v.notna().groupby(level="entite", sort=False).any().sum())
        resumes.append(_Resume(k, len(n), mesurees, int(n.sum())))
        ordre = sorted(n.index, key=lambda e: (-int(critiques.get(e, 0)), -int(n[e]), str(e)))
        autres += max(len(ordre) - CONGESTION_MAX, 0)
        for entite, valeurs in t.detail(ordre[:CONGESTION_MAX]).items():
            serie = valeurs[k.code].dropna()
            franchies = statuts(serie, k)
            franchies = franchies[franchies != ""]
            pic, v_pic = _pire(serie, k)
            nb_critiques = int((franchies == "critique").sum())
            sortie.append(CongestionEntite(
                techno=t.techno, entite=entite, kpi=k, gravite="critique" if nb_critiques else "alerte",
                periodes=len(franchies), periodes_critiques=nb_critiques, periodes_mesurees=len(serie),
                pic=_texte(v_pic, k), pic_quand=_quand(pic, t.granularite),
                plages=plages(franchies.index, t.granularite),
                impacts=_impacts(t, entite, valeurs, set(franchies.index), pic, k)))
    return sortie, resumes, autres


def _signes(t: _Techno) -> list[Signe]:
    sortie = []
    for k in t.res.kpis:
        if k.code not in t.signes:
            continue
        masque = t.touches(k)
        maxima = t.colonne(k.code).where(masque).groupby(level="entite", sort=False).max()
        for entite, periodes in _periodes(masque).items():
            sortie.append(Signe(techno=t.techno, entite=entite, kpi=k, periodes=len(periodes),
                                maximum=_texte(maxima.get(entite), k), plages=plages(periodes, t.granularite)))
    return sortie


def _constats(t: _Techno, congestion: list[CongestionEntite], resumes: list[_Resume], signes: list[Signe],
              niveau, global_: bool) -> list[str]:
    """Phrases de tête : la congestion de chaque techno en une ou deux phrases."""
    unite = UNITES_PERIODE[t.granularite]
    phrases = []
    for r in resumes:
        k = r.kpi
        v = t.colonne(k.code).dropna()
        if v.empty:
            continue
        seuil = _texte(k.seuils.alerte, k)
        if not r.entites:
            (periode, entite), pire = _pire(v, k)
            ou = "" if global_ else f" sur {entite}"
            phrases.append(f"{t.techno} : pas de congestion, {k.libelle} "
                           f"{'sous' if k.sens == 'bas_est_mieux' else 'au-dessus de'} {seuil} à chaque période "
                           f"(au plus {_texte(pire, k)}{ou}, le {_quand(periode, t.granularite)}).")
            continue
        pire = max((c for c in congestion if c.kpi.code == k.code),
                   key=lambda c: (c.periodes_critiques, c.periodes), default=None)
        if pire is None:
            continue
        critiques = (f" dont {pire.periodes_critiques} au-delà du seuil critique ({_texte(k.seuils.critique, k)})"
                     if pire.periodes_critiques else "")
        if global_:
            phrases.append(f"{t.techno} : congestion sur le périmètre ({k.libelle} au-delà de {seuil}) pendant "
                           f"{_pluriel(pire.periodes, unite)}{critiques} : {pire.plages} ; pic {pire.pic} "
                           f"le {pire.pic_quand}.")
            continue
        phrases.append(f"{t.techno} : {_pluriel(r.entites, niveau)} sur {r.mesurees} en congestion "
                       f"({k.libelle} au-delà de {seuil}), {_cumul(r.periodes, t.granularite, niveau, global_)} "
                       f"au total. La plus touchée : {pire.entite}, {_pluriel(pire.periodes, unite)}{critiques}, "
                       f"pic {pire.pic} le {pire.pic_quand}.")
    if signes:
        par_kpi: dict[str, list[Signe]] = {}
        for s in signes:
            par_kpi.setdefault(s.kpi.libelle, []).append(s)
        details = " ; ".join(f"{libelle} sur {_citer([s.entite for s in sorted(liste, key=lambda s: -s.periodes)])}"
                             for libelle, liste in par_kpi.items())
        phrases.append(f"{t.techno} : rejets ou blocages dus à la charge : {details}.")
    return phrases


# ------------------------------------------------------------------ bien / mal

def _evaluer(t: _Techno, niveau, global_: bool, signes: list[Signe]) -> tuple[list[Point], list[Point], list[str]]:
    """Chaque KPI à seuil : ce qui s'est mal passé (périmètre, entités sur la période, périodes
    isolées) et ce qui s'est bien passé (valeur d'ensemble et entités dans le seuil)."""
    res, techno, granularite = t.res, t.techno, t.granularite
    bien, mal, non_evalues = [], [], []
    for k in res.kpis:
        if k.decomposition_de or k.code in t.signes:
            continue
        if k.seuils.alerte is None:
            if k.categorie != "trafic":
                non_evalues.append(_nom(k, techno))
            continue
        v = valeur(res.synthese_globale.get(k.code))
        if v is None:
            continue
        nom, statut, seuil = _nom(k, techno), k.statut(v), _texte(k.seuils.alerte, k)
        par_entite = t.sur_periode(k.code)
        st = statuts(par_entite, k)
        entites = sorted(((str(e), par_entite[e], st[e]) for e in st[st != ""].index),
                         key=lambda e: (GRAVITES[e[2]], -e[1] if k.sens == "bas_est_mieux" else e[1]))
        n = _par_entite(statuts(t.colonne(k.code), k) != "")
        n_periodes = int(n.sum())
        congestion = k.categorie == "congestion"
        if statut or (entites and not global_):
            gravite = min([statut or "alerte", *(e[2] for e in entites)], key=GRAVITES.get)
            texte = f"{nom} : {_texte(v, k)} sur l'ensemble" + (f" ({statut})" if statut else "")
            if entites and not global_:
                cites = _citer([f"{e} ({_texte(x, k)})" for e, x, _ in entites])
                texte += f" ; {_pluriel(len(entites), niveau)} {_hors_seuil(k)} ({seuil}) sur la période : {cites}"
            if n_periodes:
                texte += f" ; {_cumul(n_periodes, granularite, niveau, global_)} {_hors_seuil(k)}"
            mal.append(Point(texte + ".", techno, gravite, congestion))
        elif n_periodes:
            touchees = [str(e) for e in n.sort_values(ascending=False, kind="stable").index]
            ou = "" if global_ else f", sur {_pluriel(len(touchees), niveau)} : {_citer(touchees)}"
            mal.append(Point(f"{nom} : dans le seuil sur la période ({_texte(v, k)}), mais "
                             f"{_cumul(n_periodes, granularite, niveau, global_)} {_hors_seuil(k)} ({seuil}){ou}.",
                             techno, "ponctuel", congestion))
        if not statut:
            texte = f"{nom} : {_texte(v, k)} sur l'ensemble, dans le seuil ({seuil})"
            if global_:
                texte += "" if n_periodes else " à chaque période"
            elif not entites and not n_periodes:
                texte += f" pour {TOUS.get(niveau[0], 'toutes les entités')}, à chaque période"
            else:
                sans = len(par_entite) - len({str(e) for e in n.index} | {e for e, _, _ in entites})
                if sans:
                    texte += f" ; {sans} {niveau[0] if sans == 1 else niveau[1]} sur {len(par_entite)} sans aucun dépassement"
            bien.append(Point(texte + ".", techno, "", congestion))
    # Signes de charge : touchés (mal) ou absents (bien, une ligne par techno).
    presents = [k for k in res.kpis if k.code in t.signes]
    par_kpi: dict[str, list[Signe]] = {}
    for s in signes:
        par_kpi.setdefault(s.kpi.code, []).append(s)
    for k in presents:
        if k.code in par_kpi:
            liste = sorted(par_kpi[k.code], key=lambda s: -s.periodes)
            maxi = max(liste, key=lambda s: s.periodes).maximum
            ou = "" if global_ else f" sur {_pluriel(len(liste), niveau)} : {_citer([s.entite for s in liste])}"
            mal.append(Point(f"{_nom(k, techno)} : {_cumul(sum(s.periodes for s in liste), granularite, niveau, global_)}"
                             f" avec des rejets{ou} (jusqu'à {maxi}).", techno, "alerte", True, True))
    absents = [k for k in presents if k.code not in par_kpi]
    if absents:
        bien.append(Point(f"{techno} : aucun rejet ni blocage dû à la charge ("
                          f"{', '.join(_SUFFIXE_TECHNO.sub('', k.libelle) for k in absents)}).", techno, "", True, True))
    if res.cellules_sans_donnees:
        mal.append(Point(f"{_pluriel(len(res.cellules_sans_donnees), ('cellule', 'cellules'))} {techno} sans aucune "
                         f"donnée : {_citer(res.cellules_sans_donnees, 5)}.", techno, "alerte"))
    elif res.cellules_demandees:
        bien.append(Point(f"Toutes les cellules {techno} du périmètre ({res.cellules_demandees}) ont remonté des "
                          f"données.", techno))
    return bien, mal, non_evalues


# ------------------------------------------------------------------ assemblage

def analyser(resultat: Resultat, catalogue_visible: dict[str, DefinitionKpi] | None = None,
             config: Configuration | None = None) -> Bilan:
    """Bilan du résultat. ``catalogue_visible`` : KPI que l'utilisateur peut voir (compteurs
    proposés) ; sans lui, aucune proposition."""
    config = config or configuration()
    req = resultat.requete
    granularite, espace = req.granularite_temps, req.granularite_espace
    niveau = NIVEAUX.get(espace, ("entité", "entités"))
    global_ = espace == "global"
    bilan = Bilan(unite_periode=UNITES_PERIODE[granularite][1])
    for res in resultat.par_techno:
        signes = config.signes.get(res.techno, {})
        if any(k.categorie == "congestion" or k.code in signes for k in res.kpis):
            bilan.congestion_sujet = True
        if not res.kpis or res.table is None or res.table.empty:
            continue
        t = _Techno(res, granularite, signes)
        congestion, resumes, autres = _congestion(t)
        liste_signes = _signes(t)
        bilan.constats += _constats(t, congestion, resumes, liste_signes, niveau, global_)
        bilan.congestion += congestion
        bilan.congestion_autres += autres
        bilan.signes += liste_signes
        if not any(k.seuils.alerte is not None or k.code in signes for k in res.kpis):
            bilan.non_evalues += [_nom(k, t.techno) for k in res.kpis if k.categorie != "trafic"
                                  and not k.decomposition_de]
            continue  # rien à juger (volumes de trafic…) : pas de bien / mal passé
        bien, mal, non_evalues = _evaluer(t, niveau, global_, liste_signes)
        bilan.bien += bien
        bilan.mal += mal
        bilan.non_evalues += non_evalues
    bilan.congestion.sort(key=lambda c: (GRAVITES[c.gravite], -c.periodes_critiques, -c.periodes, c.entite))
    bilan.signes.sort(key=lambda s: (-s.periodes, s.techno, s.entite))
    bilan.signes_autres = max(len(bilan.signes) - SIGNES_MAX, 0)
    bilan.signes = bilan.signes[:SIGNES_MAX]
    # Congestion d'abord (le sujet), puis les signes de charge, puis par gravité.
    bilan.mal.sort(key=lambda p: (not p.congestion, p.signe, GRAVITES.get(p.gravite, 9)))
    bilan.bien.sort(key=lambda p: (not p.congestion, p.signe))
    if bilan.congestion_sujet and catalogue_visible is not None:
        bilan.suggestions = _suggestions(resultat, catalogue_visible, config)
    if bilan.congestion_sujet:
        bilan.conseil_cellule = espace in ("global", "commune", "site")
        bilan.conseil_heure = granularite != "heure" and (req.periode.fin - req.periode.debut).days < 31
    return bilan


def _suggestions(resultat: Resultat, cat: dict[str, DefinitionKpi], config: Configuration) -> list[Suggestion]:
    """Compteurs de congestion absents du résultat : technos du résultat d'abord."""
    presents = set(resultat.requete.kpis)
    technos = list(dict.fromkeys([*resultat.requete.techno, *config.complements]))
    sortie = []
    for techno in technos:
        for code, raison in config.complements.get(techno, {}).items():
            if code in presents or code not in cat or cat[code].techno != techno:
                continue
            sortie.append(Suggestion(code, cat[code].libelle, LIBELLES_TECHNO.get(techno, techno), raison))
    return sortie[:SUGGESTIONS_MAX]


def sections_rapport(bilan: Bilan) -> list[tuple[str, list[str]]]:
    """Analyse en texte pour les rapports PowerPoint et PDF : (titre, lignes) par section."""
    sections = []
    if bilan.congestion_sujet and bilan.constats:
        lignes = list(bilan.constats)
        lignes += [f"{c.entite} ({c.techno}) : {c.periodes} {bilan.unite_periode} en congestion"
                   + (f" dont {c.periodes_critiques} critiques" if c.periodes_critiques else "")
                   + f", pic {c.pic} le {c.pic_quand} ; {c.plages}." for c in bilan.congestion]
        lignes += [f"{s.entite} ({s.techno}) : {s.kpi.libelle} sur {s.periodes} {bilan.unite_periode}, jusqu'à "
                   f"{s.maximum} ; {s.plages}." for s in bilan.signes]
        sections.append(("Congestion", lignes))
    if bilan.mal:
        sections.append(("Ce qui ne s'est pas bien passé",
                         [f"{'Ponctuel' if p.gravite == 'ponctuel' else p.gravite.capitalize()} : {p.texte}"
                          for p in bilan.mal]))
    if bilan.bien:
        sections.append(("Ce qui s'est bien passé", [p.texte for p in bilan.bien]))
    return sections
