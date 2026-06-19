from django.urls import path

from .views import edit_pdf_log, upload_pdf

urlpatterns = [
    path("upload/", upload_pdf, name="pdf-upload"),
    path("logs/<int:pk>/editar/", edit_pdf_log, name="pdf-log-edit"),
]
