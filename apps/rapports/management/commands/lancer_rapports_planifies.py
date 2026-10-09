from django.core.management.base import BaseCommand

from apps.rapports.planification import lancer_dus


class Command(BaseCommand):
    help = ("Lance les rapports planifiés arrivés à échéance (fait automatiquement toutes les 15 minutes "
            "par le worker qcluster ; utile depuis un cron sans worker).")

    def handle(self, **options):
        self.stdout.write(f"{lancer_dus()} rapport(s) lancé(s).")
