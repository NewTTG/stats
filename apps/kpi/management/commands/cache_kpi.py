"""Inspection et purge du cache, sans afficher les données ou clés de recherche."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.kpi.cache import ouvrir


class Command(BaseCommand):
    help = "État du cache KPI partagé ; --vider pour forcer le rechargement des résultats."

    def add_arguments(self, parser):
        parser.add_argument("--vider", action="store_true")

    def handle(self, *args, **options):
        try:
            with ouvrir() as cache:
                if options["vider"]:
                    cache.clear()
                    cache.stats(reset=True)
                cache.expire()
                hits, misses = cache.stats()
                self.stdout.write(
                    f"Cache {'activé' if settings.KPI_CACHE_ENABLED else 'désactivé'} : "
                    f"{len(cache)} résultat(s), {cache.volume() / 1024**2:.2f} Mio "
                    f"/ {settings.KPI_CACHE_MAX_BYTES / 1024**2:.0f} Mio ; "
                    f"TTL {settings.KPI_CACHE_TTL} s ; lectures trouvées {hits}, absentes {misses}."
                )
        except Exception as exc:
            raise CommandError("Le cache KPI est inaccessible ; vérifier le répertoire et ses droits.") from exc
