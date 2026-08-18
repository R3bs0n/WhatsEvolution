"""Registro do MAPEAMENTO POSICIONAL de variáveis por template aprovado.

Provisório de propósito: NÃO é o modelo de template sincronizado com a Meta
(categoria/idioma/status via API) — essa é a próxima peça, ainda não
construída (ver Trilha do projeto). Aqui o template é só um nome + idioma com
uma ordem de variáveis declarada à mão.

Formato exigido pela Cloud API (confirmado ao vivo contra a Evolution
instalada — ver relatório da investigação): dentro de `components`, o objeto
`{"type": "body", "parameters": [...]}` tem `parameters` POSICIONAL — índice 0
vira {{1}} no template aprovado, índice 1 vira {{2}}, e assim por diante. A
Evolution não reordena nem valida isso — repassa como está pro Graph API da
Meta, então a ordem abaixo precisa bater exatamente com o template aprovado.
"""
from __future__ import annotations


class TemplateVariableError(Exception):
    """Erro claro de configuração/uso do template — nunca monta components
    incompleto ou fora de ordem silenciosamente."""


# (nome_do_template, idioma) -> ordem exata das variáveis nomeadas
TEMPLATE_VARIABLE_ORDER: dict[tuple[str, str], list[str]] = {
    ("confirmacao_sus", "pt_BR"): ["nome_paciente", "tipo_exame"],
}


def list_available_templates() -> list[tuple[str, str]]:
    """(nome, idioma) de todo template com ordem de variáveis registrada.

    Única forma que qualquer UI deve usar pra listar templates disponíveis --
    nunca hardcodar um nome de template numa view/form. Quando a sincronização
    real com a Graph API da Meta for construída, esta função (ou o que a
    substituir) continua sendo o único ponto de leitura.
    """
    return list(TEMPLATE_VARIABLE_ORDER.keys())


def build_template_components(template_name: str, language: str, variables: dict) -> list[dict]:
    """Monta o `components` no formato da Cloud API a partir de variáveis
    NOMEADAS, na ordem certa pro template. Só suporta corpo de texto simples
    (um único component tipo "body", parâmetros tipo "text") — de propósito,
    é o escopo combinado para esta etapa; template com header/botão/mídia
    precisa de suporte novo, não deve cair aqui silenciosamente.
    """
    chave = (template_name, language)
    ordem = TEMPLATE_VARIABLE_ORDER.get(chave)
    if ordem is None:
        raise TemplateVariableError(
            f"Template {template_name!r} (idioma {language!r}) não tem ordem de "
            "variáveis registrada em TEMPLATE_VARIABLE_ORDER."
        )

    faltando = [nome for nome in ordem if not variables.get(nome)]
    if faltando:
        raise TemplateVariableError(
            f"Faltam variáveis para o template {template_name!r} ({language}): "
            f"{', '.join(faltando)}."
        )

    parametros = [{"type": "text", "text": str(variables[nome])} for nome in ordem]
    return [{"type": "body", "parameters": parametros}]
