from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0002_user_language")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="phone_number",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
