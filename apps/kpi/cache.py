"""Cache de résultats partagé sur disque local, borné et à expiration fixe.

Les appelants doivent résoudre les droits avant de construire leur clé. Aucun objet
utilisateur, historique ou fichier de rapport n'est mémorisé ici. Le répertoire est
privé à l'application (les résultats pandas sont sérialisés avec pickle).
"""

import hashlib
import json
import logging
import pickle
import time
from pathlib import Path

from diskcache import Cache
from django.conf import settings
from filelock import FileLock, Timeout

journal = logging.getLogger(__name__)
VERSION = 2  # À incrémenter si la structure ou la sémantique des résultats change.
ABSENT = object()


def ouvrir():
    dossier = Path(settings.KPI_CACHE_DIR)
    dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
    return Cache(str(dossier), timeout=1, size_limit=settings.KPI_CACHE_MAX_BYTES,
                 eviction_policy="least-recently-used", disk_min_file_size=1,
                 statistics=True, cull_limit=1)


def _lire(cache, cle):
    try:
        valeur = cache.get(cle, default=ABSENT)
        return ABSENT if valeur is ABSENT else pickle.loads(valeur)
    except Exception:
        # Cache absent/corrompu/inaccessible : la source reste utilisable.
        journal.warning("Lecture du cache KPI impossible ; recalcul depuis la source.")
        return ABSENT


def memoriser(espace, parametres, calculer, *, actif=True):
    """Réutilise un résultat, sans prolonger sa fraîcheur lors des consultations.

    Les verrous OS sont libérés même si un worker meurt ; 256 fichiers au plus.
    Deux clés différentes peuvent partager un verrou, mais jamais leurs résultats.
    Une attente trop longue ou une panne du cache laisse la requête se calculer.
    Les exceptions du calcul ne sont ni interceptées ni mises en cache.
    """
    if (not actif or not settings.KPI_CACHE_ENABLED or settings.KPI_CACHE_TTL <= 0
            or settings.KPI_CACHE_MAX_BYTES <= 0 or settings.KPI_CACHE_ITEM_MAX_BYTES <= 0):
        return calculer()
    empreinte = hashlib.sha256(json.dumps(
        [VERSION, settings.KPI_CACHE_TTL, espace, parametres], sort_keys=True, default=str,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    try:
        cache = ouvrir()
    except Exception:
        journal.warning("Cache KPI indisponible ; calcul depuis la source.")
        return calculer()
    try:
        valeur = _lire(cache, empreinte)
        if valeur is not ABSENT:
            return valeur
        verrou = FileLock(str(Path(settings.KPI_CACHE_DIR) / f"{empreinte[:2]}.lock"))
        try:
            verrou.acquire(timeout=settings.KPI_CACHE_WAIT_SECONDS)
        except (Timeout, OSError):
            journal.warning("Verrou du cache KPI indisponible ; calcul depuis la source.")
            return calculer()
        try:
            valeur = _lire(cache, empreinte)
            if valeur is not ABSENT:
                return valeur
            debut = time.monotonic()
            valeur = calculer()
            try:
                contenu = pickle.dumps(valeur, protocol=pickle.HIGHEST_PROTOCOL)
                restant = settings.KPI_CACHE_TTL - (time.monotonic() - debut)
                # Une réponse volumineuse est renvoyée normalement sans remplir le cache.
                limite = min(settings.KPI_CACHE_ITEM_MAX_BYTES, settings.KPI_CACHE_MAX_BYTES)
                if len(contenu) <= limite and restant > 0:
                    cache.set(empreinte, contenu, expire=restant)
                    cache.cull()  # supprime les expirés, puis les moins récemment consultés
            except Exception:
                journal.warning("Écriture du cache KPI impossible ; résultat renvoyé sans cache.")
            return valeur
        finally:
            verrou.release()
    finally:
        cache.close()
