import logging

from django.conf import settings
from django.utils import timezone

from core.services.phone import PhoneValidationError, normalize_phone
from whatsapp.models import EnvioWhatsAppLog
from whatsapp.services.message_builder import build_message
from whatsapp.services.provider_factory import get_provider

logger = logging.getLogger(__name__)


class WhatsAppSendService:
    def __init__(self):
        self.provider = get_provider()

    def send_for_atendimento(self, atendimento) -> bool:
        try:
            phone = normalize_phone(atendimento.telefone, settings.DEFAULT_COUNTRY_CODE)
        except PhoneValidationError as exc:
            EnvioWhatsAppLog.objects.create(
                atendimento=atendimento,
                telefone=atendimento.telefone or "",
                mensagem="",
                status_retorno="TELEFONE_INVALIDO",
                detalhe_retorno=str(exc),
                sucesso=False,
            )
            logger.warning("Telefone inválido (atendimento %s): %s", atendimento.pk, exc)
            return False

        mensagem = build_message(atendimento.paciente, atendimento.exame_procedimento)
        resultado = self.provider.send_message(phone, mensagem)

        EnvioWhatsAppLog.objects.create(
            atendimento=atendimento,
            telefone=phone,
            mensagem=mensagem,
            status_retorno=resultado.status,
            codigo_retorno=resultado.code or "",
            detalhe_retorno=resultado.detail or "",
            sucesso=resultado.success,
        )

        if resultado.success:
            atendimento.status_enviado = "S"
            atendimento.data_envio = timezone.now()
            atendimento.save(update_fields=["status_enviado", "data_envio"])

        return resultado.success
