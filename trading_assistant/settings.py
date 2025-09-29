from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dummy-secret-key"
DEBUG = True
ALLOWED_HOSTS = []
# settings.py

# Celery settings
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'django-db'



# Optional timezone config
CELERY_TIMEZONE = 'Asia/Kolkata'

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
    "trades",
    'marketdata',
     "django.contrib.humanize",
     'django_celery_beat',
    'django_celery_results',
      "channels",
    'accounts',
]
NEWS_API_KEY = "7cf51a5d2cc641429d3d9167e6bfc299"
STATIC_URL = '/static/'

# Add this if you haven't already
STATICFILES_DIRS = [
    BASE_DIR / "marketdata" / "static",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "trading_assistant.urls"
# settings.py

GROWW_API_KEY = "eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9.eyJleHAiOjI1NDcyMTQ3NTYsImlhdCI6MTc1ODgxNDc1NiwibmJmIjoxNzU4ODE0NzU2LCJzdWIiOiJ7XCJ0b2tlblJlZklkXCI6XCIzMDUwZTE4Ni0wNDNjLTRlYzQtYTQ5MS01OGU1MGUxMzkxNGRcIixcInZlbmRvckludGVncmF0aW9uS2V5XCI6XCJlMzFmZjIzYjA4NmI0MDZjODg3NGIyZjZkODQ5NTMxM1wiLFwidXNlckFjY291bnRJZFwiOlwiOTdkZjI1ZjYtYjJkOS00ODMzLWI5MmQtYzgxMTg0ZWJjNmNjXCIsXCJkZXZpY2VJZFwiOlwiMjhjZjAyMmQtOTQ2ZC01Y2JmLTkwYWMtY2Q2ZjI0NjUwNzdkXCIsXCJzZXNzaW9uSWRcIjpcImQ1ZDgzMTRmLWUzZDktNDE2Ny1iNTZhLTQ2MmY0ZDk4MWNmZVwiLFwiYWRkaXRpb25hbERhdGFcIjpcIno1NC9NZzltdjE2WXdmb0gvS0EwYkhnM1ZvK1R4a25EYTlnK2tkSkRWSnRSTkczdTlLa2pWZDNoWjU1ZStNZERhWXBOVi9UOUxIRmtQejFFQisybTdRPT1cIixcInJvbGVcIjpcImF1dGgtdG90cFwiLFwic291cmNlSXBBZGRyZXNzXCI6XCIyNDA5OjQwZjA6MTA0OjczMGI6NTFhNjo3M2I1OjZhMTg6MjBjNCwxNjIuMTU4LjE5OC4xOTcsMzUuMjQxLjIzLjEyM1wiLFwidHdvRmFFeHBpcnlUc1wiOjI1NDcyMTQ3NTY0ODd9IiwiaXNzIjoiYXBleC1hdXRoLXByb2QtYXBwIn0.AEDqoL0XDqyVmMJ3tRVuO871OSlQS90cTewnC6DE-P_cnmatddisbrXket1THOOi_UDb-4H934bqyzV6wYcolA"
USER_SECRET = "3SLPTNRIC5NN3EMM3GGPHWRJUQLNA36M"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
ASGI_APPLICATION = "trading_assistant.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("127.0.0.1", 6379)],
        },
    },
}
WSGI_APPLICATION = "trading_assistant.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
# TIME_ZONE = "UTC"
TIME_ZONE = "Asia/Kolkata"

USE_I18N = True
USE_TZ = True
# USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
