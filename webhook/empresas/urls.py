from django.urls import path

from . import views

urlpatterns = [
    path("selecionar/", views.selecionar_empresa, name="selecionar-empresa"),
    path("sair/", views.sair_empresa, name="sair-empresa"),
]
