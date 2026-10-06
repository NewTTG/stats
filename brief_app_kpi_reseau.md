# Brief projet — Application web d'analyse KPI réseau (OPT-NC)

> Brief destiné à Claude Code. Les éléments entre `[[...]]` sont à compléter avant lancement.
> Avant d'écrire du code : lis ce document en entier, explore le schéma PostgreSQL (lecture seule), puis propose un plan et pose tes questions sur les points marqués « À confirmer ».

---

## 1. Objectif

Application web interne, multi-utilisateurs, qui permet de sortir des statistiques de trafic et de qualité radio (4G LTE, 3G WCDMA) et de générer des rapports, avec un périmètre de données différent selon l'utilisateur.

Cas d'usage types :
- « Débits 4G pour la commune X sur le mois de septembre »
- « Y a-t-il eu des problèmes pendant l'événement Y ? » → débit, drop, congestion, etc. sur un ensemble de cellules/secteurs défini, comparé à une période de référence
- Export du résultat en PowerPoint / Excel

**Pas d'IA / LLM dans le MVP.** Les demandes passent par un formulaire structuré. L'architecture doit permettre d'ajouter plus tard une saisie en langage naturel qui produit le même objet de requête que le formulaire (voir §9).

---

## 2. Stack technique

- **Backend : Python 3.12 + Django 5** (auth, utilisateurs, groupes, permissions et interface d'admin intégrés — utile pour gérer le référentiel et les événements sans développer d'écrans)
- **Front : templates Django + HTMX + Alpine.js** (pas de SPA)
- **Graphiques : Apache ECharts** (séries temporelles, heatmaps heure × jour)
- **Données : pandas** pour les calculs ; **SQLAlchemy / psycopg 3** pour lire la base KPI
- **Exports : python-pptx** (PowerPoint), **openpyxl** (Excel)
- **Tâches longues (génération de rapports) :** Celery + Redis, ou django-q2 si on veut éviter Redis — [[À confirmer selon l'infra]]
- **Déploiement :** Docker Compose (app + base applicative + worker), derrière un reverse proxy (nginx), serveur interne [[nom/OS du serveur]]
- **Tests :** pytest + pytest-django ; jeux de données de test synthétiques (pas de données réelles dans le dépôt)

Deux bases distinctes :
1. **Base KPI existante** (PostgreSQL, accès **lecture seule** via un compte dédié) : `[[hôte]]`, `[[base]]`, `[[schéma]]`
2. **Base applicative** (PostgreSQL, gérée par Django) : utilisateurs, périmètres, référentiel importé, événements, catalogue KPI, historique des rapports

Secrets dans des variables d'environnement (`.env` non versionné, `.env.example` versionné).

---

## 3. Données sources

### 3.1 Tables KPI (PostgreSQL)
- LTE : `[[nom table/vue LTE horaire]]` — granularité `[[horaire / 15 min]]`, clé cellule `[[colonne]]`, horodatage `[[colonne]]`
- WCDMA : `[[nom table/vue WCDMA horaire]]`
- Vues existantes réutilisables : `vw_calendar_hour`, vues LTE/WCDMA mensuelles, vue de remapping des noms de cellules WCDMA

### 3.2 Pièges connus (à gérer explicitement)
- Les noms de sites diffèrent entre technologies : jointure LTE ↔ WCDMA sur une clé **Trigramme (3 caractères)**
- Suffixes ERBS `e` / `bb` (avant / après migration DUS → Baseband) : un même site peut apparaître sous deux noms selon la période
- Cellules manquantes entre périodes comparées : les signaler, ne pas les masquer
- Coupures (ex. panne WCDMA) : distinguer « pas de données » de « valeur nulle »

### 3.3 Référentiel (fichier xlsx)
Le fichier `[[nom du fichier]].xlsx` fait le lien entre les tables : cellule ↔ secteur ↔ site ↔ trigramme ↔ commune ↔ [[province / zone / autre]].
Colonnes : `[[liste des colonnes]]`

**Ne pas interroger le xlsx en direct.** Le charger dans une table `ref_cell` de la base applicative via une commande d'import (`manage.py import_referentiel <fichier>`) :
- validation (doublons, cellules orphelines, communes inconnues) avec rapport d'erreurs lisible
- historisation : chaque import est versionné (date, auteur, nb de lignes, diff ajouts/suppressions)
- upload possible depuis l'admin Django

**Plus tard — SharePoint :** prévoir une interface `ReferentielSource` avec une implémentation `FichierLocal` (MVP) et une implémentation `SharePointGraph` (Microsoft Graph API, app registration Entra ID en client credentials, permission `Sites.Selected` sur le seul site concerné). Synchronisation planifiée (quotidienne). Ne pas implémenter SharePoint dans le MVP, seulement l'interface.

---

## 4. Catalogue de KPI

Les KPI sont définis **dans un fichier de configuration (YAML) versionné**, pas en dur dans le code. Pour chaque KPI :

```yaml
- code: lte_dl_user_thp
  libelle: Débit DL utilisateur moyen
  techno: LTE
  unite: Mbps
  numerateur: "[[colonne volume DL]]"
  denominateur: "[[colonne temps de transfert DL]]"
  facteur: [[facteur de conversion]]
  sens: haut_est_mieux        # ou bas_est_mieux
  seuils: { alerte: 10, critique: 5 }
  categorie: debit
```

Catégories minimales : **débit** (DL/UL), **trafic** (volume, utilisateurs RRC), **accessibilité** (RRC/ERAB setup success), **retainability / drop** (ERAB drop rate, call drop 3G), **congestion / charge** (PRB DL utilisation, rejets), **mobilité** (HO success), **disponibilité** cellule.
Formules exactes : `[[à fournir — lexiques KPI LTE et WCDMA existants]]`

### Règle d'agrégation (critique)
Toujours agréger en **ratio de sommes**, jamais en moyenne de ratios :
`taux_drop = Σ drops / Σ releases` sur le périmètre et la période, pas `moyenne(taux_drop_horaire)`.
Le moteur de calcul doit donc remonter numérateurs et dénominateurs séparément, puis diviser après agrégation (temps et espace). Écrire des tests unitaires qui vérifient cette règle.

### Heure chargée
Fenêtres configurables : `18h–22h`, `7h–20h`, journée complète, ou « heure chargée par cellule » (heure de trafic max). Paramètre de chaque requête.

---

## 5. Modèle de requête unique

Toute demande (formulaire aujourd'hui, langage naturel demain, API éventuellement) produit le même objet :

```json
{
  "techno": ["LTE"],
  "perimetre": { "type": "commune", "valeurs": ["[[commune]]"] },
  "periode": { "debut": "2026-09-01", "fin": "2026-09-30" },
  "granularite_temps": "jour",
  "granularite_espace": "secteur",
  "fenetre_horaire": "18-22",
  "kpis": ["lte_dl_user_thp", "lte_erab_drop", "lte_prb_dl_util"],
  "comparaison": { "type": "periode_precedente" }
}
```

- `perimetre.type` : `commune`, `site`, `trigramme`, `cellule`, `secteur`, `evenement`, `zone_personnalisee`
- `granularite_temps` : `heure`, `jour`, `semaine`, `mois`
- `granularite_espace` : `global`, `commune`, `site`, `secteur`, `cellule`
- `comparaison` : `aucune`, `periode_precedente`, `meme_periode_annee_n-1`, `reference_personnalisee`

Valider avec Pydantic. **Le périmètre demandé est toujours intersecté avec le périmètre autorisé de l'utilisateur** côté serveur (§7).

---

## 6. Analyse d'événement

Entité `Evenement` (gérée dans l'admin et via un écran dédié) :
- nom, description, date/heure début et fin
- liste de cellules/secteurs concernés (sélection depuis le référentiel, par site + secteur ; [[carte si coordonnées GPS disponibles dans le référentiel]])
- période de référence : par défaut **même jour de semaine et même créneau sur les 4 semaines précédentes**, modifiable

Sortie de l'analyse :
1. Tableau de synthèse par KPI : valeur événement, valeur référence, écart %, statut (OK / alerte / critique)
2. Courbes horaires événement vs référence (bande min–max de la référence)
3. **Liste des anomalies détectées**, triée par gravité :
   - dépassement de seuil absolu (catalogue KPI)
   - écart significatif à la référence (ex. > 2 écarts-types ou > X %, paramétrable)
   - cellule indisponible / sans données sur un créneau
   - saturation : PRB DL > 90 % (paramétrable) combinée à un débit < 10 Mbps
4. Classement des secteurs les plus dégradés

Les règles de détection sont des fonctions isolées et testées, avec seuils dans la configuration.

---

## 7. Utilisateurs et droits

Rôles :
- **Admin** : tout, gestion des utilisateurs, import référentiel, catalogue KPI
- **Analyste** : tout le réseau en lecture, création d'événements, génération de rapports
- **Lecteur restreint** : uniquement son périmètre (ex. une ou plusieurs communes, une liste de sites), uniquement certains KPI [[à confirmer : clients externes ? services internes ?]]

Modèle : `Perimetre` (ensemble de communes / sites / cellules) rattaché à un utilisateur ou un groupe ; liste blanche de KPI optionnelle par groupe.

Règles :
- Le filtrage par périmètre est fait **côté serveur** dans la couche d'accès aux données, une seule fonction centrale, couverte par des tests (un lecteur restreint ne doit jamais obtenir une cellule hors périmètre, même en forgeant la requête)
- Journal d'audit : qui a demandé quoi, quand
- Authentification : comptes Django pour le MVP ; prévoir SSO **[[AD/LDAP ou Entra ID OIDC — à confirmer avec la DSI]]** (django-auth-ldap ou mozilla-django-oidc)

---

## 8. Rapports et exports

- **Écran de résultat** : tableau + graphiques, filtres modifiables sans recharger
- **Export Excel** : données brutes + onglet synthèse
- **Export PowerPoint** (python-pptx), charte existante **bleu marine / ambre** :
  - slide titre (périmètre, période, date de génération)
  - slide synthèse (tableau KPI + statuts)
  - une slide par KPI ou catégorie (graphique + commentaire automatique factuel : « Débit DL moyen 23,4 Mbps, −12 % vs période précédente »)
  - slide anomalies (pour un événement)
  - slide annexe : cellules manquantes / données absentes
  - format au niveau secteur ET version simplifiée au niveau site (deux modes)
- Génération en tâche de fond si longue, avec historique des rapports téléchargeables
- **Modèles de rapport sauvegardés** : un utilisateur enregistre une requête (§5) pour la relancer, éventuellement planifiée (ex. rapport mensuel automatique le 1er du mois)

---

## 9. Évolution future : saisie en langage naturel (hors MVP)

Prévoir un module `parseur_demande` qui transforme un texte en objet de requête §5, avec deux implémentations interchangeables :
1. **Parseur à règles (à faire en V2, sans IA)** : dictionnaires des communes, sites, KPI (synonymes FR : « débit », « drop », « coupure », « congestion », « saturation »), mois et expressions de dates (« septembre », « la semaine dernière », « le week-end du 14 »). Retourne la requête + les éléments non compris, et l'utilisateur valide le formulaire pré-rempli avant exécution.
2. **Parseur LLM (optionnel, si autorisé par la DSI)** : le modèle ne fait que produire le JSON de requête validé par Pydantic ; il ne génère jamais de SQL et ne reçoit jamais les données KPI.

Dans les deux cas : le formulaire pré-rempli est affiché pour validation avant exécution.

---

## 10. Performance

- Index sur (cellule, horodatage) sur les tables sources si absents — **proposer** les index, ne pas les créer sans accord (base partagée)
- Agrégats journaliers par cellule (numérateurs/dénominateurs) en vues matérialisées ou tables d'agrégats dans la base applicative, rafraîchis quotidiennement
- Cache des résultats de requêtes identiques (clé = hash de la requête §5 + périmètre)
- Objectif : réponse < 5 s pour une commune sur un mois en granularité jour

---

## 11. Phasage

1. **Phase 0** : exploration du schéma en lecture seule, document `docs/schema.md` décrivant tables, colonnes utiles, granularité, volumétrie ; questions ouvertes
2. **Phase 1 (MVP)** : import référentiel, catalogue KPI (5–6 KPI LTE), moteur de calcul avec règle d'agrégation testée, formulaire + écran de résultat, rôles + périmètres, export Excel
3. **Phase 2** : événements + détection d'anomalies, export PowerPoint, WCDMA
4. **Phase 3** : rapports sauvegardés et planifiés, SSO, interface SharePoint
5. **Phase 4** : parseur langage naturel à règles

Livrer chaque phase fonctionnelle et testée avant la suivante. README avec installation, lancement et ajout d'un KPI.

---

## 12. Contraintes

- Aucune écriture dans la base KPI source
- Aucune donnée réelle ni identifiant dans le dépôt Git
- Interface et libellés en français ; code et noms de variables en anglais ou français mais cohérents
- Pas de dépendance à un service cloud externe dans le MVP
