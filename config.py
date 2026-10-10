"""
config.py
Central configuration loaded from the .env file.

Never hard-code secrets here. Put real values in .env (which is git-ignored).
"""

import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# --- Runtime environment ---
# 'development' (default for local work) or 'production'.
# In production the SECRET_KEY MUST be set in .env — the app refuses to start
# without it, so sessions can never be forged using a known default key.
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# --- Flask session secret ---
_insecure_dev_default = "property-crm-dev-key-change-me"
SECRET_KEY = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY is required in production. Set SECRET_KEY in .env — "
            "do not reuse the development default."
        )
    SECRET_KEY = _insecure_dev_default

# --- Flask debug mode ---
# Debug is opt-in (DEBUG=1) and is FORCED OFF in production, so a stray
# DEBUG=1 in a production .env can never expose the Werkzeug debugger.
_requested_debug = os.getenv("DEBUG", "0").strip().lower() in ("1", "true", "yes")
DEBUG = _requested_debug and not IS_PRODUCTION

# --- Session security ---
# Sessions are permanent cookies that expire; cookies are HttpOnly (Flask
# default) and SameSite=Lax. Secure (HTTPS-only) cookies are forced in
# production so an HTTP deployment still does not leak session cookies.
PERMANENT_SESSION_LIFETIME = datetime.timedelta(
    hours=int(os.getenv("SESSION_HOURS", "12"))
)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = bool(IS_PRODUCTION)

# --- CSRF protection (implemented in security.py, no external dependency) ---
CSRF_ENABLED = True

# --- AI assistant rate limiting (per client IP, sliding window) ---
ASSISTANT_RATE_LIMIT = int(os.getenv("ASSISTANT_RATE_LIMIT", "15"))
ASSISTANT_RATE_WINDOW_SECONDS = int(os.getenv("ASSISTANT_RATE_WINDOW", "60"))

# --- Display currency ---
# Stored prices are never changed; this only controls what symbol/label is shown.
# Defaults to AED for the Dubai dataset. Set CURRENCY=INR or CURRENCY=$ etc. in .env.
def _normalize_currency(raw):
    value = (raw or "AED").strip()
    return value if value else "AED"


CURRENCY = _normalize_currency(os.getenv("CURRENCY"))

# --- Optional external AI (Groq) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
