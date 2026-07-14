import django.db.models.deletion
from django.db import migrations, models


def assign_default_empresa(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    primeira = Empresa.objects.order_by("pk").first()
    if not primeira:
        return

    changes = [
        ("whatsapp", "CanalWhatsApp", "canal(is) WhatsApp"),
        ("whatsapp", "ConfiguracaoDisparo", "configuração(ões) de disparo"),
        ("whatsapp", "TemplateMensagem", "template(s) de mensagem"),
        ("whatsapp", "ContatoBloqueado", "contato(s) bloqueado(s)"),
        ("whatsapp", "EnvioMensagem", "envio(s) de mensagem (orphan)"),
        ("whatsapp", "EnvioWhatsAppLog", "log(s) de envio WhatsApp"),
    ]
    for app_label, model_name, label in changes:
        Model = apps.get_model(app_label, model_name)
        n = Model.objects.filter(empresa__isnull=True).update(empresa=primeira)
        if n:
            print(f"\n  → {n} {label} sem empresa vinculados a '{primeira.nome}' (pk={primeira.pk})")


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0005_add_envio_mensagem_tentativa_evento"),
        ("empresas", "0002_create_empresa_padrao"),
    ]

    operations = [
        # Ponto 7: atribuir registros NULL e tornar NOT NULL
        migrations.RunPython(assign_default_empresa, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="canalwhatsapp",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="canais_whatsapp",
                to="empresas.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="configuracaodisparo",
            name="empresa",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="configuracao_disparo",
                to="empresas.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="templatemensagem",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="templates_mensagem",
                to="empresas.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="contatobloqueado",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="contatos_bloqueados",
                to="empresas.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="enviomensagem",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="envios_mensagem",
                to="empresas.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="enviowhatsapplog",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="envios_whatsapp",
                to="empresas.empresa",
            ),
        ),
        # Ponto 10: campo para rate limiting por canal
        migrations.AddField(
            model_name="configuracaodisparo",
            name="mensagens_por_minuto",
            field=models.IntegerField(
                default=20,
                verbose_name="Mensagens por minuto por canal",
            ),
        ),
    ]
