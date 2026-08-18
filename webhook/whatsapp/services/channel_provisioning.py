"""Provisionamento INICIAL do canal WHATSAPP-BUSINESS na Evolution a partir do
MetaCloudCredential do Django — a "unificação de canal".

Escopo desta etapa (decidido com Codex + skill de arquitetura): só cria a
instância na Evolution quando NENHUMA instância com esse nome existe ainda.
Nunca faz delete/recreate — a Evolution não tem endpoint de update de
credenciais (confirmado lendo o código-fonte dela: só create/restart/connect/
connectionState/fetchInstances/setPresence/logout/delete), e um delete+create
automático sem rollback confiável foi julgado arriscado demais pra esta fase
(nenhum tenant real usa isso ainda). Reprovisionamento fica pra uma etapa
futura, com um design de rollback mais maduro.

Ação sempre EXPLÍCITA — nunca dispara sozinho a partir de um save() do model.
"""
import hmac
import logging

import httpx
import redis
from django.conf import settings
from django.utils import timezone

from core.fields import TokenDecryptionError
from core.integrations.evolution.client import EvolutionClient
from whatsapp.models import CanalWhatsApp, MetaCloudCredential

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "channel-provisioning-lock:"
_LOCK_TIMEOUT = 90  # segundos — folga confortável acima do pior caso (2 chamadas HTTP + DB)


class ChannelProvisioningError(Exception):
    """Erro de provisionamento com mensagem já sanitizada pro operador
    (nunca contém token/segredo) — segura de mostrar na UI do admin."""


def _lock_key(credencial_id: int) -> str:
    return f"{_LOCK_PREFIX}{credencial_id}"


def _redis_client() -> "redis.Redis":
    # Cliente redis-py dedicado (não passa pelo cache do Django) só pra
    # locking: precisamos do Lock nativo do redis-py, que faz o release via
    # script Lua comparando o token do dono antes de apagar -- um
    # compare-and-delete atômico de verdade no servidor. A versão anterior
    # fazia cache.get() + cache.delete() do Django em duas chamadas
    # separadas, com uma janela de corrida real entre elas (achado do Codex
    # na revisão).
    return redis.Redis.from_url(settings.REDIS_URL)


def _find_existing_instance(instances: list[dict], instance_name: str) -> dict | None:
    """Procura pelo nome numa lista já buscada via fetch_instances(). Nunca
    logar `instances` inteiro -- a Evolution devolve o token de TODAS as
    instâncias em texto puro nesse endpoint (confirmado ao vivo)."""
    for item in instances:
        if item.get("name") == instance_name:
            return item
    return None


def provision_meta_channel(credencial_id: int) -> MetaCloudCredential:
    """Ponto de entrada único e explícito do provisionamento inicial.

    Levanta ChannelProvisioningError (mensagem sanitizada, segura pra UI) em
    qualquer falha. Nunca decifra o token antes do momento exato de usá-lo.
    """
    lock_key = _lock_key(credencial_id)
    lock = _redis_client().lock(lock_key, timeout=_LOCK_TIMEOUT)
    try:
        acquired = lock.acquire(blocking=False)
    except redis.exceptions.RedisError as exc:
        detalhe = f"Falha ao falar com o Redis pra travar o provisionamento ({type(exc).__name__})."
        logger.error("Provisionamento (lock) da credencial %s: %s", credencial_id, detalhe)
        raise ChannelProvisioningError(detalhe)

    if not acquired:
        raise ChannelProvisioningError(
            "Já existe um provisionamento em andamento para esta credencial. Aguarde e tente novamente."
        )

    try:
        return _provision_locked(credencial_id)
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            # release() do redis-py só levanta isso quando o valor no Redis
            # não bate mais com o token local -- ou porque o lease expirou e
            # outra operação já assumiu a chave, ou porque ela já não existe
            # mais por algum outro motivo. Em qualquer um desses casos não há
            # nada nosso pra liberar; deixar quieto é o comportamento correto.
            pass
        except redis.exceptions.RedisError as exc:
            # Erro de conexão (não de ownership) no release: o TTL do lease
            # (_LOCK_TIMEOUT) garante que a chave expira sozinha mesmo se
            # este release nunca chegar ao servidor -- só loga, não propaga
            # (o provisionamento em si já terminou, sucesso ou erro).
            logger.error(
                "Provisionamento (lock release) da credencial %s: falha ao falar com o Redis (%s).",
                credencial_id, type(exc).__name__,
            )


def _mark_erro(credencial: MetaCloudCredential, detalhe: str) -> None:
    credencial.status = MetaCloudCredential.STATUS_ERRO
    credencial.detalhe_provisionamento = detalhe
    credencial.save(update_fields=["status", "detalhe_provisionamento", "updated_at"])


def _mark_configurado(credencial: MetaCloudCredential, detalhe: str) -> None:
    credencial.status = MetaCloudCredential.STATUS_CONFIGURADO
    credencial.detalhe_provisionamento = detalhe
    credencial.save(update_fields=["status", "detalhe_provisionamento", "updated_at"])


def _decrypt_token_or_raise(credencial: MetaCloudCredential) -> str:
    try:
        token = credencial.meta_access_token
    except TokenDecryptionError:
        # Nunca deixa isso subir cru pro admin -- mesma sanitização de
        # qualquer outro erro deste serviço. Ciphertext corrompido/chave
        # errada é uma condição real de erro, não uma exceção interna.
        detalhe = "Token de acesso (meta_access_token) não pôde ser decifrado."
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)
    if not token:
        detalhe = "Token de acesso (meta_access_token) não preenchido na credencial."
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)
    return token


def _provision_locked(credencial_id: int) -> MetaCloudCredential:
    try:
        # .defer() -- nunca decifrar aqui. O token só é lido explicitamente
        # mais abaixo, no exato momento em que é realmente necessário (seja
        # pra comparar com o que já está na Evolution, seja pra criar).
        credencial = (
            MetaCloudCredential.objects
            .defer("meta_access_token")
            .select_related("canal")
            .get(pk=credencial_id)
        )
    except MetaCloudCredential.DoesNotExist:
        raise ChannelProvisioningError("Credencial não encontrada.")

    canal = credencial.canal

    # Proteção obrigatória: nunca provisionar/tocar um canal que não seja
    # WHATSAPP-BUSINESS de verdade -- não confiar só no fato de existir um
    # MetaCloudCredential apontando pra ele (o model.clean() já impede isso
    # na maioria dos caminhos, mas esta é uma entrada sensível o bastante
    # pra não confiar cegamente nessa validação ter rodado antes).
    if canal.provider != CanalWhatsApp.PROVIDER_BUSINESS:
        detalhe = (
            f"Canal '{canal.nome}' não é WHATSAPP-BUSINESS (provider={canal.provider!r}) "
            "— provisionamento recusado por segurança."
        )
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)

    if not canal.instance_name:
        detalhe = f"Canal '{canal.nome}' não tem instance_name definido."
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)

    if not credencial.phone_number_id:
        detalhe = "Phone Number ID (phone_number_id) não preenchido na credencial."
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)

    # EvolutionClient sempre monta a URL a partir de settings.EVOLUTION_API_URL
    # -- nunca aceitar/repassar uma URL vinda de fora daqui (evita SSRF).
    client = EvolutionClient(instance_name=canal.instance_name)

    try:
        instances = client.fetch_instances()
    except httpx.HTTPError as exc:
        detalhe = f"Falha ao consultar instâncias existentes na Evolution ({type(exc).__name__})."
        logger.error("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)

    existing = _find_existing_instance(instances, canal.instance_name)
    if existing is not None:
        existing_integration = existing.get("integration")
        if existing_integration != CanalWhatsApp.PROVIDER_BUSINESS:
            # Acharia uma instância com esse nome que NÃO é Business -- pode
            # ser a instância Baileys da clínica, ou qualquer outra coisa.
            # Nunca tocar. Isto é a proteção contra atingir o fluxo Baileys.
            detalhe = (
                f"Já existe uma instância '{canal.instance_name}' na Evolution, mas com "
                f"integration={existing_integration!r} (esperado {CanalWhatsApp.PROVIDER_BUSINESS!r}). "
                "Provisionamento abortado por segurança — nada foi alterado na Evolution."
            )
            logger.error("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
            _mark_erro(credencial, detalhe)
            raise ChannelProvisioningError(detalhe)

        # Nome + integration batendo sozinho não prova que a instância
        # pertence a ESTA credencial -- confere number e businessId antes de
        # seguir. Sem isso, uma instância de outro tenant/credencial com o
        # mesmo nome seria adotada silenciosamente (achado do Codex).
        existing_number = existing.get("number")
        existing_business_id = existing.get("businessId")
        if (
            existing_number != credencial.phone_number_id
            or existing_business_id != credencial.waba_id
        ):
            detalhe = (
                f"Já existe uma instância '{canal.instance_name}' na Evolution como "
                "WHATSAPP-BUSINESS, mas com number/businessId diferentes dos desta "
                "credencial. Provisionamento abortado por segurança — nada foi "
                "alterado na Evolution."
            )
            logger.error("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
            _mark_erro(credencial, detalhe)
            raise ChannelProvisioningError(detalhe)

        # number/businessId batem, mas isso não prova que a Evolution está
        # usando o token ATUAL do Django -- não existe endpoint de update, e
        # o token pode ter sido rotacionado no Django sem a instância ser
        # tocada na Evolution (a chamada fetchInstances devolve o token em
        # texto puro, então dá pra comparar diretamente -- confirmado ao
        # vivo). Decifra aqui só pra essa comparação; nunca loga nenhum dos
        # dois valores (achado do Codex: "comparar só number/businessId não
        # detecta rotação de token").
        token = _decrypt_token_or_raise(credencial)
        try:
            # compare_digest em vez de != -- os dois valores vêm de fontes
            # internas (Django e Evolution), sem canal de timing exposto de
            # fato, mas é uma comparação de segredo e o custo de usar a
            # função certa é zero (endurecimento sugerido pelo Codex).
            if not hmac.compare_digest(existing.get("token") or "", token):
                detalhe = (
                    f"Instância '{canal.instance_name}' já existe na Evolution com "
                    "number/businessId compatíveis, mas o token configurado nela diverge "
                    "do token atual desta credencial no Django. Fora do escopo desta etapa "
                    "(sem delete/recreate) — reprovisionamento manual necessário. Nada foi "
                    "alterado na Evolution."
                )
                logger.error("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
                _mark_erro(credencial, detalhe)
                raise ChannelProvisioningError(detalhe)
        finally:
            token = None  # não deixa a referência decifrada viva mais que o necessário

        # Já existe, já é Business, number/businessId E token batem com esta
        # credencial -- idempotente de verdade: não cria de novo, só
        # confirma o estado atual. Nunca tenta delete/recreate nesta etapa
        # (fora de escopo).
        detalhe = (
            f"Instância '{canal.instance_name}' já existe na Evolution como WHATSAPP-BUSINESS "
            "com number/businessId/token compatíveis. Nenhuma ação realizada (idempotente)."
        )
        logger.info("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
        _mark_configurado(credencial, detalhe)
        return credencial

    # Não existe ainda -- decifra o token só agora, no momento exato do uso.
    token = _decrypt_token_or_raise(credencial)

    try:
        client.create_instance(
            canal.instance_name,
            integration=CanalWhatsApp.PROVIDER_BUSINESS,
            number=credencial.phone_number_id,
            token=token,
            business_id=credencial.waba_id,
        )
    except httpx.HTTPStatusError as exc:
        # Nunca logar/persistir o corpo da resposta ou da exceção completa
        # -- pode ecoar o token que acabamos de enviar. Só o status code.
        detalhe = f"Evolution recusou a criação da instância (HTTP {exc.response.status_code})."
        logger.error("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)
    except httpx.HTTPError as exc:
        detalhe = f"Falha de comunicação com a Evolution ao criar a instância ({type(exc).__name__})."
        logger.error("Provisionamento do canal '%s': %s", canal.instance_name, detalhe)
        _mark_erro(credencial, detalhe)
        raise ChannelProvisioningError(detalhe)
    finally:
        token = None  # não deixa a referência decifrada viva mais que o necessário

    detalhe = f"Instância '{canal.instance_name}' criada na Evolution em {timezone.now():%d/%m/%Y %H:%M}."
    logger.info("Provisionamento do canal '%s': sucesso.", canal.instance_name)
    _mark_configurado(credencial, detalhe)
    return credencial
