"""Sites mobiles (remorques) et pages Réseau : marqueur, omni, déclaration / modification des sites,
conservation par les rechargements, déploiement d'une remorque dans un événement (position, secteurs,
cellules), analyse et carte selon la disposition déclarée."""

import json
from datetime import datetime

import pandas as pd
import pytest
import sqlalchemy as sa
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.comptes.models import JournalAudit, Perimetre
from apps.evenements import mobiles
from apps.evenements.acces import evenements_visibles
from apps.evenements.analyse import analyser
from apps.evenements.edition import reseau_pour_carte, zone_pour_carte
from apps.evenements.models import Evenement
from apps.referentiel.importation import importer
from apps.referentiel.models import Cellule, Secteur, Site, est_omni
from apps.referentiel.nommage import semble_mobile

from .test_service import analyste, referentiel  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db


@pytest.fixture
def remorque(referentiel):  # noqa: F811
    """REMORQUE_1 (1RM128) : 2 secteurs au référentiel, une cellule 4G et une 3G chacun."""
    site = Site.objects.create(code_site="1RM128", trigramme="1RM", nom="REMORQUE_1", commune="DUMBEA",
                               latitude=-22.14, longitude=166.52, mobile=True)
    for n, az in ((1, 160), (2, 320)):
        sect = Secteur.objects.create(code=f"1RM128{n}", site=site, numero=n, azimut=az)
        Cellule.objects.create(nom=f"1RMe{n}", techno="LTE", secteur=sect)
        Cellule.objects.create(nom=f"1RM128{'AB'[n - 1]}", techno="WCDMA", secteur=sect)
    return site


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


OMNI = {"1RM128": {"lat": -22.2758, "lon": 166.458, "secteurs": [
    {"numero": 1, "azimut": 0, "cellules": [["1RMe1", "LTE"], ["1RMe2", "LTE"], ["1RM128A", "WCDMA"], ["1RMe3", "LTE"]]}]}}


# ------------------------------------------------------------------ référentiel

def test_omni_et_nom_de_remorque():
    assert est_omni(0, 1) and not est_omni(0, 3) and not est_omni(None, 1) and not est_omni(90, 1)
    assert semble_mobile("REMORQUE_1bb") and semble_mobile("MOBILEbb") and not semble_mobile("AUTOMOBILE")


def _xlsx(tmp_path, sites):
    chemin = tmp_path / "ref.xlsx"
    with pd.ExcelWriter(chemin) as w:
        pd.DataFrame(sites).to_excel(w, sheet_name="Site_File", index=False)
        pd.DataFrame({"cells": ["1RM1281"], "codeSite": ["1RM128"], "azimut": [0]}).to_excel(
            w, sheet_name="Cell_File", index=False)
    return chemin


def _exports(tmp_path, lte):
    chemin = tmp_path / "lte.csv"
    chemin.write_text('"EutranCell_Id";"ERBS_Id"\n' + "".join(f'"{n}";"X"\n' for n in lte))
    return [chemin]


def test_import_marque_les_remorques_et_garde_les_sites_declares(tmp_path):
    xlsx = _xlsx(tmp_path, {"codeSite": ["AAA100", "1RM128"], "Trigramme": ["AAA", "1RM"],
                            "siteName": ["ALPHA", "REMORQUE_1bb"], "commune": ["NOUMEA", "DUMBEA"],
                            "region": ["SUD", "SUD"]})
    importer(xlsx, _exports(tmp_path, ["AAAe1", "1RMe1", "ZZZe1"]))
    assert Site.objects.get(code_site="1RM128").mobile and not Site.objects.get(code_site="AAA100").mobile
    # Omni : un seul secteur, azimut 0 dans Cell_File.
    assert Secteur.objects.get(code="1RM1281").azimut == 0

    # Marqueur retiré à la main : conservé au rechargement ; site déclaré dans l'application conservé.
    Site.objects.filter(code_site="1RM128").update(mobile=False)
    manuel = Site.objects.create(code_site="2RM129", trigramme="2RM", nom="REMORQUE_2", commune="NOUMEA",
                                 mobile=True, manuel=True)
    sect = Secteur.objects.create(code="2RM1291", site=manuel, numero=1, azimut=0)
    Cellule.objects.create(nom="2RMe1", techno="LTE", secteur=sect)
    Cellule.objects.filter(nom="ZZZe1").update(secteur=sect)  # rattachée à la main
    imp = importer(xlsx, _exports(tmp_path, ["AAAe1", "1RMe1", "ZZZe1", "2RMe1"]))
    assert not Site.objects.get(code_site="1RM128").mobile
    assert "2RM129" not in imp.suppressions
    assert Cellule.objects.get(nom="ZZZe1").secteur.code == "2RM1291"
    assert Cellule.objects.get(nom="2RMe1").secteur.code == "2RM1291"
    assert Secteur.objects.get(code="2RM1291").azimut == 0
    importer(xlsx)  # sans cellules : azimuts relus, sauf pour les sites déclarés
    assert Secteur.objects.get(code="2RM1291").azimut == 0

    # Présent dans le xlsx : le fichier fait foi.
    xlsx = _xlsx(tmp_path, {"codeSite": ["AAA100", "1RM128", "2RM129"], "Trigramme": ["AAA", "1RM", "2RM"],
                            "siteName": ["ALPHA", "REMORQUE_1bb", "REMORQUE_2"], "commune": ["NOUMEA"] * 3,
                            "region": ["SUD"] * 3})
    imp = importer(xlsx, _exports(tmp_path, ["AAAe1", "1RMe1", "2RMe1"]))
    assert not Site.objects.get(code_site="2RM129").manuel
    assert any("2RM129" in a for a in imp.anomalies)


# ------------------------------------------------------------------ pages Réseau

def test_liste_et_fiche(client_admin, remorque):
    html = client_admin.get(reverse("reseau:liste"), {"filtre": "mobiles"}).content.decode()
    assert "REMORQUE_1" in html and "SITE_AAA" not in html and "Site mobile" in html
    html = client_admin.get(reverse("reseau:liste"), {"recherche": "1RMe2"}).content.decode()
    assert "REMORQUE_1" in html
    html = client_admin.get(reverse("reseau:fiche", args=["1RM128"])).content.decode()
    assert "160°" in html and "1RM128B" in html and "Dans chaque événement" in html
    Secteur.objects.filter(code="1RM1282").delete()
    Secteur.objects.filter(code="1RM1281").update(azimut=0)
    assert "Omni (360°)" in client_admin.get(reverse("reseau:fiche", args=["1RM128"])).content.decode()
    assert 'href="/reseau/"' in client_admin.get(reverse("kpi:requete")).content.decode()  # menu


def _formulaire(**modifs):
    donnees = {
        "code_site": "2rm129", "nom": "REMORQUE_2", "trigramme": "2rm", "commune": "Noumea", "region": "",
        "latitude": "", "longitude": "", "mobile": "on",
        "secteurs-TOTAL_FORMS": "1", "secteurs-INITIAL_FORMS": "0",
        "secteurs-0-numero": "1", "secteurs-0-azimut": "0",
        "cellules-TOTAL_FORMS": "2", "cellules-INITIAL_FORMS": "0",
        "cellules-0-nom": "2RMe1", "cellules-0-techno": "LTE", "cellules-0-secteur": "1", "cellules-0-porteuse": "1",
        "cellules-1-nom": "ORPHe1", "cellules-1-techno": "LTE", "cellules-1-secteur": "1", "cellules-1-porteuse": "1",
    }
    donnees.update(modifs)
    return donnees


def test_declaration_d_un_site(client_admin, referentiel):  # noqa: F811
    assert client_admin.get(reverse("reseau:nouveau")).status_code == 200
    reponse = client_admin.post(reverse("reseau:nouveau"), _formulaire())
    assert reponse.status_code == 302, reponse.content.decode()[:3000]
    site = Site.objects.get(code_site="2RM129")
    assert (site.manuel, site.mobile, site.trigramme, site.commune, site.nb_secteurs) == (True, True, "2RM", "NOUMEA", 1)
    assert Secteur.objects.get(site=site).azimut == 0
    # La cellule non rattachée existante est reprise, pas dupliquée.
    assert Cellule.objects.get(nom="ORPHe1").secteur.code == "2RM1291"
    assert set(Cellule.objects.filter(secteur__site=site).values_list("nom", flat=True)) == {"2RMe1", "ORPHe1"}
    assert JournalAudit.objects.filter(action="declaration_site").exists()


@pytest.mark.parametrize("modifs,message", [
    ({"cellules-1-nom": "AAAe1"}, "déjà rattachée au site"),
    ({"cellules-0-secteur": "2"}, "Secteur 2 non déclaré"),
    ({"code_site": "AAA100"}, "existe déjà"),
    ({"latitude": "-22.2"}, "aucune des deux"),
    ({"secteurs-0-DELETE": "on"}, "au moins un secteur"),
])
def test_declaration_refusee(client_admin, referentiel, modifs, message):  # noqa: F811
    reponse = client_admin.post(reverse("reseau:nouveau"), _formulaire(**modifs))
    assert reponse.status_code == 200
    assert message in reponse.content.decode()
    assert not Site.objects.filter(code_site="2RM129").exists()


def test_modification_d_un_site(client_admin, remorque):
    html = client_admin.get(reverse("reseau:modifier", args=["1RM128"])).content.decode()
    assert 'value="1RMe2"' in html and "disabled" in html  # code non modifiable
    donnees = {
        "nom": "REMORQUE_1", "trigramme": "1RM", "commune": "DUMBEA", "region": "", "latitude": "-22.14",
        "longitude": "166.52",  # « mobile » décoché
        "secteurs-TOTAL_FORMS": "2", "secteurs-INITIAL_FORMS": "2",
        "secteurs-0-numero": "1", "secteurs-0-azimut": "0",
        "secteurs-1-numero": "2", "secteurs-1-azimut": "320", "secteurs-1-DELETE": "on",
        "cellules-TOTAL_FORMS": "5", "cellules-INITIAL_FORMS": "4",
        "cellules-0-nom": "1RMe1", "cellules-0-techno": "LTE", "cellules-0-secteur": "1", "cellules-0-porteuse": "1",
        "cellules-1-nom": "1RMe2", "cellules-1-techno": "LTE", "cellules-1-secteur": "1", "cellules-1-porteuse": "2",
        "cellules-2-nom": "1RM128A", "cellules-2-techno": "WCDMA", "cellules-2-secteur": "1",
        "cellules-2-porteuse": "1", "cellules-2-DELETE": "on",
        "cellules-3-nom": "1RM128B", "cellules-3-techno": "WCDMA", "cellules-3-secteur": "2",
        "cellules-3-porteuse": "1", "cellules-3-DELETE": "on",
        # Ligne ajoutée puis laissée vide : ignorée.
        "cellules-4-nom": "", "cellules-4-techno": "LTE", "cellules-4-secteur": "", "cellules-4-porteuse": "1",
    }
    reponse = client_admin.post(reverse("reseau:modifier", args=["1RM128"]), donnees)
    assert reponse.status_code == 302, reponse.content.decode()[:3000]
    site = Site.objects.get(code_site="1RM128")
    assert not site.mobile and not site.manuel
    assert list(site.secteurs.values_list("code", "azimut")) == [("1RM1281", 0)]
    assert Cellule.objects.get(nom="1RMe2").porteuse == 2
    # Cellules 3G retirées : connues, non rattachées.
    assert set(Cellule.objects.filter(nom__in=["1RM128A", "1RM128B"]).values_list("secteur", flat=True)) == {None}


def test_suppression_reservee_aux_sites_declares(client_admin, remorque):
    assert client_admin.post(reverse("reseau:supprimer", args=["1RM128"])).status_code == 403
    Site.objects.filter(code_site="1RM128").update(manuel=True)
    assert client_admin.post(reverse("reseau:supprimer", args=["1RM128"])).status_code == 302
    assert not Site.objects.filter(code_site="1RM128").exists()
    assert Cellule.objects.filter(nom="1RMe1", secteur__isnull=True).exists()


def test_droits_des_pages_reseau(client, remorque):
    lecteur = User.objects.create_user("lecteur")
    Perimetre.objects.create(nom="Paita", communes=["PAITA"]).utilisateurs.add(lecteur)
    client.force_login(lecteur)
    assert client.get(reverse("reseau:liste")).status_code == 403
    assert 'href="/reseau/"' not in client.get(reverse("evenements:liste")).content.decode()
    lecteur.user_permissions.add(Permission.objects.get(codename="add_evenement"))
    assert client.get(reverse("reseau:liste")).status_code == 200
    assert client.get(reverse("reseau:modifier", args=["1RM128"])).status_code == 403
    lecteur.user_permissions.add(Permission.objects.get(codename="change_site"))
    assert client.get(reverse("reseau:modifier", args=["1RM128"])).status_code == 200


# ------------------------------------------------------------------ déploiement dans un événement

def test_normalisation_des_deploiements(remorque):
    dep = mobiles.normaliser(json.dumps({"1RM128": {"lat": "-22,5", "lon": 166.4, "secteurs": [
        {"numero": 2, "azimut": "", "cellules": [["1RMe2", "LTE"]]},
        {"numero": 1, "azimut": 0, "cellules": [[" 1RMe1 ", "LTE"], ["1RM128A", "WCDMA"]]}]}}))
    assert dep == {"1RM128": {"lat": -22.5, "lon": 166.4, "secteurs": [
        {"numero": 1, "azimut": 0, "cellules": [["1RMe1", "LTE"], ["1RM128A", "WCDMA"]]},
        {"numero": 2, "azimut": None, "cellules": [["1RMe2", "LTE"]]}]}}
    assert mobiles.normaliser("") == {}


@pytest.mark.parametrize("dep,message", [
    ({"AAA100": OMNI["1RM128"]}, "n'est pas un site mobile"),
    ({"1RM128": {**OMNI["1RM128"], "lat": None}}, "aucune des deux"),
    ({"1RM128": {**OMNI["1RM128"], "lat": 120}}, "latitude"),
    ({"1RM128": {"secteurs": [{"numero": 1, "azimut": 400, "cellules": [["1RMe1", "LTE"]]}]}}, "azimut"),
    ({"1RM128": {"secteurs": [{"numero": 1, "cellules": [["1RMe1", "LTE"]]},
                              {"numero": 1, "cellules": [["1RMe2", "LTE"]]}]}}, "deux fois"),
    ({"1RM128": {"secteurs": [{"numero": 1, "cellules": [["1RMe1", "LTE"]]},
                              {"numero": 2, "cellules": [["1RMe1", "LTE"]]}]}}, "deux secteurs"),
    ({"1RM128": {"secteurs": [{"numero": 1, "cellules": []}]}}, "au moins une cellule"),
    ({"1RM128": {"secteurs": [{"numero": 1, "cellules": [["1RMe1", "GSM"]]}]}}, "cellule invalide"),
    ("{pas du json", "illisibles"),
])
def test_deploiements_refuses(remorque, dep, message):
    with pytest.raises(ValidationError) as e:
        mobiles.normaliser(dep if isinstance(dep, str) else json.dumps(dep))
    assert any(message in m for m in e.value.messages), e.value.messages


def test_carte_de_selection_sans_position_pour_les_remorques(remorque):
    sites = {s["code"]: s for s in reseau_pour_carte()["sites"]}
    assert sites["1RM128"]["mobile"] and sites["1RM128"]["lat"] is None
    assert [c for sec in sites["1RM128"]["secteurs"] for c in sec["cellules"]][0] == ["1RMe1", "LTE"]
    assert not sites["AAA100"]["mobile"] and sites["AAA100"]["lat"] is None  # fixture sans coordonnées
    # Remorque sans cellule connue : proposée quand même.
    Cellule.objects.filter(secteur__site=remorque).delete()
    assert "1RM128" in {s["code"] for s in reseau_pour_carte()["sites"]}


def _donnees_evenement(**modifs):
    donnees = {"nom": "Foire avec remorque", "type": "Foire", "description": "", "sites": "AAA100,1RM128",
               "secteurs": "1RM1282", "cellules": "1RMe1", "deploiements": json.dumps(OMNI),
               "semaines_reference": "4", "kpis_choisis": "false", "_enregistrer": "1"}
    donnees.update(modifs)
    return donnees


def test_creation_d_un_evenement_avec_remorque(client_admin, remorque):
    html = client_admin.get(reverse("evenements:nouveau")).content.decode()
    assert 'name="deploiements"' in html and "sites mobiles (remorques)" in html
    reponse = client_admin.post(reverse("evenements:nouveau"), _donnees_evenement())
    assert reponse.status_code == 302, reponse.content.decode()[:3000]
    e = Evenement.objects.get(nom="Foire avec remorque")
    # La remorque ne compte que par sa disposition déclarée.
    assert (e.sites, e.secteurs, e.cellules) == (["AAA100"], [], [])
    assert e.deploiements == OMNI | {"1RM128": {**OMNI["1RM128"], "secteurs": [{**OMNI["1RM128"]["secteurs"][0],
        "cellules": [["1RMe1", "LTE"], ["1RMe2", "LTE"], ["1RMe3", "LTE"], ["1RM128A", "WCDMA"]]}]}}
    assert e.noms_cellules("LTE") == ["1RMe1", "1RMe2", "1RMe3", "AAAe1", "AAAe2"]  # 1RMe3 : hors référentiel
    assert e.noms_cellules("WCDMA") == ["1RM128A"]
    # Page de modification : le JSON est restitué tel quel.
    html = client_admin.get(reverse("evenements:modifier", args=[e.pk])).content.decode()
    assert "1RMe3" in html

    reponse = client_admin.post(reverse("evenements:nouveau"), _donnees_evenement(
        nom="Autre", sites="", secteurs="", cellules="",
        deploiements=json.dumps({"1RM128": {"secteurs": [{"numero": 1, "cellules": []}]}})))
    assert reponse.status_code == 200 and "au moins une cellule" in reponse.content.decode()


def test_zone_de_l_evenement(remorque):
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"], deploiements=OMNI)
    Site.objects.filter(code_site="AAA100").update(latitude=-22.27, longitude=166.45)
    zone = zone_pour_carte(e)
    sites = {s["code"]: s for s in zone["sites"]}
    assert sites["1RM128"]["lat"] == -22.2758 and sites["1RM128"]["mobile"]  # position déclarée, pas -22.14
    assert sites["1RM128"]["nb_secteurs"] == 1 and sites["1RM128"]["secteurs"][0]["azimut"] == 0
    assert sites["AAA100"]["nb_secteurs"] == 2 and not sites["AAA100"]["mobile"]
    assert (zone["nb_secteurs"], zone["nb_cellules"], zone["sans_position"]) == (3, 6, 0)
    e.deploiements = {"1RM128": {**OMNI["1RM128"], "lat": None, "lon": None}}
    assert zone_pour_carte(e)["sans_position"] == 1


def test_analyse_selon_la_disposition_declaree(remorque, analyste):  # noqa: F811
    lignes = [{"EutranCell_Id": c, "DateHour": datetime(2026, 9, j, h), "pmRrcConnEstabAtt": 100,
               "pmRrcConnEstabSucc": 99, "PayloadDl_mB": 10.0}
              for j in (1, 8) for h in (18, 19) for c in ("1RMe1", "1RMe2")]
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    pd.DataFrame(lignes).to_sql("lte_cell_hour", engine, index=False)
    e = Evenement.objects.create(nom="Concert", deploiements=OMNI, semaines_reference=1,
                                 kpis=["lte_rrc_setup_sr", "lte_payload_dl"])
    a = analyser(e, analyste, engine, creneaux=[(datetime(2026, 9, 8, 18), datetime(2026, 9, 8, 20))])
    lte = next(t for t in a.par_techno if t.techno == "LTE")
    assert lte.nb_cellules == 3 and lte.cellules_sans_donnees == ["1RMe3"]
    assert set(lte.courbes[0].par_site) == {"REMORQUE_1"}
    # Les deux cellules sont dans le secteur omni déclaré, pas dans les secteurs 1 et 2 du référentiel.
    assert mobiles.entites(e.deploiements, "LTE", "secteur") == {"1RMe1": "1RM1281", "1RMe2": "1RM1281",
                                                                  "1RMe3": "1RM1281"}
    assert {x.entite for x in a.anomalies} <= {"1RM1281"}


def test_visibilite_par_les_cellules_deployees(remorque):
    e = Evenement.objects.create(nom="Concert", deploiements=OMNI)
    lecteur = User.objects.create_user("dumbea")
    Perimetre.objects.create(nom="Dumbea", communes=["DUMBEA"]).utilisateurs.add(lecteur)
    assert list(evenements_visibles(lecteur)) == [e]
    autre = User.objects.create_user("paita")
    Perimetre.objects.create(nom="Paita", communes=["PAITA"]).utilisateurs.add(autre)
    assert list(evenements_visibles(autre)) == []
