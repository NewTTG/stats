from django.urls import path

from . import views

app_name = "kpi"
urlpatterns = [
    path("", views.requete, name="requete"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("suggestions/", views.suggestions, name="suggestions"),
]
