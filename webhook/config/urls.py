from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.forms import BootstrapAuthenticationForm
from core.views import dashboard
from evolution.views import (
    instance_connect,
    instance_create,
    instance_delete,
    instance_list,
    qr_display,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=BootstrapAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", dashboard, name="dashboard"),
    path("atendimentos/", include("atendimentos.urls")),
    path("pdf/", include("pdf_import.urls")),
    path("whatsapp/", include("whatsapp.urls")),
    path("api/", include("core.api_urls")),
    path("webhook/", include("evolution.urls")),
    path("qr/<str:instance>/", qr_display, name="evolution-qr"),
    path("instancias/", instance_list, name="instance-list"),
    path("instancias/nova/", instance_create, name="instance-create"),
    path("instancias/<str:instance>/conectar/", instance_connect, name="instance-connect"),
    path("instancias/<str:instance>/excluir/", instance_delete, name="instance-delete"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
