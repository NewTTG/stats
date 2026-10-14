from django.urls import path

from . import views

app_name = "reseau"
urlpatterns = [
    path("", views.liste, name="liste"),
    path("nouveau/", views.edition, name="nouveau"),
    path("<str:code>/", views.fiche, name="fiche"),
    path("<str:code>/modifier/", views.edition, name="modifier"),
    path("<str:code>/supprimer/", views.supprimer, name="supprimer"),
]
