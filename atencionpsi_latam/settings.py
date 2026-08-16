import os
from pathlib import Path
import dj_database_url

# Directorio base del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent

# SEGURIDAD
# A diferencia del proyecto de Argentina, acá la SECRET_KEY viene siempre de
# una variable de entorno -- nunca hardcodeada en el repo. En local, si no
# está seteada, se usa una clave de desarrollo fija (no sirve para producción).
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-solo-para-local-no-usar-en-produccion')
DEBUG = 'RENDER' not in os.environ

ALLOWED_HOSTS = [
    'atencionpsi.com',
    'www.atencionpsi.com',
    '.onrender.com',
    'localhost',
    '127.0.0.1',
]

# Validación de contraseñas (aplica a /admin/ y a /portal/).
# Mismo criterio que en Argentina: los profesionales que usan esto no son
# todos usuarios técnicos, se mantiene lo mínimo indispensable.
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

# Login del portal de profesionales
LOGIN_URL = 'portal_login'
LOGIN_REDIRECT_URL = 'portal_dashboard'
LOGOUT_REDIRECT_URL = 'portal_login'
SESSION_COOKIE_AGE = 8 * 60 * 60  # 8 horas
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Hardening de cookies/SSL solo en Render (mismo patrón que atencionpsi.com.ar).
if 'RENDER' in os.environ:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Render termina TLS en su proxy y reenvía HTTP plano a gunicorn: sin esto,
    # SECURE_SSL_REDIRECT provoca un loop infinito de redirects en producción.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    # Aprendido de un incidente en atencionpsi.com.ar: sin esto, Django puede
    # rechazar el POST del login con "Verificación CSRF fallida" detrás del
    # proxy de Render si el Origin no matchea exactamente el host esperado.
    CSRF_TRUSTED_ORIGINS = [
        'https://atencionpsi.com',
        'https://www.atencionpsi.com',
    ]

# APLICACIONES
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'storages',  # Requerido para Supabase/S3
    'directorio',
    'portal',
    'turnos',
    'axes',  # Bloqueo por fuerza bruta en el login del portal
    'django.contrib.sitemaps',
]

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'directorio.auth_backends.EmailCaseInsensitiveBackend',
]

AXES_COOLOFF_TIME = 1  # hora de bloqueo automático tras superar el límite de intentos

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'atencionpsi_latam.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'directorio.context_processors.paises_activos',
            ],
        },
    },
]

WSGI_APPLICATION = 'atencionpsi_latam.wsgi.application'

# BASE DE DATOS
if 'RENDER' in os.environ:
    DATABASES = {
        'default': dj_database_url.config(
            default=os.environ.get('DATABASE_URL'),
            conn_max_age=600
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# --- CONFIGURACIÓN DE ARCHIVOS ---

# 1. ESTÁTICOS (CSS/JS) - Manejados por WhiteNoise
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATICFILES_STORAGE = "whitenoise.storage.StaticFilesStorage"
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 2. MEDIA (fotos de profesionales en Supabase, mismo patrón que atencionpsi.com.ar)
if 'RENDER' in os.environ:
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_SUBDOMAIN = os.environ.get('AWS_S3_SUBDOMAIN', '')

    if all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, AWS_S3_SUBDOMAIN]):
        DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
        AWS_S3_ENDPOINT_URL = f'https://{AWS_S3_SUBDOMAIN}.supabase.co/storage/v1/s3'
        AWS_S3_SIGNATURE_VERSION = 's3v4'
        AWS_S3_FILE_OVERWRITE = False
        AWS_DEFAULT_ACL = None
        AWS_QUERYSTRING_AUTH = False
        AWS_S3_VERIFY = True
        AWS_S3_ADDRESSING_STYLE = 'path'
        AWS_S3_REGION_NAME = 'us-east-1'
        AWS_S3_CUSTOM_DOMAIN = f'{AWS_S3_SUBDOMAIN}.supabase.co/storage/v1/object/public/{AWS_STORAGE_BUCKET_NAME}'
    else:
        DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# MAIL -- igual que en atencionpsi.com.ar: en local se imprime en consola.
if 'RENDER' in os.environ:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_HOST = 'smtp-relay.brevo.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('BREVO_SMTP_LOGIN', '')
EMAIL_HOST_PASSWORD = os.environ.get('BREVO_SMTP_KEY', '')
DEFAULT_FROM_EMAIL = 'Atención Psi <hola@atencionpsi.com>'

# dLocal Go -- credenciales de suscripciones (se completan cuando estén listas).
DLOCAL_GO_API_KEY = os.environ.get('DLOCAL_GO_API_KEY', '')
DLOCAL_GO_SECRET_KEY = os.environ.get('DLOCAL_GO_SECRET_KEY', '')

# EXTRAS
WHITENOISE_MANIFEST_STRICT = False
LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
