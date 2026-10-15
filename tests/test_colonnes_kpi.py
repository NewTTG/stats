"""Gestion des KPI (admin) : colonnes lues dans la base KPI, nom affiché, catégorie, description."""

import pandas as pd
import pytest
import sqlalchemy as sa
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from apps.kpi.models import ColonneKpi, SeuilKpi
from apps.kpi.source import BaseKpiNonConfiguree, colonnes_base

pytestmark = pytest.mark.django_db

LISTE = reverse("admin:kpi_colonnekpi_changelist")
RELIRE = reverse("admin:kpi_colonnekpi_relire")


def _base(lte_jour=("pmRrcConnEstabAtt", "pmRrcConnEstabSucc", "Tac"), wcdma=True):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    ligne = {"EutranCell_Id": "AAAe1", "DateDay": "2026-09-01", **{c: 1.0 for c in lte_jour}}
    pd.DataFrame([ligne]).to_sql("lte_cell_day", engine, index=False)
    pd.DataFrame([{"EutranCell_Id": "AAAe1", "DateHour": "2026-09-01 00:00", "pmRrcConnEstabAtt": 1,
                   "PayloadDl_mB": 2.0}]).to_sql("lte_cell_hour", engine, index=False)
    if wcdma:
        pd.DataFrame([{"CellWcdma": "AAA1", "DateDay": "2026-09-01", "CsTraffic_erlg": 1.0}]).to_sql(
            "wcdma_cell_day", engine, index=False)
    return engine


@pytest.fixture
def base(monkeypatch):
    engine = _base()
    monkeypatch.setattr("apps.kpi.source.moteur_kpi", lambda: engine)
    return engine


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


def test_colonnes_base_sans_cles_avec_tables():
    colonnes = colonnes_base(_base())
    assert set(colonnes["LTE"]) == {"pmRrcConnEstabAtt", "pmRrcConnEstabSucc", "Tac", "PayloadDl_mB"}
    assert sorted(colonnes["LTE"]["pmRrcConnEstabAtt"]["tables"]) == ["heure", "jour"]
    assert colonnes["LTE"]["PayloadDl_mB"]["tables"] == ["heure"]
    assert set(colonnes["WCDMA"]) == {"CsTraffic_erlg"}  # table horaire absente : ignorée


def test_synchroniser_conserve_les_saisies_et_signale_les_disparues():
    bilan = ColonneKpi.synchroniser(_base())
    assert bilan == {"lues": 5, "nouvelles": 5, "disparues": 0}
    att = ColonneKpi.objects.get(techno="LTE", nom="pmRrcConnEstabAtt")
    assert att.tables == "jour, heure" and att.presente
    # catégorie reprise des KPI du catalogue qui utilisent la colonne (une seule catégorie)
    assert att.categorie == "accessibilite"
    assert ColonneKpi.objects.get(nom="Tac").categorie == ""
    att.libelle, att.description = "Tentatives RRC", "Demandes de connexion"
    att.save()

    bilan = ColonneKpi.synchroniser(_base(lte_jour=("pmRrcConnEstabAtt", "NouvelleColonne"), wcdma=False))
    assert bilan == {"lues": 3, "nouvelles": 1, "disparues": 3}
    att.refresh_from_db()
    assert (att.libelle, att.description, att.presente) == ("Tentatives RRC", "Demandes de connexion", True)
    assert set(ColonneKpi.objects.filter(presente=False).values_list("nom", flat=True)) == {
        "pmRrcConnEstabSucc", "Tac", "CsTraffic_erlg"}
    # une colonne qui revient redevient présente
    ColonneKpi.synchroniser(_base())
    assert not ColonneKpi.objects.filter(presente=False, nom="Tac").exists()


def test_page_lue_a_la_premiere_ouverture_puis_editable(client_admin, base):
    reponse = client_admin.get(LISTE)
    html = reponse.content.decode()
    assert reponse.status_code == 200 and "Colonnes de la base KPI" in html and "Relire la base KPI" in html
    assert ColonneKpi.objects.count() == 5
    assert reponse.context["etat"]["lte"] == 4 and reponse.context["etat"]["a_nommer"] == 5
    # KPI du catalogue qui utilisent la colonne
    assert "Taux de succès d&#x27;établissement RRC" in html
    # espace Référentiel : onglet actif, pastille des colonnes à nommer (onglet et menu latéral)
    espaces = {e["libelle"]: e for e in reponse.context["navigation"]}
    assert espaces["Référentiel"]["actif"] and espaces["Référentiel"]["compteur"] == 5
    assert [o["libelle"] for o in reponse.context["onglets"]] == [
        "Événements", "KPI : noms et seuils", "Colonnes de la base"]
    onglet = reponse.context["onglet"]
    assert onglet["libelle"] == "Colonnes de la base" and onglet["compteur"] == 5
    # « utilisée par » : lien vers la fiche du KPI, à modifier
    rrc = SeuilKpi.objects.get(code="lte_rrc_setup_sr")
    assert f'href="{reverse("admin:kpi_seuilkpi_change", args=[rrc.pk])}"' in html

    # saisie dans la liste : nom affiché, catégorie, description
    colonnes = list(ColonneKpi.objects.order_by("techno", "nom"))
    donnees = {"form-TOTAL_FORMS": len(colonnes), "form-INITIAL_FORMS": len(colonnes), "_save": "Enregistrer"}
    for i, c in enumerate(colonnes):
        donnees.update({f"form-{i}-id": c.pk, f"form-{i}-libelle": c.libelle, f"form-{i}-categorie": c.categorie,
                        f"form-{i}-description": c.description, f"form-{i}-calcul": c.calcul})
    i = next(i for i, c in enumerate(colonnes) if c.nom == "Tac")
    donnees.update({f"form-{i}-libelle": "Zone de suivi (TAC)", f"form-{i}-categorie": "mobilite",
                    f"form-{i}-description": "Code de zone LTE"})
    assert client_admin.post(LISTE, donnees).status_code == 302
    tac = ColonneKpi.objects.get(nom="Tac")
    assert (tac.libelle, tac.categorie, tac.description, tac.nom_affiche) == (
        "Zone de suivi (TAC)", "mobilite", "Code de zone LTE", "Zone de suivi (TAC)")

    # filtres : à nommer, catégorie, usage par un KPI
    assert client_admin.get(LISTE, {"nommee": "non"}).context["cl"].result_count == 4
    assert [c.nom for c in client_admin.get(LISTE, {"categorie": "mobilite"}).context["cl"].result_list] == ["Tac"]
    libres = {c.nom for c in client_admin.get(LISTE, {"usage": "libre"}).context["cl"].result_list}
    assert libres == {"Tac", "CsTraffic_erlg"}
    # pas d'ajout manuel
    assert client_admin.get(reverse("admin:kpi_colonnekpi_add")).status_code == 403


def test_relire_a_la_demande(client_admin, base, monkeypatch):
    ColonneKpi.objects.create(techno="LTE", nom="Ancienne", libelle="Ancienne colonne")
    client_admin.get(LISTE)  # liste non vide : pas de lecture automatique
    assert ColonneKpi.objects.count() == 1
    reponse = client_admin.post(RELIRE, follow=True)
    assert "5 colonne(s) lue(s) dans la base KPI, 5 nouvelle(s), 1 absente(s) désormais." in reponse.content.decode()
    assert not ColonneKpi.objects.get(nom="Ancienne").presente
    assert client_admin.get(RELIRE).status_code == 403  # POST seulement

    def absente():
        raise BaseKpiNonConfiguree("non configurée")

    monkeypatch.setattr("apps.kpi.source.moteur_kpi", absente)
    reponse = client_admin.post(RELIRE, follow=True)
    assert "Base KPI non configurée" in reponse.content.decode()


def test_droits(client, base):
    user = User.objects.create_user("lecteur", password="secret-123-Abc", is_staff=True)
    client.force_login(user)
    assert client.get(LISTE).status_code == 403
    user.user_permissions.add(Permission.objects.get(codename="view_colonnekpi"))
    reponse = client.get(LISTE)
    # lecture seule : ni lecture de la base, ni bouton, ni relecture
    assert reponse.status_code == 200 and not ColonneKpi.objects.exists()
    assert "Relire la base KPI" not in reponse.content.decode()
    assert client.post(RELIRE).status_code == 403
