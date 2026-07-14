import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def empresa_pode_disparar(empresa) -> tuple[bool, str]:
    """
    Retorna (pode: bool, motivo: str).

    Regras:
    - Empresa None: bloqueia sempre.
    - Assinatura suspensa/cancelada: bloqueia.
    - Assinatura em carencia dentro do prazo: permite.
    - Sem assinatura cadastrada: depende de BILLING_GRACE_MODE.
    """
    if empresa is None:
        return False, "Empresa nao identificada na sessao."

    from .models import Assinatura

    try:
        assinatura = empresa.assinatura
        if not assinatura.esta_ativa():
            motivo = (
                f"Assinatura {assinatura.get_status_display().lower()}. "
                "Renove o plano para continuar disparando."
            )
            logger.warning(
                "Disparo bloqueado - billing (empresa=%s, status=%s).",
                empresa.pk,
                assinatura.status,
            )
            return False, motivo
    except Assinatura.DoesNotExist:
        if not getattr(settings, "BILLING_GRACE_MODE", True):
            logger.warning(
                "Disparo bloqueado: empresa %s sem assinatura e grace mode desligado.",
                empresa.pk,
            )
            return False, "Empresa sem assinatura ativa para disparos."

        logger.debug(
            "Empresa %s sem assinatura - disparo permitido (grace mode).",
            empresa.pk,
        )

    return True, ""
