import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("ASSIGNMENT", "Assignment"),
                            ("RESULT", "Result"),
                            ("SYSTEM", "System"),
                        ],
                        max_length=20,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("message", models.TextField(blank=True)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "notifications",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["recipient", "read_at", "created_at"],
                        name="idx_notification_inbox",
                    )
                ],
            },
        ),
    ]
