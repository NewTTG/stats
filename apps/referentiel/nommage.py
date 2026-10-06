"""Décodage des noms de cellules LTE / WCDMA vers (préfixe site, porteuse, secteur).

Conventions observées dans les exports (hypothèses à valider, cf. docs/questions.md) :

- LTE  : ``<Trigramme>e<S>`` (porteuse 1) ou ``<Trigramme>e<P><S>`` (porteuse P + 1)
    ``DZUe2``  -> trigramme DZU, porteuse 1, secteur 2
    ``DZUe12`` -> trigramme DZU, porteuse 2, secteur 2   (confirmé)
    ``DZUe22`` -> trigramme DZU, porteuse 3, secteur 2
- WCDMA : ``<codeSite><lettre>``
    A/B/C -> porteuse 1, secteurs 1-3 ; D/E/F -> porteuse 2 ; J/K/L -> porteuse 3 ;
    G/H/I -> secteurs 4-6 (porteuse 1) ; M -> secteur 7 (porteuse 1).

Le secteur référentiel (onglet Cell_File) s'écrit ``<codeSite><secteur>``.
"""

import re
from dataclasses import dataclass

_LTE = re.compile(r"^(?P<prefixe>.+?)e(?P<num>\d{1,2})$")
_WCDMA = re.compile(r"^(?P<prefixe>.+)(?P<lettre>[A-Z])$")

_WCDMA_LETTRES = {
    "A": (1, 1), "B": (1, 2), "C": (1, 3),
    "D": (2, 1), "E": (2, 2), "F": (2, 3),
    "J": (3, 1), "K": (3, 2), "L": (3, 3),
    "G": (1, 4), "H": (1, 5), "I": (1, 6),
    "M": (1, 7),
}


@dataclass(frozen=True)
class CelluleDecodee:
    techno: str
    prefixe: str  # trigramme (LTE) ou codeSite (WCDMA)
    porteuse: int
    secteur: int


def decoder_lte(nom: str) -> CelluleDecodee | None:
    m = _LTE.match(nom)
    if not m:
        return None
    num = m["num"]
    porteuse, secteur = (1, int(num)) if len(num) == 1 else (int(num[0]) + 1, int(num[1]))
    return CelluleDecodee("LTE", m["prefixe"], porteuse, secteur)


def decoder_wcdma(nom: str) -> CelluleDecodee | None:
    m = _WCDMA.match(nom)
    if not m or m["lettre"] not in _WCDMA_LETTRES:
        return None
    porteuse, secteur = _WCDMA_LETTRES[m["lettre"]]
    return CelluleDecodee("WCDMA", m["prefixe"], porteuse, secteur)


def nom_site_normalise(nom: str) -> str:
    """Retire les suffixes ERBS ``bb`` / ``e`` (migration DUS -> Baseband)."""
    for suffixe in ("bb", "e"):
        if nom.endswith(suffixe) and len(nom) > len(suffixe):
            return nom[: -len(suffixe)]
    return nom
