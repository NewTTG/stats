"""Configuration Django. Les secrets viennent des variables d'environnement (.env)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _charger_dotenv(chemin: Path):
    """Charge .env s'il existe ; les variables déjà définies (ex. Docker) restent prioritaires."""
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8-sig").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            os.environ.setdefault(cle.strip(), valeur.strip())


_charger_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = env("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.comptes",
    "apps.referentiel",
    "apps.kpi",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Base applicative : PostgreSQL si APP_DB_HOST est défini, sinon SQLite (dev / tests).
if env("APP_DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("APP_DB_HOST"),
            "PORT": env("APP_DB_PORT", "5432"),
            "NAME": env("APP_DB_NAME"),
            "USER": env("APP_DB_USER"),
            "PASSWORD": env("APP_DB_PASSWORD"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Base KPI source : lue en lecture seule via SQLAlchemy (pas un alias Django).
KPI_DB = {
    "host": env("KPI_DB_HOST"),
    "port": env("KPI_DB_PORT", "5432"),
    "name": env("KPI_DB_NAME"),
    "schema": env("KPI_DB_SCHEMA"),
    "user": env("KPI_DB_USER"),
    "password": env("KPI_DB_PASSWORD"),
}

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "kpi:requete"
LOGOUT_REDIRECT_URL = "login"

KPI_CATALOGUE_PATH = BASE_DIR / "config" / "kpi_catalogue.yaml"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Pacific/Noumea"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
