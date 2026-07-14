import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from core.services.rate_limit import acquire_rate_slot

logger = logging.getLogger(__name__)

_DISPATCH_DELAY_SECONDS = 3


def _get_configuracao(empresa=None):
    from whatsapp.models import ConfiguracaoDisparo, ConfiguracaoSistema
    if empresa is not None:
        config, _ = ConfiguracaoDisparo.objects.get_or_create(empresa=empresa)
        return config
    return ConfiguracaoSistema.get()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def dispatch_batch_after_import(self, atendimento_ids: list, empresa_id: int = None) -> dict:
    """Enfileira e agenda envio WhatsApp para um lote de Atendimentos importados."""
    from atendimentos.models import Atendimento
    from core.tenant_context import reset_session_tenant, set_session_tenant, set_tenant

    if not atendimento_ids:
        return {"scheduled": 0, "skipped": 0}

    set_session_tenant(empresa_id)
    try:
        try:
            with transaction.atomic():
                set_tenant(empresa_id)
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
                args=[aid, empresa_id],
                countdown=i * _DISPATCH_DELAY_SECONDS,
            )

        logger.info("Lote de %d mensagens agendadas para disparo.", updated)
        return {"scheduled": updated, "skipped": skipped}
    finally:
        reset_session_tenant()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_whatsapp_for_atendimento(self, atendimento_id: int, empresa_id: int = None) -> bool:
    """
    Envia uma mensagem WhatsApp para um Atendimento.

    Padrão:
    - set_session_tenant no início (nível de sessão, sobrevive a commits)
    - Tx1: valida + lock + verifica limite + commit
    - HTTP via WhatsAppSendService (fora de atomic; tenant ainda ativo na sessão)
    - Tx2: reverte status em caso de falha
    - reset_session_tenant no finally
    """
    from atendimentos.models import Atendimento
    from billing.utils import empresa_pode_disparar
    from core.tenant_context import reset_session_tenant, set_session_tenant, set_tenant
    from whatsapp.models import EnvioWhatsAppLog
    from whatsapp.services.sender import WhatsAppSendService

    set_session_tenant(empresa_id)
    try:
        # === Tx1: validação e bloqueio ===
        try:
            with transaction.atomic():
                set_tenant(empresa_id)

                atendimento = (
                    Atendimento.objects
                    .select_for_update(skip_locked=True)
                    .get(pk=atendimento_id, status_enviado__in=["N", "E"])
                )
                empresa = atendimento.empresa

                pode, motivo = empresa_pode_disparar(empresa)
                if not pode:
                    Atendimento.objects.filter(
                        pk=atendimento_id, status_enviado__in=["N", "E"]
                    ).update(status_enviado="L")
                    EnvioWhatsAppLog.objects.create(
                        empresa=empresa,
                        atendimento_id=atendimento_id,
                        telefone="",
                        mensagem="",
                        status_retorno="BILLING_BLOQUEADO",
                        detalhe_retorno=motivo,
                        sucesso=False,
                    )
                    logger.warning(
                        "Disparo bloqueado por billing (empresa=%s, atendimento=%s): %s",
                        empresa_id, atendimento_id, motivo,
                    )
                    return False

                config = _get_configuracao(empresa)
                hoje = timezone.now().date()

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
                        empresa_id, atendimento_id,
                    )
                    return False

        except Atendimento.DoesNotExist:
            logger.info(
                "Atendimento %s ignorado (não encontrado, já enviado ou bloqueado).",
                atendimento_id,
            )
            return True

        # === Rate limiting por canal ===
        from whatsapp.models import CanalWhatsApp
        canal = CanalWhatsApp.objects.filter(empresa=empresa, principal=True, ativo=True).first()
        limit_per_minute = getattr(config, "mensagens_por_minuto", 20)
        if canal and not acquire_rate_slot(canal.pk, limit_per_minute):
            seconds_to_next_window = 60 - timezone.now().second + 2
            logger.info(
                "Rate limit atingido para canal %s (%d/min, empresa=%s). Reagendando em %ds.",
                canal.pk, limit_per_minute, empresa_id, seconds_to_next_window,
            )
            raise self.retry(
                countdown=seconds_to_next_window,
                exc=Exception(f"Rate limit canal {canal.pk}"),
            )

        # === HTTP — fora de atomic(); tenant ativo na sessão garante RLS ===
        try:
            atendimento_obj = Atendimento.objects.get(pk=atendimento_id)
            service = WhatsAppSendService()
            success = service.send_for_atendimento(atendimento_obj)
        except Atendimento.DoesNotExist:
            logger.error("Atendimento %s desapareceu entre Tx1 e HTTP.", atendimento_id)
            return False
        except Exception as exc:
            logger.error("Erro ao enviar atendimento %s: %s", atendimento_id, exc)
            if self.request.retries >= self.max_retries:
                with transaction.atomic():
                    set_tenant(empresa_id)
                    Atendimento.objects.filter(pk=atendimento_id, status_enviado="E").update(
                        status_enviado="N"
                    )
            raise self.retry(exc=exc)

        # === Tx2: reverte status se o envio falhou ===
        if not success:
            try:
                with transaction.atomic():
                    set_tenant(empresa_id)
                    Atendimento.objects.filter(
                        pk=atendimento_id, status_enviado="E"
                    ).update(status_enviado="N")
            except Exception as exc:
                logger.error("Erro ao reverter status (atendimento=%s): %s", atendimento_id, exc)

        logger.info("Atendimento %s — %s", atendimento_id, "OK" if success else "FALHA")
        return success

    finally:
        reset_session_tenant()
