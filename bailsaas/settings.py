import os
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = 'dev-secret-key,'
DEBUG = True
ALLOWED_HOSTS = [".ngrok-free.app",
                 ".leapcell.dev",
                 "localhost", "127.0.0.1",]

VAPID_PUBLIC_KEY= "BGFve9B7xnz5PY8oOEHhcaB-ddguHguQ8r-sncEMpZ5kaMCfqPMPGLPMzS7B14UC9KS7myTKXxVHkYG3deJjL74"
VAPID_PRIVATE_KEY= "iNTdyZsc20x7jEPAmE0sl5ofCv6Xj_xqV_0t0Zz-R2Y"
VAPID_CLAIM_EMAIL = ("VAPID_CLAIM_EMAIL", "mailto:ezamora121997@gmail.com")

PUBLIC_BASE_URL = "https://05014a56bf45.ngrok-free.app"

CSRF_TRUSTED_ORIGINS = [
    "https://*.ngrok-free.app",
    "https://*.leapcell.dev",
]

# So Django knows the original request was HTTPS behind the proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'django.contrib.humanize',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.TenantAttachMiddleware',
]

ROOT_URLCONF = 'bailsaas.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'bailsaas.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
DATABASES["default"]= dj_database_url.parse("postgresql://bondkeeper_django_user:pJpkXLv5vOY4jutAiY3d7v8NYK0t3JRa@dpg-d32aog7fte5s7389uje0-a.oregon-postgres.render.com/bondkeeper_django")

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / "staticfiles"        # collected files destination

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
