from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pdf_import", "0002_alter_pdfimportlog_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="pdfimportlog",
            name="nome",
            field=models.CharField(blank=True, max_length=255, verbose_name="Nome"),
        ),
        migrations.AddField(
            model_name="pdfimportlog",
            name="periodo",
            field=models.DateField(
                blank=True,
                help_text="Mês/ano a que este PDF se refere (armazenado como 1º dia do mês)",
                null=True,
                verbose_name="Período",
            ),
        ),
    ]
