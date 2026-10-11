"""Nouvelle interface : aperçu du réseau de l'accueil (/apercu/) et rapports PDF
(export direct depuis un résultat, rapports de requête et d'événement en tâche de fond)."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User

from apps.comptes.models import JournalAudit, Perimetre
from apps.evenements.analyse import analyser
from apps.kpi.catalogue import catalogue
from apps.kpi.service import executer
from apps.kpi.source import moteur_kpi
from apps.kpi.tableau_de_bord import date_longue, etincelle, variation
from apps.rapports.models import Rapport
from apps.rapports.pdf import pdf_evenement, pdf_requete, texte

from .test_evenements import base_horaire, evenement  # noqa: F401  (fixtures)
from .test_rapports import client_analyste, worker  # noqa: F401
from .test_recherche_regles import J, ref_recherche  # noqa: F401
from .test_recherche_vues import _html, admin, base_recherche  # noqa: F401
from .test_service import analyste, base_kpi, referentiel, requete  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def sans_cache(settings):
    settings.APERCU_CACHE_SECONDES = 0


def _pages(octets: bytes) -> int:
    return octets.count(b"/Type /Page\n") + octets.count(b"/Type /Page ") + octets.count(b"/Type /Page>")


# ------------------------------------------------------------------ accueil

def test_accueil_barre_rapports_et_apercu(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/"))
    assert "Bonjour, admin" in html or "Bonsoir, admin" in html
    assert 'placeholder="Comment puis-je vous aider aujourd' in html
    assert 'href="?q=&amp;intention=bilan&amp;periode=hier"' in html  # rapport affiché en un clic
    assert 'data-url="/apercu/"' in html and 'data-jour="aujourdhui"' in html
    assert 'id="composer"' in html and 'id="constructeur"' in html  # tiroir « Composer un rapport »


def test_apercu_hier(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/apercu/", {"jour": "hier"}))
    hier = J - timedelta(days=1)
    assert f"Tout le réseau · {date_longue(hier)}" in html
    for libelle in ("Volume data 4G", "Appels voix 3G", "Taux d&#x27;accès 4G", "Coupures voix 3G"):
        assert libelle in html, libelle
    assert "vs veille" in html and 'class="etincelle' in html and 'id="donnees-apercu"' in html
    assert "Coupures 4G par site" in html and "Trafic data 4G heure par heure" in html
    # Tuile : détail heure par heure du jour affiché ; bilan complet de la journée.
    assert f"kpis=lte_payload_dl&amp;debut={hier}&amp;fin={hier}&amp;granularite_temps=heure" in html
    assert f"intention=bilan&amp;debut={hier}&amp;fin={hier}" in html


def test_apercu_aujourdhui_sans_donnees(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/apercu/", {"jour": "aujourdhui"}))  # démo arrêtée la veille de J
    assert "pas encore chargées" in html and 'data-jour="hier"' in html


def test_apercu_aujourdhui_avec_donnees(admin, base_recherche, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.kpi.views.timezone.localdate", lambda: date(2026, 10, 7))
    html = _html(admin.get("/apercu/", {"jour": "aujourdhui"}))
    assert "hui, de 0 h à 24 h" in html and "vs hier" in html


def test_apercu_demo_ancienne_dernier_jour(admin, base_recherche, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.kpi.views.timezone.localdate", lambda: J + timedelta(days=5))
    html = _html(admin.get("/apercu/"))
    assert date_longue(date(2026, 10, 7)) in html  # dernier jour de la démonstration


def test_apercu_lecteur_restreint(client, base_recherche):  # noqa: F811
    lecteur = User.objects.create_user("lec_apercu")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"], kpis_autorises=["lte_erab_drop"]).utilisateurs.add(lecteur)
    client.force_login(lecteur)
    html = _html(client.get("/apercu/"))
    assert "Votre périmètre" in html and "Coupures data 4G" in html
    assert "Volume data 4G" not in html and "Appels voix 3G" not in html


def test_apercu_sans_indicateur(client, base_recherche):  # noqa: F811
    lecteur = User.objects.create_user("lec_vide")
    Perimetre.objects.create(nom="Païta", communes=["PAITA"], kpis_autorises=["lte_ul_user_thp"]).utilisateurs.add(lecteur)
    client.force_login(lecteur)
    assert "Aucun indicateur de l&#x27;aperçu" in _html(client.get("/apercu/"))


def test_apercu_base_indisponible(client, base_recherche, settings, tmp_path):  # noqa: F811
    from django.contrib.auth.models import Group

    analyste_ = User.objects.create_user("lec_base")
    analyste_.groups.add(Group.objects.get_or_create(name="Analyste")[0])
    client.force_login(analyste_)
    settings.KPI_DEMO_SQLITE = tmp_path / "absente.sqlite3"
    moteur_kpi.cache_clear()
    html = _html(client.get("/apercu/"))
    assert "momentanément indisponibles" in html and "KPI_DB" not in html


def test_apercu_mis_en_cache(admin, base_recherche, settings, monkeypatch):  # noqa: F811
    settings.APERCU_CACHE_SECONDES = 60
    from django.core.cache import cache

    cache.clear()
    appels = []
    import apps.kpi.tableau_de_bord as tdb

    original = tdb.calculer
    monkeypatch.setattr(tdb, "calculer", lambda *a: appels.append(a) or original(*a))
    admin.get("/apercu/")
    admin.get("/apercu/")
    assert len(appels) == 1
    cache.clear()


def test_variation_et_etincelle():
    cat = catalogue()
    drop, volume, debit = cat["lte_erab_drop"], cat["lte_payload_dl"], cat["lte_dl_user_thp"]
    assert variation(drop, 1.2, 1.0) == {"texte": "+0,20 pt", "sens": "mauvais", "fleche": "▲"}
    assert variation(debit, 9.0, 10.0) == {"texte": "−10,0 %", "sens": "mauvais", "fleche": "▼"}
    assert variation(volume, 110, 100)["sens"] == ""  # volume de trafic : neutre
    assert variation(volume, 100, None) is None and variation(volume, 100, 0) is None
    assert variation(drop, 1.0, 1.001)["texte"].startswith("=")
    trace = etincelle([1, None, 3, 2])
    assert trace["ligne"].startswith("M0.0,29.0") and trace["aire"].endswith("Z")
    assert etincelle([None, 5]) is None


# ------------------------------------------------------------------ PDF

def test_texte_pdf_jeu_de_caracteres():
    assert texte("≈ 1,2 → 3 · Σ x <b>") == "~ 1,2 – 3 · somme des x &lt;b&gt;"
    assert texte("Nouméa 12 450") == "Nouméa 12 450"


def test_pdf_requete(referentiel, base_kpi, analyste):  # noqa: F811
    octets = pdf_requete(executer(requete(granularite_espace="commune"), analyste, base_kpi), titre="Essai")
    assert octets.startswith(b"%PDF") and _pages(octets) >= 1


def test_pdf_evenement(evenement, base_horaire, analyste):  # noqa: F811
    octets = pdf_evenement(analyser(evenement, analyste, base_horaire, niveau="site"))
    assert octets.startswith(b"%PDF") and _pages(octets) >= 2


def test_export_pdf_depuis_un_resultat(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "causes de coupure 4G par site à Nouméa la semaine dernière"}))
    assert "Télécharger en PDF" in html and "export=pdf" in html
    r = admin.get("/", {"q": "causes de coupure 4G par site à Nouméa la semaine dernière", "export": "pdf"})
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r["Content-Disposition"].endswith('.pdf"') and r.content.startswith(b"%PDF")
    assert JournalAudit.objects.filter(action="export_pdf").exists()
    # L'export n'apparaît pas dans « Mes dernières recherches » en double.
    assert _html(admin.get("/")).count("causes de coupure 4G par site à Nouméa la semaine dernière") <= 2


def test_rapport_evenement_pdf(client_analyste, evenement, worker):  # noqa: F811
    client_analyste.post(f"/rapports/evenement/{evenement.pk}/", {"niveau": "site", "format": "pdf"})
    rapport = Rapport.objects.get()
    assert rapport.statut == "termine" and rapport.fichier.name.endswith(".pdf")
    assert JournalAudit.objects.filter(action="rapport_evenement_pdf").exists()
    r = client_analyste.get(f"/rapports/{rapport.pk}/telecharger/")
    assert b"".join(r.streaming_content).startswith(b"%PDF")


def test_rapport_requete_pdf(client_analyste, referentiel, base_kpi, worker, monkeypatch):  # noqa: F811
    monkeypatch.setattr("apps.rapports.taches.moteur_kpi", lambda: base_kpi)
    params = {"techno": "LTE", "perimetre_type": "commune", "perimetre_valeurs": "NOUMEA", "format": "pdf",
              "debut": "2026-09-01", "fin": "2026-09-02", "granularite_temps": "jour",
              "granularite_espace": "site", "fenetre_horaire": "journee", "kpis": ["lte_rrc_setup_sr"]}
    client_analyste.post("/rapports/requete/", params)
    rapport = Rapport.objects.get()
    assert (rapport.statut, rapport.format) == ("termine", "pdf") and rapport.fichier.name.endswith(".pdf")
    client_analyste.post("/rapports/requete/", {**params, "format": "docx"})  # format inconnu : refusé
    assert Rapport.objects.count() == 1


def test_enregistrer_propose_le_pdf(client_analyste, referentiel):  # noqa: F811
    html = _html(client_analyste.get("/rapports/enregistrer/", {
        "techno": "LTE", "perimetre_type": "global", "debut": "2026-09-01", "fin": "2026-09-02",
        "granularite_temps": "jour", "granularite_espace": "global", "fenetre_horaire": "journee",
        "kpis": ["lte_rrc_setup_sr"]}))
    assert 'name="format" value="pdf" checked' in html and 'value="pptx"' in html and 'value="xlsx"' in html
