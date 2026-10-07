"""Phase 0 : explore la base KPI en lecture seule et écrit docs/schema_bdd.md.

À lancer depuis un poste ayant accès au réseau de la base :

    pip install "psycopg[binary]"
    python scripts/explorer_schema.py            # lit KPI_DB_* dans .env

La session est forcée en lecture seule (default_transaction_read_only) et chaque
requête est limitée à 30 s. Seules des métadonnées sont lues (catalogue PostgreSQL,
estimations de volumétrie, bornes de dates sur les tables KPI) : aucune donnée.
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "docs" / "schema_bdd.md"
MOTIFS_KPI = re.compile(r"lte|wcdma|eutran|cell|calendar", re.I)


def charger_env():
    fichier = RACINE / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8-sig").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            os.environ.setdefault(cle.strip(), valeur.strip())


def connexion():
    manquantes = [v for v in ("KPI_DB_HOST", "KPI_DB_NAME", "KPI_DB_USER") if not os.environ.get(v)]
    if manquantes:
        sys.exit(f"Variables manquantes dans .env : {', '.join(manquantes)}")
    return psycopg.connect(
        host=os.environ["KPI_DB_HOST"],
        port=os.environ.get("KPI_DB_PORT", "5432"),
        dbname=os.environ["KPI_DB_NAME"],
        user=os.environ["KPI_DB_USER"],
        password=os.environ.get("KPI_DB_PASSWORD", ""),
        options="-c default_transaction_read_only=on -c statement_timeout=30000",
        connect_timeout=10,
    )


def requete(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def main():
    charger_env()
    lignes = [f"# Schéma de la base KPI (généré le {datetime.now():%Y-%m-%d %H:%M})", ""]
    with connexion() as conn, conn.cursor() as cur:
        version = requete(cur, "select version()")[0][0]
        lignes += [f"PostgreSQL : `{version.split(',')[0]}`", ""]

        objets = requete(cur, """
            select n.nspname, c.relname, c.relkind, greatest(c.reltuples, 0)::bigint,
                   pg_total_relation_size(c.oid)
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where c.relkind in ('r', 'v', 'm', 'p')
              and n.nspname not in ('pg_catalog', 'information_schema')
              and n.nspname not like 'pg_toast%'
            order by n.nspname, c.relname
        """)
        types = {"r": "table", "v": "vue", "m": "vue matérialisée", "p": "table partitionnée"}
        lignes += ["## Objets", "", "| Schéma | Nom | Type | Lignes (estim.) | Taille |", "|---|---|---|---|---|"]
        for schema, nom, kind, n, taille in objets:
            lignes.append(f"| {schema} | {nom} | {types[kind]} | {n:,} | {taille / 1e6:,.0f} Mo |")
        lignes.append("")

        for schema, nom, kind, n, _ in objets:
            if not MOTIFS_KPI.search(nom):
                continue
            lignes += [f"## `{schema}.{nom}` ({types[kind]})", ""]
            colonnes = requete(cur, """
                select column_name, data_type from information_schema.columns
                where table_schema = %s and table_name = %s order by ordinal_position
            """, (schema, nom))
            lignes.append(f"{len(colonnes)} colonnes : " + ", ".join(f"`{c}` ({t})" for c, t in colonnes))
            lignes.append("")

            index = requete(cur, "select indexdef from pg_indexes where schemaname = %s and tablename = %s",
                            (schema, nom))
            lignes += ["Index :" + (" aucun" if not index else ""), *[f"- `{i[0]}`" for i in index], ""]

            dates = [c for c, t in colonnes if t.startswith(("timestamp", "date"))]
            for col in dates[:2]:
                try:
                    mini, maxi = requete(
                        cur,
                        sql.SQL("select min({c}), max({c}) from {s}.{t}").format(
                            c=sql.Identifier(col),
                            s=sql.Identifier(schema),
                            t=sql.Identifier(nom),
                        ),
                    )[0]
                    lignes.append(f"- `{col}` : {mini} → {maxi}")
                except psycopg.errors.QueryCanceled:
                    conn.rollback()
                    lignes.append(f"- `{col}` : bornes non calculées (> 30 s, pas d'index ?)")
            if kind in ("v", "m"):
                definition = requete(cur, "select pg_get_viewdef(%s::regclass, true)", (f'"{schema}"."{nom}"',))
                lignes += ["", "<details><summary>Définition</summary>", "", "```sql",
                           definition[0][0].strip(), "```", "</details>"]
            lignes.append("")

    SORTIE.write_text("\n".join(lignes), encoding="utf-8")
    print(f"Écrit : {SORTIE}")


if __name__ == "__main__":
    main()
