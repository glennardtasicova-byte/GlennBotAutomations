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
# --- MULTI-PLATFORM EMAIL HUB (COMPOSIO v3 OAUTH2 FOR GMAIL & MICROSOFT + IMAP/SMTP) ---
# ==============================================================================
import html as py_html
import base64
import zipfile
import mimetypes
import imaplib
import smtplib
import email as py_email
from email.header import decode_header as py_decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import hmac

COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3"
DEFAULT_COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "").strip()
DEFAULT_COMPOSIO_WEBHOOK_URL = os.getenv("COMPOSIO_WEBHOOK_URL", "").strip() or f"{get_dynamic_base_url(prefer_public=True)}/webhooks"
DEFAULT_COMPOSIO_WEBHOOK_SECRET = os.getenv("COMPOSIO_WEBHOOK_SECRET", "").strip() or "e6747eca1553134a55d78dbe509f20608700580e670cdc4c99ddf52057af5e59"
EMAIL_CLOUDINARY_PUBLIC_ID = "glennbot_config/email_accounts_store.json"
MANILA_TZ = pytz.timezone("Asia/Manila")


def _resolve_active_composio_webhook_url(request: Optional[Request] = None) -> str:
    """
    Dynamically resolves the active Email Webhook URL (`/webhooks`) based on the live environment
    (Ngrok, Render.com, Railway, Cloud Run, custom domain, or localhost) so it never gets stuck
    on a stale Render or old Ngrok URL when switching environments.
    """
    explicit_env_wh = os.getenv("COMPOSIO_WEBHOOK_URL", "").strip()
    if explicit_env_wh:
        return explicit_env_wh
    live_base = get_dynamic_base_url(request=request, prefer_public=True)
    dynamic_wh = f"{live_base}/webhooks"
    stored_wh = str(EMAIL_HUB_STATE.get("composio_webhook_url") or "").strip()
    if not stored_wh:
        return dynamic_wh
    # If stored_wh is from a previous environment (e.g. old onrender.com while currently on ngrok, or vice versa),
    # automatically adapt to the current live_base!
    if not stored_wh.startswith(live_base) and not _is_localhost_origin(live_base):
        EMAIL_HUB_STATE["composio_webhook_url"] = dynamic_wh
        return dynamic_wh
    if "glennbot-scheduler.onrender.com" in stored_wh and "glennbot-scheduler.onrender.com" not in live_base:
        EMAIL_HUB_STATE["composio_webhook_url"] = dynamic_wh
        return dynamic_wh
    return stored_wh


EMAIL_HUB_STATE = {
    "composio_api_key": DEFAULT_COMPOSIO_API_KEY,
    "composio_webhook_url": DEFAULT_COMPOSIO_WEBHOOK_URL,
    "composio_webhook_secret": DEFAULT_COMPOSIO_WEBHOOK_SECRET,
    "gmail_auth_config_id": "ac_Nk5guPh9u7VB",
    "microsoft_auth_config_id": "ac_M6tM9yS3Oq7L",
    "accounts": [],
    "table_initialized": False,
    "loaded_from_cloud": False,
    "messages_cache": {},  # key: f"{account_id}:{folder}:{q}" -> {"ts": float, "messages": list}
    "inbox_snapshots": {},  # key: f"{account_id}:{folder}" -> {"ts": float, "messages": list, "next_page_token": str, "result_size_estimate": int}
    "rate_limit_until": {},  # conn_id -> {"until_ts": float, "retry_after_iso": str, "manila_str": str}
    "realtime_events": [],  # ring buffer of newest incoming email notifications
    "realtime_seq": 0,
    "seen_message_ids_by_account": {},  # account_id -> set of seen message IDs
    "webhook_hits_count": 0,
    "last_webhook_received_at": "",
    "triggers_enabled_accounts": set()
}
EMAIL_HUB_LOCK = threading.Lock()


def _is_placeholder_connected_email(em: Any) -> bool:
    """
    Returns True if an email string is empty, lacks '@', or is a fallback placeholder
    like 'gmail_connected_0Pyole@connected.account', 'google_calendar_9uipjg@connected.account',
    or a Google group/holiday calendar ID ('...calendar.google.com').
    """
    clean = str(em or "").strip().lower()
    if not clean or "@" not in clean:
        return True
    if (
        clean.endswith("@connected.account")
        or clean.endswith("@connected.local")
        or clean.endswith("calendar.google.com")
    ):
        return True
    if (
        clean.startswith("gmail_connected_")
        or clean.startswith("microsoft_connected_")
        or re.match(r"^(?:google_calendar|outlook_calendar|zoom)_[a-z0-9]+@connected\.", clean)
    ):
        return True
    return False


def _extract_email_from_composio_item(item: dict) -> Tuple[str, str]:
    """
    Extracts the real authenticated email address and display name directly from a Composio
    connected_account object (`item["data"]["displayName"]`, `email`, `userPrincipalName`, etc.)
    BEFORE making any external Gmail/Microsoft/Google Calendar API call.
    This guarantees that even when an API is temporarily rate-limited (HTTP 429),
    connecting or reconnecting an account still resolves the real email address!
    """
    if not isinstance(item, dict):
        return ("", "")
    data_obj = item.get("data") if isinstance(item.get("data"), dict) else {}
    state_val = ((item.get("state") or {}).get("val") or {}) if isinstance(item.get("state"), dict) else {}
    params_obj = item.get("params") if isinstance(item.get("params"), dict) else {}
    conn_params = item.get("connectionParams") if isinstance(item.get("connectionParams"), dict) else {}
    member_obj = item.get("member") if isinstance(item.get("member"), dict) else {}

    candidate_fields = [
        data_obj.get("email"),
        data_obj.get("emailAddress"),
        data_obj.get("userPrincipalName"),
        data_obj.get("mail"),
        data_obj.get("displayName"),
        data_obj.get("id"),
        item.get("alias"),
        item.get("email"),
        state_val.get("email"),
        state_val.get("emailAddress"),
        state_val.get("userPrincipalName"),
        state_val.get("displayName"),
        params_obj.get("email"),
        params_obj.get("emailAddress"),
        conn_params.get("email"),
        conn_params.get("emailAddress"),
        member_obj.get("email"),
    ]
    resolved_email = ""
    for cand in candidate_fields:
        c_str = str(cand or "").strip()
        if c_str and "@" in c_str and not _is_placeholder_connected_email(c_str):
            m = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", c_str)
            if m and not _is_placeholder_connected_email(m.group(1)):
                resolved_email = m.group(1).strip().lower()
                break

    raw_disp = str(
        data_obj.get("name")
        or data_obj.get("displayName")
        or state_val.get("name")
        or state_val.get("displayName")
        or ""
    ).strip()
    if raw_disp and "@" in raw_disp:
        raw_disp = raw_disp.split("@")[0].strip()
    if not raw_disp and resolved_email:
        raw_disp = resolved_email.split("@")[0].strip()
    return (resolved_email, raw_disp)



def _ensure_email_accounts_table():
    if EMAIL_HUB_STATE.get("table_initialized"):
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_email_accounts (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    email_address TEXT NOT NULL,
                    display_name TEXT,
                    composio_connection_id TEXT,
                    composio_entity_id TEXT,
                    imap_host TEXT,
                    imap_port INTEGER DEFAULT 993,
                    smtp_host TEXT,
                    smtp_port INTEGER DEFAULT 465,
                    imap_password TEXT,
                    avatar_url TEXT,
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TEXT
                );
            """))
        EMAIL_HUB_STATE["table_initialized"] = True
    except Exception as e:
        print(f"[EmailHub] Table init warning: {e}")


def _save_email_hub_to_cloudinary():
    try:
        compact_snapshots = {}
        for snap_key, snap_val in list((EMAIL_HUB_STATE.get("inbox_snapshots") or {}).items()):
            if isinstance(snap_val, dict) and snap_val.get("messages"):
                compact_snapshots[snap_key] = {
                    "ts": snap_val.get("ts", time.time()),
                    "messages": list(snap_val.get("messages") or [])[:25],
                    "next_page_token": snap_val.get("next_page_token", ""),
                    "result_size_estimate": snap_val.get("result_size_estimate", 0)
                }
        payload = {
            "composio_api_key": EMAIL_HUB_STATE.get("composio_api_key") or DEFAULT_COMPOSIO_API_KEY,
            "composio_webhook_url": EMAIL_HUB_STATE.get("composio_webhook_url") or DEFAULT_COMPOSIO_WEBHOOK_URL,
            "composio_webhook_secret": EMAIL_HUB_STATE.get("composio_webhook_secret") or DEFAULT_COMPOSIO_WEBHOOK_SECRET,
            "gmail_auth_config_id": EMAIL_HUB_STATE.get("gmail_auth_config_id") or "",
            "microsoft_auth_config_id": EMAIL_HUB_STATE.get("microsoft_auth_config_id") or "",
            "accounts": EMAIL_HUB_STATE.get("accounts") or [],
            "inbox_snapshots": compact_snapshots,
            "updated_at": datetime.now(MANILA_TZ).isoformat()
        }
        raw_bytes = json.dumps(payload, indent=2).encode("utf-8")
        cloudinary.uploader.upload(
            io.BytesIO(raw_bytes),
            resource_type="raw",
            public_id=EMAIL_CLOUDINARY_PUBLIC_ID,
            overwrite=True,
            invalidate=True
        )
    except Exception as e:
        print(f"[EmailHub] Cloudinary backup warning: {e}")


def _load_email_hub_state(force_cloud: bool = False):
    _ensure_email_accounts_table()
    with EMAIL_HUB_LOCK:
        if EMAIL_HUB_STATE["loaded_from_cloud"] and not force_cloud:
            return EMAIL_HUB_STATE

    # 1. Load from DB using SQLAlchemy db_engine
    db_accounts = []
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, provider, email_address, display_name, composio_connection_id,
                       composio_entity_id, imap_host, imap_port, smtp_host, smtp_port,
                       imap_password, avatar_url, status, created_at
                FROM glennbot_email_accounts
                ORDER BY created_at DESC
            """)).mappings().all()
            for r in rows:
                db_accounts.append({
                    "id": str(r.get("id") or ""),
                    "provider": str(r.get("provider") or "gmail").lower(),
                    "email_address": str(r.get("email_address") or ""),
                    "display_name": str(r.get("display_name") or r.get("email_address") or ""),
                    "composio_connection_id": str(r.get("composio_connection_id") or ""),
                    "composio_entity_id": str(r.get("composio_entity_id") or "glennbot_email_user"),
                    "imap_host": str(r.get("imap_host") or ""),
                    "imap_port": int(r.get("imap_port") or 993),
                    "smtp_host": str(r.get("smtp_host") or ""),
                    "smtp_port": int(r.get("smtp_port") or 465),
                    "imap_password": str(r.get("imap_password") or ""),
                    "avatar_url": str(r.get("avatar_url") or ""),
                    "status": str(r.get("status") or "ACTIVE"),
                    "created_at": str(r.get("created_at") or "")
                })
    except Exception as e:
        print(f"[EmailHub] DB read warning: {e}")

    # 2. Load from Cloudinary if DB is empty or force_cloud
    cloud_accounts = []
    try:
        res_info = cloudinary.api.resource(EMAIL_CLOUDINARY_PUBLIC_ID, resource_type="raw")
        sec_url = res_info.get("secure_url")
        if sec_url:
            r = HTTP_SESSION.get(f"{sec_url}?_t={int(time.time())}", timeout=10)
            if r.status_code == 200:
                c_data = r.json()
                env_comp_key = os.getenv("COMPOSIO_API_KEY", "").strip()
                if env_comp_key:
                    EMAIL_HUB_STATE["composio_api_key"] = env_comp_key
                elif c_data.get("composio_api_key"):
                    EMAIL_HUB_STATE["composio_api_key"] = str(c_data["composio_api_key"]).strip()
                if c_data.get("composio_webhook_url"):
                    EMAIL_HUB_STATE["composio_webhook_url"] = str(c_data["composio_webhook_url"]).strip()
                if c_data.get("composio_webhook_secret"):
                    EMAIL_HUB_STATE["composio_webhook_secret"] = str(c_data["composio_webhook_secret"]).strip()
                if c_data.get("gmail_auth_config_id"):
                    EMAIL_HUB_STATE["gmail_auth_config_id"] = str(c_data["gmail_auth_config_id"]).strip()
                if c_data.get("microsoft_auth_config_id"):
                    EMAIL_HUB_STATE["microsoft_auth_config_id"] = str(c_data["microsoft_auth_config_id"]).strip()
                if isinstance(c_data.get("accounts"), list):
                    cloud_accounts = c_data["accounts"]
                if isinstance(c_data.get("inbox_snapshots"), dict):
                    with EMAIL_HUB_LOCK:
                        for sk, sv in c_data["inbox_snapshots"].items():
                            if isinstance(sv, dict) and sv.get("messages") and sk not in EMAIL_HUB_STATE["inbox_snapshots"]:
                                EMAIL_HUB_STATE["inbox_snapshots"][sk] = sv
    except Exception:
        pass

    # Deduplicate by email_address (case-insensitive) and prefer real email addresses over @connected.account placeholders
    merged_by_email: Dict[str, Dict[str, Any]] = {}
    duplicate_ids_to_prune: List[str] = []
    for acc in db_accounts + cloud_accounts:
        acc_id = str(acc.get("id") or "").strip()
        if not acc_id:
            continue
        em_key = str(acc.get("email_address") or "").strip().lower()
        is_placeholder = _is_placeholder_connected_email(em_key)
        dedup_key = em_key if not is_placeholder else acc_id
        if dedup_key in merged_by_email:
            prev_acc = merged_by_email[dedup_key]
            prev_em = str(prev_acc.get("email_address") or "").strip().lower()
            prev_is_placeholder = _is_placeholder_connected_email(prev_em)
            if not prev_is_placeholder and is_placeholder:
                continue
            prev_id = str(prev_acc.get("id") or "").strip()
            if prev_id and prev_id != acc_id:
                duplicate_ids_to_prune.append(prev_id)
        merged_by_email[dedup_key] = acc

    if duplicate_ids_to_prune:
        try:
            with db_engine.begin() as conn:
                for dup_id in duplicate_ids_to_prune:
                    conn.execute(text("DELETE FROM glennbot_email_accounts WHERE id = :id"), {"id": dup_id})
        except Exception:
            pass

    merged_list = list(merged_by_email.values())
    with EMAIL_HUB_LOCK:
        EMAIL_HUB_STATE["accounts"] = merged_list
        EMAIL_HUB_STATE["loaded_from_cloud"] = True

    # Ensure DB has all merged accounts
    for acc in merged_list:
        _upsert_email_account_in_db(acc, sync_cloud=False)

    if any(_is_placeholder_connected_email(a.get("email_address")) for a in merged_list):
        try:
            _discover_composio_email_accounts()
        except Exception:
            pass

    return EMAIL_HUB_STATE


def _upsert_email_account_in_db(acc: dict, sync_cloud: bool = True):
    _ensure_email_accounts_table()
    em_clean = str(acc.get("email_address") or "").strip().lower()
    acc_id_clean = str(acc.get("id") or "").strip()

    # Remove any older duplicate rows with the same email_address but a different id so Gmail never duplicates
    stale_conn_ids_to_remove: List[str] = []
    if em_clean and not _is_placeholder_connected_email(em_clean):
        with EMAIL_HUB_LOCK:
            for existing_a in list(EMAIL_HUB_STATE.get("accounts") or []):
                ex_id = str(existing_a.get("id") or "").strip()
                ex_em = str(existing_a.get("email_address") or "").strip().lower()
                if ex_em == em_clean and ex_id != acc_id_clean:
                    old_cid = str(existing_a.get("composio_connection_id") or "").strip()
                    if old_cid and old_cid != str(acc.get("composio_connection_id") or "").strip():
                        stale_conn_ids_to_remove.append(old_cid)
        try:
            with db_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM glennbot_email_accounts WHERE LOWER(email_address) = :em AND id != :id"),
                    {"em": em_clean, "id": acc_id_clean}
                )
        except Exception:
            pass

    params = {
        "id": acc_id_clean,
        "provider": str(acc.get("provider") or "gmail").lower(),
        "email_address": str(acc.get("email_address") or ""),
        "display_name": str(acc.get("display_name") or acc.get("email_address") or ""),
        "composio_connection_id": str(acc.get("composio_connection_id") or ""),
        "composio_entity_id": str(acc.get("composio_entity_id") or "glennbot_email_user"),
        "imap_host": str(acc.get("imap_host") or ""),
        "imap_port": int(acc.get("imap_port") or 993),
        "smtp_host": str(acc.get("smtp_host") or ""),
        "smtp_port": int(acc.get("smtp_port") or 465),
        "imap_password": str(acc.get("imap_password") or ""),
        "avatar_url": str(acc.get("avatar_url") or ""),
        "status": str(acc.get("status") or "ACTIVE"),
        "created_at": str(acc.get("created_at") or datetime.now(MANILA_TZ).isoformat())
    }
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO glennbot_email_accounts
                (id, provider, email_address, display_name, composio_connection_id, composio_entity_id,
                 imap_host, imap_port, smtp_host, smtp_port, imap_password, avatar_url, status, created_at)
                VALUES (:id, :provider, :email_address, :display_name, :composio_connection_id, :composio_entity_id,
                        :imap_host, :imap_port, :smtp_host, :smtp_port, :imap_password, :avatar_url, :status, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    email_address = EXCLUDED.email_address,
                    display_name = EXCLUDED.display_name,
                    composio_connection_id = EXCLUDED.composio_connection_id,
                    composio_entity_id = EXCLUDED.composio_entity_id,
                    imap_host = EXCLUDED.imap_host,
                    imap_port = EXCLUDED.imap_port,
                    smtp_host = EXCLUDED.smtp_host,
                    smtp_port = EXCLUDED.smtp_port,
                    imap_password = EXCLUDED.imap_password,
                    avatar_url = EXCLUDED.avatar_url,
                    status = EXCLUDED.status
            """), params)
    except Exception as e:
        print(f"[EmailHub] Upsert warning: {e}")

    with EMAIL_HUB_LOCK:
        existing = [
            a for a in EMAIL_HUB_STATE["accounts"]
            if str(a.get("id")) != acc_id_clean
            and (
                _is_placeholder_connected_email(em_clean)
                or str(a.get("email_address") or "").strip().lower() != em_clean
            )
        ]
        existing.insert(0, acc)
        EMAIL_HUB_STATE["accounts"] = existing

    if stale_conn_ids_to_remove:
        def _cleanup_stale_conns(cids: List[str]):
            headers = _get_composio_headers()
            for cid in cids:
                try:
                    HTTP_SESSION.delete(f"{COMPOSIO_BASE_URL}/connected_accounts/{cid}", headers=headers, timeout=10)
                except Exception:
                    pass
        threading.Thread(target=_cleanup_stale_conns, args=(stale_conn_ids_to_remove,), daemon=True).start()

    if sync_cloud:
        threading.Thread(target=_save_email_hub_to_cloudinary, daemon=True).start()


def _get_composio_headers():
    try:
        load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)
    except Exception:
        pass
    env_key = (os.getenv("COMPOSIO_API_KEY") or "").strip()
    api_key = (env_key or EMAIL_HUB_STATE.get("composio_api_key") or DEFAULT_COMPOSIO_API_KEY).strip()
    if env_key and EMAIL_HUB_STATE.get("composio_api_key") != env_key:
        EMAIL_HUB_STATE["composio_api_key"] = env_key
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GlennBot/3.0"
    }


def _get_or_create_composio_auth_config_id(provider: str, force_lookup: bool = False) -> str:
    """
    Finds or creates a Composio Managed OAuth2 auth_config_id for 'gmail' or 'microsoft' (toolkit 'outlook').
    """
    clean_p = provider.strip().lower()
    cached_id = (
        EMAIL_HUB_STATE.get("gmail_auth_config_id")
        if clean_p == "gmail"
        else EMAIL_HUB_STATE.get("microsoft_auth_config_id")
    )
    if cached_id and not force_lookup:
        return str(cached_id).strip()

    toolkit_slug = "gmail" if clean_p == "gmail" else "outlook"
    headers = _get_composio_headers()

    # 1. List existing auth configs on this API key
    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/auth_configs", headers=headers, timeout=15)
        if r.status_code == 200:
            items = r.json().get("items") or []
            for item in items:
                tk = (item.get("toolkit") or {}).get("slug", "").lower()
                scheme = str(item.get("auth_scheme") or "").upper()
                if tk == toolkit_slug and ("OAUTH" in scheme or not scheme):
                    found_id = str(item.get("id") or "").strip()
                    if found_id:
                        if clean_p == "gmail":
                            EMAIL_HUB_STATE["gmail_auth_config_id"] = found_id
                        else:
                            EMAIL_HUB_STATE["microsoft_auth_config_id"] = found_id
                        return found_id
    except Exception as e:
        print(f"[EmailHub] List auth_configs error: {e}")

    # 2. Create a new Composio Managed OAuth2 Auth Config if not found
    try:
        create_payload = {
            "toolkit": {"slug": toolkit_slug},
            "auth_config": {
                "type": "use_composio_managed_auth",
                "name": f"GlennBot {toolkit_slug.capitalize()} OAuth2"
            }
        }
        r_create = HTTP_SESSION.post(
            f"{COMPOSIO_BASE_URL}/auth_configs",
            headers=headers,
            json=create_payload,
            timeout=15
        )
        if r_create.status_code in (200, 201):
            c_json = r_create.json()
            ac_obj = c_json.get("auth_config") or c_json
            new_id = str(ac_obj.get("id") or "").strip()
            if new_id:
                if clean_p == "gmail":
                    EMAIL_HUB_STATE["gmail_auth_config_id"] = new_id
                else:
                    EMAIL_HUB_STATE["microsoft_auth_config_id"] = new_id
                return new_id
    except Exception as e:
        print(f"[EmailHub] Create auth_config error: {e}")

    return str(cached_id or "")


def _get_account_rate_limit_info(connected_account_id: str) -> Optional[Dict[str, Any]]:
    """
    Returns active Gmail/Outlook 429 cooldown info for `connected_account_id` if still in cooldown,
    or None if the account is clear to call the API.
    """
    cid = str(connected_account_id or "").strip()
    if not cid:
        return None
    rl_map = EMAIL_HUB_STATE.get("rate_limit_until") or {}
    info = rl_map.get(cid)
    if not info:
        return None
    if time.time() >= float(info.get("until_ts") or 0.0):
        rl_map.pop(cid, None)
        return None
    return info


def _record_account_rate_limit_from_error(connected_account_id: str, err_text: str) -> Dict[str, Any]:
    """
    Parses Google Gmail API's `Retry after YYYY-MM-DDTHH:MM:SS.sssZ` timestamp when a 429 occurs,
    and locks out further Gmail API calls for this `connected_account_id` until that exact time
    (because hitting Gmail API while in a 429 window resets Google's 15-minute penalty timer!).
    """
    cid = str(connected_account_id or "").strip()
    now_ts = time.time()
    until_ts = now_ts + 120.0
    retry_iso = ""
    m = re.search(r"Retry after\s+([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z)", str(err_text or ""), re.I)
    if m:
        retry_iso = m.group(1)
        try:
            dt_utc = datetime.fromisoformat(retry_iso.replace("Z", "+00:00"))
            parsed_ts = dt_utc.timestamp()
            if parsed_ts > now_ts:
                until_ts = parsed_ts + 3.0
        except Exception:
            pass
    try:
        manila_dt = datetime.fromtimestamp(until_ts, tz=MANILA_TZ)
        manila_str = manila_dt.strftime("%I:%M:%S %p")
    except Exception:
        manila_str = "a few minutes"

    info = {
        "until_ts": until_ts,
        "retry_after_iso": retry_iso,
        "manila_str": manila_str
    }
    if cid:
        EMAIL_HUB_STATE.setdefault("rate_limit_until", {})[cid] = info
    return info


def _composio_execute_tool(tool_slug: str, connected_account_id: str, entity_id: str, arguments: dict) -> dict:
    """
    Executes a Composio v3 tool for a specific connected_account_id and entity_id.
    Automatically enforces Gmail 429 rate-limit cooldown so Google's 15-minute Retry-After
    timer is never extended by background polling.
    For non-Gmail tools (such as Zoom), rate limits are scoped per tool_slug (`cid::tool_slug`)
    so a 429 on `ZOOM_LIST_MEETINGS` never blocks `ZOOM_CREATE_A_MEETING` or `ZOOM_GET_A_MEETING`!
    """
    cid = str(connected_account_id or "").strip()
    slug_upper = str(tool_slug or "").strip().upper()
    rl_key = cid if slug_upper.startswith("GMAIL_") else f"{cid}::{slug_upper}"
    active_rl = _get_account_rate_limit_info(rl_key)
    if active_rl:
        rem_sec = max(1, int(float(active_rl.get("until_ts") or 0) - time.time()))
        return {
            "successful": False,
            "rate_limited": True,
            "retry_after_seconds": rem_sec,
            "retry_after_manila": active_rl.get("manila_str", ""),
            "error": f"API rate-limit cooldown active for {slug_upper} (resumes at {active_rl.get('manila_str')} Manila time, {rem_sec}s remaining)."
        }

    headers = _get_composio_headers()
    clean_entity = (entity_id or "glennbot_email_user").strip()
    body = {
        "connected_account_id": cid,
        "entity_id": clean_entity,
        "user_id": clean_entity,
        "arguments": arguments or {}
    }
    r = HTTP_SESSION.post(
        f"{COMPOSIO_BASE_URL}/tools/execute/{tool_slug}",
        headers=headers,
        json=body,
        timeout=25
    )
    try:
        res_json = r.json()
    except Exception:
        res_json = {"successful": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}

    raw_dump = json.dumps(res_json) if isinstance(res_json, dict) else str(res_json)
    if (
        cid
        and ("ActionExecute_ConnectedAccountEntityIdMismatch" in raw_dump or "Connected account user ID does not match" in raw_dump)
    ):
        try:
            r_conn = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts/{cid}", headers=headers, timeout=12)
            if r_conn.status_code == 200:
                c_data = r_conn.json()
                true_uid = str(c_data.get("user_id") or c_data.get("entity_id") or "").strip()
                if true_uid and true_uid != clean_entity:
                    body["entity_id"] = true_uid
                    body["user_id"] = true_uid
                    r = HTTP_SESSION.post(
                        f"{COMPOSIO_BASE_URL}/tools/execute/{tool_slug}",
                        headers=headers,
                        json=body,
                        timeout=25
                    )
                    res_json = r.json()
                    raw_dump = json.dumps(res_json) if isinstance(res_json, dict) else str(res_json)
        except Exception:
            pass

    if "429" in raw_dump and (
        "Too Many Requests" in raw_dump
        or "rateLimitExceeded" in raw_dump
        or "User-rate limit exceeded" in raw_dump
        or "maximum daily rate limit" in raw_dump
    ):
        rl_info = _record_account_rate_limit_from_error(rl_key, raw_dump)
        rem_sec = max(1, int(float(rl_info.get("until_ts") or 0) - time.time()))
        if isinstance(res_json, dict):
            res_json["successful"] = False
            res_json["rate_limited"] = True
            res_json["retry_after_seconds"] = rem_sec
            res_json["retry_after_manila"] = rl_info.get("manila_str", "")
    return res_json


def _composio_execute_proxy(
    connected_account_id: str,
    entity_id: str,
    endpoint: str,
    method: str = "GET",
    body: Optional[dict] = None
) -> dict:
    """
    Executes a native REST API call (PATCH, DELETE, POST, GET) directly against the provider's API
    (Zoom /v2, Google Calendar /calendar/v3, Microsoft Graph /v1.0) using Composio's server-side
    unredacted OAuth2 token via `POST /api/v3/tools/execute/proxy`.
    Automatically heals `user_id` if an entity mismatch occurs.
    """
    cid = str(connected_account_id or "").strip()
    if not cid:
        return {"successful": False, "status": 400, "error": "Missing connected_account_id"}
    headers = _get_composio_headers()
    clean_entity = str(entity_id or "glennbot_calendar_user").strip()
    payload: Dict[str, Any] = {
        "connected_account_id": cid,
        "user_id": clean_entity,
        "endpoint": endpoint,
        "method": str(method or "GET").upper()
    }
    if body is not None:
        payload["body"] = body

    try:
        r = HTTP_SESSION.post(
            f"{COMPOSIO_BASE_URL}/tools/execute/proxy",
            headers=headers,
            json=payload,
            timeout=25
        )
        res_json = r.json() if r.content else {}
        raw_dump = json.dumps(res_json) if isinstance(res_json, dict) else str(res_json)
        if (
            r.status_code == 400
            and ("ExternalProxy_UserIdRequired" in raw_dump or "ConnectedAccountEntityIdMismatch" in raw_dump or "does not match" in raw_dump)
        ):
            r_conn = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts/{cid}", headers=headers, timeout=12)
            if r_conn.status_code == 200:
                true_uid = str((r_conn.json() or {}).get("user_id") or "").strip()
                if true_uid:
                    payload["user_id"] = true_uid
                    r = HTTP_SESSION.post(
                        f"{COMPOSIO_BASE_URL}/tools/execute/proxy",
                        headers=headers,
                        json=payload,
                        timeout=25
                    )
                    res_json = r.json() if r.content else {}
        proxy_status = int(res_json.get("status") or r.status_code or 0) if isinstance(res_json, dict) else r.status_code
        ok = (200 <= r.status_code < 300) and (200 <= proxy_status < 300)
        return {
            "successful": ok,
            "status": proxy_status,
            "http_status": r.status_code,
            "data": res_json.get("data") if isinstance(res_json, dict) else res_json
        }
    except Exception as e:
        return {"successful": False, "status": 500, "error": str(e)}



def _discover_composio_email_accounts() -> list:
    """
    Polls Composio /api/v3/connected_accounts, finds ACTIVE Gmail and Outlook connections,
    extracts their real email addresses directly from `item["data"]["displayName"]` first
    (with GMAIL_GET_PROFILE / OUTLOOK_OUTLOOK_GET_PROFILE as fallback), heals any
    `@connected.account` placeholders, and cleans up stale EXPIRED/FAILED connections.
    """
    _load_email_hub_state()
    headers = _get_composio_headers()
    discovered = []
    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts", headers=headers, timeout=15)
        if r.status_code != 200:
            return EMAIL_HUB_STATE["accounts"]
        items = r.json().get("items") or []
    except Exception as e:
        print(f"[EmailHub] Discover connected_accounts error: {e}")
        return EMAIL_HUB_STATE["accounts"]

    existing_by_conn_id = {
        str(a.get("composio_connection_id") or ""): a
        for a in EMAIL_HUB_STATE["accounts"]
        if a.get("composio_connection_id")
    }

    stale_expired_cids: List[str] = []
    now_epoch = time.time()

    for item in items:
        status = str(item.get("status") or "").upper()
        conn_id = str(item.get("id") or "").strip()
        tk_slug = str((item.get("toolkit") or {}).get("slug") or "").lower()
        if not conn_id or tk_slug not in ("gmail", "outlook"):
            continue

        if status in ("EXPIRED", "FAILED"):
            stale_expired_cids.append(conn_id)
            continue
        if status == "INITIALIZING":
            created_str = str(item.get("created_at") or item.get("createdAt") or "")
            if created_str:
                try:
                    c_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if (now_epoch - c_dt.timestamp()) > 900:
                        stale_expired_cids.append(conn_id)
                except Exception:
                    pass
            continue
        if status != "ACTIVE":
            continue

        provider = "gmail" if tk_slug == "gmail" else "microsoft"
        entity_id = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "glennbot_email_user").strip()

        if entity_id.startswith(("glennbot_admin_oauth_", "glennbot_gcontacts_")):
            continue

        # 1. Extract email directly from Composio item metadata (`item["data"]["displayName"]`) FIRST!
        meta_email, meta_display = _extract_email_from_composio_item(item)

        # 2. Check if already in EMAIL_HUB_STATE with a real (non-placeholder) email
        if conn_id in existing_by_conn_id:
            ex = existing_by_conn_id[conn_id]
            ex_email = str(ex.get("email_address") or "").strip()
            if not _is_placeholder_connected_email(ex_email):
                discovered.append(ex)
                continue
            if meta_email:
                ex["email_address"] = meta_email
                ex["display_name"] = meta_display or meta_email.split("@")[0]
                _upsert_email_account_in_db(ex, sync_cloud=True)
                discovered.append(ex)
                continue

        email_addr = meta_email
        display_name = meta_display

        # 3. Only call GMAIL_GET_PROFILE / OUTLOOK_OUTLOOK_GET_PROFILE if Composio metadata didn't already have the email
        if not email_addr:
            if provider == "gmail":
                prof_res = _composio_execute_tool("GMAIL_GET_PROFILE", conn_id, entity_id, {"user_id": "me"})
                data_obj = prof_res.get("data") or {}
                if isinstance(data_obj, dict):
                    resp_data = data_obj.get("response_data") or data_obj
                    if isinstance(resp_data, dict):
                        email_addr = str(resp_data.get("emailAddress") or resp_data.get("email") or "").strip().lower()
            else:
                prof_res = _composio_execute_tool("OUTLOOK_OUTLOOK_GET_PROFILE", conn_id, entity_id, {"user_id": "me"})
                data_obj = prof_res.get("data") or {}
                if isinstance(data_obj, dict):
                    resp_data = data_obj.get("response_data") or data_obj
                    if isinstance(resp_data, dict):
                        email_addr = str(resp_data.get("mail") or resp_data.get("userPrincipalName") or resp_data.get("emailAddress") or "").strip().lower()
                        display_name = str(resp_data.get("displayName") or "").strip()

        if not email_addr:
            short_id = conn_id[-6:] if len(conn_id) >= 6 else conn_id
            email_addr = f"{provider}_connected_{short_id}@connected.account"

        if not display_name:
            display_name = email_addr.split("@")[0] if "@" in email_addr else email_addr

        acc_record = {
            "id": f"email_{provider}_{conn_id}",
            "provider": provider,
            "email_address": email_addr,
            "display_name": display_name,
            "composio_connection_id": conn_id,
            "composio_entity_id": entity_id,
            "imap_host": "",
            "imap_port": 993,
            "smtp_host": "",
            "smtp_port": 465,
            "imap_password": "",
            "avatar_url": "",
            "status": "ACTIVE",
            "created_at": str(item.get("created_at") or datetime.now(MANILA_TZ).isoformat())
        }
        _upsert_email_account_in_db(acc_record, sync_cloud=True)
        discovered.append(acc_record)

    if stale_expired_cids:
        def _prune_expired(cids: List[str]):
            for cid_exp in cids:
                try:
                    HTTP_SESSION.delete(f"{COMPOSIO_BASE_URL}/connected_accounts/{cid_exp}", headers=headers, timeout=10)
                except Exception:
                    pass
        threading.Thread(target=_prune_expired, args=(stale_expired_cids,), daemon=True).start()

    return EMAIL_HUB_STATE["accounts"]


@router.get("/api/email/config")
async def api_get_email_config():
    await run_in_threadpool(_load_email_hub_state)
    key = EMAIL_HUB_STATE.get("composio_api_key") or DEFAULT_COMPOSIO_API_KEY
    masked = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else key
    return {
        "status": "success",
        "composio_api_key": key,
        "masked_key": masked,
        "gmail_auth_config_id": EMAIL_HUB_STATE.get("gmail_auth_config_id") or "ac_Nk5guPh9u7VB",
        "microsoft_auth_config_id": EMAIL_HUB_STATE.get("microsoft_auth_config_id") or "ac_M6tM9yS3Oq7L"
    }


@router.post("/api/email/config")
async def api_save_email_config(request: Request):
    body = await request.json()
    new_key = str(body.get("composio_api_key") or "").strip()
    if not new_key:
        return JSONResponse({"status": "error", "message": "Composio API Key cannot be empty."}, status_code=400)
    def _save_and_verify():
        _load_email_hub_state()
        with EMAIL_HUB_LOCK:
            EMAIL_HUB_STATE["composio_api_key"] = new_key
        g_ac = _get_or_create_composio_auth_config_id("gmail", force_lookup=True)
        m_ac = _get_or_create_composio_auth_config_id("microsoft", force_lookup=True)
        _save_email_hub_to_cloudinary()
        return g_ac, m_ac
    gmail_ac, ms_ac = await run_in_threadpool(_save_and_verify)
    return {
        "status": "success",
        "message": "Composio API Key saved and verified!",
        "composio_api_key": new_key,
        "gmail_auth_config_id": gmail_ac,
        "microsoft_auth_config_id": ms_ac
    }


def _create_composio_oauth_link_for_provider(provider: str, request: Request) -> Dict[str, Any]:
    """
    Internal helper that generates the Composio v3 OAuth2 link for Gmail or Microsoft Outlook.
    Automatically retries with a fresh auth_config lookup if the cached auth_config_id belongs to a different key.
    """
    _load_email_hub_state()
    clean_p = str(provider or "gmail").strip().lower()
    if clean_p not in ("gmail", "microsoft"):
        return {"status": "error", "message": f"Unsupported OAuth email provider: {clean_p}"}

    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:5001"
    proto = request.headers.get("x-forwarded-proto") or ("https" if ("ngrok" in host or "onrender" in host or "run.app" in host) else "http")
    base_url = f"{proto}://{host}"
    callback_url = f"{base_url}/api/oauth/email/callback?provider={clean_p}"
    entity_id = f"glennbot_{clean_p}_{int(time.time())}"
    headers = _get_composio_headers()

    for force_flag in (False, True):
        auth_config_id = _get_or_create_composio_auth_config_id(clean_p, force_lookup=force_flag)
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
                return {
                    "status": "success",
                    "provider": clean_p,
                    "auth_url": redirect_url,
                    "connected_account_id": conn_id,
                    "entity_id": entity_id,
                    "auth_config_id": auth_config_id
                }
            err_msg = (data.get("error") or {}).get("message") or data.get("message") or f"HTTP {r.status_code}"
            if force_flag:
                return {"status": "error", "message": f"OAuth Link Error: {err_msg}"}
        except Exception as e:
            if force_flag:
                return {"status": "error", "message": f"Failed to start {clean_p} OAuth popup: {e}"}

    return {
        "status": "error",
        "message": f"Could not resolve OAuth configuration for {clean_p}. Please verify your environment configuration."
    }


@router.post("/api/oauth/email/start")
async def api_start_email_oauth(request: Request):
    """
    Generates an OAuth2 Popup Redirect URL for Gmail or Microsoft Outlook.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    provider = str(body.get("provider") or request.query_params.get("provider") or "gmail").strip().lower()
    res = await run_in_threadpool(lambda: _create_composio_oauth_link_for_provider(provider, request))
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.get("/api/oauth/email/redirect", response_class=HTMLResponse)
async def api_redirect_email_oauth(request: Request, provider: str = "gmail"):
    """
    Synchronous popup target page that immediately redirects the newly opened popup window
    to the OAuth2 authorization screen (prevents browser popup blockers 100%).
    """
    clean_p = str(provider or "gmail").strip().lower()
    res = await run_in_threadpool(lambda: _create_composio_oauth_link_for_provider(clean_p, request))
    if res.get("status") == "success" and res.get("auth_url"):
        auth_url = res["auth_url"]
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Connecting {clean_p.capitalize()}...</title>
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
            max-width: 390px;
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
        <div class="title">Connecting to {clean_p.capitalize()}...</div>
        <p class="sub">Redirecting you to the secure OAuth2 login page...</p>
        <a href="{auth_url}">Click here if not redirected automatically</a>
    </div>
    <script>
        window.location.replace({json.dumps(auth_url)});
    </script>
</body>
</html>"""
        return HTMLResponse(content=html)

    err_msg = res.get("message") or "Could not start OAuth session."
    err_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>OAuth Error</title></head>
<body style="background:#050b14;color:#f43f5e;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;">
    <div style="padding:28px;border:1px solid #f43f5e;border-radius:16px;background:#0f172a;max-width:400px;">
        <h3 style="margin:0 0 10px 0;">Could Not Start {clean_p.capitalize()} OAuth</h3>
        <p style="color:#cbd5e1;font-size:13px;">{err_msg}</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=err_html, status_code=400)


@router.get("/api/oauth/email/callback", response_class=HTMLResponse)
async def api_email_oauth_callback(request: Request):
    """
    OAuth popup callback landing page. Automatically discovers the newly authorized
    Gmail / Microsoft account on Composio, notifies the opener window via postMessage,
    and closes the popup window.
    """
    provider = str(request.query_params.get("provider") or "gmail").strip().lower()
    try:
        await run_in_threadpool(_discover_composio_email_accounts)
    except Exception as e:
        print(f"[EmailHub] Callback discovery warning: {e}")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>GlennBot Email Connected</title>
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
            background: rgba(15, 23, 42, 0.92);
            border: 1px solid rgba(0, 240, 255, 0.5);
            border-radius: 16px;
            padding: 32px 28px;
            max-width: 380px;
            box-shadow: 0 0 35px rgba(0, 240, 255, 0.25);
        }}
        .title {{ color: #00f0ff; font-size: 18px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #94a3b8; font-size: 13px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="title">Email Account Connected!</div>
        <p class="sub">Syncing your {provider.capitalize()} inbox with GlennBot Automations. This window will close automatically...</p>
    </div>
    <script>
        try {{
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'GLENNBOT_EMAIL_OAUTH_DONE',
                    provider: '{provider}'
                }}, '*');
            }}
        }} catch (e) {{}}
        setTimeout(function() {{ window.close(); }}, 900);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/api/email/accounts")
async def api_get_email_accounts(discover: bool = False):
    def _load_and_maybe_discover():
        _load_email_hub_state()
        has_placeholder = any(
            _is_placeholder_connected_email(a.get("email_address"))
            for a in (EMAIL_HUB_STATE.get("accounts") or [])
        )
        if discover or has_placeholder:
            _discover_composio_email_accounts()
    await run_in_threadpool(_load_and_maybe_discover)
    accounts = EMAIL_HUB_STATE.get("accounts") or []
    # Mask IMAP password before returning to frontend
    safe_accounts = []
    for a in accounts:
        copy_a = dict(a)
        if copy_a.get("imap_password"):
            copy_a["imap_password"] = "••••••••"
        safe_accounts.append(copy_a)
    return {
        "status": "success",
        "accounts": safe_accounts,
        "count": len(safe_accounts)
    }


@router.get("/api/email/discover")
async def api_discover_email_accounts():
    accounts = await run_in_threadpool(_discover_composio_email_accounts)
    safe_accounts = []
    for a in accounts:
        copy_a = dict(a)
        if copy_a.get("imap_password"):
            copy_a["imap_password"] = "••••••••"
        safe_accounts.append(copy_a)
    return {
        "status": "success",
        "accounts": safe_accounts,
        "count": len(safe_accounts)
    }


@router.post("/api/email/imap/connect")
async def api_connect_imap_account(request: Request):
    """
    Verifies and saves a custom IMAP/SMTP email account (e.g. Hostinger, cPanel, Zoho, Yahoo, Custom Domain, or App Password).
    """
    body = await request.json()
    return await run_in_threadpool(lambda: _connect_imap_account_sync(body))


def _connect_imap_account_sync(body: Dict[str, Any]):
    _load_email_hub_state()
    email_address = str(body.get("email_address") or "").strip()
    display_name = str(body.get("display_name") or email_address.split("@")[0] or "").strip()
    password = str(body.get("password") or "").strip()
    imap_host = str(body.get("imap_host") or "").strip()
    imap_port = int(body.get("imap_port") or 993)
    smtp_host = str(body.get("smtp_host") or "").strip()
    smtp_port = int(body.get("smtp_port") or 465)

    if not email_address or not password or not imap_host or not smtp_host:
        return JSONResponse({
            "status": "error",
            "message": "Please fill in Email Address, Password / App Password, IMAP Host, and SMTP Host."
        }, status_code=400)

    # Test IMAP login
    try:
        imap_conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=12)
        imap_conn.login(email_address, password)
        imap_conn.logout()
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"IMAP Login Failed ({imap_host}:{imap_port}): {e}"
        }, status_code=400)

    acc_id = f"email_imap_{re.sub(r'[^a-zA-Z0-9]', '_', email_address.lower())}"
    acc_record = {
        "id": acc_id,
        "provider": "imap",
        "email_address": email_address,
        "display_name": display_name,
        "composio_connection_id": "",
        "composio_entity_id": "",
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "imap_password": password,
        "avatar_url": "",
        "status": "ACTIVE",
        "created_at": datetime.now(MANILA_TZ).isoformat()
    }
    _upsert_email_account_in_db(acc_record, sync_cloud=True)
    safe_record = dict(acc_record)
    safe_record["imap_password"] = "••••••••"
    return {
        "status": "success",
        "message": f"Connected IMAP/SMTP account {email_address}!",
        "account": safe_record
    }


@router.delete("/api/email/accounts/{account_id}")
async def api_delete_email_account(account_id: str):
    return await run_in_threadpool(lambda: _delete_email_account_sync(account_id))


def _delete_email_account_sync(account_id: str):
    _load_email_hub_state()
    clean_id = str(account_id or "").strip()
    target = None
    with EMAIL_HUB_LOCK:
        for a in EMAIL_HUB_STATE["accounts"]:
            if str(a.get("id")) == clean_id:
                target = a
                break
        EMAIL_HUB_STATE["accounts"] = [a for a in EMAIL_HUB_STATE["accounts"] if str(a.get("id")) != clean_id]

    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM glennbot_email_accounts WHERE id = :id"),
                {"id": clean_id}
            )
    except Exception as e:
        print(f"[EmailHub] Delete DB warning: {e}")

    # Also remove from Composio if it has a composio_connection_id
    if target and target.get("composio_connection_id"):
        try:
            headers = _get_composio_headers()
            HTTP_SESSION.delete(
                f"{COMPOSIO_BASE_URL}/connected_accounts/{target['composio_connection_id']}",
                headers=headers,
                timeout=10
            )
        except Exception:
            pass

    threading.Thread(target=_save_email_hub_to_cloudinary, daemon=True).start()
    return {"status": "success", "message": "Email account disconnected."}


def _decode_gmail_b64(data_str: str) -> str:
    if not data_str or not isinstance(data_str, str):
        return ""
    try:
        clean_b64 = data_str.strip().replace("-", "+").replace("_", "/")
        pad_len = (-len(clean_b64)) % 4
        if pad_len:
            clean_b64 += "=" * pad_len
        raw_bytes = base64.b64decode(clean_b64)
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_gmail_mime_parts(payload_obj: dict) -> tuple:
    """
    Recursively walks a Gmail MIME payload object to extract (plain_text, html_text).
    """
    if not isinstance(payload_obj, dict):
        return ("", "")
    plain_chunks = []
    html_chunks = []

    def _walk(part: dict):
        if not isinstance(part, dict):
            return
        mime_type = str(part.get("mimeType") or "").lower()
        body_obj = part.get("body") or {}
        b64_data = body_obj.get("data") if isinstance(body_obj, dict) else ""
        if b64_data:
            decoded = _decode_gmail_b64(str(b64_data))
            if decoded:
                if mime_type == "text/plain":
                    plain_chunks.append(decoded)
                elif mime_type == "text/html":
                    html_chunks.append(decoded)
        sub_parts = part.get("parts") or []
        if isinstance(sub_parts, list):
            for sp in sub_parts:
                _walk(sp)

    _walk(payload_obj)
    return ("\n".join(plain_chunks).strip(), "\n".join(html_chunks).strip())


def _looks_like_html_content(text_val: str) -> bool:
    if not text_val or not isinstance(text_val, str):
        return False
    sample = text_val[:2000].lower()
    html_markers = (
        "<!doctype html", "<html", "<head", "<body", "<table", "<div",
        "<style", "<p>", "<p ", "<br", "<a href=", "<img ", "<span", "<tr", "<td"
    )
    return any(marker in sample for marker in html_markers)


def _clean_email_html_to_text(raw_str: str) -> str:
    """
    Converts raw HTML or marketing email text into clean, human-readable plain text
    without <!DOCTYPE>, <style> blocks, HTML tags, entities, or tracking placeholders.
    """
    if not raw_str:
        return ""
    txt = str(raw_str)
    # 1. Strip <head>, <style>, <script>, <xml>, and HTML comments
    txt = re.sub(r"(?is)<head[^>]*>.*?</head>", " ", txt)
    txt = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", txt)
    txt = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", txt)
    txt = re.sub(r"(?is)<xml[^>]*>.*?</xml>", " ", txt)
    txt = re.sub(r"(?is)<!--.*?-->", " ", txt)
    txt = re.sub(r"(?is)<!doctype[^>]*>", " ", txt)

    # 2. Convert block tags and line breaks to newlines
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|blockquote|section|article|header|footer)>", "\n", txt)

    # 3. Strip all remaining HTML tags
    txt = re.sub(r"<[^>]+>", " ", txt)

    # 4. Unescape HTML entities (&amp;, &#39;, &nbsp;, etc.)
    try:
        txt = py_html.unescape(txt)
    except Exception:
        pass

    # 5. Strip invisible zero-width preheader padding characters (\u034f, \u200b, etc.)
    txt = re.sub(r"[\u034f\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060]+", "", txt)

    # 6. Strip marketing tracking placeholders & long bracketed tracking URLs
    txt = re.sub(r"%%[a-zA-Z0-9_]+%%", "", txt)
    txt = re.sub(r"https?://___MirrorURLMultiMid___\S*", "", txt)
    txt = re.sub(r"\[https?://[^\]]{45,}\]", "", txt)

    # 7. Normalize whitespace while preserving paragraph breaks
    lines = []
    for line in txt.splitlines():
        cleaned_line = re.sub(r"[ \t\r\f\v\u00a0]+", " ", line).strip()
        lines.append(cleaned_line)
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return joined


def _make_clean_email_snippet(raw_preview, clean_body_text: str) -> str:
    """
    Builds a clean 160-character single-line preview for the inbox list.
    Never returns raw HTML code or preheader filler dots.
    """
    preview_str = ""
    if isinstance(raw_preview, dict):
        preview_str = str(raw_preview.get("body") or raw_preview.get("snippet") or "").strip()
    elif raw_preview is not None and str(raw_preview).lower() != "none":
        preview_str = str(raw_preview).strip()

    cleaned_preview = _clean_email_html_to_text(preview_str)
    cleaned_preview = re.sub(r"^[\.\s•·\-_]+", "", cleaned_preview)
    cleaned_preview = re.sub(r"\s+", " ", cleaned_preview).strip()

    # Check if cleaned_preview has enough real words (not just empty preheader padding)
    alnum_count = len(re.sub(r"[^a-zA-Z0-9]", "", cleaned_preview))
    if alnum_count < 8 or _looks_like_html_content(cleaned_preview):
        fallback = re.sub(r"\s+", " ", clean_body_text or "").strip()
        fallback = re.sub(r"^[\.\s•·\-_]+", "", fallback).strip()
        return (fallback or cleaned_preview or "(No preview)")[:160]

    return cleaned_preview[:160]


from email.utils import parsedate_to_datetime as py_parsedate_to_datetime


def _parse_email_timestamp_and_manila_str(raw_date_str: str, internal_date_val=None) -> tuple:
    """
    Parses an email timestamp from Gmail internalDate (ms), ISO-8601 messageTimestamp, or RFC 2822 Date header.
    Returns (unix_timestamp_float, formatted_manila_str).
    """
    dt_obj = None

    # 1. Check numeric internalDate (epoch ms or seconds) first since it is 100% timezone-unambiguous
    if internal_date_val is not None:
        raw_num_str = str(internal_date_val).strip()
        if raw_num_str.isdigit():
            try:
                num_val = int(raw_num_str)
                if num_val > 100_000_000_000:
                    ts_sec = num_val / 1000.0
                elif num_val > 100_000_000:
                    ts_sec = float(num_val)
                else:
                    ts_sec = 0.0
                if ts_sec > 0:
                    dt_obj = datetime.fromtimestamp(ts_sec, tz=pytz.UTC)
            except Exception:
                dt_obj = None

    # 2. Parse string date if dt_obj not yet resolved
    s = str(raw_date_str or "").strip()
    if dt_obj is None and s:
        if s.isdigit():
            try:
                num_val = int(s)
                ts_sec = num_val / 1000.0 if num_val > 100_000_000_000 else float(num_val)
                dt_obj = datetime.fromtimestamp(ts_sec, tz=pytz.UTC)
            except Exception:
                dt_obj = None
        if dt_obj is None:
            try:
                iso_candidate = s.replace("Z", "+00:00")
                parsed_iso = datetime.fromisoformat(iso_candidate)
                if parsed_iso.tzinfo is None:
                    parsed_iso = pytz.UTC.localize(parsed_iso)
                dt_obj = parsed_iso
            except Exception:
                dt_obj = None
        if dt_obj is None:
            try:
                parsed_rfc = py_parsedate_to_datetime(s)
                if parsed_rfc is not None:
                    if parsed_rfc.tzinfo is None:
                        parsed_rfc = pytz.UTC.localize(parsed_rfc)
                    dt_obj = parsed_rfc
            except Exception:
                dt_obj = None

    if dt_obj is not None:
        try:
            manila_dt = dt_obj.astimezone(MANILA_TZ)
            ts_val = float(dt_obj.timestamp())
            formatted = manila_dt.strftime("%Y-%m-%d %I:%M %p")
            return (ts_val, formatted)
        except Exception:
            pass

    return (0.0, s[:19] if s else "")


def _extract_gmail_message_fields(raw_msg: dict, idx: int = 0) -> dict:
    """
    Normalizes a Gmail message object returned by Composio's GMAIL_FETCH_EMAILS tool.
    Extracts both rich `body_html` (for formatted email rendering) and clean `body` / `snippet`.
    """
    msg_id = str(raw_msg.get("messageId") or raw_msg.get("id") or f"gm_{idx}")
    thread_id = str(raw_msg.get("threadId") or msg_id)
    subject = str(raw_msg.get("subject") or "").strip()
    sender = str(raw_msg.get("sender") or raw_msg.get("from") or "").strip()
    to_rcpt = str(raw_msg.get("to") or raw_msg.get("recipient") or "").strip()
    cc_rcpt = str(raw_msg.get("cc") or "").strip()
    internal_date_raw = raw_msg.get("internalDate")
    date_str = str(raw_msg.get("messageTimestamp") or raw_msg.get("date") or internal_date_raw or "").strip()
    header_date_str = ""
    raw_msg_text = str(raw_msg.get("messageText") or raw_msg.get("body") or "").strip()

    payload = raw_msg.get("payload") or {}
    mime_plain, mime_html = ("", "")
    if isinstance(payload, dict):
        if not internal_date_raw and payload.get("internalDate"):
            internal_date_raw = payload.get("internalDate")
        mime_plain, mime_html = _extract_gmail_mime_parts(payload)
        headers = payload.get("headers") or []
        if isinstance(headers, list):
            for h in headers:
                if not isinstance(h, dict):
                    continue
                h_name = str(h.get("name") or "").lower()
                h_val = str(h.get("value") or "").strip()
                if h_name == "subject" and not subject:
                    subject = h_val
                elif h_name == "from" and not sender:
                    sender = h_val
                elif h_name == "to" and not to_rcpt:
                    to_rcpt = h_val
                elif h_name == "cc" and not cc_rcpt:
                    cc_rcpt = h_val
                elif h_name == "date":
                    header_date_str = h_val
                    if not date_str:
                        date_str = h_val

    ts_epoch, manila_display_date = _parse_email_timestamp_and_manila_str(
        date_str or header_date_str,
        internal_date_raw
    )
    if ts_epoch == 0.0 and header_date_str and header_date_str != date_str:
        ts_epoch, manila_display_date = _parse_email_timestamp_and_manila_str(header_date_str, internal_date_raw)

    # Determine rich HTML content vs clean plain-text content
    body_html = ""
    if mime_html:
        body_html = mime_html
    elif _looks_like_html_content(raw_msg_text):
        body_html = raw_msg_text

    if mime_plain and not _looks_like_html_content(mime_plain):
        clean_body_text = _clean_email_html_to_text(mime_plain)
    elif raw_msg_text:
        clean_body_text = _clean_email_html_to_text(raw_msg_text)
    elif body_html:
        clean_body_text = _clean_email_html_to_text(body_html)
    else:
        clean_body_text = ""

    raw_preview = raw_msg.get("snippet") if raw_msg.get("snippet") is not None else raw_msg.get("preview")
    clean_snippet = _make_clean_email_snippet(raw_preview, clean_body_text)

    if not subject:
        subject = "(No Subject)"
    if not clean_body_text:
        clean_body_text = clean_snippet or "(No message content)"

    label_ids = raw_msg.get("labelIds") or []
    is_unread = "UNREAD" in label_ids if isinstance(label_ids, list) else False

    # Parse sender display name & email address
    sender_name = sender
    sender_email = sender
    m = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>$', sender.strip())
    if m:
        sender_name = m.group(1).strip() or m.group(2).strip()
        sender_email = m.group(2).strip()

    att_list = raw_msg.get("attachmentList") or []
    attachments_meta = []
    seen_att_keys = set()
    if isinstance(att_list, list):
        for att in att_list:
            if isinstance(att, dict) and (att.get("filename") or att.get("name")):
                fname = str(att.get("filename") or att.get("name") or "attachment").strip()
                att_id = str(att.get("attachmentId") or att.get("id") or "").strip()
                dedup_k = f"{fname}:{att_id[:32]}"
                if dedup_k not in seen_att_keys:
                    seen_att_keys.add(dedup_k)
                    attachments_meta.append({
                        "filename": fname,
                        "mimeType": str(att.get("mimeType") or "application/octet-stream"),
                        "attachmentId": att_id,
                        "size": int(att.get("size") or 0)
                    })

    # Also walk payload.parts recursively to catch any attachments not in top-level attachmentList
    def _walk_att_parts(part_obj: dict):
        if not isinstance(part_obj, dict):
            return
        p_fname = str(part_obj.get("filename") or "").strip()
        p_body = part_obj.get("body") if isinstance(part_obj.get("body"), dict) else {}
        p_att_id = str(p_body.get("attachmentId") or "").strip()
        if p_fname and (p_att_id or p_body.get("data")):
            dedup_k = f"{p_fname}:{p_att_id[:32]}"
            if dedup_k not in seen_att_keys:
                seen_att_keys.add(dedup_k)
                attachments_meta.append({
                    "filename": p_fname,
                    "mimeType": str(part_obj.get("mimeType") or "application/octet-stream"),
                    "attachmentId": p_att_id,
                    "size": int(p_body.get("size") or 0)
                })
        for sub_p in (part_obj.get("parts") or []):
            _walk_att_parts(sub_p)

    if isinstance(payload, dict):
        _walk_att_parts(payload)

    return {
        "id": msg_id,
        "thread_id": thread_id,
        "subject": subject,
        "sender": sender,
        "sender_name": sender_name or "Unknown Sender",
        "sender_email": sender_email,
        "to": to_rcpt,
        "cc": cc_rcpt,
        "date": manila_display_date or date_str,
        "raw_date": date_str,
        "timestamp": ts_epoch,
        "snippet": clean_snippet,
        "body": clean_body_text,
        "body_html": body_html,
        "attachments": attachments_meta,
        "is_unread": is_unread,
        "labels": label_ids if isinstance(label_ids, list) else []
    }


def _decode_mime_words(raw_val: str) -> str:
    if not raw_val:
        return ""
    try:
        parts = py_decode_header(raw_val)
        out = []
        for content, enc in parts:
            if isinstance(content, bytes):
                out.append(content.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(str(content))
        return "".join(out)
    except Exception:
        return str(raw_val)


def _fetch_imap_folder_messages(acc: dict, folder: str = "inbox", query_str: str = "", page_token: str = "", max_results: int = 25) -> tuple:
    imap_host = acc.get("imap_host")
    imap_port = int(acc.get("imap_port") or 993)
    email_addr = acc.get("email_address")
    password = acc.get("imap_password")

    folder_map = {
        "inbox": "INBOX",
        "sent": "Sent",
        "drafts": "Drafts",
        "spam": "Junk",
        "trash": "Trash"
    }
    target_box = folder_map.get(folder.lower(), "INBOX")

    messages_out = []
    next_token = ""
    total_count = 0
    skip_offset = int(page_token) if str(page_token or "").isdigit() else 0

    imap_conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=15)
    try:
        imap_conn.login(email_addr, password)
        typ, _ = imap_conn.select(target_box, readonly=True)
        if typ != "OK":
            imap_conn.select("INBOX", readonly=True)

        typ, data = imap_conn.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return ([], "", 0)

        msg_nums = data[0].split()
        total_count = len(msg_nums)
        reversed_nums = list(reversed(msg_nums))
        latest_nums = reversed_nums[skip_offset: skip_offset + max_results]
        if skip_offset + max_results < total_count:
            next_token = str(skip_offset + max_results)

        for num in latest_nums:
            typ, msg_data = imap_conn.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            if not isinstance(raw_bytes, bytes):
                continue
            parsed = py_email.message_from_bytes(raw_bytes)
            subject = _decode_mime_words(parsed.get("Subject", "(No Subject)"))
            sender = _decode_mime_words(parsed.get("From", ""))
            to_rcpt = _decode_mime_words(parsed.get("To", ""))
            cc_rcpt = _decode_mime_words(parsed.get("Cc", ""))
            date_str = _decode_mime_words(parsed.get("Date", ""))
            ts_epoch, manila_display_date = _parse_email_timestamp_and_manila_str(date_str)
            msg_id = _decode_mime_words(parsed.get("Message-ID", num.decode("utf-8", errors="ignore")))

            plain_part_text = ""
            html_part_text = ""
            imap_attachments = []
            if parsed.is_multipart():
                for part_idx, part in enumerate(parsed.walk()):
                    ctype = part.get_content_type()
                    cdisp = str(part.get("Content-Disposition") or "")
                    raw_fname = part.get_filename()
                    if raw_fname or "attachment" in cdisp.lower():
                        decoded_fname = _decode_mime_words(raw_fname) if raw_fname else f"attachment_{part_idx}"
                        imap_attachments.append({
                            "filename": decoded_fname,
                            "mimeType": ctype or "application/octet-stream",
                            "attachmentId": f"imap_part_{part_idx}",
                            "size": 0
                        })
                        continue
                    payload_bytes = part.get_payload(decode=True)
                    if not payload_bytes:
                        continue
                    decoded_str = payload_bytes.decode(part.get_content_charset() or "utf-8", errors="replace")
                    if ctype == "text/plain" and not plain_part_text:
                        plain_part_text = decoded_str
                    elif ctype == "text/html" and not html_part_text:
                        html_part_text = decoded_str
            else:
                payload_bytes = parsed.get_payload(decode=True)
                if payload_bytes:
                    decoded_str = payload_bytes.decode(parsed.get_content_charset() or "utf-8", errors="replace")
                    if parsed.get_content_type() == "text/html" or _looks_like_html_content(decoded_str):
                        html_part_text = decoded_str
                    else:
                        plain_part_text = decoded_str

            body_text = _clean_email_html_to_text(plain_part_text or html_part_text)
            snippet = _make_clean_email_snippet("", body_text)
            if query_str:
                q_low = query_str.lower()
                if q_low not in subject.lower() and q_low not in sender.lower() and q_low not in body_text.lower():
                    continue

            sender_name = sender
            sender_email = sender
            m = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>$', sender.strip())
            if m:
                sender_name = m.group(1).strip() or m.group(2).strip()
                sender_email = m.group(2).strip()

            messages_out.append({
                "id": num.decode("utf-8", errors="ignore"),
                "thread_id": msg_id,
                "subject": subject or "(No Subject)",
                "sender": sender,
                "sender_name": sender_name or "Unknown Sender",
                "sender_email": sender_email,
                "to": to_rcpt,
                "cc": cc_rcpt,
                "date": manila_display_date or date_str,
                "raw_date": date_str,
                "timestamp": ts_epoch,
                "snippet": snippet or "(No preview)",
                "body": body_text or "(Empty email body)",
                "body_html": html_part_text,
                "attachments": imap_attachments,
                "is_unread": False,
                "labels": [folder.upper()]
            })
    finally:
        try:
            imap_conn.logout()
        except Exception:
            pass

    messages_out.sort(key=lambda m: float(m.get("timestamp") or 0.0), reverse=True)
    return (messages_out, next_token, total_count)


@router.get("/api/email/messages")
def api_get_single_account_emails(
    account_id: str,
    folder: str = "inbox",
    q: str = "",
    page_token: str = "",
    max_results: int = 25,
    force: bool = False
):
    """
    Strictly fetches emails for ONE selected email account at a time (never mixes multiple accounts).
    Supports pagination via `page_token` for loading older batches ("Load More Emails").
    """
    _load_email_hub_state()
    clean_acc_id = str(account_id or "").strip()
    if not clean_acc_id:
        return JSONResponse({"status": "error", "message": "account_id is required."}, status_code=400)

    target_acc = None
    for a in EMAIL_HUB_STATE["accounts"]:
        if str(a.get("id")) == clean_acc_id:
            target_acc = a
            break

    if not target_acc:
        # Try discovering once in case it was just connected
        _discover_composio_email_accounts()
        for a in EMAIL_HUB_STATE["accounts"]:
            if str(a.get("id")) == clean_acc_id:
                target_acc = a
                break

    if not target_acc:
        return JSONResponse({"status": "error", "message": "Selected email account not found."}, status_code=404)

    clean_folder = (folder or "inbox").strip().lower()
    clean_q = (q or "").strip()
    clean_page_token = (page_token or "").strip()
    page_size = max(5, min(int(max_results or 25), 50))
    cache_key = f"v5:{clean_acc_id}:{clean_folder}:{clean_q}:{clean_page_token}:{page_size}"
    snap_key = f"{clean_acc_id}:{clean_folder}"
    now_ts = time.time()

    # Use a 25-second cache TTL for background/non-forced inbox fetches (and 4s debounce even on force)
    # so we never hammer Google's Gmail per-user quota and trigger a 15-minute 429 lockout!
    if not clean_page_token and cache_key in EMAIL_HUB_STATE["messages_cache"]:
        cached_entry = EMAIL_HUB_STATE["messages_cache"][cache_key]
        ttl_limit = 4.0 if force else 25.0
        if now_ts - cached_entry["ts"] < ttl_limit:
            return {
                "status": "success",
                "account": {
                    "id": target_acc["id"],
                    "provider": target_acc["provider"],
                    "email_address": target_acc["email_address"],
                    "display_name": target_acc["display_name"]
                },
                "folder": clean_folder,
                "messages": cached_entry["messages"],
                "next_page_token": cached_entry.get("next_page_token", ""),
                "has_more": bool(cached_entry.get("next_page_token")),
                "result_size_estimate": cached_entry.get("result_size_estimate", len(cached_entry["messages"])),
                "cached": True
            }

    provider = str(target_acc.get("provider") or "gmail").lower()
    conn_id = str(target_acc.get("composio_connection_id") or "").strip()
    entity_id = str(target_acc.get("composio_entity_id") or "glennbot_email_user").strip()

    normalized_messages = []
    next_page_token_out = ""
    result_size_estimate = 0
    upstream_error_or_rate_limit = False
    rate_limit_msg = ""
    retry_after_manila = ""
    try:
        if provider == "gmail":
            folder_query_map = {
                "inbox": "in:inbox",
                "sent": "in:sent",
                "drafts": "in:drafts",
                "spam": "in:spam",
                "trash": "in:trash"
            }
            base_q = folder_query_map.get(clean_folder, "in:inbox")
            full_query = f"{base_q} {clean_q}".strip()
            fetch_args = {
                "user_id": "me",
                "max_results": page_size,
                "query": full_query,
                "include_payload": True,
                "verbose": True
            }
            if clean_folder in ("trash", "spam"):
                fetch_args["include_spam_trash"] = True
            if clean_page_token:
                fetch_args["page_token"] = clean_page_token

            exec_res = _composio_execute_tool(
                "GMAIL_FETCH_EMAILS",
                conn_id,
                entity_id,
                fetch_args
            )
            data_obj = exec_res.get("data") or {}
            resp_data = data_obj.get("response_data") if isinstance(data_obj, dict) and "response_data" in data_obj else data_obj
            if exec_res.get("rate_limited") or (isinstance(data_obj, dict) and data_obj.get("http_error")) or exec_res.get("error"):
                upstream_error_or_rate_limit = True
                retry_after_manila = str(exec_res.get("retry_after_manila") or "")
                rate_limit_msg = str(exec_res.get("error") or (data_obj.get("http_error") if isinstance(data_obj, dict) else "") or "")

            raw_list = []
            if isinstance(resp_data, dict):
                raw_list = resp_data.get("messages") or resp_data.get("items") or []
                next_page_token_out = str(resp_data.get("nextPageToken") or resp_data.get("next_page_token") or "").strip()
                result_size_estimate = int(resp_data.get("resultSizeEstimate") or len(raw_list))
            elif isinstance(resp_data, list):
                raw_list = resp_data
                result_size_estimate = len(raw_list)

            for idx, m_item in enumerate(raw_list):
                if isinstance(m_item, dict):
                    normalized_messages.append(_extract_gmail_message_fields(m_item, idx))

        elif provider == "microsoft":
            skip_val = int(clean_page_token) if clean_page_token.isdigit() else 0
            ms_folder_map = {
                "inbox": "inbox",
                "sent": "sentitems",
                "drafts": "drafts",
                "spam": "junkemail",
                "trash": "deleteditems"
            }
            ms_fetch_args = {
                "user_id": "me",
                "folder": ms_folder_map.get(clean_folder, clean_folder),
                "top": page_size
            }
            if skip_val > 0:
                ms_fetch_args["skip"] = skip_val

            exec_res = _composio_execute_tool(
                "OUTLOOK_OUTLOOK_LIST_MESSAGES",
                conn_id,
                entity_id,
                ms_fetch_args
            )
            data_obj = exec_res.get("data") or {}
            resp_data = data_obj.get("response_data") if isinstance(data_obj, dict) and "response_data" in data_obj else data_obj
            if exec_res.get("rate_limited") or (isinstance(data_obj, dict) and data_obj.get("http_error")) or exec_res.get("error"):
                upstream_error_or_rate_limit = True
                retry_after_manila = str(exec_res.get("retry_after_manila") or "")
                rate_limit_msg = str(exec_res.get("error") or "")

            raw_list = []
            if isinstance(resp_data, dict):
                raw_list = resp_data.get("value") or resp_data.get("messages") or []
            elif isinstance(resp_data, list):
                raw_list = resp_data

            if len(raw_list) >= page_size:
                next_page_token_out = str(skip_val + page_size)

            for idx, m_item in enumerate(raw_list):
                if not isinstance(m_item, dict):
                    continue
                from_obj = (m_item.get("from") or {}).get("emailAddress") or {}
                sender_name = str(from_obj.get("name") or from_obj.get("address") or "Unknown Sender")
                sender_email = str(from_obj.get("address") or "")
                to_list_objs = m_item.get("toRecipients") or []
                to_addrs = []
                if isinstance(to_list_objs, list):
                    for r_item in to_list_objs:
                        if isinstance(r_item, dict):
                            ea = (r_item.get("emailAddress") or {}).get("address")
                            if ea:
                                to_addrs.append(str(ea))
                cc_list_objs = m_item.get("ccRecipients") or []
                cc_addrs = []
                if isinstance(cc_list_objs, list):
                    for r_item in cc_list_objs:
                        if isinstance(r_item, dict):
                            ea = (r_item.get("emailAddress") or {}).get("address")
                            if ea:
                                cc_addrs.append(str(ea))
                subj = str(m_item.get("subject") or "(No Subject)")
                preview = str(m_item.get("bodyPreview") or "")
                body_obj = m_item.get("body") or {}
                raw_body_content = str(body_obj.get("content") or preview or "")
                is_html_body = str(body_obj.get("contentType") or "").lower() == "html" or _looks_like_html_content(raw_body_content)
                body_html = raw_body_content if is_html_body else ""
                clean_body_content = _clean_email_html_to_text(raw_body_content)
                clean_snippet = _make_clean_email_snippet(preview, clean_body_content)
                if clean_q:
                    q_low = clean_q.lower()
                    if q_low not in subj.lower() and q_low not in sender_email.lower() and q_low not in clean_body_content.lower():
                        continue
                ms_raw_date = str(m_item.get("receivedDateTime") or m_item.get("sentDateTime") or "")
                ts_epoch, manila_display_date = _parse_email_timestamp_and_manila_str(ms_raw_date)
                normalized_messages.append({
                    "id": str(m_item.get("id") or f"ms_{skip_val + idx}"),
                    "thread_id": str(m_item.get("conversationId") or m_item.get("id") or f"ms_{skip_val + idx}"),
                    "subject": subj,
                    "sender": f"{sender_name} <{sender_email}>" if sender_email else sender_name,
                    "sender_name": sender_name,
                    "sender_email": sender_email,
                    "to": ", ".join(to_addrs),
                    "cc": ", ".join(cc_addrs),
                    "date": manila_display_date or ms_raw_date,
                    "raw_date": ms_raw_date,
                    "timestamp": ts_epoch,
                    "snippet": clean_snippet,
                    "body": clean_body_content or clean_snippet,
                    "body_html": body_html,
                    "is_unread": not bool(m_item.get("isRead", True)),
                    "labels": [clean_folder.upper()]
                })
            result_size_estimate = skip_val + len(normalized_messages)

        elif provider == "imap":
            normalized_messages, next_page_token_out, result_size_estimate = _fetch_imap_folder_messages(
                target_acc, clean_folder, clean_q, clean_page_token, page_size
            )

        # CRITICAL: If Gmail/Outlook returned a 429 rate-limit or upstream error and 0 messages,
        # NEVER overwrite the existing cached inbox with `[]`! Return the last-known-good cached inbox instead.
        if not normalized_messages and upstream_error_or_rate_limit:
            fallback_entry = EMAIL_HUB_STATE["messages_cache"].get(cache_key)
            if not fallback_entry and not clean_q and not clean_page_token:
                fallback_entry = EMAIL_HUB_STATE.get("inbox_snapshots", {}).get(snap_key)
            fallback_msgs = list((fallback_entry or {}).get("messages") or [])
            return {
                "status": "success",
                "account": {
                    "id": target_acc["id"],
                    "provider": target_acc["provider"],
                    "email_address": target_acc["email_address"],
                    "display_name": target_acc["display_name"]
                },
                "folder": clean_folder,
                "messages": fallback_msgs,
                "next_page_token": (fallback_entry or {}).get("next_page_token", ""),
                "has_more": bool((fallback_entry or {}).get("next_page_token")),
                "result_size_estimate": (fallback_entry or {}).get("result_size_estimate", len(fallback_msgs)),
                "cached": True,
                "rate_limited": True,
                "retry_after_manila": retry_after_manila,
                "rate_limit_message": rate_limit_msg
            }

        # CRITICAL: Always sort emails strictly by timestamp descending (Newest First)
        normalized_messages.sort(key=lambda m: float(m.get("timestamp") or 0.0), reverse=True)

        if clean_folder == "inbox" and normalized_messages and not clean_q and not clean_page_token:
            is_first_inbox_seed = clean_acc_id not in EMAIL_HUB_STATE["seen_message_ids_by_account"]
            seen_set = EMAIL_HUB_STATE["seen_message_ids_by_account"].setdefault(clean_acc_id, set())
            if is_first_inbox_seed:
                for nm in normalized_messages:
                    if nm.get("id"):
                        seen_set.add(str(nm["id"]))
            else:
                for nm in reversed(normalized_messages[:5]):
                    mid = str(nm.get("id") or "").strip()
                    if mid and mid not in seen_set:
                        msg_ts = float(nm.get("timestamp") or 0.0)
                        if msg_ts <= 0 or (time.time() - msg_ts) <= 1800:
                            _dispatch_signed_composio_webhook_for_email(target_acc, nm)
                        else:
                            seen_set.add(mid)
                for nm in normalized_messages:
                    if nm.get("id"):
                        seen_set.add(str(nm["id"]))

        if not clean_page_token:
            cache_obj = {
                "ts": now_ts,
                "messages": normalized_messages,
                "next_page_token": next_page_token_out,
                "result_size_estimate": result_size_estimate
            }
            EMAIL_HUB_STATE["messages_cache"][cache_key] = cache_obj
            if not clean_q and normalized_messages:
                prev_snap = EMAIL_HUB_STATE.setdefault("inbox_snapshots", {}).get(snap_key)
                EMAIL_HUB_STATE["inbox_snapshots"][snap_key] = cache_obj
                if not prev_snap:
                    threading.Thread(target=_save_email_hub_to_cloudinary, daemon=True).start()
        return {
            "status": "success",
            "account": {
                "id": target_acc["id"],
                "provider": target_acc["provider"],
                "email_address": target_acc["email_address"],
                "display_name": target_acc["display_name"]
            },
            "folder": clean_folder,
            "messages": normalized_messages,
            "next_page_token": next_page_token_out,
            "has_more": bool(next_page_token_out),
            "result_size_estimate": result_size_estimate
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Failed to fetch emails: {e}"}, status_code=500)


