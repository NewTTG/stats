from django.urls import path

from . import views

app_name = "rapports"
urlpatterns = [
    path("", views.liste, name="liste"),
    path("requete/", views.rapport_requete, name="requete"),
    path("evenement/<int:pk>/", views.rapport_evenement, name="evenement"),
    path("<int:pk>/telecharger/", views.telecharger, name="telecharger"),
    path("enregistrer/", views.enregistrer, name="enregistrer"),
    path("enregistres/<int:pk>/lancer/", views.planifie_lancer, name="planifie_lancer"),
    path("enregistres/<int:pk>/basculer/", views.planifie_basculer, name="planifie_basculer"),
    path("enregistres/<int:pk>/supprimer/", views.planifie_supprimer, name="planifie_supprimer"),
]
