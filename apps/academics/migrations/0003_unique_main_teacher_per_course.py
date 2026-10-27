from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0002_modules_and_groups"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="courseteacher",
            constraint=models.UniqueConstraint(
                condition=models.Q(("type", "MAIN")),
                fields=("course",),
                name="uniq_main_teacher_per_course",
            ),
        ),
    ]
