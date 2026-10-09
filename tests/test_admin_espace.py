"""Administration : espace séparé de l'application (marque, tableau de bord, sections rangées par
usage), comptes visiteur filtrés, page de connexion comme entrée de l'administration."""

from datetime import timedelta

import pytest
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.comptes.models import JournalAudit
from apps.comptes.visiteurs import creer_visiteur
from apps.evenements.models import Creneau, Evenement
from config.admin import AdminStats

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


def _html(reponse):
    assert reponse.status_code == 200
    return reponse.content.decode()


def _evenement(nom, avec_creneau):
    evenement = Evenement.objects.create(nom=nom)
    if avec_creneau:
        debut = timezone.now() - timedelta(days=2)
        Creneau.objects.create(evenement=evenement, debut=debut, fin=debut + timedelta(hours=3))
    return evenement


# ------------------------------------------------------------------ site, marque, tableau de bord

def test_site_du_projet():
    assert isinstance(admin.site, AdminStats)
    assert admin.site.site_header == "Stats réseau · Administration"
    assert admin.site.index_title == "Tableau de bord"
    # django-q2 renommé, label (et donc migrations) inchangé
    config_q = apps.get_app_config("django_q")
    assert config_q.verbose_name == "Tâches de fond" and config_q.name == "django_q"


def test_aucune_migration_manquante():
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)  # SystemExit si une migration manque


def test_tableau_de_bord(client_admin):
    _evenement("Foire de Bourail", avec_creneau=False)
    _evenement("Fête de la musique", avec_creneau=True)
    html = _html(client_admin.get("/admin/"))
    assert "Stats réseau · Administration" in html and "Tableau de bord" in html
    assert 'class="marque-admin-logo"' in html
    # lien de retour vers l'application, à la place de « Voir le site »
    assert '<a class="retour-statistiques" href="/">← Retour aux statistiques</a>' in html
    assert "Voir le site" not in html
    # accès rapides, avant la liste des sections
    assert html.index("Accès rapides") < html.index('class="app-evenements module')
    for titre in ["Créer un événement", "Événements à compléter", "Seuils KPI", "Périmètres d&#x27;accès",
                  "Comptes utilisateurs", "Journal d&#x27;audit"]:
        assert titre in html
    assert f'href="{reverse("admin:evenements_evenement_add")}"' in html
    assert f'href="{reverse("admin:evenements_evenement_changelist")}?creneaux=sans"' in html
    assert f'href="{reverse("admin:kpi_seuilkpi_changelist")}"' in html
    assert f'href="{reverse("admin:auth_user_changelist")}"' in html
    assert 'class="carte-admin-compteur" title="1 à compléter">1</span>' in html
    # rappel des opérations en ligne de commande : réservé à l'administration
    assert "python manage.py import_referentiel" in html
    assert "import_referentiel" not in _html(client_admin.get("/"))


def test_ordre_des_sections(client_admin):
    reponse = client_admin.get("/admin/")
    sections = [(a["app_label"], a["name"]) for a in reponse.context["app_list"]]
    assert sections == [
        ("evenements", "Événements"), ("kpi", "KPI"), ("comptes", "Comptes et périmètres"),
        ("referentiel", "Référentiel réseau"), ("rapports", "Rapports"), ("django_q", "Tâches de fond"),
    ]
    modeles = {a["app_label"]: [m["object_name"] for m in a["models"]] for a in reponse.context["app_list"]}
    assert modeles["evenements"] == ["Evenement"]
    assert modeles["kpi"] == ["SeuilKpi", "ReglagesAnomalies"]
    assert modeles["comptes"] == ["User", "Group", "Perimetre", "JournalAudit"]
    assert modeles["referentiel"] == ["Site", "Secteur", "Cellule", "ImportReferentiel"]
    assert modeles["rapports"] == ["RapportPlanifie", "Rapport"]
    assert modeles["django_q"][0] == "Schedule"
    noms = {m["object_name"]: m["name"] for a in reponse.context["app_list"] for m in a["models"]}
    assert noms["Perimetre"] == "Périmètres d'accès" and noms["Rapport"] == "Rapports générés"
    # même ordre dans le menu latéral des autres pages ; la page d'une application reste complète
    reponse = client_admin.get(reverse("admin:evenements_evenement_changelist"))
    assert [a["app_label"] for a in reponse.context["available_apps"]][:3] == ["evenements", "kpi", "comptes"]
    reponse = client_admin.get(reverse("admin:app_list", args=["auth"]))
    assert [m["object_name"] for m in reponse.context["app_list"][0]["models"]] == ["User", "Group"]


def test_acces_rapides_selon_les_droits(client):
    user = User.objects.create_user("gestionnaire", password="secret-123-Abc", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_seuilkpi"))
    client.force_login(user)
    reponse = client.get("/admin/")
    assert [c["titre"] for c in reponse.context["acces_rapides"]] == ["Seuils KPI"]
    assert [a["app_label"] for a in reponse.context["app_list"]] == ["kpi"]
    assert "Créer un événement" not in reponse.content.decode()


def test_import_du_referentiel_sans_ajout_manuel(client_admin):
    html = _html(client_admin.get("/admin/"))
    assert reverse("admin:referentiel_importreferentiel_add") not in html
    assert client_admin.get(reverse("admin:referentiel_importreferentiel_add")).status_code == 403


# ------------------------------------------------------------------ comptes visiteur

@pytest.fixture
def comptes():
    visiteurs = {creer_visiteur().username, creer_visiteur().username}
    bob = User.objects.create_user("bob", password="secret-123-Abc")
    # préfixe de visiteur mais mot de passe utilisable : un vrai compte
    imposteur = User.objects.create_user("visiteur-compte", password="secret-123-Abc")
    return visiteurs, {"admin", bob.username, imposteur.username}


def _noms(reponse):
    assert reponse.status_code == 200
    return {u.username for u in reponse.context["cl"].result_list}


def test_visiteurs_masques_par_defaut(client_admin, comptes):
    visiteurs, avec_mot_de_passe = comptes
    url = reverse("admin:auth_user_changelist")
    reponse = client_admin.get(url)
    assert _noms(reponse) == avec_mot_de_passe
    html = reponse.content.decode()
    assert "Type de compte" in html or "type de compte" in html
    assert "Comptes (avec mot de passe)" in html and "Visiteurs (sans compte)" in html and "Tous" in html
    filtre = next(f for f in reponse.context["cl"].filter_specs if f.parameter_name == "compte")
    choix = list(filtre.choices(reponse.context["cl"]))
    assert [c["display"] for c in choix if c["selected"]] == ["Comptes (avec mot de passe)"]
    assert "visiteur" in reponse.context["cl"].list_display

    assert _noms(client_admin.get(url, {"compte": "visiteurs"})) == visiteurs
    assert _noms(client_admin.get(url, {"compte": "tous"})) == visiteurs | avec_mot_de_passe
    # recherche standard, toujours dans le type choisi
    assert _noms(client_admin.get(url, {"q": "visiteur"})) == {"visiteur-compte"}
    assert len(_noms(client_admin.get(url, {"q": "visiteur", "compte": "tous"}))) == 3


def test_journal_d_audit_lisible(client_admin):
    bob = User.objects.create_user("bob", password="secret-123-Abc")
    JournalAudit.objects.create(utilisateur=bob, action="recherche_kpi", requete={"q": "drop 3G à Nouméa hier"})
    JournalAudit.objects.create(utilisateur=bob, action="export_excel", requete={})
    JournalAudit.objects.create(utilisateur=creer_visiteur(), action="recherche_kpi", requete={"q": "trafic Koné"})
    url = reverse("admin:comptes_journalaudit_changelist")
    reponse = client_admin.get(url)
    html = _html(reponse)
    assert reponse.context["cl"].date_hierarchy == "date"
    assert "« drop 3G à Nouméa hier »" in html and "Export Excel" in html
    assert reverse("admin:comptes_journalaudit_add") not in html
    assert len(client_admin.get(url, {"q": "bob"}).context["cl"].result_list) == 2
    assert len(client_admin.get(url, {"action": "recherche_kpi"}).context["cl"].result_list) == 2


def test_evenements_a_completer(client_admin):
    _evenement("Foire de Bourail", avec_creneau=False)
    _evenement("Fête de la musique", avec_creneau=True)
    url = reverse("admin:evenements_evenement_changelist")

    def noms(parametres):
        return {e.nom for e in client_admin.get(url, parametres).context["cl"].result_list}

    assert noms({"creneaux": "sans"}) == {"Foire de Bourail"}
    assert noms({"creneaux": "avec"}) == {"Fête de la musique"}
    assert len(noms({})) == 2


# ------------------------------------------------------------------ entrée de l'administration

def test_page_de_connexion(client):
    html = _html(client.get("/connexion/", {"next": "/admin/"}))
    assert "Accès administrateur" in html and "sans compte" in html
    assert f'<a href="{reverse("kpi:requete")}">← Retour aux statistiques</a>' in html
    assert 'id="id_username"' in html and 'id="id_password"' in html
    assert '<input type="hidden" name="next" value="/admin/">' in html


def test_page_de_connexion_sans_acces_anonyme(client, settings):
    settings.ACCES_ANONYME = False
    html = _html(client.get("/connexion/"))
    assert "Accès administrateur" not in html and "Retour aux statistiques" not in html
    assert "<h1" in html and "Connexion</h1>" in html


def test_anonyme_et_visiteur_renvoyes_vers_la_connexion(client):
    reponse = client.get("/admin/")
    assert reponse.status_code == 302 and reponse.url.startswith(reverse("admin:login"))
    reponse = client.get("/admin/", follow=True)
    assert reponse.redirect_chain[-1][0] == "/connexion/?next=%2Fadmin%2F"
    assert "Accès administrateur" in reponse.content.decode()
    client.get("/")  # session visiteur
    reponse = client.get("/admin/", follow=True)
    html = _html(reponse)
    assert reponse.redirect_chain[-1][0].startswith("/connexion/") and "Accès administrateur" in html
    assert "n'a pas accès à l'administration" not in html


def test_compte_sans_administration(client):
    client.force_login(User.objects.create_user("bob", password="secret-123-Abc"))
    reponse = client.get("/admin/")
    assert reponse.status_code == 302
    html = _html(client.get("/admin/", follow=True))
    assert "Le compte « bob » n'a pas accès à l'administration" in html


def test_redirection_apres_connexion(client, settings):
    User.objects.create_user("chef", password="secret-123-Abc", is_staff=True)
    User.objects.create_user("bob", password="secret-123-Abc")
    identifiants = {"username": "chef", "password": "secret-123-Abc"}
    # administrateur : tableau de bord, sauf « next » explicite
    assert client.post("/connexion/", identifiants).url == reverse("admin:index")
    assert client.post("/connexion/", {**identifiants, "next": "/evenements/"}).url == "/evenements/"
    # autre compte : la recherche
    assert client.post("/connexion/", {"username": "bob", "password": "secret-123-Abc"}).url == reverse("kpi:requete")
    # connexion obligatoire (pas d'accès sans compte) : tout le monde arrive sur la recherche
    settings.ACCES_ANONYME = False
    assert client.post("/connexion/", identifiants).url == reverse("kpi:requete")
    # formulaire de l'admin envoyé directement (POST) : toujours accepté
    reponse = client.post(reverse("admin:login"), {**identifiants, "next": "/admin/"})
    assert reponse.status_code == 302 and reponse.url == "/admin/"


def test_deconnexion_depuis_l_administration(client_admin):
    reponse = client_admin.post(reverse("admin:logout"))
    assert reponse.status_code == 302 and reponse.url == reverse("kpi:requete")
