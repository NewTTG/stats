# Stats — analyse KPI réseau (LTE / WCDMA)

Application web interne de statistiques de trafic et de qualité radio, avec périmètre
de données par utilisateur et exports Excel / PowerPoint. Cahier des charges :
[`brief_app_kpi_reseau.md`](brief_app_kpi_reseau.md).

**État : phase 1 (MVP)** — import du référentiel, catalogue KPI, moteur de calcul,
écran de requête (tableau, synthèse, graphiques), périmètres d'accès, export Excel.
Données décrites dans [`docs/schema.md`](docs/schema.md), questions ouvertes dans
[`docs/questions.md`](docs/questions.md).

## Initialiser et démarrer l'application

### En local (dev)

Prérequis : Python 3.11+. Toutes les commandes se lancent **depuis la racine du dépôt**.

**Windows (PowerShell)**

```powershell
# 1. Environnement Python
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 2. Configuration (sans APP_DB_HOST : base applicative SQLite locale)
Copy-Item .env.example .env

# 3. Base applicative + compte administrateur
python manage.py migrate
python manage.py createsuperuser

# 4. Chargement du référentiel (+ cellules lues dans les extraits KPI) — sur une seule ligne
python manage.py import_referentiel OPT_Network_Database_V2.xlsx --cellules lte_cell_hour.csv lte_cell_day.csv wcdma_cell_hour.csv wcdma_cell_day.csv

# 5. Lancement
python manage.py runserver             # http://localhost:8000 -> admin
```

**Linux / macOS (bash)** : mêmes commandes, avec `source .venv/bin/activate` et
`cp .env.example .env`.

Le fichier `.env` est lu automatiquement. Renseigner `APP_DB_HOST` (et les autres
`APP_DB_*`) pour utiliser PostgreSQL plutôt que SQLite.

Tests : `pytest`.

### Avec Docker (serveur)

```bash
cp .env.example .env                   # renseigner DJANGO_SECRET_KEY, APP_DB_PASSWORD, KPI_DB_*
docker compose up -d --build           # PostgreSQL + application, migrations appliquées au démarrage
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py import_referentiel OPT_Network_Database_V2.xlsx \
    --cellules lte_cell_hour.csv lte_cell_day.csv wcdma_cell_hour.csv wcdma_cell_day.csv
```

Application sur http://<serveur>:8000.

### Ce que l'on peut faire aujourd'hui

- **Requête KPI** (page d'accueil, http://localhost:8000) : technologie, périmètre
  (commune, site, trigramme, secteur, cellule), période, fenêtre horaire, pas de temps,
  niveau d'agrégation, KPI → synthèse sur toute la période (ratio de sommes) avec statut
  OK / alerte / critique, graphiques d'évolution (ECharts), tableau détaillé avec seuils
  en couleur et liste des cellules du périmètre sans données. Nécessite `KPI_DB_*` dans `.env`.
- **Export Excel** (bouton sur l'écran de résultat) : onglet *Synthèse* (paramètres de la
  requête + valeur et statut de chaque KPI), un onglet de données par technologie,
  onglet *Cellules sans données*. Chaque export est tracé dans le journal d'audit.
- **Administration** (/admin) : sites / secteurs / cellules, historique des imports,
  utilisateurs, groupes, périmètres, journal d'audit des requêtes.

### Droits d'accès

- superutilisateur ou membre du groupe **Admin** ou **Analyste** : tout le réseau, tous les KPI ;
- autre utilisateur : uniquement les cellules et KPI de ses **Périmètres** (admin →
  Périmètres), rattachés à lui ou à l'un de ses groupes. Sans périmètre : aucune donnée.

### Import du référentiel : règles

- relancer `import_referentiel` à chaque nouvelle version du xlsx : chaque import est historisé ;
- secteurs en double : première ligne conservée ; secteurs sans site : rejetés ;
- trigramme partagé par plusieurs sites : le premier site du fichier fait foi ;
- cellules dont le secteur est absent du xlsx : conservées sans rattachement et signalées.

## Exploration de la base KPI (phase 0)

Depuis un poste ayant accès au réseau de la base, avec `KPI_DB_*` renseignés dans `.env` :

```bash
pip install "psycopg[binary]"
python scripts/explorer_schema.py   # depuis la racine du dépôt ; lecture seule -> docs/schema_bdd.md
```

## Organisation

| Chemin | Rôle |
|---|---|
| `config/` | settings Django, `kpi_catalogue.yaml` |
| `apps/comptes/` | périmètres d'accès, journal d'audit |
| `apps/referentiel/` | sites / secteurs / cellules importés du xlsx, décodage des noms de cellules |
| `apps/kpi/` | modèle de requête (Pydantic), catalogue, moteur de calcul |
| `static/vendor/` | ECharts, servi localement (aucun CDN) |
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

Le référentiel xlsx et les 4 extraits CSV à la racine sont conservés comme référence.
Aucun identifiant dans le dépôt : les secrets sont dans `.env` (non versionné).
