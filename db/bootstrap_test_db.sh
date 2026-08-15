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
# IMPORTANTE: roda do HOST (fora dos containers), via `docker exec` -- os
# clientes psql/createdb/dropdb vivem no container evolution_postgres (imagem
# oficial do Postgres), e o Django/manage.py vive no container
# evolution_webhook (imagem Python) -- nenhum dos dois tem as duas coisas.
# Corrigido em 2026-08-14: a v1 deste script presumia psql/createdb dentro do
# container webhook, o que nunca existiu -- so foi validado rodando os passos
# manualmente antes, nunca como script unico ate agora.
#
# Uso (do host, com docker compose já de pé):
#   sh db/bootstrap_test_db.sh
#
# Variaveis esperadas no ambiente (.env local, lido pelo docker-compose):
#   TEST_ROLE_USER, TEST_ROLE_PASSWORD, TEST_DB_NAME

set -e

: "${TEST_ROLE_USER:?defina TEST_ROLE_USER}"
: "${TEST_ROLE_PASSWORD:?defina TEST_ROLE_PASSWORD}"
: "${TEST_DB_NAME:?defina TEST_DB_NAME}"

case "$TEST_DB_NAME" in
  test_*) ;;
  *) echo "TEST_DB_NAME='$TEST_DB_NAME' nao comeca com 'test_' -- abortando por seguranca." >&2; exit 1 ;;
esac

echo "==> Recriando $TEST_DB_NAME (se ja existir) -- via evolution_postgres..."
docker exec -e PGPASSWORD="$TEST_ROLE_PASSWORD" evolution_postgres \
  dropdb -U "$TEST_ROLE_USER" -h localhost --if-exists "$TEST_DB_NAME"
docker exec -e PGPASSWORD="$TEST_ROLE_PASSWORD" evolution_postgres \
  createdb -U "$TEST_ROLE_USER" -h localhost "$TEST_DB_NAME"

echo "==> Privilegios padrao (tabelas futuras criadas por $TEST_ROLE_USER -> app_role)..."
docker exec -e PGPASSWORD="$TEST_ROLE_PASSWORD" evolution_postgres \
  psql -U "$TEST_ROLE_USER" -h localhost -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 <<SQL
ALTER DEFAULT PRIVILEGES FOR ROLE $TEST_ROLE_USER IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_role;
ALTER DEFAULT PRIVILEGES FOR ROLE $TEST_ROLE_USER IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_role;
GRANT USAGE ON SCHEMA public TO app_role;
SQL

echo "==> Rodando migrations do Django (como $TEST_ROLE_USER, direto no Postgres) -- via evolution_webhook..."
docker exec \
  -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 -e POSTGRES_USER="$TEST_ROLE_USER" \
  -e POSTGRES_PASSWORD="$TEST_ROLE_PASSWORD" -e POSTGRES_DB="$TEST_DB_NAME" \
  evolution_webhook python manage.py migrate --noinput

echo "==> Privilegios retroativos nas tabelas ja criadas pelo migrate acima..."
# ALTER DEFAULT PRIVILEGES sozinho nao foi suficiente em teste real (2026-08-14
# -- django_migrations ficou sem grant pro app_role, causando "permission
# denied" nos testes). GRANT explicito em tudo que ja existe e mais robusto.
docker exec -e PGPASSWORD="$TEST_ROLE_PASSWORD" evolution_postgres \
  psql -U "$TEST_ROLE_USER" -h localhost -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 <<SQL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role;
SQL

echo "==> Aplicando RLS (db/rls_policies.sql) -- via evolution_postgres..."
# MSYS_NO_PATHCONV evita o Git Bash (Windows) reescrever "/tmp/..." como
# caminho local -- inofensivo em shells não-MSYS (variável só ignorada).
MSYS_NO_PATHCONV=1 docker cp "$(dirname "$0")/rls_policies.sql" evolution_postgres:/tmp/rls_policies_test.sql
MSYS_NO_PATHCONV=1 docker exec -e PGPASSWORD="$TEST_ROLE_PASSWORD" evolution_postgres \
  psql -U "$TEST_ROLE_USER" -h localhost -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 -f /tmp/rls_policies_test.sql

echo "==> Pronto: $TEST_DB_NAME criado, migrado e com RLS aplicado."
