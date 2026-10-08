"""Vocabulaire de la recherche (``config/recherche.yaml``) : intentions -> KPI par techno."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .texte import Correspondeur, normaliser

TECHNOS = ("LTE", "WCDMA")
LIBELLES_TECHNO = {"LTE": "4G", "WCDMA": "3G"}


@dataclass
class Intention:
    code: str
    libelle: str
    mots: list[str]
    kpis: dict[str, list[str]]
    technos_defaut: list[str] = field(default_factory=lambda: list(TECHNOS))
    famille: bool = False
    # qualificatif (« voix », « data ») -> intention précise : « coupure voix » = drop voix
    absorbe: dict[str, str] = field(default_factory=dict)


@dataclass
class Vocabulaire:
    technos: dict[str, list[str]]
    intentions: dict[str, Intention]
    modificateurs: dict[str, list[str]]
    neutres: list[str]
    regions: list[dict]
    communes: dict[str, dict]
    pas_trigrammes: set[str]
    exemples: list[str]
    qualificatifs: dict[str, list[str]] = field(default_factory=dict)
    mots: Correspondeur = field(default_factory=Correspondeur, repr=False)

    def libelle_commune(self, nom: str) -> str:
        return (self.communes.get(nom) or {}).get("libelle") or nom.title()

    @property
    def familles(self) -> list[Intention]:
        return [i for i in self.intentions.values() if i.famille]


def charger_vocabulaire(chemin: Path) -> Vocabulaire:
    with open(chemin, encoding="utf-8") as f:
        brut = yaml.safe_load(f)
    intentions = {}
    for code, d in brut["intentions"].items():
        kpis = {t: list(v or []) for t, v in (d.get("kpis") or {}).items()}
        inconnues = set(kpis) - set(TECHNOS)
        if inconnues:
            raise ValueError(f"intention {code} : techno inconnue {sorted(inconnues)}")
        intentions[code] = Intention(code=code, libelle=d["libelle"], mots=[str(m) for m in d["mots"]], kpis=kpis,
                                     technos_defaut=list(d.get("technos_defaut") or TECHNOS),
                                     famille=bool(d.get("famille")), absorbe=dict(d.get("absorbe") or {}))
    voc = Vocabulaire(
        technos={t: [str(m) for m in mots] for t, mots in brut["technos"].items()},
        intentions=intentions,
        modificateurs={k: [str(m) for m in v] for k, v in brut.get("modificateurs", {}).items()},
        neutres=[str(m) for m in brut.get("neutres", [])],
        regions=brut.get("regions", []),
        communes={k: v or {} for k, v in brut.get("communes", {}).items()},
        pas_trigrammes={normaliser(str(m)) for m in brut.get("pas_trigrammes", [])},
        exemples=list(brut.get("exemples", [])),
        qualificatifs={k: [str(m) for m in v] for k, v in (brut.get("qualificatifs") or {}).items()},
    )
    for code, intention in intentions.items():
        for cible in intention.absorbe.values():
            if cible not in intentions:
                raise ValueError(f"intention {code} : absorbe vers une intention inconnue {cible!r}")
    # Un seul dictionnaire : l'expression la plus longue gagne entre intentions,
    # modificateurs et mots neutres (« taux d'accès » > « taux »).
    for mot in voc.neutres:
        voc.mots.ajouter(mot, ("neutre", None))
    for code, mots in voc.modificateurs.items():
        for mot in mots:
            voc.mots.ajouter(mot, ("modificateur", code))
    for intention in intentions.values():
        for mot in intention.mots:
            voc.mots.ajouter(mot, ("intention", intention.code))
    for code, mots in voc.qualificatifs.items():
        for mot in mots:
            voc.mots.ajouter(mot, ("qualificatif", code))
    return voc


@lru_cache
def vocabulaire() -> Vocabulaire:
    from django.conf import settings

    return charger_vocabulaire(settings.RECHERCHE_VOCABULAIRE_PATH)


def causes_de(code: str, catalogue: dict) -> list[str]:
    """KPI « causes » d'un KPI : ceux du catalogue dont ``decomposition_de`` vaut ``code``."""
    return [c for c, k in catalogue.items() if k.decomposition_de == code]


def kpis_intention(intention: Intention, technos: list[str], catalogue: dict) -> list[str]:
    """KPI d'une intention pour les technos données (codes absents du catalogue ignorés)."""
    return [c for t in technos for c in intention.kpis.get(t, []) if c in catalogue]
