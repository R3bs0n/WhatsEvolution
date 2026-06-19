import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("atendimentos", "0005_remove_atendimento_pdf_caminho_arquivo_and_more"),
        ("pdf_import", "0003_pdfimportlog_nome_pdfimportlog_periodo"),
    ]

    operations = [
        migrations.AddField(
            model_name="atendimento",
            name="pdf_import",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="atendimentos",
                to="pdf_import.pdfimportlog",
                verbose_name="Importação PDF",
            ),
        ),
    ]
