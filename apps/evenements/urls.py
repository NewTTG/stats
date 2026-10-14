from django.urls import path

from . import views

app_name = "evenements"
urlpatterns = [
    path("", views.liste, name="liste"),
    path("nouveau/", views.edition, name="nouveau"),
    path("reseau.json", views.reseau_json, name="reseau"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/modifier/", views.edition, name="modifier"),
    path("<int:pk>/supprimer/", views.supprimer, name="supprimer"),
    path("<int:pk>/periode/", views.memoriser_periode, name="memoriser_periode"),
    path("<int:pk>/editions/enregistrer/", views.enregistrer_edition, name="enregistrer_edition"),
]
