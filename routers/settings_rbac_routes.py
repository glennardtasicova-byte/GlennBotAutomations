import html as py_html
import imaplib
import smtplib
import email as py_email
import hmac as _tb_hmac
from email.header import decode_header as py_decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import parsedate_to_datetime as py_parsedate_to_datetime
from xml.sax.saxutils import escape as xml_escape
from fastapi.responses import Response as FastAPIResponse
import os
import sys
import re
import time
import json
import uuid
import hmac
import asyncio
import hashlib
import base64
import shutil
import secrets
import zipfile
import tempfile
import threading
import mimetypes
import traceback
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytz
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api
from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text

from core.config import *
from core.config import (
    _invalidate_fast_db_cache,
    _normalize_origin_url,
    _is_localhost_origin,
    _detect_cloud_hosting_url_from_env,
    _detect_local_ngrok_tunnel_url,
    _extract_origin_from_request,
    _RUNTIME_URL_STATE,
)
from core.database import *
from core.database import (
    _normalize_social_page_name,
    _strip_social_page_punctuation,
    _extract_social_page_segments,
    _is_same_social_page_name,
    _does_zernio_account_match_page,
    _resolve_service_callable,
    _get_cached_seen_comment_ids,
    _get_cached_published_posts,
    _get_cached_seen_messages_map,
)
from services.gdrive_service import *
from services.gdrive_service import (
    _load_gdrive_auth_store,
    _save_gdrive_auth_store,
)
from services.cloudinary_service import *
from services.cloudinary_service import (
    _make_key_id,
    _mask_api_key,
    _is_message_deleted_for_conversation,
    _filter_out_deleted_messages,
    _CLOUDINARY_COMMENTS_UPLOAD_LOCK,
    _CLOUDINARY_MESSAGES_UPLOAD_LOCK,
)
from services.zernio_service import *
from services.zernio_service import (
    _format_bytes_label,
    _resolve_runtime_helper,
    _collect_valid_account_ids_for_page,
    _detect_attachment_media_category,
    _normalize_zernio_content_type,
    _is_valid_final_permalink,
    _strip_internal_ids_from_status_message,
    _format_zernio_error_text,
    _differentiate_caption_for_zernio_24h_guard,
    _should_proactively_differentiate_caption,
    _handle_zernio_duplicate_content_response,
    _recover_zernio_post_after_timeout,
    _cancel_zernio_scheduled_post,
    _ZERNIO_PUBLISH_LOCK,
    _ZERNIO_ACTIVE_PUBLISH_RECORDS,
)
from services.ai_service import *
from services.ai_service import (
    _perform_free_web_search_for_ai,
    _sanitize_outbound_social_or_email_text,
    _execute_glennbot_ask_ai_core,
)
from routers.auth_and_keys import *
from routers.ai_routes import api_ask_ai

router = APIRouter()


# ==============================================================================
# --- DASHBOARD LOGIN GATE & ROLE-BASED ACCESS CONTROL (CLIENT vs. ADMIN) ---
# ==============================================================================
# 1. Client Login: Uses DASHBOARD_USER_ID & DASHBOARD_PASSWORD from .env
#    -> Grants access to Dashboard EXCEPT "Internal API (n8n)" (Strictly Restricted).
# 2. Administrator Login: Uses Composio Google OAuth ("glennardtasico@gmail.com")
#    -> Grants full Administrator access INCLUDING "Internal API (n8n)".
# ==============================================================================

AUTH_SESSION_COOKIE_NAME = "gb_auth_session"
STRICT_ADMIN_GOOGLE_EMAIL = "glennardtasico@gmail.com"
PENDING_ADMIN_OAUTH_LOCK = threading.Lock()
PENDING_ADMIN_OAUTH_STATES: Dict[str, Dict[str, Any]] = {}

# ==============================================================================
# --- PER-ACCOUNT CLOUDINARY USER SETTINGS & THEME STORE (CLIENT vs. ADMIN) ---
# Saves and loads user settings (including Theme: 'default' | 'light' | 'dark')
# in Cloudinary keyed by who is logged in:
#   - Client account (.env credentials): "client:<DASHBOARD_USER_ID>"
#   - Administrator account (Google OAuth): "admin:glennardtasico@gmail.com"
# ==============================================================================
CLOUDINARY_USER_SETTINGS_PUBLIC_ID = "glennbot_config/user_settings_profiles_v1.json"
LOCAL_USER_SETTINGS_CACHE_PATH = os.path.join(BASE_DIR, "user_settings_profiles_cache.json")
USER_SETTINGS_LOCK = threading.Lock()
DEFAULT_ACCOUNT_USER_SETTINGS: Dict[str, Any] = {
    "theme": "default",  # "default" | "light" | "dark"
    "instantBackgroundQueue": True,
    "autoClearAfterLaunch": True,
    "fadeEffects": True,
    "popupNotifications": True,
    "soundEffects": True,
    "soundVolume": 85
}
USER_SETTINGS_PROFILES_STORE: Dict[str, Any] = {
    "loaded": False,
    "profiles": {}
}


def _normalize_user_settings_dict(raw: Any) -> Dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    theme_val = str(src.get("theme") or "default").strip().lower()
    if theme_val not in ("default", "light", "dark"):
        theme_val = "default"
    try:
        vol = max(10, min(100, int(src.get("soundVolume", 85))))
    except Exception:
        vol = 85
    return {
        "theme": theme_val,
        "instantBackgroundQueue": bool(src.get("instantBackgroundQueue", True)),
        "autoClearAfterLaunch": bool(src.get("autoClearAfterLaunch", True)),
        "fadeEffects": bool(src.get("fadeEffects", True)),
        "popupNotifications": bool(src.get("popupNotifications", True)),
        "soundEffects": bool(src.get("soundEffects", True)),
        "soundVolume": vol
    }


def _load_user_settings_profiles_store(force_cloud: bool = False) -> Dict[str, Any]:
    with USER_SETTINGS_LOCK:
        if USER_SETTINGS_PROFILES_STORE.get("loaded") and not force_cloud:
            return USER_SETTINGS_PROFILES_STORE

        profiles_map: Dict[str, Any] = {}
        loaded_cloud = False

        if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
            try:
                res = cloudinary.api.resource(
                    CLOUDINARY_USER_SETTINGS_PUBLIC_ID,
                    resource_type="raw"
                )
                sec_url = (res or {}).get("secure_url")
                if sec_url:
                    sep = "&" if "?" in sec_url else "?"
                    r = HTTP_SESSION.get(f"{sec_url}{sep}_ts={int(time.time())}", timeout=12)
                    if r.status_code == 200:
                        data = r.json() or {}
                        if isinstance(data.get("profiles"), dict):
                            profiles_map = data["profiles"]
                            loaded_cloud = True
            except Exception:
                pass

        if not loaded_cloud and os.path.exists(LOCAL_USER_SETTINGS_CACHE_PATH):
            try:
                with open(LOCAL_USER_SETTINGS_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                    if isinstance(data.get("profiles"), dict):
                        profiles_map = data["profiles"]
            except Exception:
                pass

        USER_SETTINGS_PROFILES_STORE["profiles"] = profiles_map
        USER_SETTINGS_PROFILES_STORE["loaded"] = True
        return USER_SETTINGS_PROFILES_STORE


def _save_user_settings_profiles_store() -> bool:
    with USER_SETTINGS_LOCK:
        payload = {
            "version": 1,
            "updated_at": datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p"),
            "profiles": USER_SETTINGS_PROFILES_STORE.get("profiles") or {}
        }
        raw_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        try:
            with open(LOCAL_USER_SETTINGS_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(raw_bytes.decode("utf-8"))
        except Exception:
            pass

    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        try:
            cloudinary.uploader.upload(
                io.BytesIO(raw_bytes),
                resource_type="raw",
                public_id=CLOUDINARY_USER_SETTINGS_PUBLIC_ID,
                overwrite=True,
                invalidate=True
            )
            return True
        except Exception as e:
            print(f"[⚠️ USER SETTINGS CLOUDINARY SAVE WARNING]: {e}")
    return False


def _resolve_settings_profile_identity(sess: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    """
    Resolves (profile_key, role_label, account_display) based on who is logged in:
      - Administrator ('glennardtasico@gmail.com') -> ('admin:glennardtasico@gmail.com', 'admin', 'Administrator (glennardtasico@gmail.com)')
      - Client (.env DASHBOARD_USER_ID) -> ('client:<user_id>', 'client', 'Client (<user_id>)')
    """
    cfg = _get_live_env_auth_config()
    if sess and isinstance(sess, dict):
        is_admin = bool(sess.get("is_admin")) or (
            str(sess.get("role") or "").lower() == "admin"
            and str(sess.get("email") or "").lower().strip() == cfg["admin_email"].lower()
        )
        if is_admin:
            admin_em = cfg["admin_email"].lower()
            return (f"admin:{admin_em}", "admin", f"Administrator ({admin_em})")
        uid = str(sess.get("user_id") or cfg["user_id"] or "glennbot_client").strip()
        return (f"client:{uid.lower()}", "client", f"Client ({uid})")

    default_uid = str(cfg.get("user_id") or "glennbot_client").strip()
    return (f"client:{default_uid.lower()}", "client", f"Client ({default_uid})")


def _get_user_settings_for_session(sess: Optional[Dict[str, Any]], force_cloud: bool = False) -> Dict[str, Any]:
    store = _load_user_settings_profiles_store(force_cloud=force_cloud)
    profile_key, role_str, account_label = _resolve_settings_profile_identity(sess)
    profiles = store.get("profiles") or {}
    saved_entry = profiles.get(profile_key) or {}
    norm_settings = _normalize_user_settings_dict(saved_entry)
    return {
        "profile_key": profile_key,
        "role": role_str,
        "account_label": account_label,
        "updated_at": str(saved_entry.get("updated_at") or ""),
        "settings": norm_settings
    }


def _get_live_env_auth_config() -> Dict[str, str]:
    """
    Reads DASHBOARD_USER_ID and DASHBOARD_PASSWORD dynamically from .env (for Client access),
    while strictly locking Administrator Google OAuth access to STRICT_ADMIN_GOOGLE_EMAIL
    ('glennardtasico@gmail.com') inside Python code so clients with .env access can never alter it.
    """
    file_vals: Dict[str, str] = {}
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k:
                        file_vals[k] = v
    except Exception:
        pass

    user_id = (
        file_vals.get("DASHBOARD_USER_ID")
        or os.getenv("DASHBOARD_USER_ID", "").strip()
        or "glennbot_client"
    )
    password = (
        file_vals.get("DASHBOARD_PASSWORD")
        or os.getenv("DASHBOARD_PASSWORD", "").strip()
        or "GlennBot2026!"
    )
    # Strictly hardcoded in Python code — never read from .env
    admin_email = STRICT_ADMIN_GOOGLE_EMAIL.lower()
    signing_key = (
        file_vals.get("WEBHOOK_VERIFY_TOKEN")
        or os.getenv("WEBHOOK_VERIFY_TOKEN", "").strip()
        or "glennbot_webhook_secret"
    ) + "_dashboard_auth_v1"
    return {
        "user_id": user_id,
        "password": password,
        "admin_email": admin_email,
        "signing_key": signing_key
    }


def _create_dashboard_session_token(role: str, user_id: str, email: str = "", display_name: str = "") -> str:
    cfg = _get_live_env_auth_config()
    clean_role = "admin" if str(role).lower() == "admin" else "client"
    payload = {
        "role": clean_role,
        "is_admin": clean_role == "admin",
        "can_access_internal_api": clean_role == "admin",
        "user_id": str(user_id or ""),
        "email": str(email or "").lower(),
        "display_name": str(display_name or user_id or email or clean_role.capitalize()),
        "iat": int(time.time()),
        "exp": int(time.time()) + (30 * 86400)  # 30 days session validity
    }
    raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    sig = hmac.new(cfg["signing_key"].encode("utf-8"), b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def _verify_dashboard_session_token(token: str) -> Optional[Dict[str, Any]]:
    raw = str(token or "").strip()
    if not raw or "." not in raw:
        return None
    try:
        cfg = _get_live_env_auth_config()
        b64_payload, sig = raw.rsplit(".", 1)
        expected_sig = hmac.new(cfg["signing_key"].encode("utf-8"), b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        pad = "=" * ((4 - len(b64_payload) % 4) % 4)
        data = json.loads(base64.urlsafe_b64decode((b64_payload + pad).encode("ascii")).decode("utf-8"))
        if not isinstance(data, dict):
            return None
        if int(data.get("exp") or 0) < int(time.time()):
            return None
        role = str(data.get("role") or "client").lower()
        email = str(data.get("email") or "").lower().strip()
        is_admin = (role == "admin" and email == cfg["admin_email"].lower())
        data["role"] = "admin" if is_admin else "client"
        data["is_admin"] = bool(is_admin)
        data["can_access_internal_api"] = bool(is_admin)
        return data
    except Exception:
        return None


def _get_authenticated_dashboard_session(request: Request) -> Optional[Dict[str, Any]]:
    # 1. Check X-GlennBot-Session header
    hdr_tok = str(request.headers.get("X-GlennBot-Session") or request.headers.get("x-glennbot-session") or "").strip()
    if hdr_tok:
        sess = _verify_dashboard_session_token(hdr_tok)
        if sess:
            return sess
    # 2. Check Cookie
    cookie_tok = str(request.cookies.get(AUTH_SESSION_COOKIE_NAME) or "").strip()
    if cookie_tok:
        sess = _verify_dashboard_session_token(cookie_tok)
        if sess:
            return sess
    # 3. Check Query Param (for popups/downloads if needed)
    qp_tok = str(request.query_params.get("gb_session") or "").strip()
    if qp_tok:
        sess = _verify_dashboard_session_token(qp_tok)
        if sess:
            return sess
    return None


async def _internal_api_admin_rbac_middleware(request: Request, call_next):
    """
    Strictly restricts all '/api/internal-api/*' GUI & AI Workflow Architect routes
    to the Administrator account (glennardtasico@gmail.com).
    Client accounts logged in via UserID/Password cannot access Internal API (n8n).
    (Note: External '/api/v1/*' routes used by n8n HTTP Request nodes continue to authenticate via X-API-Key.)
    """
    path = str(request.url.path or "")
    if path.startswith("/api/internal-api"):
        sess = _get_authenticated_dashboard_session(request)
        if not sess:
            return JSONResponse(
                status_code=401,
                content={
                    "status": "error",
                    "message": "Authentication required. Please sign in as Administrator (glennardtasico@gmail.com) to access Internal API (n8n)."
                }
            )
        if not sess.get("is_admin"):
            return JSONResponse(
                status_code=403,
                content={
                    "status": "error",
                    "message": "Restricted Access: Internal API (n8n) is strictly reserved for the Administrator (glennardtasico@gmail.com)."
                }
            )
    return await call_next(request)


@router.get("/api/auth/session")
async def api_get_dashboard_auth_session(request: Request):
    cfg = _get_live_env_auth_config()
    sess = _get_authenticated_dashboard_session(request)
    if not sess:
        return {
            "status": "unauthenticated",
            "authenticated": False,
            "admin_google_email_hint": cfg["admin_email"]
        }
    profile_settings_info = await run_in_threadpool(lambda: _get_user_settings_for_session(sess, force_cloud=False))
    return {
        "status": "success",
        "authenticated": True,
        "user": sess,
        "role": sess.get("role", "client"),
        "is_admin": bool(sess.get("is_admin")),
        "can_access_internal_api": bool(sess.get("can_access_internal_api")),
        "user_settings": profile_settings_info.get("settings"),
        "settings_profile": profile_settings_info
    }


@router.get("/api/user/settings")
async def api_get_user_settings(request: Request, refresh: bool = False):
    sess = _get_authenticated_dashboard_session(request)
    info = await run_in_threadpool(lambda: _get_user_settings_for_session(sess, force_cloud=bool(refresh)))
    return {
        "status": "success",
        "authenticated": bool(sess),
        "profile_key": info["profile_key"],
        "role": info["role"],
        "account_label": info["account_label"],
        "updated_at": info["updated_at"],
        "settings": info["settings"]
    }


@router.post("/api/user/settings")
async def api_save_user_settings(request: Request):
    """
    Saves user settings (including Theme: 'default', 'light', 'dark') to Cloudinary
    under the active account's profile ('client:<DASHBOARD_USER_ID>' vs 'admin:glennardtasico@gmail.com').
    """
    sess = _get_authenticated_dashboard_session(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    raw_settings = body.get("settings") if isinstance(body.get("settings"), dict) else body
    norm_settings = _normalize_user_settings_dict(raw_settings)
    profile_key, role_str, account_label = _resolve_settings_profile_identity(sess)
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p")

    def _persist():
        store = _load_user_settings_profiles_store(force_cloud=False)
        with USER_SETTINGS_LOCK:
            profiles = store.setdefault("profiles", {})
            profiles[profile_key] = {
                **norm_settings,
                "profile_key": profile_key,
                "role": role_str,
                "saved_by": account_label,
                "updated_at": now_str
            }
        cloud_ok = _save_user_settings_profiles_store()
        return cloud_ok

    saved_to_cloud = await run_in_threadpool(_persist)
    return {
        "status": "success",
        "saved_to_cloudinary": saved_to_cloud,
        "profile_key": profile_key,
        "role": role_str,
        "account_label": account_label,
        "updated_at": now_str,
        "settings": norm_settings,
        "message": f"Settings & Theme ('{norm_settings['theme']}') saved to Cloudinary for {account_label}!"
    }


@router.post("/api/auth/login")
async def api_dashboard_client_login(request: Request):
    """
    Validates UserID and Password against DASHBOARD_USER_ID and DASHBOARD_PASSWORD in .env.
    Grants Client access (Internal API n8n is restricted).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    input_uid = str(body.get("user_id") or body.get("username") or "").strip()
    input_pwd = str(body.get("password") or "").strip()
    cfg = _get_live_env_auth_config()

    if not input_uid or not input_pwd:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Please enter both User ID and Password."}
        )

    uid_ok = hmac.compare_digest(input_uid.encode("utf-8"), cfg["user_id"].encode("utf-8"))
    pwd_ok = hmac.compare_digest(input_pwd.encode("utf-8"), cfg["password"].encode("utf-8"))

    if not (uid_ok and pwd_ok):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Invalid User ID or Password. Access Denied."}
        )

    token = _create_dashboard_session_token(
        role="client",
        user_id=cfg["user_id"],
        email="",
        display_name=f"Client ({cfg['user_id']})"
    )
    user_obj = _verify_dashboard_session_token(token)
    profile_settings_info = await run_in_threadpool(lambda: _get_user_settings_for_session(user_obj, force_cloud=False))
    resp = JSONResponse(content={
        "status": "success",
        "message": "Signed in successfully as Client!",
        "session_token": token,
        "user": user_obj,
        "user_settings": profile_settings_info.get("settings"),
        "settings_profile": profile_settings_info
    })
    resp.set_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        value=token,
        max_age=30 * 86400,
        httponly=False,
        samesite="lax",
        path="/"
    )
    return resp


def _disconnect_admin_email_from_email_hub(target_email: str = STRICT_ADMIN_GOOGLE_EMAIL) -> int:
    """
    Automatically disconnects and removes `glennardtasico@gmail.com` (and any Composio
    admin OAuth connections) from the Email Modal (`EMAIL_HUB_STATE`, `glennbot_email_accounts` DB,
    Cloudinary store, and Composio `/connected_accounts`) upon Logout so the admin's Gmail
    never duplicates or remains exposed in the Email Modal after logging out.
    """
    _load_email_hub_state()
    clean_target = str(target_email or STRICT_ADMIN_GOOGLE_EMAIL).strip().lower()
    conn_ids_to_delete: set = set()
    removed_count = 0

    with EMAIL_HUB_LOCK:
        kept_accounts = []
        for a in (EMAIL_HUB_STATE.get("accounts") or []):
            em = str(a.get("email_address") or "").strip().lower()
            ent = str(a.get("composio_entity_id") or "").strip().lower()
            cid = str(a.get("composio_connection_id") or "").strip()
            if em == clean_target or ent.startswith("glennbot_admin_oauth_"):
                removed_count += 1
                if cid:
                    conn_ids_to_delete.add(cid)
            else:
                kept_accounts.append(a)
        EMAIL_HUB_STATE["accounts"] = kept_accounts

    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM glennbot_email_accounts WHERE LOWER(email_address) = :em OR composio_entity_id LIKE 'glennbot_admin_oauth_%'"),
                {"em": clean_target}
            )
    except Exception as e:
        print(f"[AuthLogout] DB email cleanup warning: {e}")

    # Also query Composio connected_accounts to remove any ACTIVE connections for glennardtasico@gmail.com or glennbot_admin_oauth_*
    try:
        headers = _get_composio_headers()
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts", headers=headers, timeout=12)
        if r.status_code == 200:
            for item in (r.json().get("items") or []):
                cid = str(item.get("id") or "").strip()
                uid = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "").strip()
                tk = str((item.get("toolkit") or {}).get("slug") or "").lower()
                if not cid or tk != "gmail":
                    continue
                if uid.startswith("glennbot_admin_oauth_"):
                    conn_ids_to_delete.add(cid)
                elif cid not in conn_ids_to_delete:
                    meta_em, _ = _extract_email_from_composio_item(item)
                    if meta_em == clean_target:
                        conn_ids_to_delete.add(cid)
                    elif not meta_em:
                        try:
                            prof = _composio_execute_tool("GMAIL_GET_PROFILE", cid, uid or "glennbot_email_user", {"user_id": "me"})
                            resp_d = ((prof.get("data") or {}).get("response_data") or prof.get("data") or {})
                            if isinstance(resp_d, dict):
                                em_found = str(resp_d.get("emailAddress") or resp_d.get("email") or "").strip().lower()
                                if em_found == clean_target:
                                    conn_ids_to_delete.add(cid)
                        except Exception:
                            pass

        for cid_del in conn_ids_to_delete:
            try:
                HTTP_SESSION.delete(f"{COMPOSIO_BASE_URL}/connected_accounts/{cid_del}", headers=headers, timeout=10)
            except Exception:
                pass
    except Exception as e:
        print(f"[AuthLogout] Composio cleanup warning: {e}")

    threading.Thread(target=_save_email_hub_to_cloudinary, daemon=True).start()
    return removed_count


@router.post("/api/auth/logout")
async def api_dashboard_logout(request: Request):
    sess = _get_authenticated_dashboard_session(request)
    disconnected_admin_email = False
    # If logged in as Admin (glennardtasico@gmail.com) or if glennardtasico@gmail.com is in Email Hub, auto-disconnect it!
    if (sess and sess.get("is_admin")) or any(
        str(a.get("email_address") or "").strip().lower() == STRICT_ADMIN_GOOGLE_EMAIL.lower()
        for a in (EMAIL_HUB_STATE.get("accounts") or [])
    ):
        await run_in_threadpool(lambda: _disconnect_admin_email_from_email_hub(STRICT_ADMIN_GOOGLE_EMAIL))
        disconnected_admin_email = True

    resp = JSONResponse(content={
        "status": "success",
        "disconnected_admin_email": disconnected_admin_email,
        "message": "Logged out successfully and disconnected Administrator Gmail from Email Hub."
    })
    resp.delete_cookie(key=AUTH_SESSION_COOKIE_NAME, path="/")
    return resp


def _create_composio_admin_google_oauth_link(request: Request, state: str = "") -> Dict[str, Any]:
    """
    Creates a Composio Managed Google OAuth2 authorization URL for Administrator sign-in.
    """
    _load_email_hub_state()
    clean_state = re.sub(r"[^a-zA-Z0-9_.-]", "", str(state or f"admin_{int(time.time())}"))
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:5001"
    proto = request.headers.get("x-forwarded-proto") or ("https" if ("ngrok" in host or "onrender" in host or "run.app" in host) else "http")
    base_url = f"{proto}://{host}"
    entity_id = f"glennbot_admin_oauth_{int(time.time())}"
    callback_url = f"{base_url}/api/auth/google/callback?state={urllib.parse.quote(clean_state)}&entity_id={urllib.parse.quote(entity_id)}"
    headers = _get_composio_headers()

    for force_flag in (False, True):
        auth_config_id = _get_or_create_composio_auth_config_id("gmail", force_lookup=force_flag)
        if not auth_config_id:
            continue
        link_payload = {
            "auth_config_id": auth_config_id,
            "user_id": entity_id,
            "callback_url": callback_url
        }
        try:
            r = HTTP_SESSION.post(
                f"{COMPOSIO_BASE_URL}/connected_accounts/link",
                headers=headers,
                json=link_payload,
                timeout=20
            )
            data = r.json() if r.content else {}
            redirect_url = str(data.get("redirect_url") or data.get("redirectUrl") or "").strip()
            conn_id = str(data.get("connected_account_id") or data.get("id") or "").strip()
            if r.status_code in (200, 201) and redirect_url:
                with PENDING_ADMIN_OAUTH_LOCK:
                    PENDING_ADMIN_OAUTH_STATES[clean_state] = {
                        "status": "pending",
                        "entity_id": entity_id,
                        "connected_account_id": conn_id,
                        "created_at": time.time()
                    }
                return {
                    "status": "success",
                    "auth_url": redirect_url,
                    "state": clean_state,
                    "entity_id": entity_id,
                    "connected_account_id": conn_id
                }
        except Exception as e:
            if force_flag:
                return {"status": "error", "message": f"Failed to start Composio Google OAuth: {e}"}

    return {"status": "error", "message": "Could not initialize Composio Google OAuth link."}


@router.get("/api/auth/google/redirect", response_class=HTMLResponse)
async def api_redirect_admin_google_oauth(request: Request, state: str = ""):
    """
    Opens in a popup window when the user clicks 'Sign in with Google (Administrator via Composio)'.
    Immediately redirects to Composio's Google OAuth consent screen.
    """
    res = _create_composio_admin_google_oauth_link(request, state=state)
    if res.get("status") == "success" and res.get("auth_url"):
        auth_url = res["auth_url"]
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>GlennBot Administrator Google Sign-In...</title>
    <style>
        body {{
            background: #050b14;
            color: #e2e8f0;
            font-family: 'Segoe UI', system-ui, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            text-align: center;
        }}
        .card {{
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid rgba(0, 240, 255, 0.45);
            border-radius: 16px;
            padding: 32px 28px;
            max-width: 400px;
            box-shadow: 0 0 35px rgba(0, 240, 255, 0.2);
        }}
        .spinner {{
            width: 38px;
            height: 38px;
            border: 3px solid rgba(0, 240, 255, 0.2);
            border-top-color: #00f0ff;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 16px auto;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .title {{ color: #00f0ff; font-size: 17px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #94a3b8; font-size: 13px; line-height: 1.5; }}
        a {{ color: #00f0ff; font-size: 12px; display: inline-block; margin-top: 14px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <div class="title">Administrator Google OAuth (Composio)</div>
        <p class="sub">Redirecting to Google Sign-In to verify Administrator account...</p>
        <a href="{auth_url}">Click here if not redirected automatically</a>
    </div>
    <script>
        window.location.replace({json.dumps(auth_url)});
    </script>
</body>
</html>"""
        return HTMLResponse(content=html)

    err_msg = res.get("message") or "Could not start Composio Google OAuth."
    return HTMLResponse(
        content=f"<html><body style='background:#050b14;color:#f43f5e;font-family:sans-serif;padding:40px;text-align:center;'><h3>Google OAuth Error</h3><p>{err_msg}</p></body></html>",
        status_code=400
    )


def _resolve_composio_google_email_for_login(conn_id: str = "", entity_id: str = "") -> str:
    """
    Resolves the exact Google email address from Composio after OAuth callback.
    Checks `item["data"]["displayName"]` metadata first before falling back to GMAIL_GET_PROFILE.
    """
    headers = _get_composio_headers()
    candidate_conns: List[Tuple[str, str]] = []
    if conn_id:
        candidate_conns.append((conn_id, entity_id or "glennbot_email_user"))

    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts", headers=headers, timeout=15)
        if r.status_code == 200:
            items = r.json().get("items") or []
            for item in items:
                st = str(item.get("status") or "").upper()
                tk = str((item.get("toolkit") or {}).get("slug") or "").lower()
                cid = str(item.get("id") or "").strip()
                uid = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "").strip()
                if st == "ACTIVE" and tk == "gmail" and cid:
                    if (entity_id and uid == entity_id) or (conn_id and cid == conn_id):
                        meta_em, _ = _extract_email_from_composio_item(item)
                        if meta_em:
                            return meta_em
                        if (cid, uid) not in candidate_conns:
                            candidate_conns.insert(0, (cid, uid or entity_id or "glennbot_email_user"))
            if not candidate_conns:
                for item in items:
                    st = str(item.get("status") or "").upper()
                    tk = str((item.get("toolkit") or {}).get("slug") or "").lower()
                    cid = str(item.get("id") or "").strip()
                    uid = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "glennbot_email_user").strip()
                    if st == "ACTIVE" and tk == "gmail" and cid:
                        meta_em, _ = _extract_email_from_composio_item(item)
                        if meta_em:
                            return meta_em
                        candidate_conns.append((cid, uid))
                        break
    except Exception as e:
        print(f"[AuthGoogle] Composio connected_accounts lookup warning: {e}")

    for cid, uid in candidate_conns[:3]:
        try:
            prof_res = _composio_execute_tool("GMAIL_GET_PROFILE", cid, uid, {"user_id": "me"})
            data_obj = prof_res.get("data") or {}
            if isinstance(data_obj, dict):
                resp_data = data_obj.get("response_data") or data_obj
                if isinstance(resp_data, dict):
                    em = str(resp_data.get("emailAddress") or resp_data.get("email") or "").strip().lower()
                    if em and "@" in em:
                        return em
        except Exception as e:
            print(f"[AuthGoogle] GMAIL_GET_PROFILE warning ({cid}): {e}")

    return ""


@router.get("/api/auth/google/callback", response_class=HTMLResponse)
async def api_admin_google_oauth_callback(request: Request):
    """
    Callback endpoint after Composio Google OAuth completes.
    Verifies if the authenticated Google email is strictly ADMIN_GOOGLE_EMAIL ('glennardtasico@gmail.com').
    """
    qp = request.query_params
    state = re.sub(r"[^a-zA-Z0-9_.-]", "", str(qp.get("state") or ""))
    entity_id = str(qp.get("entity_id") or "").strip()
    conn_id = str(qp.get("connectedAccountId") or qp.get("connected_account_id") or qp.get("connectionId") or "").strip()

    with PENDING_ADMIN_OAUTH_LOCK:
        st_info = PENDING_ADMIN_OAUTH_STATES.get(state) or {}
        if not entity_id:
            entity_id = str(st_info.get("entity_id") or "")
        if not conn_id:
            conn_id = str(st_info.get("connected_account_id") or "")

    cfg = _get_live_env_auth_config()
    admin_target_email = cfg["admin_email"].lower().strip()

    resolved_email = await run_in_threadpool(lambda: _resolve_composio_google_email_for_login(conn_id=conn_id, entity_id=entity_id))
    # Also sync Email Hub accounts in background so if glennardtasico@gmail.com logged in, it's kept in sync
    try:
        threading.Thread(target=_discover_composio_email_accounts, daemon=True).start()
    except Exception:
        pass

    if resolved_email and resolved_email.lower() == admin_target_email:
        token = _create_dashboard_session_token(
            role="admin",
            user_id="administrator",
            email=resolved_email,
            display_name=f"Administrator ({resolved_email})"
        )
        user_obj = _verify_dashboard_session_token(token)
        admin_settings_info = await run_in_threadpool(lambda: _get_user_settings_for_session(user_obj, force_cloud=False))
        result_payload = {
            "type": "GLENNBOT_ADMIN_GOOGLE_AUTH_RESULT",
            "status": "success",
            "session_token": token,
            "user": user_obj,
            "user_settings": admin_settings_info.get("settings"),
            "settings_profile": admin_settings_info,
            "message": f"Welcome Administrator ({resolved_email})! Full Internal API (n8n) access unlocked."
        }
        if state:
            with PENDING_ADMIN_OAUTH_LOCK:
                PENDING_ADMIN_OAUTH_STATES[state] = result_payload

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Administrator Verified — GlennBot Automations</title>
    <style>
        body {{
            background: #050b14;
            color: #e2e8f0;
            font-family: 'Segoe UI', system-ui, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            text-align: center;
        }}
        .card {{
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid rgba(16, 185, 129, 0.65);
            border-radius: 16px;
            padding: 32px 28px;
            max-width: 410px;
            box-shadow: 0 0 35px rgba(16, 185, 129, 0.25);
        }}
        .title {{ color: #34d399; font-size: 18px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #94a3b8; font-size: 13px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="title">✅ Administrator Verified!</div>
        <p class="sub">Authenticated as <strong style="color:#fff;">{resolved_email}</strong> via Composio Google OAuth.<br>Internal API (n8n) is now unlocked. Closing window...</p>
    </div>
    <script>
        try {{
            localStorage.setItem('gb_auth_session_token', {json.dumps(token)});
        }} catch (e) {{}}
        try {{
            if (window.opener) {{
                window.opener.postMessage({json.dumps(result_payload)}, '*');
            }}
        }} catch (e) {{}}
        setTimeout(function() {{ window.close(); }}, 800);
    </script>
</body>
</html>"""
        resp = HTMLResponse(content=html)
        resp.set_cookie(
            key=AUTH_SESSION_COOKIE_NAME,
            value=token,
            max_age=30 * 86400,
            httponly=False,
            samesite="lax",
            path="/"
        )
        return resp

    # Unauthorized Google Account
    denied_reason = (
        f"Access Denied: Google account '{resolved_email}' is not authorized for Administrator access. Only '{admin_target_email}' is permitted."
        if resolved_email
        else f"Access Denied: Could not verify Administrator Google account ('{admin_target_email}') via Composio OAuth."
    )
    err_payload = {
        "type": "GLENNBOT_ADMIN_GOOGLE_AUTH_RESULT",
        "status": "error",
        "message": denied_reason
    }
    if state:
        with PENDING_ADMIN_OAUTH_LOCK:
            PENDING_ADMIN_OAUTH_STATES[state] = err_payload

    html_err = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Access Denied — GlennBot Automations</title>
    <style>
        body {{
            background: #050b14;
            color: #e2e8f0;
            font-family: 'Segoe UI', system-ui, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            text-align: center;
        }}
        .card {{
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid rgba(244, 63, 94, 0.65);
            border-radius: 16px;
            padding: 32px 28px;
            max-width: 420px;
            box-shadow: 0 0 35px rgba(244, 63, 94, 0.25);
        }}
        .title {{ color: #fb7185; font-size: 18px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #cbd5e1; font-size: 13px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="title">⛔ Administrator Access Denied</div>
        <p class="sub">{denied_reason}</p>
    </div>
    <script>
        try {{
            if (window.opener) {{
                window.opener.postMessage({json.dumps(err_payload)}, '*');
            }}
        }} catch (e) {{}}
        setTimeout(function() {{ window.close(); }}, 2200);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_err, status_code=403)


@router.get("/api/auth/google/poll")
async def api_poll_admin_google_oauth_state(state: str = ""):
    """
    Allows the Login screen to poll the completion status of the Composio Google OAuth popup
    even if browser Cross-Origin-Opener-Policy headers clear window.opener during Google redirect.
    """
    clean_state = re.sub(r"[^a-zA-Z0-9_.-]", "", str(state or ""))
    if not clean_state:
        return {"status": "pending"}
    with PENDING_ADMIN_OAUTH_LOCK:
        info = PENDING_ADMIN_OAUTH_STATES.get(clean_state)
        if not info:
            return {"status": "pending"}
        st = str(info.get("status") or "pending")
        if st in ("success", "error"):
            # Return and pop after reading so token isn't left around
            PENDING_ADMIN_OAUTH_STATES.pop(clean_state, None)
            if st == "success" and info.get("session_token"):
                resp = JSONResponse(content=info)
                resp.set_cookie(
                    key=AUTH_SESSION_COOKIE_NAME,
                    value=str(info["session_token"]),
                    max_age=30 * 86400,
                    httponly=False,
                    samesite="lax",
                    path="/"
                )
                return resp
            return info
    return {"status": "pending"}


# --- DASHBOARD GUI MANAGEMENT ROUTES FOR INTERNAL API & N8N ---

@router.get("/api/internal-api/config")
async def api_get_internal_api_config(request: Request):
    state = await run_in_threadpool(lambda: _load_internal_api_state(force_cloud=False))
    base_url = get_dynamic_base_url(request=request, prefer_public=True)
    browser_url = get_dynamic_base_url(request=request, prefer_public=False)
    live_base_api = f"{base_url}/api/v1"
    wfs_out = []
    for w in (state.get("n8n_workflows") or []):
        if isinstance(w, dict):
            w_copy = dict(w)
            if isinstance(w_copy.get("workflow_json"), dict) and w_copy.get("workflow_json"):
                w_copy["workflow_json"] = _auto_inject_credentials_into_workflow_json(w_copy["workflow_json"], live_base_api)
            wfs_out.append(w_copy)
    return {
        "status": "success",
        "base_api_url": live_base_api,
        "browser_api_url": f"{browser_url}/api/v1",
        "local_api_url": f"{LOCAL_DEVICE_URL}/api/v1",
        "public_render_api_url": live_base_api,
        "keys": state.get("keys") or [],
        "n8n_webhook_url": state.get("n8n_webhook_url") or "",
        "n8n_webhook_secret": state.get("n8n_webhook_secret") or "gb_whsec_n8n_automation_2026",
        "n8n_events": state.get("n8n_events") or {},
        "n8n_workflows": wfs_out,
        "recent_logs": state.get("recent_logs") or []
    }


@router.post("/api/internal-api/keys/generate")
async def api_generate_internal_api_key(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    def _gen_key_sync():
        _load_internal_api_state(force_cloud=False)
        key_name = str(body.get("name") or "n8n Automation Key").strip() or "n8n Automation Key"
        random_token = f"gb_live_{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}"
        new_key_obj = {
            "id": f"ikey_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}",
            "name": key_name,
            "api_key": random_token,
            "scopes": "all",
            "status": "ACTIVE",
            "requests_count": 0,
            "last_used_at": "Never",
            "created_at": datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
        }
        return key_name, _upsert_internal_api_key_in_db(new_key_obj, sync_cloud=True)
    key_name, saved = await run_in_threadpool(_gen_key_sync)
    return {
        "status": "success",
        "message": f"Generated new Internal API Key '{key_name}'!",
        "key": saved,
        "keys": INTERNAL_API_STATE.get("keys") or []
    }


@router.delete("/api/internal-api/keys/{key_id}")
async def api_delete_internal_api_key(key_id: str):
    return await run_in_threadpool(lambda: _delete_internal_api_key_sync(key_id))


def _delete_internal_api_key_sync(key_id: str):
    _load_internal_api_state(force_cloud=False)
    clean_id = str(key_id or "").strip()
    with INTERNAL_API_LOCK:
        remaining = [k for k in INTERNAL_API_STATE["keys"] if str(k.get("id")) != clean_id]
        if not remaining:
            return JSONResponse({
                "status": "error",
                "message": "At least one active Internal API Key must remain available. Generate a new key first before deleting this one."
            }, status_code=400)
        INTERNAL_API_STATE["keys"] = remaining

    try:
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM glennbot_internal_api_keys WHERE id = :id"), {"id": clean_id})
    except Exception as e:
        print(f"[InternalAPI] Delete key warning: {e}")

    threading.Thread(target=_save_internal_api_to_cloudinary, daemon=True).start()
    return {
        "status": "success",
        "message": "Internal API Key revoked and removed.",
        "keys": INTERNAL_API_STATE.get("keys") or []
    }


@router.post("/api/internal-api/n8n-workflows/analyze")
async def api_analyze_uploaded_n8n_workflow(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    def _do_analyze():
        _load_internal_api_state(force_cloud=False)
        live_base_api = f"{get_dynamic_base_url(request=request, prefer_public=True)}/api/v1"
        wf_json = body.get("workflow_json") or body
        p_json = _auto_inject_credentials_into_workflow_json(wf_json, live_base_api)
        return p_json, _analyze_n8n_workflow_json(p_json)
    patched_json, analysis = await run_in_threadpool(_do_analyze)
    return {
        "status": "success",
        "analysis": analysis,
        "patched_workflow_json": patched_json
    }


def _build_dynamic_glennbot_n8n_system_specification(live_base_api: str) -> str:
    """
    Dynamically introspects the entire live GlennBot FastAPI application (`app.routes`), Pydantic schemas,
    all 10 UI Views/Tabs, all 14 Modals & their internal DOM IDs/controls, all 5 User Settings,
    connected social/email accounts, Google Drive Files Vault (`file_...`), Spreadsheets (`.xlsx` + column headers),
    Presets, CRM Contacts, Recent Posts, Recent Comments, and Active n8n Workflows at runtime.
    Whenever `main.py` or `index.html` is revised, this function automatically feeds the complete live
    architecture to Gemini 3.5 Flash so it generates 100% accurate n8n Workflow `.json` files!
    """
    import inspect

    clean_base = str(live_base_api or f"{get_dynamic_base_url(prefer_public=True)}/api/v1").rstrip("/")
    active_api_key = _get_active_internal_api_key_token()
    global_wh_secret = str(INTERNAL_API_STATE.get("n8n_webhook_secret") or "gb_whsec_n8n_automation_2026").strip()

    # 1. Live FastAPI Routes Introspection (All /api/v1/* and /api/* routes with signatures & docstrings)
    v1_routes_summary: List[str] = []
    other_api_routes_summary: List[str] = []
    try:
        for route in getattr(getattr(sys.modules.get("main"), "app", router), "routes", router.routes):
            path_val = str(getattr(route, "path", "") or "")
            methods_val = sorted(list((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}))
            if not path_val or not methods_val:
                continue
            endpoint_fn = getattr(route, "endpoint", None)
            doc_str = ""
            sig_str = ""
            if endpoint_fn:
                raw_doc = (getattr(endpoint_fn, "__doc__", "") or "").strip()
                if raw_doc:
                    doc_str = " | ".join(line.strip() for line in raw_doc.splitlines() if line.strip())[:360]
                try:
                    sig_obj = inspect.signature(endpoint_fn)
                    params = [
                        p_name for p_name in sig_obj.parameters.keys()
                        if p_name not in ("request", "self", "self_inner")
                    ]
                    if params:
                        sig_str = f" [params: {', '.join(params)}]"
                except Exception:
                    pass
            m_str = "/".join(methods_val)
            line_desc = f"- {m_str} {path_val}{sig_str}" + (f" -> {doc_str}" if doc_str else "")
            if path_val.startswith("/api/v1/"):
                v1_routes_summary.append(line_desc)
            elif path_val.startswith("/api/"):
                other_api_routes_summary.append(line_desc)
    except Exception:
        pass

    # 2. Live Pydantic Payload Models Introspection
    pydantic_models_summary: List[str] = []
    try:
        for g_name, g_obj in list(globals().items()):
            if isinstance(g_obj, type) and issubclass(g_obj, BaseModel) and g_obj is not BaseModel:
                fields_map = getattr(g_obj, "model_fields", None) or getattr(g_obj, "__fields__", None) or {}
                if fields_map:
                    f_names = list(fields_map.keys())
                    pydantic_models_summary.append(f"- {g_name}: {{{', '.join(f_names)}}}")
    except Exception:
        pass

    # 3. Live Connected Social Accounts (All platforms: Facebook, Instagram, TikTok, YouTube, WhatsApp, Telegram)
    social_summary: List[str] = []
    try:
        for s in (refresh_connected_accounts_cache(force=False) or [])[:30]:
            social_summary.append(
                f"- platform='{s.get('platform')}', account_id='{s.get('account_id')}', account_name='{s.get('account_name') or s.get('username')}', username='{s.get('username') or ''}'"
            )
    except Exception:
        pass

    # 4. Live Connected Email Accounts (Gmail, Microsoft/Outlook, IMAP/SMTP)
    email_summary: List[str] = []
    try:
        _load_email_hub_state(force_cloud=False)
        for e in (EMAIL_HUB_STATE.get("accounts") or [])[:20]:
            email_summary.append(
                f"- account_id='{e.get('id')}', email_address='{e.get('email_address')}', display_name='{e.get('display_name') or ''}', provider='{e.get('provider')}'"
            )
    except Exception:
        pass

    # 5. Live Uploaded Google Drive "Files" Vault Items (`file_...`)
    vault_files_summary: List[str] = []
    try:
        v_store = _load_files_vault_store(force_cloud=False)
        for vf in (v_store.get("files") or [])[:30]:
            vault_files_summary.append(
                f"- file_id='{vf.get('file_id')}', filename='{vf.get('filename')}', content_type='{vf.get('content_type')}', size='{vf.get('size_formatted') or ''}', notes='{vf.get('notes') or ''}'"
            )
    except Exception:
        pass

    # 6. Live Saved & Google Drive Synced Spreadsheets (`.xlsx` / `.xls`) with File ID, Sheet Names, Row 1 Headers & Actual Cell Values (`A1`, `B2`...)
    spreadsheets_summary: List[str] = []
    try:
        _sync_spreadsheets_with_gdrive_and_vault(force_gdrive_check=False)
        sp_store = _load_spreadsheets_store(force_cloud=False)
        for wb in (sp_store.get("workbooks") or [])[:15]:
            sh_details = []
            for sh in (wb.get("sheets") or []):
                hdrs, next_r = _extract_sheet_headers_and_next_row(sh)
                raw_cells = sh.get("cells") or {}
                sample_cells = {k: raw_cells[k] for k in list(raw_cells.keys())[:60]}
                sh_details.append(
                    f"{sh.get('name', 'Sheet1')}(headers={hdrs}, next_row={next_r}, cells={sample_cells})"
                )
            spreadsheets_summary.append(
                f"- workbook_id='{wb.get('workbook_id')}', file_id='{wb.get('file_id') or ''}', gdrive_file_id='{wb.get('gdrive_file_id') or ''}', title='{wb.get('title')}', sheets=[{', '.join(sh_details)}]"
            )
    except Exception:
        pass

    # 7. Live Presets, Recent Posts, Recent Comments, CRM Summary, and Saved n8n Workflows
    presets_summary: List[str] = []
    try:
        p_res = get_presets()
        for pr in (p_res.get("presets") or [])[:10]:
            presets_summary.append(f"- preset_id='{pr.get('id')}', name='{pr.get('name')}', platforms={pr.get('platforms')}")
    except Exception:
        pass

    recent_posts_summary: List[str] = []
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, platform, page_id, account_name, post_type, caption, status
                FROM glennbot_scheduled_posts
                ORDER BY scheduled_time DESC
                LIMIT 10
            """)).mappings().all()
            for r in rows:
                cap_short = str(r.get("caption") or "").replace("\n", " ")[:60]
                recent_posts_summary.append(
                    f"- record_id='{r.get('id')}', platform='{r.get('platform')}', account_name='{r.get('account_name')}', type='{r.get('post_type')}', status='{r.get('status')}', caption='{cap_short}'"
                )
    except Exception:
        pass

    recent_comments_summary: List[str] = []
    try:
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        for r_id, p_entry in list(posts_store.items())[:8]:
            for c_id, c_obj in list((p_entry.get("comments") or {}).items())[:3]:
                if isinstance(c_obj, dict):
                    recent_comments_summary.append(
                        f"- comment_id='{c_id}', record_id='{r_id}', platform='{c_obj.get('platform')}', account_name='{c_obj.get('account_name')}', author='{c_obj.get('author_name')}', message='{str(c_obj.get('message') or '')[:50]}', replies_count={len(c_obj.get('replies') or [])}"
                    )
                if len(recent_comments_summary) >= 10:
                    break
            if len(recent_comments_summary) >= 10:
                break
    except Exception:
        pass

    crm_summary_str = "0 contacts"
    try:
        crm_list = _load_crm_contacts_state(force_cloud=False) or []
        crm_cats = sorted(list({str(c.get("category") or "General") for c in crm_list if isinstance(c, dict)}))
        crm_summary_str = f"{len(crm_list)} contacts (active categories: {crm_cats or ['Hot Lead', 'Client / Customer', 'Inquiry', 'VIP', 'Partner', 'Follow-Up', 'General']})"
    except Exception:
        pass

    saved_workflows_summary: List[str] = []
    try:
        for w in (INTERNAL_API_STATE.get("n8n_workflows") or [])[:10]:
            if isinstance(w, dict):
                saved_workflows_summary.append(
                    f"- workflow_id='{w.get('id')}', name='{w.get('name')}', webhook_path='{w.get('webhook_path')}', enabled={w.get('enabled')}, events={w.get('events')}"
                )
    except Exception:
        pass

    calendar_accounts_summary: List[str] = []
    calendar_events_summary: List[str] = []
    try:
        _load_calendar_hub_state()
        for ca in (CALENDAR_HUB_STATE.get("accounts") or [])[:15]:
            if isinstance(ca, dict):
                calendar_accounts_summary.append(
                    f"- account_id='{ca.get('id')}', provider='{ca.get('provider')}', email_address='{ca.get('email_address')}', display_name='{ca.get('display_name') or ''}'"
                )
        for cev in (CALENDAR_HUB_STATE.get("events") or [])[:15]:
            if isinstance(cev, dict):
                att_str = ", ".join(
                    str(a.get("email") if isinstance(a, dict) else a or "")
                    for a in (cev.get("attendees") or [])
                )
                calendar_events_summary.append(
                    f"- event_id='{cev.get('id')}', external_event_id='{cev.get('external_event_id') or ''}', subject='{cev.get('subject')}', date='{cev.get('date_str') or cev.get('display_date')}', time='{cev.get('time_range_str') or cev.get('time_str')}', provider='{cev.get('provider')}', meeting_platform='{cev.get('meeting_platform')}', organizer='{cev.get('organizer_email')}', attendees=['{att_str}']"
                )
    except Exception:
        pass

    spec_text = f"""=== GLENNBOT AUTOMATIONS: COMPLETE SYSTEM, UI MODAL, ID & API SPECIFICATION ===

1. LIVE GLENNBOT INTERNAL API v1 & SERVER CONFIGURATION:
   - Active Base API URL (Auto-detected Local / Ngrok / Render): {clean_base}
   - Local Device URL: {LOCAL_DEVICE_URL}/api/v1
   - Active Internal API Key (Header `X-API-Key` or `Authorization: Bearer`): {active_api_key}
   - Default Outbound Webhook Signing Secret (`X-GlennBot-Signature` HMAC-SHA256): {global_wh_secret}
   - Timezone: Asia/Manila (UTC+8)

2. COMPLETE CATALOG OF ALL GLENNBOT UI VIEWS, TABS, MODALS, SETTINGS & DOM IDs:
   (When the user mentions any modal, tab, button, setting, or attaches a UI screenshot, map it to these exact features and APIs):
   - **Left Sidebar Navigation (`#left-nav-sidebar`)**:
     * `#tab-btn-scheduler` -> View 1: Create Post / Scheduler (`#view-scheduler`)
     * `#tab-btn-calendar` -> View 2: Calendar View (`#view-calendar`) + Expanded Day Modal (`#day-modal`, `#modal-table-container`)
     * `#tab-btn-queue` -> View 3: Queue View (`#view-queue`, `#queue-filter-status`, `#queue-container`)
     * `#tab-btn-comments` -> View 5: Comments & Notifications Hub (`#view-comments`, `#comment-detail-panel`)
     * `#tab-btn-messages` -> View 4: Unified Inbox & Direct Messages (`#view-messages`, `#message-detail-panel`)
     * `#tab-btn-email` -> View 7: Dedicated Single-Account Email Hub (`#view-email`, `#email-reader-pane`)
     * `#tab-btn-contacts` -> View 8: Client Contacts & Lead CRM Database (`#view-contacts`, `#crm-contacts-table-container`)
     * `#tab-btn-analytics` -> View 6: Social Media Analytics & Per-Page Insights (`#view-analytics`, `#analytics-kpi-grid`, `#analytics-pages-grid`, `#analytics-posts-container`)
     * `#tab-btn-files` -> View 9: "Files" Modal / Google Drive Vault (`#view-files`, `#vault-files-table-container`)
     * `#tab-btn-spreadsheet` -> View 10: "Spread Sheet" Modal / `.xlsx` Editor (`#view-spreadsheet`, `#ss-grid-table`, `#ss-sheet-tabs-container`)
   - **All Modals & Pop-up Windows in GlennBot**:
     * **Settings Modal (`#settings-modal`, opened via `#header-settings-btn`)**:
       - `instantBackgroundQueue` (`#setting-btn-instantBackgroundQueue`): Instant Non-Blocking Launch Automation queue.
       - `autoClearAfterLaunch` (`#setting-btn-autoClearAfterLaunch`): Auto-reset media & caption after scheduling.
       - `fadeEffects` (`#setting-btn-fadeEffects`): Pop-up & notification fade-in/out animations.
       - `popupNotifications` (`#setting-btn-popupNotifications`): Floating pop-up alerts (`#gb-live-notification-stack`) on new comments/messages.
       - `soundEffects` (`#setting-btn-soundEffects`) + Volume (`#setting-sound-volume`): Plays `/coin.mp3` (`#gb-notification-sound`) on new comments & messages.
     * **Manage External API Modal (`#external-api-manager-modal`) & Limit Alert Modal (`#external-api-error-modal`)**:
       - Manages External API (Zernio) Key Pool & Buffer (`#new-external-api-key-input`, `#external-api-keys-list`). Max 2 social accounts per key; automatically maps each Facebook/Instagram/TikTok/YouTube/WhatsApp/Telegram page (including Unicode/Japanese page names like `"Sket Dance /スケット・ダンス (Suketto Dansu)"`) to its exact owning API key via `get_zernio_key_for_account`.
     * **GlennBot Internal REST API (v1) & n8n Automation Hub Modal (`#internal-api-n8n-modal`)**:
       - Sub-tab 1 (`#iapi-tab-keys` / `#iapi-panel-keys`): Generate/revoke `gb_live_...` API keys (`#iapi-new-key-name`, `#btn-generate-internal-key`).
       - Sub-tab 2 (`#iapi-tab-endpoints` / `#iapi-panel-endpoints`): Reference cards for `/api/v1/*` endpoints.
       - Sub-tab 3 (`#iapi-tab-webhook` / `#iapi-panel-webhook`): Outbound n8n Webhook Trigger & Upload n8n Workflow `.json` Manager (`#iapi-upload-wf-file`, `#iapi-new-wf-form-panel`, `#iapi-new-wf-url`, `#iapi-workflows-list-container`).
       - Sub-tab 4 (`#iapi-tab-logs` / `#iapi-panel-logs`): Live API Activity Logs (`#iapi-logs-container`).
     * **Ask AI: n8n Workflow `.json` Architect Modal (`#ask-ai-n8n-modal`)**:
       - Prompt box (`#ask-ai-n8n-prompt`), Attach File icon (`#ask-ai-n8n-attach-btn` / `#ask-ai-n8n-file-input` on the left of `#ask-ai-n8n-generate-btn`), Generated JSON code editor (`#ask-ai-n8n-json-code`), Download `.json` (`#ask-ai-n8n-download-btn`), and Import to Outbound n8n Workflows (`#ask-ai-n8n-import-btn`).
     * **Send a DM to Commenter Modal (`#comment-dm-modal`)**:
       - Sends a Private Reply DM (`POST /api/v1/comments/send-dm`) to a Facebook/Instagram commenter (`#comment-dm-input`, `#comment-dm-attachment-preview`, `#btn-confirm-send-comment-dm`). Supports attaching files from Local Device (`#comment-dm-local-file-input`) OR from the "Files" Modal (`file_id`) as a true binary attachment!
     * **Create Post Media Source Chooser Modal (`#create-post-media-source-modal`)**:
       - Step 1 (`#cp-media-source-step-choice`): Choose "From Local Device" or "From Files Modal (Google Drive -> Zernio)".
       - Step 2 (`#cp-media-source-step-vault`): Pick any file (`file_id`) from the Google Drive Files Vault (`#cp-vault-picker-list`).
     * **Ask AI Content & Caption Generator Modal (`#ask-ai-modal`)**:
       - Generates viral video titles (`#ask-ai-res-title`), primary captions (`#ask-ai-res-caption`), and platform variations (`#ask-ai-res-fb`, `#ask-ai-res-ig`, `#ask-ai-res-tiktok`, `#ask-ai-res-yt`) or replies using Gemini 3.5 Flash + Google Search (`POST /api/v1/ai/ask`).
     * **Custom Selection Presets Modal (`#preset-modal`)**: Loads/saves platform & account presets (`GET /api/v1/presets`).
     * **Connect & Manage Social Accounts Modal (`#connect-accounts-modal`)**: Tabs `#conn-tab-manage`, `#conn-tab-facebook`, `#conn-tab-instagram`, `#conn-tab-tiktok`, `#conn-tab-youtube`, `#conn-tab-whatsapp`, `#conn-tab-telegram`, `#conn-tab-gmail`, `#conn-tab-microsoft`, `#conn-tab-imap`.
     * **Compose Email Modal (`#compose-email-modal`), Expanded Email Reader Modal (`#expanded-email-modal`), Email Webhook Modal (`#email-webhook-modal`)**: Single-account isolated email composer/reader with Local Device & Google Drive Vault `file_id` attachments.
     * **Create/Edit CRM Contact Modal (`#crm-contact-modal`)**: Smart social lead auto-fill + phone/email duplicate detection & auto-combine (`POST /api/v1/contacts`).
     * **Schedule Appointment / Online Meeting Modal (`#schedule-meeting-modal`) & Reschedule Appointment Modal (`#reschedule-meeting-modal`)**:
       - Creates, reschedules, or cancels real Google Calendar/Meet, Microsoft Outlook/Teams, and Zoom appointments (`POST /api/v1/calendar/schedule`, `POST /api/v1/calendar/reschedule`, `POST /api/v1/calendar/cancel`, `GET /api/v1/calendar/events`).
       - In the Calendar Appointments table (`buildCalendarEventsTableHTML`), the **Action** column has a **"Cancel"** button on top (cancels the appointment & sends an automatic HTML cancellation email to guests) and a **"Reschedule"** button right below it (opens `#reschedule-meeting-modal` to update Date, Start/End Time, Duration, Subject, Location/Meeting Link, and restructure the notification email message body).

3. OUTBOUND WEBHOOK EVENTS DISPATCHED BY GLENNBOT TO N8N (`n8n-nodes-base.webhook` POST Trigger):
   GlennBot dispatches real-time POST requests to every active n8n workflow's Webhook URL.
   IMPORTANT: GlennBot copies all `data` keys to the top-level JSON body as well as inside `data`, so in n8n expressions you MUST reference `$json.body.<field>` (with fallback `|| $json.<field>`):

   A) Event `comment.received` (New Facebook / Instagram / TikTok / YouTube Comment OR Page Reply to a Comment):
      - `$json.body.event` = "comment.received"
      - `$json.body.platform` ("facebook", "instagram", "tiktok", "youtube")
      - `$json.body.record_id` (GlennBot post record ID, e.g. "post_...")
      - `$json.body.post_id` (Platform / Zernio post ID)
      - `$json.body.comment_id` (Specific Comment ID to Like, Hide, Reply to, or Send Private DM to)
      - `$json.body.parent_comment_id` (Empty `""` if top-level comment on post; non-empty if nested reply to a comment)
      - `$json.body.is_reply_to_comment` (Boolean: `false` if comment on the post, `true` if reply to an existing comment)
      - `$json.body.account_id` (Page / Account ID)
      - `$json.body.account_name` (Page / Account Name, e.g. "Savvy Finds")
      - `$json.body.author_id` (Commenter user ID, or parent_author_id fallback when the Page replies)
      - `$json.body.author_name` (Commenter name, or Page name when the Page replies)
      - `$json.body.parent_author_id` (Original commenter's user ID when the Page or another user replies inside a comment thread)
      - `$json.body.parent_author_name` (Original commenter's name when the Page or another user replies inside a comment thread)
      - `$json.body.message` (The comment or reply text)
      - `$json.body.is_own_comment` (Boolean: `false` for incoming user comments; `true` when the Page itself replies to a comment. Note: Top-level comments by the Page on its own post are automatically ignored!)

   B) Event `email.received` (New Incoming Email via Gmail / Microsoft / IMAP):
      - `$json.body.event` = "email.received"
      - `$json.body.account_id` (GlennBot connected email account ID)
      - `$json.body.account_email` (Receiving email address in GlennBot dashboard)
      - `$json.body.sender_email` (Sender's email address to reply to)
      - `$json.body.sender_name` (Sender's display name)
      - `$json.body.subject` (Email subject line)
      - `$json.body.body` (Full email body text)
      - `$json.body.snippet` (Short email preview snippet)
      - `$json.body.message_id` (Email message ID)
      - `$json.body.thread_id` (Email thread ID for threaded replies)

   C) Event `message.received` (New Direct Message on Facebook, Instagram, WhatsApp, or Telegram):
      - `$json.body.event` = "message.received"
      - `$json.body.platform` ("facebook", "instagram", "whatsapp", "telegram")
      - `$json.body.account_id` (Connected account ID)
      - `$json.body.account_name` (Connected page / account name)
      - `$json.body.conversation_id` (Conversation / thread ID)
      - `$json.body.participant_id` (Sender / recipient ID)
      - `$json.body.participant_name` (Sender display name)
      - `$json.body.text` or `$json.body.message.text` (Incoming DM text)

   C1) Event `sms.sent` (User Initiated / Sent an Outbound SMS via TextBee.dev SIM 2 from GlennBot GUI or Phone):
      - Triggered automatically whenever the user sends an SMS to someone via `+ Create New SMS` or replies in an SMS conversation!
      - `$json.body.event` = "sms.sent"
      - `$json.body.platform` = "sms"
      - `$json.body.direction` = "outbound"
      - `$json.body.is_own` = true
      - `$json.body.account_id` = "textbee_sms_gateway"
      - `$json.body.account_name` = "TextBee SMS (SIM 2)"
      - `$json.body.conversation_id` (e.g. "sms_639175497760")
      - `$json.body.recipient_phone` / `$json.body.recipient` / `$json.body.phone` / `$json.body.to` / `$json.body.participant_id` (Recipient phone number in E.164 format, e.g. "+639175497760")
      - `$json.body.recipient_name` / `$json.body.participant_name` (Recipient contact name)
      - `$json.body.message` / `$json.body.text` (The SMS text sent by the user)
      - `$json.body.message_id` (Unique SMS message ID)
      - `$json.body.sim_subscription_id` ("2")

   C2) Event `sms.received` (Incoming SMS Received on TextBee.dev Android Gateway SIM 2):
      - Triggered automatically when a customer/recipient sends or replies via SMS to the user's phone!
      - `$json.body.event` = "sms.received"
      - `$json.body.platform` = "sms"
      - `$json.body.direction` = "inbound"
      - `$json.body.is_own` = false
      - `$json.body.account_id` = "textbee_sms_gateway"
      - `$json.body.conversation_id` (e.g. "sms_639175497760")
      - `$json.body.sender_phone` / `$json.body.sender` / `$json.body.phone` / `$json.body.from` / `$json.body.participant_id` (Sender phone number, e.g. "+639175497760")
      - `$json.body.sender_name` / `$json.body.participant_name` (Sender name)
      - `$json.body.message` / `$json.body.text` (Incoming SMS text)
      - `$json.body.message_id` (Unique SMS message ID)

   D) Event `contact.saved` (New or Updated CRM Contact):
      - `$json.body.event` = "contact.saved"
      - `$json.body.contact.id`, `$json.body.contact.name`, `$json.body.contact.email`, `$json.body.contact.phone`, `$json.body.contact.platform`, `$json.body.contact.notes`

   E) Event `post.scheduled` (Social Media Post Queued / Scheduled):
      - `$json.body.event` = "post.scheduled"
      - `$json.body.queued_posts` (Array of scheduled post records)

   F) Event `calendar.scheduled` (New Appointment / Online Meeting Scheduled in GlennBot Calendar):
      - Triggered automatically whenever an appointment/meeting is created via `#schedule-meeting-modal` or `POST /api/v1/calendar/schedule`!
      - `$json.body.event` = "calendar.scheduled"
      - `$json.body.action` = "scheduled"
      - `$json.body.event_id` (GlennBot Calendar Event ID, e.g. "cal_ev_...")
      - `$json.body.external_event_id` (Google Calendar / Outlook / Zoom native event ID)
      - `$json.body.account_id` (Connected Calendar Account ID)
      - `$json.body.provider` ("google_calendar", "outlook_calendar", "zoom")
      - `$json.body.subject` (Appointment / Meeting Title)
      - `$json.body.description` / `$json.body.message_body` (Agenda / Message Body)
      - `$json.body.date_str` / `$json.body.date` ("YYYY-MM-DD") & `$json.body.display_date` (e.g. "May 15, 2026")
      - `$json.body.time_str` / `$json.body.start_time` ("HH:MM") & `$json.body.time_range_str` (e.g. "10:00 AM – 11:00 AM")
      - `$json.body.start_iso`, `$json.body.end_iso`, `$json.body.timezone`, `$json.body.duration_minutes`
      - `$json.body.meeting_platform` ("google_meet", "microsoft_teams", "zoom", "none")
      - `$json.body.meeting_url` (Live video call join URL) & `$json.body.location`
      - `$json.body.organizer_email`, `$json.body.sender_email`, `$json.body.attendees` (Array of `{{"email": "..."}}`), `$json.body.attendee_emails` (Array of guest emails), `$json.body.primary_guest_email` / `$json.body.attendee_email` (First guest email)

   G) Event `calendar.rescheduled` (Existing Appointment / Meeting Rescheduled via "Reschedule" Modal or API):
      - Triggered automatically whenever an appointment's Date, Time, Duration, Subject, or Restructured Message Body is updated via `#reschedule-meeting-modal` or `POST /api/v1/calendar/reschedule`!
      - `$json.body.event` = "calendar.rescheduled"
      - `$json.body.action` = "rescheduled"
      - `$json.body.event_id`, `$json.body.external_event_id`, `$json.body.account_id`, `$json.body.provider`
      - `$json.body.subject`, `$json.body.description`, `$json.body.restructured_message_body`, `$json.body.reschedule_reason`
      - `$json.body.previous_date_str` / `$json.body.old_date`, `$json.body.previous_display_date` / `$json.body.old_display_date`, `$json.body.previous_time_range_str` / `$json.body.old_time_range_str`, `$json.body.previous_start_iso`, `$json.body.previous_end_iso`
      - `$json.body.date_str` / `$json.body.date`, `$json.body.display_date`, `$json.body.time_str` / `$json.body.start_time`, `$json.body.time_range_str`, `$json.body.start_iso`, `$json.body.end_iso`, `$json.body.timezone`, `$json.body.duration_minutes`
      - `$json.body.meeting_platform`, `$json.body.meeting_url`, `$json.body.location`
      - `$json.body.organizer_email`, `$json.body.sender_email`, `$json.body.attendees`, `$json.body.attendee_emails`, `$json.body.primary_guest_email` / `$json.body.attendee_email`

   H) Event `calendar.cancelled` (Appointment / Meeting Cancelled via "Cancel" Action Button or API):
      - Triggered automatically whenever an appointment is cancelled via the Calendar "Cancel" button (`#cancel-meeting-modal`) or `POST /api/v1/calendar/cancel`!
      - `$json.body.event` = "calendar.cancelled"
      - `$json.body.action` = "cancelled"
      - `$json.body.event_id`, `$json.body.external_event_id`, `$json.body.account_id`, `$json.body.provider`
      - `$json.body.subject`, `$json.body.description`, `$json.body.cancellation_reason` (Optional — may be blank `""` if organizer cancelled without specifying a reason)
      - `$json.body.date_str` / `$json.body.date`, `$json.body.display_date`, `$json.body.time_str` / `$json.body.start_time`, `$json.body.time_range_str`, `$json.body.timezone`
      - `$json.body.meeting_platform`, `$json.body.meeting_url`, `$json.body.meeting_url_status` ("invalidated_cancelled"), `$json.body.location`
      - `$json.body.organizer_email`, `$json.body.sender_email`, `$json.body.attendees`, `$json.body.attendee_emails`, `$json.body.primary_guest_email` / `$json.body.attendee_email`

4. COMPLETE GLENNBOT `/api/v1/*` ACTION & QUERY ENDPOINTS FOR N8N `HTTP Request` NODES:
   Every n8n `n8n-nodes-base.httpRequest` node calling GlennBot MUST send header `X-API-Key: {active_api_key}`:

   A) Ask Gemini AI (`POST {clean_base}/ai/ask`):
      - Generates clean plain-text AI replies (`$json.reply`), classifies comment/message intent (`$json.is_relevant`, `$json.is_delivery_related`, `$json.has_tracking_number`, `$json.tracking_number`, `$json.intent`), answers questions with live Google Search (`use_search: true`), or writes social post captions/titles.
      - JSON Body:
        {{
          "topic": "={{{{ 'Reply politely, kindly, and accurately to this comment or question: ' + ($json.body.message || $json.message || '') }}}}",
          "tone": "Polite, friendly, helpful, and accurate",
          "language": "Taglish",
          "post_type": "comment_reply",
          "use_search": true,
          "platforms": ["={{{{ $json.body.platform || $json.platform || 'facebook' }}}}"]
        }}
      - Output JSON fields:
        * `$json.reply`, `$json.response`, `$json.text`, `$json.answer`, `$json.message` (Always clean plain text, never raw JSON!)
        * `$json.is_relevant` (Boolean `true`/`false` — whether the comment/message matches the topic/condition asked in the prompt)
        * `$json.is_delivery_related` (Boolean `true`/`false` — whether the comment/message is asking about parcel/delivery/order tracking)
        * `$json.has_tracking_number` (Boolean `true`/`false` — whether an order/tracking number was provided in the comment)
        * `$json.tracking_number` (String — the extracted tracking number or `""` if none)
        * `$json.intent` (String — e.g. `"delivery_inquiry"`, `"price_inquiry"`, `"general"`)
      - CRITICAL RULE FOR `IF` NODES AFTER `Ask Gemini AI`:
        * NEVER check `Boolean($json.reply)` in an `IF` node to test if a comment matches a topic (because `$json.reply` is ALWAYS a non-empty string!). Instead, check `$json.is_delivery_related` or `$json.is_relevant` (`value1: "={{{{ Boolean($json.is_delivery_related) }}}}"`, `value2: true`), and if checking whether a tracking number was provided, check `Boolean($json.tracking_number)`!
      - IMPORTANT: Any node running AFTER `Ask Gemini AI` MUST reference the Webhook Trigger node (`$('Webhook').item.json.body.record_id`, `$('Webhook').item.json.body.comment_id`, etc.) for original trigger fields, and `$json.reply` for the clean plain-text AI output!

   B) Reply Directly to a User's Comment Thread (`POST {clean_base}/comments/reply`):
      - ALWAYS posts a **nested reply directly inside the user's comment thread (`comment_id`)**, NEVER a top-level comment on the post!
      - Automatically tracks multi-level sub-threads so follow-up replies stay in the active conversation sub-thread!
      - JSON Body:
        {{
          "record_id": "={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id || $json.record_id }}}}",
          "comment_id": "={{{{ $json.reply_target_comment_id || $json.subthread_comment_id || $json.latest_reply_id || $('Webhook').item.json.body.comment_id || $json.body.comment_id || $json.comment_id }}}}",
          "message": "Your public nested reply text here",
          "send_dm": false,
          "file_id": ""  // optional: Google Drive Files Vault file_id (e.g. "file_xxxxxxxxxxxx")
        }}

   B1) Send a Private DM to a Commenter (`POST {clean_base}/comments/send-dm` or `/comments/reply` with `"send_dm": true`):
      - Corresponds to the "Send a DM" Modal (`#comment-dm-modal`). Uses the exact API key of the social page where the user commented and attaches any `file_id` from the Google Drive Files Vault as a real native binary attachment (not a link!).
      - JSON Body:
        {{
          "record_id": "={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id || $json.record_id }}}}",
          "comment_id": "={{{{ $('Webhook').item.json.body.comment_id || $json.body.comment_id || $json.comment_id }}}}",
          "message": "Your private DM message here",
          "send_dm": true,
          "file_id": ""  // optional: Google Drive Files Vault file_id (e.g. "file_xxxxxxxxxxxx")
        }}

   B2) Like (or Unlike) a User's Comment (`POST {clean_base}/comments/like`):
      - JSON Body:
        {{
          "record_id": "={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id || $json.record_id }}}}",
          "comment_id": "={{{{ $('Webhook').item.json.body.comment_id || $json.body.comment_id || $json.comment_id }}}}",
          "liked": true
        }}

   B3) Hide (or Unhide) a User's Comment (`POST {clean_base}/comments/hide`):
      - JSON Body:
        {{
          "record_id": "={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id || $json.record_id }}}}",
          "comment_id": "={{{{ $('Webhook').item.json.body.comment_id || $json.body.comment_id || $json.comment_id }}}}",
          "hidden": true
        }}

   B4) Check If Commenter Replied in the Comment Thread After a Wait Timer (`GET {clean_base}/comments/thread-status`):
      - URL: `{clean_base}/comments/thread-status?record_id={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id }}}}&comment_id={{{{ $('Webhook').item.json.body.comment_id || $json.body.comment_id }}}}&force=true`
      - Method: `GET`
      - What it does: Performs a live sync on the post (including Level-2 and Level-3 sub-replies under the Page's own reply comment) and checks if the commenter replied **inside that specific comment thread** after our Page's reply (`has_reply_to_comment: true`), vs merely posting a separate top-level comment on the post (`replied_on_post_only: true`, `has_reply_to_comment: false`) or not replying at all (`has_reply_to_comment: false`).
      - Output JSON fields:
        * `$json.has_reply_to_comment` (Boolean `true` / `false`)
        * `$json.replied_on_comment_thread` (Boolean `true` / `false`)
        * `$json.replied_on_post_only` (Boolean `true` / `false`)
        * `$json.reply_target_comment_id` (The exact sub-thread Comment ID to pass as `comment_id` in the next `POST /comments/reply` node so the Page's reply lands inside the active sub-thread!)
        * `$json.subthread_comment_id` (The Page's Level-2 sub-thread comment ID)
        * `$json.latest_reply_id` (The commenter's latest nested reply ID)
        * `$json.latest_reply_message` (Text of the commenter's nested reply)
        * `$json.latest_reply_author` (Name of the commenter)

   B5) Mark Comments Read / Dismiss Notifications (`POST {clean_base}/comments/mark-read`, `POST {clean_base}/comments/dismiss`):
      - JSON Body: `{{"record_id": "...", "comment_ids": ["..."]}}`

   C) Send or Auto-Reply to Email (`POST {clean_base}/emails/send`, `POST {clean_base}/emails/trash`):
      - Supports Gmail, Microsoft/Outlook, and IMAP/SMTP + Google Drive Vault `file_id` binary attachments!
      - JSON Body:
        {{
          "account_id": "={{{{ $('Webhook').item.json.body.account_id || $json.body.account_id || $json.account_id }}}}",
          "from_email": "={{{{ $('Webhook').item.json.body.account_email || $json.body.account_email || $json.account_email }}}}",
          "to": "={{{{ $('Webhook').item.json.body.sender_email || $json.body.sender_email || $json.sender_email }}}}",
          "subject": "={{{{ 'Re: ' + ($('Webhook').item.json.body.subject || $json.body.subject || 'Inquiry') }}}}",
          "thread_id": "={{{{ $('Webhook').item.json.body.thread_id || $json.body.thread_id || '' }}}}",
          "message_id": "={{{{ $('Webhook').item.json.body.message_id || $json.body.message_id || '' }}}}",
          "body": "Your email reply message here",
          "file_id": ""  // optional: Google Drive Files Vault file_id
        }}

   D) Send Direct Message in Unified Inbox (`POST {clean_base}/messages/send`, `POST {clean_base}/messages/mark-read`):
      - Supports Facebook Messenger, Instagram DM, WhatsApp, and Telegram + Google Drive Vault `file_id` binary attachments!
      - JSON Body:
        {{
          "account_id": "={{{{ $('Webhook').item.json.body.account_id || $json.body.account_id || $json.account_id }}}}",
          "conversation_id": "={{{{ $('Webhook').item.json.body.conversation_id || $json.body.conversation_id || $json.conversation_id }}}}",
          "recipient_id": "={{{{ $('Webhook').item.json.body.participant_id || $json.body.participant_id || $json.participant_id }}}}",
          "message": "Your automated chat reply here",
          "file_id": ""  // optional: Google Drive Files Vault file_id
        }}

   D1) Send Outbound SMS via TextBee.dev SIM 2 (`POST {clean_base}/sms/send`):
      - Sends a real SMS message through the user's connected TextBee.dev Android Gateway (SIM 2) and logs it in Unified Inbox (`TextBee SMS (SIM 2)`).
      - Note: By default `trigger_webhook` is `false` so automated SMS replies from n8n do NOT re-trigger `sms.sent` in an infinite loop!
      - JSON Body:
        {{
          "recipient": "={{{{ $('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.sender_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || $json.phone || '' }}}}",
          "recipient_name": "={{{{ $('Webhook').item.json.body.recipient_name || $('Webhook').item.json.body.sender_name || $('Webhook').item.json.body.participant_name || '' }}}}",
          "message": "Your SMS message text here",
          "sim_subscription_id": "2"
        }}

   D2) Check If Recipient Replied to an SMS After a Wait Timer (`GET {clean_base}/sms/thread-status`):
      - URL (MUST start with `=` at the very beginning, NEVER wrap the base URL in `'...' +`):
        `={clean_base}/sms/thread-status?phone={{{{ encodeURIComponent($('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.sender_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || '') }}}}&conversation_id={{{{ $('Webhook').item.json.body.conversation_id || '' }}}}&message_id={{{{ $('Webhook').item.json.body.message_id || '' }}}}&force=true`
      - Method: `GET`
      - What it does: Polls TextBee.dev for any newly received SMS and checks if the recipient has replied in the SMS conversation thread after the user's outbound `message_id`!
      - Output JSON fields:
        * `$json.has_reply_to_sms` (Boolean `true` / `false`)
        * `$json.replied` (Boolean `true` / `false`)
        * `$json.latest_reply_id` (ID of the recipient's SMS reply)
        * `$json.latest_reply_message` (Text of the recipient's SMS reply)
        * `$json.latest_reply_sender` (Sender name or phone number)

   E) Publish, Schedule, or Delete Social Media Posts (`POST {clean_base}/posts/publish`, `POST {clean_base}/posts/schedule`, `POST {clean_base}/posts/delete`):
      - JSON Body:
        {{
          "platforms": ["facebook", "instagram", "tiktok", "youtube"],
          "account_id": "",  // optional specific page/account_id
          "post_type": "reels",  // "text", "image", "reels", "video169"
          "title": "Optional Video Title for YouTube",
          "caption": "Post caption here",
          "file_id": "",     // optional: Google Drive Vault file_id for single image/video
          "file_ids": [],    // optional: array of Google Drive Vault file_ids for multi-image album grid
          "thumb_file_id": "", // optional: Google Drive Vault file_id for video thumbnail
          "media_url": "",
          "date": "YYYY-MM-DD",
          "time": "HH:MM",
          "publish_now": true
        }}

   F) Create / Update / Sync CRM Contacts (`POST {clean_base}/contacts`, `POST {clean_base}/contacts/sync`, `GET {clean_base}/contacts`):
      - Corresponds to View 8 (`#view-contacts` / `#crm-contact-modal`). Automatically deduplicates & merges contacts by phone/email.
      - JSON Body:
        {{
          "first_name": "={{{{ $json.body.sender_name || $json.body.author_name || $json.body.participant_name || 'Lead' }}}}",
          "last_name": "",
          "email_address": "={{{{ $json.body.sender_email || '' }}}}",
          "contact_number": "",
          "platform": "={{{{ $json.body.platform || 'facebook' }}}}",
          "social_username": "={{{{ $json.body.author_name || $json.body.participant_name || '' }}}}",
          "account_name": "={{{{ $json.body.account_name || '' }}}}",
          "category": "Hot Lead",  // "Hot Lead", "Client / Customer", "Inquiry", "VIP", "Partner", "Follow-Up", "General"
          "notes": "Auto-captured by n8n workflow"
        }}

   G) Read / Lookup / Append / Update GlennBot Spreadsheets (`.xlsx` / `.xls` in View 10 Synced with Google Drive & Files Vault):
      - Corresponds to View 10 ("Spread Sheet" Modal `#view-spreadsheet`). Every spreadsheet is saved directly to Google Drive (`{GOOGLE_DRIVE_FOLDER_NAME}`), appears in the "Files" Modal with its own `file_id` (`file_...`), and two-way auto-syncs live if the client edits the spreadsheet in Google Drive / Google Sheets!
      - G1) Read Specific Cell(s), Row(s), Column(s), or Lookup Row Values (`GET {clean_base}/spreadsheets/read` or `POST {clean_base}/spreadsheets/read`):
        * URL example to read a specific cell (e.g. `B2`) or entire sheet (automatically live-syncs latest edits from Google Drive first!):
          `={clean_base}/spreadsheets/read?workbook_id=YOUR_WORKBOOK_ID_OR_FILE_ID&sheet_name=Sheet1&cell=B2&sync_gdrive=true`
        * Or lookup a row where a column matches a value (e.g. find row where column `Phone` or `A` matches sender):
          `={clean_base}/spreadsheets/read?workbook_id=YOUR_WORKBOOK_ID_OR_FILE_ID&lookup_column=A&lookup_value={{{{ encodeURIComponent($('Webhook').item.json.body.phone || '') }}}}&sync_gdrive=true`
        * Output JSON fields from `/spreadsheets/read`:
          - `$json.value` (Exact value of the requested `cell`, e.g. if `cell=B2`, `$json.value` is the value inside B2!)
          - `$json.cells` (Dictionary of all cell coordinates on the sheet, e.g. `$json.cells.A1`, `$json.cells.B2`, `$json.cells.C2`!)
          - `$json.row_data` (Dictionary of the requested `row` or matched `lookup` row, keyed by BOTH column letter `$json.row_data.A`, `$json.row_data.B` AND Row 1 header name `$json.row_data['Client Name']`!)
          - `$json.rows` (Array of all data rows in the sheet, each containing `_row_number`, column letters `A, B, C...`, and Row 1 header keys)
          - `$json.headers` (Map of Row 1 column headers `{{"A": "...", "B": "..."}}`)
          - `$json.file_id` (The spreadsheet's Files Vault `file_id`) & `$json.workbook_id`
      - G2) Append a New Row (`POST {clean_base}/spreadsheets/append-row`) — also auto-updates the `.xlsx` file on Google Drive:
        {{
          "workbook_id": "YOUR_WORKBOOK_ID_OR_FILE_ID",  // accepts workbook_id, file_id, or filename
          "sheet_name": "Sheet1",                        // optional (defaults to first sheet)
          "row": {{
            "A": "={{{{ $('Webhook').item.json.body.author_name || $('Webhook').item.json.body.sender_name || $('Webhook').item.json.body.participant_name || '' }}}}",
            "B": "={{{{ $('Webhook').item.json.body.sender_email || '' }}}}",
            "C": "={{{{ $('Webhook').item.json.body.phone || $('Webhook').item.json.body.recipient_phone || '' }}}}",
            "D": "={{{{ $('Webhook').item.json.body.platform || 'facebook' }}}}",
            "E": "={{{{ $('Webhook').item.json.body.message || $('Webhook').item.json.body.subject || 'Replied' }}}}"
          }}
        }}
      - G3) Update Specific Cells (`POST {clean_base}/spreadsheets/update-cells`) — also auto-updates the `.xlsx` file on Google Drive:
        `{{"workbook_id": "YOUR_WORKBOOK_ID_OR_FILE_ID", "sheet_name": "Sheet1", "cells": {{"A2": "Name", "E2": "Completed"}}}}`

   H) Create, Reschedule, Cancel, or Query Calendar Appointments & Online Meetings (`/api/v1/calendar/*`):
      - Corresponds to View 2 (`#view-calendar`), Schedule Modal (`#schedule-meeting-modal`), Reschedule Modal (`#reschedule-meeting-modal`), and the Calendar Appointments Table **Cancel** & **Reschedule** buttons!
      - H1) Schedule / Create a New Appointment or Online Meeting (`POST {clean_base}/calendar/schedule`):
        * Creates a real event on Google Calendar (with Google Meet), Microsoft Outlook (with MS Teams), or Zoom (with automatic Zoom Calendar sync via `push_change_to_calendar`), saves it in GlennBot Calendar, sends an HTML invitation email from `sender_email` (or auto-matched organizer email) to all attendees, and triggers `calendar.scheduled`.
        * JSON Body:
          {{
            "account_id": "", // optional: specific connected calendar account_id (auto-selected if blank)
            "provider": "google_calendar", // "google_calendar", "outlook_calendar", or "zoom"
            "sender_email": "={{{{ $('Webhook').item.json.body.account_email || $('Webhook').item.json.body.sender_email || '' }}}}", // optional: connected email account to send the invite from
            "subject": "={{{{ $json.body.subject || 'Client Discovery Call' }}}}",
            "date": "={{{{ $json.body.date_str || $json.body.date || '2026-05-20' }}}}", // YYYY-MM-DD
            "start_time": "14:00", // HH:MM (24h)
            "end_time": "15:00",   // optional HH:MM (24h)
            "duration_minutes": 60,
            "timezone": "Asia/Manila",
            "meeting_platform": "google_meet", // "google_meet", "microsoft_teams", "zoom", or "none"
            "location": "Google Meet",
            "attendees": ["={{{{ $json.body.sender_email || $json.body.primary_guest_email || $json.body.attendee_email || 'guest@example.com' }}}}"],
            "description": "Hi! Looking forward to our scheduled meeting. Here is our agenda..."
          }}
      - H2) Reschedule an Existing Appointment & Restructure Message Body (`POST {clean_base}/calendar/reschedule`):
        * Updates an existing appointment's Date, Start Time, End Time, Duration, Subject, Location, or Attendees on Google Calendar / Outlook / Zoom, sends a rich HTML **Rescheduled Appointment Notice** (showing Previous Schedule vs New Schedule + the restructured message body) from `sender_email` to all guests, and triggers `calendar.rescheduled`.
        * You can identify the appointment by `event_id` (`cal_ev_...` or `external_event_id`), OR by `subject_lookup` / `attendee_lookup` if `event_id` is omitted!
        * JSON Body:
          {{
            "event_id": "={{{{ $('Webhook').item.json.body.event_id || $json.body.event_id || $json.event_id || '' }}}}",
            "subject_lookup": "={{{{ $('Webhook').item.json.body.subject || '' }}}}", // optional fallback lookup if event_id is unknown
            "attendee_lookup": "={{{{ $('Webhook').item.json.body.sender_email || $('Webhook').item.json.body.primary_guest_email || $('Webhook').item.json.body.attendee_email || '' }}}}",
            "sender_email": "={{{{ $('Webhook').item.json.body.organizer_email || $('Webhook').item.json.body.account_email || '' }}}}",
            "subject": "={{{{ $('Webhook').item.json.body.subject || 'Rescheduled Consultation Call' }}}}",
            "date": "2026-05-22",       // New Date (YYYY-MM-DD)
            "start_time": "15:00",      // New Start Time (HH:MM 24h)
            "end_time": "16:00",        // New End Time (HH:MM 24h)
            "duration_minutes": 60,
            "timezone": "Asia/Manila",
            "location": "",             // optional updated location / meeting link
            "reschedule_reason": "Updated schedule per client request",
            "description": "Hi! Our appointment has been moved to a new date and time. Please review the updated schedule and restructured agenda below.",
            "notify_attendees": true
          }}
      - H3) Cancel an Existing Appointment & Notify Guests (`POST {clean_base}/calendar/cancel` or `DELETE {clean_base}/calendar/events/{{event_id}}`):
        * Cancels and removes the appointment from Google Calendar / Outlook / Zoom and GlennBot, sends an automatic HTML **Meeting Cancelled Notice** (with optional reason & deactivated meeting link) from `sender_email` to all invited guests, and triggers `calendar.cancelled`.
        * Supports lookup by `event_id`, or fallback lookup by `subject_lookup` / `attendee_lookup`! Note that `cancellation_reason` is optional and may be left blank `""`.
        * JSON Body (`POST {clean_base}/calendar/cancel`):
          {{
            "event_id": "={{{{ $('Webhook').item.json.body.event_id || $json.body.event_id || $json.event_id || '' }}}}",
            "subject_lookup": "={{{{ $('Webhook').item.json.body.subject || '' }}}}",
            "attendee_lookup": "={{{{ $('Webhook').item.json.body.sender_email || $('Webhook').item.json.body.primary_guest_email || $('Webhook').item.json.body.attendee_email || '' }}}}",
            "sender_email": "={{{{ $('Webhook').item.json.body.organizer_email || $('Webhook').item.json.body.account_email || '' }}}}",
            "cancellation_reason": "", // optional: reason for cancellation (allowed to be blank)
            "notify_attendees": true
          }}
      - H4) List / Query Calendar Appointments (`GET {clean_base}/calendar/events?sync=true`):
        * Returns all upcoming & synced appointments (`events` array with `id`, `external_event_id`, `subject`, `date_str`, `time_str`, `time_range_str`, `attendees`, `meeting_url`, `provider`) and connected `accounts`.

   I) Read / Query Endpoints (`GET`):
      - `GET {clean_base}/status`
      - `GET {clean_base}/accounts`
      - `GET {clean_base}/posts`
      - `GET {clean_base}/comments?unread_only=true`
      - `GET {clean_base}/comments/thread-status?record_id=...&comment_id=...&force=true`
      - `GET {clean_base}/messages?unread_only=true`
      - `GET {clean_base}/emails?folder=inbox&limit=20`
      - `GET {clean_base}/contacts`
      - `GET {clean_base}/files` & `GET {clean_base}/files/{{file_id}}`
      - `GET {clean_base}/spreadsheets` & `GET {clean_base}/spreadsheets/read?workbook_id=...&cell=A2&sync_gdrive=true`
      - `GET {clean_base}/calendar/events?sync=true`
      - `GET {clean_base}/analytics?period=90d`
      - `GET {clean_base}/presets`

5. LIVE INTROSPECTED `/api/v1/*` ROUTES IN `main.py`:
{chr(10).join(v1_routes_summary) if v1_routes_summary else '- Standard /api/v1/* endpoints active'}

6. ADDITIONAL LIVE `/api/*` ROUTES IN `main.py`:
{chr(10).join(other_api_routes_summary[:60]) if other_api_routes_summary else '- Standard dashboard /api/* endpoints active'}

7. LIVE PYDANTIC MODELS IN `main.py`:
{chr(10).join(pydantic_models_summary) if pydantic_models_summary else '- Dynamic JSON payloads supported'}

8. LIVE WORKSPACE DATA & RESOURCE IDs IN USER'S GLENNBOT ACCOUNT:
   - Connected Social Accounts (`platform`, `account_id`, `account_name`):
{chr(10).join(social_summary) if social_summary else '     (Auto-resolved by platform name at runtime)'}
   - Connected Email Accounts (`account_id`, `email_address`, `provider`):
{chr(10).join(email_summary) if email_summary else '     (Uses primary connected email account automatically)'}
   - Uploaded Google Drive "Files" Vault Items (`file_id`, `filename`, `content_type`):
{chr(10).join(vault_files_summary) if vault_files_summary else '     (No files uploaded yet or pass any file_... ID)'}
   - Saved & Google Drive Synced Spreadsheets (`.xlsx` / `.xls` in View 10 with `workbook_id`, `file_id`, `title`, `sheets`, Row 1 Headers & Live Cell Values):
{chr(10).join(spreadsheets_summary) if spreadsheets_summary else '     (No spreadsheets saved yet — pass workbook_id, file_id, or filename)'}
   - Saved Selection Presets (`#preset-modal`):
{chr(10).join(presets_summary) if presets_summary else '     (No custom presets saved yet)'}
   - Recent Scheduled / Published Posts (`record_id`, `platform`, `account_name`):
{chr(10).join(recent_posts_summary) if recent_posts_summary else '     (No recent posts in table)'}
   - Recent Comments (`comment_id`, `record_id`, `account_name`, `author`):
{chr(10).join(recent_comments_summary) if recent_comments_summary else '     (No recent comments cached yet)'}
   - Connected Calendar Accounts (`account_id`, `provider`, `email_address`):
{chr(10).join(calendar_accounts_summary) if calendar_accounts_summary else '     (Auto-resolved from connected Google Calendar / Outlook / Zoom accounts)'}
   - Upcoming / Synced Calendar Appointments (`event_id`, `subject`, `date`, `time`, `attendees`):
{chr(10).join(calendar_events_summary) if calendar_events_summary else '     (No calendar events cached yet — use POST /api/v1/calendar/schedule, /reschedule, or /cancel)'}
   - CRM Contacts Database Summary: {crm_summary_str}
   - Currently Saved n8n Workflows in GlennBot:
{chr(10).join(saved_workflows_summary) if saved_workflows_summary else '     (None saved yet)'}
"""
    return spec_text


def _prepare_ask_ai_n8n_attachment_parts(raw_attachments: list) -> tuple:
    """
    Processes user-attached files from the Ask AI n8n Workflow modal into:
    1) Gemini multimodal `inlineData` parts (images, PDFs, audio, video)
    2) Extracted readable text sections (for .docx, .xlsx/.xls, .json, .csv, .txt, .md, code files, etc.)
    Returns (inline_parts, extracted_text_sections, attachment_names).
    """
    import zipfile
    import xml.etree.ElementTree as ET

    inline_parts = []
    extracted_text_sections = []
    attachment_names = []

    if not isinstance(raw_attachments, list):
        return inline_parts, extracted_text_sections, attachment_names

    supported_inline_prefixes = ("image/", "audio/", "video/")
    supported_inline_exact = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/gif",
    }

    for idx, item in enumerate(raw_attachments[:8], start=1):
        if not isinstance(item, dict):
            continue
        fname = str(item.get("name") or f"attachment_{idx}").strip()
        mime_type = str(item.get("mime_type") or "").strip().lower()
        b64_str = str(item.get("data_base64") or "").strip()
        text_content = str(item.get("text_content") or "").strip()

        if "," in b64_str and b64_str.startswith("data:"):
            b64_str = b64_str.split(",", 1)[1].strip()

        if not mime_type or mime_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(fname)
            if guessed:
                mime_type = guessed.lower()

        lower_name = fname.lower()
        attachment_names.append(fname)

        raw_bytes = b""
        if b64_str:
            try:
                raw_bytes = base64.b64decode(b64_str)
            except Exception:
                raw_bytes = b""

        # 1. Native multimodal inlineData for images, PDFs, audio, video
        if b64_str and (
            mime_type in supported_inline_exact
            or any(mime_type.startswith(pref) for pref in supported_inline_prefixes)
            or lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".pdf"))
        ):
            effective_mime = mime_type
            if lower_name.endswith(".pdf"):
                effective_mime = "application/pdf"
            elif lower_name.endswith((".jpg", ".jpeg")):
                effective_mime = "image/jpeg"
            elif lower_name.endswith(".png"):
                effective_mime = "image/png"
            elif lower_name.endswith(".webp"):
                effective_mime = "image/webp"
            elif lower_name.endswith(".gif"):
                effective_mime = "image/gif"
            inline_parts.append({
                "inlineData": {
                    "mimeType": effective_mime or "image/png",
                    "data": b64_str
                }
            })
            extracted_text_sections.append(
                f"[Attached File #{idx}: '{fname}' ({effective_mime}) — Included as multimodal visual/document input for Gemini 3.5 Flash to inspect directly.]"
            )
            continue

        # 2. Word (.docx) extraction in-memory
        if raw_bytes and lower_name.endswith(".docx"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    if "word/document.xml" in zf.namelist():
                        xml_bytes = zf.read("word/document.xml")
                        root = ET.fromstring(xml_bytes)
                        paragraphs = []
                        for elem in root.iter():
                            if elem.tag.endswith("}t") and elem.text:
                                paragraphs.append(elem.text)
                            elif elem.tag.endswith("}p"):
                                paragraphs.append("\n")
                        docx_text = "".join(paragraphs).strip()
                        if docx_text:
                            extracted_text_sections.append(
                                f"--- ATTACHED WORD DOCUMENT #{idx}: {fname} ---\n{docx_text[:60000]}"
                            )
                            continue
            except Exception:
                pass

        # 3. Excel (.xlsx / .xls) extraction in-memory
        if raw_bytes and lower_name.endswith((".xlsx", ".xls")):
            try:
                wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
                sheet_dumps = []
                for sheet_name in wb.sheetnames[:6]:
                    ws = wb[sheet_name]
                    rows_out = []
                    for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                        if r_idx >= 150:
                            break
                        vals = [str(cell).strip() if cell is not None else "" for cell in row]
                        if any(vals):
                            rows_out.append(" | ".join(vals))
                    if rows_out:
                        sheet_dumps.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows_out))
                if sheet_dumps:
                    extracted_text_sections.append(
                        f"--- ATTACHED EXCEL SPREADSHEET #{idx}: {fname} ---\n" + "\n\n".join(sheet_dumps)[:60000]
                    )
                    continue
            except Exception:
                pass

        # 4. Text / JSON / CSV / Markdown / Code / XML / YAML
        if not text_content and raw_bytes:
            try:
                text_content = raw_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                text_content = ""

        if text_content:
            extracted_text_sections.append(
                f"--- ATTACHED FILE #{idx}: {fname} ({mime_type or 'text'}) ---\n{text_content[:60000]}"
            )
        elif b64_str:
            # Fallback: pass as text/plain inline or note
            extracted_text_sections.append(
                f"[Attached File #{idx}: '{fname}' ({mime_type or 'binary'})]"
            )

    return inline_parts, extracted_text_sections, attachment_names


@router.post("/api/internal-api/n8n-workflows/ask-ai")
async def api_ask_ai_generate_n8n_workflow(request: Request):
    """
    Uses Gemini 3.5 Flash (`GEMINI_API_KEY` from `.env`, strictly never exposed to GUI) + live runtime
    introspection of `main.py` and `index.html` to generate a complete, importable n8n Workflow `.json` file
    from the user's prompt and/or any attached files (images, screenshots, flowcharts, PDFs, DOCX, XLSX, JSON, TXT, CSV, etc.).
    Automatically injects the user's active `X-API-Key` and live `/api/v1/*` URLs and analyzes triggers/conditions.
    """
    _load_internal_api_state(force_cloud=False)
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "GEMINI_API_KEY is not configured in .env. Please check your .env file."
            }
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    user_prompt = str(body.get("prompt") or body.get("topic") or "").strip()
    raw_attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    inline_parts, extracted_text_sections, attachment_names = _prepare_ask_ai_n8n_attachment_parts(raw_attachments)

    if not user_prompt and not inline_parts and not extracted_text_sections:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Paki-describe muna o mag-attach ng file/image kung anong n8n workflow automation ang gusto mong ipagawa kay Gemini!"}
        )

    live_base_api = f"{get_dynamic_base_url(request=request, prefer_public=True)}/api/v1"
    active_internal_key = _get_active_internal_api_key_token()
    preferred_model = (os.getenv("GEMINI_MODEL") or "gemini-3.5-flash").strip() or "gemini-3.5-flash"
    candidate_models = [preferred_model]
    for fallback in [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-latest",
    ]:
        if fallback not in candidate_models:
            candidate_models.append(fallback)

    try:
        live_spec = _build_dynamic_glennbot_n8n_system_specification(live_base_api)
    except Exception as spec_err:
        print(f"⚠️ Warning building live n8n system specification: {spec_err}")
        live_spec = f"Active GlennBot Base API URL: {live_base_api} | Active X-API-Key: {active_internal_key}"

    system_instruction = (
        "You are GlennBot Master n8n Workflow Architect AI (powered by Gemini 3.5 Flash). "
        "You have complete, line-by-line mastery of the entire GlennBot Automations Python backend (main.py), "
        "every frontend modal, tab, setting, DOM ID, database table, Cloudinary store, Google Drive Files Vault, "
        "Spreadsheet (.xlsx) engine, Unified Inbox, Email Hub, CRM Contacts, and n8n JSON schema. "
        "Given the user's automation request and/or any attached files (flowcharts, diagrams, UI screenshots, PDFs, "
        "Word docs, Excel spreadsheets, text specs, or JSON files), you must carefully inspect every detail and "
        "generate a 100% valid, production-ready n8n Workflow JSON object (`workflow_json`) with zero missing steps."
    )

    effective_user_request = user_prompt if user_prompt else (
        "Please carefully read and interpret the attached file(s)/image(s) to understand the automation workflow requested, "
        "and build the complete GlennBot-compatible n8n Workflow .json for it."
    )

    attachments_context_block = ""
    if extracted_text_sections:
        attachments_context_block = (
            "\n\n=== USER ATTACHED FILES / DOCUMENTS / VISUALS FOR INTERPRETATION ===\n"
            + "\n\n".join(extracted_text_sections)
            + "\n"
        )

    full_prompt = f"""{live_spec}

=== USER'S N8N AUTOMATION REQUEST ===
"{effective_user_request}"{attachments_context_block}

=== MASTER N8N WORKFLOW JSON GENERATION & FLOWCHART INTERPRETATION RULES ===
1. **Complete End-to-End Fidelity**:
   - Build a complete, valid n8n workflow JSON object (`workflow_json`) that fulfills 100% of the user's prompt and/or EVERY action box, parallel branch, wait timer, like action, DM action, file attachment, spreadsheet row log, CRM contact save, and decision diamond in any attached flowchart/image/document.
   - Match exact resource IDs from Section 8 of the live specification whenever the user mentions a connected Page name (e.g. `"Savvy Finds"`), an email address, a Google Drive Vault file (by filename or `file_id`), or a Spreadsheet (`.xlsx` `workbook_id` / `title`).

2. **Trigger Node (`n8n-nodes-base.webhook` or `n8n-nodes-base.scheduleTrigger`)**:
   - Unless the user asks exclusively for a recurring timer/cron schedule (`n8n-nodes-base.scheduleTrigger`), ALWAYS start with an `n8n-nodes-base.webhook` node named `"Webhook"`:
     * `"type": "n8n-nodes-base.webhook"`
     * `"typeVersion": 2`
     * `"parameters": {{"httpMethod": "POST", "path": "<descriptive-kebab-case-slug>", "responseMode": "onReceived", "options": {{}}}}`
     * `"webhookId": "<descriptive-kebab-case-slug>"`

3. **IF / Filter Node Rules (`n8n-nodes-base.if`)**:
   - **CRITICAL MULTI-PLATFORM / MULTI-VALUE RULE**: A single webhook event comes from ONE platform at a time (`"facebook"` OR `"instagram"`). If an IF node checks multiple platforms or multiple keywords on the same field, you MUST set `"combinator": "or"` (for IF `typeVersion: 2`) or `"combineOperation": "any"` (for IF `typeVersion: 1`)! NEVER use `"and"` for mutually exclusive values of the same field!
   - If the user or flowchart specifies a particular Page/Account name (e.g. `"Savvy Finds"` Facebook page), add an `n8n-nodes-base.if` filter node right after `"Webhook"` checking:
     * `value1: "={{{{ $json.body.account_name || $json.account_name || '' }}}}"`, `operation: "contains"`, `value2: "<Page Name>"`
     * And if a specific platform is mentioned (e.g. Facebook), also check `value1: "={{{{ $json.body.platform || $json.platform || '' }}}}"`, `operation: "contains"`, `value2: "facebook"`.
   - When logging both customer comments AND the Page's own replies to comments into a spreadsheet (like `Conversations.xlsx`), allow `Boolean(!($json.body.is_own_comment ?? $json.is_own_comment) || ($json.body.is_reply_to_comment ?? $json.is_reply_to_comment) || ($json.body.parent_comment_id ?? $json.parent_comment_id))` so customer comments and Page replies to comments are logged while top-level Page self-comments on its own post are ignored. Always use valid `$('Webhook Trigger').item.json.body` syntax (never `($'Webhook Trigger')`). Furthermore, group each comment thread (root comment + all replies to that comment by the Page and Commenter) into ONE SINGLE ROW per comment thread by reading the sheet (`GET /api/v1/spreadsheets/read`) and upserting the matching `[Thread: ...]` row (or passing `thread_id` to `POST /api/v1/spreadsheets/append-row`).

4. **CRITICAL RULES FOR FLOWCHART / DIAGRAM CALLOUT BOXES ("Correct" / "InCorrect" / "True" / "Then" / "Example:")**:
   - Flowcharts often contain **Action/Decision Nodes** (rectangles/diamonds connected by workflow arrows) AND **Illustrative Example Callout Boxes** (speech bubbles or side boxes labeled `Correct`, `InCorrect`, `True`, `Then`, `Example:` showing sample conversations like `Someone : Nice one!`, `Savvy Finds: "Thank you very much"`, `Someone : "Your Welcome!"`, `Savvy Finds "Hehehe!"`).
   - **NEVER** include `Someone:`'s example text (such as `"Nice one!"` or `"Your Welcome!"`) inside the Page's reply `message`! `Someone:` represents the user/commenter in the example illustration, NOT what the Page/bot should say!
   - If an `If yes` branch has an action box `Reply to his comment saying "Thank you"` AND a `Then` callout box showing the Page (`Savvy Finds`) sending a follow-up line `"Hehehe!"`, create **two sequential `POST {live_base_api}/comments/reply` HTTP Request nodes** (first node sends `"Thank you"`, second node connected after it sends `"Hehehe!"`), OR send the exact reply text specified in the action box (`"Thank you"`). NEVER mash them together with `Someone:`'s line into `"Thank you! Your Welcome! Hehehe!"`!

5. **CRITICAL RULES FOR COMMENT LIKE, COMMENT THREAD REPLY, AND SUB-THREAD CONTINUATION AFTER WAIT**:
   - **Liking a Comment ("Like the comment")**: Add an `n8n-nodes-base.httpRequest` node calling `POST {live_base_api}/comments/like` with JSON body:
     `{{"record_id": $('Webhook').item.json.body.record_id, "comment_id": $('Webhook').item.json.body.comment_id, "liked": true}}`
   - **Replying ON the Comment vs Commenting on the Post**: Calling `POST {live_base_api}/comments/reply` with `record_id` and `comment_id` ALWAYS posts a **nested reply directly on that comment**, never a separate comment on the post.
   - **Parallel Branches from Trigger/Filter**: If a flowchart splits into two arrows after receiving a comment (e.g., Arrow 1 -> `Like the comment` -> `Wait...`, Arrow 2 -> `Reply to a comment saying "Thank you very much"`), connect BOTH nodes (`Like the comment` and `Reply to a comment...`) in parallel from the Filter/Webhook output (or run `Reply to a comment` and `Like the comment` immediately before `Wait` so the Page's reply is posted BEFORE the 2-minute Wait timer starts!).
   - **Waiting N Minutes for Commenter to Reply in the Thread ("Wait till he replies to your comment for X minutes" -> "Receives the reply comment?" -> If Yes / If No)**:
     a) Add an `n8n-nodes-base.wait` node (`"type": "n8n-nodes-base.wait"`, `"typeVersion": 1.1`, `"parameters": {{"resume": "timeInterval", "amount": <N>, "unit": "minutes"}}`).
     b) Immediately after `Wait`, add an `n8n-nodes-base.httpRequest` node (`"method": "GET"`) calling:
        `"{live_base_api}/comments/thread-status?record_id={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id }}}}&comment_id={{{{ $('Webhook').item.json.body.comment_id || $json.body.comment_id }}}}&force=true"`
     c) Immediately after `GET /comments/thread-status`, add an `n8n-nodes-base.if` node (e.g. `"Receives the reply comment?"`, `"typeVersion": 1`) checking `parameters.conditions.boolean`:
        `"boolean": [{{"value1": "={{{{ $json.has_reply_to_comment }}}}", "value2": true}}]`
     d) **SUB-THREAD CONTINUATION (`reply_target_comment_id`)**:
        - On the **True branch (output index 0 — "If yes")**, connect to `POST {live_base_api}/comments/reply` and MUST pass:
          `"comment_id": $('Check Comment Thread Status').item.json.reply_target_comment_id || $json.reply_target_comment_id || $json.subthread_comment_id || $json.latest_reply_id || $('Webhook').item.json.body.comment_id`
          Why? Because passing `reply_target_comment_id` / `subthread_comment_id` / `latest_reply_id` ensures the Page's follow-up reply is posted **directly under the commenter's latest nested reply inside the active sub-thread**, rather than jumping back to the root comment!
        - On the **False branch (output index 1 — "If no")**, connect to `POST {live_base_api}/comments/reply` passing:
          `"comment_id": $json.reply_target_comment_id || $json.subthread_comment_id || $('Webhook').item.json.body.comment_id`
          and the `"If no"` reply message (e.g. `"Hey!!! answer me!!"`).

5B. **CRITICAL RULES FOR TEXTBEE.DEV SMS WORKFLOWS (USER-INITIATED `sms.sent`, INBOUND `sms.received`, AND POST-WAIT SMS REPLY CHECK)**:
   - **When the workflow starts because the USER initiated/sent an SMS to someone ("kapag ako ang nag-initiate mag-send ng SMS")**:
     a) Start with the `"Webhook"` node (`n8n-nodes-base.webhook`). Optionally add an IF filter (`"typeVersion": 1`) checking `parameters.conditions.string`:
        `{{"value1": "={{{{ $json.body.event || $json.event || '' }}}}", "operation": "contains", "value2": "sms.sent"}}`
        (and if a specific phone number like `+639175497760` was requested, check `{{"value1": "={{{{ $json.body.recipient_phone || $json.body.phone || '' }}}}", "operation": "contains", "value2": "9175497760"}}`).
     b) If the workflow waits for the recipient to reply (e.g., `Wait 2 minutes` -> `Check if recipient replied to my SMS` -> `If Yes` / `If No`):
        - Add an `n8n-nodes-base.wait` node (`"resume": "timeInterval"`, `"amount": <N>`, `"unit": "minutes"`).
        - Immediately after `Wait`, add an `n8n-nodes-base.httpRequest` node (`"method": "GET"`) with `"url"` starting with `=` (NEVER use `'https://...' +`):
          `"={live_base_api}/sms/thread-status?phone={{{{ encodeURIComponent($('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || '') }}}}&conversation_id={{{{ $('Webhook').item.json.body.conversation_id || '' }}}}&message_id={{{{ $('Webhook').item.json.body.message_id || '' }}}}&force=true"`
        - Immediately after `GET /sms/thread-status`, add an `n8n-nodes-base.if` node (`"typeVersion": 1`) checking `parameters.conditions.boolean`:
          `"boolean": [{{"value1": "={{{{ Boolean($json.has_reply_to_sms) }}}}", "value2": true}}]`
        - On the **True branch (If Yes — recipient replied)** or **False branch (If No — recipient did not reply)**, send follow-up SMS messages using `POST {live_base_api}/sms/send` with JSON body:
          `{{"recipient": $('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id, "recipient_name": $('Webhook').item.json.body.recipient_name || $('Webhook').item.json.body.participant_name || '', "message": "<follow-up SMS text>", "sim_subscription_id": "2"}}`

5C. **CRITICAL RULES FOR CALENDAR APPOINTMENT CREATION, RESCHEDULING, AND CANCELLATION WORKFLOWS (`calendar.scheduled`, `calendar.rescheduled`, `calendar.cancelled`, `/calendar/schedule`, `/calendar/reschedule`, `/calendar/cancel`)**:
   - **Triggering on Calendar Events from GlennBot**:
     * When the user wants an automation triggered when an appointment is **booked/created**, check `$json.body.event` contains `"calendar.scheduled"`.
     * When the user wants an automation triggered when an appointment is **rescheduled** (via the Calendar "Reschedule" button/modal or API), check `$json.body.event` contains `"calendar.rescheduled"`. Note that `calendar.rescheduled` provides both the old schedule (`$json.body.previous_display_date`, `$json.body.previous_time_range_str`) and the new schedule (`$json.body.display_date`, `$json.body.time_range_str`, `$json.body.date_str`, `$json.body.time_str`), plus `$json.body.restructured_message_body`, `$json.body.reschedule_reason`, `$json.body.meeting_url`, and `$json.body.primary_guest_email`!
     * When the user wants an automation triggered when an appointment is **cancelled** (via the Calendar "Cancel" button or API), check `$json.body.event` contains `"calendar.cancelled"`.
   - **Automating Appointment Booking / Rescheduling / Cancellation from Inbound Emails, SMS, or DMs**:
     * If a workflow starts from `email.received`, `sms.received`, `message.received`, or `comment.received` (e.g., a client emails or texts asking to **book**, **reschedule**, or **cancel** an appointment):
       - To **Create / Book** an appointment: Call `POST {live_base_api}/calendar/schedule` with `subject`, `date` (`YYYY-MM-DD`), `start_time` (`HH:MM`), `duration_minutes`, `meeting_platform` (`"google_meet"`, `"microsoft_teams"`, `"zoom"`), `attendees` (`[$('Webhook').item.json.body.sender_email]`), and `description`.
       - To **Reschedule** an existing appointment (and restructure the message body): Call `POST {live_base_api}/calendar/reschedule` with `event_id` (or `attendee_lookup`: `$('Webhook').item.json.body.sender_email` / `subject_lookup`), new `date`, new `start_time`, `duration_minutes`, `reschedule_reason`, and the restructured `description` (`message_body`).
       - To **Cancel** an existing appointment: Call `POST {live_base_api}/calendar/cancel` with `event_id` (or `attendee_lookup`: `$('Webhook').item.json.body.sender_email` / `subject_lookup`), `cancellation_reason`, and `"notify_attendees": true`.
       - You can also chain `POST {live_base_api}/ai/ask` before `/calendar/schedule` or `/calendar/reschedule` if the workflow needs Gemini AI to draft a polite restructured appointment message body or parse natural language dates!

6. **HTTP Request Node Format (`n8n-nodes-base.httpRequest`, `typeVersion: 4.2`)**:
   - Always include header `X-API-Key: {active_internal_key}` (`sendHeaders: true`).
   - For `POST` endpoints: `"method": "POST"`, `"sendBody": true`, `"specifyBody": "json"`, `"jsonBody": "={{{{ JSON.stringify({{ ... }}) }}}}"`.
   - For `GET` endpoints (like `/comments/thread-status`, `/sms/thread-status`, `/files`, `/spreadsheets`, `/analytics`): `"method": "GET"`. Always prefix dynamic GET URLs with `=` at the very start of the string (e.g. `"={live_base_api}/sms/thread-status?phone={{{{ ... }}}}"`), NEVER use JS string concatenation `'...' +` inside `"url"`.

7. **Clean Visual Layout & Connections**:
   - Space node `"position": [x, y]` coordinates cleanly left-to-right (e.g. `[240, 300]`, `[500, 300]`, `[780, 180]`, `[780, 420]`, `[1040, 180]`, `[1300, 180]`, `[1560, 180]`, `[1820, 100]`, `[1820, 300]`) and verify every node name in `"connections"` matches `"nodes"` 100%.

8. **Strict JSON Response Format**:
   Return ONLY a valid raw JSON object (no markdown fences, no extra text outside JSON) with this exact structure:
{{
  "workflow_name": "Descriptive Name of the Workflow",
  "explanation": "Clear Taglish explanation of how the workflow works, how each modal/API/ID is used, and how every step/branch from the prompt or attached file was implemented.",
  "workflow_json": {{
    "name": "Descriptive Name of the Workflow",
    "nodes": [ ... ],
    "connections": {{ ... }},
    "active": false,
    "settings": {{ "executionOrder": "v1" }}
  }}
}}
"""

    request_parts = list(inline_parts) + [{"text": f"{system_instruction}\n\n{full_prompt}"}]

    last_err = ""
    for current_model in candidate_models:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": request_parts}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json"
            }
        }

        for attempt in range(1, 3):
            try:
                resp = await run_in_threadpool(lambda: requests.post(gemini_url, json=payload, timeout=65))
                if resp.status_code == 200:
                    res_data = resp.json()
                    candidates = res_data.get("candidates", [])
                    if not candidates:
                        last_err = f"No response returned from Gemini ({current_model})."
                        break

                    parts = candidates[0].get("content", {}).get("parts", [])
                    raw_text = "".join(part.get("text", "") for part in parts).strip()

                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        if lines and lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        raw_text = "\n".join(lines).strip()

                    parsed = None
                    try:
                        parsed = json.loads(raw_text)
                    except Exception:
                        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
                        if m:
                            try:
                                parsed = json.loads(m.group(0))
                            except Exception:
                                pass

                    if not isinstance(parsed, dict):
                        last_err = f"Gemini ({current_model}) returned an invalid JSON format."
                        break

                    # Extract workflow_json whether nested under "workflow_json" or returned directly as an n8n workflow object
                    wf_json_obj = parsed.get("workflow_json") if isinstance(parsed.get("workflow_json"), dict) else None
                    if not wf_json_obj and isinstance(parsed.get("nodes"), list):
                        wf_json_obj = parsed

                    if not isinstance(wf_json_obj, dict) or not isinstance(wf_json_obj.get("nodes"), list):
                        last_err = f"Generated JSON from {current_model} did not contain valid n8n 'nodes'."
                        break

                    wf_name = str(parsed.get("workflow_name") or wf_json_obj.get("name") or "AI Generated n8n Workflow").strip()
                    wf_json_obj["name"] = wf_name
                    explanation = str(parsed.get("explanation") or f"Generated n8n workflow '{wf_name}' with {len(wf_json_obj.get('nodes') or [])} nodes.").strip()

                    # Auto-inject live X-API-Key & live /api/v1/* URLs and run GlennBot's workflow analyzer
                    patched_json = _auto_inject_credentials_into_workflow_json(wf_json_obj, live_base_api)
                    analysis = _analyze_n8n_workflow_json(patched_json)

                    # Remember the most recently generated AI workflow so live webhooks work immediately even before manual card save
                    with INTERNAL_API_LOCK:
                        INTERNAL_API_STATE["last_ai_generated_workflow"] = {
                            "name": wf_name,
                            "webhook_path": analysis.get("webhook_path") or "",
                            "events": analysis.get("events") or {},
                            "workflow_json": patched_json
                        }

                    return {
                        "status": "success",
                        "model": current_model,
                        "workflow_name": wf_name,
                        "explanation": explanation,
                        "workflow_json": patched_json,
                        "analysis": analysis
                    }
                elif resp.status_code in (429, 404):
                    last_err = f"Gemini {current_model} returned HTTP {resp.status_code}: {resp.text[:200]}"
                    break
                elif resp.status_code in (503, 500) and attempt < 2:
                    await run_in_threadpool(lambda: time.sleep(1.0))
                    continue
                else:
                    err_detail = (resp.text or "")[:300]
                    last_err = f"Gemini API ({current_model}) returned HTTP {resp.status_code}: {err_detail}"
                    break
            except Exception as ex:
                last_err = f"Network error connecting to Gemini ({current_model}): {str(ex)}"
                if attempt < 2:
                    await run_in_threadpool(lambda: time.sleep(1.0))

    return JSONResponse(status_code=500, content={"status": "error", "message": last_err or "Failed to generate n8n workflow with Gemini."})



@router.post("/api/internal-api/n8n-workflows/save")
async def api_save_n8n_workflow(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    def _do_save_wf():
        _load_internal_api_state(force_cloud=False)
        if body.get("global_webhook_secret") is not None:
            sec_g = str(body.get("global_webhook_secret") or "").strip()
            if sec_g:
                with INTERNAL_API_LOCK:
                    INTERNAL_API_STATE["n8n_webhook_secret"] = sec_g
        return _upsert_n8n_workflow_in_db(body, sync_cloud=True)
    saved_wf = await run_in_threadpool(_do_save_wf)
    return {
        "status": "success",
        "message": f"Saved workflow '{saved_wf.get('name')}'!",
        "workflow": saved_wf,
        "n8n_workflows": INTERNAL_API_STATE.get("n8n_workflows") or [],
        "n8n_webhook_secret": INTERNAL_API_STATE.get("n8n_webhook_secret") or "gb_whsec_n8n_automation_2026"
    }


@router.delete("/api/internal-api/n8n-workflows/{workflow_id}")
async def api_delete_n8n_workflow(workflow_id: str):
    return await run_in_threadpool(lambda: _delete_n8n_workflow_sync(workflow_id))


def _delete_n8n_workflow_sync(workflow_id: str):
    _load_internal_api_state(force_cloud=False)
    clean_id = str(workflow_id or "").strip()
    with INTERNAL_API_LOCK:
        INTERNAL_API_STATE["n8n_workflows"] = [
            w for w in (INTERNAL_API_STATE.get("n8n_workflows") or [])
            if str(w.get("id")) != clean_id
        ]
        deleted_ids = set(INTERNAL_API_STATE.get("deleted_workflow_ids") or [])
        if clean_id:
            deleted_ids.add(clean_id)
        INTERNAL_API_STATE["deleted_workflow_ids"] = list(deleted_ids)
    try:
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM glennbot_n8n_workflows WHERE id = :id"), {"id": clean_id})
    except Exception as e:
        print(f"[InternalAPI] Delete workflow warning: {e}")

    _save_internal_api_to_cloudinary()
    return {
        "status": "success",
        "message": "Workflow automation permanently removed from Database and Cloudinary.",
        "n8n_workflows": INTERNAL_API_STATE.get("n8n_workflows") or []
    }


@router.post("/api/internal-api/n8n-webhook")
async def api_save_outbound_n8n_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    await run_in_threadpool(lambda: _load_internal_api_state(force_cloud=False))

    wh_url = str(body.get("n8n_webhook_url") or "").strip()
    wh_sec = str(body.get("n8n_webhook_secret") or "gb_whsec_n8n_automation_2026").strip()
    events_in = body.get("n8n_events")

    with INTERNAL_API_LOCK:
        if wh_url:
            INTERNAL_API_STATE["n8n_webhook_url"] = wh_url
        if wh_sec:
            INTERNAL_API_STATE["n8n_webhook_secret"] = wh_sec
        if isinstance(events_in, dict):
            for k, v in events_in.items():
                INTERNAL_API_STATE["n8n_events"][str(k)] = bool(v)

    threading.Thread(target=_save_internal_api_to_cloudinary, daemon=True).start()
    return {
        "status": "success",
        "message": "Global n8n Webhook Signing Secret & settings saved!",
        "n8n_webhook_url": INTERNAL_API_STATE["n8n_webhook_url"],
        "n8n_webhook_secret": INTERNAL_API_STATE["n8n_webhook_secret"],
        "n8n_events": INTERNAL_API_STATE["n8n_events"],
        "n8n_workflows": INTERNAL_API_STATE.get("n8n_workflows") or []
    }


@router.post("/api/internal-api/n8n-webhook/test")
async def api_test_outbound_n8n_webhook(request: Request):
    """
    Dynamically tests a specific n8n Workflow Automation (or custom URL) by inspecting its uploaded
    `workflow_json` and auto-generating a matching sample payload with any required IF-node keywords!
    Runs inside the worker threadpool so the FastAPI event loop remains 100% unblocked when n8n
    simultaneously calls back into /api/v1/* endpoints during the workflow run!
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await run_in_threadpool(lambda: _test_outbound_n8n_webhook_sync(body))


def _test_outbound_n8n_webhook_sync(body: Dict[str, Any]):
    _load_internal_api_state(force_cloud=False)

    wf_id = str(body.get("workflow_id") or "").strip()
    override_url = str(body.get("n8n_webhook_url") or body.get("webhook_url") or "").strip()
    override_sec = str(body.get("webhook_secret") or "").strip()

    workflows = list(INTERNAL_API_STATE.get("n8n_workflows") or [])
    matched_wf = next((w for w in workflows if str(w.get("id")) == wf_id), None) if wf_id else None

    if matched_wf and override_url:
        matched_wf["webhook_url"] = override_url
        _upsert_n8n_workflow_in_db(matched_wf, sync_cloud=True)

    target_url = override_url or str((matched_wf or {}).get("webhook_url") or INTERNAL_API_STATE.get("n8n_webhook_url") or "").strip()
    if not target_url or not target_url.startswith("http"):
        return JSONResponse({
            "status": "error",
            "message": "Please paste an n8n Webhook Trigger URL (POST) for this workflow before sending a Test Event."
        }, status_code=400)

    # Determine which event to simulate from request or from the workflow's enabled `events`
    sim_event = str(body.get("event_type") or "").strip()
    if not sim_event and matched_wf:
        wf_evts = matched_wf.get("events") if isinstance(matched_wf.get("events"), dict) else {}
        sim_event = next((k for k, v in wf_evts.items() if v), "")
    if not sim_event:
        sim_event = "comment.received"

    sample_data = _build_dynamic_test_payload_for_workflow(sim_event, matched_wf or body)
    res = _dispatch_outbound_n8n_webhook_sync(
        sim_event,
        sample_data,
        target_workflow_id=wf_id if matched_wf else None,
        override_url=target_url,
        override_secret=override_sec or None
    )
    if res.get("dispatched"):
        return {
            "status": "success",
            "message": f"Dynamic '{sim_event}' test event sent to '{(matched_wf or {}).get('name') or 'n8n Webhook'}' (HTTP {res.get('status_code')})!",
            "result": res
        }
    return JSONResponse({
        "status": "error",
        "message": f"Failed to reach n8n Webhook URL: {res.get('error') or res.get('reason')}",
        "result": res
    }, status_code=400)


