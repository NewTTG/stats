# Phase 0 — Description des données sources

> Établi à partir des extraits CSV, du référentiel xlsx et de l'exploration de la base
> KPI (`docs/schema_bdd.md`, généré par `scripts/explorer_schema.py`).

## 0. Base KPI PostgreSQL — synthèse

PostgreSQL 17.5, schéma `public`, accès lecture seule.

| Table | Lignes | Historique | Clé unique (index) |
|---|---|---|---|
| `lte_cell_hour` | 16,1 M | 2025-08-13 → aujourd'hui | (`DateHour`, `EutranCell_Id`) + index sur chaque colonne |
| `lte_cell_day` | 3,1 M | 2020-02-27 → J-1 | (`DateDay`, `EutranCell_Id`) + index (`ERBS_Id`, `DateDay`) |
| `wcdma_cell_hour` | 12,9 M | 2025-07-31 → aujourd'hui | (`DateHour`, `CellWcdma`) + index cellule, date, site |
| `wcdma_cell_day` | 3,4 M | 2020-10-01 → J-1 | (`CellWcdma`, `DateDay`) + index cellule, date, site |

- Colonnes **identiques** aux extraits CSV (144 LTE, 127 WCDMA) : le catalogue KPI
  s'applique tel quel. **Aucun compteur brut supplémentaire** en base : les KPI marqués
  `reconstruit` / `approx` le restent.
- Horaire : historique d'environ 14 mois ; au-delà, seules les tables journalières existent.
- Index existants suffisants pour filtrer par période + liste de cellules : **aucun index
  à proposer**.
- Agrégats existants par site (`*_rbs_*`), zone (`lte_tac_*`, `wcdma_lac_*`), RNC et
  réseau : ratios calculés par l'OSS au bon niveau, utilisables pour les vues globales.
- Autres tables : GSM (`gsm_*`), voisinages / handovers (`lte_neigh_day`, `wcdma_*ho_day`),
  états de cellules ENM, alarmes, `ref_sites` (576 lignes), `ref_cells` (vide).
- `vw_calendar_hour` ne couvre que les 2 derniers mois ; `vw_lte_wcdma_aug2026` est une
  vue ponctuelle (événement août 2026, jointure LTE/WCDMA par 3 premiers caractères).
- Horodatages `timestamp without time zone` : heure locale de Nouvelle-Calédonie (GMT+11), **confirmé** : aucune conversion.

## 1. Tables KPI

| Extrait | Table supposée | Clé cellule | Clé site | Zone | Horodatage | Lignes extrait | Colonnes |
|---|---|---|---|---|---|---|---|
| `lte_cell_hour.csv` | LTE horaire | `EutranCell_Id` | `ERBS_Id` | `Tac` | `DateHour` (`2026-09-17 00:00:00.000`) | 2 007 cellules × 1 h | 144 |
| `lte_cell_day.csv` | LTE journalière | `EutranCell_Id` | `ERBS_Id` | `Tac` | `DateDay` (`2024-08-01`) | 1 529 cellules × 1 j | 144 |
| `wcdma_cell_hour.csv` | WCDMA horaire | `CellWcdma` | `SiteWcdma` | `LAC` | `DateHour` | 1 915 cellules × 1 h | 127 |
| `wcdma_cell_day.csv` | WCDMA journalière | `CellWcdma` | `SiteWcdma` | `LAC` | `DateDay` | 1 686 cellules × 1 j | 127 |

Format : séparateur `;`, valeurs entre guillemets, décimale `.`, aucune valeur vide
dans les extraits. Toutes les colonnes de mesure sont numériques.

Volumétrie estimée (à confirmer en base) : ~2 000 cellules LTE × 24 h ≈ 48 000 lignes/jour,
≈ 17,5 M lignes/an pour LTE horaire ; ordre de grandeur similaire pour WCDMA.

### 1.1 Nature des colonnes

Suffixes : `_p` pourcentage, `_kbps` débit, `_mB` / `_kB` volume, `_nb` nombre,
`_erlg` Erlang, `_dBm` / `_dB` puissance, préfixe `pm*` compteur Ericsson brut.

**Constat majeur** : la plupart des KPI sont livrés **déjà calculés** (ratios `_p`,
débits `_kbps`) sans leurs numérateur / dénominateur. Or la règle du brief impose
d'agréger en ratio de sommes. Situation par KPI (cf. `config/kpi_catalogue.yaml`) :

| KPI | Calcul possible | Qualité |
|---|---|---|
| RRC setup SR LTE | `pmRrcConnEstabSucc / pmRrcConnEstabAtt` | exact (écart < 0,2 % en moyenne avec `RrcSetupSuccRate_p`) |
| Volume DL/UL, trafic voix | somme | exact |
| Débit utilisateur DL/UL, HSDPA | temps reconstruit = volume / débit | reconstruit |
| HO intra-fréquence | ratio × `pmHoPrepAttLteIntraF` | reconstruit |
| E-RAB drop, CS drop 3G | pondéré par E-RAB établis / appels voix | **approximatif** |
| PRB DL, disponibilité | moyenne par cellule-période | **approximatif** (PRB) |

Les colonnes `Max_max` (ex. `RrcConnMax_max_nb`) s'agrègent en **max**, pas en somme.

## 2. Référentiel `OPT_Network_Database_V2.xlsx`

| Onglet | Lignes | Rôle | Colonnes clés |
|---|---|---|---|
| `Site_File` | 588 | un site physique | `codeSite`, `Trigramme`, `commune` (33), `region` (NORD, SUD, GRD NEA 1, NEA, ILES), `siteNameWcdma`, `siteNameLte`, `RBS_Name_3G`, `ERBS`, `lonWgs84`/`latWgs84`, `nbSect`, `bandType` |
| `Cell_File` | 1 391 | un **secteur** (`cells` = `codeSite` + n° secteur) | `cells`, `codeSite`, `commune`, `province` (SUD, NORD, ILES), `azimut`, `NbCarrierLte`, `nbCarrierWcdma`, `Trigramme` |
| `Cluster` | 342 | cellules par **événement** (24 clusters : carnaval, foires…) | `Cluster`, `RBS`, `Trigramme`, `Cellule`, `Type` (Concert / Day) |

Coordonnées GPS disponibles → carte possible pour la sélection de cellules.

## 3. Jointures KPI ↔ référentiel

### LTE
`EutranCell_Id` = `<Trigramme>e<S>` (porteuse 1) ou `<Trigramme>e<P><S>` (porteuse P + 1),
S = secteur — **confirmé**. Ex. site DZU (3 porteuses) : `DZUe1..3` (porteuse 1),
`DZUe11..13` (porteuse 2), `DZUe21..23` (porteuse 3). Sur un site à 3 secteurs,
e4 = e1, e5 = e2, e6 = e3 (et e7-e9 de même) : couche supplémentaire (RAVe4) ou site
déporté, qui porte toujours son propre trigramme (ACRe4/e5/e6 = secteurs 1 à 3 d'ACR ;
Cell_File les numérote aussi 4 à 6). Sur un site à 4 secteurs, e4 = secteur 4.
→ 99,9 % des préfixes trouvent un `Trigramme` dans `Site_File`.
`ERBS_Id` correspond à la colonne `ERBS` dans 97,9 % des cas.

### WCDMA
`CellWcdma` = `<codeSite><lettre>` — **confirmé** : secteur 1 = A/D/G/J, secteur 2 = B/E/H/K,
secteur 3 = C/F/I/L (porteuses 1 à 4). Site à 4 secteurs (ex. DTS009) :
A/B/C/D = secteurs 1-4 porteuse 1, J/K/L/M = secteurs 1-4 porteuse 2. Un site compte
4 secteurs si Site_File le déclare (`nbSect` = 4), si Cell_File liste ses secteurs 1 à 4
ou s'il porte une cellule M. Ex. secteur 1 d'Aiguade : AIG101A, AIG101D, AIG101J (3G),
AIGe1, AIGe11, AIGe21 (4G).
→ 98,1 % des préfixes trouvent un `codeSite`. Non trouvés : ex. `EXP099*`, `FLA384*`.

### Résultat de l'import (`import_referentiel` sur le xlsx + les 4 extraits)
588 sites, 1 383 secteurs ; cellules rattachées à un secteur : LTE 1 958 / 2 044,
WCDMA 1 914 / 1 990 (≈ 96 %). Les non-rattachées correspondent à des sites ou secteurs
absents de `Cell_File` et sont listées dans l'historique de l'import.

### Pièges relevés
- `Trigramme` **non unique** : `3VL` (2 sites), `CHT` (3 sites), `NKA` (2 sites). La
  jointure LTE par trigramme seul est donc ambiguë : règle provisoire, le premier site
  du fichier fait foi.
- Suffixes `bb` / `e` dans les noms ERBS (`TIARIbb`, `KARIKATEe`) et `s` (`3_VALLEESbbs`).
- Secteur `BGV0021` en double dans `Cell_File`.
- Onglet `Cluster` : noms de cellules mixtes LTE (`ZIZe3`) / WCDMA (`ZIZ179C`) et
  `RBS` avec espaces (`PIC MARTIN`) au lieu de `_` ; seules 260 / 342 cellules
  se retrouvent dans les extraits horaires.
- `UlLoad_p` WCDMA ≈ 100 % partout (à vérifier : métrique ou artefact).
