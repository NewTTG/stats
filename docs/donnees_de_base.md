# Données de base — appels, SMS, coupures, accès

Ce que l'on peut répondre aux questions courantes (« combien d'appels », « le drop 3G »,
« pourquoi ça coupe », « le taux d'accès 4G »…) avec les colonnes des tables KPI, et avec quelle
fiabilité. Établi et vérifié sur les 4 extraits CSV, dont les colonnes sont identiques à
celles de la base. Les formules sont dans `config/kpi_catalogue.yaml` ; les vérifications
sont automatisées dans `tests/test_donnees_de_base.py`.

Rappel : toute agrégation se fait en **ratio de sommes**. Un KPI composite (taux d'accès)
est le **produit des ratios de sommes** de ses étapes, jamais une moyenne de produits.

Qualité : **exact** = compteurs bruts ; **reconstruit** = dénominateur déduit d'un ratio
publié et d'un compteur de tentatives (fidèle) ; **approx** = pondération de substitution
faute du vrai dénominateur.

## 1. Correspondance besoin → KPI

| Besoin | Techno | KPI (code) | Formule | Qualité |
|---|---|---|---|---|
| **Appels voix** établis | 3G | `wcdma_appels_voix` | Σ `NbrSpeechCalls` | exact |
| Tentatives d'appel | 3G | `wcdma_tentatives_voix` | Σ `NbrSpeechCallsAtt` | exact |
| Trafic voix | 3G | `wcdma_speech_traffic` | Σ `SpeechTrafficDay_erlg` (Erl·h) | exact |
| Durée moyenne d'appel | 3G | `wcdma_duree_appel` | Σ Erl·h × 3600 / Σ `NbrSpeechCalls` | reconstruit |
| Appels émis/reçus en 4G | 4G | `lte_csfb_appels` | Σ (`CsfbRelVolWcdma_nb` + `CsfbRelVolGsm_nb`) | exact |
| **SMS** | 3G | `wcdma_sms` | Σ `ReqSms` | exact |
| **Taux d'accès voix** | 3G | `wcdma_cssr_cs` | RRC voix × RAB voix | exact |
| ↳ étape RRC voix | 3G | `wcdma_rrc_cs_sr` | Σ `ReqCsSucc` / Σ `ReqCs` | exact |
| ↳ étape RAB voix | 3G | `wcdma_rab_cs_sr` | Σ `NbrSpeechCalls` / Σ `NbrSpeechCallsAtt` | exact |
| **Taux d'accès data** | 3G | `wcdma_cssr_ps` | RRC data × RAB data | exact |
| ↳ étape RRC data | 3G | `wcdma_rrc_ps_sr` | Σ `ReqPsSucc` / Σ `ReqPs` | exact |
| ↳ étape RAB data | 3G | `wcdma_rab_ps_sr` | Σ `pmNoRabEstablishSuccessPacketInteractive` / Σ `…AttemptPacketInteractive` | exact |
| **Taux d'accès 4G** | 4G | `lte_acces` | RRC × S1 × E-RAB initial | reconstruit |
| ↳ étape RRC | 4G | `lte_rrc_setup_sr` | Σ `pmRrcConnEstabSucc` / Σ `pmRrcConnEstabAtt` | exact |
| ↳ étape S1 | 4G | `lte_s1_sig_sr` | `S1signalingSuccRate_p` pondéré par `pmS1SigConnEstabAtt` | reconstruit |
| ↳ étape E-RAB initial | 4G | `lte_init_erab_sr` | `InitErabSuccRate_p` pondéré par `pmErabEstabAttInit` | reconstruit |
| **Drop voix** | 3G | `wcdma_cs_drop` | `RabDropCs_p` pondéré par `NbrSpeechCalls` | approx |
| Drop data | 3G | `wcdma_ps_drop` | `RabDropPs_p` pondéré par les RAB data établis | approx |
| **Drop 4G** (E-RAB) | 4G | `lte_erab_drop` | `ErabDropRate_p` pondéré par `ErabEstabSucc_nb` | approx |

## 2. Causes de coupure

Chaque cause est un KPI (`decomposition_de` = KPI parent), avec la **même pondération** que
le parent : la part de chaque cause s'additionne.

**4G** (`lte_erab_drop`) — vérifié : `ErabDropRate_p = ErabDropRateEnb_p + ErabDropRateMme_p`
(écart nul) et Σ causes eNB = `ErabDropRateEnb_p` (écart max 0,01). Les causes **somment
exactement** au taux de drop.

| Code | Cause | Colonne |
|---|---|---|
| `lte_drop_mme` | coupure demandée par le cœur de réseau (MME) | `ErabDropRateMme_p` |
| `lte_drop_radio` | perte radio du mobile | `ErabDropEnbUeLost_p` |
| `lte_drop_ho` | échec de handover | `ErabDropEnbHo_p` |
| `lte_drop_cellule_indispo` | cellule indisponible | `ErabDropEnbCellDt_p` |
| `lte_drop_transport` | panne transport | `ErabDropEnbTnFail_p` |
| `lte_drop_preemption` | préemption (haute priorité + standard) | `ErabDropEnbHpr_p + ErabDropEnbPe_p` |
| `lte_drop_licence` | limite de licence | `ErabDropEnbLic_p` |

**3G voix** (`wcdma_cs_drop`) — les causes publiées n'expliquent qu'**environ la moitié** des
coupures (54 % sur l’extrait journalier). Le reste est affiché **« non ventilé »** (= total −
Σ causes) ; il n'est pas réparti.

| Code | Cause | Colonne |
|---|---|---|
| `wcdma_drop_sho` | soft handover | `RabDropCsSho_p` |
| `wcdma_drop_perte_synchro` | perte de synchronisation radio | `RabDropCsOutOfSync_p` |
| `wcdma_drop_voisinage_manquant` | voisinage manquant (à confirmer) | `RabDropCsMissRel_p` |
| `wcdma_drop_ifho` | handover inter-fréquence | `RabDropCsIfho_p` |
| `wcdma_drop_irat` | handover vers la 2G | `RabDropCsIratho_p` |
| `wcdma_drop_congestion` | congestion | `RabDropCsRelCong_p` (toujours 0 sur l'extrait) |

## 3. Valeurs de référence (réseau entier, extraits CSV)

Utiles pour contrôler l'application : une requête « tout le réseau » sur la même date doit
redonner ces valeurs.

| KPI | Jour 01/08/2024 | Heure 17/09/2026 0h |
|---|---|---|
| Appels voix 3G établis | 2 172 890 | 2 064 |
| Appels 4G (CSFB) | 1 134 966 | 2 345 |
| SMS (3G) | 211 692 | 850 |
| Trafic voix (Erl·h) | 74 878 | 52,9 |
| Durée moyenne d'appel | 124 s | 92 s |
| Taux d'accès voix 3G | 99,44 % | 99,95 % |
| Taux d'accès data 3G | 99,26 % | 99,28 % |
| Taux d'accès 4G | 99,60 % | 99,58 % |
| Drop voix 3G | 0,45 % (dont 0,20 non ventilé) | 0,15 % |
| Drop data 3G | 1,88 % | 2,00 % |
| Drop 4G | 1,81 % | 1,48 % |
| ↳ dont MME / radio / HO | 1,52 / 0,27 / 0,02 % | 1,34 / 0,13 / 0,01 % |
| Disponibilité 4G (plafonnée) | 99,08 % | 98,99 % |
| Disponibilité 3G | 93,20 % | 96,20 % |

L'extrait horaire est pris à 0h (trafic de nuit) : il ne représente pas une heure chargée.

## 4. Vérifications effectuées

- Taux d'accès composites recalculés par cellule vs ratio publié : `PssrLte_p`, `CssrSp_p`,
  `CssrPs_p` → écart médian < 0,1 point. Les formules sont donc les bonnes.
- `ReqCsSucc / ReqCs = 100 − RrcFailedCs_p − RrcBlockingCs_p` et
  `NbrSpeechCalls / NbrSpeechCallsAtt = 100 − RabFailedCs_p − RabBlockingCs_p` (horaire :
  écart nul). Les causes d'échec d'accès 3G sont donc exploitables plus tard.
- Drop voix 3G horaire : sur les cellules à faible trafic, `RabDropCs_p × NbrSpeechCalls`
  retombe sur un nombre entier de coupures (ex. 1/7, 1/13). La pondération est donc
  pertinente, sans être exacte.

## 5. Limites et pièges

- **Pas de VoLTE ni de SMS 4G** dans les tables : en 4G, seuls les basculements CSFB sont
  comptés, et ces appels réapparaissent ensuite dans les appels 3G. **Ne pas additionner**
  appels 3G et CSFB.
- `CellAvaibilityD_p` (LTE, journalier) dépasse 100 % sur 170 / 1 529 cellules (max 248 %) :
  plafonné à 100 par cellule-période (`plafond`).
- `UlLoad_p` (3G) ≈ 100 % partout et `SpeechTrafficDayBest_erlg` a des valeurs négatives :
  colonnes non utilisées.
- Drops 3G/4G et PRB restent **approximatifs** tant que les compteurs de release ne sont pas
  disponibles (cf. `docs/questions.md`).
- Valeurs `Max_max` : à agréger en maximum, pas en somme (aucune n'est utilisée aujourd'hui).
