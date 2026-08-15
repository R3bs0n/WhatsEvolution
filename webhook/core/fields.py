"""Campo Django para gravar valores cifrados em repouso (ex.: tokens de API).

Usa Fernet (cryptography), simétrica e autenticada — detecta adulteração do
ciphertext, não só decifra. A chave vem de FIELD_ENCRYPTION_KEY (env var),
validada na subida do Django em core.apps.CoreConfig.ready().

Formato gravado no banco: "<key_id>:<token_fernet>". O prefixo <key_id>
identifica qual chave cifrou aquele valor — hoje só existe uma chave ativa
("v1"), mas ter o identificador desde já evita que uma futura rotação de
chave precise adivinhar o formato de linhas antigas.
"""
from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.db import models

_ACTIVE_KEY_ID = "v1"


class TokenDecryptionError(Exception):
    """Levantado quando um valor cifrado não pôde ser decifrado.

    Nunca inclui o ciphertext nem a chave na mensagem — só o nome do campo.
    """


def _get_fernet():
    from cryptography.fernet import Fernet
    from django.conf import settings

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        # CoreConfig.ready() já deveria ter barrado a subida do Django antes
        # de chegar aqui — isso é uma segunda linha de defesa (ex.: campo
        # usado fora do ciclo normal de management commands).
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY não configurada — não é possível cifrar/decifrar."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def validate_field_encryption_key(key: str) -> None:
    """Levanta ImproperlyConfigured com mensagem clara se `key` não for uma
    chave Fernet válida. Não loga nem inclui a chave na exceção."""
    from cryptography.fernet import Fernet

    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY ausente. Gere uma com:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"\n'
            "e defina FIELD_ENCRYPTION_KEY no .env antes de subir o Django. "
            "Sem essa chave, campos com dados cifrados (ex.: tokens de API) "
            "não podem ser gravados nem lidos."
        )
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY inválida — não é uma chave Fernet "
            "utilizável (deve ser uma chave de 32 bytes em base64 urlsafe, "
            "gerada via Fernet.generate_key()). Erro original: "
            f"{type(exc).__name__}"
        ) from exc


class EncryptedTextField(models.TextField):
    """TextField que cifra o valor antes de gravar e decifra ao ler.

    Vazio/None é tratado como "sem valor" e gravado como string vazia, sem
    passar pelo Fernet (evita cifrar/decifrar ruído para campos opcionais).
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        token = _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")
        return f"{_ACTIVE_KEY_ID}:{token}"

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            key_id, _, token = value.partition(":")
            if not token or key_id != _ACTIVE_KEY_ID:
                raise ValueError("formato ou key_id desconhecido")
            plaintext = _get_fernet().decrypt(token.encode("ascii"))
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise TokenDecryptionError(
                f"Falha ao decifrar o campo '{self.name}' do modelo "
                f"'{self.model.__name__}' — verifique se FIELD_ENCRYPTION_KEY "
                "é a mesma usada para gravar este valor, ou se o dado foi "
                "corrompido."
            ) from exc

    def to_python(self, value):
        return value
