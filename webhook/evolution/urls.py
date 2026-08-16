from django.urls import path

from .meta_gateway import meta_webhook_gateway
from .views import webhook_receiver

urlpatterns = [
    path("", webhook_receiver, name="evolution-webhook"),
    path("token/<str:webhook_token>/", webhook_receiver, name="evolution-webhook-token"),
    # Precisa vir ANTES do catch-all <str:instance>/ abaixo — senão o
    # resolver do Django casaria "meta-gateway" como se fosse um nome de
    # instância e nunca chegaria nesta view.
    path("meta-gateway/", meta_webhook_gateway, name="evolution-meta-gateway"),
    path("<str:instance>/", webhook_receiver, name="evolution-webhook-instance"),
]
