"""Lecture de la base KPI (PostgreSQL, lecture seule) via SQLAlchemy.

Les noms de colonnes viennent du catalogue KPI versionné ; ils sont tout de même
validés et cités. Les valeurs (cellules, dates) passent toujours en paramètres liés.

Sans ``KPI_DB_HOST`` : base de démonstration SQLite (mêmes tables et colonnes, données
synthétiques) générée par ``python manage.py charger_demo_kpi``.
"""

import json
import hashlib
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

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
MESSAGE_BASE_INDISPONIBLE = ("Les statistiques sont momentanément indisponibles : la base de données KPI n'est pas "
                             "accessible. Prévenez l'administrateur de l'application.")


def identite_source(engine: sa.Engine):
    """Identité sans secret et version de la source pour les clés du cache.

    SQLite en mémoire : pas de cache persistant. Fichier SQLite : détecte aussi
    remplacement/régénération et écritures WAL. PostgreSQL : fraîcheur bornée par TTL.
    """
    url = engine.url
    version = None
    if url.get_backend_name() == "sqlite":
        nom = url.database
        if not nom or nom == ":memory:" or url.query.get("mode") == "memory":
            return None
        chemin = Path(unquote(nom[5:]) if nom.startswith("file:") else nom).resolve()
        try:
            def signature(p):
                stat = p.stat()
                return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            wal = Path(str(chemin) + "-wal")
            version = [str(chemin), signature(chemin), signature(wal) if wal.exists() else None]
        except OSError:
            return None
    # Le mot de passe participe au hash sans apparaître dans la clé ou les journaux.
    identite = [url.render_as_string(hide_password=False), settings.KPI_DB.get("schema"), version]
    return hashlib.sha256(json.dumps(identite, default=str).encode()).hexdigest()


class BaseKpiNonConfiguree(RuntimeError):
    pass


def _citer(nom: str) -> str:
    if not _IDENTIFIANT.match(nom):
        raise ValueError(f"identifiant SQL invalide : {nom!r}")
    return f'"{nom}"'


def chemin_demo() -> Path:
    return Path(settings.KPI_DEMO_SQLITE)


def est_demo() -> bool:
    """Vrai si les KPI viennent de la base de démonstration (données synthétiques)."""
    return not settings.KPI_DB["host"] and chemin_demo().exists()


def infos_demo() -> dict:
    """Paramètres de génération de la base de démonstration (période, incidents simulés).

    Mis en cache tant que le fichier n'est pas régénéré (date de modification).
    """
    if not est_demo():
        return {}
    try:
        return dict(_infos_demo(str(chemin_demo()), chemin_demo().stat().st_mtime))
    except Exception:  # base générée par une version antérieure, ou en cours de remplacement
        return {}


@lru_cache(maxsize=4)
def _infos_demo(chemin: str, _mtime: float) -> dict:
    with moteur_kpi().connect() as conn:
        infos = dict(conn.execute(sa.text("SELECT cle, valeur FROM demo_info")).all())
    infos["incidents"] = json.loads(infos.get("incidents") or "[]")
    for cle in ("debut", "fin"):
        if infos.get(cle):
            infos[cle] = date.fromisoformat(infos[cle])
    return infos


def _moteur_demo(chemin: Path) -> sa.Engine:
    # Lecture seule ; NullPool : une base régénérée (fichier remplacé) est relue sans redémarrer.
    url = f"sqlite:///file:{chemin.as_posix()}?mode=ro&uri=true"
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@lru_cache
def moteur_kpi() -> sa.Engine:
    cfg = settings.KPI_DB
    if not cfg["host"]:
        if chemin_demo().exists():
            return _moteur_demo(chemin_demo())
        raise BaseKpiNonConfiguree(
            "Base KPI non configurée : renseigner KPI_DB_* dans .env, ou générer des données de "
            "démonstration avec « python manage.py charger_demo_kpi ».")
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


def cellules_distinctes(engine: sa.Engine, techno: str) -> list[str]:
    """Noms de toutes les cellules de la table journalière (tout l'historique).

    Lecture légère : la colonne cellule est indexée dans la base KPI.
    """
    table, col_cellule, _ = TABLES[(techno, "jour")]
    sql = sa.text(f"SELECT DISTINCT {_citer(col_cellule)} FROM {_citer(table)} WHERE {_citer(col_cellule)} IS NOT NULL")
    with engine.connect() as conn:
        return sorted(conn.execute(sql).scalars())


def dernieres_heures(engine: sa.Engine, techno: str, cellules: list[str] | None) -> list[datetime]:
    """Les 24 derniers créneaux horaires présents dans le périmètre autorisé.

    Chaque technologie a sa propre fraîcheur ; les trous ne consomment pas de créneau.
    La limite porte sur les heures distinctes, jamais sur les lignes de cellules.
    """
    if cellules is not None and not cellules:
        return []
    table, col_cellule, col_temps = TABLES[(techno, "heure")]
    temps = _citer(col_temps)
    sql = f"SELECT DISTINCT {temps} FROM {_citer(table)} WHERE {temps} IS NOT NULL"
    params = {}
    if cellules is not None:
        sql += f" AND {_citer(col_cellule)} IN :cellules"
        params["cellules"] = list(cellules)
    sql += f" ORDER BY {temps} DESC LIMIT 24"
    requete = sa.text(sql)
    if cellules is not None:
        requete = requete.bindparams(sa.bindparam("cellules", expanding=True))
    with engine.connect() as conn:
        heures = conn.execute(requete, params).scalars().all()
    return sorted(pd.Timestamp(h).to_pydatetime() for h in heures)


def lire(
    engine: sa.Engine,
    techno: str,
    resolution: str,
    colonnes: list[str],
    debut: date,
    fin: date,
    cellules: list[str] | None,
    heures: list[datetime] | None = None,
) -> pd.DataFrame:
    """Lignes de la table KPI sur [debut, fin] (bornes incluses).

    ``cellules`` à None : toutes les cellules. Liste vide : aucune ligne.
    ``heures`` renseigné : uniquement ces créneaux de la table horaire.
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
    if heures:
        sql += f" AND {_citer(col_temps)} IN :heures"
    requete = sa.text(sql)
    if cellules is not None:
        requete = requete.bindparams(sa.bindparam("cellules", expanding=True))
        params["cellules"] = list(cellules)
    if heures:
        requete = requete.bindparams(sa.bindparam("heures", expanding=True, type_=sa.DateTime()))
        params["heures"] = list(heures)

    # Lecture via SQLAlchemy plutôt que pd.read_sql : certaines combinaisons
    # de versions pandas/SQLAlchemy ne reconnaissent pas la connexion.
    with engine.connect() as conn:
        lignes = conn.execute(requete, params).all()
    df = pd.DataFrame(lignes, columns=["cellule", "horodatage", *colonnes])
    df["horodatage"] = pd.to_datetime(df["horodatage"])
    for c in colonnes:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df
