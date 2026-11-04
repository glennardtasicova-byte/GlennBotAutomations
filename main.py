import os
import sys
import threading

# Ensure UTF-8 console output on Windows PowerShell / CMD so emoji logs never raise UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Pre-bind the listening socket within the first 5ms when launched as `python3 main.py`
# so container process supervisors that probe the port within 1.5s immediately detect the bound port.
_EARLY_SERVER_SOCKET = None
if __name__ == "__main__":
    try:
        import socket as _socket
        _early_port = int(os.getenv("PORT", 3000))
        _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        _s.bind(("0.0.0.0", _early_port))
        _s.listen(2048)
        _s.setblocking(False)
        _EARLY_SERVER_SOCKET = _s
    except Exception:
        _EARLY_SERVER_SOCKET = None

try:
    import uvicorn
except ImportError:
    import shutil
    import subprocess
    import urllib.request
    if not shutil.which("pip3"):
        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", "/tmp/get-pip.py")
        subprocess.run(
            [sys.executable, "/tmp/get-pip.py", "-q", "--root-user-action=ignore"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
        try:
            with open("/usr/bin/pip3", "w", encoding="utf-8") as _pf:
                _pf.write('#!/bin/sh\nPIP_ROOT_USER_ACTION=ignore PIP_QUIET=1 exec python3 -m pip "$@"\n')
            os.chmod("/usr/bin/pip3", 0o755)
        except Exception:
            pass
    _req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if os.path.exists(_req_path):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--root-user-action=ignore", "-r", _req_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
    import uvicorn

import cloudinary
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- APSCHEDULER SQLALCHEMY JOBSTORE COMPATIBILITY ---
# Ensures jobs persisted in PostgreSQL/Supabase under "main:post_to_*" or "main:cleanup_*"
# always resolve cleanly to this module even when launched as "uvicorn main:app".
sys.modules.setdefault("main", sys.modules[__name__])

from core.config import (
    BASE_DIR,
    DEFAULT_LOCAL_PORT,
    LOCAL_DEVICE_URL,
    PUBLIC_APP_URL,
    NGROK_PUBLIC_URL,
    WEBHOOK_VERIFY_TOKEN,
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    HTTP_SESSION,
    BG_SYNC_EXECUTOR,
    get_dynamic_base_url,
    _is_localhost_origin,
)
from core.database import (
    db_engine,
    init_records_db,
    scheduler,
    cleanup_old_records,
)
from services.gdrive_service import (
    is_gdrive_authorized,
    gdrive_get_access_token,
    upload_media_to_gdrive,
    delete_media_from_gdrive,
)
from services.cloudinary_service import (
    CLOUDINARY_COMMENTS_STORE,
    CLOUDINARY_MESSAGES_STORE,
    load_external_keys_from_cloudinary,
    sync_external_keys_to_cloudinary,
    load_comments_store_from_cloudinary,
    save_comments_store_to_cloudinary,
    save_comments_store_async,
    load_messages_store_from_cloudinary,
    save_messages_store_to_cloudinary,
    save_messages_store_async,
    cleanup_cloudinary,
)
from services.zernio_service import (
    post_via_zernio,
    post_to_facebook,
    post_to_instagram,
    post_to_tiktok,
    post_to_youtube,
)
from services.ai_service import (
    AskAIRequest,
    _perform_free_web_search_for_ai,
    _sanitize_outbound_social_or_email_text,
    _execute_glennbot_ask_ai_core,
)
from routers.health import router as health_router
from routers.auth_and_keys import router as auth_and_keys_router
from routers.scheduler_routes import (
    router as scheduler_router,
    _trigger_background_analytics_sync,
    _internal_api_admin_rbac_middleware,
    _startup_recover_recent_activity,
)
from routers.comments_routes import router as comments_router
from routers.messages_routes import router as messages_router
from routers.sms_routes import router as sms_router
from routers.webhooks_routes import router as webhooks_router
from routers.comment_actions_routes import router as comment_actions_router
from routers.analytics_routes import router as analytics_router
from routers.email_accounts_routes import router as email_accounts_router
from routers.email_send_webhooks_routes import router as email_send_webhooks_router
from routers.contacts_routes import router as contacts_router
from routers.internal_api_routes import router as internal_api_router
from routers.settings_rbac_routes import router as settings_rbac_router
from routers.automations_routes import router as automations_router
from routers.files_routes import router as files_router
from routers.spreadsheet_routes import router as spreadsheet_router
from routers.calendar_sync_routes import router as calendar_sync_router
from routers.calendar_booking_routes import router as calendar_booking_router
from routers.ai_routes import router as ai_router

# Re-export APScheduler target callables explicitly on module `main`
__all__ = [
    "app",
    "scheduler",
    "db_engine",
    "post_to_facebook",
    "post_to_instagram",
    "post_to_tiktok",
    "post_to_youtube",
    "cleanup_cloudinary",
    "cleanup_old_records",
    "save_comments_store_async",
    "_trigger_background_analytics_sync",
]

# Configure Cloudinary
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

# Ensure static and templates directories exist before mounting
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
os.makedirs(os.path.join(TEMPLATES_DIR, "partials"), exist_ok=True)

app = FastAPI()

# Mount /static and initialize Jinja2Templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
async def _configure_high_concurrency_threadpool_limiter():
    """
    Expands the default AnyIO/Starlette threadpool capacity from 40 to 128 concurrent worker threads
    so simultaneous n8n workflows, Gemini AI calls, Google Drive/Sheets syncs, and dashboard polling
    never queue-block or freeze the Python server.
    """
    try:
        import anyio
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 128
    except Exception:
        pass


@app.middleware("http")
async def _dynamic_origin_auto_detect_middleware(request: Request, call_next):
    """
    Automatically tracks the live URL being used to access GlennBot (Localhost, Ngrok, Render, or any host)
    so webhooks, Internal API URLs, and n8n workflows always adapt dynamically without hardcoding.
    """
    try:
        get_dynamic_base_url(request=request, prefer_public=True)
    except Exception:
        pass
    return await call_next(request)


@app.middleware("http")
async def _admin_rbac_middleware_entry(request: Request, call_next):
    """
    Strictly restricts all '/api/internal-api/*' GUI & AI Workflow Architect routes
    to the Administrator account (glennardtasico@gmail.com).
    """
    return await _internal_api_admin_rbac_middleware(request, call_next)


# --- HOME PAGE (JINJA2 TEMPLATES) & STATIC ROOT ASSETS ---
_INDEX_HTML_CACHE = {"mtime": 0.0, "content": ""}


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def home(request: Request):
    if request.method == "HEAD":
        return HTMLResponse(content="", status_code=200)

    template_index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(template_index_path):
        try:
            return templates.TemplateResponse(
                request=request,
                name="index.html",
                context={"request": request}
            )
        except TypeError:
            return templates.TemplateResponse("index.html", {"request": request})

    # Fallback to root index.html if templates/index.html is not yet generated
    html_path = os.path.join(BASE_DIR, "index.html")
    try:
        mtime = os.path.getmtime(html_path)
        if not _INDEX_HTML_CACHE["content"] or mtime != _INDEX_HTML_CACHE["mtime"]:
            with open(html_path, "r", encoding="utf-8") as f:
                _INDEX_HTML_CACHE["content"] = f.read()
            _INDEX_HTML_CACHE["mtime"] = mtime
        return HTMLResponse(content=_INDEX_HTML_CACHE["content"])
    except Exception:
        return HTMLResponse(content="<h1>GlennBot Automations</h1>", status_code=200)


@app.get("/Profile Picture.jfif")
def get_logo():
    logo_path = os.path.join(BASE_DIR, "Profile Picture.jfif")
    return FileResponse(logo_path) if os.path.exists(logo_path) else {"error": "No Logo"}


@app.get("/coin.mp3")
@app.get("/api/sound/coin.mp3")
def get_notification_sound():
    for candidate in ("coin.mp3", "Coin.mp3", "COIN.MP3", "assets/coin.mp3", "static/coin.mp3"):
        sound_path = os.path.join(BASE_DIR, candidate)
        if os.path.exists(sound_path):
            return FileResponse(
                sound_path,
                media_type="audio/mpeg",
                headers={"Cache-Control": "public, max-age=3600", "Accept-Ranges": "bytes"}
            )
    return PlainTextResponse("coin.mp3 not found in repository root", status_code=404)


# --- MOUNT ALL MODULAR FASTAPI ROUTERS ---
app.include_router(health_router)
app.include_router(auth_and_keys_router)
app.include_router(scheduler_router)
app.include_router(comments_router)
app.include_router(messages_router)
app.include_router(sms_router)
app.include_router(webhooks_router)
app.include_router(comment_actions_router)
app.include_router(analytics_router)
app.include_router(email_accounts_router)
app.include_router(email_send_webhooks_router)
app.include_router(contacts_router)
app.include_router(internal_api_router)
app.include_router(settings_rbac_router)
app.include_router(automations_router)
app.include_router(files_router)
app.include_router(spreadsheet_router)
app.include_router(calendar_sync_router)
app.include_router(calendar_booking_router)
app.include_router(ai_router)

# Ensure APScheduler and continuous background poller start non-blockingly once server binds
def _start_scheduler_and_recovery_bg():
    try:
        init_records_db()
    except Exception:
        pass
    if not scheduler.running:
        try:
            scheduler.start()
        except Exception:
            pass
    _startup_recover_recent_activity()


threading.Thread(target=_start_scheduler_and_recovery_bg, daemon=True).start()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    detected_pub = get_dynamic_base_url(prefer_public=True)
    print("\n" + "=" * 68)
    print("🚀 GLENNBOT AUTOMATIONS SERVER STARTING...")
    print(f"   • Local Device Access URL : http://localhost:{port}")
    if detected_pub and not _is_localhost_origin(detected_pub):
        print(f"   • Public / Tunnel / Cloud : {detected_pub}")
        print(f"   • Active Webhook Endpoint : {detected_pub}/webhooks")
        print(f"   • Active Internal API v1  : {detected_pub}/api/v1")
    else:
        print(f"   • Active Base API v1      : http://localhost:{port}/api/v1")
    print("=" * 68 + "\n")
    if _EARLY_SERVER_SOCKET is not None:
        _uv_config = uvicorn.Config(app, host="0.0.0.0", port=port)
        _uv_server = uvicorn.Server(_uv_config)
        _uv_server.run(sockets=[_EARLY_SERVER_SOCKET])
    else:
        uvicorn.run(app, host="0.0.0.0", port=port)
