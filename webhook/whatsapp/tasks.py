import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_whatsapp_for_atendimento(self, atendimento_id: int) -> bool:
    from atendimentos.models import Atendimento
    from whatsapp.services.sender import WhatsAppSendService

    try:
        atendimento = Atendimento.objects.get(pk=atendimento_id)
    except Atendimento.DoesNotExist:
        logger.warning("Atendimento %s não encontrado. Tarefa cancelada.", atendimento_id)
        return False

    if atendimento.status_enviado == "S":
        logger.info("Atendimento %s já foi enviado. Pulando.", atendimento_id)
        return True

    try:
        with transaction.atomic():
            service = WhatsAppSendService()
            success = service.send_for_atendimento(atendimento)
        logger.info("Atendimento %s — %s", atendimento_id, "OK" if success else "FALHA")
        return success
    except Exception as exc:
        logger.error("Erro ao enviar atendimento %s: %s", atendimento_id, exc)
        raise self.retry(exc=exc)
