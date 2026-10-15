# Diagnostic de la découverte des heures du dashboard

Les traces observées le 14 octobre 2026 donnent 25,046 s pour la découverte des heures
LTE et 20,300 s pour WCDMA, sur un total de 46,531 s. Les lectures des compteurs ne
produisent pas d'avertissement de dépassement d'une seconde dans cet extrait. Les
mesures de découverte incluent l'ouverture de connexion et la récupération du résultat.
Une seconde requête du dashboard peut attendre le verrou du premier calcul du cache ;
sa durée totale ne prouve pas qu'elle exécute à nouveau toutes les lectures.

La version précédente utilisait, pour chaque technologie :

```sql
SELECT DISTINCT "DateHour"
FROM public.lte_cell_hour  -- public.wcdma_cell_hour pour la 3G
WHERE "DateHour" IS NOT NULL
ORDER BY "DateHour" DESC
LIMIT 24;
```

`LIMIT 24` limite les heures distinctes renvoyées, pas nécessairement le nombre de
lignes que PostgreSQL parcourt pour les trouver. Il faut regarder le plan réel : un
parcours d'index peut déjà s'arrêter tôt, tandis qu'un tri ou une agrégation après
lecture de l'historique peut être coûteux. Le schéma documenté présente environ
16,2 millions de lignes LTE et 12,9 millions WCDMA, ainsi que des index temporels
et des index uniques `(DateHour, cellule)` ; ce relevé ne garantit pas le plan
choisi aujourd'hui sur le serveur déployé.

Le plan réel fourni pour LTE confirme un `Parallel Seq Scan` : environ
16,5 millions de lignes sont lues, puis `HashAggregate`, `Sort`, `Gather Merge`
et `Unique` précèdent le `Limit`. `Execution Time` vaut **28 152,442 ms**.
Il rapporte **2 755 818 blocs lus** dans les buffers PostgreSQL, soit environ
21 Gio pour des blocs de 8 Kio (ces lectures peuvent venir du cache du système
d'exploitation et ne mesurent pas directement des accès au disque physique).
L'estimation de 200 heures distinctes est éloignée des 8 576 groupes réellement
trouvés par worker ; les statistiques sont un autre point à faire vérifier par
l'administrateur de la base. Aucun rafraîchissement de statistiques ni création
d'index n'est exécuté par l'application en lecture seule.

Le correctif recherche le maximum de `DateHour`, puis le maximum strictement
inférieur à cette heure, jusqu'à 24 valeurs. PostgreSQL peut ainsi passer d'une
heure à la précédente par l'index, sans parcourir toutes les cellules d'une heure
pour la dédupliquer. Les cellules autorisées filtrent les deux MAX, avant tout
accès au cache. Il n'y a pas de borne « maintenant moins 48 heures » qui rendrait
une base ancienne vide ou exclurait des heures séparées par de longs trous.

## Comparer sur le serveur KPI

Ouvrir [sql/dashboard-performances.sql](sql/dashboard-performances.sql) avec le
même schéma, la même base et idéalement le même compte que l'application. Exécuter
chaque bloc séparément. `EXPLAIN (ANALYZE, BUFFERS)` réalise la lecture et renvoie
son plan ainsi que sa durée ; comparer un premier passage et plusieurs passages
à chaud, pour les deux technologies.

Examiner notamment `Execution Time`, les lignes parcourues, `Seq Scan`, les tris,
les `Index Scan` / `Index Only Scan`, `Heap Fetches`, les buffers lus ou trouvés
et les boucles des sous-requêtes MAX. Si le SQL est rapide dans l'outil mais lent
via l'application, comparer aussi le compte SQL, la connexion et la concurrence.
Il n'existe pas de durée universelle attendue pour ce serveur.

Les deux premiers blocs de chaque technologie comparent les découvertes. Le
bloc des compteurs a les mêmes colonnes et filtres temporels que `lire()` ; pour
être exécutable sans recopier 24 horodatages, il redécouvre aussi ces heures dans
une CTE. Son plan inclut donc cette découverte, alors que l'application utilise
les heures déjà obtenues et les lie comme paramètres.

Le script vise le périmètre global de l'administrateur. Pour un lecteur restreint,
ajouter le filtre de cellules dans les deux MAX et dans la lecture des compteurs.
Le code applique ces filtres automatiquement via des paramètres liés.

## Lecture des compteurs (traces du 16 octobre 2026)

Après le correctif de la découverte, celle-ci ne dépasse plus une seconde. Les lectures
des compteurs, elles, durent 7,822 s (LTE) et 6,947 s (WCDMA) pour un dashboard de
15,205 s : elles s'enchaînaient et représentaient 97 % du temps.

Le 14 octobre, ces mêmes lectures (SQL inchangé) prenaient moins d'une seconde chacune.
La différence la plus probable : l'ancienne découverte parcourait toute la table juste
avant, ce qui laissait les pages des dernières heures en mémoire. Désormais la lecture
des 24 heures (environ 48 000 lignes larges de 144 colonnes, soit quelque 8 000 blocs
pour LTE) trouve des pages froides. Les deux durées sont proportionnelles au nombre de
blocs lus (LTE/WCDMA ≈ 1,2), pas au volume renvoyé : le débit réseau n'explique pas
l'écart, puisque le même volume passait en moins d'une seconde le 14.

Correctif : sur PostgreSQL, l'accueil lance les lectures LTE et WCDMA en parallèle
(une connexion du pool chacune). La page attend la plus longue et non plus leur somme :
environ 8 s au lieu de 15 s d'après ces traces. Droits, périmètre et référentiel sont
résolus avant, dans le fil de la requête ; les fils ne lisent que la base KPI ou le
cache. Serveur injoignable : un seul délai de connexion est attendu (en 24 h, la
découverte LTE échoue et WCDMA n'est pas tentée ; sinon les deux tentatives sont
simultanées). La base de démonstration SQLite reste lue séquentiellement.

À confirmer sur le serveur KPI avec le bloc « compteurs » de
[sql/dashboard-performances.sql](sql/dashboard-performances.sql), lancé de préférence
après `SET track_io_timing = on` : au premier passage, un grand nombre de
`shared read` et un `I/O Timings` proche de la durée totale confirment des pages
froides ; un second passage aussitôt après doit être nettement plus rapide
(`shared hit`). Un `Seq Scan` sur la table indiquerait au contraire un mauvais plan.

Les 8 s restantes ne dépendent pas de l'application tant que chaque consultation
relit les 24 heures. Pistes, à décider :

- côté base (administrateur) : mémoire disponible pour le cache, `pg_prewarm` des
  dernières heures, ou réduction des index (un par colonne) qui alourdissent les
  insertions et occupent le cache ;
- côté application : mémoriser les sommes numérateur / dénominateur par heure, puis
  ne relire que les heures récentes. Une consultation ne lirait plus qu'une ou deux
  heures. Il faut alors borner la durée pendant laquelle une heure ancienne corrigée
  en source peut rester affichée (voir « Cache local » plus haut).

## Cache local et synchronisation par heure

Le cache existant conserve les heures découvertes et les résultats calculés sur
le disque du serveur applicatif. Il est partagé entre ses processus et entre les
utilisateurs ayant les mêmes droits effectifs, avec expiration fixe de cinq
minutes et budget disque. Une heure nouvellement arrivée peut prendre jusqu'à
cinq minutes pour apparaître ; les consultations ne repoussent pas l'expiration.
Les données KPI du cache sont privées à l'application.

Une copie locale glissante de 48 heures peut compléter ce mécanisme, mais elle
n'est pas ajoutée par ce correctif. Le dashboard affiche actuellement les 24
**heures disponibles**, pas nécessairement hier et aujourd'hui ni 24 heures
consécutives. Ces deux choix de période n'ont pas la même signification.

Pour une copie locale, le curseur doit suivre la dernière **heure présente en
source**, par technologie. S'il reste à 13 h et que la source arrive à 16 h,
la synchronisation doit charger 14 h, 15 h et 16 h, puis relire par exemple 12 h
et 13 h pour les arrivées tardives. Une heure partielle ne doit pas être traitée
comme complète. Une relecture périodique plus large doit également récupérer
les corrections anciennes ; sans date de modification ou garantie sur le délai
d'arrivée, une simple copie « nouvelles heures seulement » peut rester fausse.
Le regroupement doit conserver les numérateurs/dénominateurs et les pics
simultanés, et appliquer les droits avant toute réutilisation. C'est une évolution
distincte ; les traces actuelles justifient d'abord la correction de la découverte.

## Vérification disponible

PostgreSQL 17, tables temporaires synthétiques : 13 tests comparent exactement
la nouvelle requête à l'ancienne, pour LTE et WCDMA, cellules filtrées ou absentes,
périmètre vide, données anciennes, doublons d'heures et trous.

Sur un million de lignes synthétiques (1 000 heures × 1 000 cellules), table
étroite avec index temporels et statistiques à jour, médiane de trois passages
à chaud : ancienne requête 2,91 ms, nouvelle 0,53 ms, mêmes 24 horodatages.
Cette mesure locale sert à vérifier le mécanisme ; elle ne prédit pas le temps
sur les tables KPI réelles, plus larges, ni le coût des accès réseau.
