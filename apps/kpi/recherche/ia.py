"""Interprétation par IA (facultative) : API Groq compatible OpenAI, en bibliothèque standard.

Garde-fous :
- le modèle reçoit le texte de la demande et la description du modèle de requête
  (codes KPI, types de périmètre, granularités) ; il ne reçoit JAMAIS de données KPI ;
- il ne produit que le JSON de requête (jamais de SQL) ;
- les lieux qu'il renvoie sont re-résolus par le résolveur local (périmètre de
  l'utilisateur), les codes KPI filtrés sur ceux visibles, puis la requête complète
  est validée par Pydantic (``RequeteKpi``) ;
- toute erreur (réseau, HTTP, JSON, validation) => repli sur les règles locales.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import date

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..requete import RequeteKpi
from .construction import GRANULARITES_ESPACE, GRANULARITES_TEMPS, TYPES_PERIMETRE, Contexte, construire
from .dates import Periode
from .interpretation import GLOBAL, Ambiguite, Demande, Interpretation
from .texte import Texte
from .vocabulaire import TECHNOS, vocabulaire

journal = logging.getLogger(__name__)

NOTE_REPLI = "Recherche IA indisponible, interprétation locale utilisée."
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class ErreurIA(RuntimeError):
    pass


def disponible() -> bool:
    return bool(settings.GROQ_API_KEY)


def prompt_systeme(aujourdhui: date, catalogue: dict) -> str:
    voc = vocabulaire()
    kpis = "\n".join(
        f"- {k.code} | {k.libelle} | {k.techno} | {k.unite}"
        + (f" | cause de {k.decomposition_de}" if k.decomposition_de else "")
        for k in catalogue.values())
    communes = ", ".join(sorted(voc.communes))
    regions = "; ".join(f"{r['libelle']} = communes de la région {'/'.join(r['regions'])}" for r in voc.regions)
    return f"""Tu convertis une demande en français sur les indicateurs (KPI) du réseau mobile de l'OPT
(Nouvelle-Calédonie : 4G = LTE, 3G = WCDMA) en un objet JSON de requête.
Date du jour : {JOURS[aujourdhui.weekday()]} {aujourdhui.isoformat()}.

Réponds UNIQUEMENT par un objet JSON, sans aucun texte autour, exactement de cette forme :
{{"techno": ["LTE", "WCDMA"], "kpis": ["code", ...],
  "perimetre": {{"type": "global|commune|site|trigramme|secteur|cellule|evenement", "valeurs": ["..."]}},
  "periode": {{"debut": "AAAA-MM-JJ", "fin": "AAAA-MM-JJ"}} ou null,
  "granularites": {{"temps": "heure|jour|semaine|mois" ou null, "espace": "global|commune|site|secteur|cellule" ou null}},
  "fenetre": "journee" | "H-H" (ex. "18-22") | "heure_chargee" | null,
  "manquants": ["kpis" | "periode" | "perimetre", ...]}}

Règles :
- Ne produis jamais de SQL ni de code. Tu n'as accès à aucune donnée : ne donne jamais de valeur de KPI.
- kpis : uniquement des codes de la liste ci-dessous. Pour les « causes », « pourquoi », « raisons »
  d'une coupure, mets le KPI parent et tous ses KPI « cause de » ce parent.
- Appels sans techno précisée : 3G (appels voix) + 4G (appels basculés CSFB, pas de VoLTE). SMS : 3G.
- perimetre : lieux tels que cités (commune, nom ou code de site, trigramme de 3 caractères, nom
  d'événement) ; type "global" et valeurs [] pour « réseau », « partout » ou aucun lieu.
  Communes : {communes}. Régions : {regions} (type "commune", valeurs = nom de la région).
- periode : bornes incluses. « la semaine dernière » = du lundi au dimanche précédents ; « les N derniers
  jours » = de J-N à J-1 ; mois sans année = année courante, ou précédente si ce mois est à venir.
  null et "periode" dans manquants si la demande ne donne aucune période.
- granularites : null si la demande ne les précise pas (l'application choisit). « pires sites »,
  « classement », « top » => espace "site".
- fenetre : « soirée » = "18-22" ; « en journée » = "7-20" ; null si rien n'est précisé.
- manquants : éléments indispensables absents de la demande ("kpis" si on ne sait pas quoi afficher).

KPI disponibles (code | libellé | techno | unité | cause de) :
{kpis}
"""


def appeler(texte: str, aujourdhui: date, catalogue: dict) -> dict:
    """Appel de l'API (température 0, réponse JSON) ; lève une exception en cas d'échec."""
    corps = {
        "model": settings.GROQ_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt_systeme(aujourdhui, catalogue)},
            {"role": "user", "content": texte[:500]},
        ],
    }
    requete = urllib.request.Request(
        settings.GROQ_URL, data=json.dumps(corps).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "stats-kpi-reseau/1.0"})
    with urllib.request.urlopen(requete, timeout=settings.GROQ_TIMEOUT) as reponse:
        brut = json.loads(reponse.read().decode("utf-8"))
    contenu = brut["choices"][0]["message"]["content"]
    donnees = json.loads(contenu)
    if not isinstance(donnees, dict):
        raise ErreurIA("réponse JSON inattendue")
    return donnees


class PerimetreIA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = "global"
    valeurs: list[str] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        v = v or "global"
        if v not in TYPES_PERIMETRE:
            raise ValueError(f"type de périmètre inconnu : {v}")
        return v

    @field_validator("valeurs", mode="before")
    @classmethod
    def _valeurs(cls, v):
        return [str(x) for x in (v if isinstance(v, list) else [v] if v is not None else []) if str(x).strip()]


class PeriodeIA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    debut: date
    fin: date


class GranularitesIA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    temps: str | None = None
    espace: str | None = None

    @field_validator("temps", "espace", mode="before")
    @classmethod
    def _connue(cls, v, info):
        permises = GRANULARITES_TEMPS if info.field_name == "temps" else GRANULARITES_ESPACE
        return v if v in permises else None  # valeur inconnue : défaut de l'application


class ReponseIA(BaseModel):
    """Schéma de la réponse JSON du modèle (validée avant tout usage)."""

    model_config = ConfigDict(extra="ignore")
    techno: list[str] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    perimetre: PerimetreIA | None = None
    periode: PeriodeIA | None = None
    granularites: GranularitesIA | None = None
    fenetre: str | None = None
    manquants: list[str] = Field(default_factory=list)

    @field_validator("techno", "kpis", "manquants", mode="before")
    @classmethod
    def _liste(cls, v):
        return [str(x) for x in (v if isinstance(v, list) else [v] if v is not None else [])]

    @field_validator("periode", mode="before")
    @classmethod
    def _periode(cls, v):
        return v if isinstance(v, dict) and v.get("debut") and v.get("fin") else None

    @field_validator("fenetre", mode="before")
    @classmethod
    def _fenetre(cls, v):
        if v in (None, "", "journee", "heure_chargee"):
            return v or None
        try:
            debut, fin = (int(x) for x in str(v).split("-"))
        except ValueError:
            raise ValueError(f"fenêtre illisible : {v}") from None
        return f"{debut}-{fin}" if 0 <= debut < fin <= 24 else None


def vers_demande(donnees: dict, contexte: Contexte, aujourdhui: date) -> tuple[Demande, list[str], list[str]]:
    """Réponse du modèle -> ``Demande`` ; schéma Pydantic, lieux re-résolus localement, codes filtrés."""
    if not isinstance(donnees, dict):
        raise ErreurIA("réponse JSON inattendue")
    r = ReponseIA.model_validate(donnees)  # ValidationError -> repli sur les règles
    d = Demande()
    notes, non_compris = [], []
    d.techno = [t for t in TECHNOS if t in {x.upper() for x in r.techno}]

    d.kpis = [c for c in r.kpis if c in contexte.catalogue]
    inconnus = [c for c in r.kpis if c not in contexte.catalogue]
    if inconnus:
        notes.append(f"KPI proposés par l'IA ignorés (inconnus ou non autorisés) : {', '.join(inconnus)}.")

    perimetre = r.perimetre or PerimetreIA()
    if perimetre.type == "global" or not perimetre.valeurs:
        d.global_demande = perimetre.type == "global"
    for valeur in perimetre.valeurs:
        # Pas de confiance aveugle : chaque lieu est re-résolu dans le périmètre de l'utilisateur.
        t = Texte(valeur)
        trouves = list(contexte.lieux.evenements_complets(t))
        lieux, ambiguites, notes_lieux = contexte.lieux.resoudre(t)
        for _indices, candidats in trouves:
            if len(candidats) == 1:
                lieux.insert(0, candidats[0])
            else:
                ambiguites.append(Ambiguite(valeur, candidats))
        notes += notes_lieux
        if not lieux and not ambiguites:
            non_compris.append(valeur)
        d.lieux += [lieu for lieu in lieux if lieu not in d.lieux and lieu != GLOBAL]
        d.ambiguites += ambiguites

    if r.periode:
        debut, fin = sorted((r.periode.debut, r.periode.fin))
        if debut <= aujourdhui:
            fin = min(fin, aujourdhui)
            d.periode = Periode(debut, fin, f"Du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}")
    if r.granularites:
        d.granularite_temps, d.granularite_espace = r.granularites.temps, r.granularites.espace
    if r.fenetre == "heure_chargee":
        d.heure_chargee = True
    elif r.fenetre:
        d.fenetre = r.fenetre
    return d, non_compris, notes


def interpreter(texte: str, aujourdhui: date, contexte: Contexte) -> Interpretation:
    from .regles import interpreter as interpreter_regles

    try:
        if not disponible():
            raise ErreurIA("clé GROQ_API_KEY absente")
        donnees = appeler(texte, aujourdhui, contexte.catalogue)
        demande, non_compris, notes = vers_demande(donnees, contexte, aujourdhui)
        interp = construire(demande, contexte, aujourdhui, source="ia", non_compris=non_compris, notes=notes)
        if interp.complete:
            RequeteKpi(**interp.params)  # validation Pydantic avant exécution
        return interp
    except Exception as e:  # réseau, HTTP, JSON, validation : repli sur les règles locales
        detail = f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else type(e).__name__
        journal.warning("Recherche IA en échec (%s) : repli sur les règles locales", detail)
        interp = interpreter_regles(texte, aujourdhui, contexte)
        interp.notes.insert(0, NOTE_REPLI)
        return interp
