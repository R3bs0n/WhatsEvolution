import logging

from core.services.phone import mask_phone

from .providers import WhatsAppProvider, WhatsAppSendResult

logger = logging.getLogger(__name__)


class EvolutionWhatsAppProvider(WhatsAppProvider):
    def __init__(self, instance_name: str = None, api_url: str = None):
        from core.integrations.evolution.client import EvolutionClient
        self._client = EvolutionClient(instance_name=instance_name, api_url=api_url)

    def send_message(self, phone: str, message: str) -> WhatsAppSendResult:
        import httpx
        try:
            self._client.send_text(phone, message)
            logger.info("Mensagem enviada para %s via instância '%s'", mask_phone(phone), self._client.instance)
            return WhatsAppSendResult(success=True, status="SENT", code="200")
        except httpx.HTTPStatusError as exc:
            code = str(exc.response.status_code)
            detail = exc.response.text[:200]
            logger.error("HTTP %s ao enviar para %s: %s", code, mask_phone(phone), detail)
            return WhatsAppSendResult(success=False, status="HTTP_ERROR", code=code, detail=detail)
        except Exception as exc:
            logger.error("Erro ao enviar para %s: %s", mask_phone(phone), exc)
            return WhatsAppSendResult(success=False, status="ERROR", detail=str(exc))

    def send_template(
        self, phone: str, template_name: str, language: str, components: list
    ) -> WhatsAppSendResult:
        import httpx
        try:
            raw = self._client.send_template(phone, template_name, language, components)
        except httpx.HTTPStatusError as exc:
            # Nunca logar/persistir o corpo da resposta ou a exceção completa
            # -- o payload que ENVIAMOS (com o token) pode ser ecoado de
            # volta pela Evolution/Meta num corpo de erro (ex.: "invalid
            # parameter: <payload>"). Só o status code é seguro (mesmo
            # princípio já aplicado em channel_provisioning.py).
            code = str(exc.response.status_code)
            logger.error(
                "HTTP %s ao enviar template '%s' para %s.", code, template_name, mask_phone(phone),
            )
            return WhatsAppSendResult(
                success=False, status="HTTP_ERROR", code=code,
                detail=f"Evolution recusou o envio do template (HTTP {code}).",
            )
        except Exception as exc:
            logger.error(
                "Erro ao enviar template '%s' para %s (%s).",
                template_name, mask_phone(phone), type(exc).__name__,
            )
            return WhatsAppSendResult(
                success=False, status="ERROR",
                detail=f"Falha de comunicação com a Evolution ({type(exc).__name__}).",
            )

        # A Evolution NÃO lança exceção quando a Meta recusa o template (ex.:
        # não aprovado, fora de janela) — confirmado lendo o código-fonte
        # dela: erro de rede vira None, e só template com o campo
        # `error_data` é tratado como falha internamente. Por isso não
        # confiamos em "não veio exceção" — exigimos um message id de
        # verdade na resposta antes de marcar sucesso.
        message_id = None
        if isinstance(raw, dict):
            message_id = (raw.get("key") or {}).get("id")

        if not message_id:
            # Mesmo princípio: nunca logar/persistir `raw` inteiro -- pode
            # conter o token que acabamos de enviar (a Evolution ecoa dados
            # de instância em outros endpoints; não confiar que este nunca o
            # faria). Só o fato de faltar o message id é o que importa.
            logger.error(
                "Resposta sem message id ao enviar template '%s' para %s.",
                template_name, mask_phone(phone),
            )
            return WhatsAppSendResult(
                success=False, status="RESPOSTA_SEM_MESSAGE_ID",
                detail="Evolution não retornou um message id válido para este envio.",
            )

        logger.info(
            "Template '%s' enviado para %s via instância '%s'",
            template_name, mask_phone(phone), self._client.instance,
        )
        return WhatsAppSendResult(
            success=True, status="SENT", code="200", external_message_id=message_id,
        )
