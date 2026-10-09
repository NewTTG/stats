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
    "config.apps.AdminStatsConfig",  # django.contrib.admin avec le site du projet (config/admin.py)
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.comptes",
    "apps.referentiel",
    "apps.kpi",
    "apps.evenements",
    "apps.rapports",
    "config.apps.TachesDeFondConfig",  # django_q, nommé « Tâches de fond » dans l'administration
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.comptes.visiteurs.VisiteurAnonymeMiddleware",
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
                "apps.kpi.views.contexte_global",
                "apps.comptes.visiteurs.contexte_visiteur",
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
# Sans KPI_DB_HOST : base de démonstration SQLite (données synthétiques) si elle existe,
# générée par « python manage.py charger_demo_kpi ».
KPI_DEMO_SQLITE = Path(env("KPI_DEMO_SQLITE") or BASE_DIR / "data" / "kpi_demo.sqlite3")

# Recherche en langage libre : interprétation par règles locales (config/recherche.yaml).
# Option « Recherche IA » (Groq, API compatible OpenAI) visible seulement si la clé est définie.
# Le modèle ne reçoit que le texte de la demande et ne produit que le JSON de requête.
RECHERCHE_VOCABULAIRE_PATH = BASE_DIR / "config" / "recherche.yaml"
GROQ_API_KEY = env("GROQ_API_KEY", "")
GROQ_MODEL = env("GROQ_MODEL") or "llama-3.3-70b-versatile"
GROQ_TIMEOUT = float(env("GROQ_TIMEOUT") or 10)
GROQ_URL = env("GROQ_URL") or "https://api.groq.com/openai/v1/chat/completions"

# Accès sans compte (défaut) : chaque navigateur a sa session « visiteur », gardée un an
# dans un cookie (historique de recherches, rapports). ACCES_ANONYME=0 : connexion obligatoire.
ACCES_ANONYME = env("ACCES_ANONYME", "1") == "1"
SESSION_COOKIE_AGE = 365 * 24 * 3600

LOGIN_URL = "kpi:requete" if ACCES_ANONYME else "login"
# Après connexion sans « next » : la recherche ; avec l'accès sans compte, un administrateur
# arrive sur /admin/ (la page de connexion est alors l'entrée de l'administration, cf. ConnexionView).
LOGIN_REDIRECT_URL = "kpi:requete"
LOGOUT_REDIRECT_URL = "kpi:requete" if ACCES_ANONYME else "login"

KPI_CATALOGUE_PATH = BASE_DIR / "config" / "kpi_catalogue.yaml"

# Modèle PowerPoint (charte) : utilisé s'il existe, sinon charte dessinée par le code.
PPTX_MODELE = env("PPTX_MODELE") or BASE_DIR / "config" / "modele_rapport.pptx"
# Dispositions du modèle par rôle (premier nom trouvé ; sinon dispositions standard).
PPTX_DISPOSITIONS = {
    "titre": ["Diapo 1", "Titre", "Diapositive de titre", "Title Slide"],
    "contenu": ["Diapo Simple 3", "Titre seul", "Title Only"],
    "fin": ["Diapo FIN"],
}

# Tâches de fond (django-q2, file d'attente dans la base applicative : pas de Redis).
# Lancer le worker : python manage.py qcluster. Q_SYNC=1 : exécution immédiate, sans worker.
Q_CLUSTER = {
    "name": "stats",
    "orm": "default",
    "workers": int(env("Q_WORKERS", "2")),
    "timeout": 900,
    "retry": 1200,
    "max_attempts": 1,
    "catch_up": False,
    "sync": env("Q_SYNC", "0") == "1",
}

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
STATICFILES_DIRS = [BASE_DIR / "static"]  # dont ECharts, servi localement (pas de CDN)
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
