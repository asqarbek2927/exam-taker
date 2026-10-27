from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="language",
            field=models.CharField(
                choices=[("en", "English"), ("uz", "O‘zbekcha"), ("ru", "Русский")],
                default="en",
                max_length=5,
            ),
        ),
    ]
