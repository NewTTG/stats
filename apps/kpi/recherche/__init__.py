"""Recherche en langage libre : texte -> ``Interpretation`` -> ``RequeteKpi`` (brief §9).

Deux interprétations interchangeables : règles locales (``regles``, par défaut) et
IA (``ia``, facultative, repli automatique sur les règles). Dans les deux cas le
résultat est validé par Pydantic (``RequeteKpi``) avant exécution, et l'exécution
passe par ``service.executer`` (intersection avec le périmètre de l'utilisateur).
"""

from datetime import date

from .construction import Contexte, appliquer, construire, parametres_explicites
from .interpretation import Interpretation, Option, Puce, Question


def interpreter(texte: str, aujourdhui: date, contexte: Contexte, ia: bool = False) -> Interpretation:
    if ia:
        from .ia import interpreter as interpreter_ia

        return interpreter_ia(texte, aujourdhui, contexte)
    from .regles import interpreter as interpreter_regles

    return interpreter_regles(texte, aujourdhui, contexte)


def avec_parametres(interp: Interpretation, get, contexte: Contexte, aujourdhui: date) -> Interpretation:
    """Interprétation complétée par les paramètres explicites (réponses, puces modifiées)."""
    explicites = parametres_explicites(get)
    if not explicites:
        return interp
    demande, notes = appliquer(interp.demande, explicites, contexte, aujourdhui)
    return construire(demande, contexte, aujourdhui, source=interp.source, non_compris=interp.non_compris,
                      notes=[*interp.notes, *notes])


__all__ = ["Contexte", "Interpretation", "Option", "Puce", "Question", "avec_parametres", "interpreter"]
