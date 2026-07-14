def criar_configuracao_disparo(sender, instance, created, **kwargs):
    """Garante que toda empresa criada já tenha uma ConfiguracaoDisparo com defaults."""
    if not created:
        return
    from core.tenant_context import session_tenant_context
    from whatsapp.models import ConfiguracaoDisparo

    with session_tenant_context(instance.pk):
        ConfiguracaoDisparo.objects.get_or_create(empresa=instance)
