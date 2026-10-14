"""Création / modification d'un événement dans l'application (/evenements/nouveau/, /<pk>/modifier/) :
zone couverte sur carte, KPI, suppression, données de la carte, azimut des secteurs ; l'administration
renvoie vers ces pages. La période se choisit sur la page de l'événement (tests/test_evenement_periode.py)."""

import pandas as pd
import pytest
from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse

from apps.comptes.models import Perimetre
from apps.evenements.models import Evenement
from apps.kpi.recherche.lieux import ResolveurLieux
from apps.referentiel.importation import importer
from apps.referentiel.models import Secteur

from .test_service import referentiel  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db
URL_AJOUT = "evenements:nouveau"


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


def _donnees(**modifs):
    donnees = {
        "nom": "Foire de Bourail", "type": "Foire", "description": "",
        "sites": "AAA100", "secteurs": "BBB2002", "cellules": "BBBe1",
        "semaines_reference": "4", "kpis_choisis": "false",
        "_enregistrer": "1",
    }
    donnees.update(modifs)
    return donnees


def test_page_d_edition(client_admin, referentiel):  # noqa: F811
    html = client_admin.get(reverse(URL_AJOUT)).content.decode()
    assert 'class="workspace' in html  # gabarit de l'application, pas de l'administration
    assert 'id="ev-zone"' in html and reverse("evenements:reseau") in html
    assert "vendor/leaflet-1.9.4/leaflet.js" in html
    # Ni créneaux (choisis à l'affichage), ni saisie libre des cellules.
    assert 'type="datetime-local"' not in html and "<textarea name=\"cellules\"" not in html
    assert 'type="hidden" name="cellules"' in html


def test_creation(client_admin, referentiel):  # noqa: F811
    reponse = client_admin.post(reverse(URL_AJOUT), _donnees())
    assert reponse.status_code == 302, reponse.content.decode()[:2000]
    e = Evenement.objects.get(nom="Foire de Bourail")
    assert reponse["Location"] == reverse("evenements:detail", args=[e.pk])
    assert (e.sites, e.secteurs, e.cellules, e.kpis) == (["AAA100"], ["BBB2002"], ["BBBe1"], [])
    assert e.cree_par.username == "admin"
    assert not e.creneaux.exists()
    assert e.noms_cellules("LTE") == ["AAAe1", "AAAe2", "BBBe1", "BBBe2"]


def test_kpi_choisis_et_continuer(client_admin, referentiel):  # noqa: F811
    donnees = _donnees(kpis_choisis="true", kpis=["lte_rrc_setup_sr", "lte_erab_drop"], _continuer="1")
    del donnees["_enregistrer"]
    reponse = client_admin.post(reverse(URL_AJOUT), donnees)
    e = Evenement.objects.get(nom="Foire de Bourail")
    url = reverse("evenements:modifier", args=[e.pk])
    assert reponse.status_code == 302 and reponse["Location"] == url
    assert e.kpis == ["lte_rrc_setup_sr", "lte_erab_drop"]
    # Retour aux KPI principaux : la liste enregistrée est vidée.
    client_admin.post(url, _donnees(kpis=["lte_rrc_setup_sr"]))
    e.refresh_from_db()
    assert e.kpis == []


def test_erreurs(client_admin, referentiel):  # noqa: F811
    reponse = client_admin.post(reverse(URL_AJOUT), _donnees(
        sites="", secteurs="", cellules="", kpis_choisis="true"))
    assert reponse.status_code == 200
    html = reponse.content.decode()
    assert html.count("Choisissez au moins un site, un secteur ou une cellule.") == 1
    assert "Cochez au moins un KPI" in html
    assert not Evenement.objects.exists()


def test_donnees_de_la_carte(client_admin, referentiel):  # noqa: F811
    Secteur.objects.filter(code="AAA1001").update(azimut=40)
    donnees = client_admin.get(reverse("evenements:reseau")).json()
    aaa = next(s for s in donnees["sites"] if s["code"] == "AAA100")
    assert aaa["nom"] == "SITE_AAA" and aaa["commune"] == "NOUMEA"
    assert [(s["code"], s["azimut"], s["cellules"]) for s in aaa["secteurs"]] == [
        ("AAA1001", 40, [["AAAe1", "LTE"]]), ("AAA1002", None, [["AAAe2", "LTE"]])]
    assert donnees["libres"] == [["ORPHe1", "LTE"]]


def test_suppression(client_admin, referentiel):  # noqa: F811
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    assert client_admin.get(reverse("evenements:supprimer", args=[e.pk])).status_code == 405
    reponse = client_admin.post(reverse("evenements:supprimer", args=[e.pk]))
    assert reponse.status_code == 302 and reponse["Location"] == reverse("evenements:liste")
    assert not Evenement.objects.exists()


def test_liens_de_l_application(client_admin, referentiel):  # noqa: F811
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    liste = client_admin.get(reverse("evenements:liste")).content.decode()
    assert reverse("evenements:nouveau") in liste and reverse("evenements:modifier", args=[e.pk]) in liste
    assert "/admin/" not in liste.split("<main", 1)[1]
    assert reverse("evenements:modifier", args=[e.pk]) in client_admin.get(
        reverse("evenements:detail", args=[e.pk])).content.decode()
    # L'administration renvoie vers les pages de l'application.
    assert client_admin.get(reverse("admin:evenements_evenement_add"))["Location"] == reverse("evenements:nouveau")
    assert client_admin.get(reverse("admin:evenements_evenement_change", args=[e.pk]))["Location"] == \
        reverse("evenements:modifier", args=[e.pk])


def test_droits(client, referentiel):  # noqa: F811
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    lecteur = User.objects.create_user("lecteur", password="x", is_staff=True)
    lecteur.user_permissions.add(Permission.objects.get(codename="view_evenement"))
    lecteur.groups.add(Group.objects.create(name="Analyste"))
    client.force_login(lecteur)
    # Création et modification ouvertes à tous ; suppression : droit Django ou créateur.
    for url in [reverse("evenements:reseau"), reverse("evenements:nouveau"),
                reverse("evenements:modifier", args=[e.pk])]:
        assert client.get(url).status_code == 200
    assert client.put(reverse("evenements:modifier", args=[e.pk])).status_code == 405
    assert client.post(reverse("evenements:supprimer", args=[e.pk])).status_code == 403
    html = client.get(reverse("evenements:liste")).content.decode()
    assert reverse("evenements:nouveau") in html and reverse("evenements:modifier", args=[e.pk]) in html
    assert reverse("evenements:modifier", args=[e.pk]) in client.get(
        reverse("evenements:detail", args=[e.pk])).content.decode()
    assert "Supprimer l'événement" not in client.get(reverse("evenements:modifier", args=[e.pk])).content.decode()
    # Consultation seule dans l'administration : page standard de Django, sans redirection.
    reponse = client.get(reverse("admin:evenements_evenement_change", args=[e.pk]))
    assert reponse.status_code == 200 and "Concert" in reponse.content.decode()


# ------------------------------------------------------------------ public / privé

@pytest.fixture
def analystes():
    groupe = Group.objects.create(name="Analyste")  # tout le réseau, sans droit evenements.*
    comptes = [User.objects.create_user(nom) for nom in ("alice", "bruno")]
    for u in comptes:
        u.groups.add(groupe)
    return comptes


def test_public_par_defaut(client, referentiel, analystes):  # noqa: F811
    alice, bruno = analystes
    client.force_login(alice)
    html = client.get(reverse(URL_AJOUT)).content.decode()
    assert 'name="public" value="public" checked' in html and 'name="public" value="prive">' in html
    assert client.post(reverse(URL_AJOUT), _donnees()).status_code == 302
    e = Evenement.objects.get()
    assert e.public and e.cree_par == alice
    # Un autre utilisateur le voit et le modifie, sans pouvoir le rendre privé.
    client.force_login(bruno)
    url = reverse("evenements:modifier", args=[e.pk])
    assert 'name="public"' not in client.get(url).content.decode()
    assert client.post(url, _donnees(type="Concert", public="prive")).status_code == 302
    e.refresh_from_db()
    assert (e.type, e.public, e.cree_par) == ("Concert", True, alice)
    assert client.post(reverse("evenements:supprimer", args=[e.pk])).status_code == 403
    # Le créateur, lui, le rend privé puis le supprime.
    client.force_login(alice)
    assert client.post(url, _donnees(public="prive")).status_code == 302
    e.refresh_from_db()
    assert not e.public
    assert client.post(reverse("evenements:supprimer", args=[e.pk])).status_code == 302
    assert not Evenement.objects.exists()


def test_evenement_prive(client, referentiel, analystes):  # noqa: F811
    alice, bruno = analystes
    client.force_login(alice)
    client.post(reverse(URL_AJOUT), _donnees(public="prive"))
    e = Evenement.objects.get()
    assert not e.public
    assert "Privé" in client.get(reverse("evenements:liste")).content.decode()
    assert "Privé" in client.get(reverse("evenements:detail", args=[e.pk])).content.decode()
    assert 'name="public" value="prive" checked' in client.get(
        reverse("evenements:modifier", args=[e.pk])).content.decode()
    # Invisible des autres, administrateurs compris, et de leur recherche.
    admin = User.objects.create_superuser("admin")
    for autre in (bruno, admin):
        client.force_login(autre)
        assert "Foire de Bourail" not in client.get(reverse("evenements:liste")).content.decode()
        for nom in ("detail", "modifier", "supprimer"):
            methode = client.post if nom == "supprimer" else client.get
            assert methode(reverse(f"evenements:{nom}", args=[e.pk])).status_code == 404
        assert not ResolveurLieux(autre).evenements.entrees
    assert ResolveurLieux(alice).evenements.entrees


def test_perimetre_restreint(client, referentiel):  # noqa: F811
    """Sans tout le réseau : carte limitée au périmètre ; ses propres événements toujours visibles."""
    lecteur = User.objects.create_user("lec")
    Perimetre.objects.create(nom="Paita", communes=["PAITA"]).utilisateurs.add(lecteur)
    client.force_login(lecteur)
    donnees = client.get(reverse("evenements:reseau")).json()
    assert [s["code"] for s in donnees["sites"]] == ["BBB200"] and donnees["libres"] == []
    noumea = Evenement.objects.create(nom="Noumea", sites=["AAA100"])
    client.post(reverse(URL_AJOUT), _donnees(sites="BBB200", secteurs="", cellules="", public="prive"))
    perso = Evenement.objects.get(nom="Foire de Bourail")
    html = client.get(reverse("evenements:liste")).content.decode()
    assert "Foire de Bourail" in html and "Noumea" not in html
    assert client.get(reverse("evenements:modifier", args=[noumea.pk])).status_code == 404
    # Même hors de tout périmètre, on retrouve les siens.
    sans = User.objects.create_user("sans")
    perso.cree_par = sans
    perso.save()
    client.force_login(sans)
    assert "Foire de Bourail" in client.get(reverse("evenements:liste")).content.decode()


# ------------------------------------------------------------------ azimut des secteurs

def test_import_des_azimuts(tmp_path):
    chemin = tmp_path / "ref.xlsx"
    with pd.ExcelWriter(chemin) as w:
        pd.DataFrame({"codeSite": ["AAA100", "ACR584"], "Trigramme": ["AAA", "ACR"], "siteName": ["A", "ACR"],
                      "commune": ["NOUMEA", "PAITA"], "region": ["SUD", "SUD"]}).to_excel(w, sheet_name="Site_File", index=False)
        # ACR584 : secteurs numérotés 4 à 6 dans Cell_File (site déporté), soit 1 à 3 ; 380° = 20°.
        pd.DataFrame({"cells": ["AAA1001", "AAA1002", "ACR5844", "ACR5845"], "codeSite": ["AAA100", "AAA100", "ACR584", "ACR584"],
                      "azimut": [10, 380, 60, 180]}).to_excel(w, sheet_name="Cell_File", index=False)
    exports = tmp_path / "lte.csv"
    exports.write_text('"EutranCell_Id"\n' + "".join(f'"{n}"\n' for n in ["AAAe1", "AAAe2", "AAAe3", "ACRe1", "ACRe2"]))
    importer(chemin, [exports])
    assert dict(Secteur.objects.values_list("code", "azimut")) == {
        "AAA1001": 10, "AAA1002": 20, "AAA1003": None, "ACR5841": 60, "ACR5842": 180}
    # Import sans cellules : secteurs inchangés, azimuts relus.
    Secteur.objects.update(azimut=None)
    importer(chemin)
    assert Secteur.objects.get(code="ACR5841").azimut == 60
