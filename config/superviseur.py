"""Superviseur des processus du serveur : application web et worker des rapports (exports).

``python manage.py superviser`` lance les deux processus, les relance s'ils s'arrêtent et exécute
les redémarrages demandés depuis l'administration (Système → Processus). Il est démarré avec le
serveur : tâche planifiée Windows (scripts/windows/installer_demarrage.ps1) ou service systemd
(scripts/linux/stats.service).

Échanges avec l'application par fichiers, dans ``SUPERVISEUR_DIR`` (défaut data/superviseur) :
- ``etat.json`` : écrit par le superviseur toutes les 2 s (PID, démarrages, redémarrages) ;
- ``demande.json`` : déposé par l'administration, lu puis supprimé par le superviseur ;
- ``app.log``, ``worker.log``, ``superviseur.log`` : sorties des processus, à la place des consoles.
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

WINDOWS = os.name == "nt"
PROCESSUS = {"app": "Application web", "worker": "Worker des rapports et exports"}
# Boutons de l'administration : cible → processus redémarrés.
CIBLES = {"worker": ["worker"], "app": ["app"], "tout": ["app", "worker"]}
BATTEMENT_S = 2  # écriture de etat.json
SILENCE_MAX_S = 15  # au-delà sans battement, le superviseur est considéré arrêté
ARRET_DELAI_S = 30  # arrêt propre attendu avant de forcer
JOURNAL_MAX_OCTETS = 10 * 1024 * 1024  # au-delà, le journal passe en .log.1 au prochain démarrage


def repertoire():
    return Path(settings.SUPERVISEUR_DIR)


def _maintenant():
    return datetime.now(timezone.utc)


def _ecrire_json(chemin, donnees):
    """Écriture atomique : un lecteur ne voit jamais un fichier à moitié écrit."""
    temporaire = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
    temporaire.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    os.replace(temporaire, chemin)


def _lire_json(chemin):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ côté application (administration)

def lire_etat():
    """État publié par le superviseur, avec ``actif`` (battement récent) ; None s'il n'a jamais tourné."""
    etat = _lire_json(repertoire() / "etat.json")
    if not isinstance(etat, dict):
        return None
    for cle in ("demarre_le", "battement"):
        etat[cle] = _date(etat.get(cle))
    for p in (etat.get("processus") or {}).values():
        p["demarre_le"] = _date(p.get("demarre_le"))
        p["libelle"] = PROCESSUS.get(p.get("nom"), p.get("nom"))
    etat["actif"] = bool(etat["battement"]) and (_maintenant() - etat["battement"]).total_seconds() < SILENCE_MAX_S
    return etat


def _date(texte):
    try:
        return datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def demander_redemarrage(processus, auteur):
    """Dépose une demande ; une demande encore en attente est complétée, pas remplacée."""
    repertoire().mkdir(parents=True, exist_ok=True)
    chemin = repertoire() / "demande.json"
    precedente = _lire_json(chemin) or {}
    cibles = sorted(set(precedente.get("processus") or []) | set(processus))
    _ecrire_json(chemin, {"processus": cibles, "auteur": auteur, "le": _maintenant().isoformat()})
    return cibles


def demande_en_attente():
    demande = _lire_json(repertoire() / "demande.json")
    return demande if isinstance(demande, dict) else None


def fin_journal(nom, lignes=40, octets=16384):
    """Dernières lignes du journal d'un processus ('' s'il n'existe pas)."""
    try:
        with open(repertoire() / f"{nom}.log", "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - octets))
            texte = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(texte.splitlines()[-lignes:])


# ------------------------------------------------------------------ côté superviseur

def commandes(port, hote="0.0.0.0", serveur="runserver", workers_web=3, avec_worker=True):
    """Commandes lancées depuis la racine du dépôt, avec le Python courant (celui du .venv)."""
    manage = str(Path(settings.BASE_DIR) / "manage.py")
    if serveur == "gunicorn":
        app = [sys.executable, "-m", "gunicorn", "config.wsgi:application", "--bind", f"{hote}:{port}",
               "--workers", str(workers_web), "--timeout", "120"]
    else:
        app = [sys.executable, manage, "runserver", f"{hote}:{port}", "--noreload"]
    resultat = {"app": app}
    if avec_worker:
        resultat["worker"] = [sys.executable, manage, "qcluster"]
    return resultat


class _TacheWindows:
    """Objet tâche (Job Object) Windows d'un processus et de ses sous-processus : ils s'arrêtent avec
    le superviseur, même tué (fin de la tâche planifiée), au lieu de rester orphelins sur le port."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Basique(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class CompteursES(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                       "OtherOperationCount", "ReadTransferCount",
                                                       "WriteTransferCount", "OtherTransferCount")]

        class Etendue(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basique), ("IoInfo", CompteursES),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32, self._ctypes = k32, ctypes
        self._job = k32.CreateJobObjectW(None, None)
        if not self._job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Etendue()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self._job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def ajouter(self, popen):
        if not self._k32.AssignProcessToJobObject(self._job, int(popen._handle)):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def fermer(self):
        """Arrête tout ce qui reste dans l'objet tâche, puis le libère."""
        self._k32.TerminateJobObject(self._job, 1)
        self._k32.CloseHandle(self._job)


class Processus:
    def __init__(self, nom, commande):
        self.nom, self.commande = nom, commande
        self.popen = None
        self.tache = None  # Windows : objet tâche du processus
        self.demarre_le = None  # datetime UTC
        self.lance_a = 0.0  # time.monotonic() du dernier lancement
        self.redemarrages = 0  # relances après un arrêt inattendu
        self.dernier_code = None
        self.echecs_rapides = 0
        self.relance_a = None  # time.monotonic() avant lequel ne pas relancer

    @property
    def en_marche(self):
        return self.popen is not None and self.popen.poll() is None

    def etat(self):
        return {"nom": self.nom, "pid": self.popen.pid if self.en_marche else None, "en_marche": self.en_marche,
                "demarre_le": self.demarre_le.isoformat() if self.en_marche and self.demarre_le else None,
                "redemarrages": self.redemarrages, "dernier_code": self.dernier_code,
                "commande": " ".join(self.commande)}


class Superviseur:
    def __init__(self, commandes, dossier=None, racine=None, sortie=None):
        self.dossier = Path(dossier or repertoire())
        self.racine = Path(racine or settings.BASE_DIR)
        self.processus = {nom: Processus(nom, cmd) for nom, cmd in commandes.items()}
        self.sortie = sortie or sys.stdout
        self.demarre_le = _maintenant()
        self.arret_demande = False
        self._dernier_battement = 0.0
        self.infos = {}

    # -------------------------------------------------------------- journal du superviseur
    def journal(self, message):
        ligne = f"[{datetime.now().astimezone():%Y-%m-%d %H:%M:%S}] {message}"
        try:
            print(ligne, file=self.sortie, flush=True)
        except (OSError, ValueError):
            pass  # pas de console (tâche planifiée)
        try:
            with open(self.dossier / "superviseur.log", "a", encoding="utf-8") as f:
                f.write(ligne + "\n")
        except OSError:
            pass

    # -------------------------------------------------------------- lancement et arrêt
    def _ouvrir_journal(self, nom):
        chemin = self.dossier / f"{nom}.log"
        try:
            if chemin.stat().st_size > JOURNAL_MAX_OCTETS:
                os.replace(chemin, chemin.with_name(f"{nom}.log.1"))
        except OSError:
            pass
        return open(chemin, "ab")

    def demarrer(self, p):
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
                   else {"start_new_session": True})
        with self._ouvrir_journal(p.nom) as journal:
            journal.write(f"\n===== {datetime.now().astimezone():%Y-%m-%d %H:%M:%S} démarrage : "
                          f"{' '.join(p.commande)}\n".encode())
            journal.flush()
            p.popen = subprocess.Popen(p.commande, cwd=self.racine, env=env, stdin=subprocess.DEVNULL,
                                       stdout=journal, stderr=subprocess.STDOUT, **options)
        if WINDOWS:
            try:
                p.tache = _TacheWindows()
                p.tache.ajouter(p.popen)
            except OSError as e:
                p.tache = None
                self.journal(f"{p.nom} : objet tâche Windows indisponible ({e}), ses sous-processus pourraient "
                             "survivre à un arrêt brutal")
        p.demarre_le, p.lance_a, p.relance_a = _maintenant(), time.monotonic(), None
        self.journal(f"{p.nom} démarré (PID {p.popen.pid})")

    def arreter(self, p, delai=ARRET_DELAI_S):
        if not p.en_marche:
            return
        pid = p.popen.pid
        try:
            if WINDOWS:  # tout l'arbre : runserver, qcluster et ses processus de calcul
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
            else:  # comme systemd ou Docker : le processus principal arrête proprement les siens
                os.kill(pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            p.popen.wait(delai)
        except subprocess.TimeoutExpired:
            self.journal(f"{p.nom} : arrêt forcé après {delai} s")
            if WINDOWS and not p.tache:
                p.popen.kill()
        self._achever(p)
        p.popen.wait()
        p.dernier_code = p.popen.returncode
        self.journal(f"{p.nom} arrêté (PID {pid})")

    def _achever(self, p):
        """Arrête ce qui reste du processus : lui-même s'il tourne encore, ses sous-processus orphelins
        (worker tué : processus de calcul de qcluster encore en vie)."""
        if p.tache:
            p.tache.fermer()
            p.tache = None
        elif not WINDOWS:
            try:
                os.killpg(p.popen.pid, signal.SIGKILL)  # groupe créé au lancement (start_new_session)
            except OSError:
                pass  # plus aucun processus dans le groupe

    def redemarrer(self, p):
        self.arreter(p)
        self.demarrer(p)

    # -------------------------------------------------------------- boucle
    def _prendre_demande(self):
        chemin = self.dossier / "demande.json"
        if not chemin.exists():
            return None
        demande = _lire_json(chemin)
        try:
            chemin.unlink()
        except OSError:
            return None  # fichier en cours d'écriture : prochain tour
        return demande if isinstance(demande, dict) else {}

    def tour(self):
        """Un passage : demande de l'administration, processus arrêtés, battement."""
        demande = self._prendre_demande()
        if demande is not None:
            noms = [n for n in demande.get("processus") or [] if n in self.processus]
            self.journal(f"redémarrage demandé par {demande.get('auteur') or '?'} : {', '.join(noms) or 'rien'}")
            for nom in noms:
                self.redemarrer(self.processus[nom])
        maintenant = time.monotonic()
        for p in self.processus.values():
            if p.popen is None or p.en_marche:
                continue
            if p.relance_a is None:  # arrêt inattendu : relance différée, plus longue s'il s'arrête aussitôt
                p.dernier_code = p.popen.returncode
                self._achever(p)
                p.echecs_rapides = p.echecs_rapides + 1 if maintenant - p.lance_a < 30 else 0
                delai = min(60, 2 ** p.echecs_rapides)
                p.relance_a = maintenant + delai
                self.journal(f"{p.nom} arrêté de lui-même (code {p.dernier_code}) : relance dans {delai} s, "
                             f"voir {p.nom}.log")
            elif maintenant >= p.relance_a:
                p.redemarrages += 1
                self.demarrer(p)
        if maintenant - self._dernier_battement >= BATTEMENT_S:
            self.ecrire_etat()
            self._dernier_battement = maintenant

    def ecrire_etat(self):
        try:
            _ecrire_json(self.dossier / "etat.json", {
                "pid": os.getpid(), "demarre_le": self.demarre_le.isoformat(),
                "battement": _maintenant().isoformat(), **self.infos,
                "processus": {nom: p.etat() for nom, p in self.processus.items()},
            })
        except OSError as e:  # Windows : fichier ouvert par un lecteur, réessayé au prochain battement
            self.journal(f"etat.json non écrit ({e})")

    def _signal(self, *args):
        self.arret_demande = True

    def executer(self, intervalle=1.0):
        from filelock import FileLock, Timeout

        self.dossier.mkdir(parents=True, exist_ok=True)
        verrou = FileLock(str(self.dossier / "superviseur.lock"))
        try:
            verrou.acquire(timeout=0)
        except Timeout:
            raise RuntimeError(f"Un superviseur tourne déjà (verrou {self.dossier / 'superviseur.lock'}).") from None
        try:
            for nom in ("SIGTERM", "SIGBREAK"):
                if hasattr(signal, nom):
                    signal.signal(getattr(signal, nom), self._signal)
            (self.dossier / "demande.json").unlink(missing_ok=True)  # demande antérieure au démarrage
            self.journal(f"superviseur démarré (PID {os.getpid()})")
            for p in self.processus.values():
                self.demarrer(p)
            try:
                while not self.arret_demande:
                    self.tour()
                    time.sleep(intervalle)
            except KeyboardInterrupt:
                pass
            self.journal("arrêt du superviseur")
            for p in self.processus.values():
                self.arreter(p)
            (self.dossier / "etat.json").unlink(missing_ok=True)
        finally:
            verrou.release()
