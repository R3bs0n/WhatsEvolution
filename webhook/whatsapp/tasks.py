import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)

_DISPATCH_DELAY_SECONDS = 3  # gap between consecutive WhatsApp messages


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def dispatch_batch_after_import(self, atendimento_ids: list) -> dict:
    """Schedule WhatsApp dispatch for a list of newly-imported Atendimento IDs.

    Marks all eligible records as 'E' (enfileirado) in a single batch UPDATE,
    then schedules individual send_whatsapp_for_atendimento tasks spaced
    _DISPATCH_DELAY_SECONDS apart to respect WhatsApp rate limits.

    Returns {"scheduled": N, "skipped": M} where skipped = IDs that were
    already sent or not in status N.
    """
    from atendimentos.models import Atendimento

    if not atendimento_ids:
        return {"scheduled": 0, "skipped": 0}

    try:
        with transaction.atomic():
            updated = (
                Atendimento.objects
                .filter(pk__in=atendimento_ids, status_enviado="N")
                .update(status_enviado="E")
            )
    except Exception as exc:
        logger.error("Erro ao enfileirar lote de atendimentos: %s", exc)
        raise self.retry(exc=exc)

    skipped = len(atendimento_ids) - updated
    if skipped:
        logger.info("%d atendimento(s) do lote ignorados (status != N).", skipped)

    for i, aid in enumerate(atendimento_ids):
        send_whatsapp_for_atendimento.apply_async(
            args=[aid],
            countdown=i * _DISPATCH_DELAY_SECONDS,
        )

    logger.info("Lote de %d mensagens agendadas para disparo.", updated)
    return {"scheduled": updated, "skipped": skipped}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_whatsapp_for_atendimento(self, atendimento_id: int) -> bool:
    from django.utils import timezone
    from atendimentos.models import Atendimento
    from whatsapp.models import ConfiguracaoSistema, EnvioWhatsAppLog
    from whatsapp.services.sender import WhatsAppSendService

    config = ConfiguracaoSistema.get()
    hoje = timezone.now().date()
    enviados_hoje = EnvioWhatsAppLog.objects.filter(enviado_em__date=hoje, sucesso=True).count()
    if enviados_hoje >= config.limite_diario_mensagens:
        logger.warning(
            "Limite diário de %d mensagens atingido. Atendimento %s marcado como 'Limitado'.",
            config.limite_diario_mensagens,
            atendimento_id,
        )
        from atendimentos.models import Atendimento
        Atendimento.objects.filter(
            pk=atendimento_id, status_enviado__in=["N", "E"]
        ).update(status_enviado="L")
        EnvioWhatsAppLog.objects.create(
            atendimento_id=atendimento_id,
            telefone="",
            mensagem="",
            status_retorno="LIMITE_DIARIO",
            detalhe_retorno=f"Limite diário de {config.limite_diario_mensagens} mensagens atingido.",
            sucesso=False,
        )
        return False

    try:
        with transaction.atomic():
            # Aceita status "E" (Enfileirado) OU "N" (Não enviado) para
            # garantir compatibilidade com registros enfileirados pela view
            # e também com envios manuais diretos via admin.
            # select_for_update(skip_locked=True) impede double-send sob
            # concorrência de workers: se bloqueado, sai silenciosamente.
            atendimento = (
                Atendimento.objects
                .select_for_update(skip_locked=True)
                .get(pk=atendimento_id, status_enviado__in=["N", "E"])
            )
            service = WhatsAppSendService()
            success = service.send_for_atendimento(atendimento)

        logger.info("Atendimento %s — %s", atendimento_id, "OK" if success else "FALHA")
        return success

    except Atendimento.DoesNotExist:
        # Já enviado, não existe, ou bloqueado por outro worker (skip_locked)
        logger.info("Atendimento %s ignorado (não encontrado, já enviado ou bloqueado).", atendimento_id)
        return True

    except Exception as exc:
        logger.error("Erro ao enviar atendimento %s: %s", atendimento_id, exc)
        # Reverte para "N" se esgotar as tentativas, para não ficar preso em "E"
        if self.request.retries >= self.max_retries:
            try:
                Atendimento.objects.filter(pk=atendimento_id, status_enviado="E").update(
                    status_enviado="N"
                )
                logger.warning("Atendimento %s revertido para 'N' após %s tentativas.", atendimento_id, self.max_retries)
            except Exception:
                pass
        raise self.retry(exc=exc)
