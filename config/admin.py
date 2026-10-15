"""Site d'administration du projet : espace séparé de l'application, rangé par usage.

Déclaré par ``config.apps.AdminStatsConfig`` (``default_site``) : ``admin.site`` et tous les
``@admin.register`` des applications désignent ce site.
"""

from datetime import timedelta
from functools import update_wrapper
from urllib.parse import urlencode

from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone

# Ordre des sections et des modèles (``get_app_list`` : pages d'application, droits du menu).
ORDRE_SECTIONS = ["evenements", "kpi", "comptes", "auth", "referentiel", "rapports", "django_q"]
# Ordre des modèles dans une section (les autres suivent, par ordre alphabétique).
ORDRE_MODELES = [
    "Evenement", "ReglagesAnomalies",
    "SeuilKpi", "ColonneKpi",
    "User", "Group", "Perimetre", "DemandeSuivie", "JournalAudit",
    "Site", "Secteur", "Cellule", "ImportReferentiel",
    "RapportPlanifie", "Rapport",
    "Schedule", "Failure", "Success", "OrmQ",
]


# Raccourcis du tableau de bord : (titre, description, modèle, page, paramètres de la liste).
# Un raccourci n'est affiché que si l'utilisateur a le droit correspondant.
ACCES_RAPIDES = [
    ("Créer un événement", "Page de l’application : carte des secteurs, KPI",
     "evenements.Evenement", "add", {}),
    ("KPI : noms et seuils", "Noms affichés, catégories, descriptions et seuils",
     "kpi.SeuilKpi", "changelist", {}),
    ("Colonnes de la base KPI", "Noms, descriptions, indicateurs proposés",
     "kpi.ColonneKpi", "changelist", {}),
    ("Périmètres d'accès", "Communes, sites, cellules et KPI visibles",
     "comptes.Perimetre", "changelist", {}),
    ("Comptes utilisateurs", "Comptes avec mot de passe",
     "auth.User", "changelist", {}),
    ("Journal d'audit", "Recherches, exports, analyses et rapports",
     "comptes.JournalAudit", "changelist", {}),
]

# Menu latéral : une entrée par espace ; ses pages sont des onglets en haut de page.
# (clé, titre, icône, [(page, libellé de l'onglet)]) : page = label du modèle, « index » ou « processus ».
# Un onglet sans libellé appartient à l'espace (menu actif) sans apparaître dans la barre d'onglets.
# Pages sans droit omises, espace vide omis ; un modèle enregistré absent d'ici est rangé dans « Autres ».
ESPACES = [
    ("accueil", "Vue d’ensemble", "accueil", [("index", "Vue d’ensemble")]),
    ("suivi", "Suivi des demandes", "suivi", [("comptes.DemandeSuivie", "Suivi des demandes")]),
    ("rapports", "Rapports", "rapports", [("rapports.Rapport", "Rapports générés"),
                                          ("rapports.RapportPlanifie", "Enregistrés et planifiés")]),
    ("referentiel", "Référentiel", "referentiel", [
        ("evenements.Evenement", "Événements"), ("kpi.SeuilKpi", "KPI : noms et seuils"),
        ("kpi.ColonneKpi", "Colonnes de la base"),
        ("evenements.ReglagesAnomalies", None)]),  # carte de l'onglet KPI
    ("reseau", "Réseau", "reseau", [
        ("referentiel.ImportReferentiel", "Imports et rechargement"), ("referentiel.Site", "Sites"),
        ("referentiel.Secteur", "Secteurs"), ("referentiel.Cellule", "Cellules")]),
    ("comptes", "Comptes et accès", "comptes", [
        ("auth.User", "Utilisateurs"), ("auth.Group", "Groupes"), ("comptes.Perimetre", "Périmètres d’accès"),
        ("comptes.JournalAudit", "Journal d’audit")]),
    ("systeme", "Système", "systeme", [
        ("processus", "Processus du serveur"), ("django_q.Schedule", "Planifications"),
        ("django_q.OrmQ", "File d’attente"), ("django_q.Failure", "Tâches échouées"),
        ("django_q.Success", "Tâches réussies")]),
]
# Page d'une application Django (/admin/<app>/) : remplacée par l'espace qui la regroupe.
ESPACE_DES_APPLICATIONS = {"evenements": "referentiel", "kpi": "referentiel", "auth": "comptes",
                           "comptes": "comptes", "referentiel": "reseau", "rapports": "rapports",
                           "django_q": "systeme"}

# Ouverture en fenêtre (popup) : paramètre ajouté aux pages ouvertes dans la fenêtre de l'administration.
MODALE_VAR = "_modale"


def _colonnes_a_nommer():
    from apps.kpi.models import ColonneKpi

    return ColonneKpi.objects.filter(presente=True, libelle="").count()


# Pastille du menu latéral : nombre d'éléments à compléter (rien si zéro).
COMPTEURS_NAVIGATION = {"kpi.ColonneKpi": _colonnes_a_nommer}

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


class ModaleMixin:
    """Création et modification ouvertes en fenêtre depuis les listes (``static/js/admin.js``).

    Ajouté à chaque ModelAdmin par ``AdminStats.register``. Une page appelée avec ``?_modale=1`` est
    affichée sans menu ni en-tête (``admin/base.html``) ; une fois l'objet enregistré ou supprimé, la
    fenêtre se ferme et la liste se recharge à la même position. « Enregistrer et continuer » et
    « Enregistrer et ajouter un nouveau » restent dans la fenêtre.
    """

    # ``ouverture_modale = False`` sur un ModelAdmin : ses fiches s'ouvrent en pleine page (redirection vers
    # l'application, page de détail riche…). Lu avec getattr : le mixin précède la classe dans l'héritage.

    @staticmethod
    def en_modale(request):
        return MODALE_VAR in request.GET

    def changelist_view(self, request, extra_context=None):
        contexte = {"ouverture_modale": getattr(self, "ouverture_modale", True), **(extra_context or {})}
        return super().changelist_view(request, contexte)

    def _rester_en_modale(self, reponse):
        if isinstance(reponse, HttpResponseRedirect):
            url = reponse["Location"]
            reponse["Location"] = f"{url}{'&' if '?' in url else '?'}{MODALE_VAR}=1"
        return reponse

    def _fermer_modale(self, request, action):
        return TemplateResponse(request, "admin/modale_fermer.html", {"action": action})

    def _apres_enregistrement(self, request, reponse):
        if not self.en_modale(request):
            return reponse
        if {"_continue", "_addanother", "_saveasnew"} & set(request.POST):
            return self._rester_en_modale(reponse)
        return self._fermer_modale(request, "enregistre")

    def response_add(self, request, obj, post_url_continue=None):
        return self._apres_enregistrement(request, super().response_add(request, obj, post_url_continue))

    def response_change(self, request, obj):
        return self._apres_enregistrement(request, super().response_change(request, obj))

    def response_delete(self, request, obj_display, obj_id):
        reponse = super().response_delete(request, obj_display, obj_id)
        return self._fermer_modale(request, "supprime") if self.en_modale(request) else reponse


class AdminStats(admin.AdminSite):
    site_header = "Stats réseau · Administration"
    site_title = "Stats réseau · Administration"
    index_title = "Tableau de bord"
    site_url = "/"  # lien « ← Retour aux statistiques » de l'en-tête

    def register(self, model_or_iterable, admin_class=None, **options):
        admin_class = admin_class or admin.ModelAdmin
        if not issubclass(admin_class, ModaleMixin):
            admin_class = type(admin_class.__name__, (ModaleMixin, admin_class), {"__module__": admin_class.__module__})
        return super().register(model_or_iterable, admin_class, **options)

    def admin_view(self, view, cacheable=False):
        vue = super().admin_view(view, cacheable)

        def vue_encadrable(request, *args, **kwargs):
            reponse = vue(request, *args, **kwargs)
            # Fenêtre de l'administration : page affichée dans un cadre de la même origine.
            if MODALE_VAR in request.GET:
                reponse["X-Frame-Options"] = "SAMEORIGIN"
            return reponse

        return update_wrapper(vue_encadrable, vue)

    def get_app_list(self, request, app_label=None):
        app_dict = self._build_app_dict(request, app_label)
        app_list = sorted(app_dict.values(), key=lambda a: (_rang(ORDRE_SECTIONS, a["app_label"]), a["name"].lower()))
        for app in app_list:
            app["models"].sort(key=lambda m: (_rang(ORDRE_MODELES, m["object_name"]), m["name"]))
        return app_list

    def app_index(self, request, app_label, extra_context=None):
        """Page d'une application : remplacée par la première page accessible de l'espace qui la regroupe."""
        cle = ESPACE_DES_APPLICATIONS.get(app_label)
        espace = next((e for e in self.espaces(request) if e["cle"] == cle), None)
        if espace:
            return HttpResponseRedirect(espace["url"])
        return super().app_index(request, app_label, extra_context)

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

    def espaces(self, request, app_list=None):
        """Espaces accessibles (menu latéral), chacun avec ses onglets, selon les droits de l'utilisateur."""
        if app_list is None:
            app_list = self.get_app_list(request)
        # Clé : label du modèle (« auth.User »).
        modeles = {m["model"]._meta.label: m for a in app_list for m in a["models"]}
        index = reverse("admin:index", current_app=self.name)
        ranges = {page for *_, pages in ESPACES for page, _ in pages}
        definitions = list(ESPACES)
        autres = [(cle, None) for cle in modeles if cle not in ranges]
        if autres:
            definitions.append(("autres", "Autres", "autres", autres))

        espaces = []
        for cle, titre, icone, pages in definitions:
            onglets = []
            for page, libelle in pages:
                if page == "index":
                    url, actif = index, request.path == index
                elif page == "processus":
                    if not request.user.is_superuser:
                        continue
                    url = reverse("admin:processus", current_app=self.name)
                    actif = request.path == url
                elif page in modeles and modeles[page].get("admin_url"):
                    url = modeles[page]["admin_url"]
                    actif = request.path.startswith(url)
                    libelle = libelle if libelle is not None or cle != "autres" else modeles[page]["name"]
                else:
                    continue
                compteur = COMPTEURS_NAVIGATION.get(page)
                onglets.append({"libelle": libelle, "url": url, "actif": actif,
                                "compteur": (compteur() or None) if compteur else None})
            visibles = [o for o in onglets if o["libelle"]]
            if not visibles:
                continue
            espaces.append({
                "cle": cle, "libelle": titre, "icone": icone, "url": visibles[0]["url"],
                "actif": any(o["actif"] for o in onglets),
                "compteur": sum(o["compteur"] or 0 for o in visibles) or None,
                "onglets": visibles,
            })
        return espaces

    def each_context(self, request):
        contexte = super().each_context(request)
        espaces = self.espaces(request, contexte.get("available_apps") or [])
        contexte["navigation"] = espaces
        courant = next((e for e in espaces if e["actif"]), None)
        contexte["espace"] = courant
        # Barre d'onglets : seulement pour un espace à plusieurs pages.
        contexte["onglets"] = courant["onglets"] if courant and len(courant["onglets"]) > 1 else []
        contexte["onglet"] = next((o for o in courant["onglets"] if o["actif"]), None) if courant else None
        contexte["en_modale"] = MODALE_VAR in request.GET
        contexte["peut_suivi"] = request.user.has_perm("comptes.view_demandesuivie")
        contexte["peut_rapports"] = request.user.has_perm("rapports.view_rapport")
        return contexte

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
        from apps.rapports.models import Rapport

        lignes = []
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

    def get_urls(self):
        return [path("processus/", self.admin_view(self.processus_view), name="processus")] + super().get_urls()

    def processus_view(self, request):
        """Application web et worker lancés par ``manage.py superviser`` : état, journaux, redémarrage."""
        from apps.comptes.models import JournalAudit
        from config import superviseur

        if not request.user.is_superuser:
            raise PermissionDenied
        page = reverse("admin:processus", current_app=self.name)
        if request.method == "POST":
            cible = request.POST.get("cible")
            etat = superviseur.lire_etat()
            if cible not in superviseur.CIBLES:
                messages.error(request, "Processus inconnu.")
            elif not (etat and etat["actif"]):
                messages.error(request, "Le superviseur ne tourne pas : redémarrage impossible depuis "
                                        "l'administration (voir « Démarrage automatique » dans le README).")
            else:
                noms = superviseur.demander_redemarrage(superviseur.CIBLES[cible], request.user.get_username())
                JournalAudit.objects.create(utilisateur=request.user, action="redemarrage_processus",
                                            requete={"processus": superviseur.CIBLES[cible]})
                libelles = " et ".join(superviseur.PROCESSUS[n].lower() for n in noms)
                message = f"Redémarrage demandé : {libelles}. Pris en compte dans les secondes qui viennent."
                if "app" in noms:
                    message += (" Base mise à niveau avant la relance (migrations…) : l’application sera indisponible"
                                " quelques secondes, recharger ensuite la page.")
                messages.success(request, message)
            return HttpResponseRedirect(page)
        etat = superviseur.lire_etat()
        processus = list(((etat or {}).get("processus") or {}).values())
        contexte = {
            **self.each_context(request),
            "title": "Processus du serveur",
            "etat": etat,
            "processus": processus,
            "demande": superviseur.demande_en_attente(),
            "journaux": [(nom, libelle, superviseur.fin_journal(nom))
                         for nom, libelle in [*superviseur.PROCESSUS.items(), ("preparation", "Mise à niveau"),
                                             ("superviseur", "Superviseur")]],
            "repertoire": superviseur.repertoire(),
        }
        request.current_app = self.name
        return TemplateResponse(request, "admin/processus.html", contexte)

    def login(self, request, extra_context=None):
        """Une seule porte d'entrée : la page de connexion de l'application (/connexion/).

        Un visiteur ou un compte sans accès à l'administration y est renvoyé, avec ``next``.
        """
        if request.method == "GET" and not self.has_permission(request):
            suite = request.GET.get(REDIRECT_FIELD_NAME) or reverse("admin:index", current_app=self.name)
            return HttpResponseRedirect(f"{reverse('login')}?{urlencode({REDIRECT_FIELD_NAME: suite})}")
        return super().login(request, extra_context)
