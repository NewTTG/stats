"""Rechargement du référentiel depuis l'administration : même traitement que
``manage.py import_referentiel`` (puis, au choix, ``detecter_bascules --enregistrer``).

Le xlsx de référence est le dernier déposé dans l'administration (``MEDIA_ROOT/referentiel/``),
sinon ``settings.REFERENTIEL_XLSX``. Un fichier déposé ne devient la référence qu'une fois
son import réussi.
"""

import shutil
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils.text import get_valid_filename

from apps.kpi.source import BaseKpiNonConfiguree, cellules_distinctes, moteur_kpi

from .importation import importer
from .models import Site


class RechargementImpossible(Exception):
    """Fichier illisible ou incomplet, base KPI indisponible : message affiché tel quel."""


def dossier_depots() -> Path:
    return Path(settings.MEDIA_ROOT) / "referentiel"


def fichier_courant() -> Path | None:
    dossier = dossier_depots()
    depots = sorted(dossier.glob("*.xlsx"), key=lambda p: p.stat().st_mtime) if dossier.is_dir() else []
    if depots:
        return depots[-1]
    defaut = Path(settings.REFERENTIEL_XLSX)
    return defaut if defaut.exists() else None


def base_kpi_disponible() -> bool:
    try:
        moteur_kpi()
    except BaseKpiNonConfiguree:
        return False
    return True


def peut_recharger(utilisateur) -> bool:
    # L'ajout manuel d'un import est fermé (has_add_permission) : le droit sert au rechargement.
    return utilisateur.has_perm("referentiel.add_importreferentiel")


def _enregistrer_bascules() -> int:
    """Dates de passage à 4 secteurs encore vides : renseignées d'après la base KPI."""
    from .management.commands.detecter_bascules import detecter

    enregistrees = 0
    for code_site, bascule in detecter(moteur_kpi()).items():
        if bascule is not None:
            enregistrees += Site.objects.filter(code_site=code_site, bascule_4_secteurs__isnull=True).update(
                bascule_4_secteurs=bascule)
    return enregistrees


def recharger(auteur, depot=None, cellules_kpi=False, bascules=False):
    """Importe ``depot`` (fichier envoyé) ou le xlsx de référence. Renvoie (import, bascules enregistrées)."""
    with tempfile.TemporaryDirectory() as temporaire:
        if depot is not None:
            nom = get_valid_filename(Path(depot.name).name) or "referentiel.xlsx"
            chemin = Path(temporaire) / nom
            with chemin.open("wb") as sortie:
                for morceau in depot.chunks():
                    sortie.write(morceau)
        else:
            chemin = fichier_courant()
            if chemin is None:
                raise RechargementImpossible(
                    "Aucun fichier de référentiel sur le serveur : déposez le xlsx (onglet Site_File).")

        noms = None
        if cellules_kpi or bascules:
            try:
                engine = moteur_kpi()
            except BaseKpiNonConfiguree as e:
                raise RechargementImpossible(str(e)) from e
            if cellules_kpi:
                noms = {techno: cellules_distinctes(engine, techno) for techno in ("LTE", "WCDMA")}
        try:
            with transaction.atomic():
                imp = importer(chemin, auteur=auteur, cellules=noms)
        except (ValueError, KeyError, zipfile.BadZipFile) as e:
            raise RechargementImpossible(f"Fichier non importé : {e}") from e

        if depot is not None:
            dossier_depots().mkdir(parents=True, exist_ok=True)
            shutil.copyfile(chemin, dossier_depots() / chemin.name)
    return imp, (_enregistrer_bascules() if bascules else None)
