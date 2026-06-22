from django.urls import path

from . import views

urlpatterns = [
    # Contatos
    path("contatos/", views.contato_list, name="campanha-contato-list"),
    path("contatos/importar/", views.contato_import_csv, name="campanha-contato-import"),
    # Segmentos
    path("segmentos/", views.segmento_list, name="campanha-segmento-list"),
    path("segmentos/novo/", views.segmento_create, name="campanha-segmento-create"),
    path("segmentos/<int:pk>/", views.segmento_detail, name="campanha-segmento-detail"),
    # Campanhas
    path("", views.campanha_list, name="campanha-list"),
    path("nova/", views.campanha_create, name="campanha-create"),
    path("<int:pk>/", views.campanha_detail, name="campanha-detail"),
    path("<int:pk>/disparar/", views.campanha_dispatch, name="campanha-dispatch"),
]
