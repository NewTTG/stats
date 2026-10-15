"""Noms des KPI réglés dans l'admin et colonnes de la base proposées aux utilisateurs comme indicateurs."""

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.kpi.catalogue import catalogue, catalogue_yaml, kpis_principaux
from apps.kpi.forms import RequeteForm
from apps.kpi.models import ColonneKpi, SeuilKpi, unite_et_calcul
from apps.kpi.service import executer

from .test_service import analyste, base_kpi, referentiel, requete  # noqa: F401

pytestmark = pytest.mark.django_db

KPI = reverse("admin:kpi_seuilkpi_changelist")


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


def _colonne(nom="PayloadDl_mB", **champs):
    valeurs = {"techno": "LTE", "nom": nom, "libelle": "Volume descendant", "categorie": "trafic",
               "unite": "Mo", "calcul": "somme", "tables": "jour, heure", "type_donnees": "float",
               "proposee": True, **champs}
    return ColonneKpi.objects.create(**valeurs)


# ------------------------------------------------------------------ noms des KPI

def test_kpi_initialises_avec_le_catalogue_puis_renommes_partout(client_admin):
    yaml = catalogue_yaml()["lte_payload_dl"]
    html = client_admin.get(KPI).content.decode()
    assert "KPI : noms et seuils" in html
    reglage = SeuilKpi.objects.get(code="lte_payload_dl")
    assert (reglage.libelle, reglage.categorie, reglage.description) == (yaml.libelle, yaml.categorie, "")

    reglage.libelle, reglage.categorie, reglage.description = "Data téléchargée", "debit", "Octets envoyés aux mobiles"
    reglage.save()
    kpi = catalogue()["lte_payload_dl"]
    assert (kpi.libelle, kpi.categorie, kpi.note) == ("Data téléchargée", "debit", "Octets envoyés aux mobiles")
    assert catalogue_yaml()["lte_payload_dl"].libelle == yaml.libelle  # le YAML reste la référence
    # vu par les utilisateurs : choix des KPI du formulaire de requête
    assert ("lte_payload_dl", "LTE · Data téléchargée (Mo)") in RequeteForm().fields["kpis"].choices

    # description vidée : plus d'info-bulle ; ancienne ligne sans description : celle du YAML
    reglage.description = ""
    reglage.save()
    assert catalogue()["lte_payload_dl"].note is None
    SeuilKpi.objects.filter(code="lte_dl_user_thp").update(description=None, libelle="")
    SeuilKpi.synchroniser()
    complete = SeuilKpi.objects.get(code="lte_dl_user_thp")
    assert complete.libelle == catalogue_yaml()["lte_dl_user_thp"].libelle
    assert complete.description == catalogue_yaml()["lte_dl_user_thp"].note


def test_kpi_modifies_dans_la_liste_et_retablis(client_admin):
    client_admin.get(KPI)
    reglage = SeuilKpi.objects.get(code="lte_rrc_setup_sr")
    donnees = {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1, "_save": "Enregistrer", "form-0-id": reglage.pk,
               "form-0-libelle": "Accès RRC", "form-0-categorie": "accessibilite", "form-0-description": "",
               "form-0-alerte": "97", "form-0-critique": "90"}
    assert client_admin.post(f"{KPI}?q=lte_rrc_setup_sr", donnees).status_code == 302
    reglage.refresh_from_db()
    assert (reglage.libelle, reglage.alerte, reglage.critique) == ("Accès RRC", 97, 90)
    # nom obligatoire
    reponse = client_admin.post(f"{KPI}?q=lte_rrc_setup_sr", {**donnees, "form-0-libelle": ""})
    assert reponse.status_code == 200 and reponse.context["cl"].formset.errors[0]["libelle"]
    # fiche : formule et colonnes de la base, avec lien
    fiche = client_admin.get(reverse("admin:kpi_seuilkpi_change", args=[reglage.pk])).content.decode()
    assert "pmRrcConnEstabSucc" in fiche and "Nom dans le catalogue" in fiche
    # action : retour aux valeurs du YAML
    client_admin.post(KPI, {"action": "retablir", "_selected_action": [reglage.pk]})
    reglage.refresh_from_db()
    yaml = catalogue_yaml()["lte_rrc_setup_sr"]
    assert (reglage.libelle, reglage.alerte, reglage.critique) == (yaml.libelle, yaml.seuils.alerte,
                                                                    yaml.seuils.critique)


# ------------------------------------------------------------------ colonnes proposées

def test_unite_et_calcul_suggeres():
    assert unite_et_calcul("CellAvaibilityD_p") == ("%", "moyenne")
    assert unite_et_calcul("PayloadDl_mB") == ("Mo", "somme")
    assert unite_et_calcul("RrcConnMax_max_nb") == ("nombre", "pic")
    assert unite_et_calcul("Inconnue") == ("", "somme")


def test_colonne_proposee_doit_etre_complete():
    colonne = ColonneKpi(techno="LTE", nom="PayloadDl_mB", tables="jour, heure", type_donnees="float", proposee=True)
    with pytest.raises(ValidationError) as erreur:
        colonne.clean()
    assert set(erreur.value.message_dict) == {"libelle", "categorie", "calcul", "unite"}
    colonne.libelle, colonne.categorie, colonne.calcul, colonne.unite = "Volume", "trafic", "somme", "Mo"
    colonne.clean()
    for modif in ({"tables": "jour"}, {"presente": False}, {"type_donnees": "varchar(20)"}):
        autre = ColonneKpi(**{**{f.name: getattr(colonne, f.name) for f in ColonneKpi._meta.fields}, **modif})
        with pytest.raises(ValidationError):
            autre.clean()


def test_colonnes_proposees_dans_le_catalogue():
    _colonne()
    _colonne("CellAvaibilityD_p", libelle="Disponibilité", categorie="disponibilite", unite="%", calcul="moyenne",
             description="Moyenne des cellules")
    _colonne("Brouillon", proposee=False)
    _colonne("Absente", presente=False)
    cat = catalogue()
    volume, dispo = cat["col_lte_PayloadDl_mB"], cat["col_lte_CellAvaibilityD_p"]
    assert (volume.libelle, volume.unite, volume.categorie, volume.additif) == ("Volume descendant", "Mo", "trafic", True)
    assert (dispo.denominateur, dispo.note) == ("1", "Moyenne des cellules")
    assert "col_lte_Brouillon" not in cat and "col_lte_Absente" not in cat
    # pas analysées par défaut dans les événements
    assert not any(c.startswith("col_") for c in kpis_principaux(cat))
    assert ("col_lte_PayloadDl_mB", "LTE · Volume descendant (Mo)") in RequeteForm().fields["kpis"].choices


@pytest.mark.parametrize("calcul, attendu", [("somme", 160.0), ("moyenne", 20.0), ("pic", 80.0)])
def test_colonne_proposee_calculee(referentiel, base_kpi, analyste, calcul, attendu):
    # 4 cellules × 2 jours, 20 Mo par cellule et par jour (table journalière)
    _colonne(calcul=calcul)
    res = executer(requete(kpis=["col_lte_PayloadDl_mB"]), analyste, base_kpi).par_techno[0]
    assert res.synthese_globale["col_lte_PayloadDl_mB"] == pytest.approx(attendu)


def test_colonne_proposee_depuis_la_liste(client_admin):
    colonne = ColonneKpi.objects.create(techno="LTE", nom="PayloadDl_mB", tables="jour, heure", type_donnees="float",
                                        unite="Mo", calcul="somme")
    liste = reverse("admin:kpi_colonnekpi_changelist")
    donnees = {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1, "_save": "Enregistrer", "form-0-id": colonne.pk,
               "form-0-libelle": "", "form-0-categorie": "", "form-0-description": "", "form-0-proposee": "on",
               "form-0-calcul": "somme"}
    reponse = client_admin.post(liste, donnees)
    assert reponse.status_code == 200 and "Obligatoire pour proposer" in reponse.content.decode()
    assert "col_lte_PayloadDl_mB" not in catalogue()
    donnees.update({"form-0-libelle": "Volume descendant", "form-0-categorie": "trafic"})
    assert client_admin.post(liste, donnees).status_code == 302
    assert catalogue()["col_lte_PayloadDl_mB"].libelle == "Volume descendant"
    assert client_admin.get(liste, {"usage": "proposee"}).context["cl"].result_count == 1
