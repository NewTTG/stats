from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

admin.site.site_header = "Stats KPI réseau"
admin.site.site_title = "Stats KPI réseau"

urlpatterns = [
    # En attendant les écrans de requête (phase 1), l'accueil mène à l'admin.
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
]
