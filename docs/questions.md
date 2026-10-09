# Prérequis et questions ouvertes

Ce qui bloque (🔴), ce qui est nécessaire pour la phase 1 (🟠), ce qui peut attendre (🟢).
Les hypothèses retenues en attendant sont indiquées.

## 🔴 Bloquant

1. **Accès à la base KPI** — ✅ identifiants reçus (à mettre dans `.env`, jamais dans Git).
   La base est sur le réseau interne : injoignable depuis l'environnement de développement
   cloud. → Lancer `python scripts/explorer_schema.py` depuis un poste du réseau et
   fournir le `docs/schema_bdd.md` produit (métadonnées uniquement).
   ✅ Le compte est limité en lecture seule côté serveur.
2. ✅ **Compteurs bruts** : absents de la base (colonnes identiques aux CSV). Les KPI
   approximatifs le restent sauf si une autre source existe. Question initiale : les tables exposent-elles (ou une autre table expose-t-elle)
   les compteurs `pm*` derrière les ratios ? Sinon, le lexique KPI LTE/WCDMA (formules)
   pour savoir quoi demander. Sans eux, E-RAB drop, CS drop et PRB restent approximatifs.
   *Hypothèse : pondérations décrites dans `config/kpi_catalogue.yaml` (champ `qualite`).*
3. ✅ **Données dans le dépôt** : le xlsx et les 4 CSV restent dans le dépôt comme référence.

## 🟠 Phase 1

4. **Nommage des cellules** — confirmer :
   - ✅ LTE : `XXXeS` = porteuse 1, secteur S ; `XXXePS` = porteuse P + 1, secteur S.
     Site à 3 secteurs : e4 = e1, e5 = e2, e6 = e3 (couche supplémentaire ou site déporté,
     ce dernier avec son propre trigramme). Site à 4 secteurs : e4 = secteur 4.
   - ✅ WCDMA : secteur 1 = A/D/G/J, 2 = B/E/H/K, 3 = C/F/I/L (porteuses 1 à 4) ;
     site à 4 secteurs : A/B/C/D porteuse 1, J/K/L/M porteuse 2.
   - ✅ Secteur du reporting = secteur physique du site, toutes technos et porteuses
     confondues (ex. secteur 1 d'Aiguade : AIG101A/D/J, AIGe1/e11/e21), déduit des noms de
     cellules ; site rattaché par le trigramme dans `Site_File` (`Cell_File` non utilisé).
   - ✅ Passage de 3 à 4 secteurs (DTS009, MDO355) : D/E/F = secteurs 1-3 avant, D = secteur 4
     ensuite, E et F sans statistiques. Date : `manage.py detecter_bascules` (1re apparition
     de e4 / M dans la base KPI) ou admin → Sites.
   - Sites détectés à 4 secteurs (`nbSect` = 4, cellule M, ou e1 à e4 sur une porteuse LTE) :
     BAU472, DTS009, LEB353, MDO355, NES466, PRB220, ROC735, SLR682, TSI667. Liste à valider
     (BAU472 et NES466 sont déclarés à 3 secteurs dans `Site_File`).
5. ✅ **Trigrammes partagés** (3VL, CHT, NKA) : le premier site du fichier fait foi (provisoire).
5 bis. **Trous du référentiel** : 0,3 % des cellules 4G (trigrammes EXP, OHP) et 1,7 % des
   cellules 3G (EXP099, MB2997, MB3998, MBN999, MCO060, OHP527) n'ont pas de site dans
   `Site_File` — la liste est dans l'historique des imports (admin). À compléter dans le xlsx ?
6. ✅ **Unités** : `PayloadDl_mB` et `PayloadPsHs_mb` sont tous deux en mégaoctets.
7. ✅ **Seuils** : valeurs provisoires conservées, réglables dans l'admin (Seuils KPI).
8. **Liste des 5-6 KPI LTE du MVP** : proposition = débit DL, débit UL, volume DL,
   RRC SR, E-RAB drop, PRB DL, HO intra, disponibilité.
9. ✅ **Historique** : horaire ≈ 14 mois, journalier depuis 2020 ; chargement horaire (H-1)
   et journalier (J-1) d'après les bornes observées.
10. ✅ **Fuseau** : horodatages déjà en heure locale (GMT+11, Nouvelle-Calédonie), sans conversion.
10 bis. **Données de base** (cf. `docs/donnees_de_base.md`) — à confirmer :
   - ✅ `RabDropCsMissRel_p` : coupure due à une relation de voisinage 3G manquante.
   - Causes de coupure voix 3G : elles n'expliquent qu'~54 % des coupures. Existe-t-il
     d'autres colonnes ou compteurs (ex. `pmNoSysRelSpeech*`) pour le reste ?
   - ✅ `SpeechTrafficDay_erlg` journalier = somme des Erlangs horaires (Erl·h) : la durée
     moyenne d'appel qui en découle (≈ 2 min) est cohérente.
   - ✅ SMS : seul `ReqSms` (3G) existe, pas de statistique de SMS en 4G. Pas de compteur
     VoLTE : en 4G, la voix n'est visible qu'en CSFB.
   - Seuils provisoires des nouveaux KPI (taux d'accès 98 / 95 %, drop data 3G 2 / 5 %).

## 🟢 Plus tard

11. ✅ Tâches de fond : **django-q2** (pas de Redis), service `worker` dans Docker Compose.
12. Serveur cible (OS, Docker disponible ?, reverse proxy existant ?).
13. SSO : AD/LDAP ou Entra ID OIDC.
14. Lecteurs restreints : clients externes ou services internes ?
15. ✅ Onglet `Cluster` : importé une fois comme événements initiaux (`import_clusters`),
    non réutilisé ensuite. `Type` (Concert / Day) = nature du créneau ; un événement
    peut couvrir plusieurs jours avec des horaires différents → créneaux multiples.
    37 noms distincts, dont des quasi-doublons à fusionner dans l'admin
    (ex. « Foire de Ponerihouen » / « Foire de Ponérihouen »).
16. ✅ **Charte PowerPoint** : modèle Helia PRO fourni (`config/modele_rapport.pptx`).
17. ✅ Référence d'un événement : mêmes jours et heures des 4 semaines précédentes
    (modifiable par événement). Anomalies : écart > 2 σ et > 20 %, saturation
    PRB DL > 90 % avec débit < 10 Mbps, cellule sans données (réglables dans l'admin).
