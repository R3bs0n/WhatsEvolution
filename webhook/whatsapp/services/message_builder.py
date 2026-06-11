_DEFAULT_TEMPLATE = (
    "Olá, {nome_paciente}.\n\n"
    "Informamos que o procedimento *{tipo_exame}* foi autorizado pelo SUS para realização na "
    "Clínica Médica Saúde Popular.\n\n"
    "📅 Entre em contato para confirmar sua consulta ou obter mais informações:\n"
    "👉 {contato_url}\n\n"
    "Atenciosamente,\nClínica Médica Saúde Popular"
)


def build_message(nome_paciente: str, tipo_exame: str) -> str:
    from django.conf import settings

    template = getattr(settings, "WHATSAPP_MESSAGE_TEMPLATE", "") or _DEFAULT_TEMPLATE
    contato_url = getattr(settings, "WHATSAPP_CONTACT_URL", "") or "https://wa.me/5548988762025"

    return template.format(
        nome_paciente=nome_paciente or "Paciente",
        tipo_exame=tipo_exame or "procedimento",
        contato_url=contato_url,
    )
