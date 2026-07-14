from django.conf import settings

from .providers import WhatsAppProvider


def get_provider(canal=None) -> WhatsAppProvider:
    provider_name = getattr(settings, "WHATSAPP_PROVIDER", "evolution").lower()

    if provider_name == "evolution":
        from .evolution_provider import EvolutionWhatsAppProvider
        instance_name = canal.instance_name if canal else None
        api_url = canal.api_url if canal else None
        return EvolutionWhatsAppProvider(instance_name=instance_name, api_url=api_url)

    if provider_name == "fake":
        from .fake_provider import FakeWhatsAppProvider
        return FakeWhatsAppProvider()

    raise ValueError(f"WHATSAPP_PROVIDER desconhecido: '{provider_name}'")
