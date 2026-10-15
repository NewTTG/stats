"""Administration : espace séparé de l'application (marque, tableau de bord, sections rangées par
usage), comptes visiteur filtrés, page de connexion comme entrée de l'administration."""

from datetime import timedelta

import pytest
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.comptes.models import JournalAudit
from apps.comptes.visiteurs import creer_visiteur
from apps.evenements.models import Creneau, Evenement, ReglagesAnomalies
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
    # menu latéral : un lien par espace, présent aussi sur le tableau de bord ; pas d'onglets sur l'accueil
    assert 'id="nav-sidebar"' in html
    reponse = client_admin.get("/admin/")
    espaces = [e["libelle"] for e in reponse.context["navigation"]]
    assert espaces == ["Vue d’ensemble", "Suivi des demandes", "Graphiques et rapports", "Référentiel", "Réseau",
                       "Comptes et accès", "Système"]
    assert reponse.context["espace"]["cle"] == "accueil" and reponse.context["onglets"] == []
    assert 'class="admin-onglets"' not in html
    # thème : choix explicite dans le menu du compte, plus de bouton de Django qui tourne en boucle
    assert 'data-theme-choix' in html and 'class="theme-toggle"' not in html
    # raccourcis et points à traiter ; un événement sans période mémorisée n'est plus « à compléter »
    # (la période se choisit à l'affichage)
    for titre in ["Accès rapides", "À traiter", "Créer un événement", "KPI : noms et seuils", "Périmètres d&#x27;accès",
                  "Comptes utilisateurs", "Journal d&#x27;audit"]:
        assert titre in html
    assert "Événements sans créneau" not in html and "admin-pastille" not in html
    assert f'href="{reverse("admin:evenements_evenement_add")}"' in html
    assert f'href="{reverse("admin:kpi_seuilkpi_changelist")}"' in html
    assert f'href="{reverse("admin:auth_user_changelist")}"' in html
    # référentiel : volumes et accès au rechargement
    assert "Référentiel réseau" in html and "Recharger le référentiel" in html
    # rappel des opérations en ligne de commande : réservé à l'administration
    assert "python manage.py import_referentiel" in html
    assert "import_referentiel" not in _html(client_admin.get("/"))


def test_ordre_des_sections(client_admin):
    reponse = client_admin.get("/admin/")
    sections = [(a["app_label"], a["name"]) for a in reponse.context["app_list"]]
    assert sections == [
        ("evenements", "Événements"), ("kpi", "KPI"), ("comptes", "Comptes et périmètres"),
        ("auth", "Authentification et autorisation"), ("referentiel", "Référentiel réseau"), ("rapports", "Rapports"), ("django_q", "Tâches de fond"),
    ]
    modeles = {a["app_label"]: [m["object_name"] for m in a["models"]] for a in reponse.context["app_list"]}
    assert modeles["evenements"] == ["Evenement", "ReglagesAnomalies"]
    assert modeles["kpi"] == ["ModeleRapport", "Graphique", "SeuilKpi", "ColonneKpi"]
    assert modeles["comptes"] == ["Perimetre", "DemandeSuivie", "JournalAudit"]
    assert modeles["auth"] == ["User", "Group"]
    assert modeles["referentiel"] == ["Site", "Secteur", "Cellule", "ImportReferentiel"]
    assert modeles["rapports"] == ["RapportPlanifie", "Rapport"]
    assert modeles["django_q"][0] == "Schedule"
    noms = {m["object_name"]: m["name"] for a in reponse.context["app_list"] for m in a["models"]}
    assert noms["Perimetre"] == "Périmètres d'accès" and noms["Rapport"] == "Rapports générés"
    # même ordre dans les droits du menu des autres pages
    reponse = client_admin.get(reverse("admin:evenements_evenement_changelist"))
    assert [a["app_label"] for a in reponse.context["available_apps"]][:3] == ["evenements", "kpi", "comptes"]
    # la page d'une application mène à l'espace qui la regroupe (première page accessible)
    for app, page in [("auth", "admin:auth_user_changelist"), ("comptes", "admin:auth_user_changelist"),
                      ("kpi", "admin:evenements_evenement_changelist"),
                      ("referentiel", "admin:referentiel_importreferentiel_changelist"),
                      ("rapports", "admin:kpi_modelerapport_changelist"), ("django_q", "admin:processus")]:
        reponse = client_admin.get(reverse("admin:app_list", args=[app]))
        assert (reponse.status_code, reponse["Location"]) == (302, reverse(page)), app


def test_acces_rapides_selon_les_droits(client):
    user = User.objects.create_user("gestionnaire", password="secret-123-Abc", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_seuilkpi"))
    client.force_login(user)
    reponse = client.get("/admin/")
    assert [c["titre"] for c in reponse.context["acces_rapides"]] == ["KPI : noms et seuils"]
    assert [a["app_label"] for a in reponse.context["app_list"]] == ["kpi"]
    # menu et points à traiter limités aux droits ; pas de référentiel sans droit de lecture
    assert [(e["libelle"], [o["libelle"] for o in e["onglets"]]) for e in reponse.context["navigation"]] == [
        ("Vue d’ensemble", ["Vue d’ensemble"]), ("Référentiel", ["KPI : noms et seuils"])]
    assert reponse.context["a_traiter"] == [] and reponse.context["referentiel"] is None
    assert "Créer un événement" not in reponse.content.decode()
    # un espace réduit à une page : pas de barre d'onglets
    reponse = client.get(reverse("admin:kpi_seuilkpi_changelist"))
    assert reponse.context["onglets"] == [] and reponse.context["espace"]["cle"] == "referentiel"
    # sans droit sur les réglages de détection : pas de carte
    assert reponse.context["detection"] is None


def test_import_du_referentiel_sans_ajout_manuel(client_admin):
    html = _html(client_admin.get("/admin/"))
    assert reverse("admin:referentiel_importreferentiel_add") not in html
    assert client_admin.get(reverse("admin:referentiel_importreferentiel_add")).status_code == 403


# ------------------------------------------------------------------ espaces, onglets et fenêtres

def test_onglets_de_l_espace(client_admin):
    reponse = client_admin.get(reverse("admin:auth_group_changelist"))
    html = _html(reponse)
    assert reponse.context["espace"]["libelle"] == "Comptes et accès"
    assert [o["libelle"] for o in reponse.context["onglets"]] == [
        "Utilisateurs", "Groupes", "Périmètres d’accès", "Journal d’audit"]
    assert reponse.context["onglet"]["libelle"] == "Groupes"
    assert 'class="admin-onglets"' in html and f'<a href="{reverse("admin:auth_group_changelist")}" aria-current="page">' in html
    # fil d'Ariane : espace › onglet
    assert "Comptes et accès</a> › Groupes</div>" in html
    # liste dont les fiches s'ouvrent en fenêtre
    assert ' ouverture-modale"' in html
    # rapports générés et planifiés : un seul espace ; système : processus avec les tâches de fond
    reponse = client_admin.get(reverse("admin:rapports_rapportplanifie_changelist"))
    assert [o["libelle"] for o in reponse.context["onglets"]] == [
        "Rapports et accueil", "Graphiques", "Rapports générés", "Enregistrés et planifiés"]
    reponse = client_admin.get(reverse("admin:processus"))
    assert reponse.context["espace"]["libelle"] == "Système"
    assert [o["libelle"] for o in reponse.context["onglets"]][:2] == ["Processus du serveur", "Planifications"]
    # fiche : espace et onglet toujours actifs
    groupe = Group.objects.create(name="Exploitation")
    reponse = client_admin.get(reverse("admin:auth_group_change", args=[groupe.pk]))
    assert reponse.context["onglet"]["libelle"] == "Groupes"
    assert "Groupes</a> › Exploitation</div>" in _html(reponse)


def test_fiches_en_fenetre(client_admin):
    ajout = reverse("admin:auth_group_add")
    # page affichée seule, encadrable par l'administration elle-même
    reponse = client_admin.get(ajout, {"_modale": 1})
    html = _html(reponse)
    assert '<body class="modale ' in html and 'id="nav-sidebar"' not in html and 'id="header"' not in html
    assert reponse["X-Frame-Options"] == "SAMEORIGIN"
    assert client_admin.get(ajout)["X-Frame-Options"] == "DENY"
    # enregistrement : fin de fenêtre (la liste se recharge)
    reponse = client_admin.post(f"{ajout}?_modale=1", {"name": "Exploitation", "_save": "1"})
    assert reponse.status_code == 200 and 'data-modale-action="enregistre"' in reponse.content.decode()
    groupe = Group.objects.get(name="Exploitation")
    # « Enregistrer et continuer » : reste dans la fenêtre
    fiche = reverse("admin:auth_group_change", args=[groupe.pk])
    reponse = client_admin.post(f"{fiche}?_modale=1", {"name": "Exploitation réseau", "_continue": "1"})
    assert reponse.status_code == 302 and "_modale=1" in reponse["Location"]
    # sans fenêtre : comportement de Django inchangé
    reponse = client_admin.post(fiche, {"name": "Exploitation", "_save": "1"})
    assert reponse["Location"] == reverse("admin:auth_group_changelist")
    # suppression confirmée dans la fenêtre
    suppression = reverse("admin:auth_group_delete", args=[groupe.pk])
    assert '<body class="modale ' in _html(client_admin.get(suppression, {"_modale": 1}))
    reponse = client_admin.post(f"{suppression}?_modale=1", {"post": "yes"})
    assert 'data-modale-action="supprime"' in reponse.content.decode() and not Group.objects.exists()


def test_fiches_en_pleine_page(client_admin):
    # événements (page de l'application) et suivi des demandes (détail du parcours) : pas de fenêtre
    for liste in ["admin:evenements_evenement_changelist", "admin:comptes_demandesuivie_changelist"]:
        reponse = client_admin.get(reverse(liste))
        assert reponse.context["ouverture_modale"] is False and " ouverture-modale" not in _html(reponse)


def test_reglages_de_detection_dans_l_onglet_kpi(client_admin):
    kpi = reverse("admin:kpi_seuilkpi_changelist")
    # plus de liste d'une seule ligne : l'onglet KPI la remplace
    assert client_admin.get(reverse("admin:evenements_reglagesanomalies_changelist"))["Location"] == kpi
    reponse = client_admin.get(kpi)
    html = _html(reponse)
    reglages = ReglagesAnomalies.courant()
    fiche = reverse("admin:evenements_reglagesanomalies_change", args=[reglages.pk])
    assert "Détection d’anomalies" in html and f'href="{fiche}" data-modale' in html
    assert "90 %" in html and "10 Mbps" in html
    assert "evenements.ReglagesAnomalies" not in str(reponse.context["navigation"])
    # modifiés en fenêtre : la fenêtre se ferme ; en pleine page : retour à l'onglet KPI
    donnees = {"ecart_sigma": "2.5", "ecart_pct": "20", "saturation_prb": "85", "saturation_debit": "10", "_save": "1"}
    reponse = client_admin.post(f"{fiche}?_modale=1", donnees)
    assert 'data-modale-action="enregistre"' in reponse.content.decode()
    assert ReglagesAnomalies.courant().saturation_prb == 85
    assert client_admin.post(fiche, donnees)["Location"] == kpi
    assert "85 %" in _html(client_admin.get(kpi))


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
