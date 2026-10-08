"""Non-régression du contrôle indépendant (tour 4 du développement, constats « tour 5 ») :
classement « les plus chargés », oracle des noms de sites pour un lecteur restreint,
sigles indisponibles, mots capitalisés, rapprochements, granularités, messages, mobile,
écart significatif des taux de succès."""

import re

import pytest
from django.contrib.auth.models import User

from apps.kpi.recherche.regles import interpreter

from .test_controle_tour3 import ctx3, ref_t3  # noqa: F401  (fixtures)
from .test_recherche_regles import J, ref_recherche  # noqa: F401  (fixture)
from .test_recherche_vues import base_recherche  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def _nombre(texte: str) -> float:
    return float(re.sub(r"[\s  ]", "", texte).replace(",", "."))


def _classement(html: str, titre: str) -> list[float]:
    bloc = re.search(rf"{re.escape(titre)}</h3>(.*?)</table>", html, re.S)
    assert bloc, f"classement « {titre} » absent"
    return [_nombre(v) for v in re.findall(r'<td class="val">([\d\s  ,]+)', bloc[1])]


# ------------------------------------------------------------------ MAJEUR 1 : « les plus chargés »

def test_top_sites_les_plus_charges_interpretation(ctx3):  # noqa: F811
    i = interpreter("top 10 des sites les plus chargés en trafic data à Nouméa la semaine dernière", J, ctx3)
    assert i.complete and i.non_compris == []
    assert i.params["granularite_espace"] == "site" and i.params["kpis"] == ["lte_payload_dl", "wcdma_payload_hs"]
    assert i.demande.classement and i.demande.classement_nombre == 10


@pytest.mark.parametrize("phrase,niveau,nombre", [
    ("top 5 des pires secteurs en drop 4G à Nouméa hier", "secteur", 5),
    ("les 3 sites les plus chargés en appels à Koné hier", "site", 3),
    ("les 10 cellules 4G avec le pire débit montant à Païta hier", "cellule", 10),
    ("les sites avec le plus de trafic à Nouméa hier", "site", None),
])
def test_top_n_et_les_n(ctx3, phrase, niveau, nombre):  # noqa: F811
    i = interpreter(phrase, J, ctx3)
    assert i.params["granularite_espace"] == niveau and i.demande.classement
    assert i.demande.classement_nombre == nombre and i.non_compris == []


def test_vue_classement_les_plus_charges_decroissant(base_recherche, client):  # noqa: F811
    client.force_login(User.objects.create_superuser("admin4"))
    html = client.get("/", {"q": "top 10 des sites les plus chargés en trafic data à Nouméa la semaine dernière"}
                      ).content.decode()
    assert "Classement par site" in html and "Les plus dégradés — Volume" not in html
    valeurs = _classement(html, "Les plus chargés — Volume DL")
    assert 2 <= len(valeurs) <= 10 and valeurs == sorted(valeurs, reverse=True)
    html = client.get("/", {"q": "top 2 des sites les plus chargés en trafic data à Nouméa la semaine dernière"}
                      ).content.decode()
    valeurs = _classement(html, "Les plus chargés — Volume DL")
    assert len(valeurs) == 2 and valeurs[0] >= valeurs[1]
    # Qualité : toujours « les plus dégradés » ; durée moyenne d'appel : jamais classée.
    html = client.get("/", {"q": "drop 4G et durée moyenne des appels par site à Nouméa la semaine dernière"}
                      ).content.decode()
    assert "Les plus dégradés — Taux de coupure E-RAB" in html and "— Durée" not in html
