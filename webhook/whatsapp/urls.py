from django.urls import path

from . import views

urlpatterns = [
    path("disparar/", views.send_panel, name="whatsapp-send"),
    path("logs/", views.logs, name="whatsapp-logs"),
]
