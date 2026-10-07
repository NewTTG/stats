# Stats — analyse KPI réseau (LTE / WCDMA)

Application web interne de statistiques de trafic et de qualité radio, avec périmètre
de données par utilisateur et exports Excel / PowerPoint. Cahier des charges :
[`brief_app_kpi_reseau.md`](brief_app_kpi_reseau.md).

**État : phase 2** — phase 1 (référentiel, catalogue KPI, moteur de calcul, écran de
requête, périmètres d'accès, export Excel) + événements avec détection d'anomalies,
rapports PowerPoint / Excel en tâche de fond, KPI WCDMA, seuils réglables dans l'admin.
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

# 5. (une fois) Événements initiaux depuis l'onglet Cluster — créneaux à renseigner ensuite dans l'admin
python manage.py import_clusters OPT_Network_Database_V2.xlsx

# 6. Lancement : application + worker des rapports (deux terminaux)
python manage.py runserver             # http://localhost:8000
python manage.py qcluster              # génère les rapports PowerPoint / Excel
```

Sans worker, mettre `Q_SYNC=1` dans `.env` : les rapports sont alors générés
immédiatement, pendant la requête.

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
docker compose exec app python manage.py import_clusters OPT_Network_Database_V2.xlsx   # une seule fois
```

Application sur http://<serveur>:8000. Le service `worker` (django-q2, sans Redis :
la file d'attente est dans la base applicative) génère les rapports ; les fichiers
sont conservés dans le volume `media`.

### Ce que l'on peut faire aujourd'hui

- **Requête KPI** (page d'accueil, http://localhost:8000) : technologie, périmètre
  (commune, site, trigramme, secteur, cellule), période, fenêtre horaire, pas de temps,
  niveau d'agrégation, KPI → synthèse sur toute la période (ratio de sommes) avec statut
  OK / alerte / critique, graphiques d'évolution (ECharts), tableau détaillé avec seuils
  en couleur et liste des cellules du périmètre sans données. Nécessite `KPI_DB_*` dans `.env`.
- **Export Excel** (bouton sur l'écran de résultat) : onglet *Paramètres* (requête,
  cellules sans données, avertissements), par technologie un onglet *Synthèse*
  (ensemble du périmètre puis chaque entité, sur toute la période) et un onglet
  *Données*, onglet *Définitions* des KPI. Chaque export est tracé dans le journal d'audit.
- **Rapport PowerPoint d'une requête** (bouton sur l'écran de résultat) : titre,
  synthèse, un graphique commenté par KPI, annexe des cellules sans données.
- **Événements** (/evenements) : pour chaque événement, comparaison des créneaux avec
  les mêmes jours et heures des N semaines précédentes (4 par défaut) :
  - synthèse par KPI (événement, référence, écart %, statut) ;
  - courbes horaires événement / référence avec la bande min–max des semaines ;
  - anomalies triées par gravité : seuil dépassé, écart significatif à la référence,
    cellule sans données sur un créneau, saturation (PRB DL haute + débit DL bas) ;
  - classement des secteurs (ou sites) les plus dégradés ;
  - rapports PowerPoint et Excel, par secteur ou par site.
- **Mes rapports** (/rapports) : historique et téléchargement des rapports générés.
- **Administration** (/admin) : sites / secteurs / cellules, historique des imports,
  utilisateurs, groupes, périmètres, journal d'audit, **événements** (cellules,
  créneaux, semaines de référence), **seuils KPI**, **réglages de détection d'anomalies**.

### Événements

- Cellules : codes site (toutes leurs cellules), codes secteur et/ou noms de cellules
  LTE ou WCDMA. Elles sont enregistrées par leur nom : un nouvel import du référentiel
  ne les perd pas.
- Créneaux : autant que nécessaire (plusieurs jours, horaires différents chaque jour).
- Référence : moyenne des mêmes créneaux décalés de 1 à N semaines. Pour un KPI
  additif (volume, trafic), c'est la moyenne des semaines, pas leur somme.
- Écart significatif : dégradation de plus de 20 % **et** de plus de 2 écarts-types
  (sur les semaines de référence) ; critique au-delà de 40 %. Réglable dans l'admin.
- Un lecteur restreint ne voit que les cellules et KPI de son périmètre.

### Seuils KPI

Admin → **Seuils KPI** : une ligne par KPI, initialisée avec les valeurs du catalogue
YAML ; modifier directement dans la liste. L'action « Rétablir les seuils du catalogue »
remet les valeurs du YAML.

### Modèle PowerPoint

Le modèle de la charte Helia PRO est en `config/modele_rapport.pptx` (autre chemin :
variable `PPTX_MODELE`). Les rapports utilisent ses dispositions « Diapo 1 » (titre),
« Diapo Simple 3 » (contenu) et « Diapo FIN » (fin), à changer dans
`PPTX_DISPOSITIONS` (`config/settings.py`). Les couleurs des graphiques et des
tableaux viennent du thème du modèle (magenta pour l'événement, gris pour la
référence). Ses diapositives d'exemple sont ignorées et les dispositions non
utilisées retirées du fichier produit (≈ 2 Mo au lieu de 10). Sans modèle, la
charte bleu marine / ambre est dessinée par le code.

## Droits d'accès

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
| `apps/kpi/` | modèle de requête (Pydantic), catalogue, moteur de calcul, seuils réglables |
| `apps/evenements/` | événements, analyse contre référence, règles de détection (`detection.py`) |
| `apps/rapports/` | PowerPoint / Excel, tâche django-q2, historique |
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
