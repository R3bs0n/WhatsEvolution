from django.urls import path

from . import views

urlpatterns = [
    path("", views.atendimento_list, name="atendimento-list"),
    path("novo/", views.atendimento_create, name="atendimento-create"),
    path("<int:pk>/", views.atendimento_detail, name="atendimento-detail"),
    path("<int:pk>/editar/", views.atendimento_update, name="atendimento-update"),
    path("<int:pk>/excluir/", views.atendimento_delete, name="atendimento-delete"),
    path("<int:pk>/status/", views.atendimento_update_status, name="atendimento-update-status"),
    path("disparar/", views.atendimento_dispatch, name="atendimento-dispatch"),
    path("exportar/csv/", views.export_csv, name="atendimento-export-csv"),
]
