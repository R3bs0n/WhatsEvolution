import django.db.models.deletion
from django.db import migrations, models


def assign_default_empresa(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    primeira = Empresa.objects.order_by("pk").first()
    if not primeira:
        return

    PdfImportLog = apps.get_model("pdf_import", "PdfImportLog")
    n = PdfImportLog.objects.filter(empresa__isnull=True).update(empresa=primeira)
    if n:
        print(f"\n  → {n} log(s) PDF sem empresa vinculados a '{primeira.nome}' (pk={primeira.pk})")


class Migration(migrations.Migration):

    dependencies = [
        ("pdf_import", "0004_pdfimportlog_empresa"),
        ("empresas", "0002_create_empresa_padrao"),
    ]

    operations = [
        migrations.RunPython(assign_default_empresa, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pdfimportlog",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="pdf_imports",
                to="empresas.empresa",
            ),
        ),
    ]
