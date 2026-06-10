from django.urls import include, path
from rest_framework.routers import DefaultRouter

from atendimentos.api import AtendimentoViewSet
from whatsapp.api import EnvioWhatsAppLogViewSet

router = DefaultRouter()
router.register(r"atendimentos", AtendimentoViewSet, basename="api-atendimento")
router.register(r"whatsapp-logs", EnvioWhatsAppLogViewSet, basename="api-whatsapp-log")

urlpatterns = [
    path("", include(router.urls)),
]
