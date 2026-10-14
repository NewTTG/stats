"""Durée de chaque requête : journal ``stats.requetes`` (INFO, WARNING au-delà de REQUETE_LENTE_S)
et en-tête ``Server-Timing`` (outils de développement du navigateur).

Rien n'est ajouté au contenu des pages : à demande équivalente, la page reste identique au mot près
(cf. tests/test_controle_tour4.py). Les fichiers statiques ne sont pas journalisés.
"""

import logging
import time

from django.conf import settings

journal = logging.getLogger("stats.requetes")


def _duree(secondes: float) -> str:
    return f"{secondes * 1000:.0f} ms" if secondes < 1 else f"{secondes:.1f} s".replace(".", ",")


class DureeRequeteMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        debut = time.perf_counter()
        reponse = self.get_response(request)
        duree = time.perf_counter() - debut
        mesure = f"app;dur={duree * 1000:.0f}"
        reponse["Server-Timing"] = f"{reponse['Server-Timing']}, {mesure}" if reponse.has_header("Server-Timing") else mesure
        if not request.path.startswith(("/" + settings.STATIC_URL.lstrip("/"), "/favicon.ico")):
            lente = duree >= settings.REQUETE_LENTE_S
            journal.log(logging.WARNING if lente else logging.INFO, "%s %s %s en %s%s", request.method,
                        request.get_full_path()[:300], reponse.status_code, _duree(duree), " (lente)" if lente else "")
        return reponse
