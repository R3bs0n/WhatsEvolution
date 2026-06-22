import logging
import uuid

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)

_DELAY_SECONDS = 3


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def dispatch_campanha(self, campanha_id: int) -> dict:
    """
    Materializa os destinatários de uma campanha e agenda os envios.

    Padrão de duas transações:
    - Tx1: carrega campanha + segmento → cria DestinatarioCampanha (snapshots) → commit
    - Por destinatário: agenda send_mensagem_campanha como task Celery
    """
    from campanhas.models import Campanha, DestinatarioCampanha
    from whatsapp.models import CanalWhatsApp

    try:
        campanha = Campanha.objects.select_related(
            "segmento", "template", "canal", "empresa"
        ).get(pk=campanha_id)
    except Campanha.DoesNotExist:
        logger.error("Campanha %s não encontrada.", campanha_id)
        return {"error": "not_found"}

    empresa = campanha.empresa
    contatos = list(campanha.segmento.contatos.filter(ativo=True))

    if not contatos:
        campanha.status = "concluida"
        campanha.save(update_fields=["status"])
        logger.warning("Campanha %s sem contatos ativos.", campanha_id)
        return {"scheduled": 0}

    # Tx1: materializa destinatários (snapshots imutáveis)
    with transaction.atomic():
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
        "Campanha %s: %d destinatários materializados.",
        campanha_id, len(destinatarios_criados)
    )

    # Agenda envio individual para cada destinatário
    for i, dest in enumerate(destinatarios_criados):
        send_mensagem_campanha.apply_async(
            args=[dest.pk],
            countdown=i * _DELAY_SECONDS,
        )

    return {"scheduled": len(destinatarios_criados)}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_mensagem_campanha(self, destinatario_id: int) -> bool:
    """
    Envia a mensagem para um DestinatarioCampanha individual.

    Padrão de duas transações:
    - Tx1: valida + lock + marca PROCESSANDO + commit
    - HTTP: chama a Evolution API
    - Tx2: grava resultado + commit
    """
    from campanhas.models import DestinatarioCampanha
    from whatsapp.models import CanalWhatsApp, ContatoBloqueado, EnvioMensagem
    from whatsapp.services.sender import WhatsAppSendService

    # Tx1
    try:
        with transaction.atomic():
            dest = (
                DestinatarioCampanha.objects
                .select_related("campanha__empresa", "campanha__template", "campanha__canal")
                .select_for_update(skip_locked=True)
                .get(pk=destinatario_id, status="pendente")
            )
            empresa = dest.campanha.empresa
            telefone = dest.telefone_snapshot

            # Verifica opt-out
            if ContatoBloqueado.objects.for_empresa(empresa).filter(telefone=telefone).exists():
                dest.status = "optout"
                dest.save(update_fields=["status"])
                return False

            dest.status = "processando"
            dest.save(update_fields=["status"])

            # Renderiza mensagem com template
            template = dest.campanha.template
            if template:
                try:
                    conteudo = template.renderizar(dest.variaveis_snapshot)
                except ValueError as e:
                    dest.status = "falha"
                    dest.erro = str(e)
                    dest.save(update_fields=["status", "erro"])
                    return False
            else:
                conteudo = dest.variaveis_snapshot.get("mensagem", "")

            idempotency_key = f"campanha-{dest.campanha_id}-dest-{dest.pk}"

    except DestinatarioCampanha.DoesNotExist:
        return True

    # HTTP (fora de atomic())
    try:
        from django.conf import settings
        canal = dest.campanha.canal
        instance_name = canal.instance_name if canal else settings.EVOLUTION_INSTANCE_NAME

        from evolution.services import EvolutionAPIClient
        client = EvolutionAPIClient()
        result = client.send_text(instance_name, telefone, conteudo)
        success = result.get("success", False)
        external_id = result.get("key", {}).get("id", "")
    except Exception as exc:
        logger.error("Erro HTTP enviando destinatário %s: %s", destinatario_id, exc)
        if self.request.retries >= self.max_retries:
            with transaction.atomic():
                DestinatarioCampanha.objects.filter(pk=destinatario_id).update(
                    status="falha", erro=str(exc)
                )
        raise self.retry(exc=exc)

    # Tx2: grava resultado
    with transaction.atomic():
        if success:
            DestinatarioCampanha.objects.filter(pk=destinatario_id).update(status="enviado")
        else:
            DestinatarioCampanha.objects.filter(pk=destinatario_id).update(
                status="falha", erro="Falha no envio"
            )

    return success
