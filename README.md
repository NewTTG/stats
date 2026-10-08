# Stats — analyse KPI réseau (LTE / WCDMA)

Application web interne de statistiques de trafic et de qualité radio, avec périmètre
de données par utilisateur et exports Excel / PowerPoint. Cahier des charges :
[`brief_app_kpi_reseau.md`](brief_app_kpi_reseau.md).

**État : phase 2 + recherche en langage libre** — phase 1 (référentiel, catalogue KPI,
moteur de calcul, périmètres d'accès, export Excel) + événements avec détection
d'anomalies, rapports PowerPoint / Excel en tâche de fond, KPI WCDMA, seuils réglables
dans l'admin ; barre de recherche en langage libre (règles locales, IA facultative) et
base de démonstration synthétique utilisable sans accès à la base KPI.
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

# 5 bis. Sans accès à la base KPI : données de démonstration (≈ 20 s, ≈ 650 Mo dans data/)
python manage.py charger_demo_kpi --jours 30

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

Tests : `pytest` (aucun appel réseau : l'API IA est simulée).

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

- **Recherche en langage libre** (page d'accueil, http://localhost:8000) : « Drop 3G à
  Nouméa la semaine dernière », « Causes de coupure 4G à Koné hier », « Débit 4G par site
  à Dumbéa les 7 derniers jours »… (voir [Recherche](#recherche-en-langage-libre)). Résultat :
  cartes KPI (valeur sur toute la période en ratio de sommes, statut OK / alerte /
  critique, ≈ si approximatif), répartition par cause (Pareto + barres empilées, reste
  « Non ventilé »), classement des entités (« Les plus dégradés » pour la qualité, « Les plus
  chargés » pour les volumes de trafic ; « top 5 », « les 10 cellules » fixent le nombre de
  lignes, 10 par défaut ; la durée moyenne d'appel n'est pas classée), courbes avec seuils,
  tableau détaillé et cellules sans données repliables.
- **Recherche avancée** (formulaire repliable, pré-rempli par la recherche) : technologie,
  périmètre (commune, site, trigramme, secteur, cellule, événement), période, fenêtre
  horaire, pas de temps, niveau d'agrégation, KPI.
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
- KPI analysés : ceux de l'événement s'il en liste, sinon les KPI principaux du
  catalogue (sans les causes de coupure ni les composants des taux d'accès composites,
  qui restent sélectionnables explicitement).
- Écart significatif : dégradation de plus de 20 % **et** de plus de 2 écarts-types
  (sur les semaines de référence) **et** d'au moins `ecart_min` (catalogue, unité du KPI :
  0,1 pt pour les coupures, 0,5 pt pour les taux d'accès…) ; critique au-delà de 40 %.
  Pourcentages réglables dans l'admin.
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

## Recherche en langage libre

La barre de recherche transforme le texte en requête (même objet que le formulaire,
validé par Pydantic) puis exécute directement. Elle ne bloque jamais : s'il manque
quelque chose, elle pose une question avec des réponses en un clic.

- **Compris** : chaque élément reconnu (techno · KPI · lieu · période · pas · niveau ·
  heures) est une puce cliquable pour le modifier ; les mots non compris sont listés.
- **Questions** : période absente (Hier, 7 derniers jours, Semaine dernière…, ou dates
  libres), KPI non reconnu (Drop, Taux d'accès, Débit, Trafic data, Appels, SMS,
  Disponibilité, Congestion), lieu ambigu (trigramme partagé `CHT`, événements en double),
  lieu mal orthographié ou inconnu (« Nouméaa » → « vouliez-vous dire Nouméa ? », ou
  « Tout le réseau ») : jamais de repli silencieux sur tout le réseau.
- **Vocabulaire** dans [`config/recherche.yaml`](config/recherche.yaml) : intentions →
  synonymes → KPI par techno. Les causes de coupure ne sont pas listées : « causes »,
  « pourquoi » ajoutent les KPI du catalogue dont `decomposition_de` est le KPI retenu.
  « voix » / « data » précisent une intention (« taux de coupure voix » = coupures voix
  3G seules, « accès data » = accès data) au lieu d'ajouter les appels ou le volume.
  Sigles : « S1 » (signalisation S1), « RRC », « E-RAB » (drop ou établissement selon le
  contexte), « PRB DL » (congestion). Sans techno citée, certains termes l'impliquent
  (`technos_implicites`) : E-RAB, PRB, S1, CSFB, CQI → 4G ; HSDPA, HSUPA, CSSR, RAB,
  Erlang → 3G. Les sigles (`termes_techniques` : HSDPA, RRC, PRB, KPI, DL…) ne sont
  jamais pris pour un lieu. « comparaison », « comparer », « vs » ou plusieurs communes
  citées → résultat par commune.
- **Lieux** : communes (accents et tirets tolérés), régions / provinces, codes et noms de
  site, trigrammes, secteurs, cellules, événements — limités au périmètre de l'utilisateur
  (un lecteur restreint ne se voit proposer aucun lieu hors de son périmètre). Un lieu
  cité hors périmètre ou inconnu n'est jamais calculé en silence sur le périmètre : la
  question « « Dumbéa » n'est pas dans votre périmètre. » propose « Voir mon périmètre
  (Koné) », avec le même message que le lieu existe ailleurs ou non. Sans restriction, un
  code inconnu (« PIM999 ») donne « Lieu non reconnu ». Correspondance approchée : communes
  et événements d'abord, puis noms de sites (seuil 0,85) ; « Konee » (nom 4G du site KONE)
  demande « commune Koné ou site KONE ? ».
- **Dates** : aujourd'hui, hier, cette semaine, la semaine dernière, les N derniers jours,
  ce mois-ci, le mois dernier, « septembre », « septembre 2025 », « du 1er au 15
  septembre », « du 01/09 au 15/09 », « le 14/09 », « le week-end du 14 », « semaine 38 »
  ou « sem. 38 » (jamais « S38 » seul : « S1 » est l'interface S1), « 2025 », « ce
  week-end », « le week-end dernier ». Jours de la semaine (« jeudi », « samedi
  dernier », « mardi passé ») : toujours le jour le plus récent **strictement avant
  aujourd'hui** (jamais aujourd'hui ni l'avenir) ; un jeudi, « jeudi » = jeudi de la
  semaine précédente et « samedi dernier » = samedi précédent. « depuis septembre »,
  « depuis le 15/09 », « depuis lundi » : de cette date à hier. Période limitée à 400 jours en horaire et 10 ans en journalier ; si les
  données ne couvrent qu'une partie de la période, un avertissement donne les dates
  réellement disponibles.
  Heures : « 18h-22h », « entre 7h et 20h », « soirée », « en journée ». « Heure chargée »
  est reconnue mais pas encore calculée (journée complète, avec une note).
- **URL partageable, sans état** : `/?q=…` ; les paramètres explicites (`periode=7j`,
  `debut` / `fin`, `techno`, `kpis`, `perimetre_type` / `perimetre_valeurs`,
  `granularite_temps`, `granularite_espace`, `fenetre_horaire`) priment sur le texte.
  Les paramètres du formulaire historique fonctionnent toujours.
- Exports Excel (200 000 lignes de données au plus par techno, mention dans l'onglet
  Paramètres) et rapport PowerPoint (une diapo Pareto pour les causes) depuis tout
  résultat ; après une recherche IA, les liens rejouent la requête résolue sans rappeler
  le modèle ; chaque recherche est tracée
  dans le journal d'audit (texte, IA ou non, requête produite) et apparaît dans « Mes
  dernières recherches ». Suggestions de lieux en JSON : `/suggestions/?q=nou`.
- Fonctionne sans JavaScript (formulaires GET) ; JavaScript sert aux graphiques (ECharts
  servi localement).

### Recherche IA (facultative)

Avec `GROQ_API_KEY` renseignée, une case **✨ Recherche IA** apparaît sous la barre.
Cochée, le texte est interprété par l'API Groq (compatible OpenAI, modèle
`GROQ_MODEL`, température 0, réponse JSON imposée). Le modèle ne reçoit que le texte et
la description du modèle de requête (codes KPI, types de périmètre…) : jamais de donnée
KPI ; il ne produit que le JSON de requête, jamais de SQL. Les lieux qu'il renvoie sont
re-résolus localement (périmètre de l'utilisateur) et la requête est validée par
Pydantic. En cas d'erreur (réseau, clé, délai, JSON invalide), l'interprétation locale
prend le relais avec la note « Recherche IA indisponible ».

## Données de démonstration

Sans `KPI_DB_HOST`, l'application lit la base SQLite `data/kpi_demo.sqlite3`
(`KPI_DEMO_SQLITE`) si elle existe : mêmes tables et noms de colonnes que la base KPI
(limités aux colonnes du catalogue), générées par :

```bash
python manage.py charger_demo_kpi [--jours 30] [--sortie data/kpi_demo.sqlite3] [--graine 42]
```

À partir des 4 extraits CSV (une journée chacun) : profil horaire semaine / week-end,
bruit, succès ≤ tentatives, causes de coupure cohérentes, journalier = agrégat de
l'horaire, et quelques incidents déterministes (site coupé quelques heures, pic de
coupures sur un site, congestion PRB en soirée) listés à la fin de la commande et dans
le bandeau. Un bandeau « Données de démonstration (synthétiques) » est affiché sur toutes
les pages. Dès que `KPI_DB_HOST` est renseigné, la base PostgreSQL est utilisée.

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Django |
| `APP_DB_*` | base applicative PostgreSQL (vide : SQLite local) |
| `KPI_DB_*` | base KPI PostgreSQL en lecture seule |
| `KPI_DEMO_SQLITE` | base de démonstration (défaut `data/kpi_demo.sqlite3`), utilisée sans `KPI_DB_HOST` |
| `GROQ_API_KEY` | clé de l'API Groq ; vide = pas de recherche IA (jamais dans le dépôt) |
| `GROQ_MODEL` | modèle (défaut `llama-3.3-70b-versatile`) |
| `GROQ_TIMEOUT` | délai de réponse en secondes (défaut 10) |
| `PPTX_MODELE`, `Q_SYNC`, `Q_WORKERS` | rapports |

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
| `config/` | settings Django, `kpi_catalogue.yaml`, vocabulaire de recherche `recherche.yaml` |
| `apps/comptes/` | périmètres d'accès, journal d'audit |
| `apps/referentiel/` | sites / secteurs / cellules importés du xlsx, décodage des noms de cellules |
| `apps/kpi/` | modèle de requête (Pydantic), catalogue, moteur de calcul, seuils réglables, écran de recherche |
| `apps/kpi/recherche/` | recherche en langage libre : règles (`regles.py`), IA (`ia.py`), lieux, dates |
| `apps/kpi/management/commands/charger_demo_kpi.py` | base KPI de démonstration (SQLite) |
| `apps/evenements/` | événements, analyse contre référence, règles de détection (`detection.py`) |
| `apps/rapports/` | PowerPoint / Excel, tâche django-q2, historique |
| `static/` | feuille de style, script des graphiques ; `vendor/` : ECharts servi localement (aucun CDN) |
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
