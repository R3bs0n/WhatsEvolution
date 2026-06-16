import re


class PhoneValidationError(ValueError):
    pass


def normalize_phone(raw: str, country_code: str = "55") -> str:
    """Return a fully-qualified phone number for the Evolution API.

    Strips all non-digits, applies *country_code* if not already present,
    and validates the result has 12–13 digits (CC + area + number).
    """
    if not raw:
        raise PhoneValidationError("Telefone vazio.")

    digits = re.sub(r"\D", "", raw)

    if digits.startswith("0"):
        digits = digits[1:]

    if not digits.startswith(country_code):
        digits = country_code + digits

    if len(digits) < 12 or len(digits) > 13:
        raise PhoneValidationError(
            f"Número inválido após normalização: '{digits}' ({len(digits)} dígitos)."
        )

    return digits


def mask_phone(raw: str) -> str:
    """Mask all but the last 4 digits of a phone/JID for safe logging.

    Preserves any non-digit suffix (e.g. "@s.whatsapp.net") so the masked
    value is still useful for correlating log lines without exposing the
    full number.
    """
    if not raw:
        return ""

    match = re.match(r"^(\d+)(.*)$", raw)
    if not match:
        return "***"

    digits, suffix = match.groups()
    if len(digits) <= 4:
        masked = "*" * len(digits)
    else:
        masked = "*" * (len(digits) - 4) + digits[-4:]
    return masked + suffix
