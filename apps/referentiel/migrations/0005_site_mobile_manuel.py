"""Sites mobiles (remorques des événements) et sites déclarés dans l'application.

Les remorques déjà présentes dans le référentiel (nom REMORQUE…, MOBILE…) sont marquées mobiles.
"""

from django.db import migrations, models

from apps.referentiel.nommage import semble_mobile


def marquer(apps, schema_editor):
    Site = apps.get_model("referentiel", "Site")
    ids = [pk for pk, nom in Site.objects.values_list("pk", "nom") if semble_mobile(nom)]
    Site.objects.filter(pk__in=ids).update(mobile=True)


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0004_secteur_azimut")]

    operations = [
        migrations.AddField(
            model_name="site",
            name="mobile",
            field=models.BooleanField(
                default=False,
                help_text="Remorque déplacée lors des événements : position, azimuts et cellules se déclarent "
                          "dans chaque événement.",
                verbose_name="site mobile"),
        ),
        migrations.AddField(
            model_name="site",
            name="manuel",
            field=models.BooleanField(
                default=False,
                help_text="Site absent du xlsx : conservé, avec ses secteurs et cellules, par les rechargements.",
                verbose_name="déclaré dans l'application"),
        ),
        migrations.RunPython(marquer, migrations.RunPython.noop),
    ]
