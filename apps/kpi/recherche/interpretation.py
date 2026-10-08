"""Résultat de l'interprétation d'une demande en langage libre.

Une ``Interpretation`` contient un fragment de ``RequeteKpi`` (``params``), ce qui a
été compris (puces modifiables), les questions à poser quand il manque quelque chose
(jamais de blocage) et les mots non compris.
"""

from dataclasses import dataclass, field
from typing import Literal

from .dates import Periode

CHAMPS_REQUIS = ("techno", "kpis", "perimetre", "periode")


@dataclass(frozen=True)
class Lieu:
    """Périmètre reconnu : type de ``RequeteKpi.perimetre`` + valeurs + libellé affiché."""

    type: str
    valeurs: tuple[str, ...]
    libelle: str
    detail: str = ""

    @property
    def params(self) -> dict:
        """Paramètres GET équivalents."""
        if self.type == "global":
            return {"perimetre_type": "global", "perimetre_valeurs": ""}
        return {"perimetre_type": self.type, "perimetre_valeurs": ", ".join(self.valeurs)}


GLOBAL = Lieu("global", (), "Tout le réseau autorisé")


@dataclass
class Ambiguite:
    texte: str  # mots saisis
    candidats: list[Lieu]
    # Lieu non reconnu (faute de frappe, nom inconnu) : candidats approchés, éventuellement aucun.
    non_reconnu: bool = False


@dataclass
class Option:
    libelle: str
    params: dict  # paramètres GET ajoutés à la recherche courante (ex. {"periode": "7j"})
    detail: str = ""


@dataclass
class Question:
    champ: str
    texte: str
    options: list[Option] = field(default_factory=list)
    saisie: Literal["aucune", "dates", "texte"] = "aucune"


@dataclass
class Puce:
    """Élément compris, affiché comme une puce cliquable (modifiable)."""

    champ: str  # techno | kpis | perimetre | periode | granularite_temps | granularite_espace | fenetre_horaire
    libelle: str
    titre: str = ""  # détail (infobulle)
    defaut: bool = False  # valeur par défaut (non dite dans la demande)


@dataclass
class Demande:
    """Ce qui a été compris de la demande, avant les valeurs par défaut."""

    techno: list[str] = field(default_factory=list)
    intentions: list[str] = field(default_factory=list)
    causes: bool = False
    kpis: list[str] = field(default_factory=list)  # codes explicites (IA, paramètres)
    lieux: list[Lieu] = field(default_factory=list)
    ambiguites: list[Ambiguite] = field(default_factory=list)
    global_demande: bool = False
    periode: Periode | None = None
    fenetre: str | None = None
    fenetre_libelle: str | None = None
    granularite_temps: str | None = None
    granularite_espace: str | None = None
    classement: bool = False
    heure_chargee: bool = False
    comparaison: bool = False  # « comparaison », « comparer », « vs »


@dataclass
class Interpretation:
    params: dict = field(default_factory=dict)  # fragment de RequeteKpi
    compris: list[Puce] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    non_compris: list[str] = field(default_factory=list)
    source: Literal["regles", "ia"] = "regles"
    notes: list[str] = field(default_factory=list)
    demande: Demande | None = field(default=None, repr=False)

    @property
    def complete(self) -> bool:
        return not self.questions and all(self.params.get(c) for c in CHAMPS_REQUIS)

    def puce(self, champ: str) -> Puce | None:
        return next((p for p in self.compris if p.champ == champ), None)
