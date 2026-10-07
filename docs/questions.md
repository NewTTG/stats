# Prérequis et questions ouvertes

Ce qui bloque (🔴), ce qui est nécessaire pour la phase 1 (🟠), ce qui peut attendre (🟢).
Les hypothèses retenues en attendant sont indiquées.

## 🔴 Bloquant

1. **Accès à la base KPI** — ✅ identifiants reçus (à mettre dans `.env`, jamais dans Git).
   La base est sur le réseau interne : injoignable depuis l'environnement de développement
   cloud. → Lancer `python scripts/explorer_schema.py` depuis un poste du réseau et
   fournir le `docs/schema_bdd.md` produit (métadonnées uniquement).
   ✅ Le compte est limité en lecture seule côté serveur.
2. **Compteurs bruts** : les tables exposent-elles (ou une autre table expose-t-elle)
   les compteurs `pm*` derrière les ratios ? Sinon, le lexique KPI LTE/WCDMA (formules)
   pour savoir quoi demander. Sans eux, E-RAB drop, CS drop et PRB restent approximatifs.
   *Hypothèse : pondérations décrites dans `config/kpi_catalogue.yaml` (champ `qualite`).*
3. ✅ **Données dans le dépôt** : le xlsx et les 4 CSV restent dans le dépôt comme référence.

## 🟠 Phase 1

4. **Nommage des cellules** — confirmer :
   - ✅ LTE : `XXXeS` = porteuse 1, secteur S ; `XXXePS` = porteuse P + 1, secteur S.
   - ✅ WCDMA : secteur 1 = A/D/G/J, 2 = B/E/H/K, 3 = C/F/I/L (porteuses 1 à 4) ;
     site à 4 secteurs (lettre M) : A/B/C/D porteuse 1, J/K/L/M porteuse 2.
     Cas résiduels non décodables signalés à l'import (ex. DTS009E/F dans l'extrait 2024).
   - Que représente la notion de « secteur » pour le reporting : `Cell_File.cells` ?
5. ✅ **Trigrammes partagés** (3VL, CHT, NKA) : le premier site du fichier fait foi (provisoire).
5 bis. **Trous du référentiel** : ~4 % des cellules n'ont pas de secteur dans `Cell_File`
   (ex. EXP099, FLA384, NDI186, CGO491…) — la liste complète est dans l'historique
   des imports (admin). À compléter dans le xlsx ?
6. **Unités** : `PayloadDl_mB` = mégaoctets ? `PayloadPsHs_mb` (minuscule) = mégabits ?
7. **Seuils** d'alerte / critique par KPI (valeurs provisoires dans le catalogue).
8. **Liste des 5-6 KPI LTE du MVP** : proposition = débit DL, débit UL, volume DL,
   RRC SR, E-RAB drop, PRB DL, HO intra, disponibilité.
9. **Profondeur d'historique** en base et fréquence de chargement (temps réel ? J+1 ?).
10. **Fuseau** des horodatages (heure locale Nouméa supposée).

## 🟢 Plus tard

11. Tâches de fond : **django-q2** (pas de Redis) proposé par défaut — Celery si Redis déjà opéré.
12. Serveur cible (OS, Docker disponible ?, reverse proxy existant ?).
13. SSO : AD/LDAP ou Entra ID OIDC.
14. Lecteurs restreints : clients externes ou services internes ?
15. Onglet `Cluster` : à importer comme événements initiaux ? Que signifie `Type` (Concert / Day) ?
16. Charte PowerPoint : fournir un modèle `.pptx` (bleu marine / ambre).
