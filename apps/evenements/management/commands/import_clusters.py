from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.evenements.clusters import importer_clusters


class Command(BaseCommand):
    help = "Crée un événement (sans créneau) par cluster de l'onglet Cluster du référentiel xlsx."

    def add_arguments(self, parser):
        parser.add_argument("fichier", type=Path)

    def handle(self, fichier, **options):
        if not fichier.exists():
            raise CommandError(f"fichier introuvable : {fichier}")
        try:
            crees, ignores = importer_clusters(fichier)
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(f"{len(crees)} événement(s) créé(s), créneaux à renseigner dans l'admin."))
        if ignores:
            self.stdout.write(f"{len(ignores)} déjà présent(s), non modifié(s) : {', '.join(ignores)}")
