# Contrôle des endpoints : 12 octobre 2026

Contrôle effectué sur la version intégrant l'interface et les rapports PDF de `main`
(commit `4d3843e`), avec le cache des recherches et les corrections ci-dessous.

## Périmètre

Les tests passent par le client HTTP de Django avec les middlewares de session,
authentification et contrôle d'accès. Les tests CSRF activent explicitement cette
protection. Les données sont synthétiques, dans des bases et répertoires de tests.

| Routes | Contrôles |
|---|---|
| `/`, `/suggestions/` | GET/HEAD, paramètres invalides, périmètres, base KPI indisponible, accueil sans cellule accessible |
| `/evenements/`, `/evenements/<id>/` | Visibilité selon les cellules, sites et secteurs autorisés, événement absent/inaccessible, erreur de source |
| `/rapports/` | Historique propre à l'utilisateur, messages d'échec sans détails techniques |
| `/rapports/requete/`, `/rapports/evenement/<id>/` | POST, CSRF, format/paramètres, panne de file d'attente, génération PDF/Excel/PowerPoint |
| `/rapports/<id>/telecharger/` | Propriétaire, état terminé, fichier manquant, Content-Type, téléchargement et ouverture du fichier produit |
| `/rapports/enregistrer/` | Formulaire, validation, création, restriction des méthodes HTTP |
| `/rapports/enregistres/<id>/{lancer,basculer,supprimer}/` | POST, CSRF, propriété, identifiant absent, requête enregistrée devenue invalide |
| `/connexion/`, `/deconnexion/` | Authentification, méthodes, CSRF et refus des redirections externes |
| `/admin/` | Routes générales et sections ; liste, ajout, modification, historique et suppression des 17 modèles, selon trois profils |
| Anciennes URL d'administration | Redirection vers les pages de modification |
| `/favicon.ico`, routes inconnues | Réponses 204/404 |
| `/static/…` | CSS et JavaScript servis par WhiteNoise après collectstatic avec DEBUG désactivé |

Un test d'inventaire vérifie que toutes les routes applicatives nommées sont
représentées dans la matrice. Les routes d'administration des modèles sont
énumérées depuis le registre Django ; les cas métiers existants complètent ce
contrôle transversal.

## Corrections apportées

- Les recherches et analyses d'événements renvoient une page d'indisponibilité
  avec HTTP 503 lors d'une erreur SQLAlchemy, sans exposer les détails de connexion.
- Liste, détail, création de rapport et génération des événements appliquent le
  périmètre d'accès. Une recherche avancée ne distingue plus un événement inaccessible
  d'un nom inconnu. Les droits sont également revérifiés au moment de la génération.
- L'accueil gère les KPI autorisés dont aucune cellule n'est accessible.
- Un rapport enregistré invalide produit un message utile, au lieu d'une erreur 500.
- Une panne de mise en file marque le rapport en erreur, au lieu de le laisser en
  attente indéfiniment ; les détails des échecs de génération restent dans les logs.
- Les endpoints de consultation refusent POST/PUT/PATCH/DELETE ; l'enregistrement
  de rapports conserve GET/HEAD/POST et les actions conservent POST uniquement.
- Le journal d'audit de l'administration accepte une ancienne entrée malformée.
- Les réglages d'anomalies exigent la permission d'ajout. Une consultation sans
  permission ne crée plus les réglages ni les seuils KPI avant de refuser l'accès.

## Résultats

- 424 scénarios dans la matrice des endpoints.
- 1 034 tests réussis sur la suite complète, en 45 secondes environ.
- Contrôles Django, migrations manquantes et espaces du diff : aucun problème détecté.

## Reproduire

```bash
pip install -r requirements-dev.txt
pytest -q tests/test_endpoints.py
pytest -q
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --check
```

Les tests de génération exécutent réellement les tâches et ouvrent les fichiers
produits. Le broker et les pannes sont simulés. Ce contrôle ne constitue pas une
mesure du serveur de production, de sa base PostgreSQL distante ni de son worker
réel. La mise en service doit appliquer les dépendances et migrations de la version
récente (dont la migration des formats PDF), puis redémarrer les processus.
