from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db.models import Count

from .models import JournalAudit, Perimetre
from .visiteurs import est_visiteur, filtre_visiteurs


class TypeCompteFilter(admin.SimpleListFilter):
    """Comptes avec mot de passe par défaut : les sessions visiteur (une par navigateur) ne noient
    pas la liste. « Tous » est un choix explicite, à la place du « Tout » de Django."""

    title = "type de compte"
    parameter_name = "compte"
    DEFAUT = "comptes"

    def lookups(self, request, model_admin):
        return [("comptes", "Comptes (avec mot de passe)"), ("visiteurs", "Visiteurs (sans compte)"), ("tous", "Tous")]

    def value(self):
        valeur = super().value()
        return valeur if valeur in {v for v, _ in self.lookup_choices} else self.DEFAUT

    def queryset(self, request, queryset):
        if self.value() == "comptes":
            return queryset.exclude(filtre_visiteurs())
        if self.value() == "visiteurs":
            return queryset.filter(filtre_visiteurs())
        return queryset

    def choices(self, changelist):
        compteurs = self.get_facet_queryset(changelist) if changelist.add_facets else None
        for i, (valeur, libelle) in enumerate(self.lookup_choices):
            if compteurs is not None:
                libelle = f"{libelle} ({compteurs.get(f'{i}__c', '-')})"
            yield {
                "selected": self.value() == valeur,
                "query_string": (changelist.get_query_string(remove=[self.parameter_name]) if valeur == self.DEFAUT
                                 else changelist.get_query_string({self.parameter_name: valeur})),
                "display": libelle,
            }


admin.site.unregister(User)


@admin.register(User)
class UtilisateurAdmin(UserAdmin):
    list_display = ["username", "nom_complet", "email", "is_staff", "visiteur", "last_login"]
    list_filter = [TypeCompteFilter, *UserAdmin.list_filter]

    @admin.display(description="nom", ordering="last_name")
    def nom_complet(self, obj):
        return obj.get_full_name()

    @admin.display(description="visiteur", boolean=True)
    def visiteur(self, obj):
        return est_visiteur(obj)


@admin.register(Perimetre)
class PerimetreAdmin(admin.ModelAdmin):
    list_display = ["nom", "attribue_a", "contenu", "kpis"]
    search_fields = ["nom"]
    filter_horizontal = ["utilisateurs", "groupes"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            nb_utilisateurs=Count("utilisateurs", distinct=True), nb_groupes=Count("groupes", distinct=True))

    @admin.display(description="attribué à")
    def attribue_a(self, obj):
        return f"{obj.nb_utilisateurs} utilisateur(s), {obj.nb_groupes} groupe(s)"

    @admin.display(description="contenu")
    def contenu(self, obj):
        parties = [f"{len(obj.communes)} commune(s)", f"{len(obj.sites)} site(s)", f"{len(obj.cellules)} cellule(s)"]
        return ", ".join(parties)

    @admin.display(description="KPI autorisés")
    def kpis(self, obj):
        return f"{len(obj.kpis_autorises)}" if obj.kpis_autorises else "tous"


# Libellés des actions tracées (apps/kpi/views.py, apps/evenements/views.py, apps/rapports/lancement.py).
LIBELLES_ACTIONS = {
    "recherche_kpi": "Recherche",
    "requete_kpi": "Recherche avancée",
    "export_excel": "Export Excel",
    "analyse_evenement": "Analyse d'événement",
    "rapport_requete_pptx": "Rapport PowerPoint (requête)",
    "rapport_requete_xlsx": "Rapport Excel (requête)",
    "rapport_evenement_pptx": "Rapport PowerPoint (événement)",
    "rapport_evenement_xlsx": "Rapport Excel (événement)",
}


def libelle_action(action: str) -> str:
    return LIBELLES_ACTIONS.get(action, action)


class ActionFilter(admin.SimpleListFilter):
    title = "action"
    parameter_name = "action"

    def lookups(self, request, model_admin):
        actions = JournalAudit.objects.order_by("action").values_list("action", flat=True).distinct()
        return sorted(((a, libelle_action(a)) for a in actions), key=lambda choix: choix[1].lower())

    def queryset(self, request, queryset):
        return queryset.filter(action=self.value()) if self.value() else queryset


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    list_display = ["date", "utilisateur", "action_libelle", "detail"]
    list_filter = [ActionFilter]
    list_select_related = ["utilisateur"]
    date_hierarchy = "date"
    search_fields = ["utilisateur__username", "action"]
    search_help_text = "Nom d'utilisateur (ex. visiteur-1a2b3c4d) ou code d'action."
    readonly_fields = ["date", "utilisateur", "action", "requete"]

    def has_add_permission(self, request):
        return False  # entrées créées par l'application seulement

    @admin.display(description="action", ordering="action")
    def action_libelle(self, obj):
        return libelle_action(obj.action)

    @admin.display(description="détail")
    def detail(self, obj):
        requete = obj.requete if isinstance(obj.requete, dict) else {}
        if requete.get("q"):
            texte = requete["q"]
            return f"« {texte[:80]}… »" if len(texte) > 80 else f"« {texte} »"
        if obj.action == "analyse_evenement" and requete.get("evenement"):
            return f"événement n° {requete['evenement']} ({requete.get('niveau', 'secteur')})"
        return ""
