_BASE_MESSAGE = (
    "Olá, {nome_paciente}.\n\n"
    "Informamos que o procedimento *{tipo_exame}* foi autorizado pelo SUS para realização na "
    "Clínica Médica Saúde Popular.\n\n"
    "📅 Entre em contato para confirmar sua consulta ou obter mais informações:\n"
    "👉 https://wa.me/5548988762025\n\n"
    "Atenciosamente,\nClínica Médica Saúde Popular"
)


def build_message(nome_paciente: str, tipo_exame: str) -> str:
    return _BASE_MESSAGE.format(
        nome_paciente=nome_paciente or "Paciente",
        tipo_exame=tipo_exame or "procedimento",
    )
