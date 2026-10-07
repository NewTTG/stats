"""Exécution de requêtes sur une base KPI simulée (SQLite) et contrôle d'accès."""

from datetime import date, datetime

import pandas as pd
import pytest
import sqlalchemy as sa
from django.contrib.auth.models import Group, User

from apps.comptes.models import Perimetre
from apps.kpi.requete import RequeteKpi
from apps.kpi.service import RequeteRefusee, executer
from apps.referentiel.models import Cellule, Secteur, Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def referentiel():
    for code, trig, commune in [("AAA100", "AAA", "NOUMEA"), ("BBB200", "BBB", "PAITA")]:
        site = Site.objects.create(code_site=code, trigramme=trig, nom=f"SITE_{trig}", commune=commune)
        for n in (1, 2):
            sect = Secteur.objects.create(code=f"{code}{n}", site=site, numero=n)
            Cellule.objects.create(nom=f"{trig}e{n}", techno="LTE", secteur=sect, porteuse=1)
    Cellule.objects.create(nom="ORPHe1", techno="LTE")  # cellule non rattachée


@pytest.fixture
def base_kpi():
    """Deux jours horaires (0h et 19h) pour 4 cellules ; BBBe2 sans données."""
    lignes = []
    for jour in (1, 2):
        for heure in (0, 19):
            for cell, att, succ in [("AAAe1", 100, 99), ("AAAe2", 1000, 900), ("BBBe1", 10, 10), ("ORPHe1", 50, 50)]:
                lignes.append({"EutranCell_Id": cell, "DateHour": datetime(2026, 9, jour, heure),
                               "pmRrcConnEstabAtt": att, "pmRrcConnEstabSucc": succ, "PayloadDl_mB": 10.0})
    horaire = pd.DataFrame(lignes)
    journalier = (horaire.assign(DateDay=horaire["DateHour"].dt.date)
                  .groupby(["EutranCell_Id", "DateDay"], as_index=False)
                  [["pmRrcConnEstabAtt", "pmRrcConnEstabSucc", "PayloadDl_mB"]].sum())
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    horaire.to_sql("lte_cell_hour", engine, index=False)
    journalier.to_sql("lte_cell_day", engine, index=False)
    return engine


def requete(**modifs):
    base = {
        "techno": ["LTE"],
        "perimetre": {"type": "global"},
        "periode": {"debut": date(2026, 9, 1), "fin": date(2026, 9, 2)},
        "granularite_temps": "jour",
        "granularite_espace": "global",
        "kpis": ["lte_rrc_setup_sr", "lte_payload_dl"],
    }
    return RequeteKpi(**{**base, **modifs})


@pytest.fixture
def analyste():
    u = User.objects.create_user("ana")
    u.groups.add(Group.objects.create(name="Analyste"))
    return u


@pytest.fixture
def lecteur_paita():
    u = User.objects.create_user("lec")
    p = Perimetre.objects.create(nom="Paita", communes=["PAITA"], kpis_autorises=["lte_rrc_setup_sr"])
    p.utilisateurs.add(u)
    return u


def test_global_ratio_de_sommes(referentiel, base_kpi, analyste):
    res = executer(requete(), analyste, base_kpi).par_techno[0]
    jour1 = res.table.loc[(pd.Timestamp("2026-09-01"), "Global")]
    assert jour1["lte_rrc_setup_sr"] == pytest.approx((99 + 900 + 10 + 50) * 2 / ((100 + 1000 + 10 + 50) * 2) * 100)
    assert jour1["lte_payload_dl"] == pytest.approx(80.0)


def test_fenetre_horaire_et_commune(referentiel, base_kpi, analyste):
    req = requete(perimetre={"type": "commune", "valeurs": ["noumea"]}, fenetre_horaire="18-22",
                  granularite_espace="site")
    res = executer(req, analyste, base_kpi).par_techno[0]
    ligne = res.table.loc[(pd.Timestamp("2026-09-01"), "SITE_AAA")]
    assert ligne["lte_payload_dl"] == pytest.approx(20.0)  # 2 cellules × l'heure 19h seulement
    assert ligne["lte_rrc_setup_sr"] == pytest.approx(999 / 1100 * 100)


def test_cellules_sans_donnees_signalees(referentiel, base_kpi, analyste):
    req = requete(perimetre={"type": "commune", "valeurs": ["PAITA"]})
    res = executer(req, analyste, base_kpi).par_techno[0]
    assert res.cellules_sans_donnees == ["BBBe2"]


def test_cellule_non_rattachee(referentiel, base_kpi, analyste):
    res = executer(requete(granularite_espace="commune"), analyste, base_kpi).par_techno[0]
    entites = set(res.table.index.get_level_values("entite"))
    assert entites == {"NOUMEA", "PAITA", "(non rattachée)"}


def test_granularite_heure_lit_la_table_horaire(referentiel, base_kpi, analyste):
    res = executer(requete(granularite_temps="heure"), analyste, base_kpi).par_techno[0]
    assert len(res.table) == 4


def test_lecteur_restreint_ne_voit_que_son_perimetre(referentiel, base_kpi, lecteur_paita):
    # Requête forgée sur tout le réseau puis sur une cellule hors périmètre.
    res = executer(requete(granularite_espace="cellule"), lecteur_paita, base_kpi)
    cellules = set(res.par_techno[0].table.index.get_level_values("entite"))
    assert cellules == {"BBBe1"}
    assert [k.code for k in res.par_techno[0].kpis] == ["lte_rrc_setup_sr"]
    assert any("non autorisés" in a for a in res.avertissements)

    res = executer(requete(perimetre={"type": "cellule", "valeurs": ["AAAe1"]}), lecteur_paita, base_kpi)
    assert res.par_techno == []
    assert any("aucune cellule accessible" in a for a in res.avertissements)


def test_utilisateur_sans_perimetre_ne_voit_rien(referentiel, base_kpi):
    u = User.objects.create_user("vide")
    res = executer(requete(), u, base_kpi)
    assert res.par_techno == []


def test_fonctions_non_disponibles(referentiel, base_kpi, analyste):
    with pytest.raises(RequeteRefusee):
        executer(requete(fenetre_horaire="heure_chargee"), analyste, base_kpi)
    with pytest.raises(RequeteRefusee):
        executer(requete(perimetre={"type": "evenement", "valeurs": ["x"]}), analyste, base_kpi)
