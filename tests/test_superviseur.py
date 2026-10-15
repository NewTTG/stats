"""Superviseur des processus (manage.py superviser) et page « Processus du serveur » de l'administration."""

import json
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import JournalAudit
from config import superviseur
from config.superviseur import Superviseur

DORMIR = [sys.executable, "-c", "import time; print('pret', flush=True); time.sleep(60)"]
ECHOUER = [sys.executable, "-c", "raise SystemExit(3)"]


@pytest.fixture
def lanceur(settings):
    lances = []

    def creer(commandes):
        s = Superviseur(commandes, dossier=settings.SUPERVISEUR_DIR, racine=settings.BASE_DIR)
        s.dossier.mkdir(parents=True, exist_ok=True)
        lances.append(s)
        return s

    yield creer
    for s in lances:
        for p in s.processus.values():
            s.arreter(p, delai=5)


def _attendre(condition, delai=10):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_lance_publie_l_etat_et_redemarre_sur_demande(lanceur):
    s = lanceur({"app": DORMIR, "worker": DORMIR})
    for p in s.processus.values():
        s.demarrer(p)
    s.tour()
    etat = superviseur.lire_etat()
    assert etat["actif"] and etat["pid"]
    assert {n: p["en_marche"] for n, p in etat["processus"].items()} == {"app": True, "worker": True}
    assert etat["processus"]["worker"]["libelle"] == "Worker des rapports et exports"

    pid_app, pid_worker = (s.processus[n].popen.pid for n in ("app", "worker"))
    assert superviseur.demander_redemarrage(["worker"], "admin") == ["worker"]
    assert superviseur.demande_en_attente()["auteur"] == "admin"
    s.tour()
    assert superviseur.demande_en_attente() is None
    assert s.processus["worker"].popen.pid != pid_worker and s.processus["worker"].en_marche
    assert s.processus["app"].popen.pid == pid_app  # non concerné
    assert s.processus["worker"].redemarrages == 0  # redémarrage demandé, pas une relance après arrêt
    assert _attendre(lambda: "pret" in superviseur.fin_journal("worker"))
    assert "redémarrage demandé par admin : worker" in superviseur.fin_journal("superviseur")


def test_demandes_cumulees():
    superviseur.demander_redemarrage(["worker"], "a")
    assert superviseur.demander_redemarrage(["app"], "b") == ["app", "worker"]


def test_relance_un_processus_arrete_de_lui_meme(lanceur):
    s = lanceur({"worker": ECHOUER})
    p = s.processus["worker"]
    s.demarrer(p)
    assert _attendre(lambda: p.popen.poll() is not None)
    s.tour()
    assert p.dernier_code == 3 and p.relance_a is not None and p.redemarrages == 0
    assert "arrêté de lui-même (code 3)" in superviseur.fin_journal("superviseur")
    p.relance_a = time.monotonic()  # délai écoulé
    s.tour()
    assert p.redemarrages == 1 and p.relance_a is None


@pytest.mark.skipif(sys.platform == "win32", reason="groupe de processus POSIX")
def test_arret_inattendu_arrete_les_sous_processus_orphelins(lanceur, tmp_path):
    """Worker tué : ses processus de calcul ne restent pas en vie à côté du nouveau worker."""
    fichier = tmp_path / "petit_enfant.pid"
    code = ("import subprocess, sys; e = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(fichier)!r}, 'w').write(str(e.pid)); raise SystemExit(9)")
    s = lanceur({"worker": [sys.executable, "-c", code]})
    p = s.processus["worker"]
    s.demarrer(p)
    assert _attendre(lambda: p.popen.poll() is not None)
    petit_enfant = int(fichier.read_text())
    assert _vivant(petit_enfant)
    s.tour()
    assert _attendre(lambda: not _vivant(petit_enfant))


def _vivant(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"  # zombie : déjà arrêté
    except FileNotFoundError:
        return False


def test_arret(lanceur):
    s = lanceur({"app": DORMIR})
    p = s.processus["app"]
    s.demarrer(p)
    s.arreter(p, delai=5)
    assert not p.en_marche


def test_preparation_avant_l_application(lanceur, tmp_path):
    """Après un git pull, le redémarrage de l'application applique d'abord les migrations."""
    trace = tmp_path / "trace.txt"

    def etape(nom, code=0):
        return [sys.executable, "-c", f"open({str(trace)!r}, 'a').write({nom!r} + chr(10)); raise SystemExit({code})"]

    s = lanceur({"app": DORMIR, "worker": DORMIR})
    s.etapes = [("dépendances", etape("pip")), ("migrations de la base", etape("migrate", 1)),
                ("fichiers statiques", etape("collectstatic"))]
    s.redemarrer(["app", "worker"])
    assert trace.read_text().split() == ["pip", "migrate", "collectstatic"]  # un échec n'arrête pas la suite
    assert all(p.en_marche for p in s.processus.values())  # ni le démarrage
    s.ecrire_etat()
    preparation = superviseur.lire_etat()["preparation"]
    assert preparation["ok"] is False and preparation["echecs"] == ["migrations de la base"]
    assert "échec « migrations de la base »" in superviseur.fin_journal("superviseur")
    assert "migrations de la base" in superviseur.fin_journal("preparation")

    trace.unlink()
    superviseur.demander_redemarrage(["worker"], "admin")
    s.tour()
    assert not trace.exists()  # worker seul : pas de préparation


def test_etapes_de_preparation():
    etapes = dict(superviseur.preparation())
    assert etapes["dépendances"][-2:] == ["-r", str(superviseur.settings.BASE_DIR / "requirements.txt")]
    assert etapes["migrations de la base"][-2:] == ["migrate", "--noinput"]
    assert etapes["fichiers statiques"][-2:] == ["collectstatic", "--noinput"]


def test_commandes(settings):
    cmds = superviseur.commandes(8082)
    assert cmds["app"][-3:] == ["runserver", "0.0.0.0:8082", "--noreload"]
    assert cmds["worker"][-1] == "qcluster"
    assert "--bind" in superviseur.commandes(8082, serveur="gunicorn")["app"]
    assert "worker" not in superviseur.commandes(8082, avec_worker=False)


# ------------------------------------------------------------------ administration

def _etat_frais(settings, secondes=0):
    settings.SUPERVISEUR_DIR.mkdir(parents=True, exist_ok=True)
    battement = datetime.now(timezone.utc) - timedelta(seconds=secondes)
    (settings.SUPERVISEUR_DIR / "etat.json").write_text(json.dumps({
        "pid": 1234, "demarre_le": battement.isoformat(), "battement": battement.isoformat(),
        "hote": "0.0.0.0", "port": 8082, "serveur": "runserver",
        "preparation": {"le": battement.isoformat(), "ok": False, "echecs": ["migrations de la base"]},
        "processus": {"app": {"nom": "app", "pid": 11, "en_marche": True, "demarre_le": battement.isoformat(),
                              "redemarrages": 0, "dernier_code": None, "commande": "python manage.py runserver"}},
    }), encoding="utf-8")


@pytest.mark.django_db
def test_page_reservee_aux_superutilisateurs(client):
    personnel = User.objects.create_user("gestion", password="secret-123-Abc", is_staff=True)
    client.force_login(personnel)
    assert client.get("/admin/processus/").status_code == 403
    assert client.post("/admin/processus/", {"cible": "tout"}).status_code == 403
    assert superviseur.demande_en_attente() is None


@pytest.mark.django_db
def test_page_sans_superviseur(client, settings):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    html = client.get("/admin/processus/").content.decode()
    assert "Jamais lancé" in html and "Processus du serveur" in html
    assert 'name="cible"' not in html
    reponse = client.post("/admin/processus/", {"cible": "worker"}, follow=True)
    assert "Le superviseur ne tourne pas" in reponse.content.decode()
    assert superviseur.demande_en_attente() is None

    _etat_frais(settings, secondes=60)  # battement trop ancien
    assert "Arrêté" in client.get("/admin/processus/").content.decode()


@pytest.mark.django_db
def test_redemarrage_depuis_l_administration(client, settings):
    admin = User.objects.create_superuser("admin", password="secret-123-Abc")
    client.force_login(admin)
    _etat_frais(settings)
    html = client.get("/admin/").content.decode()
    assert "/admin/processus/" in html  # menu latéral, rubrique Système
    html = client.get("/admin/processus/").content.decode()
    assert "Actif" in html and "0.0.0.0:8082" in html and 'value="tout"' in html
    assert "Échec : migrations de la base" in html and "Mise à niveau" in html

    reponse = client.post("/admin/processus/", {"cible": "tout"}, follow=True)
    assert "Redémarrage demandé" in reponse.content.decode()
    assert superviseur.demande_en_attente()["processus"] == ["app", "worker"]
    journal = JournalAudit.objects.get(action="redemarrage_processus")
    assert journal.utilisateur == admin and journal.requete == {"processus": ["app", "worker"]}

    client.post("/admin/processus/", {"cible": "inconnu"})
    assert JournalAudit.objects.filter(action="redemarrage_processus").count() == 1
