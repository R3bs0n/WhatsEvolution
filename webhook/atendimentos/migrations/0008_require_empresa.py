import django.db.models.deletion
from django.db import migrations, models


def assign_default_empresa(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    primeira = Empresa.objects.order_by("pk").first()
    if not primeira:
        return

    Atendimento = apps.get_model("atendimentos", "Atendimento")
    n = Atendimento.objects.filter(empresa__isnull=True).update(empresa=primeira)
    if n:
        print(f"\n  → {n} atendimento(s) sem empresa vinculados a '{primeira.nome}' (pk={primeira.pk})")

    SituacaoAtendimento = apps.get_model("atendimentos", "SituacaoAtendimento")
    n = SituacaoAtendimento.objects.filter(empresa__isnull=True).update(empresa=primeira)
    if n:
        print(f"  → {n} situação(ões) sem empresa vinculadas a '{primeira.nome}'")

    StatusAtendimento = apps.get_model("atendimentos", "StatusAtendimento")
    n = StatusAtendimento.objects.filter(empresa__isnull=True).update(empresa=primeira)
    if n:
        print(f"  → {n} status sem empresa vinculados a '{primeira.nome}'")


class Migration(migrations.Migration):

    dependencies = [
        ("atendimentos", "0007_atendimento_empresa_situacaoatendimento_empresa_and_more"),
        ("empresas", "0002_create_empresa_padrao"),
    ]

    operations = [
        migrations.RunPython(assign_default_empresa, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="atendimento",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="atendimentos",
                to="empresas.empresa",
                verbose_name="Empresa",
            ),
        ),
        migrations.AlterField(
            model_name="situacaoatendimento",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="situacoes_atendimento",
                to="empresas.empresa",
            ),
        ),
        migrations.AlterField(
            model_name="statusatendimento",
            name="empresa",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="status_atendimento",
                to="empresas.empresa",
            ),
        ),
    ]
