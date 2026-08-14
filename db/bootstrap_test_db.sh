#!/bin/sh
# Cria/recria o banco de teste local (test_evolution_db) do zero, aplicando
# schema (migrations do Django) + RLS (db/rls_policies.sql) + privilegios
# padrao pro app_role -- tudo via test_role (CREATEDB, sem superuser, sem
# BYPASSRLS), nunca via evolution/migrate_role.
#
# Rodar de novo sempre que houver migration nova (o CI/dev precisa refazer
# esse passo -- os testes usam --reuse-db + TEST.MIGRATE=False, entao NAO
# rodam migrate sozinhos).
#
# Uso (de dentro do container evolution_webhook, ou local com psql apontando
# pro Postgres do docker-compose):
#   sh db/bootstrap_test_db.sh
#
# Variaveis esperadas no ambiente (ja vem do .env local via docker-compose):
#   TEST_ROLE_USER, TEST_ROLE_PASSWORD, TEST_DB_NAME
#   POSTGRES_DB (banco "molde" de onde o rls_policies.sql e copiado)

set -e

: "${TEST_ROLE_USER:?defina TEST_ROLE_USER}"
: "${TEST_ROLE_PASSWORD:?defina TEST_ROLE_PASSWORD}"
: "${TEST_DB_NAME:?defina TEST_DB_NAME}"

case "$TEST_DB_NAME" in
  test_*) ;;
  *) echo "TEST_DB_NAME='$TEST_DB_NAME' nao comeca com 'test_' -- abortando por seguranca." >&2; exit 1 ;;
esac

export PGPASSWORD="$TEST_ROLE_PASSWORD"

echo "==> Recriando $TEST_DB_NAME (se ja existir)..."
dropdb -U "$TEST_ROLE_USER" -h postgres --if-exists "$TEST_DB_NAME"
createdb -U "$TEST_ROLE_USER" -h postgres "$TEST_DB_NAME"

echo "==> Privilegios padrao (tabelas futuras criadas por $TEST_ROLE_USER -> app_role)..."
psql -U "$TEST_ROLE_USER" -h postgres -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 <<SQL
ALTER DEFAULT PRIVILEGES FOR ROLE $TEST_ROLE_USER IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_role;
ALTER DEFAULT PRIVILEGES FOR ROLE $TEST_ROLE_USER IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_role;
GRANT USAGE ON SCHEMA public TO app_role;
SQL

echo "==> Rodando migrations do Django (como $TEST_ROLE_USER, direto no Postgres)..."
POSTGRES_HOST=postgres POSTGRES_PORT=5432 POSTGRES_USER="$TEST_ROLE_USER" \
  POSTGRES_PASSWORD="$TEST_ROLE_PASSWORD" POSTGRES_DB="$TEST_DB_NAME" \
  python manage.py migrate --noinput

echo "==> Aplicando RLS (db/rls_policies.sql)..."
psql -U "$TEST_ROLE_USER" -h postgres -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 -f /app/../db/rls_policies.sql \
  || psql -U "$TEST_ROLE_USER" -h postgres -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 -f db/rls_policies.sql

echo "==> Pronto: $TEST_DB_NAME criado, migrado e com RLS aplicado."
