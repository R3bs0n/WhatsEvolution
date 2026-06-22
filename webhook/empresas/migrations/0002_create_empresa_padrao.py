from django.db import migrations


def create_empresa_padrao(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    CanalWhatsApp = apps.get_model("whatsapp", "CanalWhatsApp")
    ConfiguracaoDisparo = apps.get_model("whatsapp", "ConfiguracaoDisparo")
    ConfiguracaoSistema = apps.get_model("whatsapp", "ConfiguracaoSistema")

    import os
    instance_name = os.environ.get("EVOLUTION_INSTANCE_NAME", "clinica")

    empresa, created = Empresa.objects.get_or_create(
        slug="clinica-medica-saude-popular",
        defaults={
            "nome": "Clínica Médica Saúde Popular",
            "segmento": "saude",
            "cor_primaria": "#0d6efd",
            "cor_secundaria": "#6c757d",
            "tema": "light",
            "ativo": True,
        },
    )

    # Canal WhatsApp padrão
    if not CanalWhatsApp.objects.filter(instance_name=instance_name).exists():
        CanalWhatsApp.objects.create(
            empresa=empresa,
            nome="Canal principal",
            instance_name=instance_name,
            api_url=os.environ.get("EVOLUTION_API_URL", ""),
            principal=True,
            ativo=True,
        )
    else:
        CanalWhatsApp.objects.filter(instance_name=instance_name).update(empresa=empresa)

    # ConfiguracaoDisparo copiando da ConfiguracaoSistema global
    if not ConfiguracaoDisparo.objects.filter(empresa=empresa).exists():
        try:
            config_global = ConfiguracaoSistema.objects.get(pk=1)
            limite = config_global.limite_diario_mensagens
        except ConfiguracaoSistema.DoesNotExist:
            limite = 1000

        ConfiguracaoDisparo.objects.create(
            empresa=empresa,
            limite_diario_mensagens=limite,
            tamanho_lote=300,
            intervalo_segundos=3,
            contato_url=os.environ.get("WHATSAPP_CONTACT_URL", ""),
            privacy_policy_url=os.environ.get("WHATSAPP_PRIVACY_POLICY_URL", ""),
        )

    # Backfill: vincular todos os registros existentes à empresa padrão
    Atendimento = apps.get_model("atendimentos", "Atendimento")
    SituacaoAtendimento = apps.get_model("atendimentos", "SituacaoAtendimento")
    StatusAtendimento = apps.get_model("atendimentos", "StatusAtendimento")
    PdfImportLog = apps.get_model("pdf_import", "PdfImportLog")
    ContatoBloqueado = apps.get_model("whatsapp", "ContatoBloqueado")
    EnvioWhatsAppLog = apps.get_model("whatsapp", "EnvioWhatsAppLog")

    Atendimento.objects.filter(empresa__isnull=True).update(empresa=empresa)
    SituacaoAtendimento.objects.filter(empresa__isnull=True).update(empresa=empresa)
    StatusAtendimento.objects.filter(empresa__isnull=True).update(empresa=empresa)
    PdfImportLog.objects.filter(empresa__isnull=True).update(empresa=empresa)
    ContatoBloqueado.objects.filter(empresa__isnull=True).update(empresa=empresa)
    EnvioWhatsAppLog.objects.filter(empresa__isnull=True).update(empresa=empresa)


def reverse_empresa_padrao(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    Empresa.objects.filter(slug="clinica-medica-saude-popular").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0001_initial"),
        ("atendimentos", "0007_atendimento_empresa_situacaoatendimento_empresa_and_more"),
        ("pdf_import", "0004_pdfimportlog_empresa"),
        ("whatsapp", "0004_canalwhatsapp_configuracaodisparo_templatemensagem_and_more"),
    ]

    operations = [
        migrations.RunPython(create_empresa_padrao, reverse_empresa_padrao),
    ]
