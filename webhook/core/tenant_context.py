"""
Gerenciamento de contexto de tenant para PostgreSQL RLS.

Dois níveis de configuração:

  set_session_tenant(id)  — nível de SESSÃO (set_config false).
                            Sobrevive a commits de transação.
                            Usar no início de tasks Celery (com reset em finally).

  set_tenant(id)          — nível de TRANSAÇÃO (SET LOCAL).
                            Revertido automaticamente no commit/rollback.
                            Usar dentro de atomic() como proteção extra.
"""
from contextlib import contextmanager

from django.db import connection


# ── Nível de sessão — para tasks Celery ──────────────────────────────────────

def set_session_tenant(empresa_id):
    """
    Define o tenant em nível de SESSÃO — persiste entre transações.
    Equivalente ao que o TenantMiddleware faz para requests web.
    Chamar no início de cada task Celery; sempre resetar em finally.
    """
    if empresa_id is None:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.current_tenant', %s, false)",
            [str(empresa_id)],
        )


def reset_session_tenant():
    """
    Limpa o tenant da sessão. Chamar no bloco finally de cada task Celery
    para não vazar contexto entre tasks que compartilham a conexão (CONN_MAX_AGE > 0).
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant', '', false)")


# ── Nível de transação — para blocos atomic() ────────────────────────────────

def get_session_tenant() -> str:
    """Retorna o tenant atualmente gravado na sessao da conexao PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_tenant', true)")
        value = cursor.fetchone()[0]
    return value or ""


@contextmanager
def session_tenant_context(empresa_id):
    """
    Define temporariamente o tenant em nivel de sessao e restaura o valor anterior.
    Usar em operacoes administrativas que criam/alteram dados de uma empresa alvo.
    """
    previous = get_session_tenant()
    if empresa_id is None:
        reset_session_tenant()
    else:
        set_session_tenant(empresa_id)
    try:
        yield
    finally:
        if previous:
            set_session_tenant(previous)
        else:
            reset_session_tenant()


@contextmanager
def tenant_context(empresa_id):
    """
    SET LOCAL: dura apenas até o fim da transação corrente.
    Usar DENTRO de atomic().
    """
    if empresa_id is None:
        yield
        return
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.current_tenant = %s", [str(empresa_id)])
    yield  # SET LOCAL é revertido automaticamente no commit/rollback


def set_tenant(empresa_id):
    """
    Versão imperativa de tenant_context. Usar dentro de atomic() apenas.
    """
    if empresa_id is None:
        return
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.current_tenant = %s", [str(empresa_id)])
