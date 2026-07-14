import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from core.services.rate_limit import acquire_rate_slot

logger = logging.getLogger(__name__)

_DELAY_SECONDS = 3


def _get_configuracao(empresa=None):
    from whatsapp.models import ConfiguracaoDisparo, ConfiguracaoSistema

    if empresa is not None:
        config, _ = ConfiguracaoDisparo.objects.get_or_create(empresa=empresa)
        return config
    return ConfiguracaoSistema.get()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def dispatch_campanha(self, campanha_id: int, empresa_id: int = None) -> dict:
    """Materializa destinatarios de uma campanha e agenda envios individuais."""
    from billing.utils import empresa_pode_disparar
    from campanhas.models import Campanha, DestinatarioCampanha
    from core.tenant_context import reset_session_tenant, set_session_tenant, set_tenant

    set_session_tenant(empresa_id)
    try:
        try:
            with transaction.atomic():
                set_tenant(empresa_id)
                campanha = (
                    Campanha.objects
                    .select_related("segmento", "template", "canal", "empresa")
                    .get(pk=campanha_id)
                )
        except Campanha.DoesNotExist:
            logger.error("Campanha %s nao encontrada.", campanha_id)
            return {"error": "not_found"}

        pode, motivo = empresa_pode_disparar(campanha.empresa)
        if not pode:
            with transaction.atomic():
                set_tenant(empresa_id)
                Campanha.objects.filter(pk=campanha_id).update(status="pausada")
            logger.warning("Campanha %s bloqueada por billing: %s", campanha_id, motivo)
            return {"error": "billing_blocked"}

        contatos = list(campanha.segmento.contatos.filter(ativo=True))
        if not contatos:
            with transaction.atomic():
                set_tenant(empresa_id)
                campanha.status = "concluida"
                campanha.save(update_fields=["status"])
            logger.warning("Campanha %s sem contatos ativos.", campanha_id)
            return {"scheduled": 0}

        with transaction.atomic():
            set_tenant(empresa_id)
            destinatarios_criados = []
            for contato in contatos:
                dest, created = DestinatarioCampanha.objects.get_or_create(
                    campanha=campanha,
                    contato=contato,
                    defaults={
                        "nome_snapshot": contato.nome,
                        "telefone_snapshot": contato.telefone,
                        "variaveis_snapshot": {"nome": contato.nome},
                        "status": "pendente",
                    },
                )
                if created:
                    destinatarios_criados.append(dest)

        logger.info(
            "Campanha %s: %d destinatarios materializados.",
            campanha_id,
            len(destinatarios_criados),
        )

        for i, dest in enumerate(destinatarios_criados):
            send_mensagem_campanha.apply_async(
                args=[dest.pk, empresa_id],
                countdown=i * _DELAY_SECONDS,
            )

        return {"scheduled": len(destinatarios_criados)}
    finally:
        reset_session_tenant()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_mensagem_campanha(self, destinatario_id: int, empresa_id: int = None) -> bool:
    """Envia uma mensagem individual de campanha."""
    from billing.utils import empresa_pode_disparar
    from campanhas.models import DestinatarioCampanha
    from core.integrations.evolution.client import EvolutionClient
    from core.tenant_context import reset_session_tenant, set_session_tenant, set_tenant
    from whatsapp.models import ContatoBloqueado

    set_session_tenant(empresa_id)
    try:
        try:
            with transaction.atomic():
                set_tenant(empresa_id)
                dest = (
                    DestinatarioCampanha.objects
                    .select_related("campanha__empresa", "campanha__template", "campanha__canal")
                    .select_for_update(skip_locked=True)
                    .get(pk=destinatario_id, status="pendente")
                )
                empresa = dest.campanha.empresa
                telefone = dest.telefone_snapshot
                canal = dest.campanha.canal

                pode, motivo = empresa_pode_disparar(empresa)
                if not pode:
                    dest.status = "falha"
                    dest.erro = motivo
                    dest.save(update_fields=["status", "erro"])
                    return False

                if ContatoBloqueado.objects.for_empresa(empresa).filter(telefone=telefone).exists():
                    dest.status = "optout"
                    dest.save(update_fields=["status"])
                    return False

                config = _get_configuracao(empresa)
                limit_per_minute = getattr(config, "mensagens_por_minuto", 20)
                if canal and not acquire_rate_slot(canal.pk, limit_per_minute):
                    seconds_to_next_window = 60 - timezone.now().second + 2
                    logger.info(
                        "Rate limit atingido para canal %s (%d/min, empresa=%s). Reagendando em %ds.",
                        canal.pk,
                        limit_per_minute,
                        empresa_id,
                        seconds_to_next_window,
                    )
                    raise self.retry(
                        countdown=seconds_to_next_window,
                        exc=Exception(f"Rate limit canal {canal.pk}"),
                    )

                dest.status = "processando"
                dest.save(update_fields=["status"])

                template = dest.campanha.template
                if template:
                    try:
                        conteudo = template.renderizar(dest.variaveis_snapshot)
                    except ValueError as exc:
                        dest.status = "falha"
                        dest.erro = str(exc)
                        dest.save(update_fields=["status", "erro"])
                        return False
                else:
                    conteudo = dest.variaveis_snapshot.get("mensagem", "")

        except DestinatarioCampanha.DoesNotExist:
            return True

        try:
            client = EvolutionClient(
                instance_name=canal.instance_name if canal else None,
                api_url=canal.api_url if canal else None,
            )
            client.send_text(telefone, conteudo)
            success = True
        except Exception as exc:
            logger.error("Erro HTTP enviando destinatario %s: %s", destinatario_id, exc)
            if self.request.retries >= self.max_retries:
                with transaction.atomic():
                    set_tenant(empresa_id)
                    DestinatarioCampanha.objects.filter(pk=destinatario_id).update(
                        status="falha",
                        erro=str(exc),
                    )
            raise self.retry(exc=exc)

        with transaction.atomic():
            set_tenant(empresa_id)
            DestinatarioCampanha.objects.filter(pk=destinatario_id).update(
                status="enviado" if success else "falha"
            )

        return success
    finally:
        reset_session_tenant()
