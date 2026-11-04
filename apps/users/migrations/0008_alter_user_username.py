from django.db import migrations, models


def populate_missing_usernames(apps, schema_editor):
    User = apps.get_model("users", "User")
    used = {
        username.casefold()
        for username in User.objects.exclude(username__isnull=True)
        .exclude(username="")
        .values_list("username", flat=True)
    }
    for user in User.objects.filter(models.Q(username__isnull=True) | models.Q(username="")):
        base = f"user_{str(user.pk).replace('-', '')}"
        candidate = base[:150]
        suffix = 1
        while candidate.casefold() in used:
            suffix += 1
            suffix_text = f"_{suffix}"
            candidate = f"{base[: 150 - len(suffix_text)]}{suffix_text}"
        user.username = candidate
        user.save(update_fields=["username"])
        used.add(candidate.casefold())


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0007_alter_user_username"),
    ]

    operations = [
        migrations.RunPython(populate_missing_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(max_length=150, unique=True),
        ),
    ]
