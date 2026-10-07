"""Lecture de la base KPI (PostgreSQL, lecture seule) via SQLAlchemy.

Les noms de colonnes viennent du catalogue KPI versionné ; ils sont tout de même
validés et cités. Les valeurs (cellules, dates) passent toujours en paramètres liés.
"""

import re
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd
import sqlalchemy as sa
from django.conf import settings

# (techno, résolution) -> (table, colonne cellule, colonne horodatage)
TABLES = {
    ("LTE", "heure"): ("lte_cell_hour", "EutranCell_Id", "DateHour"),
    ("LTE", "jour"): ("lte_cell_day", "EutranCell_Id", "DateDay"),
    ("WCDMA", "heure"): ("wcdma_cell_hour", "CellWcdma", "DateHour"),
    ("WCDMA", "jour"): ("wcdma_cell_day", "CellWcdma", "DateDay"),
}

_IDENTIFIANT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BaseKpiNonConfiguree(RuntimeError):
    pass


def _citer(nom: str) -> str:
    if not _IDENTIFIANT.match(nom):
        raise ValueError(f"identifiant SQL invalide : {nom!r}")
    return f'"{nom}"'


@lru_cache
def moteur_kpi() -> sa.Engine:
    cfg = settings.KPI_DB
    if not cfg["host"]:
        raise BaseKpiNonConfiguree("Base KPI non configurée : renseigner KPI_DB_* dans .env")
    url = sa.URL.create(
        "postgresql+psycopg",
        username=cfg["user"],
        password=cfg["password"],
        host=cfg["host"],
        port=int(cfg["port"] or 5432),
        database=cfg["name"],
    )
    options = "-c default_transaction_read_only=on -c statement_timeout=60000"
    if cfg["schema"]:
        options += f" -c search_path={cfg['schema']}"
    return sa.create_engine(url, connect_args={"options": options, "connect_timeout": 10}, pool_pre_ping=True)


def lire(
    engine: sa.Engine,
    techno: str,
    resolution: str,
    colonnes: list[str],
    debut: date,
    fin: date,
    cellules: list[str] | None,
) -> pd.DataFrame:
    """Lignes de la table KPI sur [debut, fin] (bornes incluses).

    ``cellules`` à None : toutes les cellules. Liste vide : aucune ligne.
    Renvoie les colonnes ``cellule``, ``horodatage`` puis ``colonnes``.
    """
    table, col_cellule, col_temps = TABLES[(techno, resolution)]
    if cellules is not None and not cellules:
        return pd.DataFrame(columns=["cellule", "horodatage", *colonnes])

    select = ", ".join(
        [f"{_citer(col_cellule)} AS cellule", f"{_citer(col_temps)} AS horodatage"]
        + [_citer(c) for c in colonnes]
    )
    sql = f"SELECT {select} FROM {_citer(table)} WHERE {_citer(col_temps)} >= :debut AND {_citer(col_temps)} < :fin"
    params = {"debut": debut, "fin": fin + timedelta(days=1)}
    if cellules is not None:
        sql += f" AND {_citer(col_cellule)} IN :cellules"
    requete = sa.text(sql)
    if cellules is not None:
        requete = requete.bindparams(sa.bindparam("cellules", expanding=True))
        params["cellules"] = list(cellules)

    # Lecture via SQLAlchemy plutôt que pd.read_sql : certaines combinaisons
    # de versions pandas/SQLAlchemy ne reconnaissent pas la connexion.
    with engine.connect() as conn:
        lignes = conn.execute(requete, params).all()
    df = pd.DataFrame(lignes, columns=["cellule", "horodatage", *colonnes])
    df["horodatage"] = pd.to_datetime(df["horodatage"])
    for c in colonnes:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
