import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PdfImportLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("filename", models.CharField(max_length=255)),
                ("total_extraidos", models.PositiveIntegerField(default=0)),
                ("total_inseridos", models.PositiveIntegerField(default=0)),
                ("total_ignorados", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(
                    choices=[("SUCESSO", "Sucesso"), ("PARCIAL", "Parcial"), ("ERRO", "Erro")],
                    default="SUCESSO",
                    max_length=10,
                )),
                ("mensagem", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "verbose_name": "Log de importação PDF",
                "verbose_name_plural": "Logs de importação PDF",
                "ordering": ["-created_at"],
            },
        ),
    ]
