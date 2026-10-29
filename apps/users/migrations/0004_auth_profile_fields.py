from django.db import migrations, models
from django.utils.text import slugify


def populate_usernames(apps, schema_editor):
    User = apps.get_model("users", "User")
    used = set()
    for user in User.objects.order_by("created_at", "id"):
        base = slugify(user.email.split("@", 1)[0]).replace("-", "_") or "user"
        candidate = base[:140]
        suffix = 1
        while candidate.lower() in used:
            suffix += 1
            candidate = f"{base[: 149 - len(str(suffix))]}_{suffix}"
        user.username = candidate
        user.save(update_fields=["username"])
        used.add(candidate.lower())


class Migration(migrations.Migration):
    dependencies = [("users", "0003_user_phone_number")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(blank=True, upload_to="avatars/%Y/%m/"),
        ),
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="temporary_password_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="theme",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark"), ("system", "System")],
                default="system",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="username",
            field=models.CharField(max_length=150, null=True, unique=True),
        ),
        migrations.RunPython(populate_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(max_length=150, unique=True),
        ),
    ]
