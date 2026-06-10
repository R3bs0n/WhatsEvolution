from django.conf import settings

from .providers import WhatsAppProvider


def get_provider() -> WhatsAppProvider:
    provider_name = getattr(settings, "WHATSAPP_PROVIDER", "evolution").lower()

    if provider_name == "evolution":
        from .evolution_provider import EvolutionWhatsAppProvider
        return EvolutionWhatsAppProvider()

    if provider_name == "fake":
        from .fake_provider import FakeWhatsAppProvider
        return FakeWhatsAppProvider()

    raise ValueError(f"WHATSAPP_PROVIDER desconhecido: '{provider_name}'")
