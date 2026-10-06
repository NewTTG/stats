# Prérequis et questions ouvertes

Ce qui bloque (🔴), ce qui est nécessaire pour la phase 1 (🟠), ce qui peut attendre (🟢).
Les hypothèses retenues en attendant sont indiquées.

## 🔴 Bloquant

1. **Accès à la base KPI** : hôte, base, schéma, compte lecture seule, et noms exacts des
   tables/vues (horaire, journalière, mensuelle ; `vw_calendar_hour` ; vue de remapping
   WCDMA). *En attendant : développement sur les CSV et sur des données synthétiques.*
2. **Compteurs bruts** : les tables exposent-elles (ou une autre table expose-t-elle)
   les compteurs `pm*` derrière les ratios ? Sinon, le lexique KPI LTE/WCDMA (formules)
   pour savoir quoi demander. Sans eux, E-RAB drop, CS drop et PRB restent approximatifs.
   *Hypothèse : pondérations décrites dans `config/kpi_catalogue.yaml` (champ `qualite`).*
3. **Données dans le dépôt** : le brief interdit les données réelles dans Git (§12), or
   le xlsx et les 4 CSV sont commités. Souhaites-tu qu'on les retire (et qu'on purge
   l'historique) ? Le `.gitignore` les exclut désormais pour les ajouts futurs.

## 🟠 Phase 1

4. **Nommage des cellules** — confirmer :
   - LTE `XXXeN` = porteuse 0, secteur N ; `XXXePS` = porteuse P, secteur S ?
   - WCDMA lettres : A/B/C, D/E/F, J/K/L = porteuses 1/2/3 ; G/H/I = secteurs 4-6 ?
   - Que représente la notion de « secteur » pour le reporting : `Cell_File.cells` ?
5. **Trigrammes partagés** (3VL, CHT, NKA) : faut-il les distinguer et comment ?
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
