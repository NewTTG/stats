"""Création / modification d'un événement dans l'administration : formulaire en pleine page
(zone couverte sur carte, créneaux date + heure, KPI), données de la carte, azimut des secteurs."""

from datetime import datetime

import pandas as pd
import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse
from django.utils import timezone

from apps.evenements.models import Creneau, Evenement
from apps.referentiel.importation import importer
from apps.referentiel.models import Secteur

from .test_service import referentiel  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db
URL_AJOUT = "admin:evenements_evenement_add"


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


def _donnees(**modifs):
    donnees = {
        "nom": "Foire de Bourail", "type": "Foire", "description": "",
        "sites": "AAA100", "secteurs": "BBB2002", "cellules": "BBBe1",
        "semaines_reference": "4", "kpis_choisis": "false",
        "creneaux-TOTAL_FORMS": "1", "creneaux-INITIAL_FORMS": "0",
        "creneaux-MIN_NUM_FORMS": "0", "creneaux-MAX_NUM_FORMS": "1000",
        "creneaux-0-debut": "2026-08-15T18:00", "creneaux-0-fin": "2026-08-15T23:00",
        "_save": "Enregistrer",
    }
    donnees.update(modifs)
    return donnees


def test_page_d_edition(client_admin, referentiel):  # noqa: F811
    html = client_admin.get(reverse(URL_AJOUT)).content.decode()
    assert 'id="ev-zone"' in html and reverse("admin:evenements_evenement_reseau") in html
    assert 'type="datetime-local"' in html and "vendor/leaflet-1.9.4/leaflet.js" in html
    # Plus de widgets date / heure de Django ni de saisie libre des cellules.
    assert "vDateField" not in html and "<textarea name=\"cellules\"" not in html
    assert 'type="hidden" name="cellules"' in html


def test_creation(client_admin, referentiel):  # noqa: F811
    reponse = client_admin.post(reverse(URL_AJOUT), _donnees())
    assert reponse.status_code == 302, reponse.content.decode()[:2000]
    e = Evenement.objects.get(nom="Foire de Bourail")
    assert (e.sites, e.secteurs, e.cellules, e.kpis) == (["AAA100"], ["BBB2002"], ["BBBe1"], [])
    assert e.cree_par.username == "admin"
    creneau = e.creneaux.get()
    assert timezone.localtime(creneau.debut).replace(tzinfo=None) == datetime(2026, 8, 15, 18)  # heure de Nouméa
    assert e.noms_cellules("LTE") == ["AAAe1", "AAAe2", "BBBe1", "BBBe2"]


def test_kpi_choisis_et_analyse(client_admin, referentiel):  # noqa: F811
    reponse = client_admin.post(reverse(URL_AJOUT), _donnees(
        kpis_choisis="true", kpis=["lte_rrc_setup_sr", "lte_erab_drop"], _save="", _analyse="1"))
    e = Evenement.objects.get(nom="Foire de Bourail")
    assert reponse.status_code == 302 and reponse["Location"] == reverse("evenements:detail", args=[e.pk])
    assert e.kpis == ["lte_rrc_setup_sr", "lte_erab_drop"]
    # Retour aux KPI principaux : la liste enregistrée est vidée.
    url = reverse("admin:evenements_evenement_change", args=[e.pk])
    client_admin.post(url, _donnees(kpis=["lte_rrc_setup_sr"], **{"creneaux-0-debut": "", "creneaux-0-fin": ""}))
    e.refresh_from_db()
    assert e.kpis == []


def test_erreurs(client_admin, referentiel):  # noqa: F811
    reponse = client_admin.post(reverse(URL_AJOUT), _donnees(
        sites="", secteurs="", cellules="", kpis_choisis="true",
        **{"creneaux-0-fin": "2026-08-15T17:00"}))
    assert reponse.status_code == 200
    html = reponse.content.decode()
    assert html.count("Choisissez au moins un site, un secteur ou une cellule.") == 1
    assert "Cochez au moins un KPI" in html
    assert "La fin doit suivre le début." in html
    assert not Evenement.objects.exists()


def test_retrait_d_un_creneau(client_admin, referentiel):  # noqa: F811
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    c = Creneau.objects.create(evenement=e, debut=timezone.now(), fin=timezone.now() + timezone.timedelta(hours=2))
    reponse = client_admin.post(reverse("admin:evenements_evenement_change", args=[e.pk]), _donnees(
        nom="Concert", **{"creneaux-INITIAL_FORMS": "1", "creneaux-0-id": str(c.pk), "creneaux-0-evenement": str(e.pk),
                          "creneaux-0-DELETE": "on"}))
    assert reponse.status_code == 302
    assert not e.creneaux.exists()


def test_donnees_de_la_carte(client_admin, referentiel):  # noqa: F811
    Secteur.objects.filter(code="AAA1001").update(azimut=40)
    donnees = client_admin.get(reverse("admin:evenements_evenement_reseau")).json()
    aaa = next(s for s in donnees["sites"] if s["code"] == "AAA100")
    assert aaa["nom"] == "SITE_AAA" and aaa["commune"] == "NOUMEA"
    assert [(s["code"], s["azimut"], s["cellules"]) for s in aaa["secteurs"]] == [
        ("AAA1001", 40, [["AAAe1", "LTE"]]), ("AAA1002", None, [["AAAe2", "LTE"]])]
    assert donnees["libres"] == [["ORPHe1", "LTE"]]


def test_droits(client, referentiel):  # noqa: F811
    lecteur = User.objects.create_user("lecteur", password="x", is_staff=True)
    lecteur.user_permissions.add(Permission.objects.get(codename="view_evenement"))
    client.force_login(lecteur)
    assert client.get(reverse("admin:evenements_evenement_reseau")).status_code == 403
    # Consultation seule : page standard de Django, sans carte.
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    html = client.get(reverse("admin:evenements_evenement_change", args=[e.pk])).content.decode()
    assert "Concert" in html and 'id="ev-zone"' not in html


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
