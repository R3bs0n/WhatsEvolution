import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("WHATSAPP_PROVIDER", "fake")


def _guard_against_production():
    """Aborta a suite ANTES de qualquer conexão de banco se o ambiente não
    parecer claramente local/CI. Ver webhook/django_tests/README de testes
    (ou o relatório da tarefa de correção da suíte) para o raciocínio
    completo — resumo: os testes recriam/usam um banco à parte (test_role +
    test_evolution_db), nunca app_role/evolution reais, mas essa checagem
    existe como camada extra caso alguém rode pytest com um .env errado."""
    test_role_password = os.environ.get("TEST_ROLE_PASSWORD", "")
    if not test_role_password:
        raise RuntimeError(
            "TEST_ROLE_PASSWORD ausente — a suite de testes precisa de um "
            "role dedicado (test_role, só CREATEDB, sem BYPASSRLS) que só "
            "deve existir em ambiente local/CI. Configure-o no .env local "
            "antes de rodar pytest. NÃO crie esse role em produção."
        )

    allowed_hosts = os.environ.get("ALLOWED_HOSTS", "")
    csrf_trusted = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    producao_markers = ("sendyou.com.br", "177.153.33.234")
    if any(m in allowed_hosts or m in csrf_trusted for m in producao_markers):
        raise RuntimeError(
            "ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS deste .env parecem ser de "
            "produção (contém domínio/IP de produção) — abortando a suite "
            "de testes por segurança. Rode os testes só com o .env local."
        )

    test_db_name = os.environ.get("TEST_DB_NAME", "")
    if not test_db_name.startswith("test_"):
        raise RuntimeError(
            f"TEST_DB_NAME={test_db_name!r} não começa com 'test_' — "
            "recusando prosseguir para não arriscar apontar os testes "
            "(que recriam o schema) para um banco que não é de teste."
        )

    # POSTGRES_HOST precisa já estar "postgres" (bypass do PgBouncer) ANTES
    # do processo Python subir — pytest-django lê isso cedo demais pra uma
    # mutação de os.environ aqui dentro do conftest.py surtir efeito (tentei,
    # não funciona: o Django já tinha montado DATABASES com o valor antigo).
    # Por isso o valor tem que vir de fora — ver webhook/run_tests.sh.
    if os.environ.get("POSTGRES_HOST") != "postgres":
        raise RuntimeError(
            "POSTGRES_HOST não é 'postgres' — os testes precisam ser "
            "rodados via webhook/run_tests.sh (ou com POSTGRES_HOST=postgres "
            "POSTGRES_PORT=5432 já setados ANTES do processo iniciar), "
            "nunca com `pytest` puro (que herda POSTGRES_HOST=pgbouncer)."
        )


_guard_against_production()

# A criação do banco de teste (test_evolution_db) usa test_role (CREATEDB,
# sem BYPASSRLS) e é feita FORA do pytest, por db/bootstrap_test_db.sh — os
# testes em si conectam como app_role (real, restrito) direto no Postgres,
# com TEST.MIGRATE=False (as tabelas já existem, criadas pelo bootstrap;
# rodar migrate aqui falharia, porque app_role não tem DDL).


def pytest_configure(config):
    # Acessa via `connections` (não `settings.DATABASES` bruto) para que o
    # Django já tenha normalizado o dict TEST com os defaults dele (MIRROR,
    # DEPENDENCIES, SERIALIZE etc.) antes de eu sobrescrever só o que importa.
    from django.db import connections

    test_settings = connections["default"].settings_dict["TEST"]
    test_settings["NAME"] = os.environ["TEST_DB_NAME"]
    test_settings["MIGRATE"] = False
