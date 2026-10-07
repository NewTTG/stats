from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "Stats KPI réseau"
admin.site.site_title = "Stats KPI réseau"

urlpatterns = [
    path("", include("apps.kpi.urls")),
    path("connexion/", auth_views.LoginView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
