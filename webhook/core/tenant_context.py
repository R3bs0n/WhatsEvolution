"""
Gerenciamento de contexto de tenant para PostgreSQL RLS.

Uso dentro de uma transação atomic():
    with tenant_context(empresa_id):
        # queries aqui são filtradas pelo RLS
"""
from contextlib import contextmanager

from django.db import connection


@contextmanager
def tenant_context(empresa_id):
    """
    Configura o contexto de tenant para RLS usando SET LOCAL.
    Deve ser usado DENTRO de uma transação atomic() — SET LOCAL
    dura apenas até o fim da transação corrente.
    """
    if empresa_id is None:
        yield
        return

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.current_tenant = %s", [str(empresa_id)])
    try:
        yield
    finally:
        pass  # SET LOCAL é revertido automaticamente com o fim da transação


def set_tenant(empresa_id):
    """
    Versão imperativa para tasks Celery onde não é prático usar context manager.
    Chamar dentro de atomic() apenas.
    """
    if empresa_id is None:
        return
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.current_tenant = %s", [str(empresa_id)])
