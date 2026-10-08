"""Interprétation par règles locales (sans IA) d'une demande en langage libre.

Ordre des passes sur le texte normalisé (chaque mot reconnu est consommé) :
noms d'événements complets, fenêtre horaire, période, granularités, technologie,
vocabulaire (intentions, modificateurs, mots neutres), puis lieux (régions,
communes, noms de sites, codes, trigrammes). Les mots restants sont « non compris ».
"""

import re
from datetime import date

from .construction import Contexte, construire
from .dates import extraire_fenetre, extraire_granularites, extraire_periode
from .interpretation import Ambiguite, Demande, Interpretation
from .texte import Texte
from .vocabulaire import vocabulaire


def analyser(texte: str, aujourdhui: date, contexte: Contexte) -> tuple[Demande, list[str], list[str]]:
    """(demande comprise, mots non compris, notes)."""
    voc = vocabulaire()
    t = Texte(texte)
    d = Demande()
    notes: list[str] = []

    evenements = [(i, c) for i, c in contexte.lieux.evenements_complets(t)]

    fenetre, libelle = extraire_fenetre(t)
    if fenetre == "heure_chargee":
        d.heure_chargee = True
    elif fenetre:
        d.fenetre, d.fenetre_libelle = fenetre, libelle

    d.periode, notes_dates = extraire_periode(t, aujourdhui)
    notes += notes_dates
    d.granularite_temps, d.granularite_espace, d.classement = extraire_granularites(t)

    for techno, mots in voc.technos.items():
        motif = "|".join(re.escape(m) for m in sorted(mots, key=len, reverse=True))
        if any(True for _ in t.chercher(re.compile(rf"\b(?:{motif})\b"))) and techno not in d.techno:
            d.techno.append(techno)
    d.techno = [x for x in ("LTE", "WCDMA") if x in d.techno]

    for _indices, valeurs in voc.mots.trouver(t):
        for nature, code in valeurs:
            if nature == "intention" and code not in d.intentions:
                d.intentions.append(code)
            elif nature == "modificateur":
                if code == "causes":
                    d.causes = True
                elif code == "classement":
                    d.classement = True
                elif code == "heure_chargee":
                    d.heure_chargee = True
                elif code == "global":
                    d.global_demande = True
    # « Drop voix » / « drop data » précisent « drop » : on ne garde que la précision.
    if {"drop_voix", "drop_data"} & set(d.intentions):
        d.intentions = [i for i in d.intentions if i != "drop"]
    if "acces_voix" in d.intentions or "acces_data" in d.intentions:
        d.intentions = [i for i in d.intentions if i != "acces"]

    lieux, ambiguites, notes_lieux = contexte.lieux.resoudre(t)
    for indices, candidats in evenements:
        mots = " ".join(t.origines[i] for i in indices)
        if len(candidats) == 1:
            lieux.insert(0, candidats[0])
        else:
            ambiguites.insert(0, Ambiguite(mots, list(candidats)))
    d.lieux, d.ambiguites = lieux, ambiguites
    notes += notes_lieux

    non_compris = [m for m in t.non_compris() if not re.fullmatch(r"[\d/:\-]+", m)]
    return d, non_compris, notes


def interpreter(texte: str, aujourdhui: date, contexte: Contexte | None = None) -> Interpretation:
    contexte = contexte or Contexte.pour(None)
    demande, non_compris, notes = analyser(texte, aujourdhui, contexte)
    return construire(demande, contexte, aujourdhui, source="regles", non_compris=non_compris, notes=notes)
