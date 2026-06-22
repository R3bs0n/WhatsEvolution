from django.urls import path

from . import views

urlpatterns = [
    path("", views.empresa_list, name="empresa-list"),
    path("nova/", views.empresa_create, name="empresa-create"),
    path("<int:pk>/", views.empresa_detail, name="empresa-detail"),
    path("<int:pk>/editar/", views.empresa_edit, name="empresa-edit"),
    path("selecionar/", views.selecionar_empresa, name="selecionar-empresa"),
    path("sair/", views.sair_empresa, name="sair-empresa"),
]
