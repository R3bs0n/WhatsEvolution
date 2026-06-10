# whatsapp-evo-test

Ambiente de testes local para a [Evolution API](https://github.com/EvolutionAPI/evolution-api) com receptor de webhooks em FastAPI.

## Pré-requisitos

- Docker e Docker Compose
- Python 3.11+ (apenas para rodar os testes localmente sem Docker)

## Início rápido

```bash
# 1. Copie o arquivo de variáveis de ambiente
cp .env.example .env

# 2. Edite o .env com sua chave da API
#    EVOLUTION_API_KEY=sua_chave_aqui

# 3. Suba o ambiente
docker compose up -d

# 4. Acesse o Swagger da Evolution API
#    http://localhost:8080/
# 5. Acesse o Swagger do webhook
#    http://localhost:8000/docs
```

## Serviços

| Serviço                | URL                              | Descrição                        |
|------------------------|----------------------------------|----------------------------------|
| **Sistema de Disparo** | http://localhost:8000            | Interface de envio em lote       |
| Evolution API          | http://localhost:8080            | API principal do WhatsApp        |
| Evolution Manager      | http://localhost:8080/manager    | Painel de gerenciamento visual   |
| Chatwoot               | http://localhost:3000            | Atendimento 1:1                  |
| Swagger UI             | http://localhost:8000/docs       | Documentação interativa da API   |

## Criando uma instância e configurando o webhook

```bash
# Criar instância
curl -X POST http://localhost:8080/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "instanceName": "test",
    "integration": "WHATSAPP-BAILEYS",
    "webhook": {
      "url": "http://webhook:8000/webhook",
      "byEvents": true,
      "base64": false,
      "events": [
        "MESSAGES_UPSERT",
        "MESSAGES_UPDATE",
        "CONNECTION_UPDATE",
        "QRCODE_UPDATED"
      ]
    }
  }'

# Obter QR Code
curl http://localhost:8080/instance/connect/test \
  -H "apikey: $EVOLUTION_API_KEY"
```

## Configurando Chatwoot para envio de mensagens

A Evolution API precisa estar com o modulo Chatwoot habilitado e a instancia precisa ser vinculada ao Chatwoot. As variaveis principais ficam no `.env`:

```env
CHATWOOT_ENABLED=true
EVOLUTION_INSTANCE_NAME=test
CHATWOOT_URL=http://chatwoot:3000
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_TOKEN=SEU_TOKEN_ADMIN_DO_CHATWOOT
CHATWOOT_INBOX_NAME=evolution
```

Use `http://localhost:3000` para abrir o Chatwoot no navegador. A variavel `CHATWOOT_URL=http://chatwoot:3000` e usada pela Evolution API dentro da rede Docker. Se o Chatwoot estiver em outro servidor, use a URL publica dele sem barra no final, por exemplo `https://chatwoot.suaempresa.com`.

Depois de preencher `CHATWOOT_TOKEN`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_URL` e garantir que a instancia `test` existe/conectou no WhatsApp, aplique a integracao:

```powershell
.\scripts\configure-chatwoot.ps1
```

O script chama:

```text
POST http://localhost:8080/chatwoot/set/test
```

com `autoCreate=true`, permitindo que a Evolution crie/vincule a inbox no Chatwoot. A partir dai, mensagens enviadas pelo Chatwoot nessa inbox devem sair pelo WhatsApp conectado na instancia.

## Fluxo de envio em lote via PDF

O webhook expõe dois endpoints para importar pacientes de um PDF e disparar mensagens personalizadas pelo WhatsApp sem necessidade de digitação manual.

### 1. Upload e extração — `POST /pdf/upload`

Envie o PDF como `multipart/form-data` (campo `file`). O sistema extrai os dados de cada paciente e **devolve a lista para conferência — nenhuma mensagem é enviada neste passo**.

```bash
curl -X POST http://localhost:8000/pdf/upload \
  -F "file=@exames.pdf"
```

Resposta:
```json
{
  "total": 2,
  "patients": [
    {
      "exam_type": "Hemograma",
      "phone": "5592999999999",
      "name": "Maria da Silva",
      "cpf": "123.456.789-00",
      "age": 45
    },
    {
      "exam_type": "Glicemia",
      "phone": "5511988887777",
      "name": "João Pereira",
      "cpf": "987.654.321-00",
      "age": 32
    }
  ]
}
```

### 2. Disparo — `POST /pdf/send`

Após revisar a lista, envie-a de volta com o template desejado. O sistema dispara as mensagens via Evolution API (instância `TESTE`) e retorna o relatório:

```bash
curl -X POST http://localhost:8000/pdf/send \
  -H "Content-Type: application/json" \
  -d '{
    "patients": [...],
    "template": "Olá, {name}. Identificamos seu exame: {exam_type}. Entre em contato conosco."
  }'
```

Resposta:
```json
{
  "total": 2,
  "sent": 2,
  "failed": 0,
  "results": [
    {"name": "Maria da Silva", "phone": "5592999999999", "status": "sent"},
    {"name": "João Pereira",   "phone": "5511988887777", "status": "sent"}
  ]
}
```

**Variáveis de template disponíveis:** `{name}`, `{exam_type}`, `{phone}`

**Comportamento em falhas:** cada paciente é processado independentemente; erros são registrados em `results[].error` sem interromper o lote.

**Normalização de telefone:** o sistema aceita `(92) 99999-9999`, `92999999999`, `5592999999999` etc. e converte automaticamente para o formato internacional brasileiro com DDI 55.

---

## Estrutura

```
whatsapp-evo-test/
├── docker-compose.yml       # Orquestração dos serviços
├── .env.example             # Template de variáveis de ambiente
└── webhook/
    ├── Dockerfile
    ├── pytest.ini
    ├── requirements.txt
    └── app/
        ├── main.py          # Entrypoint FastAPI
        ├── routers/
        │   ├── webhook.py   # POST /webhook (eventos Evolution API)
        │   └── pdf.py       # POST /pdf/upload  •  POST /pdf/send
        ├── models/
        │   ├── payload.py   # Modelos dos eventos webhook
        │   └── pdf_models.py # PatientData, SendRequest, SendResponse
        └── services/
            ├── message_handler.py  # Processamento de eventos recebidos
            ├── pdf_parser.py       # Extração de pacientes do PDF
            └── message_sender.py   # Envio via Evolution API
```

## Rodando os testes

```bash
cd webhook
pip install -r requirements.txt
pytest tests/ -v
```

## Eventos suportados

| Evento               | Descrição                              |
|----------------------|----------------------------------------|
| `MESSAGES_UPSERT`    | Nova mensagem recebida/enviada         |
| `MESSAGES_UPDATE`    | Atualização de status da mensagem      |
| `CONNECTION_UPDATE`  | Mudança no estado da conexão           |
| `QRCODE_UPDATED`     | Novo QR Code gerado                    |
| `SEND_MESSAGE`       | Confirmação de envio                   |
