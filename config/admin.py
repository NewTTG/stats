"""Site d'administration du projet : espace séparé de l'application, rangé par usage.

Déclaré par ``config.apps.AdminStatsConfig`` (``default_site``) : ``admin.site`` et tous les
``@admin.register`` des applications désignent ce site.
"""

from datetime import timedelta
from urllib.parse import urlencode

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponseRedirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

# Sections du tableau de bord et du menu latéral : usage le plus fréquent d'abord, technique en dernier.
ORDRE_SECTIONS = ["evenements", "kpi", "comptes", "auth", "referentiel", "rapports", "django_q"]
# Ordre des modèles dans une section (les autres suivent, par ordre alphabétique).
ORDRE_MODELES = [
    "Evenement",
    "SeuilKpi", "ReglagesAnomalies",
    "User", "Group", "Perimetre", "DemandeSuivie", "JournalAudit",
    "Site", "Secteur", "Cellule", "ImportReferentiel",
    "RapportPlanifie", "Rapport",
    "Schedule", "Failure", "Success", "OrmQ",
]
# Regroupements sur le tableau de bord et dans le menu latéral (la page propre à chaque application,
# ex. /admin/auth/, reste celle de Django) : réglages de détection avec les seuils KPI, utilisateurs
# et groupes avec les périmètres. Sans droit sur la section cible, le modèle reste à sa place.
REGROUPEMENTS = {
    ("evenements", "ReglagesAnomalies"): "kpi",
    ("auth", "User"): "comptes",
    ("auth", "Group"): "comptes",
}


def _evenements_sans_creneau():
    from apps.evenements.models import Evenement

    return Evenement.objects.filter(creneaux__isnull=True).count()


# Raccourcis du tableau de bord : (titre, description, modèle, page, paramètres de la liste).
# Un raccourci n'est affiché que si l'utilisateur a le droit correspondant.
ACCES_RAPIDES = [
    ("Créer un événement", "Sites et secteurs sur carte, créneaux, KPI",
     "evenements.Evenement", "add", {}),
    ("Seuils KPI", "Seuils d'alerte et critiques",
     "kpi.SeuilKpi", "changelist", {}),
    ("Périmètres d'accès", "Communes, sites, cellules et KPI visibles",
     "comptes.Perimetre", "changelist", {}),
    ("Comptes utilisateurs", "Comptes avec mot de passe",
     "auth.User", "changelist", {}),
    ("Journal d'audit", "Recherches, exports, analyses et rapports",
     "comptes.JournalAudit", "changelist", {}),
]

# Menu latéral : rubriques par usage. Les modèles sans droit sont omis, une rubrique vide aussi ;
# un modèle enregistré mais absent d'ici est rangé dans « Autres ».
NAVIGATION = [
    ("Pilotage", ["index", "comptes.DemandeSuivie", "rapports.Rapport", "rapports.RapportPlanifie",
                  "comptes.JournalAudit"]),
    ("Analyse", ["evenements.Evenement", "kpi.SeuilKpi", "evenements.ReglagesAnomalies"]),
    ("Référentiel réseau", ["referentiel.ImportReferentiel", "referentiel.Site", "referentiel.Secteur",
                            "referentiel.Cellule"]),
    ("Comptes et accès", ["auth.User", "auth.Group", "comptes.Perimetre"]),
    ("Système", ["django_q.Schedule", "django_q.OrmQ", "django_q.Failure", "django_q.Success"]),
]
LIBELLES_NAVIGATION = {
    "referentiel.ImportReferentiel": "Chargement et imports",
    "evenements.ReglagesAnomalies": "Détection d'anomalies",
    "comptes.DemandeSuivie": "Suivi des demandes",
}

# Opérations faites en ligne de commande, depuis la racine du dépôt (rappel réservé à l'administration).
RAPPELS_COMMANDES = [
    ("Référentiel réseau (nouvelle version du xlsx, nouvelles cellules)",
     "python manage.py import_referentiel OPT_Network_Database_V2.xlsx --cellules-kpi"),
    ("Sites passés de 3 à 4 secteurs", "python manage.py detecter_bascules --enregistrer"),
    ("Sessions visiteur abandonnées (plus de 400 jours)", "python manage.py purger_visiteurs"),
]
RAPPEL_DEMO = ("Données de démonstration", "python manage.py charger_demo_kpi --jours 30")


def _rang(liste, valeur):
    return liste.index(valeur) if valeur in liste else len(liste)


class AdminStats(admin.AdminSite):
    site_header = "Stats réseau · Administration"
    site_title = "Stats réseau · Administration"
    index_title = "Tableau de bord"
    site_url = "/"  # lien « ← Retour aux statistiques » de l'en-tête

    def get_app_list(self, request, app_label=None):
        app_dict = self._build_app_dict(request, app_label)
        if app_label is None:
            for (source, nom), cible in REGROUPEMENTS.items():
                if source not in app_dict or cible not in app_dict:
                    continue
                modeles = app_dict[source]["models"]
                for modele in [m for m in modeles if m["object_name"] == nom]:
                    modeles.remove(modele)
                    app_dict[cible]["models"].append(modele)
                if not modeles:
                    del app_dict[source]
        app_list = sorted(app_dict.values(), key=lambda a: (_rang(ORDRE_SECTIONS, a["app_label"]), a["name"].lower()))
        for app in app_list:
            app["models"].sort(key=lambda m: (_rang(ORDRE_MODELES, m["object_name"]), m["name"]))
        return app_list

    def _url(self, modele, page, parametres=None):
        try:
            url = reverse(f"admin:{modele._meta.app_label}_{modele._meta.model_name}_{page}", current_app=self.name)
        except NoReverseMatch:
            return None
        return f"{url}?{urlencode(parametres)}" if parametres else url

    def _droit(self, request, label, page="changelist"):
        """ModelAdmin de ``label`` si l'utilisateur peut ouvrir la page, sinon None."""
        try:
            modele_admin = self._registry.get(apps.get_model(label))
        except LookupError:
            return None
        if modele_admin is None:
            return None
        autorise = (modele_admin.has_add_permission(request) if page == "add"
                    else modele_admin.has_view_or_change_permission(request))
        return modele_admin if autorise else None

    def acces_rapides(self, request):
        cartes = []
        for titre, description, label, page, parametres in ACCES_RAPIDES:
            modele_admin = self._droit(request, label, page)
            url = self._url(modele_admin.model, page, parametres) if modele_admin else None
            if url:
                cartes.append({"titre": titre, "description": description, "url": url, "ajout": page == "add"})
        return cartes

    def navigation(self, request, app_list):
        """Rubriques du menu latéral, d'après ``app_list`` (déjà filtrée selon les droits)."""
        # Clé : label réel du modèle (« auth.User »), même regroupé dans une autre section.
        modeles = {m["model"]._meta.label: m for a in app_list for m in a["models"]}
        index = reverse("admin:index", current_app=self.name)
        rubriques, ranges = [], set()

        def entree(cle):
            m = modeles[cle]
            ranges.add(cle)
            url = m.get("admin_url")
            # Pastille : événements à compléter (sans créneau, donc pas encore analysables).
            compteur = (_evenements_sans_creneau() or None) if cle == "evenements.Evenement" else None
            return {"libelle": LIBELLES_NAVIGATION.get(cle, m["name"]), "url": url,
                    "actif": bool(url) and request.path.startswith(url), "compteur": compteur}

        for titre, cles in NAVIGATION:
            entrees = []
            for cle in cles:
                if cle == "index":
                    entrees.append({"libelle": "Vue d’ensemble", "url": index, "actif": request.path == index,
                                    "compteur": None})
                elif cle in modeles:
                    entrees.append(entree(cle))
            if entrees:
                rubriques.append({"titre": titre, "entrees": entrees})
        autres = [entree(cle) for cle in modeles if cle not in ranges]
        if autres:
            rubriques.append({"titre": "Autres", "entrees": autres})
        return rubriques

    def etat_referentiel(self, request):
        """Volumes du référentiel, dernier import et droit de recharger (None sans droit de lecture)."""
        from apps.referentiel.models import Cellule, ImportReferentiel, Secteur, Site
        from apps.referentiel.rechargement import fichier_courant, peut_recharger

        if not self._droit(request, "referentiel.ImportReferentiel"):
            return None
        cellules = dict(Cellule.objects.values_list("techno").annotate(n=Count("pk")).values_list("techno", "n"))
        fichier = fichier_courant()
        return {
            "import": ImportReferentiel.objects.select_related("auteur").first(),
            "url": self._url(ImportReferentiel, "changelist"),
            "sites": Site.objects.count(),
            "secteurs": Secteur.objects.count(),
            "cellules_lte": cellules.get("LTE", 0),
            "cellules_wcdma": cellules.get("WCDMA", 0),
            "non_rattachees": Cellule.objects.filter(secteur__isnull=True).count(),
            "url_non_rattachees": self._url(Cellule, "changelist", {"rattachement": "non"}),
            "fichier": fichier.name if fichier else None,
            "peut_recharger": peut_recharger(request.user),
            "url_recharger": reverse("admin:referentiel_importreferentiel_recharger", current_app=self.name),
        }

    def a_traiter(self, request, depuis):
        """Points à examiner : (libellé, nombre, lien, gravité), selon les droits de l'utilisateur."""
        from apps.comptes.models import DemandeSuivie
        from apps.evenements.models import Evenement
        from apps.rapports.models import Rapport

        lignes = []
        if self._droit(request, "evenements.Evenement"):
            lignes.append(("Événements sans créneau", _evenements_sans_creneau(),
                           self._url(Evenement, "changelist", {"creneaux": "sans"}), "attention"))
        if self._droit(request, "comptes.DemandeSuivie"):
            recentes = DemandeSuivie.objects.filter(creee_le__gte=depuis)
            lignes.append(("Précisions sans réponse (7 j)",
                           recentes.filter(statut="a_preciser", suites__isnull=True).count(),
                           self._url(DemandeSuivie, "changelist", {"suite": "sans_suite",
                                                                   "creee_le__gte": depuis.isoformat()}),
                           "attention"))
            lignes.append(("Demandes en échec (7 j)", recentes.filter(statut="erreur").count(),
                           self._url(DemandeSuivie, "changelist", {"statut__exact": "erreur",
                                                                   "creee_le__gte": depuis.isoformat()}),
                           "critique"))
        if self._droit(request, "rapports.Rapport"):
            lignes.append(("Rapports en erreur", Rapport.objects.filter(statut="erreur").count(),
                           self._url(Rapport, "changelist", {"statut__exact": "erreur"}), "critique"))
        if self._droit(request, "django_q.Failure"):
            from django_q.models import Failure
            lignes.append(("Tâches de fond échouées", Failure.objects.count(),
                           self._url(Failure, "changelist"), "critique"))
        return [{"libelle": l, "nombre": n, "url": u, "gravite": g} for l, n, u, g in lignes]

    def each_context(self, request):
        contexte = super().each_context(request)
        contexte["navigation"] = self.navigation(request, contexte.get("available_apps") or [])
        contexte["peut_suivi"] = request.user.has_perm("comptes.view_demandesuivie")
        contexte["peut_rapports"] = request.user.has_perm("rapports.view_rapport")
        return contexte

    def index(self, request, extra_context=None):
        from apps.kpi.source import est_demo

        depuis = timezone.now() - timedelta(days=7)
        rappels = list(RAPPELS_COMMANDES) + ([RAPPEL_DEMO] if est_demo() else [])
        contexte = {
            "acces_rapides": self.acces_rapides(request),
            "rappels_commandes": rappels,
            "referentiel": self.etat_referentiel(request),
            "a_traiter": self.a_traiter(request, depuis),
            **(extra_context or {}),
        }
        if request.user.has_perm("comptes.view_demandesuivie"):
            from apps.comptes.models import DemandeSuivie

            contexte["suivi_depuis"] = depuis.isoformat()
            demandes = DemandeSuivie.objects.filter(creee_le__gte=depuis).annotate(
                a_une_suite=Exists(DemandeSuivie.objects.filter(parent_id=OuterRef("pk"))))
            stats = demandes.aggregate(
                total=Count("pk"), reussies=Count("pk", filter=Q(statut="reussie")),
                erreurs=Count("pk", filter=Q(statut="erreur")),
                a_preciser=Count("pk", filter=Q(statut="a_preciser", a_une_suite=False)),
                sans_donnees=Count("pk", filter=Q(statut="sans_donnees")))
            stats["taux"] = round(100 * stats["reussies"] / stats["total"]) if stats["total"] else None
            contexte["suivi_stats"] = stats
            contexte["dernieres_demandes"] = DemandeSuivie.objects.select_related("utilisateur")[:10]
        return super().index(request, contexte)

    def login(self, request, extra_context=None):
        """Une seule porte d'entrée : la page de connexion de l'application (/connexion/).

        Un visiteur ou un compte sans accès à l'administration y est renvoyé, avec ``next``.
        """
        if request.method == "GET" and not self.has_permission(request):
            suite = request.GET.get(REDIRECT_FIELD_NAME) or reverse("admin:index", current_app=self.name)
            return HttpResponseRedirect(f"{reverse('login')}?{urlencode({REDIRECT_FIELD_NAME: suite})}")
        return super().login(request, extra_context)
