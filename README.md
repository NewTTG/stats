# Stats — analyse KPI réseau (LTE / WCDMA)

Application web interne de statistiques de trafic et de qualité radio, avec périmètre
de données par utilisateur et exports Excel / PowerPoint. Cahier des charges :
[`brief_app_kpi_reseau.md`](brief_app_kpi_reseau.md).

**État : phase 0** — squelette, description des données ([`docs/schema.md`](docs/schema.md)),
prérequis et questions ouvertes ([`docs/questions.md`](docs/questions.md)).

## Installation (dev)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # sans APP_DB_HOST : base SQLite locale
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver    # admin : http://localhost:8000/admin/
pytest
```

## Docker

```bash
cp .env.example .env   # renseigner APP_DB_PASSWORD, DJANGO_SECRET_KEY…
docker compose up --build
```

## Exploration de la base KPI (phase 0)

Depuis un poste ayant accès au réseau de la base, avec `KPI_DB_*` renseignés dans `.env` :

```bash
python scripts/explorer_schema.py   # session forcée en lecture seule -> docs/schema_bdd.md
```

## Organisation

| Chemin | Rôle |
|---|---|
| `config/` | settings Django, `kpi_catalogue.yaml` |
| `apps/comptes/` | périmètres d'accès, journal d'audit |
| `apps/referentiel/` | sites / secteurs / cellules importés du xlsx, décodage des noms de cellules |
| `apps/kpi/` | modèle de requête (Pydantic), catalogue, moteur de calcul |
| `docs/` | documentation phase 0 |
| `tests/` | pytest (données synthétiques uniquement) |

## Ajouter un KPI

Ajouter une entrée dans `config/kpi_catalogue.yaml` :

```yaml
- code: lte_rrc_setup_sr
  libelle: Taux de succès d'établissement RRC
  techno: LTE
  unite: "%"
  categorie: accessibilite
  numerateur: pmRrcConnEstabSucc      # expression pandas sur les colonnes source
  denominateur: pmRrcConnEstabAtt     # omis => KPI additif (somme)
  facteur: 100
  sens: haut_est_mieux
  seuils: { alerte: 98, critique: 95 }
```

Le moteur somme numérateurs et dénominateurs sur le périmètre et la période **avant**
de diviser (ratio de sommes, jamais moyenne de ratios). `pytest` vérifie que toutes
les expressions du catalogue sont évaluables.

## Données

Aucune donnée réelle ni identifiant dans le dépôt : les fichiers `*.xlsx` / `*.csv`
sont ignorés par Git, les secrets sont dans `.env`.
