import logging

from django.conf import settings
from django.utils import timezone

from core.services.phone import PhoneValidationError, mask_phone, normalize_phone
from whatsapp.models import EnvioWhatsAppLog
from whatsapp.services.message_builder import build_message
from whatsapp.services.provider_factory import get_provider

logger = logging.getLogger(__name__)


class WhatsAppSendService:
    def __init__(self, provider=None):
        self.provider = provider

    def send_for_atendimento(self, atendimento) -> bool:
        empresa = atendimento.empresa

        try:
            phone = normalize_phone(atendimento.telefone, settings.DEFAULT_COUNTRY_CODE)
        except PhoneValidationError as exc:
            EnvioWhatsAppLog.objects.create(
                empresa=empresa,
                atendimento=atendimento,
                telefone=atendimento.telefone or "",
                mensagem="",
                status_retorno="TELEFONE_INVALIDO",
                detalhe_retorno=str(exc),
                sucesso=False,
            )
            logger.warning("Telefone inválido (atendimento %s): %s", atendimento.pk, exc)
            return False

        from whatsapp.models import CanalWhatsApp, ContatoBloqueado

        # Opt-out isolado por empresa
        if ContatoBloqueado.objects.for_empresa(empresa).filter(telefone=phone).exists():
            EnvioWhatsAppLog.objects.create(
                empresa=empresa,
                atendimento=atendimento,
                telefone=phone,
                mensagem="",
                status_retorno="BLOQUEADO",
                detalhe_retorno="Número na lista de opt-out.",
                sucesso=False,
            )
            logger.info(
                "Envio ignorado — número bloqueado (atendimento %s): %s",
                atendimento.pk,
                mask_phone(phone),
            )
            return False

        # Resolve canal principal da empresa (fallback: settings globais)
        canal = None
        if empresa:
            canal = CanalWhatsApp.objects.filter(
                empresa=empresa, principal=True, ativo=True
            ).first()

        provider = self.provider or get_provider(canal=canal)
        mensagem = build_message(
            atendimento.paciente,
            atendimento.exame_procedimento,
            empresa=empresa,
        )
        resultado = provider.send_message(phone, mensagem)

        EnvioWhatsAppLog.objects.create(
            empresa=empresa,
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
