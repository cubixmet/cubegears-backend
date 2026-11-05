from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("companies", "0005_customer_website")]

    operations = [
        migrations.AlterField(
            model_name="companydomain",
            name="id",
            field=models.BigAutoField(
                auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
            ),
        ),
        migrations.AlterField(
            model_name="companywebsitesettings",
            name="id",
            field=models.BigAutoField(
                auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
            ),
        ),
    ]
