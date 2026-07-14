import logging

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60


def acquire_rate_slot(canal_id: int, limit_per_minute: int) -> bool:
    """
    Tenta adquirir um slot de envio dentro da janela de 1 minuto para este canal.
    Usa Redis via Django cache (operações atômicas: add + incr).
    Retorna True se pode enviar, False se o limite foi atingido.
    """
    from django.core.cache import cache
    from django.utils import timezone

    bucket = timezone.now().strftime("%Y%m%d%H%M")
    key = f"rl:canal:{canal_id}:{bucket}"

    # cache.add() é atômico no Redis: só escreve se a chave não existir
    cache.add(key, 0, timeout=_RATE_WINDOW_SECONDS + 10)
    try:
        count = cache.incr(key)
    except ValueError:
        # Raro: chave expirou entre add e incr
        cache.set(key, 1, timeout=_RATE_WINDOW_SECONDS + 10)
        count = 1

    if count > limit_per_minute:
        try:
            cache.decr(key)
        except Exception:
            logger.debug("Nao foi possivel devolver slot de rate limit para canal %s.", canal_id)
        return False

    return True
