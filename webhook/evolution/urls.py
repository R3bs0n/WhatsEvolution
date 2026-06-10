from django.urls import path

from .views import webhook_receiver

urlpatterns = [
    path("", webhook_receiver, name="evolution-webhook"),
    path("<str:instance>/", webhook_receiver, name="evolution-webhook-instance"),
]
