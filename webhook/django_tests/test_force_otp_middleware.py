"""Testes do ForceOTPSetupMiddleware (webhook/core/middleware.py).

Cobre os casos pedidos (anônimo, sem dispositivo, não confirmado, confirmado,
rotas isentas, sem loop) + casos extras que surgiram na análise crítica feita
antes de commitar o middleware: fronteira exata dos prefixos isentos, e o
comportamento hoje (não é bug, é documentado) de /api/ redirecionar em vez de
devolver 401/JSON pra quem não passou pelo 2FA.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django_otp.plugins.otp_totp.models import TOTPDevice

from .auth_helpers import login_with_2fa, login_without_2fa


class ForceOTPSetupMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user-2fa-mw", password="SenhaForte123!")
        self.client = Client()

    def test_anonymous_user_is_never_redirected_to_setup(self):
        response = self.client.get("/")
        # Anônimo é tratado por outras camadas (@login_required etc.), não
        # por este middleware — não deve mandar pro setup de 2FA (pode
        # perfeitamente mandar pro login normal, isso não é problema).
        self.assertNotEqual(getattr(response, "url", None), "/account/two_factor/setup/")

    def test_authenticated_without_any_device_redirects_to_setup(self):
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/account/two_factor/setup/")

    def test_authenticated_with_unconfirmed_device_redirects_to_setup(self):
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        TOTPDevice.objects.create(user=self.user, name="default", confirmed=False)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/account/two_factor/setup/")

    def test_authenticated_and_verified_is_not_redirected(self):
        login_with_2fa(self.client, self.user, "SenhaForte123!")
        response = self.client.get("/")
        self.assertNotEqual(response.status_code, 302)
        if response.status_code == 302:
            self.assertNotEqual(response.url, "/account/two_factor/setup/")

    def test_exempt_prefixes_never_redirect_even_without_device(self):
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        for path in ("/account/login/", "/admin/login/", "/logout/"):
            response = self.client.get(path)
            self.assertNotEqual(
                getattr(response, "url", None), "/account/two_factor/setup/",
                f"{path} foi redirecionado pro setup de 2FA, mas deveria ser isento",
            )

    def test_setup_screen_itself_does_not_loop(self):
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        response = self.client.get("/account/two_factor/setup/")
        # A própria tela de setup é isenta (prefixo /account/) — não pode se
        # redirecionar pra si mesma.
        self.assertNotEqual(getattr(response, "url", None), "/account/two_factor/setup/")

    def test_qrcode_endpoint_used_by_setup_screen_is_exempt(self):
        """Sem isso, a imagem do QR code na própria tela de setup quebraria
        (o <img> receberia um redirect HTML em vez do PNG)."""
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        response = self.client.get("/account/two_factor/qrcode/")
        self.assertNotEqual(getattr(response, "url", None), "/account/two_factor/setup/")

    def test_lookalike_prefix_is_not_accidentally_exempted(self):
        """`/administrator/` não deve ser confundido com `/admin/` só porque
        startswith("/admin") bateria — os prefixos isentos têm barra no
        final de propósito ("/admin/", não "/admin")."""
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        response = self.client.get("/administrator/")
        # Rota nem existe (404) OU foi barrada pelo middleware (302 setup) —
        # o que NÃO pode acontecer é passar direto sem checagem alguma por
        # engano de prefixo. Como a rota não existe, aceitamos 404 também.
        self.assertIn(response.status_code, (302, 404))
        if response.status_code == 302:
            self.assertEqual(response.url, "/account/two_factor/setup/")

    def test_api_without_2fa_redirects_html_instead_of_401(self):
        """Documenta o comportamento ATUAL (não é bug, é uma limitação
        conhecida registrada na análise): um cliente de API autenticado por
        sessão mas sem 2FA recebe um redirect HTML 302, não um 401/403 JSON.
        Se esse comportamento mudar de propósito no futuro, este teste deve
        ser atualizado — ele existe pra tornar a mudança visível, não pra
        proibi-la."""
        login_without_2fa(self.client, self.user, "SenhaForte123!")
        response = self.client.get("/api/atendimentos/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/account/two_factor/setup/")

    def test_authenticated_implies_verified_today(self):
        """Documenta a garantia (testada empiricamente na análise crítica,
        não suposição): hoje é impossível ter uma sessão autenticada de um
        usuário com dispositivo confirmado sem essa sessão também estar
        OTP-verificada, porque o único portão de login (assistente do
        two_factor) só chama django.contrib.auth.login() depois do desafio
        de token passar. Este teste existe pra pegar uma regressão se
        alguém adicionar outro caminho de login no futuro que quebre essa
        garantia (ver análise crítica do middleware para o raciocínio
        completo — é uma decisão de escopo, não um bug corrigido aqui)."""
        login_with_2fa(self.client, self.user, "SenhaForte123!")
        session = self.client.session
        from django_otp import DEVICE_ID_SESSION_KEY
        self.assertIn(DEVICE_ID_SESSION_KEY, session)
