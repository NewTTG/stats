"""Accès sans compte : une session « visiteur » par navigateur, avec son propre historique."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.comptes.acces import voit_tout_le_reseau
from apps.comptes.models import JournalAudit
from apps.comptes.visiteurs import est_visiteur

from .test_service import base_kpi, referentiel  # noqa: F401  (fixtures)
from .test_vues import PARAMS

pytestmark = pytest.mark.django_db


def _visiteur(client) -> User:
    return User.objects.get(pk=client.session["_auth_user_id"])


def test_premiere_visite_ouvre_une_session(client):
    r = client.get("/")
    assert r.status_code == 200
    user = _visiteur(client)
    assert est_visiteur(user) and voit_tout_le_reseau(user)
    html = r.content.decode()
    assert "Session de ce navigateur" in html and "Déconnexion" not in html
    assert "Mes rapports" in html
    # même navigateur (même cookie) : même visiteur
    client.get("/rapports/")
    assert User.objects.filter(username__startswith="visiteur-").count() == 1
    assert client.cookies["sessionid"]["max-age"] == 365 * 24 * 3600


def test_historique_propre_a_chaque_navigateur(referentiel, base_kpi, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.kpi.views.moteur_kpi", lambda: base_kpi)
    a, b = Client(), Client()
    a.get("/"), b.get("/")
    a.get("/", {"q": "trafic 4G à Nouméa du 1 au 2 septembre 2026"})
    a.get("/", PARAMS)
    assert JournalAudit.objects.filter(utilisateur=_visiteur(a)).count() == 2
    html_a, html_b = a.get("/").content.decode(), b.get("/").content.decode()
    assert "trafic 4G à Nouméa du 1 au 2 septembre 2026" in html_a and "Vos recherches apparaîtront ici." in html_b
    # « Modifier » : la recherche revient dans la barre, sans être relancée
    assert "?reprendre=trafic+4G+%C3%A0+Noum%C3%A9a+du+1+au+2+septembre+2026" in html_a
    html = a.get("/", {"reprendre": "trafic 4G à Nouméa du 1 au 2 septembre 2026"}).content.decode()
    assert 'value="trafic 4G à Nouméa du 1 au 2 septembre 2026"' in html and "Mes dernières recherches" in html
    assert JournalAudit.objects.filter(utilisateur=_visiteur(a)).count() == 2


def test_pas_de_visiteur_sur_l_administration_ni_en_post(client):
    client.get("/admin/")
    client.get("/connexion/")
    client.post("/rapports/requete/", {})
    assert not User.objects.filter(username__startswith="visiteur-").exists()


def test_compte_avec_mot_de_passe_inchange(client):
    admin = User.objects.create_superuser("admin", password="secret-123-Abc")
    client.force_login(admin)
    html = client.get("/").content.decode()
    assert "admin" in html and "Déconnexion" in html and "Session de ce navigateur" not in html
    assert not est_visiteur(admin)


def test_acces_anonyme_desactive(client, settings):
    settings.ACCES_ANONYME = False
    client.get("/")
    assert not User.objects.filter(username__startswith="visiteur-").exists()


def test_activite_prolonge_la_session(client):
    client.get("/")
    user = _visiteur(client)
    User.objects.filter(pk=user.pk).update(last_login=timezone.now() - timedelta(days=30))
    client.get("/")
    user.refresh_from_db()
    assert timezone.now() - user.last_login < timedelta(minutes=1)


def test_purger_visiteurs(client, capsys):
    client.get("/")
    ancien = _visiteur(client)
    User.objects.filter(pk=ancien.pk).update(last_login=timezone.now() - timedelta(days=500))
    Client().get("/")  # visiteur récent
    admin = User.objects.create_superuser("admin")
    User.objects.filter(pk=admin.pk).update(last_login=timezone.now() - timedelta(days=900))
    call_command("purger_visiteurs")
    assert "1 visiteur(s)" in capsys.readouterr().out
    assert not User.objects.filter(pk=ancien.pk).exists()
    assert User.objects.filter(username__startswith="visiteur-").count() == 1
    assert User.objects.filter(pk=admin.pk).exists()
