"""Événements importés de l'onglet Cluster : la description ne renvoie plus à des créneaux à renseigner
(la période se choisit à l'affichage de l'événement)."""

from django.db import migrations

ANCIENNE = "Importé de l'onglet Cluster du référentiel : créneaux à renseigner."
NOUVELLE = "Importé de l'onglet Cluster du référentiel."


def corriger(apps, schema_editor):
    apps.get_model("evenements", "Evenement").objects.filter(description=ANCIENNE).update(description=NOUVELLE)


def retablir(apps, schema_editor):
    apps.get_model("evenements", "Evenement").objects.filter(description=NOUVELLE).update(description=ANCIENNE)


class Migration(migrations.Migration):
    dependencies = [("evenements", "0002_alter_creneau_options")]
    operations = [migrations.RunPython(corriger, retablir)]
