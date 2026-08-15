import logging

from django.conf import settings
from django.utils import timezone

from core.services.phone import PhoneValidationError, mask_phone, normalize_phone
from whatsapp.models import EnvioWhatsAppLog
from whatsapp.services.message_builder import build_message
from whatsapp.services.provider_factory import get_provider
from whatsapp.services.template_registry import TemplateVariableError, build_template_components

logger = logging.getLogger(__name__)


class WhatsAppSendService:
    def __init__(self, provider=None):
        self.provider = provider

    def send_for_atendimento(self, atendimento) -> bool:
        empresa = atendimento.empresa

        try:
            phone = normalize_phone(atendimento.telefone, settings.DEFAULT_COUNTRY_CODE)
        except PhoneValidationError as exc:
            EnvioWhatsAppLog.objects.create(
                empresa=empresa,
                atendimento=atendimento,
                telefone=atendimento.telefone or "",
                mensagem="",
                status_retorno="TELEFONE_INVALIDO",
                detalhe_retorno=str(exc),
                sucesso=False,
            )
            logger.warning("Telefone inválido (atendimento %s): %s", atendimento.pk, exc)
            return False

        from whatsapp.models import CanalWhatsApp, ContatoBloqueado

        # Opt-out isolado por empresa
        if ContatoBloqueado.objects.for_empresa(empresa).filter(telefone=phone).exists():
            EnvioWhatsAppLog.objects.create(
                empresa=empresa,
                atendimento=atendimento,
                telefone=phone,
                mensagem="",
                status_retorno="BLOQUEADO",
                detalhe_retorno="Número na lista de opt-out.",
                sucesso=False,
            )
            logger.info(
                "Envio ignorado — número bloqueado (atendimento %s): %s",
                atendimento.pk,
                mask_phone(phone),
            )
            return False

        # Resolve canal principal da empresa (fallback: settings globais)
        canal = None
        if empresa:
            canal = CanalWhatsApp.objects.filter(
                empresa=empresa, principal=True, ativo=True
            ).first()

        provider = self.provider or get_provider(canal=canal)
        mensagem = build_message(
            atendimento.paciente,
            atendimento.exame_procedimento,
            empresa=empresa,
        )
        resultado = provider.send_message(phone, mensagem)

        EnvioWhatsAppLog.objects.create(
            empresa=empresa,
            atendimento=atendimento,
            telefone=phone,
            mensagem=mensagem,
            status_retorno=resultado.status,
            codigo_retorno=resultado.code or "",
            detalhe_retorno=resultado.detail or "",
            sucesso=resultado.success,
        )

        if resultado.success:
            atendimento.status_enviado = "S"
            atendimento.data_envio = timezone.now()
            atendimento.save(update_fields=["status_enviado", "data_envio"])

        return resultado.success

    def send_template_for_atendimento(
        self, atendimento, template_name: str, language: str = "pt_BR",
    ) -> bool:
        """Envia por TEMPLATE (Cloud API oficial), não texto livre — exige
        canal WHATSAPP-BUSINESS com MetaCloudCredential configurada.

        Não decifra nem transmite o token da Meta: nesta etapa, o token que a
        Evolution usa de fato é o configurado na criação da instância dela, não
        algo reenviado a cada chamada — aqui só CONFIRMAMOS que existe uma
        credencial válida/configurada para o canal, como camada de validação.
        """
        empresa = atendimento.empresa

        def _log_falha(status_retorno: str, detalhe: str = "", telefone: str = "") -> bool:
            EnvioWhatsAppLog.objects.create(
                empresa=empresa,
                atendimento=atendimento,
                telefone=telefone or (atendimento.telefone or ""),
                mensagem="",
                tipo_envio="template",
                template_nome=template_name,
                status_retorno=status_retorno,
                detalhe_retorno=detalhe,
                sucesso=False,
            )
            return False

        try:
            phone = normalize_phone(atendimento.telefone, settings.DEFAULT_COUNTRY_CODE)
        except PhoneValidationError as exc:
            logger.warning("Telefone inválido (atendimento %s): %s", atendimento.pk, exc)
            return _log_falha("TELEFONE_INVALIDO", str(exc))

        from whatsapp.models import CanalWhatsApp, ContatoBloqueado, MetaCloudCredential

        if ContatoBloqueado.objects.for_empresa(empresa).filter(telefone=phone).exists():
            logger.info(
                "Envio de template ignorado — número bloqueado (atendimento %s): %s",
                atendimento.pk, mask_phone(phone),
            )
            return _log_falha("BLOQUEADO", "Número na lista de opt-out.", phone)

        canal = None
        if empresa:
            canal = CanalWhatsApp.objects.filter(
                empresa=empresa, principal=True, ativo=True,
                provider=CanalWhatsApp.PROVIDER_BUSINESS,
            ).first()

        if canal is None:
            logger.error(
                "Envio de template sem canal WHATSAPP-BUSINESS (atendimento %s, empresa %s)",
                atendimento.pk, empresa,
            )
            return _log_falha(
                "CANAL_NAO_BUSINESS",
                "Nenhum canal WHATSAPP-BUSINESS ativo/principal para esta empresa "
                "(envio por template exige Cloud API oficial, não Baileys).",
                phone,
            )

        # .defer("meta_access_token") — NÃO usar `canal.credencial_meta`
        # (relação reversa): ela faz um SELECT * implícito, e o campo cifrado
        # decifra no from_db_value() assim que a LINHA é carregada, não só
        # quando o atributo é lido (achado real, pego pelo teste
        # test_token_is_never_decrypted_even_if_corrupted). defer() exclui a
        # coluna do SELECT, então o token nunca é decifrado aqui de verdade.
        credencial = (
            MetaCloudCredential.objects.defer("meta_access_token")
            .filter(canal=canal)
            .first()
        )

        if credencial is None or credencial.status != MetaCloudCredential.STATUS_CONFIGURADO:
            logger.error(
                "Envio de template sem credencial Meta configurada (canal %s, atendimento %s)",
                canal.pk, atendimento.pk,
            )
            return _log_falha(
                "CREDENCIAL_NAO_CONFIGURADA",
                f"MetaCloudCredential do canal '{canal.nome}' ausente ou "
                f"status != {MetaCloudCredential.STATUS_CONFIGURADO!r}.",
                phone,
            )

        try:
            components = build_template_components(
                template_name, language,
                {
                    "nome_paciente": atendimento.paciente,
                    "tipo_exame": atendimento.exame_procedimento,
                },
            )
        except TemplateVariableError as exc:
            logger.error(
                "Falha ao montar template '%s' (atendimento %s): %s",
                template_name, atendimento.pk, exc,
            )
            return _log_falha("VARIAVEL_FALTANDO", str(exc), phone)

        provider = self.provider or get_provider(canal=canal)
        resultado = provider.send_template(phone, template_name, language, components)

        EnvioWhatsAppLog.objects.create(
            empresa=empresa,
            atendimento=atendimento,
            telefone=phone,
            mensagem=f"[template:{template_name}/{language}]",
            tipo_envio="template",
            template_nome=template_name,
            external_message_id=resultado.external_message_id or "",
            status_retorno=resultado.status,
            codigo_retorno=resultado.code or "",
            detalhe_retorno=resultado.detail or "",
            sucesso=resultado.success,
        )

        if resultado.success:
            atendimento.status_enviado = "S"
            atendimento.data_envio = timezone.now()
            atendimento.save(update_fields=["status_enviado", "data_envio"])

        return resultado.success
