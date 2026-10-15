"""Lance l'application web et le worker des rapports, les relance s'ils s'arrêtent (config/superviseur.py)."""

import os

from django.core.management.base import BaseCommand, CommandError

from config.superviseur import WINDOWS, Superviseur, commandes, preparation, repertoire


class Command(BaseCommand):
    help = ("Lance l'application web (port 8082 par défaut) et le worker des rapports, les relance s'ils "
            "s'arrêtent et exécute les redémarrages demandés dans l'administration (Système → Processus). "
            "À démarrer avec le serveur : voir README, « Démarrage automatique ».")

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT") or 8082))
        parser.add_argument("--hote", default=os.environ.get("APP_HOTE") or "0.0.0.0",
                            help="adresse d'écoute (défaut 0.0.0.0 : toutes les interfaces)")
        parser.add_argument("--serveur", choices=["runserver", "gunicorn"],
                            default="runserver" if WINDOWS else "gunicorn",
                            help="serveur web (défaut : runserver sous Windows, gunicorn ailleurs)")
        parser.add_argument("--workers-web", type=int, default=3, help="processus gunicorn (défaut 3)")
        parser.add_argument("--sans-worker", action="store_true",
                            help="application seule (rapports générés pendant la requête : Q_SYNC=1)")
        parser.add_argument("--sans-preparation", action="store_true",
                            help="ne pas lancer pip install, migrate et collectstatic avant l'application")

    def handle(self, *args, **options):
        if options["serveur"] == "gunicorn" and WINDOWS:
            raise CommandError("gunicorn ne fonctionne pas sous Windows : utiliser --serveur runserver.")
        cmds = commandes(options["port"], options["hote"], options["serveur"], options["workers_web"],
                         avec_worker=not options["sans_worker"])
        superviseur = Superviseur(cmds, etapes=() if options["sans_preparation"] else preparation())
        superviseur.infos = {"hote": options["hote"], "port": options["port"], "serveur": options["serveur"]}
        self.stdout.write(f"Application sur http://{options['hote']}:{options['port']}/ ; "
                          f"journaux dans {repertoire()}. Ctrl+C pour tout arrêter.")
        try:
            superviseur.executer()
        except RuntimeError as e:
            raise CommandError(str(e)) from None
