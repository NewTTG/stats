"""Période analysée choisie à l'affichage de l'événement (paramètres debut / fin), décalages,
mémorisation, rapports qui suivent la période."""

from datetime import datetime
from urllib.parse import urlencode

import pytest
from django.contrib.auth.models import Group, Permission, User
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


def _url(e, *creneaux, **autres):
    params = [p for d, f in creneaux for p in (("debut", d), ("fin", f))] + list(autres.items())
    return f"{reverse('evenements:detail', args=[e.pk])}?{urlencode(params)}"


# ------------------------------------------------------------------ lecture et décalage

def test_lecture_des_creneaux():
    assert periode.lire(["2026-09-30T18:00", "", "2026-09-29T18:00"], ["2026-09-30T20:00", "", "2026-09-29T21:00"]) == [
        (datetime(2026, 9, 29, 18), datetime(2026, 9, 29, 21)), (datetime(2026, 9, 30, 18), datetime(2026, 9, 30, 20))]
    for debuts, fins, message in [
        (["2026-09-30T18:00"], [""], "indiquez le début et la fin"),
        (["30/09/2026"], ["2026-09-30T20:00"], "illisible"),
        (["2026-09-30T18:00"], ["2026-09-30T17:00"], "la fin doit suivre le début"),
        (["2026-01-01T00:00"], ["2026-03-01T00:00"], "trop longue"),
    ]:
        with pytest.raises(periode.PeriodeInvalide, match=message):
            periode.lire(debuts, fins)


def test_decalages():
    creneau = [(datetime(2026, 3, 31, 18), datetime(2026, 3, 31, 22))]
    assert periode.decaler(creneau, mois=-1) == [(datetime(2026, 2, 28, 18), datetime(2026, 2, 28, 22))]
    assert periode.decaler(creneau, mois=-12) == [(datetime(2025, 3, 31, 18), datetime(2025, 3, 31, 22))]
    assert periode.decaler(creneau, jours=7)[0][0] == datetime(2026, 4, 7, 18)


# ------------------------------------------------------------------ page de l'événement

def test_sans_periode_la_page_la_demande(client_admin, referentiel, source):  # noqa: F811
    e = Evenement.objects.create(nom="Concert", sites=["AAA100"])
    reponse = client_admin.get(reverse("evenements:detail", args=[e.pk]))
    html = reponse.content.decode()
    assert reponse.status_code == 200 and "Période analysée" in html
    assert "Choisissez la période à analyser" in html and "administration" not in html.split("<main", 1)[1]
    assert "analyse" not in reponse.context and not DemandeSuivie.objects.exists()


def test_periode_de_l_url(client_admin, evenement, source):  # noqa: F811
    reponse = client_admin.get(_url(evenement, ("2026-09-30T18:00", "2026-09-30T20:00"), niveau="site"))
    analyse = reponse.context["analyse"]
    assert analyse.creneaux == [(datetime(2026, 9, 30, 18), datetime(2026, 9, 30, 20))]  # pas ceux mémorisés
    html = reponse.content.decode()
    assert 'value="2026-09-30T18:00"' in html
    # Décalages : même période une semaine plus tôt, niveau conservé ; onglets de niveau gardent la période.
    assert "debut=2026-09-23T18%3A00&amp;fin=2026-09-23T20%3A00&amp;niveau=site" in html
    assert "?debut=2026-09-30T18%3A00&amp;fin=2026-09-30T20%3A00&amp;niveau=secteur" in html
    assert DemandeSuivie.objects.get().parametres["creneaux"] == [["2026-09-30T18:00:00", "2026-09-30T20:00:00"]]


def test_periode_memorisee_par_defaut(client_admin, evenement, source):  # noqa: F811
    analyse = client_admin.get(reverse("evenements:detail", args=[evenement.pk])).context["analyse"]
    assert [d.day for d, _ in analyse.creneaux] == [29, 30]


def test_periode_invalide(client_admin, evenement, source):  # noqa: F811
    reponse = client_admin.get(_url(evenement, ("2026-09-30T18:00", "2026-09-30T17:00")))
    assert reponse.status_code == 200 and "analyse" not in reponse.context
    assert "la fin doit suivre le début" in reponse.content.decode()


def test_memoriser_la_periode(client, evenement):  # noqa: F811
    lecteur = User.objects.create_user("lecteur")
    lecteur.groups.add(Group.objects.create(name="Analyste"))  # tout le réseau
    client.force_login(lecteur)
    url = reverse("evenements:memoriser_periode", args=[evenement.pk])
    donnees = {"debut": ["2027-09-28T18:00"], "fin": ["2027-09-28T22:00"]}
    assert client.post(url, donnees).status_code == 403
    lecteur.user_permissions.add(Permission.objects.get(codename="change_evenement"))
    reponse = client.post(url, donnees)
    assert reponse.status_code == 302 and "debut=2027-09-28T18%3A00" in reponse["Location"]
    creneau = Creneau.objects.get(evenement=evenement)
    assert timezone.localtime(creneau.debut).replace(tzinfo=None) == datetime(2027, 9, 28, 18)


def test_rapport_suit_la_periode(client_admin, evenement, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.rapports.views.lancer", lambda rapport, parent=None: True)
    client_admin.post(reverse("rapports:evenement", args=[evenement.pk]), {
        "niveau": "secteur", "format": "pdf", "debut": ["2026-09-30T18:00"], "fin": ["2026-09-30T20:00"]})
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
