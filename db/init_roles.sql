-- Executado uma vez pelo DBA (ou via pg_hba + docker entrypoint) ANTES de ativar RLS.
-- Cria dois roles:
--   app_role     — conectado pelo Django (webhook/Celery). SEM BYPASSRLS.
--   migrate_role — conectado apenas pelo serviço 'migrate' no deploy. COM BYPASSRLS.
-- O owner das tabelas continua sendo o role que criou via Django (ex: 'evolution').
-- As políticas RLS são avaliadas para app_role; migrate_role as ignora.

\c :DBNAME

-- Cria app_role se não existir
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
    CREATE ROLE app_role LOGIN;
  END IF;
END;
$$;

-- Cria migrate_role se não existir (BYPASSRLS para executar migrations sem contexto RLS)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrate_role') THEN
    CREATE ROLE migrate_role LOGIN BYPASSRLS;
  END IF;
END;
$$;

-- Define senha para ambos os roles (sobrescrever com PGPASSWORD seguro no env)
ALTER ROLE app_role WITH PASSWORD :'APP_ROLE_PASSWORD';
ALTER ROLE migrate_role WITH PASSWORD :'MIGRATE_ROLE_PASSWORD';

-- Garante que ambos os roles têm acesso ao schema e às tabelas
GRANT CONNECT ON DATABASE :DBNAME TO app_role, migrate_role;
GRANT USAGE ON SCHEMA public TO app_role, migrate_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_role, migrate_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role, migrate_role;

-- Aplica grants a tabelas futuras também
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_role, migrate_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_role, migrate_role;
