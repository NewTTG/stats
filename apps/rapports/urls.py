from django.urls import path

from . import views

app_name = "rapports"
urlpatterns = [
    path("", views.liste, name="liste"),
    path("requete/", views.rapport_requete, name="requete"),
    path("evenement/<int:pk>/", views.rapport_evenement, name="evenement"),
    path("<int:pk>/telecharger/", views.telecharger, name="telecharger"),
]
