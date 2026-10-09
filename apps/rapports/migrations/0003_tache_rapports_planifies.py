"""Tâche django-q2 qui lance, toutes les 15 minutes, les rapports planifiés arrivés à échéance."""

from django.db import migrations

NOM = "rapports-planifies"


def creer(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.update_or_create(name=NOM, defaults={
        "func": "apps.rapports.planification.lancer_dus", "schedule_type": "I", "minutes": 15, "repeats": -1})


def supprimer(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name=NOM).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("rapports", "0002_rapports_planifies"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [migrations.RunPython(creer, supprimer)]
