# Phase 0 — Description des données sources

> Établi à partir des **extraits CSV** et du référentiel xlsx fournis (pas encore d'accès
> à la base PostgreSQL). À compléter dès que l'accès lecture seule est ouvert.

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
`EutranCell_Id` = `<Trigramme>e<N>` ou `<Trigramme>e<P><S>` (P = porteuse, S = secteur).
Ex. site DZU (3 porteuses) : `DZUe1..3`, `DZUe11..13`, `DZUe21..23`.
→ 99,9 % des préfixes trouvent un `Trigramme` dans `Site_File`.
`ERBS_Id` correspond à la colonne `ERBS` dans 97,9 % des cas.

### WCDMA
`CellWcdma` = `<codeSite><lettre>` (A/B/C, D/E/F, J/K/L… = porteuse × secteur).
→ 98,1 % des préfixes trouvent un `codeSite`. Non trouvés : ex. `EXP099*`, `FLA384*`.

### Pièges relevés
- `Trigramme` **non unique** : `3VL` (2 sites), `CHT` (3 sites), `NKA` (2 sites). La
  jointure LTE par trigramme seul est donc ambiguë pour ces sites.
- Suffixes `bb` / `e` dans les noms ERBS (`TIARIbb`, `KARIKATEe`) et `s` (`3_VALLEESbbs`).
- Secteur `BGV0021` en double dans `Cell_File`.
- Onglet `Cluster` : noms de cellules mixtes LTE (`ZIZe3`) / WCDMA (`ZIZ179C`) et
  `RBS` avec espaces (`PIC MARTIN`) au lieu de `_` ; seules 260 / 342 cellules
  se retrouvent dans les extraits horaires.
- `UlLoad_p` WCDMA ≈ 100 % partout (à vérifier : métrique ou artefact).
