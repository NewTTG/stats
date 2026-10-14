"""Éditions figées : les compteurs et rattachements sont propres à chaque période."""

import json
from datetime import datetime

import pandas as pd
from django.utils import timezone
from sqlalchemy.exc import SQLAlchemyError

from apps.comptes.acces import cellules_autorisees, voit_tout_le_reseau
from apps.kpi.catalogue import catalogue, kpis_principaux
from apps.kpi.service import colonnes_utilisees
from apps.kpi.source import BaseKpiNonConfiguree

from . import mobiles, periode
from .analyse import AnalyseImpossible, _entites, _lire_fenetres
from .edition import zone_pour_carte
from .models import EditionEvenement, ReglagesAnomalies


def creneaux(archive):
    return [(datetime.fromisoformat(d), datetime.fromisoformat(f)) for d, f in archive.donnees["creneaux"]]


def visibles(evenement, user):
    editions = evenement.editions.defer("donnees")
    if voit_tout_le_reseau(user):
        return editions
    # Ne jamais exposer les noms d'éditions dont aucune cellule n'est autorisée.
    permises = {t: cellules_autorisees(user, t) or set() for t in ("LTE", "WCDMA")}
    ids = [pk for pk, cellules in evenement.editions.values_list("pk", "cellules")
           if any(permises[t].intersection(noms) for t, noms in cellules.items())]
    return editions.filter(pk__in=ids)


def enregistrer(evenement, user, engine, plages, nom):
    if not voit_tout_le_reseau(user):
        raise AnalyseImpossible("L'enregistrement d'une édition complète nécessite l'accès à tout le réseau.")
    if not plages or not nom.strip() or len(nom.strip()) > 128:
        raise AnalyseImpossible("Indiquez une période et un nom d'édition (128 caractères au plus).")
    if plages[-1][1] > timezone.localtime().replace(tzinfo=None):
        raise AnalyseImpossible("Attendez la fin de l'édition avant de figer ses résultats.")
    cat = catalogue()
    codes = set(evenement.kpis or kpis_principaux(cat))
    kpis = [cat[c] for c in cat if c in codes]
    reglages = ReglagesAnomalies.courant()
    donnees = {"version": 1, "creneaux": [[d.isoformat(), f.isoformat()] for d, f in plages],
               "catalogue": {k.code: definition(k) for k in kpis},
               "reglages": {c: getattr(reglages, c) for c in
                            ("ecart_sigma", "ecart_pct", "saturation_prb", "saturation_debit")},
               "deploiements": evenement.deploiements, "zone": zone_pour_carte(evenement), "technos": {}}
    for techno in ("LTE", "WCDMA"):
        selection = [k for k in kpis if k.techno == techno]
        cellules = evenement.noms_cellules(techno)
        if not selection or not cellules:
            continue
        df = _lire_fenetres(engine, techno, colonnes_utilisees(selection), cellules,
                            [(0, i, d, f) for i, (d, f) in enumerate(plages)])
        entites = {}
        for niveau in ("site", "secteur"):
            entites[niveau] = _entites(techno, niveau, cellules, plages[0][0].date())
            entites[niveau].update(mobiles.entites(evenement.deploiements, techno, niveau))
        donnees["technos"][techno] = {"cellules": cellules, "entites": entites,
                                       "lignes": json.loads(df.to_json(orient="records", date_format="iso", double_precision=15))}
    if not any(t["lignes"] for t in donnees["technos"].values()):
        raise AnalyseImpossible("Aucune donnée à enregistrer pour cette édition.")
    return EditionEvenement.objects.create(evenement=evenement, nom=nom.strip(),
        debut=timezone.make_aware(plages[0][0]), fin=timezone.make_aware(plages[-1][1]),
        cellules={t: d["cellules"] for t, d in donnees["technos"].items()},
        donnees=donnees, cree_par=user)


def definition(kpi):
    # ``composants`` est exclu du model_dump habituel : il faut le conserver pour les composites.
    return {**kpi.model_dump(mode="json"), "composants": [definition(c) for c in kpi.composants]}


def lire(archive, techno, cellules, plages):
    """Filtrer les compteurs figés sans consulter la source ou le référentiel courant."""
    couvertes = creneaux(archive)
    if any(not any(d <= debut and fin <= f for d, f in couvertes) for debut, fin in plages):
        raise AnalyseImpossible("La période demandée dépasse les créneaux enregistrés de l'édition.")
    lignes = archive.donnees["technos"].get(techno, {}).get("lignes", [])
    if not lignes:
        return pd.DataFrame(columns=["cellule", "horodatage", "instant", "creneau", "semaine"])
    df = pd.DataFrame(lignes)
    df["horodatage"] = pd.to_datetime(df["horodatage"])
    for colonne in set(df) - {"cellule", "horodatage", "instant"}:
        df[colonne] = pd.to_numeric(df[colonne], errors="coerce")
    morceaux = []
    for i, (d, f) in enumerate(plages):
        m = df[df["cellule"].isin(cellules) & (df["horodatage"] >= d) & (df["horodatage"] < f)]
        morceaux.append(m.assign(creneau=i, semaine=0, instant=m["horodatage"]))
    return pd.concat(morceaux, ignore_index=True)


def lire_reference(donnees):
    from django.http import QueryDict

    valeurs = QueryDict(mutable=True)
    for k in donnees:
        if k.startswith("ref_"):
            valeurs.setlist(k[4:], donnees.getlist(k))
    return periode.lire(valeurs)[0]


def libelle(plages):
    if len(plages) > 1 and periode.reguliere(plages):
        d, f = plages[0]
        lendemain = " (fin le lendemain)" if f.date() != d.date() else ""
        return f"Du {d:%d/%m/%Y} au {plages[-1][0]:%d/%m/%Y}, de {d:%Hh} à {f:%Hh}{lendemain}"
    return " ; ".join(f"{d:%d/%m/%Y de %Hh} à {f:%Hh}" +
                     (f" le {f:%d/%m/%Y}" if f.date() != d.date() else "") for d, f in plages)


def choix_reference(evenement, user, donnees, plages):
    """Résolution commune à l'écran et aux exports, sans déduire une édition de son nom."""
    mode = donnees.get("comparaison", "auto")
    archive = None
    if mode == "semaines":
        return None, None, "Moyenne des semaines précédentes, sites mobiles exclus faute d'affectation historique"
    if mode == "personnalisee":
        reference = lire_reference(donnees)
        if not reference:
            raise periode.PeriodeInvalide("Indiquez la période de référence.")
        return reference, None, ("Période personnalisée, calculée sur les sites fixes du périmètre analysé ; "
                                 "sites mobiles exclus faute d'affectation historique")
    if mode not in ("auto", "calendrier"):
        if not mode.isdecimal():
            raise periode.PeriodeInvalide("Référence inconnue.")
        archive = visibles(evenement, user).filter(pk=int(mode)).first()
        if not archive:
            raise periode.PeriodeInvalide("Édition de référence inaccessible.")
    elif mode == "auto" and plages:
        archive = visibles(evenement, user).filter(debut__year=plages[0][0].year - 1).first()
    if archive:
        return creneaux(archive), archive, f"Édition enregistrée : {archive.nom}"
    return periode.decaler(plages, mois=-12), None, (
        "Comparaison calendaire avec l'année précédente ; aucune édition enregistrée utilisée. "
        "Les sites mobiles sont exclus de cette référence faute d'affectation historique.")


def moteur_pour_analyse(fabrique, archive, archive_reference):
    if archive and archive_reference:
        return None
    try:
        return fabrique()
    except (BaseKpiNonConfiguree, SQLAlchemyError):
        if not archive:
            raise
        return None  # l'édition reste consultable, référence en N/D avec un avertissement
