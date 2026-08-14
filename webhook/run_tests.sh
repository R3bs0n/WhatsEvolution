#!/bin/sh
# Wrapper pra rodar a suite de testes corretamente: conecta direto no
# Postgres (bypassa o PgBouncer, que não conhece o banco de teste) como
# app_role de verdade (não evolution/superuser — os testes precisam rodar
# sob o mesmo RLS restrito que a aplicação real usa).
#
# Pré-requisito (rodar 1x, ou de novo após migration nova):
#   sh ../db/bootstrap_test_db.sh
#
# Uso: sh run_tests.sh [args extras do pytest]
#   sh run_tests.sh
#   sh run_tests.sh django_tests/test_meta_credential.py -v

set -e
export POSTGRES_HOST=postgres
export POSTGRES_PORT=5432
exec pytest --reuse-db "$@"
