"""Période analysée d'un événement : créneaux choisis à l'affichage (paramètres ``debut`` / ``fin``
répétés, heure de Nouméa), à défaut les créneaux mémorisés avec l'événement.

Un même lieu sert d'une édition à l'autre (foire annuelle, marché mensuel) : on décale la période
d'un an, d'un mois ou d'une semaine plutôt que de modifier l'événement.
"""

import calendar
from datetime import datetime, timedelta
from itertools import zip_longest

from django.utils import timezone

FORMAT_CHAMP = "%Y-%m-%dT%H:%M"  # <input type="datetime-local">
MAX_CRENEAUX = 31
MAX_HEURES = 31 * 24
DECALAGES = [("-1 an", -12, 0), ("-1 mois", -1, 0), ("-1 semaine", 0, -7),
             ("+1 semaine", 0, 7), ("+1 mois", 1, 0), ("+1 an", 12, 0)]

Creneaux = list[tuple[datetime, datetime]]


class PeriodeInvalide(ValueError):
    """Message affichable : créneau incomplet, illisible, inversé ou période trop longue."""


def _lire_date(texte: str) -> datetime:
    dt = datetime.fromisoformat(texte)
    return timezone.localtime(dt).replace(tzinfo=None) if timezone.is_aware(dt) else dt


def lire(debuts: list[str], fins: list[str]) -> Creneaux:
    """Créneaux (heure locale, sans fuseau) saisis dans le formulaire ; lignes vides ignorées."""
    creneaux = []
    for numero, (d, f) in enumerate(zip_longest(debuts, fins, fillvalue=""), start=1):
        d, f = (d or "").strip(), (f or "").strip()
        if not d and not f:
            continue
        if not d or not f:
            raise PeriodeInvalide(f"Créneau {numero} : indiquez le début et la fin.")
        try:
            debut, fin = _lire_date(d), _lire_date(f)
        except ValueError:
            raise PeriodeInvalide(f"Créneau {numero} : date ou heure illisible.") from None
        if fin <= debut:
            raise PeriodeInvalide(f"Créneau {numero} : la fin doit suivre le début.")
        creneaux.append((debut, fin))
    if len(creneaux) > MAX_CRENEAUX:
        raise PeriodeInvalide(f"{MAX_CRENEAUX} créneaux au plus.")
    if sum((f - d for d, f in creneaux), timedelta()) > timedelta(hours=MAX_HEURES):
        raise PeriodeInvalide("Période trop longue : 31 jours cumulés au plus.")
    return sorted(creneaux)


def memorises(evenement) -> Creneaux:
    """Créneaux enregistrés avec l'événement (proposés à l'ouverture de sa page)."""
    local = lambda dt: timezone.localtime(dt).replace(tzinfo=None)  # noqa: E731
    return [(local(c.debut), local(c.fin)) for c in evenement.creneaux.all()]


def _decaler_mois(dt: datetime, mois: int) -> datetime:
    annee, mois_0 = divmod(dt.month - 1 + mois, 12)
    annee += dt.year
    jour = min(dt.day, calendar.monthrange(annee, mois_0 + 1)[1])  # 31 mars - 1 mois = 28/29 février
    return dt.replace(year=annee, month=mois_0 + 1, day=jour)


def decaler(creneaux: Creneaux, mois: int = 0, jours: int = 0) -> Creneaux:
    def un(dt):
        return _decaler_mois(dt, mois) + timedelta(days=jours)
    return [(un(d), un(f)) for d, f in creneaux]


def parametres(creneaux: Creneaux) -> list[tuple[str, str]]:
    """Paramètres d'URL (``debut``, ``fin`` répétés) d'une période."""
    return [p for d, f in creneaux for p in (("debut", d.strftime(FORMAT_CHAMP)), ("fin", f.strftime(FORMAT_CHAMP)))]
