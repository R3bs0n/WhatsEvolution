import logging
import uuid

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)

_DISPATCH_DELAY_SECONDS = 3


def _get_configuracao(empresa=None):
    """Retorna ConfiguracaoDisparo da empresa ou fallback para ConfiguracaoSistema global."""
    from whatsapp.models import ConfiguracaoDisparo, ConfiguracaoSistema
    if empresa is not None:
        config = ConfiguracaoDisparo.objects.filter(empresa=empresa).first()
        if config:
            return config
    return ConfiguracaoSistema.get()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def dispatch_batch_after_import(self, atendimento_ids: list) -> dict:
    """Enfileira e agenda envio WhatsApp para um lote de Atendimentos importados."""
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
    """
    Envia uma mensagem WhatsApp para um Atendimento.

    Padrão de duas transações:
    - Tx1: valida + lock + marca PROCESSANDO + commit
    - Chamada HTTP (fora de qualquer atomic())
    - Tx2: grava resultado + atualiza status + commit
    """
    from django.utils import timezone
    from atendimentos.models import Atendimento
    from whatsapp.models import ConfiguracaoSistema, EnvioWhatsAppLog
    from whatsapp.services.sender import WhatsAppSendService

    # === Tx1: validação e bloqueio ===
    try:
        with transaction.atomic():
            atendimento = (
                Atendimento.objects
                .select_for_update(skip_locked=True)
                .get(pk=atendimento_id, status_enviado__in=["N", "E"])
            )
            empresa = atendimento.empresa

            config = _get_configuracao(empresa)
            hoje = timezone.now().date()

            # Contagem de envios do dia para esta empresa (ou global se sem empresa)
            enviados_qs = EnvioWhatsAppLog.objects.filter(enviado_em__date=hoje, sucesso=True)
            if empresa is not None:
                enviados_qs = enviados_qs.filter(empresa=empresa)
            enviados_hoje = enviados_qs.count()

            limite = config.limite_diario_mensagens
            if enviados_hoje >= limite:
                Atendimento.objects.filter(
                    pk=atendimento_id, status_enviado__in=["N", "E"]
                ).update(status_enviado="L")
                EnvioWhatsAppLog.objects.create(
                    empresa=empresa,
                    atendimento_id=atendimento_id,
                    telefone="",
                    mensagem="",
                    status_retorno="LIMITE_DIARIO",
                    detalhe_retorno=f"Limite diário de {limite} mensagens atingido.",
                    sucesso=False,
                )
                logger.warning(
                    "Limite diário atingido (empresa=%s, atendimento=%s).",
                    empresa, atendimento_id,
                )
                return False

            # Captura dados necessários antes de sair da Tx1
            atendimento_snapshot = {
                "pk": atendimento.pk,
                "paciente": atendimento.paciente,
                "telefone": atendimento.telefone,
                "exame_procedimento": atendimento.exame_procedimento,
                "empresa_id": empresa.pk if empresa else None,
            }

    except Atendimento.DoesNotExist:
        logger.info("Atendimento %s ignorado (não encontrado, já enviado ou bloqueado).", atendimento_id)
        return True

    # === Chamada HTTP — fora de qualquer transação ===
    try:
        service = WhatsAppSendService()
        atendimento_obj = Atendimento.objects.get(pk=atendimento_id)
        success = service.send_for_atendimento(atendimento_obj)
    except Exception as exc:
        logger.error("Erro HTTP ao enviar atendimento %s: %s", atendimento_id, exc)
        if self.request.retries >= self.max_retries:
            Atendimento.objects.filter(pk=atendimento_id, status_enviado="E").update(
                status_enviado="N"
            )
        raise self.retry(exc=exc)

    # === Tx2: grava resultado ===
    try:
        with transaction.atomic():
            if not success:
                Atendimento.objects.filter(
                    pk=atendimento_id, status_enviado="E"
                ).update(status_enviado="N")
    except Exception as exc:
        logger.error("Erro ao salvar resultado da Tx2 (atendimento=%s): %s", atendimento_id, exc)

    logger.info("Atendimento %s — %s", atendimento_id, "OK" if success else "FALHA")
    return success
