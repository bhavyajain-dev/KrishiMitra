"""
Django settings for the KrishiMitra backend.

A single Django + Django REST Framework service (runs on port 5001) that
backs the React/Vite frontend: authentication, farm / expense / crop-plan
APIs, and the ML / RAG / AI endpoints. (The Django project package is named
`krishimitra_ml` for historical reasons.)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from the backend/ directory (this file's BASE_DIR)
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

allowed_hosts_env = os.getenv("ALLOWED_HOSTS", "")
if allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]
else:
    ALLOWED_HOSTS = ["*"] if DEBUG else [".onrender.com", "localhost", "127.0.0.1"]

if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

csrf_origins_env = os.getenv("CSRF_TRUSTED_ORIGINS", "")
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_env.split(",") if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = ["https://*.onrender.com"] if not DEBUG else []

if render_hostname:
    https_origin = f"https://{render_hostname}"
    if https_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(https_origin)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_apscheduler",
    "krishi_core",
]

AUTH_USER_MODEL = "krishi_core.User"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
if cors_origins_env:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
else:
    CORS_ALLOW_ALL_ORIGINS = True  # dev default so Vite frontend can call API

ROOT_URLCONF = "krishimitra_ml.urls"
WSGI_APPLICATION = "krishimitra_ml.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

# Database Configuration:
# - If DATABASE_URL is provided (e.g. Supabase PostgreSQL on Render), use dj_database_url
# - If absent, fall back cleanly to local SQLite (db.sqlite3) for local development
import dj_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "krishi_core.authentication.PublicFriendlyJWTAuthentication",
    ),
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "krishi_core.parsers.ObjectJSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    # Applied per-view (krishi_core.throttles.AIRateThrottle) to the endpoints
    # that call Gemini, so nobody can drain the API quota.
    "DEFAULT_THROTTLE_RATES": {
        "ai": os.getenv("AI_THROTTLE_RATE", "40/hour"),
    },
    # Visitor identity for rate limits. Left unset (DRF default: the full
    # X-Forwarded-For chain) so a wrong proxy count can never lump all
    # visitors into one bucket. Logged-in users are limited per account
    # anyway. Set NUM_PROXIES only once the exact proxy chain is known.
    "NUM_PROXIES": int(os.environ["NUM_PROXIES"]) if os.getenv("NUM_PROXIES") else None,
}

from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "krishi_core.validators.ComplexityPasswordValidator",
    },
]

USE_TZ = True
# Indian Standard Time for dates, alerts and the 02:00 / 07:00 scheduled jobs.
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kolkata")

# ── ML / RAG config (env-driven) ─────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(BASE_DIR / "knowledge-base" / "chroma_db"))
DISABLE_TENSORFLOW_IMPORT = os.getenv("DISABLE_TENSORFLOW_IMPORT", "0") == "1"
# ── Email Settings for Forgot Password OTP (SMTP Fallback) ─────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ['true', '1', 'yes']
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '5'))

# ── Brevo Transactional Email Settings (HTTPS REST API over Port 443) ───
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", os.getenv("EMAIL_HOST_USER", "noreply@krishimitra.com"))
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "KrishiMitra")
# Never send real emails from the test suite: Django's test runner swaps the
# SMTP backend for an in-memory one, but Brevo is called over HTTPS directly.
import sys as _sys
if len(_sys.argv) > 1 and _sys.argv[1] == "test":
    BREVO_API_KEY = ""

# ── Google OAuth Configuration ────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# ── Scheduler / Background Tasks Guard ─────────────────────────────────
# Render free instances spin down after inactivity; default scheduler to disabled.
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "0") == "1"

# ── General security headers (safe in every environment) ──────────────
# Stop browsers from MIME-sniffing responses, and limit referrer leakage.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ── HTTPS & Reverse Proxy Security (Production) ───────────────────────
if not DEBUG:
    # Render terminates TLS at its edge and forwards the original scheme.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Redirect HTTP → HTTPS. Default ON in production; safe behind Render's
    # proxy thanks to SECURE_PROXY_SSL_HEADER (no redirect loop). Set
    # SECURE_SSL_REDIRECT=0 only to intentionally allow plain HTTP.
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HTTP Strict Transport Security. Powerful but hard to reverse (browsers
    # cache the policy), and on a shared *.onrender.com host includeSubDomains
    # or preload can affect sibling apps. So it is OFF by default and opt-in
    # via env once the backend runs on a stable/custom HTTPS domain.
    # Recommended once stable: SECURE_HSTS_SECONDS=31536000 (1 year).
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
    SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "0") == "1"

# ── Port Configuration ────────────────────────────────────────────────
PORT = int(os.getenv("PORT", 5001))


# AI Mitra chat can carry one attached photo as base64 JSON (the app shrinks
# photos first; this is the ceiling). Leaf-scan uploads use multipart files.
DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
