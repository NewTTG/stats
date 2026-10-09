from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comptes.visiteurs import PREFIXE


class Command(BaseCommand):
    help = ("Supprime les sessions visiteur inactives (cookie effacé ou navigateur abandonné), "
            "avec leur historique de rapports ; le journal d'audit est conservé.")

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=400, help="inactivité minimale (défaut : 400 jours)")

    def handle(self, jours, **options):
        limite = timezone.now() - timedelta(days=jours)
        anciens = get_user_model().objects.filter(username__startswith=PREFIXE, password__startswith="!",
                                                  last_login__lt=limite)
        nombre = anciens.count()
        anciens.delete()
        self.stdout.write(f"{nombre} visiteur(s) inactif(s) depuis plus de {jours} jours supprimé(s).")
