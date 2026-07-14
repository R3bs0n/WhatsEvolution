# Sistema de Disparo WhatsApp Multi-tenant

Sistema Django para disparo em lote de mensagens WhatsApp, com fluxo clinico por PDF e fluxo generico de campanhas. Usa Celery, Redis, PostgreSQL, Evolution API e isolamento multi-tenant por empresa.

## Pre-requisitos

- Docker e Docker Compose
- Python 3.12+ apenas para desenvolvimento local

## Inicio Rapido

```bash
# 1. Crie/edite o arquivo .env com as variaveis de ambiente

# 2. Suba banco, Redis e servicos
docker compose up -d

# 3. Execute as migrations
docker compose run --rm migrate

# 4. Aplique as politicas RLS
docker compose exec -T postgres psql -U evolution -d evolution_db < db/rls_policies.sql

# 5. Crie o superusuario Django
docker compose exec webhook python manage.py createsuperuser

# 6. Acesse
# http://localhost:8000
```

## Servicos

| Servico | URL | Descricao |
|---|---|---|
| Sistema de Disparo | http://localhost:8000 | Interface web Django multi-tenant |
| Django Admin | http://localhost:8000/admin | Administracao interna |
| Evolution API | http://localhost:8080 | Gateway WhatsApp |
| Evolution Manager | http://localhost:8080/manager | Painel visual da Evolution API |
| Chatwoot | http://localhost:3000 | Atendimento 1:1 |
| Typebot Builder | http://localhost:3001 | Construtor de fluxos |
| Typebot Viewer | http://localhost:3002 | Viewer de fluxos |
| MailHog | http://localhost:8025 | Captura de e-mails local |

## Estrutura

```text
whatsapp-evo-test/
├── docker-compose.yml
├── db/
│   ├── init_roles.sql
│   └── rls_policies.sql
└── webhook/
    ├── config/
    ├── core/
    ├── empresas/
    ├── billing/
    ├── atendimentos/
    ├── pdf_import/
    ├── whatsapp/
    ├── campanhas/
    ├── evolution/
    └── django_tests/
```

## Multi-tenancy

O isolamento ocorre em duas camadas:

1. `TenantManager`: queries operacionais devem usar `Model.objects.for_empresa(request.empresa)`.
2. PostgreSQL RLS: `FORCE ROW LEVEL SECURITY` em tabelas operacionais, com `app.current_tenant` definido por request/task.

Contexto de tenant:

- Requests web: `TenantMiddleware` define e limpa `app.current_tenant`.
- Celery: tasks usam `set_session_tenant(empresa_id)` e `reset_session_tenant()`.
- Blocos atomicos: `set_tenant(empresa_id)` aplica `SET LOCAL`.

## Roles do Banco

| Role | Permissoes | Uso |
|---|---|---|
| `evolution` | Superuser/BYPASSRLS | Migrations, RLS e operacoes DBA |
| `app_role` | DML sem BYPASSRLS | Django web e Celery |
| `migrate_role` | BYPASSRLS controlado | Uso manual/DBA quando configurado |

O servico `migrate` do `docker-compose.yml` usa o `POSTGRES_USER` privilegiado definido no `.env`. O `webhook` e o `celery-worker` sobrescrevem usuario/senha para `app_role`.

## Variaveis Importantes

```env
SECRET_KEY=...
DEBUG=False
ALLOWED_HOSTS=...

POSTGRES_USER=evolution
POSTGRES_PASSWORD=...
APP_ROLE_USER=app_role
APP_ROLE_PASSWORD=...

EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE_NAME=clinica
EVOLUTION_WEBHOOK_SECRET=...

BILLING_GRACE_MODE=True
WHATSAPP_DEFAULT_COMPANY_NAME=Clinica Medica Saude Popular
CELERY_BROKER_URL=redis://redis:6379/0
```

`EVOLUTION_WEBHOOK_SECRET` deve estar preenchido em producao. Se estiver vazio e `DEBUG=False`, o webhook rejeita os eventos.

`BILLING_GRACE_MODE=True` preserva o comportamento atual: empresas sem assinatura cadastrada ainda podem disparar. Para cobranca ativa em producao, cadastre as assinaturas e use `BILLING_GRACE_MODE=False`.

## Fluxos

Fluxo clinico:

1. Operador envia PDF em `/pdf/upload`.
2. O sistema extrai atendimentos e cria `Atendimento` com empresa.
3. Operador dispara pelo painel de WhatsApp ou pela lista de atendimentos.
4. Celery valida billing, limite diario, rate limit por canal e opt-out.
5. Envio ocorre pela Evolution API e gera `EnvioWhatsAppLog`.

Fluxo generico:

1. Operador importa contatos por CSV.
2. Cria segmentos e campanhas.
3. Celery materializa destinatarios e dispara mensagens por canal.
4. Billing, opt-out e rate limit tambem sao validados dentro das tasks.

## Seguranca

- Dados operacionais devem ter `empresa_id` obrigatorio.
- Webhook Evolution exige `EVOLUTION_WEBHOOK_SECRET` fora de `DEBUG`.
- Painel `/instancias/` exige superuser.
- Admin operacional usa escopo por tenant; modelos globais/sensiveis exigem superuser.
- `db/rls_policies.sql` inclui a funcao `resolve_canal_by_instance()` com `SECURITY DEFINER`, `search_path` fixo e `EXECUTE` restrito a `app_role`.
- Arquivos `.env` e `.env.bak.*` estao no `.gitignore` e nao devem ser enviados para servidor publico, imagem Docker ou repositorio.

## Testes

```bash
cd webhook
pip install -r requirements.txt
pytest django_tests/ -v
```

Tambem rode antes de subir:

```bash
cd webhook
python manage.py check
cd ..
docker compose run --rm migrate
docker compose exec -T postgres psql -U evolution -d evolution_db < db/rls_policies.sql
docker compose build webhook celery-worker migrate evolution-api
docker compose up -d --force-recreate webhook celery-worker evolution-api
```
