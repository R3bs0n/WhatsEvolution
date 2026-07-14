from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse


def empresa_required(view_func):
    """
    Exige uma empresa ativa no request para telas operacionais.

    Superusuarios sem empresa selecionada sao enviados ao seletor. Usuarios
    comuns sem vinculo recebem 403 em vez de erro de constraint/tenant ausente.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request, "empresa", None) is not None:
            return view_func(request, *args, **kwargs)

        if request.user.is_authenticated and request.user.is_superuser:
            messages.warning(request, "Selecione uma empresa para continuar.")
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('selecionar-empresa')}?{query}")

        return HttpResponseForbidden("Empresa nao identificada para este usuario.")

    return _wrapped
