"""Accueil : aperçu du réseau pour la journée en cours ou la veille.

Tuiles KPI (valeur du jour, variation, tendance sur 14 jours, statut), profils horaires du
jour comparés à la veille, tendance du volume data et sites les plus dégradés. Tout passe par
``executer`` : mêmes calculs (ratio de sommes) et mêmes droits (périmètre, KPI autorisés)
que les recherches. Résultat mis en cache quelques minutes par utilisateur.

- « hier » : journée complète, comparée à l'avant-veille ; si la base n'a pas encore cette
  journée (démonstration ancienne, chargement en retard), dernier jour disponible des
  14 derniers jours ;
- « aujourd'hui » : de minuit à la dernière heure chargée, comparé à la veille sur les
  mêmes heures.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

import pandas as pd
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.comptes.acces import kpis_autorises, voit_tout_le_reseau

from .catalogue import catalogue
from .recherche.affichage import conversion, formater
from .requete import RequeteKpi
from .service import executer
from .source import est_demo, infos_demo


@dataclass(frozen=True)
class Tuile:
    code: str
    libelle: str
    icone: str


TUILES = (
    Tuile("lte_payload_dl", "Volume data 4G", "data"),
    Tuile("lte_rrc_conn_max", "Utilisateurs 4G (pic)", "utilisateurs"),
    Tuile("wcdma_appels_voix", "Appels voix 3G", "appels"),
    Tuile("wcdma_sms", "SMS", "sms"),
    Tuile("lte_dl_user_thp", "Débit DL 4G", "debit"),
    Tuile("lte_acces", "Taux d'accès 4G", "acces"),
    Tuile("lte_erab_drop", "Coupures data 4G (E-RAB)", "coupure"),
    Tuile("wcdma_cs_drop", "Coupures voix 3G", "coupure"),
)
PROFIL_TRAFIC = "lte_payload_dl"
PROFILS_QUALITE = ("lte_erab_drop", "wcdma_cs_drop")
CLASSEMENTS = ("lte_erab_drop", "wcdma_cs_drop")
JOURS_TENDANCE = 14
CLASSEMENT_MAX = 5
CHOIX = {"hier": "Hier", "aujourdhui": "Aujourd'hui"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


class AucuneDonnee(Exception):
    """Aucune donnée pour la journée demandée (message affichable)."""


def date_longue(jour: date) -> str:
    """« mardi 7 octobre 2026 »."""
    return f"{JOURS[jour.weekday()]} {jour.day}{'er' if jour.day == 1 else ''} {MOIS[jour.month - 1]} {jour.year}"


def _valeur(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _requete(kpis, debut, fin, temps="jour", espace="global", fenetre="journee") -> RequeteKpi:
    cat = catalogue()
    technos = [t for t in ("LTE", "WCDMA") if any(cat[c].techno == t for c in kpis)]
    return RequeteKpi(techno=technos, perimetre={"type": "global"}, periode={"debut": debut, "fin": fin},
                      granularite_temps=temps, granularite_espace=espace, fenetre_horaire=fenetre, kpis=list(kpis))


def _par_periode(resultat) -> dict[str, pd.Series]:
    """Code KPI -> série indexée par période (vue globale), toutes technos confondues."""
    series = {}
    for res in resultat.par_techno:
        if res.table.empty:
            continue
        table = res.table.droplevel("entite")
        for k in res.kpis:
            series[k.code] = table[k.code]
    return series


def _globales(resultat) -> dict[str, float | None]:
    return {code: _valeur(v) for res in resultat.par_techno for code, v in res.synthese_globale.items()}


def _a_des_donnees(series: dict[str, pd.Series], jour: date) -> bool:
    horodatage = pd.Timestamp(jour)
    return any(horodatage in s.index and s.notna().get(horodatage, False) for s in series.values())


def etincelle(valeurs: list) -> dict | None:
    """Tracé SVG (viewBox 100 × 32) d'une mini-courbe : ligne et aire sous la courbe."""
    points = [(i, v) for i, v in enumerate(valeurs) if v is not None]
    if len(points) < 2:
        return None
    bas, haut = min(v for _, v in points), max(v for _, v in points)
    etendue = (haut - bas) or abs(haut) or 1
    n = max(len(valeurs) - 1, 1)
    coords = [(round(100 * i / n, 2), round(29 - 26 * (v - bas) / etendue, 2)) for i, v in points]
    ligne = "M" + " L".join(f"{x},{y}" for x, y in coords)
    aire = f"{ligne} L{coords[-1][0]},32 L{coords[0][0]},32 Z"
    return {"ligne": ligne, "aire": aire}


def variation(k, valeur, reference) -> dict | None:
    """Écart à la référence : points pour un pourcentage, % sinon ; « bon » ou « mauvais »
    selon le sens du KPI (neutre pour un volume de trafic)."""
    if valeur is None or reference is None:
        return None
    if k.unite == "%":
        ecart = valeur - reference
        texte = f"{ecart:+.2f} pt".replace(".", ",")
        nul = abs(ecart) < 0.005
    else:
        if not reference:
            return None
        ecart = 100 * (valeur - reference) / abs(reference)
        texte = f"{ecart:+.1f} %".replace(".", ",")
        nul = abs(ecart) < 0.05
    texte = texte.replace("-", "−")
    if nul:
        return {"texte": "= " + texte.lstrip("+−"), "sens": "", "fleche": ""}
    hausse = ecart > 0
    if k.categorie == "trafic":
        sens = ""
    else:
        sens = "bon" if hausse == (k.sens == "haut_est_mieux") else "mauvais"
    return {"texte": texte, "sens": sens, "fleche": "▲" if hausse else "▼"}


def _lien_recherche(kpis, debut: date, fin: date, **autres) -> str:
    params = [("q", ""), *(("kpis", c) for c in kpis), ("debut", debut.isoformat()), ("fin", fin.isoformat())]
    params += list(autres.items())
    return reverse("kpi:requete") + "?" + urlencode(params)


def _profil(series: dict[str, pd.Series], code: str, jour: date, diviseur: float = 1.0) -> list:
    """24 valeurs horaires (None si absente) du KPI ``code`` le ``jour`` donné."""
    s = series.get(code)
    sortie = []
    for h in range(24):
        v = _valeur(s.get(pd.Timestamp(jour) + pd.Timedelta(hours=h))) if s is not None else None
        sortie.append(None if v is None else round(v / diviseur, 4))
    return sortie


def _derniere_heure(series: dict[str, pd.Series], jour: date) -> int | None:
    heures = [p.hour for s in series.values() for p, v in s.items() if p.date() == jour and _valeur(v) is not None]
    return max(heures) if heures else None


def _classement(user, code: str, jour: date, fenetre: str) -> dict | None:
    cat = catalogue()
    k = cat[code]
    resultat = executer(_requete([code], jour, jour, espace="site", fenetre=fenetre), user, _moteur())
    res = next((r for r in resultat.par_techno if r.synthese is not None and code in r.synthese), None)
    if res is None:
        return None
    serie = res.synthese[code].dropna().sort_values(ascending=k.sens == "haut_est_mieux")
    if serie.empty:
        return None
    pires = serie.head(CLASSEMENT_MAX)
    maximum = max(abs(float(v)) for v in pires) or 1
    lignes = [{"entite": str(e), "texte": formater(float(v), k.unite)[0], "unite": k.unite, "statut": k.statut(float(v)),
               "largeur": round(100 * abs(float(v)) / maximum, 1)} for e, v in pires.items()]
    return {"code": code, "titre": f"{'Coupures 4G' if k.techno == 'LTE' else 'Coupures voix 3G'} par site",
            "techno": k.techno, "lignes": lignes, "total": len(serie),
            "lien": _lien_recherche([code], jour, jour, granularite_espace="site")}


def _moteur():
    from .source import moteur_kpi  # importé ici : remplaçable dans les tests

    return moteur_kpi()


def calculer(user, aujourdhui: date, choix: str) -> dict:
    """Données de l'aperçu (lève ``AucuneDonnee``, ``RequeteRefusee`` ou ``BaseKpiNonConfiguree``)."""
    cat = catalogue()
    visibles = kpis_autorises(user, {t.code for t in TUILES if t.code in cat})
    tuiles = [t for t in TUILES if t.code in visibles]
    if not tuiles:
        raise AucuneDonnee("Aucun indicateur de l'aperçu n'est ouvert à votre compte.")
    codes = [t.code for t in tuiles]

    if choix == "aujourdhui":
        cible = aujourdhui
        debut_tendance, fin_tendance = cible - timedelta(days=JOURS_TENDANCE), cible - timedelta(days=1)
    else:
        cible = aujourdhui - timedelta(days=1)
        fin_demo = infos_demo().get("fin") if est_demo() else None
        if isinstance(fin_demo, date) and fin_demo < cible:
            cible = fin_demo  # démonstration générée il y a quelques jours
        debut_tendance, fin_tendance = cible - timedelta(days=JOURS_TENDANCE - 1), cible
    moteur = _moteur()
    tendance = _par_periode(executer(_requete(codes, debut_tendance, fin_tendance), user, moteur))

    decale = False
    if choix == "hier" and not _a_des_donnees(tendance, cible):
        jours = sorted({p.date() for s in tendance.values() for p, v in s.items() if _valeur(v) is not None})
        if not jours:
            raise AucuneDonnee(f"Aucune donnée sur les {JOURS_TENDANCE} jours précédant le {cible:%d/%m/%Y}.")
        cible, decale = jours[-1], True

    veille = cible - timedelta(days=1)
    horaire = _par_periode(executer(_requete(codes, veille, cible, temps="heure"), user, moteur))
    fenetre, heure = "journee", None
    if choix == "aujourdhui":
        heure = _derniere_heure(horaire, cible)
        if heure is None:
            raise AucuneDonnee("Les données d'aujourd'hui ne sont pas encore chargées.")
        fenetre = f"0-{heure + 1}"
        valeurs = _globales(executer(_requete(codes, cible, cible, fenetre=fenetre), user, moteur))
        references = _globales(executer(_requete(codes, veille, veille, fenetre=fenetre), user, moteur))
        libelle_ref = f"vs hier à {heure + 1} h" if heure < 23 else "vs hier"
    else:
        valeurs = {c: _valeur(s.get(pd.Timestamp(cible))) for c, s in tendance.items()}
        references = {c: _valeur(s.get(pd.Timestamp(veille))) for c, s in tendance.items()}
        libelle_ref = "vs veille"

    jours_tendance = [debut_tendance + timedelta(days=i) for i in range((fin_tendance - debut_tendance).days + 1)]
    sortie_tuiles = []
    for t in tuiles:
        k = cat[t.code]
        v, ref = valeurs.get(t.code), references.get(t.code)
        texte, unite = formater(v, k.unite)
        serie = tendance.get(t.code)
        historique = [_valeur(serie.get(pd.Timestamp(j))) if serie is not None else None for j in jours_tendance]
        statut = k.statut(v)
        sortie_tuiles.append({
            "code": t.code, "libelle": t.libelle, "icone": t.icone, "techno": k.techno,
            "court": "4G" if k.techno == "LTE" else "3G", "texte": texte, "unite": unite,
            "statut": statut or ("ok" if v is not None and k.seuils.alerte is not None else ""),
            "variation": variation(k, v, ref), "etincelle": etincelle(historique),
            "titre": k.libelle, "approx": k.qualite == "approx",
            "lien": _lien_recherche([t.code], cible, cible, granularite_temps="heure"),
        })

    graphiques = {"heures": [f"{h}h" for h in range(24)], "jour": f"{cible:%d/%m}", "veille": f"{veille:%d/%m}"}
    if PROFIL_TRAFIC in visibles:
        k = cat[PROFIL_TRAFIC]
        jour_ = _profil(horaire, PROFIL_TRAFIC, cible)
        diviseur, unite = conversion(k.unite, max((v for v in jour_ + _profil(horaire, PROFIL_TRAFIC, veille) if v),
                                                  default=None))
        graphiques["trafic"] = {"unite": unite, "jour": _profil(horaire, PROFIL_TRAFIC, cible, diviseur),
                                "veille": _profil(horaire, PROFIL_TRAFIC, veille, diviseur)}
        serie = tendance.get(PROFIL_TRAFIC)
        valeurs_t = [_valeur(serie.get(pd.Timestamp(j))) if serie is not None else None for j in jours_tendance]
        div_t, unite_t = conversion(k.unite, max((v for v in valeurs_t if v), default=None))
        graphiques["tendance"] = {"unite": unite_t, "jours": [f"{j:%d/%m}" for j in jours_tendance],
                                  "valeurs": [None if v is None else round(v / div_t, 3) for v in valeurs_t],
                                  "cible": f"{cible:%d/%m}"}
    qualite = [c for c in PROFILS_QUALITE if c in visibles]
    if qualite:
        graphiques["qualite"] = {"series": [{"nom": cat[c].libelle.replace("Taux de coupure ", "Coupure ")
                                             .replace("appels voix (3G)", "voix 3G").replace("E-RAB", "data 4G (E-RAB)"),
                                             "techno": cat[c].techno, "valeurs": _profil(horaire, c, cible)}
                                            for c in qualite],
                                 "seuil": cat[qualite[0]].seuils.alerte}

    classements = [c for c in (_classement(user, code, cible, fenetre) for code in CLASSEMENTS if code in visibles) if c]
    return {
        "choix": choix, "cible": cible, "date_longue": date_longue(cible), "decale": decale, "heure": heure,
        "libelle_ref": libelle_ref, "perimetre": "Tout le réseau" if voit_tout_le_reseau(user) else "Votre périmètre",
        "tuiles": sortie_tuiles, "graphiques": graphiques, "classements": classements,
        "lien_bilan": reverse("kpi:requete") + "?" + urlencode(
            [("q", ""), ("intention", "bilan"), ("debut", cible.isoformat()), ("fin", cible.isoformat())]),
    }


def apercu(user, aujourdhui: date, choix: str, heure_courante: int = 0) -> dict:
    """``calculer`` mis en cache (``APERCU_CACHE_SECONDES``, 5 min par défaut) par utilisateur."""
    duree = getattr(settings, "APERCU_CACHE_SECONDES", 300)
    if not duree:
        return calculer(user, aujourdhui, choix)
    source = settings.KPI_DB.get("host") or str(settings.KPI_DEMO_SQLITE)
    cle = f"apercu:{user.pk}:{choix}:{aujourdhui.isoformat()}:{heure_courante if choix == 'aujourdhui' else ''}:{hash(source)}"
    donnees = cache.get(cle)
    if donnees is None:
        donnees = calculer(user, aujourdhui, choix)
        cache.set(cle, donnees, duree)
    return donnees
