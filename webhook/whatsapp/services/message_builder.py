_DEFAULT_TEMPLATE = (
    "Ola, {nome_paciente}.\n\n"
    "Informamos que o procedimento *{tipo_exame}* foi autorizado pelo SUS para "
    "realizacao na {empresa_nome}.\n\n"
    "Entre em contato para confirmar sua consulta ou obter mais informacoes:\n"
    "{contato_url}\n\n"
    "Atenciosamente,\n{empresa_nome}\n\n"
    "_(Responda SAIR para nao receber mais mensagens)_"
)


def _empresa_nome(empresa, settings):
    nome = getattr(empresa, "nome", "") if empresa else ""
    return nome or getattr(settings, "WHATSAPP_DEFAULT_COMPANY_NAME", "")


def _configuracao_disparo(empresa):
    if not empresa:
        return None
    try:
        return empresa.configuracao_disparo
    except Exception:
        return None


def build_message(nome_paciente: str, tipo_exame: str, empresa=None) -> str:
    from django.conf import settings

    template = getattr(settings, "WHATSAPP_MESSAGE_TEMPLATE", "") or _DEFAULT_TEMPLATE
    config = _configuracao_disparo(empresa)
    contato_url = (
        getattr(config, "contato_url", "")
        or getattr(settings, "WHATSAPP_CONTACT_URL", "")
        or "https://wa.me/5548988762025"
    )

    mensagem = template.format(
        nome_paciente=nome_paciente or "Paciente",
        tipo_exame=tipo_exame or "procedimento",
        contato_url=contato_url,
        empresa_nome=_empresa_nome(empresa, settings),
    )

    privacy_url = (
        getattr(config, "privacy_policy_url", "")
        or getattr(settings, "WHATSAPP_PRIVACY_POLICY_URL", "")
    )
    if privacy_url:
        mensagem += f"\n\nPolitica de Privacidade: {privacy_url}"

    return mensagem
