from __future__ import annotations

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))

# Look for .env in webhook/ first, then project root (for Docker Compose setups)
for _candidate in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
    if _candidate.exists():
        environ.Env.read_env(_candidate)
        break

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env.str("SECRET_KEY", default="insecure-dev-key-change-in-production-000")

# Chave de criptografia simétrica (Fernet) para campos cifrados em repouso
# (ex.: token da Meta em CanalWhatsApp/MetaCloudCredential). SEM default —
# ausência/valor inválido derruba a subida do Django (ver core.apps.ready()).
# Gerar com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY = env.str("FIELD_ENCRYPTION_KEY", default="")
ALLOWED_HOSTS = [
    h.strip()
    for h in env.str("ALLOWED_HOSTS", default="localhost,127.0.0.1,0.0.0.0").split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in env.str("CSRF_TRUSTED_ORIGINS", default="http://localhost:8000").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "two_factor",
    "rest_framework",
    "core",
    "empresas",
    "billing",
    "atendimentos",
    "pdf_import",
    "whatsapp",
    "evolution",
    "campanhas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.ForceOTPSetupMiddleware",
    "core.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("POSTGRES_DB", default="evolution_db"),
        "USER": env.str("POSTGRES_USER", default="evolution"),
        "PASSWORD": env.str("POSTGRES_PASSWORD", default="evolution_password"),
        "HOST": env.str("POSTGRES_HOST", default="postgres"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Porto_Velho"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django rejeita POSTs com mais campos do que este limite (padrão: 1000). A ação
# "excluir selecionados" do admin envia um campo por linha marcada — ao tentar
# excluir mais de 15 mil atendimentos de uma vez, o sistema retornou erro
# "Too many fields sent" e abortou a operação sem apagar nada.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000

LOGIN_URL = "two_factor:login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "two_factor:login"

REDIS_URL = env.str("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 60 * 60,
    }
}

CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default="redis://redis:6379/1")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TIME_LIMIT = 60 * 5
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 4

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

EVOLUTION_API_URL = env.str("EVOLUTION_API_URL", default="http://evolution-api:8080")
EVOLUTION_API_KEY = env.str("EVOLUTION_API_KEY", default="")
EVOLUTION_INSTANCE_NAME = env.str("EVOLUTION_INSTANCE_NAME", default="clinica")
EVOLUTION_WEBHOOK_SECRET = env.str("EVOLUTION_WEBHOOK_SECRET", default="")
# App Secret da Meta, usado só pra validar X-Hub-Signature-256 no gateway
# público de webhook (evolution/meta_gateway.py). Default vazio de propósito:
# ausência faz o gateway rejeitar toda requisição (fail-closed), sem nenhum
# bypass de DEBUG=True, ao contrário do EVOLUTION_WEBHOOK_SECRET acima.
META_APP_SECRET = env.str("META_APP_SECRET", default="")


DEFAULT_COUNTRY_CODE = env.str("DEFAULT_COUNTRY_CODE", default="55")
WHATSAPP_PROVIDER = env.str("WHATSAPP_PROVIDER", default="evolution")
WHATSAPP_DEFAULT_COMPANY_NAME = env.str(
    "WHATSAPP_DEFAULT_COMPANY_NAME",
    default="Clinica Medica Saude Popular",
)
WHATSAPP_CONTACT_URL = env.str("WHATSAPP_CONTACT_URL", default="https://wa.me/5548988762025")
# Se vazio, message_builder usa o template padrão embutido
WHATSAPP_MESSAGE_TEMPLATE = env.str("WHATSAPP_MESSAGE_TEMPLATE", default="") or ""
# Link da política de privacidade do controlador; se vazio, a linha é omitida da mensagem
WHATSAPP_PRIVACY_POLICY_URL = env.str("WHATSAPP_PRIVACY_POLICY_URL", default="")
BILLING_GRACE_MODE = env.bool("BILLING_GRACE_MODE", default=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
