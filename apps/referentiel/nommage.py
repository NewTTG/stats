"""Décodage des noms de cellules LTE / WCDMA vers (préfixe site, porteuse, secteur).

Conventions de nommage (confirmées) :

- LTE  : ``<Trigramme>e<S>`` (porteuse 1) ou ``<Trigramme>e<P><S>`` (porteuse P + 1)
    ``DZUe2``  -> trigramme DZU, porteuse 1, secteur 2
    ``DZUe12`` -> trigramme DZU, porteuse 2, secteur 2
    ``DZUe22`` -> trigramme DZU, porteuse 3, secteur 2
  Le secteur 4 suit la même règle (``XXXe4``, ``XXXe14``…).
- WCDMA : ``<codeSite><lettre>``
    cas général (3 secteurs) : secteur 1 = A/D/G/J, secteur 2 = B/E/H/K,
    secteur 3 = C/F/I/L, porteuses 1 à 4 dans cet ordre ;
    site à 4 secteurs (présence d'une lettre M) : A/B/C/D = secteurs 1-4 porteuse 1,
    J/K/L/M = secteurs 1-4 porteuse 2.

Le secteur référentiel (onglet Cell_File) s'écrit ``<codeSite><secteur>``.
"""

import re
from dataclasses import dataclass

_LTE = re.compile(r"^(?P<prefixe>.+?)e(?P<num>\d{1,2})$")
_WCDMA = re.compile(r"^(?P<prefixe>.+)(?P<lettre>[A-Z])$")

# lettre -> (porteuse, secteur)
_WCDMA_3_SECTEURS = {
    lettre: (porteuse, secteur)
    for porteuse, lettres in enumerate(["ABC", "DEF", "GHI", "JKL"], start=1)
    for secteur, lettre in enumerate(lettres, start=1)
}
_WCDMA_4_SECTEURS = {
    lettre: (porteuse, secteur)
    for porteuse, lettres in enumerate(["ABCD", "JKLM"], start=1)
    for secteur, lettre in enumerate(lettres, start=1)
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


def decoder_wcdma(nom: str, quatre_secteurs: bool = False) -> CelluleDecodee | None:
    """``quatre_secteurs`` : le site porte une cellule M (cf. ``sites_wcdma_4_secteurs``)."""
    m = _WCDMA.match(nom)
    table = _WCDMA_4_SECTEURS if quatre_secteurs else _WCDMA_3_SECTEURS
    if not m or m["lettre"] not in table:
        return None
    porteuse, secteur = table[m["lettre"]]
    return CelluleDecodee("WCDMA", m["prefixe"], porteuse, secteur)


def sites_wcdma_4_secteurs(noms: list[str]) -> set[str]:
    """Préfixes (codeSite) des sites WCDMA ayant une cellule M, donc 4 secteurs."""
    return {m["prefixe"] for m in map(_WCDMA.match, noms) if m and m["lettre"] == "M"}


def nom_site_normalise(nom: str) -> str:
    """Retire les suffixes ERBS ``bb`` / ``e`` (migration DUS -> Baseband)."""
    for suffixe in ("bb", "e"):
        if nom.endswith(suffixe) and len(nom) > len(suffixe):
            return nom[: -len(suffixe)]
    return nom
