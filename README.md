# Stats : analyse KPI réseau (LTE / WCDMA)

Application web interne de statistiques de trafic et de qualité radio, avec périmètre
de données par utilisateur et exports Excel / PowerPoint. Cahier des charges :
[`brief_app_kpi_reseau.md`](brief_app_kpi_reseau.md).

**État : phase 2 + recherche en langage libre + rapports enregistrés et planifiés** : phase 1
(référentiel, catalogue KPI, moteur de calcul, périmètres d'accès, export Excel) + événements
avec détection d'anomalies, rapports PowerPoint / Excel en tâche de fond, KPI WCDMA, seuils
réglables dans l'admin ; barre de recherche en langage libre (règles locales, IA facultative) ;
rapports enregistrés, relancés à la demande ou planifiés (phase 3, sans SSO ni SharePoint) ;
rapports types en trois choix (rapport, lieu, période) sur l'accueil ; espace
d'administration séparé ; base de démonstration synthétique utilisable sans accès à la base KPI.
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

# 4. Chargement du référentiel + cellules : avec la base KPI (toutes les cellules de l'historique)…
python manage.py import_referentiel OPT_Network_Database_V2.xlsx --cellules-kpi
#    … ou, sans accès à la base KPI, cellules lues dans les extraits CSV : sur une seule ligne
python manage.py import_referentiel OPT_Network_Database_V2.xlsx --cellules lte_cell_hour.csv lte_cell_day.csv wcdma_cell_hour.csv wcdma_cell_day.csv

# 4 bis. Avec la base KPI : date de passage de 3 à 4 secteurs des sites concernés (DTS009, MDO355…)
python manage.py detecter_bascules --enregistrer

# 5. (une fois) Événements initiaux depuis l'onglet Cluster : créneaux à renseigner ensuite dans l'admin
python manage.py import_clusters OPT_Network_Database_V2.xlsx

# 5 bis. Sans accès à la base KPI : données de démonstration (≈ 20 s, ≈ 650 Mo dans data/)
python manage.py charger_demo_kpi --jours 30

# 6. Lancement : application + worker des rapports (deux terminaux)
python manage.py runserver             # http://localhost:8000
python manage.py qcluster              # génère les rapports, lance les rapports planifiés
```

Sans worker, mettre `Q_SYNC=1` dans `.env` : les rapports sont alors générés
immédiatement, pendant la requête. Les rapports **planifiés** ont besoin du worker (il les
lance toutes les 15 minutes) ; à défaut, appeler `python manage.py lancer_rapports_planifies`
depuis une tâche planifiée (cron, Planificateur de tâches Windows) toutes les 15 minutes.

**Linux / macOS (bash)** : mêmes commandes, avec `source .venv/bin/activate` et
`cp .env.example .env`.

Le fichier `.env` est lu automatiquement. Renseigner `APP_DB_HOST` (et les autres
`APP_DB_*`) pour utiliser PostgreSQL plutôt que SQLite. Si le projet est sur un
partage réseau (`\\serveur\...`), SQLite y échoue (« attempt to write a readonly
database », verrous) : renseigner `APP_DB_SQLITE` avec un chemin sur un disque local.

Tests : `pytest` (aucun appel réseau : l'API IA est simulée).

### Performances et cache des recherches

Les résultats calculés sont conservés dans un **cache partagé sur disque local** :
une recherche déjà effectuée peut être réutilisée par un autre utilisateur ayant le
même périmètre effectif et les mêmes KPI autorisés. Les écrans de recherche, exports
Excel et rapports PowerPoint de ces recherches utilisent ce cache. Les analyses
comparatives d'événements gardent pour l'instant leur propre parcours sans cache.

- **Fraîcheur : 5 minutes**, comptées dès le début du calcul, sans prolongation lors
  des consultations. Après expiration, les données sont relues ; une correction dans
  PostgreSQL peut donc prendre jusqu'à 5 minutes pour apparaître. Une régénération ou
  modification de la base SQLite de démonstration invalide immédiatement ses résultats.
- **Budget : 512 Mio sur disque**, 32 Mio au plus par résultat et technologie. Les
  entrées expirées puis les moins récemment consultées sont supprimées. Les résultats
  trop volumineux restent consultables mais ne sont pas stockés. Ce budget concerne le
  cache, pas la mémoire nécessaire au premier calcul ; les fichiers de verrouillage et
  les journaux SQLite temporaires peuvent ajouter un peu d'espace disque.
- **Droits relus à chaque demande**, avant tout accès au cache : les cellules et KPI
  réellement autorisés font partie de la clé. Le référentiel utilisé pour regrouper les
  cellules, les dates de bascule des secteurs et les définitions/seuils des KPI entrent
  aussi dans la clé. Une modification dans l'administration est donc prise en compte
  sans attendre l'expiration. Le catalogue YAML est chargé au démarrage du processus :
  redémarrer les processus après une modification de ses formules.
- **Requêtes simultanées identiques** : un verrou entre processus évite le même calcul
  en parallèle. Attente limitée à 65 secondes ; au-delà, calcul indépendant. Les verrous
  sont libérés par le système si un processus s'arrête. Un cache inaccessible, corrompu
  ou plein ne bloque pas la consultation : l'application recalcule depuis la source et
  écrit un avertissement dans les journaux. Les erreurs de calcul ne sont pas cachées.
- **Calcul initial allégé** : les numérateurs/dénominateurs sont évalués une seule fois
  pour le détail et les deux synthèses ; ratios de sommes, pics simultanés et KPI
  composites conservent les mêmes règles de calcul.

Réglages `.env` (redémarrer les processus après modification) :

| Variable | Défaut | Rôle |
|---|---|---|
| `KPI_CACHE_ENABLED` | `1` | `0` désactive le cache |
| `KPI_CACHE_TTL` | `300` | Durée de validité en secondes ; `0` désactive le cache |
| `KPI_CACHE_MAX_MB` | `512` | Budget global en Mio |
| `KPI_CACHE_ITEM_MAX_MB` | `32` | Taille maximale d'un résultat et technologie en Mio |
| `KPI_CACHE_DIR` | `data/cache_kpi` | Répertoire privé partagé par les processus |
| `KPI_CACHE_WAIT_SECONDS` | `65` | Attente maximale d'un calcul déjà en cours |

Après mise à jour : `pip install -r requirements.txt`, puis redémarrer l'application
et le worker. Avec Docker, reconstruire les images : `docker compose up -d --build`.
Le volume `cache_kpi` est partagé entre l'application et le worker ; tous les workers
Gunicorn partagent donc les mêmes résultats. En dehors de Docker, donner le même
`KPI_CACHE_DIR` aux processus de la même installation. Utiliser un **disque local**,
pas NFS/SMB. Pour plusieurs serveurs, chaque serveur possède son cache local ; un cache
distribué demanderait une autre configuration. Ne pas partager ce répertoire entre
installations indépendantes ni l'exposer comme dossier web : il contient des données
KPI et doit être accessible en écriture uniquement aux processus de l'application.

```bash
python manage.py cache_kpi          # nombre de résultats, volume, lectures trouvées/absentes
python manage.py cache_kpi --vider  # purge et remise à zéro des compteurs
```

Les compteurs correspondent aux accès internes au cache (une demande absente peut
faire deux lectures à cause du verrou), pas au nombre de pages vues. La purge retire
les résultats présents ; un calcul déjà en cours peut encore remplir le cache après
la purge. Pour une purge complète lors d'une maintenance de la source, arrêter d'abord
les processus de calcul, purger, puis les redémarrer. Les changements de format du
cache doivent incrémenter `VERSION` dans `apps/kpi/cache.py`.

### Avec Docker (serveur)

```bash
cp .env.example .env                   # renseigner DJANGO_SECRET_KEY, APP_DB_PASSWORD, KPI_DB_*
docker compose up -d --build           # PostgreSQL + application, migrations appliquées au démarrage
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py import_referentiel OPT_Network_Database_V2.xlsx --cellules-kpi
docker compose exec app python manage.py detecter_bascules --enregistrer
docker compose exec app python manage.py import_clusters OPT_Network_Database_V2.xlsx   # une seule fois
```

Application sur http://<serveur>:8000. Le service `worker` (django-q2, sans Redis :
la file d'attente est dans la base applicative) génère les rapports ; les fichiers
sont conservés dans le volume `media`.

### Tableau de bord et exports PDF

L’accueil affiche les KPI 4G et 3G du périmètre autorisé et leurs courbes horaires.
Par défaut, il utilise les **24 dernières heures disponibles** dans les tables horaires,
indépendamment pour chaque technologie : les périodes 3G et 4G peuvent être différentes.
Les heures manquantes sont sautées ; s’il reste moins de 24 heures, seules celles présentes
sont affichées. Les bornes exactes et le nombre d’heures sont indiqués par technologie.
Les valeurs des cartes, courbes, liens d’analyse et exports utilisent les mêmes créneaux.
Les sélecteurs **Aujourd’hui**, **Hier** et **7 derniers jours** restent disponibles.
La journée en cours est signalée comme partielle ; pour ces périodes calendaires, une démo
ancienne affiche sa dernière période disponible avec un avertissement. Aucune valeur n’est inventée.
La recherche libre et les rapports en accès direct restent disponibles, ainsi que
le constructeur de rapports personnalisés. Les graphiques proposent aussi un tableau
de valeurs accessible sans JavaScript.

**Agrandir** ouvre chaque graphique dans une fenêtre dédiée, refermable par Échap,
le bouton Fermer ou un clic sur le fond. Un clic sur une heure (axe ou tracé) la met
en avant dans tous les graphiques temporels de la page, y compris les causes par
période. Recliquer la même heure efface la sélection ; une autre heure la remplace.
Le choix de période au clavier et **Effacer la sélection** offrent les mêmes actions.

Les résultats et événements proposent **Rapport PDF**, en plus de PowerPoint et Excel.
Le PDF contient les paramètres, les synthèses, des graphiques vectoriels et les
avertissements / cellules sans données. Il est généré par le worker et disponible
dans **Mes rapports** ; le format PDF peut aussi être enregistré et planifié.
La bibliothèque ReportLab et ses polices embarquées suffisent, sans service externe.
Après mise à jour : `pip install -r requirements-dev.txt`, `python manage.py migrate`,
et redémarrer l’application et le worker. En déploiement, exécuter aussi
`python manage.py collectstatic --noinput`.

### Ce que l'on peut faire aujourd'hui

- **Rapports types** (page d'accueil, http://localhost:8000) : les demandes habituelles sans
  phrase à écrire, en trois choix : **quel rapport** (carte), **où** (vide = tout le réseau ;
  commune(s), province, site, événement, avec suggestions), **quand** (hier, 7 derniers jours,
  semaine dernière, ce mois-ci, mois dernier, 30 derniers jours ou dates précises) ; options
  repliées : détail temporel, regroupement (par commune, site…), heures.

  | Rapport | Indicateurs |
  |---|---|
  | Bilan complet | appels voix 3G, SMS, accès voix / data 3G, coupures voix / data 3G ; appels CSFB, volume data 4G, utilisateurs connectés, débit DL 4G, PRB DL, taux d'accès 4G, coupures E-RAB |
  | Trafic | appels voix 3G, SMS, appels CSFB, volume data 4G |
  | Data 4G | volume data, débit DL, PRB DL, utilisateurs connectés |
  | Qualité de service | taux d'accès 4G, accès voix / data 3G, coupures E-RAB, coupures voix / data 3G |
  | Utilisateurs 4G | utilisateurs connectés (pic RRC, estimation) |
  | Sur mesure | indicateurs cochés un par un |

  Les rapports types sont des intentions de `config/recherche.yaml` (clé `rapport`) : les
  modifier ou en ajouter un ne demande pas de code. Le résultat commence par une
  **synthèse par thème** (trafic, débit et charge, accès, coupures…) qui réunit 4G et 3G,
  puis le détail par technologie.
- **Recherche en langage libre** (même page, sous les rapports types) : « Drop 3G à
  Nouméa la semaine dernière », « Causes de coupure 4G à Koné hier », « Débit 4G par site
  à Dumbéa les 7 derniers jours »… (voir [Recherche](#recherche-en-langage-libre)). Résultat :
  cartes KPI (valeur sur toute la période en ratio de sommes, statut OK / alerte /
  critique, ≈ si approximatif), répartition par cause (Pareto + barres empilées, reste
  « Non ventilé »), classement des entités (« Les plus dégradés » pour la qualité, « Les plus
  chargés » pour les volumes de trafic ; « top 5 », « les 10 cellules » fixent le nombre de
  lignes, 10 par défaut ; la durée moyenne d'appel n'est pas classée), courbes avec seuils,
  tableau détaillé et cellules sans données repliables.
- **Modifier un résultat** : chaque élément de la demande (indicateurs ou rapport type, lieu,
  période, détail, regroupement, heures, techno) est une puce cliquable. Les paramètres GET de
  l'ancien formulaire « Recherche avancée » (`perimetre_type`, `debut`, `fin`…) restent acceptés.
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
- **Rapports enregistrés** : depuis un résultat, « Enregistrer ce rapport » garde la requête
  (lieu, KPI, granularités) avec une **période relative** (hier, 7 / 30 derniers jours, semaine
  dernière, mois dernier, ce mois-ci), recalculée à chaque lancement. Lancement à la demande
  ou automatique : chaque jour, chaque semaine (jour au choix) ou le 1er du mois, à l'heure
  choisie (heure de Nouméa), en PowerPoint ou Excel, avec les droits de l'auteur.
- **Mes rapports** (/rapports) : rapports enregistrés (afficher à l'écran sur leur période
  relative, générer le fichier, suspendre, supprimer ; les 5 premiers aussi sur l'accueil),
  historique et téléchargement des fichiers générés.
- **Administration** (/admin), à part des statistiques : lien « Administration » en haut à
  droite pour un compte administrateur, « Accès administrateur » (/connexion) en pied de page
  sinon ; les pages des statistiques n'affichent aucun détail technique à un utilisateur
  (commande de la démo, configuration de la base KPI). Espace aux couleurs de l'application,
  lien « ← Retour aux statistiques » : tableau de bord avec accès rapides (créer un événement,
  événements sans créneau à compléter, seuils KPI, périmètres, comptes, journal d'audit) et
  rappel des commandes à lancer sur le serveur ; sections rangées par usage : **événements**
  (cellules, créneaux, semaines de référence), KPI (**seuils KPI**, **réglages de détection
  d'anomalies**), comptes et périmètres (utilisateurs, groupes, périmètres d'accès, journal
  d'audit), référentiel réseau (sites / secteurs / cellules, historique des imports), rapports,
  tâches de fond. La liste des utilisateurs masque par défaut les sessions visiteur (filtre
  « Type de compte »).

### Suivi des demandes et administration

L’administration propose une vue d’ensemble de l’activité des **7 derniers jours**, un
accès permanent au **Suivi des demandes** et aux **Rapports générés**, et des pages de
configuration adaptées aux écrans étroits et aux thèmes clair / sombre.

Chaque recherche soumise conserve son texte, ses paramètres, les éléments compris,
les mots non reconnus, les questions et toutes les options proposées. Les liens de
précision, les filtres et la reformulation depuis la barre du résultat relient les
nouvelles tentatives à leur origine. Les onglets restent indépendants ; un identifiant
d’une autre session ne permet pas de rattacher une demande au parcours d’un autre utilisateur.
L’accueil et l’autocomplétion ne créent pas de demandes.

- **Aboutie** : un résultat a été obtenu ou un fichier a été généré.
- **À préciser** : l’app a demandé un complément ; le filtre « Précision sans réponse »
  retrouve celles sans suite enregistrée. Cela ne prouve pas un abandon.
- **Sans données** : la recherche a été comprise, mais n’a renvoyé aucune ligne.
- **Échec** : validation, accès aux données, calcul ou génération en erreur.
- **En cours** : traitement commencé, ou rapport en attente / en cours dans le worker.

La fiche d’un parcours présente sa chronologie, les choix repris et les paramètres
modifiés, le nombre de lignes, les avertissements et les fichiers associés. Les
recherches sans résultat, les analyses d’événements, les rapports planifiés et les
erreurs du worker sont aussi suivis. La liste se filtre par statut, type, date et suite
du parcours ; la recherche porte sur la demande, l’utilisateur et le message d’erreur.
Les compteurs comptent les **tentatives**, pas les utilisateurs ou les parcours uniques.

Les exports Excel immédiats sont désormais archivés dans `MEDIA_ROOT`, comme les PDF
et PowerPoint, et apparaissent aussi dans « Mes rapports ». L’administrateur peut
retrouver le fichier exact par utilisateur, titre, format, statut ou date, puis le
télécharger depuis une route protégée (pas de lien public direct vers le stockage).
Les téléchargements administrateur sont inscrits au journal d’audit.

L’accès nécessite un compte staff avec `comptes.view_demandesuivie` pour les demandes
et `rapports.view_rapport` pour les fichiers (ou un superutilisateur). Les traces sont
en lecture seule dans l’admin. Les fichiers suivent les règles de conservation déjà
existantes des rapports : pas de purge automatique des archives par cette fonctionnalité.
Sauvegarder la base applicative **et** `MEDIA_ROOT` pour conserver les parcours et fichiers.

**Mise à jour** : installer les dépendances, exécuter `python manage.py migrate`, puis
`python manage.py collectstatic --noinput` et redémarrer l’application et le worker.
Les deux migrations ajoutent le suivi et son lien aux rapports sans modifier les
anciennes traces. Le suivi détaillé commence après l’installation : les questions et
résultats passés ne peuvent pas être reconstruits à partir de l’ancien journal.
Les anciens rapports restent disponibles dans « Rapports générés ».

La recherche comprend désormais **auj**, **auj.** et **ajd** comme « aujourd’hui »
(heure de Nouméa). « Stats » ou « statistiques », sans indicateur précis, demande un
bilan complet ; un indicateur explicite reste prioritaire (« stats du débit » = débit).

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
  Pour un taux de succès borné à 100 % (en %, « haut est mieux », accessibilité,
  disponibilité, mobilité), les 20 % s'entendent sur le taux d'échec : 99,7 → 97,5 % =
  échecs de 0,3 à 2,5 %, +733 %, donc significatif ; 99,7 → 99,6 % reste sous `ecart_min`.
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

- **Votre demande** : chaque élément reconnu (techno · indicateurs · lieu · période · détail ·
  regroupement · heures) est une puce cliquable pour le modifier (la puce des indicateurs
  propose aussi les rapports types) ; les mots non compris sont listés.
- **Rapports types en un mot** : « bilan », « rapport », « synthèse », « stats habituelles »,
  « tableau de bord » → bilan complet ; « rapport trafic », « voix, SMS et data » → trafic ;
  « bilan data » → data 4G ; « qualité », « QoS » → qualité de service ; « utilisateurs »,
  « nombre d'utilisateurs », « RRC conn max », « affluence » → utilisateurs connectés. Les mots
  génériques (`mots_generiques` : bilan, rapport, synthèse, qualité, utilisateurs, clients…)
  ne comptent que si aucun indicateur n'est cité : « bilan des coupures » = drop,
  « qualité du débit » = débit. « Bilan 4G » = le bilan limité à la 4G.
- **Questions** : période absente (Hier, 7 derniers jours, Semaine dernière…, ou dates
  libres), KPI non reconnu (Bilan complet, Drop, Taux d'accès, Débit, Trafic data, Appels, SMS,
  Disponibilité, Congestion, Utilisateurs connectés), lieu ambigu (trigramme partagé `CHT`, événements en double),
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
  site, trigrammes, secteurs, cellules, événements : limités au périmètre de l'utilisateur
  (un lecteur restreint ne se voit proposer aucun lieu hors de son périmètre). Provinces
  lues avant le vocabulaire : « Province Sud » = toutes ses communes, Grand Nouméa compris ;
  « Province Nord », « Province des Îles » ; « sud » seul garde le sens « Sud (hors Grand
  Nouméa) » (choix documenté dans `config/recherche.yaml`). Grand Nouméa = Nouméa, Dumbéa,
  Mont-Dore, Païta : une commune à cheval sur deux régions n'est rattachée qu'à sa région
  majoritaire (le plus de sites), donc Sud et Grand Nouméa ne se recouvrent pas. Un lieu
  cité hors périmètre ou inconnu n'est jamais calculé en silence sur le périmètre : la
  question « « Dumbéa » n'est pas dans votre périmètre. » propose « Voir mon périmètre
  (Koné) », avec le même message que le lieu existe ailleurs ou non. Pour un lecteur
  restreint, cette détection ne s'appuie que sur des sources publiques (communes,
  régions / provinces, y compris par correspondance approchée : « Koumak ») et sur la forme
  des mots (code « AAA999 », trigramme en capitales, mot placé après « à », « au », « sur »…) :
  un nom de site ou un mot d'événement hors périmètre répond exactement comme un mot
  inventé (pas d'oracle d'existence). Sans restriction, un code inconnu (« PIM999 ») donne
  « Lieu non reconnu ». Un mot capitalisé en milieu de phrase (« Urgent », « Brousse ») n'est
  un lieu probable qu'après une préposition de lieu (à, au, aux, sur, de, du, pour, en) ou
  s'il ressemble à un lieu connu. Correspondance approchée : communes et événements d'abord,
  puis noms de sites (seuil 0,85), noms de 5 lettres au moins, jamais les mots courants de
  `mots_courants` (« marché », « contre ») ; « Konee » (nom 4G du site KONE) demande
  « commune Koné ou site KONE ? ».
- **Dates** : aujourd'hui, hier, cette semaine, la semaine dernière, les N derniers jours,
  ce mois-ci, le mois dernier, « septembre », « septembre 2025 », « du 1er au 15
  septembre », « du 01/09 au 15/09 », « le 14/09 », « le week-end du 14 », « semaine 38 »
  ou « sem. 38 » ; « S40 », « S 40 », « s.40 » seulement avec un contexte de date (« en S40 »,
  « la S40 », « semaine S40 », « S40 2026 ») et jamais « S1 » (interface S1) ; « Nouméa S40 »
  sans contexte : question de période avec « Semaine 40 » en premier ; « la semaine du 5
  octobre » (ou « du 05/10 ») = du lundi au dimanche contenant ce jour ; « 2025 », « ce
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
| `APP_DB_SQLITE` | fichier SQLite de la base applicative sans `APP_DB_HOST` (défaut `db.sqlite3`) ; à placer sur un disque local, jamais sur un partage réseau |
| `KPI_DB_*` | base KPI PostgreSQL en lecture seule |
| `KPI_DEMO_SQLITE` | base de démonstration (défaut `data/kpi_demo.sqlite3`), utilisée sans `KPI_DB_HOST` |
| `GROQ_API_KEY` | clé de l'API Groq ; vide = pas de recherche IA (jamais dans le dépôt) |
| `GROQ_MODEL` | modèle (défaut `llama-3.3-70b-versatile`) |
| `GROQ_TIMEOUT` | délai de réponse en secondes (défaut 10) |
| `PPTX_MODELE`, `Q_SYNC`, `Q_WORKERS` | rapports |

## Droits d'accès

**Sans compte (par défaut, `ACCES_ANONYME=1`)** : pas d'écran de connexion. Chaque navigateur
reçoit à sa première visite une session « visiteur », gardée un an après la dernière visite
dans un cookie : ses **dernières recherches** (relancer en un clic, ou « Modifier » pour la
reprendre dans la barre et changer communes / dates) et ses rapports lui restent propres.
Effacer les cookies ou changer de navigateur repart d'une session vierge. Les visiteurs voient
tout le réseau (groupe Analyste). L'administration reste réservée aux comptes avec mot de
passe : `/admin` renvoie vers `/connexion` (« Accès administrateur »), qui mène ensuite au
tableau de bord de l'administration. Ménage des sessions abandonnées :
`python manage.py purger_visiteurs` (inactives depuis plus de 400 jours). `ACCES_ANONYME=0`
rétablit la connexion obligatoire, avec les règles ci-dessous.

- superutilisateur ou membre du groupe **Admin** ou **Analyste** : tout le réseau, tous les KPI ;
- autre utilisateur : uniquement les cellules et KPI de ses **Périmètres** (admin →
  Périmètres d'accès), rattachés à lui ou à l'un de ses groupes. Sans périmètre : aucune donnée.

### Import du référentiel : règles

- relancer `import_referentiel` à chaque nouvelle version du xlsx ou après la mise en service de
  cellules : chaque import est historisé ;
- cellules : `--cellules-kpi` lit tous les noms des tables journalières de la base KPI (tout
  l'historique, y compris les cellules arrêtées, pour garder leurs statistiques passées) ;
  `--cellules` les lit dans des exports CSV ; les deux peuvent se combiner ;
- seul l'onglet `Site_File` est lu (commune, nom de site unifié `siteName`…) ; `Cell_File`
  est ignoré, sa numérotation des secteurs n'étant pas fiable ;
- les secteurs sont déduits des noms de cellules (`AIG1011` = secteur 1 d'AIG101 : AIG101A/D/J,
  AIGe1/e11/e21) et rattachés au site par le trigramme (en 3G : par le codeSite, sinon par
  le trigramme) ; trigramme partagé par plusieurs sites : le premier site du fichier fait foi ;
- site à 3 secteurs : e4 = e1, e5 = e2, e6 = e3 (couche supplémentaire, site déporté) ;
- site à 4 secteurs (`nbSect` = 4, cellule 3G M, ou porteuse LTE avec e1 à e4) : D et e4 =
  secteur 4. S'il est passé de 3 à 4 secteurs, D et e4 comptaient avant dans le secteur 1 :
  la date de passage (admin → Sites, ou `manage.py detecter_bascules --enregistrer`, qui la
  lit dans la base KPI) est appliquée aux calculs par secteur ;
- cellules dont le site est absent de `Site_File` : conservées sans rattachement et signalées.

## Exploration de la base KPI (phase 0)

Depuis un poste ayant accès au réseau de la base, avec `KPI_DB_*` renseignés dans `.env` :

```bash
pip install "psycopg[binary]"
python scripts/explorer_schema.py   # depuis la racine du dépôt ; lecture seule -> docs/schema_bdd.md
```

## Organisation

| Chemin | Rôle |
|---|---|
| `config/` | settings Django, `kpi_catalogue.yaml`, vocabulaire de recherche `recherche.yaml`, site d'administration (`admin.py` : ordre des sections, tableau de bord ; gabarits dans `templates/admin/`) |
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

Pour un compteur de pic (ex. `RrcConnMax_max_nb`, utilisateurs connectés), `agregation: pic`
(numérateur seul) : somme des cellules à chaque horodatage, puis maximum sur la période,
au lieu de la somme simple.

## Données

Le référentiel xlsx et les 4 extraits CSV à la racine sont conservés comme référence.
Aucun identifiant dans le dépôt : les secrets sont dans `.env` (non versionné).
