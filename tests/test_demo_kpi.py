"""Base KPI de démonstration : génération sur un petit échantillon des extraits CSV,
lecture par ``source.lire`` (SQL inchangé) et requête de bout en bout via ``executer``."""

import sqlite3
from datetime import date

import pandas as pd
import pytest
import sqlalchemy as sa
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command

from apps.kpi.catalogue import catalogue_yaml
from apps.kpi.management.commands.charger_demo_kpi import TECHNOS, generer
from apps.kpi.requete import RequeteKpi
from apps.kpi.service import colonnes_utilisees, executer
from apps.kpi.source import BaseKpiNonConfiguree, est_demo, lire, moteur_kpi

pytestmark = pytest.mark.django_db

FIN = date(2026, 9, 30)
JOURS = 3


@pytest.fixture(scope="module")
def extraits(tmp_path_factory):
    """Les 30 premières lignes de chacun des 4 extraits CSV (même format)."""
    dossier = tmp_path_factory.mktemp("csv")
    for t in TECHNOS.values():
        for nom in (t.csv_heure, t.csv_jour):
            pd.read_csv(django_settings.BASE_DIR / nom, sep=";", nrows=30, dtype=str).to_csv(
                dossier / nom, sep=";", index=False)
    return dossier


@pytest.fixture
def demo(extraits, tmp_path):
    sortie = tmp_path / "demo.sqlite3"
    resume = generer(sortie, jours=JOURS, graine=7, fin=FIN, dossier=extraits, journal=lambda m: None)
    return sortie, resume


@pytest.fixture
def base_demo(demo, settings):
    """L'application lit la base de démonstration (pas de KPI_DB_HOST)."""
    settings.KPI_DB = {**settings.KPI_DB, "host": ""}
    settings.KPI_DEMO_SQLITE = demo[0]
    moteur_kpi.cache_clear()
    yield moteur_kpi()
    moteur_kpi.cache_clear()


def _df(chemin, sql):
    with sqlite3.connect(chemin) as conn:
        return pd.read_sql_query(sql, conn)


def test_tables_colonnes_et_horodatages(demo):
    chemin, resume = demo
    cat = list(catalogue_yaml().values())
    for t in TECHNOS.values():
        attendues = set(colonnes_utilisees([k for k in cat if k.techno == t.nom]))
        h = _df(chemin, f'SELECT * FROM "{t.table_heure}"')
        j = _df(chemin, f'SELECT * FROM "{t.table_jour}"')
        assert set(h.columns) == {t.cle, t.site, t.zone, "DateHour"} | attendues
        assert set(j.columns) == {t.cle, t.site, t.zone, "DateDay"} | attendues
        n = h[t.cle].nunique()
        assert len(h) == n * 24 * JOURS and len(j) == n * JOURS
        assert h["DateHour"].min() == "2026-09-28 00:00:00" and h["DateHour"].max() == "2026-09-30 23:00:00"
        assert sorted(j["DateDay"].unique()) == ["2026-09-28", "2026-09-29", "2026-09-30"]
        assert resume["lignes"][t.table_heure] == len(h)


def test_coherence_des_compteurs_et_des_taux(demo):
    chemin, _ = demo
    lte = _df(chemin, "SELECT * FROM lte_cell_hour")
    assert (lte.pmRrcConnEstabSucc <= lte.pmRrcConnEstabAtt).all()
    assert (lte.ErabEstabSucc_nb <= lte.pmErabEstabAttInit).all()
    causes = [c for c in lte.columns if c.startswith("ErabDropEnb")]
    total = lte[causes].sum(axis=1) + lte.ErabDropRateMme_p
    assert (lte.ErabDropRate_p - total).abs().max() < 1e-4  # causes LTE = total exactement
    for c in [c for c in lte.columns if c.endswith("_p")]:
        assert lte[c].between(0, 100).all(), c

    w = _df(chemin, "SELECT * FROM wcdma_cell_hour")
    assert (w.NbrSpeechCalls <= w.NbrSpeechCallsAtt).all() and (w.ReqCsSucc <= w.ReqCs).all()
    causes = [c for c in w.columns if c.startswith("RabDropCs") and c != "RabDropCs_p"]
    assert (w[causes].sum(axis=1) <= w.RabDropCs_p + 1e-4).all()  # causes 3G <= total

    # Profil horaire : plus de trafic à 19 h qu'à 3 h.
    par_heure = lte.groupby(lte.DateHour.str[11:13]).PayloadDl_mB.sum()
    assert par_heure["19"] > 3 * par_heure["03"]


def test_journalier_agrege_l_horaire(demo):
    chemin, _ = demo
    h = _df(chemin, "SELECT * FROM lte_cell_hour")
    j = _df(chemin, "SELECT * FROM lte_cell_day").set_index(["EutranCell_Id", "DateDay"]).sort_index()
    h["DateDay"] = h.DateHour.str[:10]
    sommes = h.groupby(["EutranCell_Id", "DateDay"])[["PayloadDl_mB", "pmRrcConnEstabAtt"]].sum()
    pd.testing.assert_frame_equal(sommes, j[["PayloadDl_mB", "pmRrcConnEstabAtt"]], check_dtype=False, atol=1e-3)
    # Taux de coupure journalier = moyenne pondérée par les E-RAB établis.
    h["k"] = h.ErabDropRate_p * h.ErabEstabSucc_nb
    g = h.groupby(["EutranCell_Id", "DateDay"])
    pondere = (g.k.sum() / g.ErabEstabSucc_nb.sum()).fillna(0)
    assert (pondere - j.ErabDropRate_p.reindex(pondere.index)).abs().max() < 1e-3


def test_generation_deterministe_et_incidents(extraits, demo, tmp_path):
    chemin, resume = demo
    autre = tmp_path / "autre.sqlite3"
    generer(autre, jours=JOURS, graine=7, fin=FIN, dossier=extraits, journal=lambda m: None)
    sql = "SELECT * FROM wcdma_cell_hour ORDER BY CellWcdma, DateHour"
    pd.testing.assert_frame_equal(_df(chemin, sql), _df(autre, sql))

    assert any("coupé" in i for i in resume["incidents"])
    infos = dict(_df(chemin, "SELECT cle, valeur FROM demo_info").values)
    assert infos["graine"] == "7" and infos["fin"] == "2026-09-30"
    h = _df(chemin, "SELECT * FROM lte_cell_hour")
    coupees = h[h.CellAvaibilityD_p == 0]
    assert len(coupees) >= 6 and (coupees.PayloadDl_mB == 0).all()


def test_lire_sql_inchange_sur_sqlite(base_demo):
    debut = fin = date(2026, 9, 29)
    cellules = [r[0] for r in sqlite3.connect(django_settings.KPI_DEMO_SQLITE).execute(
        "SELECT DISTINCT EutranCell_Id FROM lte_cell_day ORDER BY 1 LIMIT 2")]
    df = lire(base_demo, "LTE", "heure", ["PayloadDl_mB", "pmRrcConnEstabAtt"], debut, fin, cellules)
    assert len(df) == 2 * 24 and set(df["cellule"]) == set(cellules)
    assert str(df["horodatage"].dtype).startswith("datetime64")
    assert df["horodatage"].min() == pd.Timestamp("2026-09-29 00:00")
    df = lire(base_demo, "WCDMA", "jour", ["ReqSms"], date(2026, 9, 28), FIN, None)
    assert sorted(df["horodatage"].dt.day.unique()) == [28, 29, 30]


def test_requete_de_bout_en_bout(base_demo):
    assert est_demo()
    admin = User.objects.create_superuser("demo")
    req = RequeteKpi(techno=["LTE", "WCDMA"], perimetre={"type": "global"},
                     periode={"debut": date(2026, 9, 28), "fin": FIN}, granularite_temps="jour",
                     kpis=["lte_erab_drop", "lte_drop_mme", "lte_drop_radio", "lte_payload_dl", "lte_acces",
                           "wcdma_cs_drop", "wcdma_sms"])
    res = executer(req, admin, base_demo)
    lte, wcdma = res.par_techno
    assert len(lte.table) == 3 and len(wcdma.table) == 3
    g = lte.synthese_globale
    assert 0 < g["lte_erab_drop"] < 100 and 90 < g["lte_acces"] <= 100 and g["lte_payload_dl"] > 0
    assert g["lte_drop_mme"] + g["lte_drop_radio"] <= g["lte_erab_drop"] + 1e-9
    assert wcdma.synthese_globale["wcdma_sms"] > 0

    # Lecture horaire avec fenêtre (table horaire).
    req = req.model_copy(update={"fenetre_horaire": "18-22", "granularite_temps": "heure"})
    res = executer(req, admin, base_demo)
    heures = {p.hour for p in res.par_techno[0].table.index.get_level_values("periode")}
    assert heures == {18, 19, 20, 21}


def test_sans_base_ni_demo(settings, tmp_path):
    settings.KPI_DB = {**settings.KPI_DB, "host": ""}
    settings.KPI_DEMO_SQLITE = tmp_path / "absente.sqlite3"
    moteur_kpi.cache_clear()
    assert not est_demo()
    with pytest.raises(BaseKpiNonConfiguree, match="charger_demo_kpi"):
        moteur_kpi()
    moteur_kpi.cache_clear()


def test_base_postgresql_prioritaire(settings, demo):
    settings.KPI_DB = {**settings.KPI_DB, "host": "kpi.exemple", "name": "kpi", "user": "lecteur"}
    settings.KPI_DEMO_SQLITE = demo[0]
    moteur_kpi.cache_clear()
    assert not est_demo()
    assert moteur_kpi().dialect.name == "postgresql"
    moteur_kpi.cache_clear()


def test_commande(extraits, tmp_path):
    sortie = tmp_path / "commande.sqlite3"
    call_command("charger_demo_kpi", "--jours", "2", "--sortie", str(sortie), "--csv", str(extraits),
                 "--fin", "2026-09-30", stdout=open(tmp_path / "sortie.txt", "w"))
    engine = sa.create_engine(f"sqlite:///{sortie}")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(DISTINCT DateDay) FROM lte_cell_day")).scalar() == 2
    assert "Incidents simulés" in (tmp_path / "sortie.txt").read_text()
