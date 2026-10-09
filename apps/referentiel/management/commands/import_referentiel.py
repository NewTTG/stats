from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.kpi.source import BaseKpiNonConfiguree, cellules_distinctes, moteur_kpi
from apps.referentiel.importation import importer


class Command(BaseCommand):
    help = ("Importe le référentiel réseau (xlsx) et les cellules, lues dans la base KPI "
            "(--cellules-kpi) et/ou dans des exports KPI CSV (--cellules).")

    def add_arguments(self, parser):
        parser.add_argument("fichier", type=Path, help="référentiel xlsx (onglet Site_File)")
        parser.add_argument("--cellules", type=Path, nargs="*", default=[],
                            help="exports KPI CSV (LTE ou WCDMA) dont on extrait les noms de cellules")
        parser.add_argument("--cellules-kpi", action="store_true",
                            help="toutes les cellules des tables journalières de la base KPI (tout l'historique)")
        parser.add_argument("--auteur", help="nom d'utilisateur enregistré comme auteur de l'import")

    def handle(self, fichier, cellules, cellules_kpi, auteur, **options):
        for chemin in [fichier, *cellules]:
            if not chemin.exists():
                raise CommandError(f"fichier introuvable : {chemin}")
        utilisateur = None
        if auteur:
            utilisateur = get_user_model().objects.filter(username=auteur).first()
            if utilisateur is None:
                raise CommandError(f"utilisateur inconnu : {auteur}")
        noms = None
        if cellules_kpi:
            try:
                engine = moteur_kpi()
                noms = {techno: cellules_distinctes(engine, techno) for techno in ("LTE", "WCDMA")}
            except BaseKpiNonConfiguree as e:
                raise CommandError(str(e)) from e
            self.stdout.write(f"Base KPI : {len(noms['LTE'])} cellules LTE, {len(noms['WCDMA'])} cellules WCDMA.")
        try:
            imp = importer(fichier, cellules, auteur=utilisateur, cellules=noms)
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
