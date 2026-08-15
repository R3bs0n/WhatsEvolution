from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.conf import settings

        from .fields import validate_field_encryption_key

        validate_field_encryption_key(getattr(settings, "FIELD_ENCRYPTION_KEY", ""))
