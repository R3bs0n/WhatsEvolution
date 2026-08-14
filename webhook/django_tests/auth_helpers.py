"""Helpers de login para testes, dado o ForceOTPSetupMiddleware.

Dois helpers EXPLÍCITOS de propósito (em vez de mudar client.login()/
create_user() por baixo dos panos) — a intenção de cada teste fica visível:

  login_with_2fa(...)     — usuário logado E com sessão OTP-verificada
                             (equivalente a completar o assistente do
                             two_factor de verdade). Use isso na imensa
                             maioria dos testes que só querem chegar numa
                             view protegida.

  login_without_2fa(...)  — só login por senha, sem TOTP. Use isso
                             especificamente em testes que verificam o
                             comportamento do ForceOTPSetupMiddleware em si
                             (ex.: confirma que redireciona pro setup).
"""
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice


def login_with_2fa(client, user, password):
    """Loga por senha e marca a sessão como OTP-verificada (cria um
    TOTPDevice confirmado pro usuário se ele ainda não tiver um) —
    equivalente a passar pelo assistente completo do two_factor."""
    ok = client.login(username=user.username, password=password)
    assert ok, f"login falhou para {user.username!r} — usuário/senha incorretos"

    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)

    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return device


def login_without_2fa(client, user, password):
    """Só login por senha — sessão autenticada, mas SEM dispositivo TOTP e
    SEM verificação. Use para testar o próprio middleware de 2FA, não pra
    testes que só precisam estar logados."""
    ok = client.login(username=user.username, password=password)
    assert ok, f"login falhou para {user.username!r} — usuário/senha incorretos"
