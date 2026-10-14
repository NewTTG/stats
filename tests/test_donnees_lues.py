"""Choix des données lues (table horaire ou journalière) : requête, accueil, puces et rapports."""

import pytest
from pydantic import ValidationError

from apps.kpi.forms import champs_depuis_requete
from apps.kpi.requete import RequeteKpi

from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixtures)
from .test_recherche_vues import _html, admin, base_recherche  # noqa: F401

pytestmark = pytest.mark.django_db

BASE = {
    "techno": ["LTE"],
    "perimetre": {"type": "global"},
    "periode": {"debut": "2026-10-01", "fin": "2026-10-07"},
    "granularite_temps": "jour",
    "kpis": ["lte_dl_user_thp"],
}


@pytest.mark.parametrize("modif, resolution", [
    ({}, "jour"),
    ({"granularite_temps": "heure"}, "heure"),
    ({"fenetre_horaire": "18-22"}, "heure"),
    ({"donnees": "heure"}, "heure"),  # données horaires, un point par jour
    ({"donnees": "heure", "granularite_temps": "semaine"}, "heure"),
    ({"donnees": "jour"}, "jour"),
])
def test_resolution_de_la_requete(modif, resolution):
    assert RequeteKpi(**{**BASE, **modif}).resolution == resolution


@pytest.mark.parametrize("modif", [
    {"granularite_temps": "heure"},
    {"fenetre_horaire": "18-22"},
    {"heures": ["2026-10-02T10:00:00"]},
])
def test_donnees_journalieres_sans_heures(modif):
    with pytest.raises(ValidationError):
        RequeteKpi(**{**BASE, **modif, "donnees": "jour"})


def test_champs_du_formulaire_conservent_les_donnees():
    req = RequeteKpi(**{**BASE, "donnees": "heure"})
    assert champs_depuis_requete(req)["donnees"] == "heure"
    assert "donnees" not in champs_depuis_requete(RequeteKpi(**BASE))


def _params(client, **get):
    r = client.get("/", {"q": "", "intention": "bilan", **get})
    assert r.status_code == 200
    return r.context["interp"]


def test_accueil_propose_les_donnees(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/"))
    assert 'name="donnees" value="jour"' in html and 'name="donnees" value="heure"' in html
    assert "checked" not in html.split('name="donnees" value="jour"')[1].split(">")[0]  # automatique sans JS
    assert '<details class="options-affichage">' in html


def test_donnees_horaires_sur_une_semaine(admin, base_recherche):  # noqa: F811
    interp = _params(admin, periode="7j", donnees="heure")
    assert interp.params["donnees"] == "heure" and interp.params["granularite_temps"] == "heure"
    assert interp.puce("donnees").libelle == "horaires" and not interp.puce("donnees").defaut
    # Un détail choisi reste celui demandé, calculé sur les données horaires.
    interp = _params(admin, periode="7j", donnees="heure", granularite_temps="jour")
    assert interp.params["granularite_temps"] == "jour"
    assert RequeteKpi(**interp.params).resolution == "heure"


def test_donnees_journalieres_sur_un_jour(admin, base_recherche):  # noqa: F811
    interp = _params(admin, periode="hier", donnees="jour")
    assert interp.params["granularite_temps"] == "jour" and interp.params["donnees"] == "jour"
    assert RequeteKpi(**interp.params).resolution == "jour"
    # Automatique : un seul jour se lit heure par heure.
    interp = _params(admin, periode="hier")
    assert "donnees" not in interp.params and interp.puce("donnees").libelle == "horaires"
    assert interp.puce("donnees").defaut


def test_plage_horaire_l_emporte_sur_les_donnees_journalieres(admin, base_recherche):  # noqa: F811
    interp = _params(admin, periode="7j", donnees="jour", fenetre_horaire="18-22")
    assert interp.params["donnees"] == "heure"
    assert any("données horaires utilisées" in n for n in interp.notes)
    RequeteKpi(**interp.params)


def test_puce_donnees_remet_a_zero_les_heures(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "", "intention": "bilan", "periode": "7j", "fenetre_horaire": "18-22"}))
    debut = html.index('<span class="puce-champ">Données</span>')
    panneau = html[debut:html.index("</details>", debut)]
    assert 'name="fenetre_horaire"' not in panneau and 'name="granularite_temps"' not in panneau
    assert 'name="donnees" value="heure" checked' in panneau
