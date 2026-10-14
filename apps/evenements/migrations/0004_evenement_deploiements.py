from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("evenements", "0003_description_clusters")]

    operations = [
        migrations.AddField(
            model_name="evenement",
            name="deploiements",
            field=models.JSONField(blank=True, default=dict, verbose_name="sites mobiles déployés"),
        ),
    ]
