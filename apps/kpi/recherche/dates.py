"""Expressions de dates, fenêtres horaires et granularités (texte normalisé, sans accents)."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

MOIS = {
    "janvier": 1, "janv": 1, "jan": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4,
    "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "sep": 9,
    "octobre": 10, "oct": 10, "novembre": 11, "nov": 11, "decembre": 12, "dec": 12,
}
NOMS_MOIS = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]
_MOIS = "|".join(sorted(MOIS, key=len, reverse=True))
_JOUR = r"(\d{1,2})(?:er|e|eme)?"
_AN = r"(\d{4})"
JOURS_SEMAINE = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6}
NOMS_JOURS = list(JOURS_SEMAINE)
_JOURS = "|".join(JOURS_SEMAINE)
# Nom du jour facultatif devant une date (« lundi 14 septembre », « le mardi 15/09 »).
_NOM_JOUR = rf"(?:(?:{_JOURS}) )?"
NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
           "neuf": 9, "dix": 10, "quinze": 15, "trente": 30}
_NOMBRE = r"(\d{1,3}|" + "|".join(NOMBRES) + ")"

# Préréglages de période (paramètre GET « periode ») : code -> libellé.
PRESETS = {
    "hier": "Hier",
    "7j": "7 derniers jours",
    "semaine_derniere": "Semaine dernière",
    "mois_dernier": "Mois dernier",
    "mois_courant": "Ce mois-ci",
    "aujourdhui": "Aujourd'hui",
    "30j": "30 derniers jours",
}


@dataclass
class Periode:
    debut: date
    fin: date
    libelle: str

    @property
    def jours(self) -> int:
        return (self.fin - self.debut).days + 1


def _nombre(valeur: str) -> int:
    return NOMBRES.get(valeur) or int(valeur)


def _mois_complet(annee: int, mois: int) -> tuple[date, date]:
    return date(annee, mois, 1), date(annee, mois, calendar.monthrange(annee, mois)[1])


def _annee_par_defaut(mois: int, jour: int | None, aujourdhui: date) -> int:
    """Année courante, ou précédente si la date (ou le mois) est dans le futur."""
    annee = aujourdhui.year
    try:
        candidat = date(annee, mois, jour or 1)
    except ValueError:
        return annee
    return annee - 1 if candidat > aujourdhui else annee


def semaine_numero(numero: int, aujourdhui: date) -> tuple[date, date] | None:
    """Lundi et dimanche de la semaine ISO ``numero`` (année courante, ou précédente si à venir)."""
    try:
        lundi = date.fromisocalendar(aujourdhui.year, numero, 1)
        if lundi > aujourdhui:
            lundi = date.fromisocalendar(aujourdhui.year - 1, numero, 1)
    except ValueError:
        return None
    return lundi, lundi + timedelta(days=6)


def semaine_suggeree(texte) -> int | None:
    """« Nouméa S40 » sans contexte de date : pas une période, mais « Semaine 40 » est proposée
    en premier dans la question (jamais « S1 », l'interface S1, consommée avant)."""
    for i in texte.libres():
        m = re.fullmatch(r"s(\d{1,2})", texte.mots[i])
        if m and 2 <= int(m[1]) <= 53:
            texte.consommer([i])
            return int(m[1])
    return None


def preset(code: str, aujourdhui: date) -> Periode | None:
    hier = aujourdhui - timedelta(days=1)
    if code == "hier":
        return Periode(hier, hier, "Hier")
    if code == "aujourdhui":
        return Periode(aujourdhui, aujourdhui, "Aujourd'hui")
    if code in ("7j", "30j"):
        n = int(code[:-1])
        return Periode(aujourdhui - timedelta(days=n), hier, f"{n} derniers jours")
    if code == "semaine_derniere":
        lundi = aujourdhui - timedelta(days=aujourdhui.weekday() + 7)
        return Periode(lundi, lundi + timedelta(days=6), "Semaine dernière")
    if code == "mois_dernier":
        premier = aujourdhui.replace(day=1) - timedelta(days=1)
        debut, fin = _mois_complet(premier.year, premier.month)
        return Periode(debut, fin, f"Mois dernier ({NOMS_MOIS[premier.month]})")
    if code == "mois_courant":
        return Periode(aujourdhui.replace(day=1), aujourdhui, "Ce mois-ci")
    return None


def _date(jour: int, mois: int, annee: int | None, aujourdhui: date) -> date | None:
    if annee is not None and annee < 100:
        annee += 2000
    annee = annee or _annee_par_defaut(mois, jour, aujourdhui)
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


def _week_end(jour: date) -> tuple[date, date]:
    """Samedi et dimanche du week-end le plus proche de ``jour``."""
    decalage = {0: -2, 1: -3, 2: 3, 3: 2, 4: 1, 5: 0, 6: -1}[jour.weekday()]
    samedi = jour + timedelta(days=decalage)
    return samedi, samedi + timedelta(days=1)


def _fmt(d: date) -> str:
    return f"{d.day} {NOMS_MOIS[d.month]}"


def jour_passe(jour_semaine: int, aujourdhui: date) -> date:
    """Date la plus récente, strictement avant aujourd'hui, tombant ce jour de la semaine.

    Règle unique pour « jeudi », « le jeudi », « jeudi dernier », « jeudi passé » : on
    ne regarde jamais aujourd'hui ni l'avenir. Le jeudi 8 octobre, « jeudi » et « jeudi
    dernier » = jeudi 1er octobre, « mardi » = mardi 6 octobre, « samedi dernier » =
    samedi 3 octobre (le samedi de cette semaine n'est pas encore passé).
    """
    ecart = (aujourdhui.weekday() - jour_semaine) % 7 or 7
    return aujourdhui - timedelta(days=ecart)


# Motifs de période, du plus spécifique au plus général. Chaque fonction reçoit le match.
def _motifs(aujourdhui: date):
    hier = aujourdhui - timedelta(days=1)

    def entre_jours(m):  # du 1er au 15 septembre [2025]
        mois = MOIS[m[3]]
        annee = int(m[4]) if m[4] else None
        d, f = _date(int(m[1]), mois, annee, aujourdhui), _date(int(m[2]), mois, annee, aujourdhui)
        if d and f and f < d and annee is None:  # du 28 au 3 octobre : début le mois précédent
            d = _date(int(m[1]), mois - 1 or 12, (f.year if mois > 1 else f.year - 1), aujourdhui)
        return (d, f, f"du {_fmt(d)} au {_fmt(f)}") if d and f else None

    def entre_mois(m):  # du 28 septembre au 3 octobre [2026]
        annee = int(m[5]) if m[5] else None
        d = _date(int(m[1]), MOIS[m[2]], annee, aujourdhui)
        f = _date(int(m[3]), MOIS[m[4]], annee, aujourdhui)
        return (d, f, f"du {_fmt(d)} au {_fmt(f)}") if d and f else None

    def entre_numeriques(m):  # du 01/09 au 15/09[/2026]
        a1 = int(m[3]) if m[3] else None
        a2 = int(m[6]) if m[6] else None
        d = _date(int(m[1]), int(m[2]), a1 or a2, aujourdhui)
        f = _date(int(m[4]), int(m[5]), a2 or a1, aujourdhui)
        return (d, f, f"du {d:%d/%m} au {f:%d/%m}") if d and f else None

    def semaine_du(m):  # la semaine du 5 octobre / du 05/10 [2026] : du lundi au dimanche contenant ce jour
        if m[2] and m[2] in MOIS:
            d = _date(int(m[1]), MOIS[m[2]], int(m[3]) if m[3] else None, aujourdhui)
        elif m[4]:
            d = _date(int(m[4]), int(m[5]), int(m[6]) if m[6] else None, aujourdhui)
        else:
            d = jour_seul_date(int(m[1]))
        if not d:
            return None
        lundi = d - timedelta(days=d.weekday())
        return lundi, lundi + timedelta(days=6), f"semaine du {_fmt(lundi)}"

    def jour_seul_date(jour):
        mois, an = aujourdhui.month, aujourdhui.year
        if jour > aujourdhui.day:
            mois, an = (mois - 1 or 12), (an if mois > 1 else an - 1)
        return _date(jour, mois, an, aujourdhui)

    def week_end_du(m):  # le week-end du 14 [septembre] [2026]
        jour = int(m[1])
        if m[2]:
            mois = MOIS[m[2]]
            annee = int(m[3]) if m[3] else None
        else:
            mois, annee = aujourdhui.month, aujourdhui.year
            if jour > aujourdhui.day:
                mois, annee = (mois - 1 or 12), (annee if mois > 1 else annee - 1)
        d = _date(jour, mois, annee, aujourdhui)
        if not d:
            return None
        samedi, dimanche = _week_end(d)
        return samedi, dimanche, f"week-end du {_fmt(samedi)}"

    def jour_mois(m):  # le 14 septembre [2026]
        d = _date(int(m[1]), MOIS[m[2]], int(m[3]) if m[3] else None, aujourdhui)
        return (d, d, f"le {_fmt(d)}") if d else None

    def jour_numerique(m):  # le 14/09[/2026]
        d = _date(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, aujourdhui)
        return (d, d, f"le {d:%d/%m/%Y}") if d else None

    def iso(m):
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
        return d, d, f"le {d:%d/%m/%Y}"

    def mois_annee(m):
        mois, annee = MOIS[m[1]], int(m[2])
        d, f = _mois_complet(annee, mois)
        return d, f, f"{NOMS_MOIS[mois]} {annee}"

    def mois_seul(m):
        mois = MOIS[m[1]]
        annee = _annee_par_defaut(mois, None, aujourdhui)
        d, f = _mois_complet(annee, mois)
        return d, f, f"{NOMS_MOIS[mois]} {annee}"

    def derniers(m):  # les 7 derniers jours / les 3 dernières semaines / les 2 derniers mois
        n = _nombre(m[1] or m[3])
        unite = m[2] or m[4]
        if n < 1 or n > 1000:
            return None
        jours = n * {"jour": 1, "jours": 1, "semaine": 7, "semaines": 7, "mois": 30}[unite]
        libelle = f"{n} derni{'ères' if unite.startswith('semaine') else 'ers'} {unite}"
        return aujourdhui - timedelta(days=jours), hier, libelle

    def annee(m):
        a = int(m[1])
        return date(a, 1, 1), date(a, 12, 31), f"année {a}"

    def semaine_iso(m):  # semaine 38 / sem. 38 [2026] : semaine ISO, année courante ou précédente si à venir
        numero = int(m[1])
        an = int(m[2]) if m[2] else aujourdhui.year
        try:
            lundi = date.fromisocalendar(an, numero, 1)
            if not m[2] and lundi > aujourdhui:
                lundi = date.fromisocalendar(an - 1, numero, 1)
        except ValueError:
            return None
        return lundi, lundi + timedelta(days=6), f"semaine {numero} ({lundi.isocalendar().year})"

    def relatif(code, libelle=None):
        def f(_m):
            p = preset(code, aujourdhui)
            return p.debut, p.fin, libelle or p.libelle
        return f

    def cette_semaine(_m):
        return aujourdhui - timedelta(days=aujourdhui.weekday()), aujourdhui, "Cette semaine"

    def avant_hier(_m):
        d = aujourdhui - timedelta(days=2)
        return d, d, "Avant-hier"

    def ce_week_end(_m):  # dernier week-end commencé (en cours le samedi ou le dimanche)
        samedi = aujourdhui - timedelta(days=(aujourdhui.weekday() - 5) % 7)
        return samedi, min(samedi + timedelta(days=1), aujourdhui), "Week-end dernier"

    def week_end_dernier(_m):  # dernier week-end terminé (le précédent si l'on est samedi ou dimanche)
        samedi = jour_passe(5, aujourdhui)
        if aujourdhui.weekday() == 6:
            samedi -= timedelta(days=7)
        return samedi, samedi + timedelta(days=1), "Week-end dernier"

    def jour_semaine(m):  # jeudi, le jeudi, jeudi dernier : voir jour_passe()
        d = jour_passe(JOURS_SEMAINE[m[1]], aujourdhui)
        return d, d, f"{m[1]} {_fmt(d)}"

    def jour_seul(m):  # le 14 (mois courant, ou précédent si le 14 est à venir)
        jour = int(m[1])
        mois, an = aujourdhui.month, aujourdhui.year
        if jour > aujourdhui.day:
            mois, an = (mois - 1 or 12), (an if mois > 1 else an - 1)
        d = _date(jour, mois, an, aujourdhui)
        return (d, d, f"le {_fmt(d)}") if d else None

    def cette_annee(_m):
        return date(aujourdhui.year, 1, 1), aujourdhui, f"année {aujourdhui.year}"

    def annee_derniere(_m):
        a = aujourdhui.year - 1
        return date(a, 1, 1), date(a, 12, 31), f"année {a}"

    sep = r"(?:au|a|jusqu au|jusqu a|et le|et)"
    return [
        (rf"(?:du |entre le |entre )?{_JOUR} {sep} (?:le )?{_JOUR} ({_MOIS})(?: {_AN})?", entre_jours),
        (rf"(?:du |entre le |entre )?{_JOUR} ({_MOIS}) {sep} (?:le )?{_JOUR} ({_MOIS})(?: {_AN})?", entre_mois),
        (r"(?:du |entre le |entre )?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))? " + sep + r" (?:le )?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?",
         entre_numeriques),
        (rf"(?:le |ce )?(?:week end|weekend|we) (?:du |de )?{_JOUR}(?: ({_MOIS}))?(?: {_AN})?", week_end_du),
        (rf"(?:la |pendant la |sur la |de la |cette )?semaine (?:du |de )(?:lundi )?(?:{_JOUR}(?![/\d])(?: ({_MOIS}))?(?: {_AN})?"
         r"|(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?)", semaine_du),
        (r"(\d{4})-(\d{2})-(\d{2})", iso),
        # « semaine 38 », « sem. 38 », « sem 38 » ; « S40 », « S 40 », « s.40 » seulement avec un
        # contexte de date : précédé de « en », « la », « de la », « pendant la », « depuis la »,
        # « sur la », « à partir de la », ou suivi d'une année (« S40 2026 »). Jamais « S1 »
        # (interface S1) : écrire « semaine 1 ».
        (r"(?:la |en |de la |pendant la )?(?:semaine|sem) ?(\d{1,2})(?: (\d{4}))?", semaine_iso),
        (r"(?:la|en|de la|pendant la|depuis la|sur la|a partir de la|semaine|la semaine) s ?([2-9]|\d{2})"
         r"(?: (\d{4}))?", semaine_iso),
        (r"s ?([2-9]|\d{2}) (\d{4})", semaine_iso),
        (rf"(?:le |du |au )?{_NOM_JOUR}{_JOUR} ({_MOIS})(?: {_AN})?", jour_mois),
        (rf"(?:le |du |au )?{_NOM_JOUR}(\d{{1,2}})/(\d{{1,2}})(?:/(\d{{2,4}}))?", jour_numerique),
        (rf"(?:le|du|depuis le) {_NOM_JOUR}(\d{{1,2}})(?:er|e|eme)?", jour_seul),
        (rf"(?:en |de |du mois de |mois de |le mois de )?({_MOIS}) {_AN}", mois_annee),
        (rf"(?:les |sur les |ces |depuis )?{_NOMBRE} (?:derniers |dernieres )?(jours|jour|semaines|semaine|mois)"
         rf"(?: derniers| dernieres| ecoules| passes)?|(?:les |sur les |ces )?(?:derniers|dernieres) {_NOMBRE} (jours|semaines|mois)",
         derniers),
        (r"(?:la |cette )?semaine (?:derniere|passee|precedente)|(?:la |cette )?derniere semaine", relatif("semaine_derniere")),
        (r"(?:le |ce )?mois (?:dernier|precedent|passe)|(?:le )?dernier mois", relatif("mois_dernier")),
        (r"(?:ce |le )?mois ci|ce mois|(?:le |du )?mois (?:en cours|courant)|depuis le debut du mois", relatif("mois_courant")),
        (r"(?:cette |la )?semaine (?:en cours|courante)|cette semaine", cette_semaine),
        (r"(?:le |ce )?(?:week end|weekend|we) (?:dernier|passe|precedent)|(?:le )?dernier (?:week end|weekend)",
         week_end_dernier),
        (r"(?:ce |le )?(?:week end|weekend)", ce_week_end),
        (rf"(?:le |ce |du )?({_JOURS})(?: (?:dernier|passe|precedent))?", jour_semaine),
        (r"avant hier", avant_hier),
        (r"aujourd hui|aujourdhui|ce jour", relatif("aujourdhui")),
        (r"(?:d )?hier", relatif("hier")),
        (r"(?:cette annee|l annee en cours|depuis le debut de l annee|depuis janvier)", cette_annee),
        (r"(?:l )?annee (?:derniere|passee|precedente)", annee_derniere),
        (rf"(?:en |de |du mois d |du mois de |mois de |le mois de |sur |pour )?({_MOIS})", mois_seul),
        (r"(?:en |sur |pour |annee )?(20\d\d)", annee),
    ]


# Motifs désignant un point de départ possible après « depuis » (« depuis septembre »,
# « depuis le 15/09 », « depuis lundi », « depuis la semaine 38 », « depuis 2025 »).
_POINTS_DE_DEPART = ("week_end_du", "semaine_du", "iso", "semaine_iso", "jour_mois", "jour_numerique", "jour_seul", "mois_annee",
                     "jour_semaine", "mois_seul", "annee")


def _depuis(texte, aujourdhui: date, motifs, notes: list[str]) -> Periode | None:
    """« depuis <date> » : de cette date à hier (aujourd'hui si la date est aujourd'hui)."""
    hier = aujourdhui - timedelta(days=1)
    for motif, fonction in motifs:
        if fonction.__name__ not in _POINTS_DE_DEPART:
            continue
        for m in texte.chercher(re.compile(rf"\bdepuis (?:le |la |l )?(?:{motif})\b")):
            resultat = fonction(m)
            if not resultat or not resultat[0]:
                notes.append(f"Date non valide ignorée : « {m.group(0)} ».")
                continue
            if resultat[0] > aujourdhui:
                notes.append(f"Période dans le futur ignorée : « {m.group(0)} ».")
                continue
            debut, _fin, libelle = resultat
            if libelle.startswith("le "):
                libelle = libelle[3:]
            return Periode(debut, max(hier, debut), f"Depuis {libelle}")
    return None


def extraire_periode(texte, aujourdhui: date) -> tuple[Periode | None, list[str]]:
    """Première expression de période reconnue (et consommée) ; notes éventuelles."""
    notes = []
    motifs = _motifs(aujourdhui)
    depuis = _depuis(texte, aujourdhui, motifs, notes)
    if depuis:
        return depuis, notes
    for motif, fonction in motifs:
        for m in texte.chercher(re.compile(rf"\b(?:{motif})\b")):
            resultat = fonction(m)
            if not resultat or not resultat[0] or not resultat[1]:
                notes.append(f"Date non valide ignorée : « {m.group(0)} ».")
                continue
            debut, fin, libelle = resultat
            if fin < debut:
                debut, fin = fin, debut
            if debut > aujourdhui:
                notes.append(f"Période dans le futur ignorée : « {m.group(0)} ».")
                continue
            if fin > aujourdhui:
                fin = aujourdhui
            return Periode(debut, fin, libelle[:1].upper() + libelle[1:]), notes
    return None, notes


# ------------------------------------------------------------------ fenêtre horaire

FENETRES_NOMMEES = [
    (r"heures? chargees?|heures? de pointe|busy hour|\bhc\b", "heure_chargee", "Heure chargée"),
    (r"(?:sur |la |toute la )?journee complete|toute la journee|24 ?h ?/ ?24|sur 24 ?h|24 ?h", "journee", "Journée complète"),
    (r"(?:en |la |le |dans la )?(?:soiree|soir)", "18-22", "Soirée (18 h – 22 h)"),
    (r"(?:en|dans la|pendant la) journee|journee de travail|heures? ouvrees|heures? de bureau|diurne", "7-20",
     "Journée (7 h – 20 h)"),
    (r"(?:la |de |en )?(?:nuit|nocturne)", "0-6", "Nuit (0 h – 6 h)"),
    (r"(?:le |en |dans la )?(?:matinee|matin)", "6-12", "Matin (6 h – 12 h)"),
    (r"(?:l |en |dans l )?apres midi", "12-18", "Après-midi (12 h – 18 h)"),
    (r"(?:a |le )?midi", "11-14", "Midi (11 h – 14 h)"),
]


def libelle_fenetre(code: str) -> str:
    for _motif, c, libelle in FENETRES_NOMMEES:
        if c == code:
            return libelle
    if code == "journee":
        return "Journée complète"
    debut, fin = code.split("-")
    return f"{debut} h – {fin} h"


def extraire_fenetre(texte) -> tuple[str | None, str | None]:
    """(code de fenêtre, libellé) ; code « heure_chargee » si demandé (non géré par le moteur)."""
    plage = re.compile(r"\b(?:de |entre |sur |la plage )?(\d{1,2}) ?(?:h|heures?)(?: ?00)? ?(?:-|a|et|jusqu a) ?"
                       r"(\d{1,2}) ?(?:h|heures?)(?: ?00)?\b|\b(\d{1,2}) ?- ?(\d{1,2}) ?h\b")
    for m in texte.chercher(plage):
        debut, fin = int(m[1] or m[3]), int(m[2] or m[4])
        if fin == 0:
            fin = 24
        if 0 <= debut < fin <= 24:
            code = f"{debut}-{fin}"
            return code, libelle_fenetre(code)
    for motif, code, libelle in FENETRES_NOMMEES:
        for _m in texte.chercher(re.compile(rf"\b(?:{motif})\b")):
            return code, libelle
    return None, None


# ------------------------------------------------------------------ granularités

GRANULARITES_TEMPS = [
    (r"par heures?|a l heure|heure par heure|horaires?|toutes les heures|pas horaire|par h", "heure"),
    (r"par jour|par jours|jour par jour|journaliers?|journalieres?|quotidiens?|quotidiennes?|chaque jour|pas journalier",
     "jour"),
    (r"par semaine|par semaines|semaine par semaine|hebdo|hebdomadaires?|chaque semaine", "semaine"),
    (r"par mois|mois par mois|mensuels?|mensuelles?|chaque mois", "mois"),
]
ESPACES = {"site": "site", "sites": "site", "cellule": "cellule", "cellules": "cellule", "secteur": "secteur",
           "secteurs": "secteur", "commune": "commune", "communes": "commune"}
LIBELLES_TEMPS = {"heure": "par heure", "jour": "par jour", "semaine": "par semaine", "mois": "par mois"}
LIBELLES_ESPACE = {"global": "global", "commune": "par commune", "site": "par site", "secteur": "par secteur",
                   "cellule": "par cellule"}


def extraire_granularites(texte) -> tuple[str | None, str | None, bool, int | None]:
    """(granularité temps, granularité espace, classement demandé, nombre de lignes du classement).

    « top 10 des sites », « les 10 cellules », « 5 pires secteurs », « sites les plus
    chargés » -> niveau + classement (+ nombre) ; « des secteurs du site X », « les sites
    du Sud » -> niveau seul.
    """
    temps = None
    for motif, code in GRANULARITES_TEMPS:
        if list(texte.chercher(re.compile(rf"\b(?:{motif})\b"))):  # toutes les occurrences sont consommées
            temps = temps or code
    espace, classement, nombre = None, False, None
    entites = "|".join(ESPACES)
    qualificatif = (r"(?:degrades?|degradees?|mauvais(?:es)?|touches?|touchees?|charges?|chargees?|sollicites?"
                    r"|sollicitees?|utilises?|utilisees?|actifs?|actives?)")
    classe = re.compile(
        rf"\b(?:les |le |la )?(?:top|pire|pires|classement)(?: (\d{{1,3}}))?(?: des| de| du)?(?: pires?)? ({entites})\b"
        rf"|\b(?:les |des )?(\d{{1,3}}) (pires? |plus mauvais(?:es)? )?({entites})\b"
        rf"|\b({entites}) (?:les |le |la )?(?:plus |moins )?{qualificatif}\b")
    for m in texte.chercher(classe):
        if m[2]:  # top 10 des sites, pires secteurs
            espace, classement, nombre = ESPACES[m[2]], True, m[1] or nombre
        elif m[5]:  # les 10 cellules, 5 pires sites
            espace, nombre, classement = ESPACES[m[5]], m[3], classement or bool(m[4])
        else:  # sites les plus chargés
            espace, classement = ESPACES[m[6]], True
    for m in texte.chercher(re.compile(rf"\b(?:par|pour chaque|chaque|detail par|niveau) ({entites})\b")):
        espace = espace or ESPACES[m[1]]
    for m in texte.chercher(re.compile(r"\b(?:top (\d{1,3})|top|pires?|classement|palmares|les plus degrades?)\b")):
        classement, nombre = True, m[1] or nombre
    # « le plus de trafic », « le plus d'appels » : classement ; le volume reste à lire (intention).
    if list(texte.chercher(re.compile(r"\b(?:le |les )?plus d(?:e)?(?= (?:trafic|volume|volumes|data|donnees|appels"
                                      r"|sms|communications|consommation)\b)"))):
        classement = True
    # « des secteurs du site PIM123 », « les sites du Sud », « toutes les cellules » : niveau seul.
    for m in texte.chercher(re.compile(r"\b(?:des|les|aux|ses|tous les|toutes les) (sites|secteurs|cellules)\b")):
        espace = espace or ESPACES[m[1]]
    nombre = int(nombre) if nombre and 1 <= int(nombre) <= 100 else None
    return temps, espace, classement, nombre


def granularite_par_defaut(jours: int) -> str:
    if jours <= 2:
        return "heure"
    if jours <= 31:
        return "jour"
    if jours <= 183:
        return "semaine"
    return "mois"
