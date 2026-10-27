from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assignments", "0002_assignment_recipients")]

    operations = [
        migrations.AddField(
            model_name="examassignment",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="examassignment",
            name="is_archived",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
