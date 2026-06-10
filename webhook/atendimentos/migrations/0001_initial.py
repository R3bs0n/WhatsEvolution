import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SituacaoAtendimento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("nome", models.CharField(max_length=100, unique=True)),
                ("ativo", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Situação do atendimento",
                "verbose_name_plural": "Situações do atendimento",
                "ordering": ["nome"],
                "db_table": "situacoes_atendimento",
            },
        ),
        migrations.CreateModel(
            name="Atendimento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("exame_procedimento", models.CharField(blank=True, max_length=255)),
                ("paciente", models.CharField(blank=True, db_index=True, max_length=255)),
                ("idade", models.PositiveIntegerField(blank=True, null=True)),
                ("telefone", models.CharField(blank=True, db_index=True, max_length=20)),
                ("tp_procedimento", models.CharField(blank=True, max_length=255)),
                ("un_executante", models.CharField(blank=True, max_length=255)),
                ("data_hora", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("profissional_executante", models.CharField(blank=True, max_length=255)),
                ("un_solicitante", models.CharField(blank=True, max_length=255)),
                ("data_agendamento", models.DateField(blank=True, db_index=True, null=True)),
                ("horario_agendamento", models.TimeField(blank=True, db_index=True, null=True)),
                ("observacao", models.TextField(blank=True)),
                ("status_enviado", models.CharField(
                    choices=[("N", "Não enviado"), ("S", "Enviado")],
                    db_index=True,
                    default="N",
                    max_length=1,
                )),
                ("data_extracao", models.DateTimeField(blank=True, null=True)),
                ("data_envio", models.DateTimeField(blank=True, null=True)),
                ("pdf_nome_arquivo", models.CharField(blank=True, max_length=255)),
                ("pdf_caminho_arquivo", models.CharField(blank=True, max_length=500)),
                ("texto_extraido", models.TextField(blank=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("situacao", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="atendimentos",
                    to="atendimentos.situacaoatendimento",
                )),
            ],
            options={
                "verbose_name": "Atendimento",
                "verbose_name_plural": "Atendimentos",
                "ordering": ["-criado_em"],
            },
        ),
    ]
