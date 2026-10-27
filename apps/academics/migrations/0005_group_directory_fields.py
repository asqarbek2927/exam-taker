import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0004_course_draft_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="studygroup",
            name="main_teacher",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="main_study_groups",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="studygroup",
            name="status",
            field=models.CharField(
                choices=[("ACTIVE", "Active"), ("ARCHIVED", "Archived")],
                db_index=True,
                default="ACTIVE",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="studygroup",
            name="support_teacher",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="support_study_groups",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="studygroup",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("main_teacher__isnull", True))
                    | models.Q(("support_teacher__isnull", True))
                    | ~models.Q(("main_teacher", models.F("support_teacher")))
                ),
                name="group_teachers_must_differ",
            ),
        ),
    ]
