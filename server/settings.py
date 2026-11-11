"""All deployment configuration comes from server/.env or the process environment."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent
ROOT_DIR = SERVER_DIR.parent
load_dotenv(SERVER_DIR / ".env", override=False)

APP_NAME = os.getenv("APP_NAME", "360 Pharmacy System")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# There is no local MySQL fallback, no embedded Supabase project reference, and
# no service-role key sent to the frontend. Copy DATABASE_URL from Connect.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
# Preferred Supabase server-side API key (sb_secret_...). The legacy
# service_role JWT is retained as a fallback for older projects.
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
# Supabase project publishable/anon key for public Auth endpoints (server-side only here).
SUPABASE_PUBLISHABLE_KEY = (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
# Public origin must be set correctly in Auth URL allow-list and email redirects.
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "http://127.0.0.1:8000").strip().rstrip("/")

APP_SECRET = os.getenv("APP_SECRET", "").strip()
ADMIN_SETUP_TOKEN = os.getenv("ADMIN_SETUP_TOKEN", "").strip()
INTEGRATIONS = {
    "authentication": os.getenv("AUTH_SERVICE_URL", "").rstrip("/"),
    "delivery": os.getenv("DELIVERY_SERVICE_URL", "").rstrip("/"),
    "maps": os.getenv("MAPS_SERVICE_URL", "").rstrip("/"),
    "payments": os.getenv("PAYMENT_SERVICE_URL", "").rstrip("/"),
    "notifications": os.getenv("NOTIFICATION_SERVICE_URL", "").rstrip("/"),
}
API_KEYS = {
    "maps": os.getenv("MAPS_API_KEY", ""),
    "payments_public": os.getenv("PAYMENT_PUBLIC_KEY", ""),
    "payments_secret": os.getenv("PAYMENT_SECRET_KEY", ""),
    "delivery": os.getenv("DELIVERY_API_KEY", ""),
    "sms": os.getenv("SMS_API_KEY", ""),
    "notifications": os.getenv("NOTIFICATION_API_KEY", ""),
}
