from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Rapport, RapportPlanifie


@admin.register(Rapport)
class RapportAdmin(admin.ModelAdmin):
    list_display = ["cree_le", "titre", "utilisateur", "format", "statut", "telechargement"]
    list_select_related = ['utilisateur', 'demande']
    search_fields = ['titre', 'utilisateur__username', 'utilisateur__email']
    date_hierarchy = 'cree_le'
    list_per_page = 30
    list_filter = ["statut", "nature", "format"]
    readonly_fields = [f.name for f in Rapport._meta.fields if f.name != 'fichier'] + ['telechargement']
    exclude = ['fichier']

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {'title': 'Rapports générés', **(extra_context or {})})

    def get_urls(self):
        return [path('<int:pk>/telecharger/', self.admin_site.admin_view(self.telecharger),
                     name='rapports_rapport_telecharger')] + super().get_urls()

    @admin.display(description='fichier')
    def telechargement(self, obj):
        if obj.statut != 'termine' or not obj.fichier:
            return 'Aucun fichier disponible'
        return format_html('<a class="admin-button" href="{}">Télécharger {}</a>',
                           reverse('admin:rapports_rapport_telecharger', args=[obj.pk]), obj.get_format_display())

    def telecharger(self, request, pk):
        if not self.has_view_permission(request) or request.method not in ('GET', 'HEAD'):
            raise PermissionDenied
        rapport = get_object_or_404(Rapport, pk=pk, statut='termine')
        if not rapport.fichier:
            raise Http404('Aucun fichier disponible.')
        try:
            fichier = rapport.fichier.open('rb')
        except OSError:
            raise Http404('Le fichier archivé est introuvable.')
        from apps.comptes.models import JournalAudit
        JournalAudit.objects.create(utilisateur=request.user, action='telechargement_admin',
                                    requete={'rapport': rapport.pk})
        return FileResponse(fichier, as_attachment=True, filename=rapport.fichier.name.rsplit('/', 1)[-1])

    def has_add_permission(self, request):
        return False


@admin.register(RapportPlanifie)
class RapportPlanifieAdmin(admin.ModelAdmin):
    list_display = ["titre", "utilisateur", "periode", "format", "frequence", "actif", "prochain_lancement"]
    list_filter = ["frequence", "actif", "format"]
    readonly_fields = ["prochain_lancement", "dernier_lancement", "cree_le"]

    def save_model(self, request, obj, form, change):
        obj.planifier()
        super().save_model(request, obj, form, change)
