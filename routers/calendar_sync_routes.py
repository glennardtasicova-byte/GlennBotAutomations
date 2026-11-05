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
from routers.email_accounts_routes import (
    EMAIL_HUB_STATE,
    _is_placeholder_connected_email,
    _extract_email_from_composio_item,
    _get_composio_headers,
    _composio_execute_tool,
    _composio_execute_proxy,
)

router = APIRouter()


# =========================================================================
# --- COMPOSIO UNIFIED CALENDAR & MEETINGS HUB (GOOGLE CALENDAR & MEET, MS OUTLOOK & TEAMS, ZOOM) ---
# =========================================================================
CALENDAR_CLOUDINARY_PUBLIC_ID = "glennbot_calendar_hub/calendar_hub_state_v1.json"
CALENDAR_HUB_LOCK = threading.Lock()
CALENDAR_SYNC_LOCK = threading.Lock()
CALENDAR_HUB_STATE: Dict[str, Any] = {
    "table_initialized": False,
    "loaded_from_cloud": False,
    "auth_config_ids": {},
    "accounts": [],
    "events": []
}

COMPOSIO_CALENDAR_PROVIDER_MAP = {
    "google_calendar": {"toolkit": "googlecalendar", "label": "Google Calendar & Meet"},
    "googlecalendar": {"toolkit": "googlecalendar", "label": "Google Calendar & Meet"},
    "google_meet": {"toolkit": "googlecalendar", "label": "Google Calendar & Meet"},
    "googlemeet": {"toolkit": "googlecalendar", "label": "Google Calendar & Meet"},
    "outlook_calendar": {"toolkit": "outlook", "label": "Microsoft Outlook & Teams"},
    "outlook": {"toolkit": "outlook", "label": "Microsoft Outlook & Teams"},
    "microsoft": {"toolkit": "outlook", "label": "Microsoft Outlook & Teams"},
    "microsoft_teams": {"toolkit": "outlook", "label": "Microsoft Outlook & Teams"},
    "teams": {"toolkit": "outlook", "label": "Microsoft Outlook & Teams"},
    "zoom": {"toolkit": "zoom", "label": "Zoom Cloud Meetings"}
}


def _normalize_calendar_provider_key(raw_provider: str) -> Tuple[str, str]:
    """
    Unifies Calendar + Conferencing providers:
    - Google Calendar & Google Meet share the exact same calendar (`google_calendar` / `googlecalendar`)
    - MS Outlook & MS Teams share the exact same calendar (`outlook_calendar` / `outlook`)
    - Zoom uses `zoom` (`zoom`) and syncs its meetings onto connected Google/Outlook calendars
    """
    clean = str(raw_provider or "").strip().lower()
    if clean in ("google", "google_calendar", "googlecalendar", "gcal", "google_meet", "googlemeet", "meet"):
        return ("google_calendar", "googlecalendar")
    if clean in ("outlook", "outlook_calendar", "microsoft", "ms_outlook", "office365", "microsoft_teams", "teams", "msteams", "ms_teams"):
        return ("outlook_calendar", "outlook")
    if clean in ("zoom", "zoom_meetings"):
        return ("zoom", "zoom")
    return ("google_calendar", "googlecalendar")


def _ensure_calendar_hub_tables():
    if CALENDAR_HUB_STATE.get("table_initialized"):
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_calendar_accounts (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    toolkit_slug TEXT NOT NULL,
                    email_address TEXT NOT NULL,
                    display_name TEXT,
                    composio_connection_id TEXT,
                    composio_entity_id TEXT,
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TEXT
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_calendar_events (
                    id TEXT PRIMARY KEY,
                    external_event_id TEXT,
                    account_id TEXT,
                    provider TEXT NOT NULL,
                    email_address TEXT,
                    subject TEXT NOT NULL,
                    description TEXT,
                    location TEXT,
                    start_iso TEXT NOT NULL,
                    end_iso TEXT NOT NULL,
                    timezone TEXT DEFAULT 'Asia/Manila',
                    duration_minutes INTEGER DEFAULT 60,
                    meeting_platform TEXT DEFAULT 'none',
                    meeting_url TEXT,
                    is_online_meeting INTEGER DEFAULT 0,
                    organizer_email TEXT,
                    attendees_json TEXT,
                    availability TEXT DEFAULT 'busy',
                    reminder_minutes INTEGER DEFAULT 15,
                    status TEXT DEFAULT 'confirmed',
                    html_link TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_calendar_deleted_events (
                    external_event_id TEXT PRIMARY KEY,
                    provider TEXT,
                    deleted_at TEXT
                );
            """))
        CALENDAR_HUB_STATE["table_initialized"] = True
    except Exception as e:
        print(f"[CalendarHub] Table init warning: {e}")


def _make_calendar_event_pk(provider: str, acc_id: str, ext_id: str) -> str:
    """
    Generates a 100% deterministic, collision-free primary key from the FULL external_event_id.
    Fixes Microsoft Graph / Outlook event IDs (which share an identical 120-character folder prefix
    `AQMkADAwATM3ZmYBLWJkM2Mt...` and only differ at the very end) as well as Google Calendar
    recurring event instance IDs.
    """
    clean_ext = str(ext_id or "").strip()
    clean_prov = str(provider or "cal").strip().lower()
    if "google" in clean_prov:
        short_p = "gcal"
    elif "outlook" in clean_prov or "microsoft" in clean_prov:
        short_p = "ms"
    elif "zoom" in clean_prov:
        short_p = "zoom"
    else:
        short_p = "cal"
    if not clean_ext:
        return f"calev_{short_p}_{uuid.uuid4().hex[:16]}"
    if short_p == "zoom" and len(clean_ext) <= 24 and clean_ext.isdigit():
        return f"calev_zoom_{clean_ext}"
    digest = hashlib.sha1(f"{short_p}::{acc_id}::{clean_ext}".encode("utf-8")).hexdigest()[:24]
    return f"calev_{short_p}_{digest}"


def _save_calendar_hub_to_cloudinary():
    # Cloudinary is intentionally excluded from Calendar Hub so external live sync is never overwritten by stale cloud snapshots.
    return


def _prune_deprecated_or_placeholder_calendar_accounts():
    """
    Removes deprecated separate `google_meet` / `microsoft_teams` account entries
    (since Google Calendar = Google Meet and MS Outlook = MS Teams), purges
    stale `@connected.account` placeholder rows when a real email row exists,
    and auto-heals any remaining `@connected.account` Google Calendar row to the
    authenticated Google account email (`glennardtasico@gmail.com`).
    """
    _ensure_calendar_hub_tables()
    to_delete_ids = []
    healed_records = []
    with CALENDAR_HUB_LOCK:
        current_accounts = list(CALENDAR_HUB_STATE.get("accounts") or [])
        real_providers = {
            str(a.get("provider") or "").lower()
            for a in current_accounts
            if not _is_placeholder_connected_email(str(a.get("email_address") or ""))
            and str(a.get("provider") or "").lower() in ("google_calendar", "outlook_calendar", "zoom")
        }
        cleaned = []
        seen_provider_email = set()
        for a in current_accounts:
            aid = str(a.get("id") or "")
            prov = str(a.get("provider") or "").lower()
            tk = str(a.get("toolkit_slug") or "").lower()
            em = str(a.get("email_address") or "").strip().lower()
            if prov in ("google_meet", "microsoft_teams") or tk in ("googlemeet", "microsoft_teams"):
                to_delete_ids.append(aid)
                continue
            if _is_placeholder_connected_email(em) and prov in real_providers:
                to_delete_ids.append(aid)
                continue
            if _is_placeholder_connected_email(em) and prov == "google_calendar":
                fallback_gm = ""
                try:
                    for em_acc in (EMAIL_HUB_STATE.get("accounts") or []):
                        if isinstance(em_acc, dict) and str(em_acc.get("provider") or "").lower() == "gmail":
                            cand_gm = str(em_acc.get("email_address") or "").strip().lower()
                            if "@" in cand_gm and not _is_placeholder_connected_email(cand_gm):
                                fallback_gm = cand_gm
                                break
                except Exception:
                    pass
                if not fallback_gm:
                    try:
                        gd_state = _load_gdrive_auth_store(force_cloud=False)
                        cand_gd = str(gd_state.get("connected_email") or "").strip().lower()
                        if "@" in cand_gd and not _is_placeholder_connected_email(cand_gd):
                            fallback_gm = cand_gd
                    except Exception:
                        pass
                if not fallback_gm:
                    fallback_gm = str(os.getenv("ADMIN_GOOGLE_EMAIL") or "glennardtasico@gmail.com").strip().lower()
                if fallback_gm and "@" in fallback_gm:
                    em = fallback_gm
                    a["email_address"] = fallback_gm
                    if not a.get("display_name") or _is_placeholder_connected_email(a.get("display_name")) or "google_calendar_" in str(a.get("display_name") or ""):
                        a["display_name"] = fallback_gm.split("@")[0]
                    healed_records.append(dict(a))
            dedup_key = f"{prov}::{em}"
            if em and not _is_placeholder_connected_email(em) and dedup_key in seen_provider_email:
                to_delete_ids.append(aid)
                continue
            if em:
                seen_provider_email.add(dedup_key)
            cleaned.append(a)
        CALENDAR_HUB_STATE["accounts"] = cleaned

    if to_delete_ids or healed_records:
        try:
            with db_engine.begin() as conn:
                for did in to_delete_ids:
                    conn.execute(text("DELETE FROM glennbot_calendar_accounts WHERE id = :id"), {"id": did})
                for hr in healed_records:
                    conn.execute(
                        text("UPDATE glennbot_calendar_accounts SET email_address = :em, display_name = :dn WHERE id = :id"),
                        {"em": hr["email_address"], "dn": hr.get("display_name") or "", "id": hr["id"]}
                    )
                    conn.execute(
                        text("UPDATE glennbot_calendar_events SET email_address = :em, organizer_email = :em WHERE account_id = :id OR provider = 'google_calendar'"),
                        {"em": hr["email_address"], "id": hr["id"]}
                    )
        except Exception as e:
            print(f"[CalendarHub] Prune/heal accounts warning: {e}")



def _load_calendar_hub_state(force_cloud: bool = False):
    _ensure_calendar_hub_tables()
    with CALENDAR_HUB_LOCK:
        if CALENDAR_HUB_STATE["loaded_from_cloud"] and not force_cloud:
            return CALENDAR_HUB_STATE

    db_accounts = []
    db_events = []
    legacy_bad_event_ids = []
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, provider, toolkit_slug, email_address, display_name,
                       composio_connection_id, composio_entity_id, status, created_at
                FROM glennbot_calendar_accounts
                ORDER BY created_at ASC
            """)).mappings().all()
            for r in rows:
                db_accounts.append({
                    "id": str(r.get("id") or ""),
                    "provider": str(r.get("provider") or "google_calendar"),
                    "toolkit_slug": str(r.get("toolkit_slug") or "googlecalendar"),
                    "email_address": str(r.get("email_address") or ""),
                    "display_name": str(r.get("display_name") or ""),
                    "composio_connection_id": str(r.get("composio_connection_id") or ""),
                    "composio_entity_id": str(r.get("composio_entity_id") or "glennbot_calendar_user"),
                    "status": str(r.get("status") or "ACTIVE"),
                    "created_at": str(r.get("created_at") or datetime.now(MANILA_TZ).isoformat())
                })

            ev_rows = conn.execute(text("""
                SELECT id, external_event_id, account_id, provider, email_address,
                       subject, description, location, start_iso, end_iso, timezone,
                       duration_minutes, meeting_platform, meeting_url, is_online_meeting,
                       organizer_email, attendees_json, availability, reminder_minutes,
                       status, html_link, created_at, updated_at
                FROM glennbot_calendar_events
                ORDER BY start_iso ASC
            """)).mappings().all()
            for r in ev_rows:
                raw_id = str(r.get("id") or "")
                ext_id = str(r.get("external_event_id") or "")
                acc_id = str(r.get("account_id") or "")
                prov = str(r.get("provider") or "google_calendar")
                expected_id = _make_calendar_event_pk(prov, acc_id, ext_id) if ext_id else raw_id
                if ext_id and raw_id != expected_id:
                    legacy_bad_event_ids.append(raw_id)
                try:
                    att_list = json.loads(r.get("attendees_json") or "[]")
                    if not isinstance(att_list, list):
                        att_list = []
                except Exception:
                    att_list = []
                ev_obj = _enrich_calendar_event_date_fields({
                    "id": expected_id,
                    "external_event_id": ext_id,
                    "account_id": acc_id,
                    "provider": prov,
                    "email_address": str(r.get("email_address") or ""),
                    "subject": str(r.get("subject") or "(No Subject)"),
                    "description": str(r.get("description") or ""),
                    "location": str(r.get("location") or ""),
                    "start_iso": str(r.get("start_iso") or ""),
                    "end_iso": str(r.get("end_iso") or ""),
                    "timezone": str(r.get("timezone") or "Asia/Manila"),
                    "duration_minutes": int(r.get("duration_minutes") or 60),
                    "meeting_platform": str(r.get("meeting_platform") or "none"),
                    "meeting_url": str(r.get("meeting_url") or ""),
                    "is_online_meeting": bool(r.get("is_online_meeting")),
                    "organizer_email": str(r.get("organizer_email") or ""),
                    "attendees": att_list,
                    "availability": str(r.get("availability") or "busy"),
                    "reminder_minutes": int(r.get("reminder_minutes") or 15),
                    "status": str(r.get("status") or "confirmed"),
                    "html_link": str(r.get("html_link") or ""),
                    "created_at": str(r.get("created_at") or ""),
                    "updated_at": str(r.get("updated_at") or "")
                })
                db_events.append(ev_obj)
    except Exception as e:
        print(f"[CalendarHub] DB read warning: {e}")

    db_deleted_ext_ids = set()
    try:
        with db_engine.connect() as conn:
            del_rows = conn.execute(text("SELECT external_event_id FROM glennbot_calendar_deleted_events")).mappings().all()
            for dr in del_rows:
                did_str = str(dr.get("external_event_id") or "").strip()
                if did_str:
                    db_deleted_ext_ids.add(did_str)
    except Exception:
        pass

    if legacy_bad_event_ids:
        try:
            with db_engine.begin() as conn:
                for bid in legacy_bad_event_ids:
                    conn.execute(text("DELETE FROM glennbot_calendar_events WHERE id = :id"), {"id": bid})
        except Exception:
            pass

    if db_deleted_ext_ids:
        db_events = [
            ev for ev in db_events
            if str(ev.get("external_event_id") or "").strip() not in db_deleted_ext_ids
        ]

    with CALENDAR_HUB_LOCK:
        CALENDAR_HUB_STATE["accounts"] = db_accounts
        CALENDAR_HUB_STATE["events"] = db_events
        CALENDAR_HUB_STATE["deleted_external_ids"] = db_deleted_ext_ids
        CALENDAR_HUB_STATE["loaded_from_cloud"] = True

    _prune_deprecated_or_placeholder_calendar_accounts()
    return CALENDAR_HUB_STATE


def _upsert_calendar_account_in_db(acc: dict, sync_cloud: bool = True):
    _ensure_calendar_hub_tables()
    acc_id = str(acc.get("id") or f"cal_{uuid.uuid4().hex[:10]}")
    acc["id"] = acc_id
    clean_email = str(acc.get("email_address") or "").strip().lower()
    clean_provider, clean_tk = _normalize_calendar_provider_key(acc.get("provider") or acc.get("toolkit_slug") or "google_calendar")

    duplicate_ids = []
    with CALENDAR_HUB_LOCK:
        for existing_a in CALENDAR_HUB_STATE["accounts"]:
            ex_id = str(existing_a.get("id") or "")
            ex_prov = str(existing_a.get("provider") or "").lower()
            ex_email = str(existing_a.get("email_address") or "").strip().lower()
            if ex_id != acc_id and ex_prov == clean_provider:
                # Keep strictly the newest connected account for each calendar provider so stale accounts never linger
                if clean_email and not _is_placeholder_connected_email(clean_email):
                    duplicate_ids.append(ex_id)
                elif _is_placeholder_connected_email(ex_email):
                    duplicate_ids.append(ex_id)
        if duplicate_ids:
            CALENDAR_HUB_STATE["accounts"] = [
                a for a in CALENDAR_HUB_STATE["accounts"] if a.get("id") not in duplicate_ids
            ]

    record = {
        "id": acc_id,
        "provider": clean_provider,
        "toolkit_slug": clean_tk,
        "email_address": clean_email,
        "display_name": str(acc.get("display_name") or (clean_email.split("@")[0] if "@" in clean_email else clean_provider)),
        "composio_connection_id": str(acc.get("composio_connection_id") or ""),
        "composio_entity_id": str(acc.get("composio_entity_id") or "glennbot_calendar_user"),
        "status": str(acc.get("status") or "ACTIVE"),
        "created_at": str(acc.get("created_at") or datetime.now(MANILA_TZ).isoformat())
    }
    try:
        with db_engine.begin() as conn:
            for did in duplicate_ids:
                conn.execute(text("DELETE FROM glennbot_calendar_accounts WHERE id = :id"), {"id": did})
            conn.execute(text("""
                INSERT INTO glennbot_calendar_accounts
                (id, provider, toolkit_slug, email_address, display_name, composio_connection_id, composio_entity_id, status, created_at)
                VALUES (:id, :provider, :toolkit_slug, :email_address, :display_name, :composio_connection_id, :composio_entity_id, :status, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    toolkit_slug = EXCLUDED.toolkit_slug,
                    email_address = EXCLUDED.email_address,
                    display_name = EXCLUDED.display_name,
                    composio_connection_id = EXCLUDED.composio_connection_id,
                    composio_entity_id = EXCLUDED.composio_entity_id,
                    status = EXCLUDED.status;
            """), record)
    except Exception as e:
        print(f"[CalendarHub] Upsert account warning: {e}")

    with CALENDAR_HUB_LOCK:
        replaced = False
        for i, a in enumerate(CALENDAR_HUB_STATE["accounts"]):
            if a.get("id") == acc_id:
                CALENDAR_HUB_STATE["accounts"][i] = record
                replaced = True
                break
        if not replaced:
            CALENDAR_HUB_STATE["accounts"].insert(0, record)

    if sync_cloud:
        threading.Thread(target=_save_calendar_hub_to_cloudinary, daemon=True).start()
    return record


def _attach_calendar_tz(naive_dt: datetime, tz_name: str = "Asia/Manila") -> datetime:
    """
    Safely attaches an IANA timezone to a naive datetime using `pytz.localize()`
    (NEVER `.replace(tzinfo=MANILA_TZ)`, which in pytz attaches Manila's 1844 LMT
    offset of -15:56 and shifts 10:00 AM to 9:56 AM the next day!).
    """
    if naive_dt.tzinfo is not None:
        return naive_dt
    clean_tz = str(tz_name or "Asia/Manila").strip()
    try:
        tz_obj = pytz.timezone(clean_tz)
        if hasattr(tz_obj, "localize"):
            return tz_obj.localize(naive_dt)
        return naive_dt.replace(tzinfo=tz_obj)
    except Exception:
        if hasattr(MANILA_TZ, "localize"):
            return MANILA_TZ.localize(naive_dt)
        return naive_dt.replace(tzinfo=timezone(timedelta(hours=8)))


def _parse_calendar_iso_datetime(raw_iso: str, default_tz: str = "Asia/Manila") -> Optional[datetime]:
    """
    Parses any ISO-8601 datetime string from Google Calendar, Microsoft Outlook (7-digit
    fractional seconds `.0000000`), Zoom (`Z` UTC), or internal storage, and repairs any
    legacy `-15:56` pytz LMT offset back to `+08:00`.
    """
    clean_s = str(raw_iso or "").strip()
    if not clean_s:
        return None
    try:
        # Repair legacy -15:56 pytz LMT offset if present in stored events
        clean_s = re.sub(r"-15:56(?::00)?$", "+08:00", clean_s)
        if clean_s.endswith("Z"):
            clean_s = clean_s[:-1] + "+00:00"
        # Python 3.10 fromisoformat() rejects 7-digit fractional seconds (.0000000) returned by MS Graph
        clean_s = re.sub(r"\.(\d{6})\d+", r".\1", clean_s)
        if len(clean_s) == 10 and clean_s.count("-") == 2:
            naive_d = datetime.fromisoformat(clean_s + "T09:00:00")
            return _attach_calendar_tz(naive_d, default_tz).astimezone(MANILA_TZ)
        parsed_dt = datetime.fromisoformat(clean_s)
        if parsed_dt.tzinfo is None:
            parsed_dt = _attach_calendar_tz(parsed_dt, default_tz)
        return parsed_dt.astimezone(MANILA_TZ)
    except Exception:
        return None


def _enrich_calendar_event_date_fields(ev: dict) -> dict:
    out = dict(ev)
    ev_tz = str(out.get("timezone") or "Asia/Manila").strip() or "Asia/Manila"
    start_iso = str(out.get("start_iso") or "").strip()
    end_iso = str(out.get("end_iso") or "").strip()

    dt_start = _parse_calendar_iso_datetime(start_iso, ev_tz)
    dt_end = _parse_calendar_iso_datetime(end_iso, ev_tz)

    if not dt_start:
        dt_start = datetime.now(MANILA_TZ)
    if not dt_end or dt_end <= dt_start:
        dur_m = max(10, int(out.get("duration_minutes") or 60))
        dt_end = dt_start + timedelta(minutes=dur_m)

    calc_dur = max(5, int(round((dt_end - dt_start).total_seconds() / 60.0)))
    out["duration_minutes"] = calc_dur
    out["day"] = dt_start.day
    out["month"] = dt_start.month
    out["year"] = dt_start.year
    out["date_str"] = dt_start.strftime("%Y-%m-%d")
    out["display_date"] = dt_start.strftime("%b %d, %Y")
    out["time_24"] = dt_start.strftime("%H:%M")
    out["end_time_24"] = dt_end.strftime("%H:%M")
    out["time_str"] = dt_start.strftime("%I:%M %p").lstrip("0")
    out["end_time_str"] = dt_end.strftime("%I:%M %p").lstrip("0")
    out["time_range_str"] = f"{out['time_str']} - {out['end_time_str']}"
    out["start_iso"] = dt_start.isoformat()
    out["end_iso"] = dt_end.isoformat()

    mp = str(out.get("meeting_platform") or "none").strip().lower()
    m_url = str(out.get("meeting_url") or "").strip()
    loc_and_desc = f"{out.get('location', '')} {out.get('description', '')} {m_url}".lower()
    if mp in ("", "none"):
        if "meet.google.com" in loc_and_desc:
            mp = "google_meet"
        elif "teams.microsoft.com" in loc_and_desc or "teams.live.com" in loc_and_desc:
            mp = "microsoft_teams"
        elif "zoom.us" in loc_and_desc:
            mp = "zoom"
    if not m_url:
        url_m = re.search(r"https?://(?:meet\.google\.com|teams\.microsoft\.com|teams\.live\.com|[a-z0-9.-]*zoom\.us)/[^\s\"'<>)+]+", f"{out.get('location', '')} {out.get('description', '')}", re.I)
        if url_m:
            m_url = url_m.group(0).strip()
    out["meeting_platform"] = mp if mp in ("google_meet", "microsoft_teams", "zoom") else "none"
    out["meeting_url"] = m_url
    out["is_online_meeting"] = bool(out["meeting_platform"] != "none" or m_url)
    if not isinstance(out.get("attendees"), list):
        out["attendees"] = []
    return out


def _upsert_calendar_event_in_db(ev: dict, sync_cloud: bool = True) -> dict:
    _ensure_calendar_hub_tables()
    enriched = _enrich_calendar_event_date_fields(ev)
    ev_id = str(enriched.get("id") or f"calev_{uuid.uuid4().hex[:12]}")
    enriched["id"] = ev_id
    now_iso = datetime.now(MANILA_TZ).isoformat()
    enriched["created_at"] = str(enriched.get("created_at") or now_iso)
    enriched["updated_at"] = now_iso

    db_params = {
        "id": ev_id,
        "external_event_id": str(enriched.get("external_event_id") or ""),
        "account_id": str(enriched.get("account_id") or ""),
        "provider": str(enriched.get("provider") or "google_calendar"),
        "email_address": str(enriched.get("email_address") or ""),
        "subject": str(enriched.get("subject") or "(No Subject)"),
        "description": str(enriched.get("description") or ""),
        "location": str(enriched.get("location") or ""),
        "start_iso": str(enriched.get("start_iso") or ""),
        "end_iso": str(enriched.get("end_iso") or ""),
        "timezone": str(enriched.get("timezone") or "Asia/Manila"),
        "duration_minutes": int(enriched.get("duration_minutes") or 60),
        "meeting_platform": str(enriched.get("meeting_platform") or "none"),
        "meeting_url": str(enriched.get("meeting_url") or ""),
        "is_online_meeting": 1 if enriched.get("is_online_meeting") else 0,
        "organizer_email": str(enriched.get("organizer_email") or enriched.get("email_address") or ""),
        "attendees_json": json.dumps(enriched.get("attendees") or []),
        "availability": str(enriched.get("availability") or "busy"),
        "reminder_minutes": int(enriched.get("reminder_minutes") or 15),
        "status": str(enriched.get("status") or "confirmed"),
        "html_link": str(enriched.get("html_link") or ""),
        "created_at": enriched["created_at"],
        "updated_at": enriched["updated_at"]
    }
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO glennbot_calendar_events
                (id, external_event_id, account_id, provider, email_address, subject, description, location,
                 start_iso, end_iso, timezone, duration_minutes, meeting_platform, meeting_url, is_online_meeting,
                 organizer_email, attendees_json, availability, reminder_minutes, status, html_link, created_at, updated_at)
                VALUES (:id, :external_event_id, :account_id, :provider, :email_address, :subject, :description, :location,
                        :start_iso, :end_iso, :timezone, :duration_minutes, :meeting_platform, :meeting_url, :is_online_meeting,
                        :organizer_email, :attendees_json, :availability, :reminder_minutes, :status, :html_link, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    external_event_id = EXCLUDED.external_event_id,
                    email_address = EXCLUDED.email_address,
                    subject = EXCLUDED.subject,
                    description = EXCLUDED.description,
                    location = EXCLUDED.location,
                    start_iso = EXCLUDED.start_iso,
                    end_iso = EXCLUDED.end_iso,
                    timezone = EXCLUDED.timezone,
                    duration_minutes = EXCLUDED.duration_minutes,
                    meeting_platform = EXCLUDED.meeting_platform,
                    meeting_url = EXCLUDED.meeting_url,
                    is_online_meeting = EXCLUDED.is_online_meeting,
                    organizer_email = EXCLUDED.organizer_email,
                    attendees_json = EXCLUDED.attendees_json,
                    availability = EXCLUDED.availability,
                    reminder_minutes = EXCLUDED.reminder_minutes,
                    status = EXCLUDED.status,
                    html_link = EXCLUDED.html_link,
                    updated_at = EXCLUDED.updated_at;
            """), db_params)
    except Exception as e:
        print(f"[CalendarHub] Upsert event warning: {e}")

    with CALENDAR_HUB_LOCK:
        replaced = False
        for i, existing in enumerate(CALENDAR_HUB_STATE["events"]):
            if existing.get("id") == ev_id:
                CALENDAR_HUB_STATE["events"][i] = enriched
                replaced = True
                break
        if not replaced:
            CALENDAR_HUB_STATE["events"].append(enriched)

    if sync_cloud:
        threading.Thread(target=_save_calendar_hub_to_cloudinary, daemon=True).start()
    return enriched


def _get_or_create_calendar_composio_auth_config_id(provider_or_toolkit: str, force_lookup: bool = False) -> str:
    """
    Finds or creates a Composio Managed OAuth2 auth_config_id for:
    - googlecalendar (Unified Google Calendar + Google Meet)
    - outlook (Unified Microsoft Outlook Calendar + MS Teams)
    - zoom (Zoom Cloud Meetings)
    All powered by the single shared Composio API Key!
    """
    _load_calendar_hub_state()
    _, toolkit_slug = _normalize_calendar_provider_key(provider_or_toolkit)
    cached_map = CALENDAR_HUB_STATE.setdefault("auth_config_ids", {})
    if cached_map.get(toolkit_slug) and not force_lookup:
        return str(cached_map[toolkit_slug]).strip()

    headers = _get_composio_headers()
    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/auth_configs", headers=headers, timeout=15)
        if r.status_code == 200:
            items = r.json().get("items") or []
            for item in items:
                tk = str((item.get("toolkit") or {}).get("slug") or "").lower()
                scheme = str(item.get("auth_scheme") or "").upper()
                if tk == toolkit_slug and ("OAUTH" in scheme or not scheme):
                    found_id = str(item.get("id") or "").strip()
                    if found_id:
                        cached_map[toolkit_slug] = found_id
                        return found_id
    except Exception as e:
        print(f"[CalendarHub] List auth_configs error ({toolkit_slug}): {e}")

    try:
        create_payload = {
            "toolkit": {"slug": toolkit_slug},
            "auth_config": {
                "type": "use_composio_managed_auth",
                "name": f"GlennBot {toolkit_slug.upper()} OAuth2"
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
                cached_map[toolkit_slug] = new_id
                threading.Thread(target=_save_calendar_hub_to_cloudinary, daemon=True).start()
                return new_id
    except Exception as e:
        print(f"[CalendarHub] Create auth_config error ({toolkit_slug}): {e}")

    return str(cached_map.get(toolkit_slug) or "")


def _extract_gcal_owner_email_from_events_payload(d_obj: Any) -> Tuple[str, str]:
    """
    Extracts the primary Google Calendar owner's real email address and display name
    from a Google Calendar v3 `events.list` response (`d_obj["summary"]`, `creator.self`, `organizer.self`).
    """
    if not isinstance(d_obj, dict):
        return ("", "")
    resolved_em = ""
    resolved_disp = ""

    top_summary = str(d_obj.get("summary") or "").strip()
    if "@" in top_summary and not _is_placeholder_connected_email(top_summary):
        m = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", top_summary)
        if m and not _is_placeholder_connected_email(m.group(1)):
            resolved_em = m.group(1).strip().lower()
    elif top_summary:
        resolved_disp = top_summary

    ev_items = d_obj.get("items") if isinstance(d_obj.get("items"), list) else []
    # Pass 1: Look for creator/organizer explicitly marked with `self: True`
    if not resolved_em:
        for ev_it in ev_items:
            if not isinstance(ev_it, dict):
                continue
            for role_key in ("organizer", "creator"):
                role_obj = ev_it.get(role_key)
                if isinstance(role_obj, dict) and role_obj.get("self"):
                    cand_em = str(role_obj.get("email") or "").strip().lower()
                    if "@" in cand_em and not _is_placeholder_connected_email(cand_em):
                        resolved_em = cand_em
                        if not resolved_disp:
                            resolved_disp = str(role_obj.get("displayName") or "").strip()
                        break
            if resolved_em:
                break

    # Pass 2: Look for any non-group organizer/creator email on the primary calendar
    if not resolved_em:
        for ev_it in ev_items:
            if not isinstance(ev_it, dict):
                continue
            for role_key in ("organizer", "creator"):
                role_obj = ev_it.get(role_key)
                if isinstance(role_obj, dict):
                    cand_em = str(role_obj.get("email") or "").strip().lower()
                    if "@" in cand_em and not _is_placeholder_connected_email(cand_em):
                        resolved_em = cand_em
                        if not resolved_disp:
                            resolved_disp = str(role_obj.get("displayName") or "").strip()
                        break
            if resolved_em:
                break

    return (resolved_em, resolved_disp)


def _resolve_real_email_for_calendar_toolkit(tk_slug: str, conn_id: str, entity_id: str, item: dict) -> Tuple[str, str]:
    """
    Resolves the exact user email address and display name for a Composio connected account
    (`googlecalendar`, `outlook`, `zoom`) so `@connected.account` placeholder strings never appear.
    """
    email_addr, display_name = _extract_email_from_composio_item(item)
    if email_addr and not _is_placeholder_connected_email(email_addr):
        return (email_addr, display_name or email_addr.split("@")[0])

    # Layer 0: Query single connected_account detail endpoint (`GET /connected_accounts/{conn_id}`)
    # because the list endpoint often omits nested `data` / `state` / `params` fields.
    if conn_id:
        try:
            r_det = HTTP_SESSION.get(
                f"{COMPOSIO_BASE_URL}/connected_accounts/{conn_id}",
                headers=_get_composio_headers(),
                timeout=10
            )
            if r_det.status_code == 200:
                det_json = r_det.json() or {}
                det_em, det_disp = _extract_email_from_composio_item(det_json)
                if det_em and not _is_placeholder_connected_email(det_em):
                    return (det_em, det_disp or display_name or det_em.split("@")[0])
                if det_disp and not display_name:
                    display_name = det_disp
        except Exception:
            pass

    # 1. Google Calendar (`googlecalendar`): Multi-layer resolution
    if tk_slug == "googlecalendar":
        # Layer 1A: `GOOGLECALENDAR_EVENTS_LIST` on `calendarId="primary"` (always supported; returns primary calendar `summary` = owner email + `organizer.self` / `creator.self`)
        try:
            ev_res = _composio_execute_tool(
                "GOOGLECALENDAR_EVENTS_LIST",
                conn_id,
                entity_id,
                {"calendarId": "primary", "maxResults": 20, "singleEvents": True}
            )
            d_obj = (ev_res.get("data") or {}).get("response_data") or ev_res.get("data") or {}
            ev_em, ev_disp = _extract_gcal_owner_email_from_events_payload(d_obj)
            if ev_em and not _is_placeholder_connected_email(ev_em):
                email_addr = ev_em
            if ev_disp and not display_name:
                display_name = ev_disp
        except Exception:
            pass

        # Layer 1B: Direct REST proxy to Google Calendar v3 `/calendars/primary` & `/users/me/calendarList/primary` & Google OAuth2 `/userinfo`
        if not email_addr or _is_placeholder_connected_email(email_addr):
            for proxy_ep in (
                "/calendars/primary",
                "/users/me/calendarList/primary",
                "https://www.googleapis.com/calendar/v3/calendars/primary",
                "https://www.googleapis.com/oauth2/v2/userinfo",
            ):
                try:
                    p_res = _composio_execute_proxy(conn_id, entity_id, proxy_ep, "GET")
                    p_data = (p_res.get("data") or {}).get("response_data") or p_res.get("data") or {}
                    if isinstance(p_data, dict):
                        cand_id = str(p_data.get("email") or p_data.get("id") or p_data.get("summary") or "").strip()
                        if "@" in cand_id and not _is_placeholder_connected_email(cand_id):
                            email_addr = cand_id.lower()
                            display_name = str(p_data.get("name") or p_data.get("summaryOverride") or p_data.get("summary") or display_name or "").strip()
                            break
                except Exception:
                    pass

        # Layer 1C: Calendar metadata tools with both camelCase (`calendarId`) and snake_case (`calendar_id`)
        if not email_addr or _is_placeholder_connected_email(email_addr):
            for cal_tool in ("GOOGLECALENDAR_GET_CALENDAR", "GOOGLECALENDAR_CALENDARS_GET"):
                try:
                    cal_prof = _composio_execute_tool(
                        cal_tool,
                        conn_id,
                        entity_id,
                        {"calendarId": "primary", "calendar_id": "primary"}
                    )
                    d_obj = (cal_prof.get("data") or {}).get("response_data") or cal_prof.get("data") or {}
                    if isinstance(d_obj, dict):
                        cand_id = str(d_obj.get("id") or d_obj.get("summary") or "").strip()
                        if "@" in cand_id and not _is_placeholder_connected_email(cand_id):
                            email_addr = cand_id.lower()
                            display_name = str(d_obj.get("summary") or display_name or "").strip()
                            break
                except Exception:
                    pass

        if not email_addr or _is_placeholder_connected_email(email_addr):
            for list_tool in ("GOOGLECALENDAR_LIST_CALENDARS", "GOOGLECALENDAR_CALENDAR_LIST_LIST"):
                try:
                    list_res = _composio_execute_tool(list_tool, conn_id, entity_id, {})
                    d_obj = (list_res.get("data") or {}).get("response_data") or list_res.get("data") or {}
                    cal_items = d_obj.get("items") if isinstance(d_obj, dict) else []
                    if isinstance(cal_items, list):
                        for c_item in cal_items:
                            if not isinstance(c_item, dict):
                                continue
                            cid = str(c_item.get("id") or "").strip()
                            if c_item.get("primary") and "@" in cid and not _is_placeholder_connected_email(cid):
                                email_addr = cid.lower()
                                display_name = str(c_item.get("summaryOverride") or c_item.get("summary") or display_name or "").strip()
                                break
                        if not email_addr:
                            for c_item in cal_items:
                                cid = str((c_item or {}).get("id") or "").strip()
                                if "@" in cid and not _is_placeholder_connected_email(cid):
                                    email_addr = cid.lower()
                                    break
                    if email_addr and not _is_placeholder_connected_email(email_addr):
                        break
                except Exception:
                    pass

        # Layer 1D: Same-workspace authenticated Google account fallback (Gmail Hub / Google Drive OAuth / Admin Google account)
        if not email_addr or _is_placeholder_connected_email(email_addr):
            try:
                for em_acc in (EMAIL_HUB_STATE.get("accounts") or []):
                    if isinstance(em_acc, dict) and str(em_acc.get("provider") or "").lower() == "gmail":
                        cand_gm = str(em_acc.get("email_address") or "").strip().lower()
                        if "@" in cand_gm and not _is_placeholder_connected_email(cand_gm):
                            email_addr = cand_gm
                            if not display_name:
                                display_name = str(em_acc.get("display_name") or "").strip()
                            break
            except Exception:
                pass

        if not email_addr or _is_placeholder_connected_email(email_addr):
            try:
                gd_state = _load_gdrive_auth_store(force_cloud=False)
                gd_em = str(gd_state.get("connected_email") or "").strip().lower()
                if "@" in gd_em and not _is_placeholder_connected_email(gd_em):
                    email_addr = gd_em
            except Exception:
                pass

        if not email_addr or _is_placeholder_connected_email(email_addr):
            admin_em = str(os.getenv("ADMIN_GOOGLE_EMAIL") or "glennardtasico@gmail.com").strip().lower()
            if "@" in admin_em:
                email_addr = admin_em
                if not display_name:
                    display_name = "Glennard Tasico"

    # 2. Microsoft Outlook & Teams (`outlook`): `OUTLOOK_OUTLOOK_GET_PROFILE`
    elif tk_slug == "outlook":
        try:
            prof_res = _composio_execute_tool("OUTLOOK_OUTLOOK_GET_PROFILE", conn_id, entity_id, {"user_id": "me"})
            d_obj = (prof_res.get("data") or {}).get("response_data") or prof_res.get("data") or {}
            if isinstance(d_obj, dict):
                cand = str(d_obj.get("mail") or d_obj.get("userPrincipalName") or d_obj.get("emailAddress") or "").strip().lower()
                if "@" in cand and not _is_placeholder_connected_email(cand):
                    email_addr = cand
                display_name = str(d_obj.get("displayName") or display_name or "").strip()
        except Exception:
            pass

    # 3. Zoom (`zoom`): Fast, zero-daily-quota lookup via `/users/me` proxy (returns `email`, `display_name`, and `personal_meeting_url`)
    elif tk_slug == "zoom":
        try:
            u_res = _composio_execute_proxy(conn_id, entity_id, "/users/me", "GET")
            u_data = u_res.get("data") if isinstance(u_res.get("data"), dict) else {}
            if u_data:
                cand_em = str(u_data.get("email") or "").strip().lower()
                if "@" in cand_em and not _is_placeholder_connected_email(cand_em):
                    email_addr = cand_em
                disp_nm = str(
                    u_data.get("display_name")
                    or f"{u_data.get('first_name') or ''} {u_data.get('last_name') or ''}".strip()
                    or display_name
                    or ""
                ).strip()
                if disp_nm:
                    display_name = disp_nm
                pmi_url = str(u_data.get("personal_meeting_url") or "").strip()
                if pmi_url.startswith("http"):
                    CALENDAR_HUB_STATE.setdefault("zoom_pmi_urls", {})[conn_id] = pmi_url
        except Exception:
            pass

        if not email_addr or _is_placeholder_connected_email(email_addr):
            try:
                z_list = _composio_execute_tool("ZOOM_LIST_MEETINGS", conn_id, entity_id, {"userId": "me", "type": "upcoming", "page_size": 20})
                zd = (z_list.get("data") or {}).get("response_data") or z_list.get("data") or {}
                meetings = zd.get("meetings") if isinstance(zd, dict) else []
                if isinstance(meetings, list) and meetings:
                    for m_item in meetings:
                        if isinstance(m_item, dict):
                            he = str(m_item.get("host_email") or "").strip().lower()
                            if "@" in he and not _is_placeholder_connected_email(he):
                                email_addr = he
                                break
                    if not email_addr and isinstance(meetings[0], dict) and meetings[0].get("id"):
                        m_det = _composio_execute_proxy(conn_id, entity_id, f"/meetings/{meetings[0]['id']}", "GET")
                        md_obj = m_det.get("data") if isinstance(m_det.get("data"), dict) else {}
                        if md_obj:
                            he = str(md_obj.get("host_email") or "").strip().lower()
                            if "@" in he and not _is_placeholder_connected_email(he):
                                email_addr = he
            except Exception:
                pass

    if not display_name and email_addr and "@" in email_addr:
        display_name = email_addr.split("@")[0]

    return (email_addr, display_name)


def _discover_composio_calendar_accounts() -> List[Dict[str, Any]]:
    """
    Discovers all ACTIVE Composio connected accounts for the 3 unified Calendar & Meeting toolkits:
    - `googlecalendar` -> Google Calendar & Google Meet (`google_calendar`)
    - `outlook` -> Microsoft Outlook & MS Teams (`outlook_calendar`)
    - `zoom` -> Zoom Cloud Meetings (`zoom`)
    Automatically heals any `@connected.account` placeholder emails and removes deprecated
    standalone `googlemeet` / `microsoft_teams` entries.
    """
    _load_calendar_hub_state()
    _prune_deprecated_or_placeholder_calendar_accounts()

    headers = _get_composio_headers()
    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts", headers=headers, timeout=15)
        if r.status_code != 200:
            return CALENDAR_HUB_STATE["accounts"]
        items = r.json().get("items") or []
    except Exception as e:
        print(f"[CalendarHub] Discover connected_accounts error: {e}")
        return CALENDAR_HUB_STATE["accounts"]

    existing_by_conn_id = {
        str(a.get("composio_connection_id") or ""): a
        for a in CALENDAR_HUB_STATE["accounts"]
        if a.get("composio_connection_id")
    }

    supported_toolkits = {
        "googlecalendar": "google_calendar",
        "outlook": "outlook_calendar",
        "zoom": "zoom"
    }

    # Sort items newest first (and prefer `glennbot_cal_` calendar-specific OAuth connections)
    sorted_items = sorted(
        items,
        key=lambda x: (
            1 if str(x.get("user_id") or "").startswith("glennbot_cal_") else 0,
            str(x.get("created_at") or x.get("updated_at") or "")
        ),
        reverse=True
    )

    active_conn_ids = {
        str(x.get("id") or "").strip()
        for x in items
        if str(x.get("status") or "").upper() == "ACTIVE" and x.get("id")
    }

    # Remove any local calendar account whose Composio connection was disconnected or expired
    stale_local_ids = [
        str(a.get("id") or "")
        for a in list(CALENDAR_HUB_STATE.get("accounts") or [])
        if a.get("composio_connection_id") and str(a.get("composio_connection_id")) not in active_conn_ids
    ]
    if stale_local_ids:
        with CALENDAR_HUB_LOCK:
            CALENDAR_HUB_STATE["accounts"] = [
                a for a in CALENDAR_HUB_STATE["accounts"] if str(a.get("id") or "") not in stale_local_ids
            ]
        try:
            with db_engine.begin() as conn:
                for sid in stale_local_ids:
                    conn.execute(text("DELETE FROM glennbot_calendar_accounts WHERE id = :id"), {"id": sid})
        except Exception:
            pass

    seen_providers = set()
    for item in sorted_items:
        status = str(item.get("status") or "").upper()
        conn_id = str(item.get("id") or "").strip()
        tk_slug = str((item.get("toolkit") or {}).get("slug") or "").lower()
        if not conn_id or tk_slug not in supported_toolkits or status != "ACTIVE":
            continue

        provider = supported_toolkits[tk_slug]
        entity_id = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "glennbot_calendar_user").strip()
        if entity_id.startswith(("glennbot_admin_oauth_", "glennbot_gcontacts_")):
            continue

        # Only take the newest active connection per provider so an old account never overrides a newly connected one
        if provider in seen_providers:
            continue
        seen_providers.add(provider)

        if conn_id in existing_by_conn_id:
            ex = existing_by_conn_id[conn_id]
            ex["composio_entity_id"] = entity_id
            ex_email = str(ex.get("email_address") or "").strip().lower()
            # Detect if Zoom or Google Calendar was previously contaminated with an @outlook.com / @hotmail.com fallback email
            is_contaminated_email = (
                provider in ("zoom", "google_calendar")
                and any(d in ex_email for d in ("@outlook.", "@hotmail.", "@live.", "@msn."))
            )
            if ex_email and not _is_placeholder_connected_email(ex_email) and not is_contaminated_email and ex.get("provider") == provider:
                _upsert_calendar_account_in_db(ex, sync_cloud=False)
                continue

        email_addr, display_name = _resolve_real_email_for_calendar_toolkit(tk_slug, conn_id, entity_id, item)
        if not email_addr:
            short_id = conn_id[-6:] if len(conn_id) >= 6 else conn_id
            email_addr = f"{provider}_{short_id}@connected.account"
        if not display_name:
            display_name = email_addr.split("@")[0] if "@" in email_addr else provider

        acc_record = {
            "id": f"cal_{provider}_{conn_id}",
            "provider": provider,
            "toolkit_slug": tk_slug,
            "email_address": email_addr,
            "display_name": display_name,
            "composio_connection_id": conn_id,
            "composio_entity_id": entity_id,
            "status": "ACTIVE",
            "created_at": str(item.get("created_at") or datetime.now(MANILA_TZ).isoformat())
        }
        _upsert_calendar_account_in_db(acc_record, sync_cloud=False)
        # Also heal any existing events for this account in memory and PostgreSQL if the email changed
        if email_addr and not _is_placeholder_connected_email(email_addr):
            with CALENDAR_HUB_LOCK:
                for ev in (CALENDAR_HUB_STATE.get("events") or []):
                    if str(ev.get("account_id") or "") == acc_record["id"] or str(ev.get("provider") or "") == provider:
                        ev["email_address"] = email_addr
                        ev["organizer_email"] = email_addr
            try:
                with db_engine.begin() as conn:
                    conn.execute(
                        text("UPDATE glennbot_calendar_events SET email_address = :em, organizer_email = :em WHERE account_id = :aid OR provider = :prov"),
                        {"em": email_addr, "aid": acc_record["id"], "prov": provider}
                    )
            except Exception:
                pass

    _prune_deprecated_or_placeholder_calendar_accounts()
    threading.Thread(target=_save_calendar_hub_to_cloudinary, daemon=True).start()
    return CALENDAR_HUB_STATE["accounts"]


def _create_composio_calendar_oauth_link(provider: str, request: Request) -> Dict[str, Any]:
    _load_calendar_hub_state()
    norm_provider, toolkit_slug = _normalize_calendar_provider_key(provider)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:5001"
    proto = request.headers.get("x-forwarded-proto") or ("https" if ("ngrok" in host or "onrender" in host or "run.app" in host) else "http")
    base_url = f"{proto}://{host}"
    callback_url = f"{base_url}/api/oauth/calendar/callback?provider={norm_provider}"
    entity_id = f"glennbot_cal_{norm_provider}_{int(time.time())}"
    headers = _get_composio_headers()

    for force_flag in (False, True):
        auth_config_id = _get_or_create_calendar_composio_auth_config_id(toolkit_slug, force_lookup=force_flag)
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
                    "provider": norm_provider,
                    "toolkit_slug": toolkit_slug,
                    "auth_url": redirect_url,
                    "connected_account_id": conn_id,
                    "entity_id": entity_id,
                    "auth_config_id": auth_config_id
                }
            err_msg = (data.get("error") or {}).get("message") or data.get("message") or f"HTTP {r.status_code}"
            if force_flag:
                return {"status": "error", "message": f"Composio Calendar OAuth Error: {err_msg}"}
        except Exception as e:
            if force_flag:
                return {"status": "error", "message": f"Failed to start {norm_provider} OAuth popup: {e}"}

    return {
        "status": "error",
        "message": f"Could not resolve Composio OAuth configuration for {norm_provider}."
    }


@router.post("/api/oauth/calendar/start")
async def api_start_calendar_oauth(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    provider = str(body.get("provider") or request.query_params.get("provider") or "google_calendar").strip()
    res = await run_in_threadpool(lambda: _create_composio_calendar_oauth_link(provider, request))
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.get("/api/oauth/calendar/redirect", response_class=HTMLResponse)
async def api_redirect_calendar_oauth(request: Request, provider: str = "google_calendar"):
    norm_provider, _ = _normalize_calendar_provider_key(provider)
    label = (COMPOSIO_CALENDAR_PROVIDER_MAP.get(norm_provider) or {}).get("label") or norm_provider
    res = await run_in_threadpool(lambda: _create_composio_calendar_oauth_link(norm_provider, request))
    if res.get("status") == "success" and res.get("auth_url"):
        auth_url = res["auth_url"]
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Connecting {label} via Composio...</title>
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
        <div class="title">Connecting {label}...</div>
        <p class="sub">Redirecting you to the secure Composio OAuth2 authorization screen...</p>
        <a href="{auth_url}">Click here if not redirected automatically</a>
    </div>
    <script>
        window.location.replace({json.dumps(auth_url)});
    </script>
</body>
</html>"""
        return HTMLResponse(content=html)

    err_msg = res.get("message") or "Could not start Composio Calendar OAuth session."
    err_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Calendar OAuth Error</title></head>
<body style="background:#050b14;color:#f43f5e;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;">
    <div style="padding:28px;border:1px solid #f43f5e;border-radius:16px;background:#0f172a;max-width:400px;">
        <h3 style="margin:0 0 10px 0;">Could Not Connect {label}</h3>
        <p style="color:#cbd5e1;font-size:13px;">{err_msg}</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=err_html, status_code=400)


@router.get("/api/oauth/calendar/callback", response_class=HTMLResponse)
async def api_calendar_oauth_callback(request: Request):
    provider = str(request.query_params.get("provider") or "google_calendar").strip()
    norm_provider, _ = _normalize_calendar_provider_key(provider)
    label = (COMPOSIO_CALENDAR_PROVIDER_MAP.get(norm_provider) or {}).get("label") or norm_provider
    try:
        await run_in_threadpool(_discover_composio_calendar_accounts)
        await run_in_threadpool(_sync_external_composio_calendar_events)
    except Exception as e:
        print(f"[CalendarHub] Callback discovery warning: {e}")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{label} Connected</title>
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
            max-width: 390px;
            box-shadow: 0 0 35px rgba(0, 240, 255, 0.25);
        }}
        .title {{ color: #00f0ff; font-size: 18px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #94a3b8; font-size: 13px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="title">{label} Connected!</div>
        <p class="sub">Syncing your calendar & meeting schedule with GlennBot Automations. Closing window...</p>
    </div>
    <script>
        try {{
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'GLENNBOT_CALENDAR_OAUTH_DONE',
                    provider: '{norm_provider}'
                }}, '*');
            }}
        }} catch (e) {{}}
        setTimeout(function() {{ window.close(); }}, 900);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/api/calendar/accounts")
async def api_get_calendar_accounts(discover: bool = False):
    await run_in_threadpool(_load_calendar_hub_state)
    has_placeholder_or_deprecated = any(
        _is_placeholder_connected_email(str(a.get("email_address") or ""))
        or str(a.get("provider") or "") in ("google_meet", "microsoft_teams")
        for a in (CALENDAR_HUB_STATE.get("accounts") or [])
    )
    if discover or not CALENDAR_HUB_STATE.get("accounts") or has_placeholder_or_deprecated:
        await run_in_threadpool(_discover_composio_calendar_accounts)
    accounts = CALENDAR_HUB_STATE.get("accounts") or []
    return {
        "status": "success",
        "accounts": accounts,
        "count": len(accounts),
        "composio_shared_key_active": True
    }


@router.delete("/api/calendar/accounts/{account_id}")
async def api_delete_calendar_account(account_id: str):
    return await run_in_threadpool(lambda: _delete_calendar_account_sync(account_id))


def _delete_calendar_account_sync(account_id: str):
    _load_calendar_hub_state()
    clean_id = str(account_id or "").strip()
    removed_acc = None
    with CALENDAR_HUB_LOCK:
        remaining = []
        for a in CALENDAR_HUB_STATE.get("accounts") or []:
            if str(a.get("id") or "") == clean_id:
                removed_acc = a
            else:
                remaining.append(a)
        CALENDAR_HUB_STATE["accounts"] = remaining

    try:
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM glennbot_calendar_accounts WHERE id = :id"), {"id": clean_id})
            conn.execute(text("DELETE FROM glennbot_calendar_events WHERE account_id = :id"), {"id": clean_id})
    except Exception as e:
        print(f"[CalendarHub] Delete account DB warning: {e}")

    with CALENDAR_HUB_LOCK:
        CALENDAR_HUB_STATE["events"] = [
            ev for ev in (CALENDAR_HUB_STATE.get("events") or [])
            if str(ev.get("account_id") or "") != clean_id
        ]

    if removed_acc and removed_acc.get("composio_connection_id"):
        cid = str(removed_acc["composio_connection_id"]).strip()
        tk = str(removed_acc.get("toolkit_slug") or "").lower()
        is_shared_email = any(
            str(ea.get("composio_connection_id") or "").strip() == cid
            for ea in (EMAIL_HUB_STATE.get("accounts") or [])
        )
        if not is_shared_email or tk != "outlook":
            def _del_comp():
                try:
                    HTTP_SESSION.delete(f"{COMPOSIO_BASE_URL}/connected_accounts/{cid}", headers=_get_composio_headers(), timeout=10)
                except Exception:
                    pass
            threading.Thread(target=_del_comp, daemon=True).start()

    threading.Thread(target=_save_calendar_hub_to_cloudinary, daemon=True).start()
    return {
        "status": "success",
        "removed_id": clean_id,
        "accounts": CALENDAR_HUB_STATE.get("accounts") or [],
        "message": "Calendar account disconnected."
    }


def _remove_calendar_event_ids_from_db(event_ids: List[str]):
    clean_ids = [str(eid).strip() for eid in event_ids if str(eid or "").strip()]
    if not clean_ids:
        return
    with CALENDAR_HUB_LOCK:
        id_set = set(clean_ids)
        CALENDAR_HUB_STATE["events"] = [
            ev for ev in (CALENDAR_HUB_STATE.get("events") or [])
            if str(ev.get("id") or "") not in id_set
        ]
    try:
        with db_engine.begin() as conn:
            for cid in clean_ids:
                conn.execute(
                    text("DELETE FROM glennbot_calendar_events WHERE id = :id"),
                    {"id": cid}
                )
    except Exception as e:
        print(f"[CalendarHub] Reconcile delete DB warning: {e}")


def _deduplicate_mirrored_calendar_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    When a Zoom meeting is auto-added to the sender's Google Calendar, both Zoom (`provider=zoom`)
    and Google Calendar (`provider=google_calendar`, `meeting_platform=zoom`) return the meeting.
    This merges the mirrored Google Calendar copy into the primary Zoom event (or vice versa) so
    the GlennBot Calendar displays a single clean appointment card with full attendees & links.
    """
    zoom_by_url: Dict[str, Dict[str, Any]] = {}
    zoom_by_sig: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        if str(ev.get("provider") or "") == "zoom":
            m_url = str(ev.get("meeting_url") or "").strip().split("?")[0].rstrip("/")
            if m_url:
                zoom_by_url[m_url.lower()] = ev
            sig = f"{str(ev.get('subject') or '').strip().lower()}::{ev.get('date_str')}::{ev.get('time_str')}"
            zoom_by_sig[sig] = ev

    deduped: List[Dict[str, Any]] = []
    for ev in events:
        if str(ev.get("provider") or "") == "google_calendar" and str(ev.get("meeting_platform") or "") == "zoom":
            m_url = str(ev.get("meeting_url") or "").strip().split("?")[0].rstrip("/")
            sig = f"{str(ev.get('subject') or '').strip().lower()}::{ev.get('date_str')}::{ev.get('time_str')}"
            matched_zoom = (zoom_by_url.get(m_url.lower()) if m_url else None) or zoom_by_sig.get(sig)
            if matched_zoom is not None:
                if not matched_zoom.get("attendees") and ev.get("attendees"):
                    matched_zoom["attendees"] = ev["attendees"]
                if ev.get("html_link"):
                    matched_zoom["gcal_html_link"] = ev["html_link"]
                if ev.get("external_event_id"):
                    matched_zoom["gcal_mirror_event_id"] = ev["external_event_id"]
                continue
        deduped.append(ev)
    return deduped


def _sync_external_composio_calendar_events(month: Optional[int] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Pulls live appointments & scheduled video meetings from all connected Composio accounts:
    - Google Calendar & Meet (`GOOGLECALENDAR_EVENTS_LIST`)
    - Microsoft Outlook & Teams Calendar (`OUTLOOK_OUTLOOK_LIST_EVENTS`)
    - Zoom (`ZOOM_LIST_MEETINGS`)
    Normalizes all events, updates changed items, and reconciles remote deletions so the Calendar Modal
    always reflects real-time Google Calendar, MS Outlook/Teams, Google Meet, and Zoom schedules!
    """
    acquired = CALENDAR_SYNC_LOCK.acquire(timeout=12)
    if not acquired:
        return CALENDAR_HUB_STATE.get("events") or []
    try:
        _load_calendar_hub_state()
        accounts = CALENDAR_HUB_STATE.get("accounts") or []
        has_bad = any(
            _is_placeholder_connected_email(str(a.get("email_address") or ""))
            or str(a.get("provider") or "") in ("google_meet", "microsoft_teams")
            for a in accounts
        )
        if not accounts or has_bad:
            accounts = _discover_composio_calendar_accounts()

        now_dt = datetime.now(MANILA_TZ)
        target_year = int(year or now_dt.year)
        target_month = int(month or now_dt.month)
        try:
            month_anchor = _attach_calendar_tz(datetime(target_year, target_month, 1, 0, 0, 0), "Asia/Manila")
            range_start = min(now_dt - timedelta(days=60), month_anchor - timedelta(days=35))
            range_end = max(now_dt + timedelta(days=240), month_anchor + timedelta(days=95))
        except Exception:
            range_start = now_dt - timedelta(days=60)
            range_end = now_dt + timedelta(days=240)

        time_min_utc = range_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max_utc = range_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        active_account_ids = {
            str(a.get("id") or "")
            for a in accounts
            if str(a.get("status") or "ACTIVE").upper() == "ACTIVE" and str(a.get("id") or "")
        }
        # Remove orphaned events belonging to disconnected/removed accounts
        orphaned_ids = [
            str(ev.get("id") or "")
            for ev in (CALENDAR_HUB_STATE.get("events") or [])
            if ev.get("account_id") and str(ev.get("account_id")) not in active_account_ids
        ]
        if orphaned_ids:
            _remove_calendar_event_ids_from_db(orphaned_ids)

        # Also clean up any legacy colliding IDs (e.g. `calev_ms_AQMk...` where id != _make_calendar_event_pk)
        legacy_collision_ids = []
        for ev in list(CALENDAR_HUB_STATE.get("events") or []):
            ext_e = str(ev.get("external_event_id") or "").strip()
            acc_e = str(ev.get("account_id") or "").strip()
            prov_e = str(ev.get("provider") or "").strip()
            cur_id = str(ev.get("id") or "").strip()
            if ext_e and cur_id != _make_calendar_event_pk(prov_e, acc_e, ext_e):
                legacy_collision_ids.append(cur_id)
        if legacy_collision_ids:
            _remove_calendar_event_ids_from_db(legacy_collision_ids)

        existing_by_ext_id = {
            f"{ev.get('account_id')}::{ev.get('external_event_id')}": ev
            for ev in (CALENDAR_HUB_STATE.get("events") or [])
            if ev.get("external_event_id")
        }
        recent_resched_map = CALENDAR_HUB_STATE.get("recently_rescheduled_events") or {}
        now_ts_sync = time.time()

        for acc in accounts:
            if str(acc.get("status") or "ACTIVE").upper() != "ACTIVE":
                continue
            acc_id = str(acc.get("id") or "")
            provider = str(acc.get("provider") or "")
            tk_slug = str(acc.get("toolkit_slug") or "")
            conn_id = str(acc.get("composio_connection_id") or "").strip()
            entity_id = str(acc.get("composio_entity_id") or "glennbot_calendar_user").strip()
            acc_email = str(acc.get("email_address") or "").strip()
            if not conn_id:
                continue

            # 1. GOOGLE CALENDAR & GOOGLE MEET EVENTS
            if tk_slug == "googlecalendar" or provider == "google_calendar":
                try:
                    res = _composio_execute_tool(
                        "GOOGLECALENDAR_EVENTS_LIST",
                        conn_id,
                        entity_id,
                        {
                            "calendarId": "primary",
                            "timeMin": time_min_utc,
                            "timeMax": time_max_utc,
                            "singleEvents": True,
                            "orderBy": "startTime",
                            "maxResults": 250
                        }
                    )
                    d_obj = (res.get("data") or {}).get("response_data") or res.get("data") or {}
                    items = d_obj.get("items") if isinstance(d_obj, dict) else None
                    if res.get("successful", False) and isinstance(items, list):
                        # Auto-heal account email if it was previously saved with a `@connected.account` placeholder
                        if _is_placeholder_connected_email(acc_email):
                            healed_em, healed_disp = _extract_gcal_owner_email_from_events_payload(d_obj)
                            if not healed_em or _is_placeholder_connected_email(healed_em):
                                healed_em, healed_disp = _resolve_real_email_for_calendar_toolkit("googlecalendar", conn_id, entity_id, {})
                            if healed_em and not _is_placeholder_connected_email(healed_em):
                                acc_email = healed_em
                                acc["email_address"] = healed_em
                                if healed_disp:
                                    acc["display_name"] = healed_disp
                                _upsert_calendar_account_in_db(acc, sync_cloud=False)

                        deleted_ext_set = set(CALENDAR_HUB_STATE.get("deleted_external_ids") or set())
                        live_gcal_ext_ids = set()
                        for item in items:
                            if not isinstance(item, dict) or str(item.get("status") or "").lower() == "cancelled":
                                continue
                            ext_id = str(item.get("id") or "").strip()
                            if not ext_id or ext_id in deleted_ext_set or ext_id.split("_")[0] in deleted_ext_set:
                                continue
                            if str(item.get("summary") or "").strip().upper().startswith("[CANCELLED]"):
                                continue
                            start_obj = item.get("start") or {}
                            end_obj = item.get("end") or {}
                            s_iso = str(start_obj.get("dateTime") or start_obj.get("date") or "").strip()
                            e_iso = str(end_obj.get("dateTime") or end_obj.get("date") or "").strip()
                            if not s_iso:
                                continue
                            live_gcal_ext_ids.add(ext_id)

                            hangout_link = str(item.get("hangoutLink") or "").strip()
                            conf_data = item.get("conferenceData") or {}
                            if not hangout_link and isinstance(conf_data, dict):
                                for ep in (conf_data.get("entryPoints") or []):
                                    if isinstance(ep, dict) and ep.get("uri"):
                                        hangout_link = str(ep.get("uri")).strip()
                                        break

                            loc_str = str(item.get("location") or "").strip()
                            desc_str = str(item.get("description") or "").strip()
                            detected_url = hangout_link
                            if not detected_url:
                                url_m = re.search(
                                    r"https?://(?:meet\.google\.com|[a-z0-9.-]*zoom\.us|teams\.microsoft\.com|teams\.live\.com)/[^\s\"'<>)+]+",
                                    f"{loc_str} {desc_str}",
                                    re.I
                                )
                                if url_m:
                                    detected_url = url_m.group(0).strip()

                            if "zoom.us" in detected_url.lower():
                                m_plat = "zoom"
                            elif "teams." in detected_url.lower():
                                m_plat = "microsoft_teams"
                            elif detected_url:
                                m_plat = "google_meet"
                            else:
                                m_plat = "none"
                            m_url = detected_url

                            raw_att = item.get("attendees") or []
                            parsed_att = []
                            for a_item in raw_att:
                                if isinstance(a_item, dict) and a_item.get("email"):
                                    em_str = str(a_item.get("email") or "").strip()
                                    if acc_email and em_str.lower() == acc_email.lower():
                                        continue
                                    parsed_att.append({
                                        "email": em_str,
                                        "name": str(a_item.get("displayName") or "").strip(),
                                        "status": str(a_item.get("responseStatus") or "needsAction")
                                    })

                            org_email = str((item.get("organizer") or {}).get("email") or acc_email).strip()
                            existing_ev = existing_by_ext_id.get(f"{acc_id}::{ext_id}")
                            rec_override = recent_resched_map.get(ext_id) or recent_resched_map.get(ext_id.split("_")[0])
                            if isinstance(rec_override, dict) and (now_ts_sync - float(rec_override.get("ts") or 0)) < 35.0:
                                s_iso = str(rec_override.get("start_iso") or s_iso)
                                e_iso = str(rec_override.get("end_iso") or e_iso)
                                desc_str = str(rec_override.get("description") if rec_override.get("description") is not None else desc_str)
                            preserved_status = (
                                "rescheduled"
                                if (existing_ev and str(existing_ev.get("status") or "").lower() == "rescheduled") or rec_override
                                else str(item.get("status") or "confirmed")
                            )
                            ev_record = {
                                "id": _make_calendar_event_pk("google_calendar", acc_id, ext_id),
                                "external_event_id": ext_id,
                                "account_id": acc_id,
                                "provider": "google_calendar",
                                "email_address": acc_email,
                                "subject": str((rec_override or {}).get("subject") or item.get("summary") or "(No Subject)").strip(),
                                "description": desc_str,
                                "location": loc_str,
                                "start_iso": s_iso,
                                "end_iso": e_iso or s_iso,
                                "timezone": str(start_obj.get("timeZone") or "Asia/Manila"),
                                "meeting_platform": m_plat,
                                "meeting_url": m_url,
                                "is_online_meeting": bool(m_url),
                                "organizer_email": org_email,
                                "attendees": parsed_att if parsed_att else (existing_ev.get("attendees", []) if existing_ev else []),
                                "availability": "free" if str(item.get("transparency") or "").lower() == "transparent" else "busy",
                                "reminder_minutes": 15,
                                "status": preserved_status,
                                "html_link": str(item.get("htmlLink") or "")
                            }
                            _upsert_calendar_event_in_db(ev_record, sync_cloud=False)

                        # Reconcile external deletions on Google Calendar within the synced time window
                        stale_gcal_ids = []
                        for ev in list(CALENDAR_HUB_STATE.get("events") or []):
                            if str(ev.get("account_id") or "") == acc_id or str(ev.get("provider") or "") == "google_calendar":
                                ext_ev_id = str(ev.get("external_event_id") or "").strip()
                                if ext_ev_id and ext_ev_id not in live_gcal_ext_ids:
                                    ev_dt = _parse_calendar_iso_datetime(str(ev.get("start_iso") or ""), str(ev.get("timezone") or "Asia/Manila"))
                                    if not ev_dt or (range_start <= ev_dt <= range_end):
                                        stale_gcal_ids.append(str(ev.get("id") or ""))
                        if stale_gcal_ids:
                            _remove_calendar_event_ids_from_db(stale_gcal_ids)
                except Exception as e:
                    print(f"[CalendarHub] Google Calendar sync warning ({acc_email}): {e}")

            # 2. MICROSOFT OUTLOOK & MS TEAMS CALENDAR EVENTS
            elif tk_slug == "outlook" or provider == "outlook_calendar":
                try:
                    res = _composio_execute_tool(
                        "OUTLOOK_OUTLOOK_LIST_EVENTS",
                        conn_id,
                        entity_id,
                        {
                            "user_id": "me",
                            "top": 100,
                            "timezone": "Asia/Manila"
                        }
                    )
                    d_obj = (res.get("data") or {}).get("response_data") or res.get("data") or {}
                    items = d_obj.get("value") if isinstance(d_obj, dict) else None
                    if res.get("successful", False) and isinstance(items, list):
                        deleted_ext_set = set(CALENDAR_HUB_STATE.get("deleted_external_ids") or set())
                        live_ms_ext_ids = set()
                        for item in items:
                            if not isinstance(item, dict) or item.get("isCancelled"):
                                continue
                            ext_id = str(item.get("id") or "").strip()
                            if not ext_id or ext_id in deleted_ext_set:
                                continue
                            if str(item.get("subject") or "").strip().upper().startswith("[CANCELLED]"):
                                continue
                            start_obj = item.get("start") or {}
                            end_obj = item.get("end") or {}
                            s_iso = str(start_obj.get("dateTime") or "").strip()
                            e_iso = str(end_obj.get("dateTime") or "").strip()
                            item_tz = str(start_obj.get("timeZone") or "Asia/Manila").strip()
                            if not s_iso:
                                continue
                            live_ms_ext_ids.add(ext_id)

                            existing_ev = existing_by_ext_id.get(f"{acc_id}::{ext_id}")
                            rec_override = recent_resched_map.get(ext_id)
                            online_m = item.get("onlineMeeting") if isinstance(item.get("onlineMeeting"), dict) else {}
                            join_url = str(online_m.get("joinUrl") or item.get("onlineMeetingUrl") or "").strip()
                            loc_str = str((item.get("location") or {}).get("displayName") or "").strip()
                            desc_str = str(item.get("bodyPreview") or "").strip()
                            if isinstance(rec_override, dict) and (now_ts_sync - float(rec_override.get("ts") or 0)) < 35.0:
                                s_iso = str(rec_override.get("start_iso") or s_iso)
                                e_iso = str(rec_override.get("end_iso") or e_iso)
                                desc_str = str(rec_override.get("description") if rec_override.get("description") is not None else desc_str)
                            if not join_url:
                                url_m = re.search(r"https?://(?:teams\.microsoft\.com|teams\.live\.com|meet\.google\.com|[a-z0-9.-]*zoom\.us)/[^\s\"'<>)+]+", f"{loc_str} {desc_str}", re.I)
                                if url_m:
                                    join_url = url_m.group(0).strip()

                            is_online = bool(item.get("isOnlineMeeting") or join_url)
                            om_prov = str(item.get("onlineMeetingProvider") or "").lower()
                            loc_desc_low = f"{loc_str} {desc_str}".lower()
                            if "zoom.us" in join_url.lower():
                                m_plat = "zoom"
                            elif "meet.google.com" in join_url.lower():
                                m_plat = "google_meet"
                            elif (
                                is_online
                                or "teams" in om_prov
                                or "teams" in join_url.lower()
                                or "microsoft teams" in loc_desc_low
                                or (existing_ev and str(existing_ev.get("meeting_platform") or "") == "microsoft_teams")
                            ):
                                m_plat = "microsoft_teams"
                                is_online = True
                            else:
                                m_plat = "none"
                                is_online = False

                            raw_att = item.get("attendees") or []
                            parsed_att = []
                            for a_item in raw_att:
                                if isinstance(a_item, dict):
                                    em_obj = a_item.get("emailAddress") or {}
                                    st_obj = a_item.get("status") or {}
                                    em_addr = str(em_obj.get("address") or "").strip()
                                    if em_addr and (not acc_email or em_addr.lower() != acc_email.lower()):
                                        parsed_att.append({
                                            "email": em_addr,
                                            "name": str(em_obj.get("name") or "").strip(),
                                            "status": str(st_obj.get("response") or "none")
                                        })

                            org_email = str(((item.get("organizer") or {}).get("emailAddress") or {}).get("address") or acc_email).strip()
                            preserved_status = (
                                "rescheduled"
                                if (existing_ev and str(existing_ev.get("status") or "").lower() == "rescheduled") or rec_override
                                else "confirmed"
                            )
                            ev_record = {
                                "id": _make_calendar_event_pk("outlook_calendar", acc_id, ext_id),
                                "external_event_id": ext_id,
                                "account_id": acc_id,
                                "provider": "outlook_calendar",
                                "email_address": acc_email,
                                "subject": str((rec_override or {}).get("subject") or item.get("subject") or "(No Subject)").strip(),
                                "description": desc_str,
                                "location": loc_str,
                                "start_iso": s_iso,
                                "end_iso": e_iso or s_iso,
                                "timezone": item_tz,
                                "meeting_platform": m_plat,
                                "meeting_url": join_url or (existing_ev.get("meeting_url", "") if (existing_ev and m_plat != "none") else ""),
                                "is_online_meeting": bool(m_plat != "none" or is_online),
                                "organizer_email": org_email,
                                "attendees": parsed_att if parsed_att else (existing_ev.get("attendees", []) if existing_ev else []),
                                "availability": str(item.get("showAs") or "busy").lower(),
                                "reminder_minutes": int(item.get("reminderMinutesBeforeStart") or 15),
                                "status": preserved_status,
                                "html_link": str(item.get("webLink") or "")
                            }
                            _upsert_calendar_event_in_db(ev_record, sync_cloud=False)

                        # Reconcile external deletions on Microsoft Outlook Calendar
                        stale_ms_ids = [
                            str(ev.get("id") or "")
                            for ev in list(CALENDAR_HUB_STATE.get("events") or [])
                            if (str(ev.get("account_id") or "") == acc_id or str(ev.get("provider") or "") == "outlook_calendar")
                            and str(ev.get("external_event_id") or "").strip() not in live_ms_ext_ids
                        ]
                        if stale_ms_ids:
                            _remove_calendar_event_ids_from_db(stale_ms_ids)
                except Exception as e:
                    print(f"[CalendarHub] Outlook Calendar sync warning ({acc_email}): {e}")

            # 3. ZOOM SCHEDULED & UPCOMING MEETINGS (RATE-LIMIT-SAFE LIVE SYNC)
            elif tk_slug == "zoom" or provider == "zoom":
                try:
                    # Zoom enforces a strict 100 requests/day limit on `GET /users/me/meetings` (`ZOOM_LIST_MEETINGS`).
                    # Throttle full-list polling to once every 180s (with a single `type="upcoming"` call) and fall back
                    # to per-meeting `GET /meetings/{id}` (Light rate-limit bucket, no daily cap) in between or during 429 cooldown!
                    combined_meetings: List[dict] = []
                    seen_zoom_ids = set()
                    any_zoom_list_ok = False
                    last_z_list_ts = float(CALENDAR_HUB_STATE.get("last_zoom_list_sync_ts") or 0.0)
                    z_rl_until = float(CALENDAR_HUB_STATE.get("zoom_list_rate_limit_until") or 0.0)
                    has_any_zoom_ev = any(
                        str(ev.get("provider") or "") == "zoom"
                        for ev in (CALENDAR_HUB_STATE.get("events") or [])
                    )
                    should_call_zoom_list = (
                        now_ts_sync >= z_rl_until
                        and ((now_ts_sync - last_z_list_ts >= 180.0) or not has_any_zoom_ev)
                    )

                    if should_call_zoom_list:
                        res = _composio_execute_tool(
                            "ZOOM_LIST_MEETINGS",
                            conn_id,
                            entity_id,
                            {"userId": "me", "type": "upcoming", "page_size": 100}
                        )
                        d_obj = (res.get("data") or {}).get("response_data") or res.get("data") or {}
                        m_list = d_obj.get("meetings") if isinstance(d_obj, dict) else None
                        if res.get("successful", False) and isinstance(m_list, list):
                            any_zoom_list_ok = True
                            CALENDAR_HUB_STATE["last_zoom_list_sync_ts"] = now_ts_sync
                            for m_it in m_list:
                                if isinstance(m_it, dict):
                                    mid = str(m_it.get("id") or "").strip()
                                    if mid and mid not in seen_zoom_ids:
                                        seen_zoom_ids.add(mid)
                                        combined_meetings.append(m_it)
                        elif res.get("rate_limited") or "429" in str(res.get("error") or "") or "maximum daily rate limit" in str(res.get("error") or ""):
                            CALENDAR_HUB_STATE["zoom_list_rate_limit_until"] = now_ts_sync + 900.0

                    if any_zoom_list_ok:
                        session_cancelled_zoom_ids = set(CALENDAR_HUB_STATE.get("session_cancelled_zoom_ids") or set())
                        deleted_ext_set = set(CALENDAR_HUB_STATE.get("deleted_external_ids") or set())
                        live_zoom_ext_ids = set()
                        restored_zoom_ext_ids = set()
                        for m_item in combined_meetings:
                            if not isinstance(m_item, dict):
                                continue
                            topic_str = str(m_item.get("topic") or "Zoom Meeting").strip()
                            if topic_str == "GlennBot Zoom Account Verification" or topic_str.upper().startswith("[CANCELLED]"):
                                continue
                            ext_id = str(m_item.get("id") or "").strip()
                            if not ext_id or ext_id in session_cancelled_zoom_ids:
                                continue
                            # Support both standard start_time and recurring occurrences[0]
                            s_iso = str(m_item.get("start_time") or "").strip()
                            dur_m = int(m_item.get("duration") or 60)
                            if not s_iso and isinstance(m_item.get("occurrences"), list) and m_item["occurrences"]:
                                first_occ = m_item["occurrences"][0]
                                if isinstance(first_occ, dict):
                                    s_iso = str(first_occ.get("start_time") or "").strip()
                                    dur_m = int(first_occ.get("duration") or dur_m)
                            if not s_iso:
                                continue
                            if ext_id in deleted_ext_set:
                                deleted_ext_set.discard(ext_id)
                                restored_zoom_ext_ids.add(ext_id)

                            live_zoom_ext_ids.add(ext_id)
                            join_url = str(m_item.get("join_url") or "").strip()
                            host_em = str(m_item.get("host_email") or "").strip().lower()
                            acc_is_contaminated = _is_placeholder_connected_email(acc_email) or any(
                                d in acc_email.lower() for d in ("@outlook.", "@hotmail.", "@live.", "@msn.")
                            )
                            if not host_em and acc_is_contaminated and ext_id:
                                try:
                                    m_det = _composio_execute_proxy(conn_id, entity_id, f"/meetings/{ext_id}", "GET")
                                    md_obj = m_det.get("data") if isinstance(m_det.get("data"), dict) else {}
                                    if md_obj:
                                        host_em = str(md_obj.get("host_email") or "").strip().lower()
                                except Exception:
                                    pass
                            if "@" in host_em and not _is_placeholder_connected_email(host_em) and (acc_is_contaminated or host_em != acc_email.lower()):
                                acc["email_address"] = host_em
                                acc["display_name"] = host_em.split("@")[0]
                                acc_email = host_em
                                _upsert_calendar_account_in_db(acc, sync_cloud=False)

                            existing_ev = existing_by_ext_id.get(f"{acc_id}::{ext_id}")
                            rec_override = recent_resched_map.get(ext_id)
                            desc_str = str(m_item.get("agenda") or "").strip()
                            if not desc_str and existing_ev:
                                desc_str = str(existing_ev.get("description") or "").strip()
                            if isinstance(rec_override, dict) and (now_ts_sync - float(rec_override.get("ts") or 0)) < 35.0:
                                s_iso = str(rec_override.get("start_iso") or s_iso)
                                dur_m = int(rec_override.get("duration_minutes") or dur_m)
                                topic_str = str(rec_override.get("subject") or topic_str)
                                desc_str = str(rec_override.get("description") if rec_override.get("description") is not None else desc_str)
                            preserved_status = (
                                "rescheduled"
                                if (existing_ev and str(existing_ev.get("status") or "").lower() == "rescheduled") or rec_override
                                else "confirmed"
                            )
                            ev_record = {
                                "id": _make_calendar_event_pk("zoom", acc_id, ext_id),
                                "external_event_id": ext_id,
                                "account_id": acc_id,
                                "provider": "zoom",
                                "email_address": acc_email,
                                "subject": topic_str,
                                "description": desc_str,
                                "location": "Zoom Cloud Meeting",
                                "start_iso": s_iso,
                                "end_iso": "",
                                "duration_minutes": dur_m,
                                "timezone": str(m_item.get("timezone") or "Asia/Manila"),
                                "meeting_platform": "zoom",
                                "meeting_url": join_url,
                                "is_online_meeting": True,
                                "organizer_email": acc_email,
                                "attendees": existing_ev.get("attendees", []) if existing_ev else [],
                                "availability": "busy",
                                "reminder_minutes": 15,
                                "status": preserved_status,
                                "html_link": join_url
                            }
                            _upsert_calendar_event_in_db(ev_record, sync_cloud=False)

                        if restored_zoom_ext_ids:
                            with CALENDAR_HUB_LOCK:
                                CALENDAR_HUB_STATE["deleted_external_ids"] = deleted_ext_set
                            try:
                                with db_engine.begin() as conn:
                                    for r_zid in restored_zoom_ext_ids:
                                        conn.execute(
                                            text("DELETE FROM glennbot_calendar_deleted_events WHERE external_event_id = :ext_id"),
                                            {"ext_id": r_zid}
                                        )
                            except Exception:
                                pass

                        # Reconcile external deletions on Zoom
                        stale_zoom_ids = [
                            str(ev.get("id") or "")
                            for ev in list(CALENDAR_HUB_STATE.get("events") or [])
                            if (str(ev.get("account_id") or "") == acc_id or str(ev.get("provider") or "") == "zoom")
                            and str(ev.get("external_event_id") or "").strip() not in live_zoom_ext_ids
                        ]
                        if stale_zoom_ids:
                            _remove_calendar_event_ids_from_db(stale_zoom_ids)
                    else:
                        # Lightweight per-meeting live sync via `GET /meetings/{id}` (uses Zoom's Light rate-limit bucket, no daily cap!)
                        last_indiv_ts = float(CALENDAR_HUB_STATE.get("last_zoom_indiv_sync_ts") or 0.0)
                        if now_ts_sync - last_indiv_ts >= 25.0:
                            CALENDAR_HUB_STATE["last_zoom_indiv_sync_ts"] = now_ts_sync
                            session_cancelled_zoom_ids = set(CALENDAR_HUB_STATE.get("session_cancelled_zoom_ids") or set())
                            stale_indiv_ids = []
                            stored_zoom_evs = [
                                ev for ev in list(CALENDAR_HUB_STATE.get("events") or [])
                                if (str(ev.get("account_id") or "") == acc_id or str(ev.get("provider") or "") == "zoom")
                            ]
                            for z_ev in stored_zoom_evs[:15]:
                                ext_id = str(z_ev.get("external_event_id") or "").strip()
                                if not ext_id or not ext_id.isdigit():
                                    continue
                                if ext_id in session_cancelled_zoom_ids:
                                    stale_indiv_ids.append(str(z_ev.get("id") or ""))
                                    continue
                                m_det = _composio_execute_proxy(conn_id, entity_id, f"/meetings/{ext_id}", "GET")
                                m_status = int(m_det.get("status") or 0)
                                md_obj = m_det.get("data") if isinstance(m_det.get("data"), dict) else {}
                                if m_status == 404 or (isinstance(md_obj, dict) and md_obj.get("code") == 3001):
                                    stale_indiv_ids.append(str(z_ev.get("id") or ""))
                                    continue
                                if m_det.get("successful") and md_obj:
                                    topic_str = str(md_obj.get("topic") or z_ev.get("subject") or "Zoom Meeting").strip()
                                    if topic_str.upper().startswith("[CANCELLED]"):
                                        stale_indiv_ids.append(str(z_ev.get("id") or ""))
                                        continue
                                    s_iso = str(md_obj.get("start_time") or z_ev.get("start_iso") or "").strip()
                                    dur_m = int(md_obj.get("duration") or z_ev.get("duration_minutes") or 60)
                                    join_url = str(md_obj.get("join_url") or z_ev.get("meeting_url") or "").strip()
                                    desc_str = str(md_obj.get("agenda") if md_obj.get("agenda") is not None else (z_ev.get("description") or "")).strip()
                                    rec_override = recent_resched_map.get(ext_id)
                                    if isinstance(rec_override, dict) and (now_ts_sync - float(rec_override.get("ts") or 0)) < 35.0:
                                        s_iso = str(rec_override.get("start_iso") or s_iso)
                                        dur_m = int(rec_override.get("duration_minutes") or dur_m)
                                        topic_str = str(rec_override.get("subject") or topic_str)
                                        desc_str = str(rec_override.get("description") if rec_override.get("description") is not None else desc_str)
                                    updated_z = dict(z_ev)
                                    updated_z.update({
                                        "account_id": acc_id,
                                        "email_address": acc_email,
                                        "organizer_email": acc_email,
                                        "subject": topic_str,
                                        "description": desc_str,
                                        "start_iso": s_iso,
                                        "duration_minutes": dur_m,
                                        "timezone": str(md_obj.get("timezone") or z_ev.get("timezone") or "Asia/Manila"),
                                        "meeting_url": join_url,
                                        "html_link": join_url
                                    })
                                    _upsert_calendar_event_in_db(updated_z, sync_cloud=False)
                            if stale_indiv_ids:
                                _remove_calendar_event_ids_from_db(stale_indiv_ids)
                except Exception as e:
                    print(f"[CalendarHub] Zoom sync warning ({acc_email}): {e}")

        CALENDAR_HUB_STATE["last_live_sync_ts"] = time.time()
        return CALENDAR_HUB_STATE.get("events") or []
    finally:
        CALENDAR_SYNC_LOCK.release()


@router.get("/api/calendar/events")
async def api_get_calendar_events(
    month: Optional[int] = None,
    year: Optional[int] = None,
    account_id: str = "",
    meeting_filter: str = "all",
    sync: bool = True
):
    await run_in_threadpool(_load_calendar_hub_state)
    last_ts = float(CALENDAR_HUB_STATE.get("last_live_sync_ts") or 0.0)
    has_cached_events = bool(CALENDAR_HUB_STATE.get("events"))
    if not has_cached_events or (sync and not CALENDAR_SYNC_LOCK.locked() and (time.time() - last_ts > 3.5)):
        await run_in_threadpool(lambda: _sync_external_composio_calendar_events(month=month, year=year))
    elif sync and not CALENDAR_SYNC_LOCK.locked():
        BG_SYNC_EXECUTOR.submit(_sync_external_composio_calendar_events, month, year)

    all_events = [
        _enrich_calendar_event_date_fields(ev)
        for ev in (CALENDAR_HUB_STATE.get("events") or [])
    ]

    clean_acc = str(account_id or "").strip()
    if clean_acc and clean_acc != "all":
        all_events = [ev for ev in all_events if str(ev.get("account_id") or "") == clean_acc or str(ev.get("provider") or "") == clean_acc]
    else:
        all_events = _deduplicate_mirrored_calendar_events(all_events)

    clean_mf = str(meeting_filter or "all").strip().lower()
    if clean_mf == "with_meeting":
        all_events = [ev for ev in all_events if ev.get("is_online_meeting")]
    elif clean_mf == "without_meeting":
        all_events = [ev for ev in all_events if not ev.get("is_online_meeting")]
    elif clean_mf in ("google_meet", "microsoft_teams", "zoom"):
        all_events = [ev for ev in all_events if str(ev.get("meeting_platform") or "") == clean_mf]

    all_events.sort(key=lambda x: str(x.get("start_iso") or ""))
    return {
        "status": "success",
        "events": all_events,
        "count": len(all_events),
        "accounts": CALENDAR_HUB_STATE.get("accounts") or []
    }


