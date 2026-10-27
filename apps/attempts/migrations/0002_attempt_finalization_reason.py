from django.db import migrations, models


def infer_existing_reasons(apps, schema_editor):
    Attempt = apps.get_model("attempts", "ExamAttempt")
    completed = Attempt.objects.exclude(submitted_at=None)
    completed.filter(submitted_at=models.F("deadline_at")).update(finalization_reason="TIMEOUT")
    completed.filter(finalization_reason=None).update(finalization_reason="USER_SUBMIT")


class Migration(migrations.Migration):
    dependencies = [
        ("attempts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="examattempt",
            name="finalization_reason",
            field=models.CharField(
                blank=True,
                choices=[("USER_SUBMIT", "User submit"), ("TIMEOUT", "Timeout")],
                db_index=True,
                max_length=20,
                null=True,
            ),
        ),
        migrations.RunPython(infer_existing_reasons, migrations.RunPython.noop),
    ]
