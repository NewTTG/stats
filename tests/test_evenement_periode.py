"""Période analysée choisie à l'affichage de l'événement (paramètres debut / fin), décalages,
mémorisation, rapports qui suivent la période."""

from datetime import datetime
from urllib.parse import urlencode

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone

from apps.comptes.models import DemandeSuivie
from apps.evenements import periode
from apps.evenements.models import Creneau, Evenement
from apps.rapports.models import Rapport

from .test_evenements import base_horaire, evenement  # noqa: F401  (fixtures)
from .test_service import referentiel  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_admin(client):
    client.force_login(User.objects.create_superuser("admin", password="secret-123-Abc"))
    return client


@pytest.fixture
def source(base_horaire, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.evenements.views.moteur_kpi", lambda: base_horaire)
    return base_horaire


def _url(e, **params):
    return f"{reverse('evenements:detail', args=[e.pk])}?{urlencode(params, doseq=True)}"


# ------------------------------------------------------------------ lecture et décalage

def _lire(texte):
    return periode.lire(QueryDict(texte))[0]


def test_jours_et_plage_horaire_commune():
    assert _lire("du=2026-09-29&au=2026-09-30&de=18&a=21") == [
        (datetime(2026, 9, 29, 18), datetime(2026, 9, 29, 21)), (datetime(2026, 9, 30, 18), datetime(2026, 9, 30, 21))]
    assert _lire("du=2026-09-29&de=20&a=2") == [(datetime(2026, 9, 29, 20), datetime(2026, 9, 30, 2))]  # lendemain
    assert _lire("du=2026-09-29&de=0&a=24") == [(datetime(2026, 9, 29), datetime(2026, 9, 30))]
    assert _lire("") == []


def test_heures_differentes_selon_les_jours():
    assert _lire("detail=1&jour=2026-09-30&de=18&a=20&jour=&de=&a=&jour=2026-09-29&de=17&a=23") == [
        (datetime(2026, 9, 29, 17), datetime(2026, 9, 29, 23)), (datetime(2026, 9, 30, 18), datetime(2026, 9, 30, 20))]


def test_anciens_parametres_en_heures_pleines():
    assert _lire("debut=2026-09-30T17:30&fin=2026-09-30T19:10") == [(datetime(2026, 9, 30, 17), datetime(2026, 9, 30, 20))]


@pytest.mark.parametrize("texte,message", [
    ("du=&de=18&a=20", "premier jour"),
    ("du=30/09/2026&de=18&a=20", "illisible"),
    ("du=2026-09-30&au=2026-09-29&de=18&a=20", "dernier jour doit suivre"),
    ("du=2026-09-30&de=&a=20", "heure de début"),
    ("du=2026-09-30&de=18&a=25", "heure de fin"),
    ("du=2026-01-01&au=2026-03-01&de=0&a=24", "31 jours"),
    ("detail=1&jour=2026-09-30&de=18&a=", "heure de fin"),
])
def test_saisies_invalides(texte, message):
    with pytest.raises(periode.PeriodeInvalide, match=message):
        _lire(texte)


def test_parametres_et_saisie():
    reguliere = _lire("du=2026-09-29&au=2026-09-30&de=18&a=21")
    assert periode.parametres(reguliere) == [("du", "2026-09-29"), ("au", "2026-09-30"), ("de", "18"), ("a", "21")]
    irreguliere = _lire("detail=1&jour=2026-09-29&de=17&a=23&jour=2026-09-30&de=18&a=2")
    assert periode.parametres(irreguliere) == [("detail", "1"), ("jour", "2026-09-29"), ("de", "17"), ("a", "23"),
                                               ("jour", "2026-09-30"), ("de", "18"), ("a", "2")]
    assert periode.saisie(irreguliere).detail


def test_decalages():
    creneau = [(datetime(2026, 3, 31, 18), datetime(2026, 3, 31, 22))]
    assert periode.decaler(creneau, mois=-1) == [(datetime(2026, 2, 28, 18), datetime(2026, 2, 28, 22))]
    assert periode.decaler(creneau, mois=-12) == [(datetime(2025, 3, 31, 18), datetime(2025, 3, 31, 22))]
    assert periode.decaler(creneau, jours=7)[0][0] == datetime(2026, 4, 7, 18)
    # Jours consécutifs : l'écart avec le premier jour est gardé (30 et 31 mars - 1 mois : 28 février et 1er mars).
    deux = [(datetime(2026, 3, 30, 18), datetime(2026, 3, 30, 22)), (datetime(2026, 3, 31, 18), datetime(2026, 3, 31, 22))]
    assert [d.date().isoformat() for d, _ in periode.decaler(deux, mois=-1)] == ["2026-02-28", "2026-03-01"]


# ------------------------------------------------------------------ page de l'événement

def test_sans_periode_la_page_la_demande(client_admin, referentiel, source):  # noqa: F811
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    reponse = client_admin.get(reverse("evenements:detail", args=[e.pk]))
    html = reponse.content.decode()
    assert reponse.status_code == 200 and "Période analysée" in html
    assert "Choisissez la période à analyser" in html and "administration" not in html.split("<main", 1)[1]
    assert "analyse" not in reponse.context and not DemandeSuivie.objects.exists()


def test_periode_de_l_url(client_admin, evenement, source):  # noqa: F811
    reponse = client_admin.get(_url(evenement, du="2026-09-30", de="18", a="20", niveau="site"))
    analyse = reponse.context["analyse"]
    assert analyse.creneaux == [(datetime(2026, 9, 30, 18), datetime(2026, 9, 30, 20))]  # pas ceux mémorisés
    html = reponse.content.decode()
    assert 'name="du" value="2026-09-30"' in html and '<option value="18" selected>18 h</option>' in html
    assert 'type="datetime-local"' not in html  # heures pleines
    # Décalages : même période une semaine plus tôt, niveau conservé ; onglets de niveau gardent la période.
    assert "du=2026-09-23&amp;au=2026-09-23&amp;de=18&amp;a=20&amp;niveau=site" in html
    assert "?du=2026-09-30&amp;au=2026-09-30&amp;de=18&amp;a=20&amp;niveau=secteur" in html
    assert DemandeSuivie.objects.get().parametres["creneaux"] == [["2026-09-30T18:00:00", "2026-09-30T20:00:00"]]
    # Courbes par site et par cellule ; carte de la zone (sites et secteurs actifs seulement).
    courbe = analyse.par_techno[0].courbes[0]
    # BBBe1 absente le 30/09, BBBe2 jamais présente : seul SITE_AAA a des valeurs.
    assert set(courbe.par_site) == {"SITE_AAA"} and set(courbe.par_cellule) == {"AAAe1", "AAAe2"}
    assert len(courbe.par_cellule["AAAe1"]) == 2  # 18 h et 19 h
    zone = reponse.context["zone"]
    assert zone["nb_cellules"] == 4 and zone["sans_position"] == 2  # référentiel de test sans coordonnées


def test_periode_memorisee_par_defaut(client_admin, evenement, source):  # noqa: F811
    analyse = client_admin.get(reverse("evenements:detail", args=[evenement.pk])).context["analyse"]
    assert [d.day for d, _ in analyse.creneaux] == [29, 30]


def test_periode_invalide(client_admin, evenement, source):  # noqa: F811
    reponse = client_admin.get(_url(evenement, du="2026-09-30", de="18", a=""))
    assert reponse.status_code == 200 and "analyse" not in reponse.context
    html = reponse.content.decode()
    assert "choisissez l&#x27;heure de fin" in html and 'name="du" value="2026-09-30"' in html  # saisie gardée


def test_memoriser_la_periode(client, evenement):  # noqa: F811
    lecteur = User.objects.create_user("lecteur")
    lecteur.groups.add(Group.objects.create(name="Analyste"))  # tout le réseau
    client.force_login(lecteur)
    url = reverse("evenements:memoriser_periode", args=[evenement.pk])
    donnees = {"du": "2027-09-28", "de": "18", "a": "22"}
    assert client.post(url, donnees).status_code == 403
    lecteur.user_permissions.add(Permission.objects.get(codename="change_evenement"))
    reponse = client.post(url, donnees)
    assert reponse.status_code == 302 and "du=2027-09-28&au=2027-09-28&de=18&a=22" in reponse["Location"]
    creneau = Creneau.objects.get(evenement=evenement)
    assert timezone.localtime(creneau.debut).replace(tzinfo=None) == datetime(2027, 9, 28, 18)


def test_rapport_suit_la_periode(client_admin, evenement, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.rapports.views.lancer", lambda rapport, parent=None: True)
    client_admin.post(reverse("rapports:evenement", args=[evenement.pk]), {
        "niveau": "secteur", "format": "pdf", "du": "2026-09-30", "de": "18", "a": "20"})
    rapport = Rapport.objects.get()
    assert rapport.parametres["creneaux"] == [["2026-09-30T18:00:00", "2026-09-30T20:00:00"]]
    assert rapport.titre == "Foire du 30/09/2026 : par secteur"


def test_rapport_utilise_la_periode_enregistree(evenement, base_horaire, monkeypatch):  # noqa: F811
    from apps.rapports import taches

    vues = []
    monkeypatch.setattr(taches, "moteur_kpi", lambda: base_horaire)
    monkeypatch.setattr(taches, "pdf_evenement", lambda analyse: vues.append(analyse.creneaux) or b"%PDF")
    rapport = Rapport.objects.create(utilisateur=User.objects.create_superuser("admin"), titre="Foire",
                                     nature="evenement", format="pdf",
                                     parametres={"evenement": evenement.pk, "niveau": "secteur",
                                                 "creneaux": [["2026-09-30T18:00:00", "2026-09-30T20:00:00"]]})
    taches.contenu(rapport)
    assert vues == [[(datetime(2026, 9, 30, 18), datetime(2026, 9, 30, 20))]]


def test_duree_des_requetes(client_admin, evenement, caplog):  # noqa: F811
    with caplog.at_level("INFO", logger="stats.requetes"):
        reponse = client_admin.get(reverse("evenements:liste"))
    assert reponse["Server-Timing"].startswith("app;dur=")
    assert any("GET /evenements/ 200 en" in m for m in caplog.messages)
