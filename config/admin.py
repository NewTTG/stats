"""Site d'administration du projet : espace séparé de l'application, rangé par usage.

Déclaré par ``config.apps.AdminStatsConfig`` (``default_site``) : ``admin.site`` et tous les
``@admin.register`` des applications désignent ce site.
"""

from urllib.parse import urlencode

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.urls import NoReverseMatch, reverse

# Sections du tableau de bord et du menu latéral : usage le plus fréquent d'abord, technique en dernier.
ORDRE_SECTIONS = ["evenements", "kpi", "comptes", "auth", "referentiel", "rapports", "django_q"]
# Ordre des modèles dans une section (les autres suivent, par ordre alphabétique).
ORDRE_MODELES = [
    "Evenement",
    "SeuilKpi", "ReglagesAnomalies",
    "User", "Group", "Perimetre", "JournalAudit",
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


# Accès rapides du tableau de bord : (titre, description, modèle, page, paramètres de la liste,
# compteur affiché sur la carte). Une carte n'est affichée que si l'utilisateur a le droit correspondant.
ACCES_RAPIDES = [
    ("Créer un événement", "Cellules concernées, créneaux et semaines de référence.",
     "evenements.Evenement", "add", {}, None),
    ("Événements à compléter", "Événements sans créneau : leur analyse n'est pas encore possible.",
     "evenements.Evenement", "changelist", {"creneaux": "sans"}, _evenements_sans_creneau),
    ("Seuils KPI", "Seuils d'alerte et critiques, modifiables directement dans la liste.",
     "kpi.SeuilKpi", "changelist", {}, None),
    ("Périmètres d'accès", "Communes, sites, cellules et KPI visibles par un compte ou un groupe.",
     "comptes.Perimetre", "changelist", {}, None),
    ("Comptes utilisateurs", "Comptes avec mot de passe ; les sessions visiteur sont masquées.",
     "auth.User", "changelist", {}, None),
    ("Journal d'audit", "Recherches, exports, analyses et rapports : qui, quoi, quand.",
     "comptes.JournalAudit", "changelist", {}, None),
]

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

    def acces_rapides(self, request):
        cartes = []
        for titre, description, label, page, parametres, compteur in ACCES_RAPIDES:
            try:
                modele_admin = self._registry.get(apps.get_model(label))
            except LookupError:
                continue
            if modele_admin is None:
                continue
            autorise = (modele_admin.has_add_permission(request) if page == "add"
                        else modele_admin.has_view_or_change_permission(request))
            url = self._url(modele_admin.model, page, parametres) if autorise else None
            if url:
                cartes.append({"titre": titre, "description": description, "url": url, "ajout": page == "add",
                               "compteur": compteur() if compteur else None})
        return cartes

    def dernier_import(self, request):
        from apps.referentiel.models import ImportReferentiel

        modele_admin = self._registry.get(ImportReferentiel)
        if modele_admin is None or not modele_admin.has_view_or_change_permission(request):
            return None
        dernier = ImportReferentiel.objects.select_related("auteur").first()
        return {"import": dernier, "url": self._url(ImportReferentiel, "changelist")}

    def index(self, request, extra_context=None):
        from apps.kpi.source import est_demo

        rappels = list(RAPPELS_COMMANDES) + ([RAPPEL_DEMO] if est_demo() else [])
        contexte = {
            "acces_rapides": self.acces_rapides(request),
            "rappels_commandes": rappels,
            "referentiel": self.dernier_import(request),
            **(extra_context or {}),
        }
        return super().index(request, contexte)

    def login(self, request, extra_context=None):
        """Une seule porte d'entrée : la page de connexion de l'application (/connexion/).

        Un visiteur ou un compte sans accès à l'administration y est renvoyé, avec ``next``.
        """
        if request.method == "GET" and not self.has_permission(request):
            suite = request.GET.get(REDIRECT_FIELD_NAME) or reverse("admin:index", current_app=self.name)
            return HttpResponseRedirect(f"{reverse('login')}?{urlencode({REDIRECT_FIELD_NAME: suite})}")
        return super().login(request, extra_context)
