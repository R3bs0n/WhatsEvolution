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
