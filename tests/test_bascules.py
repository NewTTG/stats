"""Détection de la date de passage de 3 à 4 secteurs (manage.py detecter_bascules)."""

from datetime import date, timedelta

import pandas as pd
import pytest
import sqlalchemy as sa
from django.core.management import call_command

from apps.referentiel.management.commands.detecter_bascules import detecter
from apps.referentiel.models import Cellule, Secteur, Site

pytestmark = pytest.mark.django_db


def _site(code, trig, cellules):
    """``cellules`` : (nom, techno, secteur, secteur avant bascule)."""
    site = Site.objects.create(code_site=code, trigramme=trig, nom=code, commune="NOUMEA")
    for nom, techno, n, avant in cellules:
        secteurs = {k: Secteur.objects.get_or_create(code=f"{code}{k}", site=site, numero=k)[0] for k in (n, avant) if k}
        Cellule.objects.create(nom=nom, techno=techno, secteur=secteurs[n], secteur_avant=secteurs.get(avant))
    return site


@pytest.fixture
def engine():
    """MDO : e4 et M apparaissent le 10 mars (D existait avant) ; LEB : 4 secteurs dès le début."""
    debut = date(2025, 3, 1)
    lte, wcdma = [], []
    for i in range(20):
        jour = debut + timedelta(days=i)
        lte += [("MDOe1", jour), ("LEBe1", jour), ("LEBe4", jour)] + ([("MDOe4", jour)] if i >= 9 else [])
        wcdma += [("MDO355D", jour)] + ([("MDO355M", jour)] if i >= 12 else [])
    e = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    pd.DataFrame(lte, columns=["EutranCell_Id", "DateDay"]).to_sql("lte_cell_day", e, index=False)
    pd.DataFrame(wcdma, columns=["CellWcdma", "DateDay"]).to_sql("wcdma_cell_day", e, index=False)
    return e


@pytest.fixture
def sites():
    _site("MDO355", "MDO", [("MDOe1", "LTE", 1, None), ("MDOe4", "LTE", 4, 1),
                            ("MDO355D", "WCDMA", 4, 1), ("MDO355M", "WCDMA", 4, None)])
    _site("LEB353", "LEB", [("LEBe1", "LTE", 1, None), ("LEBe4", "LTE", 4, 1)])
    _site("AIG101", "AIG", [("AIGe1", "LTE", 1, None)])


def test_detecter(sites, engine):
    assert detecter(engine) == {"MDO355": date(2025, 3, 10), "LEB353": None}


def test_commande_enregistre_sans_ecraser(sites, engine, monkeypatch, capsys):
    monkeypatch.setattr("apps.referentiel.management.commands.detecter_bascules.moteur_kpi", lambda: engine)
    call_command("detecter_bascules")
    assert Site.objects.get(code_site="MDO355").bascule_4_secteurs is None
    assert "MDO355 : 10/03/2025" in capsys.readouterr().out

    Site.objects.filter(code_site="MDO355").update(bascule_4_secteurs=date(2025, 3, 5))
    call_command("detecter_bascules", "--enregistrer")
    assert Site.objects.get(code_site="MDO355").bascule_4_secteurs == date(2025, 3, 5)
    call_command("detecter_bascules", "--enregistrer", "--remplacer")
    assert Site.objects.get(code_site="MDO355").bascule_4_secteurs == date(2025, 3, 10)
