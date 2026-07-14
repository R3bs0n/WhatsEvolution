from django.apps import AppConfig


class EmpresasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'empresas'

    def ready(self):
        from django.db.models.signals import post_save
        from .models import Empresa
        from .signals import criar_configuracao_disparo
        post_save.connect(criar_configuracao_disparo, sender=Empresa)
