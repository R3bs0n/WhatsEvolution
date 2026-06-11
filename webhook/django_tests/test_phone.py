"""Tests for core.services.phone — normalisation and validation."""
import pytest
from core.services.phone import normalize_phone, PhoneValidationError


@pytest.mark.parametrize("raw,expected", [
    # 11-digit mobile (DDD + 9 + 8) → prepend 55
    ("92999999999",     "5592999999999"),
    ("(92) 99999-9999", "5592999999999"),
    # 10-digit landline → prepend 55
    ("9299999999",      "559299999999"),
    ("(92)9999-9999",   "559299999999"),
    # Already has country code (13 digits)
    ("5592999999999",   "5592999999999"),
    # Leading zero stripped before prepend
    ("09299999999",     "559299999999"),
    # Hyphens and spaces stripped
    ("55 92 99999-9999", "5592999999999"),
])
def test_normalize_phone_valid(raw, expected):
    assert normalize_phone(raw, "55") == expected


@pytest.mark.parametrize("raw", [
    "",          # empty
    "9999",      # too short
    "abc",       # non-digits
    "55" + "9" * 12,   # too long after country code prepend
])
def test_normalize_phone_invalid_raises(raw):
    with pytest.raises(PhoneValidationError):
        normalize_phone(raw, "55")


def test_normalize_phone_empty_raises():
    with pytest.raises(PhoneValidationError, match="vazio"):
        normalize_phone("", "55")


def test_no_double_prepend():
    """Phones already starting with 55 must not get 55 prepended again."""
    result = normalize_phone("5511987654321", "55")
    assert result == "5511987654321"
    assert not result.startswith("5555")
