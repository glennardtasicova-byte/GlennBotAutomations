import os
import io
import sys
import re
import uuid
import json
import hashlib
import base64
import mimetypes
import urllib.parse
import urllib.request
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
import pytz
from dotenv import load_dotenv
from fastapi import Request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MANILA_TZ = pytz.timezone("Asia/Manila")
manila_tz = MANILA_TZ


# --- PERSISTENT HTTP SESSION WITH AUTO-RETRY ---
def create_resilient_http_session(pool_size: int = 128) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP_SESSION = create_resilient_http_session(pool_size=128)
# Dedicated isolated HTTP connection pool strictly for outbound n8n webhook executions
# so simultaneous comment/message bursts never contend with Zernio, Composio, or Cloudinary sockets.
N8N_HTTP_SESSION = create_resilient_http_session(pool_size=128)

# Dedicated High-Concurrency Thread Pools so n8n workflows, webhooks, AI calls, and background syncs
# execute simultaneously in parallel without ever blocking the FastAPI asyncio event loop or each other.
N8N_WEBHOOK_EXECUTOR = ThreadPoolExecutor(max_workers=64, thread_name_prefix="glennbot_n8n_wh")
BG_SYNC_EXECUTOR = ThreadPoolExecutor(max_workers=24, thread_name_prefix="glennbot_bg_sync")

# Concurrency locks & fast in-memory DB read caches so simultaneous webhooks + 2s UI polling never hang Python
COMMENTS_STORE_LOCK = threading.RLock()
N8N_DISPATCH_LOCK = threading.RLock()
WEBHOOK_POST_SYNC_DEBOUNCE: Dict[str, float] = {}
FAST_DB_READ_CACHE_LOCK = threading.RLock()
FAST_DB_READ_CACHE: Dict[str, Any] = {
    "seen_comments_ts": 0.0,
    "seen_comments": set(),
    "published_posts_ts": 0.0,
    "published_posts": [],
    "seen_messages_ts": 0.0,
    "seen_messages": {}
}


def _invalidate_fast_db_cache(keys: Optional[List[str]] = None) -> None:
    with FAST_DB_READ_CACHE_LOCK:
        if not keys:
            FAST_DB_READ_CACHE["seen_comments_ts"] = 0.0
            FAST_DB_READ_CACHE["published_posts_ts"] = 0.0
            FAST_DB_READ_CACHE["seen_messages_ts"] = 0.0
        else:
            for k in keys:
                FAST_DB_READ_CACHE[f"{k}_ts"] = 0.0


# --- 1. LOAD SECRETS FROM .env FILE (EXTERNAL API MODE) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in list(os.environ.items()):
    _v_str = str(_v or "").strip().lower()
    if (
        not _v_str
        or _v_str.startswith("your_")
        or "@host" in _v_str
        or "example.com" in _v_str
        or _v_str in ("changeme", "placeholder", "none", "null")
    ):
        os.environ.pop(_k, None)

if os.path.exists("/tmp/.glennbot_runtime_env"):
    load_dotenv("/tmp/.glennbot_runtime_env", override=True)

load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

CLOUDINARY_CLOUD_NAME = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
CLOUDINARY_API_KEY = (os.getenv("CLOUDINARY_API_KEY") or "").strip()
CLOUDINARY_API_SECRET = (os.getenv("CLOUDINARY_API_SECRET") or "").strip()

# --- GOOGLE DRIVE API v3 MEDIA STORAGE CONFIGURATION ---
_raw_gdrive_json = (os.getenv("GOOGLE_DRIVE_CLIENT_SECRET_JSON") or "").strip()
_parsed_gdrive_installed: Dict[str, Any] = {}
if _raw_gdrive_json:
    try:
        _j = json.loads(_raw_gdrive_json)
        _parsed_gdrive_installed = _j.get("installed") or _j.get("web") or _j or {}
    except Exception:
        _parsed_gdrive_installed = {}

GOOGLE_DRIVE_CLIENT_ID = (
    os.getenv("GOOGLE_DRIVE_CLIENT_ID")
    or _parsed_gdrive_installed.get("client_id")
    or ""
).strip()
GOOGLE_DRIVE_CLIENT_SECRET = (
    os.getenv("GOOGLE_DRIVE_CLIENT_SECRET")
    or _parsed_gdrive_installed.get("client_secret")
    or ""
).strip()
GOOGLE_DRIVE_PROJECT_ID = (
    os.getenv("GOOGLE_DRIVE_PROJECT_ID")
    or _parsed_gdrive_installed.get("project_id")
    or ""
).strip()
GOOGLE_DRIVE_FOLDER_NAME = (os.getenv("GOOGLE_DRIVE_FOLDER_NAME") or "GlennBot_Media_Vault").strip()
GOOGLE_DRIVE_FOLDER_ID = (os.getenv("GOOGLE_DRIVE_FOLDER_ID") or "").strip()
GOOGLE_DRIVE_REFRESH_TOKEN = (os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN") or "").strip()
CLOUDINARY_GDRIVE_TOKEN_PUBLIC_ID = "glennbot_config/google_drive_oauth_token.json"
LOCAL_GDRIVE_TOKEN_CACHE_PATH = os.path.join(BASE_DIR, "gdrive_oauth_token_cache.json")

# --- TEXTBEE.DEV SMS GATEWAY CONFIGURATION ---
TEXTBEE_API_KEY = (os.getenv("TEXTBEE_API_KEY") or "").strip()
TEXTBEE_SIM_SUBSCRIPTION_ID = (os.getenv("TEXTBEE_SIM_SUBSCRIPTION_ID") or "2").strip()
TEXTBEE_DEVICE_ID = (os.getenv("TEXTBEE_DEVICE_ID") or "").strip()
TEXTBEE_WEBHOOK_SECRET = (
    os.getenv("TEXTBEE_WEBHOOK_SECRET")
    or os.getenv("TEXTBEE_SIGNING_SECRET")
    or ""
).strip()
TEXTBEE_BASE_URL = (os.getenv("TEXTBEE_BASE_URL") or "https://api.textbee.dev/api/v1").strip().rstrip("/")
TEXTBEE_ACCOUNT_ID = "textbee_sms_sim_2"
CLOUDINARY_TEXTBEE_CONFIG_PUBLIC_ID = "glennbot_config/textbee_sms_config_v1.json"

# --- DATABASE URL CONFIGURATION ---
import sqlite3 as _sqlite3


def _parse_sqlite_timestamptz(raw_bytes: bytes) -> datetime:
    s = raw_bytes.decode("utf-8", errors="replace").strip()
    if not s:
        return datetime.now(MANILA_TZ)
    try:
        cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return pytz.utc.localize(dt)
        return dt
    except Exception:
        return datetime.now(MANILA_TZ)


_sqlite3.register_converter("TIMESTAMPTZ", _parse_sqlite_timestamptz)
_sqlite3.register_converter("TIMESTAMP", _parse_sqlite_timestamptz)
_sqlite3.register_adapter(
    datetime,
    lambda dt: (dt if dt.tzinfo is not None else MANILA_TZ.localize(dt)).isoformat()
)

_raw_database_url = (os.getenv("DATABASE_URL") or "").strip()
if not _raw_database_url:
    _raw_database_url = "sqlite:////tmp/glennbot_fallback.db"
if _raw_database_url.startswith("postgres://"):
    _raw_database_url = "postgresql://" + _raw_database_url[len("postgres://"):]
if _raw_database_url.startswith("postgresql://"):
    try:
        import psycopg  # noqa: F401
        _raw_database_url = "postgresql+psycopg://" + _raw_database_url[len("postgresql://"):]
    except ImportError:
        pass
DATABASE_URL = _raw_database_url
if DATABASE_URL.startswith("sqlite"):
    _DB_CONNECT_ARGS = {
        "check_same_thread": False,
        "detect_types": _sqlite3.PARSE_DECLTYPES | _sqlite3.PARSE_COLNAMES,
    }
elif "+psycopg" in DATABASE_URL:
    _DB_CONNECT_ARGS = {"prepare_threshold": None}
else:
    _DB_CONNECT_ARGS = {}

# --- ZERNIO / EXTERNAL API CONFIGURATION ---
_raw_env_api_key = (
    os.getenv("EXTERNAL_API_KEY")
    or os.getenv("ZERNIO_API_KEY")
    or os.getenv("ZERIO_API_KEY")
    or os.getenv("POSTZEN_API_KEY")
    or ""
).strip()
_raw_zernio_base_url = (os.getenv("ZERNIO_BASE_URL") or "").strip().rstrip("/")

# Auto-heal if an API key (sk_...) was accidentally pasted into ZERNIO_BASE_URL in Render Env Vars
_rescued_key_from_base_url = ""
if _raw_zernio_base_url.startswith("sk_"):
    _rescued_key_from_base_url = _raw_zernio_base_url.split("/")[0].strip()
    print(f"[⚠️ CONFIG AUTO-FIX] Detected API key inside ZERNIO_BASE_URL! Resetting ZERNIO_BASE_URL to https://zernio.com/api/v1")
    _raw_zernio_base_url = "https://zernio.com/api/v1"
elif not _raw_zernio_base_url.startswith(("http://", "https://")):
    _raw_zernio_base_url = "https://zernio.com/api/v1"

# Ignore placeholder values like 'your_primary_zernio_api_key'
if _raw_env_api_key.lower().startswith("your_") or "zernio_api_key" in _raw_env_api_key.lower():
    print(f"[⚠️ CONFIG AUTO-FIX] Ignoring placeholder EXTERNAL_API_KEY value: {_raw_env_api_key}")
    _raw_env_api_key = ""

ENV_EXTERNAL_API_KEY = _raw_env_api_key or _rescued_key_from_base_url
ZERNIO_BASE_URL = _raw_zernio_base_url
ZERNIO_CLOUDINARY_PUBLIC_ID = "glennbot_config/zernio_api_keys.json"
CLOUDINARY_COMMENTS_PUBLIC_ID = "glennbot_config/comments_notifications.json"
CLOUDINARY_MESSAGES_PUBLIC_ID = "glennbot_config/messages_inbox.json"
MAX_ACCOUNTS_PER_EXTERNAL_API = 2

# --- PORT & DYNAMIC BASE URL RESOLUTION ---
DEFAULT_LOCAL_PORT = int(os.getenv("PORT", 3000))
LOCAL_DEVICE_URL = f"http://localhost:{DEFAULT_LOCAL_PORT}"

_RUNTIME_URL_STATE: Dict[str, Any] = {
    "last_public_origin": "",
    "last_browser_origin": "",
    "ngrok_api_url": "",
    "ngrok_checked_at": 0.0
}


def _normalize_origin_url(raw_url: str) -> str:
    val = str(raw_url or "").strip().rstrip("/")
    if not val:
        return ""
    if not val.startswith(("http://", "https://")):
        is_local = val.startswith(("localhost", "127.0.0.1", "0.0.0.0"))
        val = f"{'http' if is_local else 'https'}://{val}"
    return val.rstrip("/")


def _is_localhost_origin(url_or_host: str) -> bool:
    clean = str(url_or_host or "").strip().lower()
    for prefix in ("http://", "https://"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    host_only = clean.split("/")[0].split(":")[0].strip()
    return host_only in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "")


def _detect_cloud_hosting_url_from_env() -> str:
    """
    Auto-detects if the Python backend is running on Render.com, Railway, Fly.io,
    Google Cloud Run, Koyeb, Vercel, or Heroku using native platform environment variables.
    """
    render_url = _normalize_origin_url(os.getenv("RENDER_EXTERNAL_URL", ""))
    if render_url:
        return render_url
    render_host = str(os.getenv("RENDER_EXTERNAL_HOSTNAME", "")).strip()
    if render_host:
        return _normalize_origin_url(f"https://{render_host}")

    railway_domain = str(os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_STATIC_URL") or "").strip()
    if railway_domain:
        return _normalize_origin_url(railway_domain)

    fly_app = str(os.getenv("FLY_APP_NAME", "")).strip()
    if fly_app:
        return f"https://{fly_app}.fly.dev"

    koyeb_domain = str(os.getenv("KOYEB_PUBLIC_DOMAIN", "")).strip()
    if koyeb_domain:
        return _normalize_origin_url(koyeb_domain)

    vercel_url = str(os.getenv("VERCEL_URL", "")).strip()
    if vercel_url:
        return _normalize_origin_url(vercel_url)

    return ""


def _detect_local_ngrok_tunnel_url(force: bool = False) -> str:
    """
    Automatically queries the local Ngrok agent API (http://127.0.0.1:4040/api/tunnels)
    when running on a local machine so even if the Ngrok domain changes, Python detects it live.
    """
    # Skip local 4040 check if running inside a known cloud container
    if os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("K_SERVICE") or os.getenv("RAILWAY_ENVIRONMENT"):
        return ""
    now_ts = time.time()
    if not force and (now_ts - float(_RUNTIME_URL_STATE.get("ngrok_checked_at") or 0.0)) < 30.0:
        return str(_RUNTIME_URL_STATE.get("ngrok_api_url") or "")

    _RUNTIME_URL_STATE["ngrok_checked_at"] = now_ts

    def _probe_local_ngrok() -> str:
        try:
            req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=0.45) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    tunnels = data.get("tunnels") or []
                    for t in tunnels:
                        pub = _normalize_origin_url(t.get("public_url") or "")
                        if pub.startswith("https://"):
                            _RUNTIME_URL_STATE["ngrok_api_url"] = pub
                            return pub
                    for t in tunnels:
                        pub = _normalize_origin_url(t.get("public_url") or "")
                        if pub:
                            _RUNTIME_URL_STATE["ngrok_api_url"] = pub
                            return pub
        except Exception:
            pass
        return str(_RUNTIME_URL_STATE.get("ngrok_api_url") or "")

    if not force:
        threading.Thread(target=_probe_local_ngrok, daemon=True).start()
        return str(_RUNTIME_URL_STATE.get("ngrok_api_url") or "")
    return _probe_local_ngrok()


def _extract_origin_from_request(request: Optional[Request]) -> str:
    if request is None:
        return ""
    try:
        raw_host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or ""
        ).split(",")[0].strip()
        if not raw_host:
            return ""
        raw_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        if not raw_proto:
            if not _is_localhost_origin(raw_host) or any(
                d in raw_host.lower() for d in ("ngrok", "onrender", "run.app", "railway", "fly.dev", "vercel", "koyeb")
            ):
                raw_proto = "https"
            else:
                raw_proto = request.url.scheme or "http"
        return _normalize_origin_url(f"{raw_proto}://{raw_host}")
    except Exception:
        return ""


def get_dynamic_base_url(request: Optional[Request] = None, prefer_public: bool = True) -> str:
    """
    Dynamically resolves the active GlennBot base URL (without trailing slash) across:
    - Live incoming HTTP request headers (Ngrok, Render.com, Railway, Cloud Run, custom domain, or localhost)
    - Cloud platform environment variables (RENDER_EXTERNAL_URL, RAILWAY_PUBLIC_DOMAIN, etc.)
    - Live local Ngrok agent tunnel inspection (http://127.0.0.1:4040/api/tunnels)
    - Explicit .env variables (NGROK_PUBLIC_URL, PUBLIC_APP_URL)
    - Local device fallback (http://localhost:5001)
    """
    global PUBLIC_APP_URL, NGROK_PUBLIC_URL

    req_origin = _extract_origin_from_request(request)
    if req_origin:
        _RUNTIME_URL_STATE["last_browser_origin"] = req_origin
        if not _is_localhost_origin(req_origin):
            _RUNTIME_URL_STATE["last_public_origin"] = req_origin
            PUBLIC_APP_URL = req_origin
            NGROK_PUBLIC_URL = req_origin
            return req_origin
        elif not prefer_public:
            return req_origin

    # 1. If running on a Cloud Host (Render, Railway, Fly.io, etc.), prioritize the native Cloud URL
    #    even if .env still contains a local Ngrok URL from local testing!
    cloud_env_url = _detect_cloud_hosting_url_from_env()
    if cloud_env_url:
        PUBLIC_APP_URL = cloud_env_url
        NGROK_PUBLIC_URL = cloud_env_url
        return cloud_env_url

    # 2. If a public origin was already observed from an incoming request (e.g. Ngrok or custom domain), use it
    last_pub = _normalize_origin_url(_RUNTIME_URL_STATE.get("last_public_origin") or "")
    if last_pub and not _is_localhost_origin(last_pub):
        return last_pub

    # 3. Check live local Ngrok tunnel daemon (http://127.0.0.1:4040/api/tunnels)
    live_ngrok = _detect_local_ngrok_tunnel_url(force=False)
    if live_ngrok and not _is_localhost_origin(live_ngrok):
        PUBLIC_APP_URL = live_ngrok
        NGROK_PUBLIC_URL = live_ngrok
        return live_ngrok

    # 4. Check explicit .env tunnel/public variables (NGROK_PUBLIC_URL / PUBLIC_APP_URL)
    env_ngrok = _normalize_origin_url(os.getenv("NGROK_PUBLIC_URL", ""))
    env_public = _normalize_origin_url(os.getenv("PUBLIC_APP_URL", ""))
    for cand in (env_ngrok, env_public):
        if cand and not _is_localhost_origin(cand):
            return cand

    # 5. If request came from localhost or no public tunnel is active, return browser origin or localhost
    if req_origin:
        return req_origin
    last_browser = _normalize_origin_url(_RUNTIME_URL_STATE.get("last_browser_origin") or "")
    if last_browser:
        return last_browser
    return LOCAL_DEVICE_URL


PUBLIC_APP_URL = (
    _detect_cloud_hosting_url_from_env()
    or _detect_local_ngrok_tunnel_url(force=True)
    or _normalize_origin_url(os.getenv("NGROK_PUBLIC_URL", ""))
    or _normalize_origin_url(os.getenv("PUBLIC_APP_URL", ""))
    or LOCAL_DEVICE_URL
)
NGROK_PUBLIC_URL = PUBLIC_APP_URL
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "glennbot_webhook_secret").strip()

# --- GEMINI AI, COMPOSIO, N8N, AUTH & MODULE CONSTANTS ---
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.5-flash").strip() or "gemini-3.5-flash"

COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3"
DEFAULT_COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "").strip()
DEFAULT_COMPOSIO_WEBHOOK_URL = os.getenv("COMPOSIO_WEBHOOK_URL", "").strip() or f"{get_dynamic_base_url(prefer_public=True)}/webhooks"
DEFAULT_COMPOSIO_WEBHOOK_SECRET = os.getenv("COMPOSIO_WEBHOOK_SECRET", "").strip() or "e6747eca1553134a55d78dbe509f20608700580e670cdc4c99ddf52057af5e59"

EMAIL_CLOUDINARY_PUBLIC_ID = "glennbot_config/email_accounts_store.json"
CONTACTS_CLOUDINARY_PUBLIC_ID = "glennbot_state/crm_contacts_v1.json"
INTERNAL_API_CLOUDINARY_PUBLIC_ID = "glennbot_state/internal_api_v1.json"

GLENNBOT_INTERNAL_API_KEY = os.getenv("GLENNBOT_INTERNAL_API_KEY", "").strip()
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "").strip()
N8N_OUTBOUND_WEBHOOK_URL = os.getenv("N8N_OUTBOUND_WEBHOOK_URL", "").strip()
N8N_OUTBOUND_WEBHOOK_SECRET = os.getenv("N8N_OUTBOUND_WEBHOOK_SECRET", "gb_whsec_n8n_automation_2026").strip()

DASHBOARD_USER_ID = os.getenv("DASHBOARD_USER_ID", "").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
AUTH_SESSION_COOKIE_NAME = "gb_auth_session"
STRICT_ADMIN_GOOGLE_EMAIL = "glennardtasico@gmail.com"

CLOUDINARY_USER_SETTINGS_PUBLIC_ID = "glennbot_config/user_settings_profiles_v1.json"
LOCAL_USER_SETTINGS_CACHE_PATH = os.path.join(BASE_DIR, "user_settings_profiles_cache.json")

CLOUDINARY_AUTOMATIONS_CANVAS_PUBLIC_ID = "glennbot_config/automations_canvas_workflows_v1.json"
LOCAL_AUTOMATIONS_CANVAS_CACHE_PATH = os.path.join(BASE_DIR, "automations_canvas_workflows_cache.json")

CLOUDINARY_FILES_VAULT_PUBLIC_ID = "glennbot_config/files_vault_v1.json"
LOCAL_FILES_VAULT_CACHE_PATH = os.path.join(BASE_DIR, "files_vault_cache.json")

CLOUDINARY_SPREADSHEETS_STORE_PUBLIC_ID = "glennbot_config/spreadsheets_store_v1.json"
LOCAL_SPREADSHEETS_CACHE_PATH = os.path.join(BASE_DIR, "spreadsheets_store_cache.json")
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME_TYPE = "application/vnd.ms-excel"
GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"

CALENDAR_CLOUDINARY_PUBLIC_ID = "glennbot_calendar_hub/calendar_hub_state_v1.json"
