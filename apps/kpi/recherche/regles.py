"""Interprétation par règles locales (sans IA) d'une demande en langage libre.

Ordre des passes sur le texte normalisé (chaque mot reconnu est consommé) :
noms d'événements complets, fenêtre horaire, période, granularités, technologie,
vocabulaire (intentions, modificateurs, mots neutres), puis lieux (régions,
communes, noms de sites, codes, trigrammes). Les mots restants sont « non compris ».
"""

import re
from datetime import date

from .construction import Contexte, construire
from .dates import extraire_fenetre, extraire_granularites, extraire_periode, semaine_suggeree
from .interpretation import Demande, Interpretation
from .texte import Texte
from .vocabulaire import vocabulaire


def _intentions(voc, correspondances, d: Demande) -> list[str]:
    """Intentions reconnues, dans l'ordre ; applique les modificateurs à ``d``.

    Un qualificatif (« voix », « appel », « data ») précise une intention présente qui
    l'accepte (drop -> drop voix, accès -> accès data, durée d'appel…) au lieu d'ouvrir
    l'intention Appels / Trafic : « taux de coupure voix » ne demande pas les appels.
    """
    elements = []  # (intentions du mot, qualificatif du mot)
    for _indices, valeurs in correspondances:
        intentions = [code for nature, code in valeurs if nature == "intention"]
        qualificatif = next((code for nature, code in valeurs if nature == "qualificatif"), None)
        for nature, code in valeurs:
            if nature == "modificateur":
                if code == "causes":
                    d.causes = True
                elif code == "classement":
                    d.classement = True
                elif code == "heure_chargee":
                    d.heure_chargee = True
                elif code == "global":
                    d.global_demande = True
                elif code == "comparaison":
                    d.comparaison = True
        if intentions or qualificatif:
            elements.append((intentions, qualificatif))

    absorbantes = {i for intentions, _ in elements for i in intentions if voc.intentions[i].absorbe}
    precisions: list[str] = []  # qualificatifs absorbés
    resultat: list[str] = []
    for intentions, qualificatif in elements:
        mot_qualificatif = qualificatif and all(not voc.intentions[i].absorbe for i in intentions)
        if mot_qualificatif and any(qualificatif in voc.intentions[i].absorbe for i in absorbantes):
            precisions.append(qualificatif)  # « voix » précise une intention présente
            continue
        resultat += intentions
    sortie: list[str] = []
    for code in resultat:
        absorbe = voc.intentions[code].absorbe
        cibles = [absorbe[q] for q in precisions if q in absorbe]
        if code in absorbe.values():  # intention déjà précise (drop voix) : gardée, + les autres précisions
            cibles = [code, *cibles]
        for cible in cibles or [code]:
            if cible not in sortie:
                sortie.append(cible)
    # « Drop voix » / « drop data » précisent « drop » : on ne garde que la précision.
    if {"drop_voix", "drop_data"} & set(sortie):
        sortie = [i for i in sortie if i != "drop"]
    if {"acces_voix", "acces_data"} & set(sortie):
        sortie = [i for i in sortie if i != "acces"]
    return sortie


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
    d.granularite_temps, d.granularite_espace, d.classement, d.classement_nombre = extraire_granularites(t)

    for techno, mots in voc.technos.items():
        motif = "|".join(re.escape(m) for m in sorted(mots, key=len, reverse=True))
        # Toutes les occurrences sont consommées (« 3G HSDPA » : « HSDPA » aussi).
        if list(t.chercher(re.compile(rf"\b(?:{motif})\b"))) and techno not in d.techno:
            d.techno.append(techno)
    if not d.techno:  # « drop E-RAB » = 4G, « CSSR » = 3G (sans consommer : le vocabulaire suit)
        d.techno = [techno for _indices, technos in voc.implicites.trouver(t, consommer=False) for techno in technos]
    else:  # « appels 3G et CSFB » : le CSFB ajoute la 4G à la 3G citée
        d.techno += [techno for _indices, technos in voc.ajoutees.trouver(t, consommer=False) for techno in technos]
    d.techno = [x for x in ("LTE", "WCDMA") if x in d.techno]
    # KPI ou technologie absents des données (« SINR », « 2G ») : note, la demande continue.
    for _indices, valeurs in voc.indisponibles.trouver(t):
        for libelle, est_techno in valeurs:
            notes.append(f"La {libelle} n'est pas dans les données : technologies disponibles, 4G et 3G."
                         if est_techno else f"KPI « {libelle} » non disponible dans les données.")

    # Provinces et régions avant le vocabulaire (« province », « région » y sont neutres).
    lieux_regions, ambiguites_regions = contexte.lieux.resoudre_regions(t)

    d.intentions = _intentions(voc, voc.mots.trouver(t), d)
    if d.periode is None:  # « Nouméa S40 » : « Semaine 40 » proposée en premier (après « S1 » = interface)
        d.semaine_suggeree = semaine_suggeree(t)

    lieux, ambiguites, notes_lieux = contexte.lieux.resoudre(t)
    lieux_ev, ambiguites_ev = contexte.lieux.lieux_evenements(t, evenements)
    lieux = lieux_ev + lieux_regions + lieux
    d.lieux = list(dict.fromkeys(lieux))
    d.ambiguites = ambiguites_ev + ambiguites_regions + ambiguites
    notes += notes_lieux

    non_compris = [m for m in t.non_compris() if not re.fullmatch(r"[\d/:\-]+", m)]
    return d, non_compris, notes


def interpreter(texte: str, aujourdhui: date, contexte: Contexte | None = None) -> Interpretation:
    contexte = contexte or Contexte.pour(None)
    demande, non_compris, notes = analyser(texte, aujourdhui, contexte)
    return construire(demande, contexte, aujourdhui, source="regles", non_compris=non_compris, notes=notes)
