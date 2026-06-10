import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("atendimentos", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EnvioWhatsAppLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("telefone", models.CharField(max_length=20)),
                ("mensagem", models.TextField()),
                ("status_retorno", models.CharField(blank=True, max_length=100)),
                ("codigo_retorno", models.CharField(blank=True, max_length=50)),
                ("detalhe_retorno", models.TextField(blank=True)),
                ("enviado_em", models.DateTimeField(default=django.utils.timezone.now)),
                ("sucesso", models.BooleanField(default=False)),
                ("atendimento", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="whatsapp_logs",
                    to="atendimentos.atendimento",
                )),
            ],
            options={
                "verbose_name": "Log de envio WhatsApp",
                "verbose_name_plural": "Logs de envio WhatsApp",
                "ordering": ["-enviado_em"],
            },
        ),
    ]
