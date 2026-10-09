from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path

from apps.comptes.views import ConnexionView

urlpatterns = [
    path("", include("apps.kpi.urls")),
    path("evenements/", include("apps.evenements.urls")),
    path("rapports/", include("apps.rapports.urls")),
    path("connexion/", ConnexionView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),  # site du projet : config/admin.py (AdminStats)
    # Pas d'icône : réponse vide plutôt qu'une 404 dans la console (pages d'administration).
    path("favicon.ico", lambda request: HttpResponse(status=204)),
]
