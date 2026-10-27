from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0003_unique_main_teacher_per_course"),
    ]

    operations = [
        migrations.AlterField(
            model_name="course",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("ACTIVE", "Active"),
                    ("ARCHIVED", "Archived"),
                ],
                db_index=True,
                default="ACTIVE",
                max_length=10,
            ),
        ),
    ]
