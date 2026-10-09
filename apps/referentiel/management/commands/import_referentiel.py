from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.referentiel.importation import importer


class Command(BaseCommand):
    help = "Importe le référentiel réseau (xlsx) et, optionnellement, les cellules d'exports KPI CSV."

    def add_arguments(self, parser):
        parser.add_argument("fichier", type=Path, help="référentiel xlsx (onglet Site_File)")
        parser.add_argument("--cellules", type=Path, nargs="*", default=[],
                            help="exports KPI CSV (LTE ou WCDMA) dont on extrait les noms de cellules")
        parser.add_argument("--auteur", help="nom d'utilisateur enregistré comme auteur de l'import")

    def handle(self, fichier, cellules, auteur, **options):
        for chemin in [fichier, *cellules]:
            if not chemin.exists():
                raise CommandError(f"fichier introuvable : {chemin}")
        utilisateur = None
        if auteur:
            utilisateur = get_user_model().objects.filter(username=auteur).first()
            if utilisateur is None:
                raise CommandError(f"utilisateur inconnu : {auteur}")
        try:
            imp = importer(fichier, cellules, auteur=utilisateur)
        except ValueError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(self.style.SUCCESS(
            f"Import n°{imp.pk} : {imp.nb_sites} sites, {imp.nb_secteurs} secteurs, "
            f"{len(imp.ajouts)} ajouts, {len(imp.suppressions)} suppressions."
        ))
        if imp.anomalies:
            self.stdout.write(self.style.WARNING(f"{len(imp.anomalies)} anomalies :"))
            for anomalie in imp.anomalies:
                self.stdout.write(f"  - {anomalie}")
