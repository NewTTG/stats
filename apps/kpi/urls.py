from django.urls import path

from . import views

app_name = "kpi"
urlpatterns = [
    path("", views.requete, name="requete"),
    path("suggestions/", views.suggestions, name="suggestions"),
]
