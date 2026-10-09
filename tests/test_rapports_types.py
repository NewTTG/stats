"""Rapports types (bilan complet, trafic, data 4G, qualité, utilisateurs) : vocabulaire, accueil,
résultat par thème ; séparation de l'espace d'administration dans l'application."""

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import JournalAudit
from apps.kpi.recherche.regles import interpreter
from apps.kpi.recherche.vocabulaire import vocabulaire
from apps.kpi.source import moteur_kpi
from apps.rapports.models import RapportPlanifie

from .test_recherche_regles import J, ctx, ref_recherche  # noqa: F401  (fixtures)
from .test_recherche_vues import _html, admin, base_recherche  # noqa: F401

pytestmark = pytest.mark.django_db

BILAN_3G = ["wcdma_appels_voix", "wcdma_sms", "wcdma_cssr_cs", "wcdma_cssr_ps", "wcdma_cs_drop", "wcdma_ps_drop"]
BILAN_4G = ["lte_csfb_appels", "lte_payload_dl", "lte_rrc_conn_max", "lte_dl_user_thp", "lte_prb_dl_util",
            "lte_acces", "lte_erab_drop"]


def _kpis(texte, contexte):
    i = interpreter(texte, J, contexte)
    return i.demande.intentions, i.params.get("kpis")


# ------------------------------------------------------------------ vocabulaire


def test_rapports_types_dans_l_ordre():
    assert [i.code for i in vocabulaire().rapports] == ["bilan", "rapport_trafic", "rapport_data",
                                                        "rapport_qualite", "utilisateurs"]
    assert vocabulaire().intentions["rapport_trafic"].rapport.titre == "Trafic"


def test_bilan_en_un_mot(ctx):  # noqa: F811
    intentions, kpis = _kpis("bilan Nouméa semaine dernière", ctx)
    assert intentions == ["bilan"] and kpis == BILAN_3G + BILAN_4G
    assert _kpis("rapport Païta hier", ctx)[0] == ["bilan"]
    assert _kpis("stats habituelles à Koné hier", ctx)[0] == ["bilan"]
    # Techno citée : le bilan de cette techno seulement.
    assert _kpis("Bilan 4G Koné hier", ctx)[1] == BILAN_4G


def test_mot_generique_cede_a_l_indicateur_cite(ctx):  # noqa: F811
    assert _kpis("bilan des coupures à Nouméa hier", ctx)[0] == ["drop"]
    assert _kpis("qualité du débit à Koné hier", ctx)[0] == ["debit"]
    assert _kpis("les utilisateurs se plaignent de coupures à Koné hier", ctx)[0] == ["drop"]
    # « par rapport à » reste une comparaison, pas un rapport type.
    assert _kpis("drop Nouméa par rapport à Païta hier", ctx)[0] == ["drop"]


def test_autres_rapports_types(ctx):  # noqa: F811
    assert _kpis("rapport trafic Lifou ce mois-ci", ctx) == (
        ["rapport_trafic"], ["wcdma_appels_voix", "wcdma_sms", "lte_csfb_appels", "lte_payload_dl"])
    assert _kpis("voix, SMS et data à Nouméa hier", ctx)[0] == ["rapport_trafic"]
    assert _kpis("bilan data 4G à Dumbéa hier", ctx) == (
        ["rapport_data"], ["lte_payload_dl", "lte_dl_user_thp", "lte_prb_dl_util", "lte_rrc_conn_max"])
    assert _kpis("qualité à Koné hier", ctx) == (
        ["rapport_qualite"], ["lte_acces", "lte_erab_drop", "wcdma_cssr_cs", "wcdma_cssr_ps", "wcdma_cs_drop",
                              "wcdma_ps_drop"])
    assert _kpis("QoS 3G Païta hier", ctx)[1] == ["wcdma_cssr_cs", "wcdma_cssr_ps", "wcdma_cs_drop", "wcdma_ps_drop"]


def test_utilisateurs_connectes(ctx):  # noqa: F811
    for texte in ("nombre d'utilisateurs à Koumac hier", "utilisateurs connectés à Koné hier", "RRC conn max Nouméa hier",
                  "utilisateurs Nouméa hier", "affluence à Nouméa hier"):
        assert _kpis(texte, ctx) == (["utilisateurs"], ["lte_rrc_conn_max"]), texte
    # « débit utilisateur » reste un débit.
    assert _kpis("débit utilisateur 4G à Koné hier", ctx)[0] == ["debit"]


# ------------------------------------------------------------------ accueil et résultat


def test_accueil_rapports_types_lieu_periode(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/"))
    for titre in ("Bilan complet", "Trafic", "Data 4G", "Qualité de service", "Utilisateurs 4G", "Sur mesure"):
        assert f"<strong>{titre}</strong>" in html, titre
    assert 'name="intention" value="bilan" checked' in html and 'name="intention" value=""' in html
    assert 'id="lieu" name="q" list="lieux-accueil"' in html and '<option value="Nouméa">Commune</option>' in html
    assert '<option value="Province Nord">Région</option>' in html
    assert 'name="periode" value="7j" checked' in html and 'value="dates"' in html


def test_rapport_type_depuis_l_accueil(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "Nouméa", "intention": "bilan", "periode": "semaine_derniere"}))
    assert "<h1>Bilan complet — Nouméa</h1>" in html
    assert "Semaine dernière · 28/09 → 04/10/2026 · par jour" in html
    # Synthèse : cartes des deux technos regroupées par thème, techno en pastille.
    for theme in ("<h3>Trafic</h3>", "<h3>Débit et charge</h3>", "<h3>Accès</h3>", "<h3>Coupures</h3>"):
        assert theme in html, theme
    assert html.index("<h3>Trafic</h3>") < html.index("<h3>Accès</h3>") < html.index("<h3>Coupures</h3>")
    assert '<span>Taux de coupure appels voix</span> <span class="badge-techno petit WCDMA">3G</span>' in html
    assert 'href="#bloc-WCDMA"' in html and 'id="bloc-LTE"' in html
    assert "Enregistrer ce rapport" in html and "Rapport PowerPoint" in html
    trace = JournalAudit.objects.get(action="recherche_kpi").requete
    assert trace["libelle"] == "Bilan complet · Nouméa · Semaine dernière"
    assert trace["parametres"] == {"intention": ["bilan"], "periode": "semaine_derniere"}


def test_rapport_type_sur_tout_le_reseau(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "", "intention": "rapport_trafic", "periode": "hier"}))
    assert "<h1>Trafic voix, SMS et data — Tout le réseau autorisé</h1>" in html
    assert "<h3>Trafic</h3>" in html and "<h3>Accès</h3>" not in html


def test_sur_mesure_et_dates_precises(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "Païta", "kpis": ["lte_dl_user_thp", "lte_prb_dl_util"],
                                 "periode": "dates", "debut": "2026-10-01", "fin": "2026-10-03"}))
    assert "<h1>Débit DL utilisateur moyen, Utilisation PRB DL — Païta</h1>" in html
    assert "01/10 → 03/10/2026" in html and "<h3>Débit et charge</h3>" in html


def test_puce_indicateurs_propose_les_rapports_types(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "drop 3G à Nouméa hier"}))
    assert '<h3>Rapports types</h3>' in html and 'name="intention" value="bilan">Bilan complet</button>' in html


def test_rapport_enregistre_affichable(admin, base_recherche):  # noqa: F811
    plan = RapportPlanifie.objects.create(
        utilisateur=User.objects.get(username="admin"), titre="Bilan hebdo Nouméa", periode="semaine_derniere",
        requete={"techno": ["WCDMA"], "perimetre": {"type": "commune", "valeurs": ["NOUMEA"]},
                 "granularite_temps": "jour", "granularite_espace": "global", "fenetre_horaire": "journee",
                 "kpis": ["wcdma_cs_drop"]})
    lien = plan.lien_ecran()
    assert lien.startswith("/?q=&kpis=wcdma_cs_drop&periode=semaine_derniere&perimetre_type=commune")
    assert "Bilan hebdo Nouméa" in _html(admin.get("/")) and "Afficher" in _html(admin.get("/rapports/"))
    html = _html(admin.get(lien))
    assert "Semaine dernière · 28/09 → 04/10/2026" in html and "Synthèse sur la période" in html
    plan.requete = {"kpis": "rien"}
    assert plan.lien_ecran() is None


# ------------------------------------------------------------------ espace d'administration à part


def test_visiteur_sans_administration(client):
    html = _html(client.get("/"))
    assert 'class="lien-admin"' not in html and "/admin/" not in html
    assert "Accès administrateur" in html and 'href="/connexion/"' in html


def test_administrateur_lien_a_part(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/"))
    assert 'class="lien-admin" href="/admin/"' in html
    navigation = html[html.index('<ul class="navigation">'):html.index("</ul>", html.index('<ul class="navigation">'))]
    assert "/admin/" not in navigation  # pas dans la navigation des statistiques


def test_details_techniques_reserves_a_l_administrateur(client, base_recherche, settings, tmp_path):  # noqa: F811
    assert "charger_demo_kpi" not in _html(client.get("/"))  # visiteur : bandeau sans commande
    settings.KPI_DEMO_SQLITE = tmp_path / "absente.sqlite3"
    moteur_kpi.cache_clear()
    html = _html(client.get("/", {"q": "drop 4G Païta hier"}))
    assert "momentanément indisponibles" in html and "charger_demo_kpi" not in html and "KPI_DB" not in html
