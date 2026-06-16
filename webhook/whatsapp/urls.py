from django.urls import path

from . import views

urlpatterns = [
    path("disparar/", views.send_panel, name="whatsapp-send"),
    path("logs/", views.logs, name="whatsapp-logs"),
    path("bloqueados/", views.optout_list, name="whatsapp-optout"),
    path("bloqueados/<int:pk>/remover/", views.optout_delete, name="whatsapp-optout-delete"),
]
