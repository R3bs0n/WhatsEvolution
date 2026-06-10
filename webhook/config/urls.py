from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.forms import BootstrapAuthenticationForm
from core.views import dashboard
from evolution.views import qr_display

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
    path("accounts/", include("accounts.urls")),
    path("", dashboard, name="dashboard"),
    path("atendimentos/", include("atendimentos.urls")),
    path("pdf/", include("pdf_import.urls")),
    path("whatsapp/", include("whatsapp.urls")),
    path("api/", include("core.api_urls")),
    path("webhook/", include("evolution.urls")),
    path("qr/<str:instance>/", qr_display, name="evolution-qr"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
