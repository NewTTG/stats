"""Période analysée d'un événement, choisie à l'affichage (heure de Nouméa, heures pleines : la base
KPI est horaire), à défaut les créneaux mémorisés avec l'événement.

Deux saisies, dans l'adresse de la page :
- jours consécutifs à la même plage horaire : ``du``, ``au`` (dates), ``de``, ``a`` (heures) ;
- heures différentes selon les jours : ``jour``, ``de``, ``a`` répétés (une ligne par jour).
``a`` inférieur ou égal à ``de`` : la plage finit le lendemain (20 h → 2 h). ``a`` = 24 : minuit.
Les anciens paramètres ``debut`` / ``fin`` (date + heure) restent lus.

Un même lieu sert d'une édition à l'autre (foire annuelle, marché mensuel) : on décale la période
d'un an, d'un mois ou d'une semaine plutôt que de modifier l'événement.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import zip_longest

from django.utils import timezone

MAX_CRENEAUX = 31
MAX_HEURES = 31 * 24
DECALAGES = [("-1 an", -12, 0), ("-1 mois", -1, 0), ("-1 semaine", 0, -7),
             ("+1 semaine", 0, 7), ("+1 mois", 1, 0), ("+1 an", 12, 0)]
HEURES_DEBUT = list(range(24))
HEURES_FIN = list(range(1, 25))

Creneaux = list[tuple[datetime, datetime]]


class PeriodeInvalide(ValueError):
    """Message affichable : saisie incomplète, illisible ou période trop longue."""


@dataclass
class Saisie:
    """Valeurs du formulaire de période (réaffichées telles quelles en cas d'erreur)."""

    detail: bool = False
    du: str = ""
    au: str = ""
    de: str = ""
    a: str = ""
    lignes: list[tuple[str, str, str]] = field(default_factory=list)  # (jour, de, a)


# ------------------------------------------------------------------ lecture

def _jour(texte: str, quoi: str) -> date:
    try:
        return date.fromisoformat(texte)
    except ValueError:
        raise PeriodeInvalide(f"{quoi} : date illisible.") from None


def _heure(texte: str, quoi: str, fin: bool) -> int:
    valides = HEURES_FIN if fin else HEURES_DEBUT
    try:
        h = int(texte)
    except ValueError:
        h = None
    if h not in valides:
        raise PeriodeInvalide(f"{quoi} : choisissez l'heure de {'fin' if fin else 'début'}.")
    return h


def _plage(jour: date, de: int, a: int) -> tuple[datetime, datetime]:
    debut = datetime.combine(jour, time(de))
    fin = datetime.combine(jour, time()) + timedelta(hours=a)
    return debut, fin if fin > debut else fin + timedelta(days=1)


def _controler(creneaux: Creneaux) -> Creneaux:
    creneaux = sorted(creneaux)
    if len(creneaux) > MAX_CRENEAUX:
        raise PeriodeInvalide(f"{MAX_CRENEAUX} jours au plus.")
    if sum((f - d for d, f in creneaux), timedelta()) > timedelta(hours=MAX_HEURES):
        raise PeriodeInvalide("Période trop longue : 31 jours cumulés au plus.")
    if any(fin > debut for (_, fin), (debut, _) in zip(creneaux, creneaux[1:])):
        raise PeriodeInvalide("Les créneaux ne doivent pas se chevaucher.")
    return creneaux


def _heure_pleine(dt: datetime, fin: bool) -> datetime:
    """Anciens créneaux à la minute : début arrondi à l'heure inférieure, fin à l'heure supérieure."""
    plein = dt.replace(minute=0, second=0, microsecond=0)
    return plein + timedelta(hours=1) if fin and plein < dt else plein


def _lire_ancien(debuts: list[str], fins: list[str]) -> Creneaux:
    creneaux = []
    for numero, (d, f) in enumerate(zip_longest(debuts, fins, fillvalue=""), start=1):
        if not (d or "").strip() and not (f or "").strip():
            continue
        try:
            debut, fin = (_local(datetime.fromisoformat(x.strip())) for x in (d, f))
        except ValueError:
            raise PeriodeInvalide(f"Créneau {numero} : date ou heure illisible.") from None
        debut, fin = _heure_pleine(debut, False), _heure_pleine(fin, True)
        if fin <= debut:
            raise PeriodeInvalide(f"Créneau {numero} : la fin doit suivre le début.")
        creneaux.append((debut, fin))
    return _controler(creneaux)


def lire(donnees) -> tuple[Creneaux, Saisie]:
    """Créneaux d'une requête (GET ou POST) et saisie à réafficher. Aucun paramètre : liste vide."""
    if "debut" in donnees or "fin" in donnees:
        creneaux = _lire_ancien(donnees.getlist("debut"), donnees.getlist("fin"))
        return creneaux, saisie(creneaux)
    if donnees.get("detail"):
        lignes = list(zip_longest(donnees.getlist("jour"), donnees.getlist("de"), donnees.getlist("a"), fillvalue=""))
        entree = Saisie(detail=True, lignes=lignes)
        creneaux = []
        for jour, de, a in lignes:
            if not (jour or "").strip():
                continue
            quoi = f"Le {jour}"
            creneaux.append(_plage(_jour(jour, quoi), _heure(de, quoi, False), _heure(a, quoi, True)))
        return _controler(creneaux), entree
    if "du" not in donnees:
        return [], Saisie()
    entree = Saisie(du=donnees.get("du", ""), au=donnees.get("au", ""), de=donnees.get("de", ""), a=donnees.get("a", ""))
    if not entree.du:
        raise PeriodeInvalide("Indiquez le premier jour.")
    du = _jour(entree.du, "Premier jour")
    au = _jour(entree.au, "Dernier jour") if entree.au else du
    if au < du:
        raise PeriodeInvalide("Le dernier jour doit suivre le premier.")
    if (au - du).days >= MAX_CRENEAUX:
        raise PeriodeInvalide(f"{MAX_CRENEAUX} jours au plus.")
    de, a = _heure(entree.de, "Heures", False), _heure(entree.a, "Heures", True)
    jours = [du + timedelta(days=i) for i in range((au - du).days + 1)]
    return _controler([_plage(j, de, a) for j in jours]), entree


def _local(dt: datetime) -> datetime:
    return timezone.localtime(dt).replace(tzinfo=None) if timezone.is_aware(dt) else dt


def memorises(evenement) -> Creneaux:
    """Créneaux enregistrés avec l'événement (proposés à l'ouverture de sa page), en heures pleines."""
    return sorted((_heure_pleine(_local(c.debut), False), _heure_pleine(_local(c.fin), True))
                  for c in evenement.creneaux.all())


# ------------------------------------------------------------------ écriture

def _heures(debut: datetime, fin: datetime) -> tuple[int, int]:
    """(de, a) d'un créneau d'un jour ; None si le créneau dépasse 24 h."""
    duree = fin - debut
    if duree > timedelta(days=1):
        return None
    a = (debut.hour + int(duree.total_seconds() // 3600)) % 24
    return debut.hour, a if a else 24


def reguliere(creneaux: Creneaux) -> bool:
    """Jours consécutifs, même plage horaire : saisie « du … au …, de … à … »."""
    if not creneaux or any(_heures(d, f) is None for d, f in creneaux):
        return False
    premier = creneaux[0]
    return all(_heures(d, f) == _heures(*premier) and d == premier[0] + timedelta(days=i)
               for i, (d, f) in enumerate(creneaux))


def saisie(creneaux: Creneaux) -> Saisie:
    if not creneaux:
        return Saisie()
    if reguliere(creneaux):
        de, a = _heures(*creneaux[0])
        return Saisie(du=creneaux[0][0].date().isoformat(), au=creneaux[-1][0].date().isoformat(), de=str(de), a=str(a))
    lignes = []
    for d, f in creneaux:
        heures = _heures(d, f) or (d.hour, f.hour or 24)
        lignes.append((d.date().isoformat(), str(heures[0]), str(heures[1])))
    return Saisie(detail=True, lignes=lignes)


def parametres(creneaux: Creneaux) -> list[tuple[str, str]]:
    """Paramètres d'URL d'une période : forme courte si elle est régulière, sinon une ligne par jour.

    Un créneau de plus de 24 h (ancienne saisie) garde les paramètres ``debut`` / ``fin``.
    """
    if any(_heures(d, f) is None for d, f in creneaux):
        return [p for d, f in creneaux
                for p in (("debut", d.strftime("%Y-%m-%dT%H:%M")), ("fin", f.strftime("%Y-%m-%dT%H:%M")))]
    s = saisie(creneaux)
    if not creneaux:
        return []
    if not s.detail:
        return [("du", s.du), ("au", s.au), ("de", s.de), ("a", s.a)]
    return [("detail", "1")] + [p for j, de, a in s.lignes for p in (("jour", j), ("de", de), ("a", a))]


# ------------------------------------------------------------------ décalages

def _decaler_mois(dt: datetime, mois: int) -> datetime:
    annee, mois_0 = divmod(dt.month - 1 + mois, 12)
    annee += dt.year
    jour = min(dt.day, calendar.monthrange(annee, mois_0 + 1)[1])  # 31 mars - 1 mois = 28/29 février
    return dt.replace(year=annee, month=mois_0 + 1, day=jour)


def decaler(creneaux: Creneaux, mois: int = 0, jours: int = 0) -> Creneaux:
    """Même période décalée : le premier jour est décalé, les suivants gardent leur écart avec lui
    (30 et 31 janvier - 1 mois : 28 février et 1er mars) et chaque créneau sa durée."""
    if not creneaux:
        return []
    origine = creneaux[0][0]
    nouvelle = _decaler_mois(origine, mois) + timedelta(days=jours)
    return [(nouvelle + (d - origine), nouvelle + (f - origine)) for d, f in creneaux]
