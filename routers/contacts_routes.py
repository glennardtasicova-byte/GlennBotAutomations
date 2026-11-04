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


# =========================================================================
# --- CLIENT CONTACTS & LEAD CRM DATABASE (DB + CLOUDINARY + WHATSAPP/TELEGRAM SYNC & DEDUP) ---
# =========================================================================
CONTACTS_CLOUDINARY_PUBLIC_ID = "glennbot_state/crm_contacts_v1.json"
CONTACTS_CRM_LOCK = threading.Lock()
CONTACTS_CRM_STATE = {
    "contacts": [],
    "loaded_from_cloud": False,
    "table_initialized": False
}


def _normalize_phone_key(phone_str: str) -> str:
    """
    Normalizes Philippine and international phone numbers so that:
    '0917-123-4567', '+63 917 123 4567', '639171234567' -> '639171234567'
    Returns empty string if fewer than 7 digits.
    """
    raw = str(phone_str or "").strip()
    if not raw:
        return ""
    if "@" in raw:
        raw = raw.split("@")[0].strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7:
        return ""
    if len(digits) == 11 and digits.startswith("09"):
        return "63" + digits[1:]
    if len(digits) == 10 and digits.startswith("9"):
        return "63" + digits
    return digits


def _normalize_email_key(email_str: str) -> str:
    clean = str(email_str or "").strip().lower()
    if "@" in clean and "." in clean.split("@")[-1]:
        return clean
    return ""


def _smart_parse_name_backend(
    raw_name: str,
    platform: str = "manual",
    sample_text: str = "",
    explicit_phone: str = "",
    explicit_email: str = ""
) -> Dict[str, str]:
    raw = str(raw_name or "").strip()
    text_sample = str(sample_text or "")

    detected_email = str(explicit_email or "").strip()
    if not detected_email and text_sample:
        m_em = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text_sample)
        if m_em:
            detected_email = m_em.group(0)

    detected_phone = str(explicit_phone or "").strip()
    if not detected_phone and text_sample:
        m_ph = re.search(r"(?:\+?63[\s\-]?|0)9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b|(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b", text_sample)
        if m_ph:
            detected_phone = m_ph.group(0).strip()

    # Check if raw name is "Full Name (@handle)"
    extracted_handle = ""
    m_paren = re.match(r"^(.*?)\s*\((@[A-Za-z0-9_.\-]+)\)\s*$", raw)
    if m_paren:
        raw = m_paren.group(1).strip()
        extracted_handle = m_paren.group(2).strip()

    if not detected_phone and platform == "whatsapp":
        digits_cand = re.sub(r"\D", "", raw)
        if 9 <= len(digits_cand) <= 15:
            detected_phone = raw if raw.startswith("+") else f"+{digits_cand}"

    if not raw:
        return {
            "first_name": "",
            "middle_name": "",
            "last_name": "",
            "social_username": extracted_handle,
            "contact_number": detected_phone,
            "email_address": detected_email
        }

    # Check if raw is purely a phone number
    if re.fullmatch(r"[\+\d\s\-\(\)]+", raw) and len(re.sub(r"\D", "", raw)) >= 7:
        if not detected_phone:
            detected_phone = raw
        return {
            "first_name": raw,
            "middle_name": "",
            "last_name": "",
            "social_username": extracted_handle or raw,
            "contact_number": detected_phone,
            "email_address": detected_email
        }

    starts_with_at = raw.startswith("@")
    has_no_spaces = (" " not in raw)
    is_handle = starts_with_at or has_no_spaces

    compound_surnames = {"dela", "de", "del", "delos", "san", "sta", "sta.", "st", "st.", "van", "von", "da", "dos"}

    def _tc(w: str) -> str:
        w = w.strip()
        if not w:
            return ""
        if len(w) <= 2 and w.endswith("."):
            return w.upper()
        return w[0].upper() + w[1:].lower()

    if not is_handle:
        clean_full = re.sub(r"[^\w\s.\-']", " ", raw, flags=re.UNICODE)
        parts = [p for p in clean_full.split() if p]
        first_name, middle_name, last_name = "", "", ""
        if len(parts) == 1:
            first_name = _tc(parts[0])
        elif len(parts) == 2:
            first_name, last_name = _tc(parts[0]), _tc(parts[1])
        elif len(parts) == 3:
            if parts[1].lower() in compound_surnames:
                first_name = _tc(parts[0])
                last_name = f"{_tc(parts[1])} {_tc(parts[2])}"
            else:
                first_name, middle_name, last_name = _tc(parts[0]), _tc(parts[1]), _tc(parts[2])
        elif len(parts) >= 4:
            if parts[-2].lower() in compound_surnames:
                last_name = f"{_tc(parts[-2])} {_tc(parts[-1])}"
                rem = parts[:-2]
                first_name = " ".join(_tc(x) for x in rem[:-1]) if len(rem) > 1 else _tc(rem[0])
                middle_name = _tc(rem[-1]) if len(rem) > 1 else ""
            else:
                last_name = _tc(parts[-1])
                middle_name = _tc(parts[-2])
                first_name = " ".join(_tc(x) for x in parts[:-2])

        return {
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "social_username": "" if platform in ("facebook", "instagram") else extracted_handle,
            "contact_number": detected_phone,
            "email_address": detected_email
        }

    handle_fmt = raw if raw.startswith("@") else f"@{raw}"
    stripped = re.sub(r"^@+", "", raw)
    stripped = re.sub(r"([a-z])([A-Z])", r"\1 \2", stripped)
    stripped = re.sub(r"[._\-]+", " ", stripped)
    stripped = re.sub(r"\d+", " ", stripped)
    noise = {"official", "real", "tv", "ph", "vlog", "vlogs", "yt", "ig", "channel", "gaming", "shop", "store", "the", "iam", "its"}
    raw_tokens = [re.sub(r"[^a-zA-Z']", "", t) for t in stripped.split()]
    raw_tokens = [t for t in raw_tokens if len(t) >= 2]
    filtered = [t for t in raw_tokens if t.lower() not in noise]
    tokens = filtered if filtered else raw_tokens

    first_name, middle_name, last_name = "", "", ""
    if not tokens:
        first_name = raw.lstrip("@")
    elif len(tokens) == 1:
        first_name = _tc(tokens[0])
    elif len(tokens) == 2:
        first_name, last_name = _tc(tokens[0]), _tc(tokens[1])
    else:
        first_name = _tc(tokens[0])
        middle_name = _tc(tokens[1])
        last_name = " ".join(_tc(x) for x in tokens[2:])

    return {
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "social_username": "" if (platform in ("facebook", "instagram") and not extracted_handle) else (extracted_handle or handle_fmt),
        "contact_number": detected_phone,
        "email_address": detected_email
    }


def _combine_two_contact_records(primary: dict, secondary: dict) -> dict:
    """
    Combines two duplicate CRM contact records (matched by Phone Number, Email Address,
    or Social Username) into 1 unified CRM contact record while preserving all platforms
    and non-empty details.
    """
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    merged = dict(primary)

    def _is_better_name(cand: str, curr: str) -> bool:
        c_s = str(cand or "").strip()
        cur_s = str(curr or "").strip()
        if not c_s:
            return False
        if not cur_s:
            return True
        # Prefer alphabetic name over phone digits or @handle
        cur_is_num_or_handle = cur_s.startswith("+") or cur_s.startswith("@") or cur_s.replace(" ", "").isdigit()
        cand_is_num_or_handle = c_s.startswith("+") or c_s.startswith("@") or c_s.replace(" ", "").isdigit()
        if cur_is_num_or_handle and not cand_is_num_or_handle:
            return True
        return False

    if _is_better_name(secondary.get("first_name"), merged.get("first_name")):
        merged["first_name"] = str(secondary.get("first_name") or "").strip()
    if not str(merged.get("middle_name") or "").strip() and str(secondary.get("middle_name") or "").strip():
        merged["middle_name"] = str(secondary.get("middle_name") or "").strip()
    if not str(merged.get("last_name") or "").strip() and str(secondary.get("last_name") or "").strip():
        merged["last_name"] = str(secondary.get("last_name") or "").strip()

    # Contact number & Email
    if not str(merged.get("contact_number") or "").strip() and str(secondary.get("contact_number") or "").strip():
        merged["contact_number"] = str(secondary.get("contact_number") or "").strip()
    if not str(merged.get("email_address") or "").strip() and str(secondary.get("email_address") or "").strip():
        merged["email_address"] = str(secondary.get("email_address") or "").strip()

    # Combine platforms (stored in source_type as comma-separated platforms if multiple, and keep primary platform)
    p1 = str(merged.get("platform") or "manual").strip().lower()
    p2 = str(secondary.get("platform") or "manual").strip().lower()
    if p1 == "manual" and p2 != "manual":
        merged["platform"] = p2

    # Track all combined platforms in source_type / linked_platforms
    existing_plats = []
    for raw_p in (
        str(merged.get("platform") or ""),
        str(secondary.get("platform") or ""),
        *str(merged.get("source_type") or "").split(","),
        *str(secondary.get("source_type") or "").split(",")
    ):
        rp = raw_p.strip().lower()
        if rp in ("facebook", "instagram", "tiktok", "youtube", "whatsapp", "telegram", "gmail", "microsoft", "imap", "google_contacts", "manual"):
            if rp not in existing_plats:
                existing_plats.append(rp)
    if len(existing_plats) > 1 and "manual" in existing_plats:
        # Keep manual too so user knows it was also manually saved + social
        pass
    if existing_plats:
        merged["source_type"] = ",".join(existing_plats)

    # Combine social usernames if distinct
    u1 = str(merged.get("social_username") or "").strip()
    u2 = str(secondary.get("social_username") or "").strip()
    if u2 and u2.lower() not in u1.lower():
        merged["social_username"] = f"{u1} • {u2}" if u1 else u2

    # Combine account names
    a1 = str(merged.get("account_name") or "").strip()
    a2 = str(secondary.get("account_name") or "").strip()
    if a2 and a2.lower() not in a1.lower():
        merged["account_name"] = f"{a1}, {a2}" if a1 else a2

    # Category & Company & Avatar
    if (not merged.get("category") or merged.get("category") == "New Lead") and secondary.get("category") and secondary.get("category") != "New Lead":
        merged["category"] = secondary.get("category")
    if not str(merged.get("company") or "").strip() and str(secondary.get("company") or "").strip():
        merged["company"] = str(secondary.get("company") or "").strip()
    if not str(merged.get("avatar_url") or "").strip() and str(secondary.get("avatar_url") or "").strip():
        merged["avatar_url"] = str(secondary.get("avatar_url") or "").strip()

    # Combine notes without duplication
    n1 = str(merged.get("notes") or "").strip()
    n2 = str(secondary.get("notes") or "").strip()
    if n2 and n2.lower() not in n1.lower():
        merged["notes"] = f"{n1} | {n2}" if n1 else n2

    merged["updated_at"] = now_str
    return merged


def _ensure_crm_contacts_table():
    if CONTACTS_CRM_STATE.get("table_initialized"):
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_crm_contacts (
                    id TEXT PRIMARY KEY,
                    first_name TEXT,
                    middle_name TEXT,
                    last_name TEXT,
                    contact_number TEXT,
                    email_address TEXT,
                    platform TEXT,
                    social_username TEXT,
                    account_name TEXT,
                    category TEXT,
                    company TEXT,
                    notes TEXT,
                    source_type TEXT,
                    source_ref_id TEXT,
                    avatar_url TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
            """))
        CONTACTS_CRM_STATE["table_initialized"] = True
    except Exception as e:
        print(f"[ContactsCRM] Table init warning: {e}")


def _save_crm_contacts_to_cloudinary():
    try:
        with CONTACTS_CRM_LOCK:
            contacts_snapshot = list(CONTACTS_CRM_STATE.get("contacts") or [])
        payload = {
            "contacts": contacts_snapshot,
            "count": len(contacts_snapshot),
            "updated_at": datetime.now(MANILA_TZ).isoformat()
        }
        raw_bytes = json.dumps(payload, indent=2).encode("utf-8")
        cloudinary.uploader.upload(
            io.BytesIO(raw_bytes),
            resource_type="raw",
            public_id=CONTACTS_CLOUDINARY_PUBLIC_ID,
            overwrite=True,
            invalidate=True
        )
    except Exception as e:
        print(f"[ContactsCRM] Cloudinary backup warning: {e}")


def _upsert_crm_contact_in_db(contact: dict, sync_cloud: bool = True):
    _ensure_crm_contacts_table()
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    params = {
        "id": str(contact.get("id") or f"crm_{int(time.time() * 1000)}"),
        "first_name": str(contact.get("first_name") or "").strip(),
        "middle_name": str(contact.get("middle_name") or "").strip(),
        "last_name": str(contact.get("last_name") or "").strip(),
        "contact_number": str(contact.get("contact_number") or "").strip(),
        "email_address": str(contact.get("email_address") or "").strip(),
        "platform": str(contact.get("platform") or "manual").strip().lower(),
        "social_username": str(contact.get("social_username") or "").strip(),
        "account_name": str(contact.get("account_name") or "").strip(),
        "category": str(contact.get("category") or "New Lead").strip(),
        "company": str(contact.get("company") or "").strip(),
        "notes": str(contact.get("notes") or "").strip(),
        "source_type": str(contact.get("source_type") or contact.get("platform") or "manual").strip(),
        "source_ref_id": str(contact.get("source_ref_id") or "").strip(),
        "avatar_url": str(contact.get("avatar_url") or "").strip(),
        "created_at": str(contact.get("created_at") or now_str).strip(),
        "updated_at": str(contact.get("updated_at") or now_str).strip()
    }
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO glennbot_crm_contacts
                (id, first_name, middle_name, last_name, contact_number, email_address,
                 platform, social_username, account_name, category, company, notes,
                 source_type, source_ref_id, avatar_url, created_at, updated_at)
                VALUES (:id, :first_name, :middle_name, :last_name, :contact_number, :email_address,
                        :platform, :social_username, :account_name, :category, :company, :notes,
                        :source_type, :source_ref_id, :avatar_url, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    middle_name = EXCLUDED.middle_name,
                    last_name = EXCLUDED.last_name,
                    contact_number = EXCLUDED.contact_number,
                    email_address = EXCLUDED.email_address,
                    platform = EXCLUDED.platform,
                    social_username = EXCLUDED.social_username,
                    account_name = EXCLUDED.account_name,
                    category = EXCLUDED.category,
                    company = EXCLUDED.company,
                    notes = EXCLUDED.notes,
                    source_type = EXCLUDED.source_type,
                    source_ref_id = EXCLUDED.source_ref_id,
                    avatar_url = EXCLUDED.avatar_url,
                    updated_at = EXCLUDED.updated_at
            """), params)
    except Exception as e:
        print(f"[ContactsCRM] Upsert DB warning: {e}")

    with CONTACTS_CRM_LOCK:
        existing = [c for c in CONTACTS_CRM_STATE["contacts"] if str(c.get("id")) != params["id"]]
        existing.insert(0, params)
        CONTACTS_CRM_STATE["contacts"] = existing

    if sync_cloud:
        threading.Thread(target=_save_crm_contacts_to_cloudinary, daemon=True).start()

    return params


def _deduplicate_and_combine_crm_contacts(contacts_list: List[dict]) -> Tuple[List[dict], int]:
    """
    Identifies duplicate contacts sharing the same normalized Phone Number,
    Email Address, or Social Username + Full Name across Cloudinary, Manual,
    WhatsApp, Telegram, and other platforms, and combines them into 1 unified contact.
    """
    unique_contacts: List[dict] = []
    phone_index: Dict[str, int] = {}
    email_index: Dict[str, int] = {}
    handle_index: Dict[str, int] = {}
    removed_ids: List[str] = []
    merged_count = 0

    for item in contacts_list:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        ph_key = _normalize_phone_key(item.get("contact_number") or "")
        em_key = _normalize_email_key(item.get("email_address") or "")
        raw_u = str(item.get("social_username") or "").split("•")[0].strip().lstrip("@").lower()
        plat = str(item.get("platform") or "manual").strip().lower()
        h_key = f"{plat}::{raw_u}" if raw_u and len(raw_u) >= 3 else ""

        match_idx = None
        if ph_key and ph_key in phone_index:
            match_idx = phone_index[ph_key]
        elif em_key and em_key in email_index:
            match_idx = email_index[em_key]
        elif h_key and h_key in handle_index:
            match_idx = handle_index[h_key]

        if match_idx is not None:
            primary_rec = unique_contacts[match_idx]
            combined = _combine_two_contact_records(primary_rec, item)
            unique_contacts[match_idx] = combined
            if cid and cid != str(combined.get("id")):
                removed_ids.append(cid)
            merged_count += 1
            # Update indices with combined record's phone/email
            c_ph = _normalize_phone_key(combined.get("contact_number") or "")
            c_em = _normalize_email_key(combined.get("email_address") or "")
            if c_ph:
                phone_index[c_ph] = match_idx
            if c_em:
                email_index[c_em] = match_idx
        else:
            new_idx = len(unique_contacts)
            unique_contacts.append(dict(item))
            if ph_key:
                phone_index[ph_key] = new_idx
            if em_key:
                email_index[em_key] = new_idx
            if h_key:
                handle_index[h_key] = new_idx

    if removed_ids:
        try:
            with db_engine.begin() as conn:
                for rid in removed_ids:
                    conn.execute(text("DELETE FROM glennbot_crm_contacts WHERE id = :id"), {"id": rid})
        except Exception as e:
            print(f"[ContactsCRM] Cleanup duplicate IDs warning: {e}")

    return unique_contacts, merged_count


def _harvest_contacts_from_whatsapp_telegram_and_zernio(force_refresh: bool = True) -> int:
    """
    Syncs conversations & contacts from connected WhatsApp, Telegram, and Zernio accounts
    and merges them into CONTACTS_CRM_STATE (combining by Phone Number / Email / Username).
    """
    imported_or_merged = 0
    try:
        if force_refresh:
            sync_all_messages_to_cloudinary(force_refresh=True)
        elif not CLOUDINARY_MESSAGES_STORE.get("loaded"):
            load_messages_store_from_cloudinary()

        convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
        now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")

        with CONTACTS_CRM_LOCK:
            current_list = list(CONTACTS_CRM_STATE.get("contacts") or [])

        for ckey, conv in list(convs_store.items()):
            if not isinstance(conv, dict):
                continue
            plat = str(conv.get("platform") or "").strip().lower()
            p_name = str(conv.get("participant_name") or "").strip()
            p_handle = str(conv.get("participant_handle") or "").strip()
            p_phone = str(conv.get("participant_phone") or "").strip()
            p_email = str(conv.get("participant_email") or "").strip()
            p_avatar = str(conv.get("participant_avatar") or "").strip()
            acc_name = str(conv.get("account_name") or "").strip()
            last_msg = str(conv.get("last_message_text") or "").strip()

            # Auto-import all WhatsApp & Telegram contacts, plus any other conversation where a phone or email was detected
            parsed = _smart_parse_name_backend(
                raw_name=p_name or p_handle,
                platform=plat,
                sample_text=last_msg,
                explicit_phone=p_phone,
                explicit_email=p_email
            )

            if plat not in ("whatsapp", "telegram") and not parsed["contact_number"] and not parsed["email_address"]:
                continue

            cand_record = {
                "id": f"crm_{plat}_{re.sub(r'[^a-zA-Z0-9]', '', str(conv.get('participant_id') or conv.get('conversation_id') or ckey))[:24]}",
                "first_name": parsed["first_name"],
                "middle_name": parsed["middle_name"],
                "last_name": parsed["last_name"],
                "contact_number": parsed["contact_number"],
                "email_address": parsed["email_address"],
                "platform": plat or "manual",
                "social_username": p_handle or parsed["social_username"],
                "account_name": acc_name,
                "category": "New Lead",
                "company": "",
                "notes": f"Synced from {plat.upper()} ({acc_name}): \"{last_msg[:120]}\"" if last_msg else f"Synced from {plat.upper()} ({acc_name})",
                "source_type": plat or "message",
                "source_ref_id": str(conv.get("conversation_id") or ckey),
                "avatar_url": p_avatar,
                "created_at": now_str,
                "updated_at": now_str
            }
            current_list.append(cand_record)
            imported_or_merged += 1

        if imported_or_merged > 0:
            deduped_list, _ = _deduplicate_and_combine_crm_contacts(current_list)
            with CONTACTS_CRM_LOCK:
                CONTACTS_CRM_STATE["contacts"] = deduped_list
            for item in deduped_list:
                _upsert_crm_contact_in_db(item, sync_cloud=False)
            threading.Thread(target=_save_crm_contacts_to_cloudinary, daemon=True).start()
    except Exception as e:
        print(f"[ContactsCRM] WhatsApp/Telegram harvest warning: {e}")

    return imported_or_merged


def _load_crm_contacts_state(force_cloud: bool = False):
    _ensure_crm_contacts_table()
    with CONTACTS_CRM_LOCK:
        if CONTACTS_CRM_STATE["loaded_from_cloud"] and not force_cloud:
            return CONTACTS_CRM_STATE["contacts"]

    db_contacts = []
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, first_name, middle_name, last_name, contact_number, email_address,
                       platform, social_username, account_name, category, company, notes,
                       source_type, source_ref_id, avatar_url, created_at, updated_at
                FROM glennbot_crm_contacts
                ORDER BY updated_at DESC, created_at DESC
            """)).mappings().all()
            for r in rows:
                db_contacts.append({
                    "id": str(r.get("id") or ""),
                    "first_name": str(r.get("first_name") or ""),
                    "middle_name": str(r.get("middle_name") or ""),
                    "last_name": str(r.get("last_name") or ""),
                    "contact_number": str(r.get("contact_number") or ""),
                    "email_address": str(r.get("email_address") or ""),
                    "platform": str(r.get("platform") or "manual").lower(),
                    "social_username": str(r.get("social_username") or ""),
                    "account_name": str(r.get("account_name") or ""),
                    "category": str(r.get("category") or "New Lead"),
                    "company": str(r.get("company") or ""),
                    "notes": str(r.get("notes") or ""),
                    "source_type": str(r.get("source_type") or r.get("platform") or "manual"),
                    "source_ref_id": str(r.get("source_ref_id") or ""),
                    "avatar_url": str(r.get("avatar_url") or ""),
                    "created_at": str(r.get("created_at") or ""),
                    "updated_at": str(r.get("updated_at") or "")
                })
    except Exception as e:
        print(f"[ContactsCRM] DB read warning: {e}")

    cloud_contacts = []
    try:
        res_info = cloudinary.api.resource(CONTACTS_CLOUDINARY_PUBLIC_ID, resource_type="raw")
        sec_url = res_info.get("secure_url")
        if sec_url:
            r = HTTP_SESSION.get(f"{sec_url}?_t={int(time.time())}", timeout=10)
            if r.status_code == 200:
                c_data = r.json()
                if isinstance(c_data.get("contacts"), list):
                    cloud_contacts = c_data["contacts"]
    except Exception:
        pass

    merged_map = {}
    for item in cloud_contacts + db_contacts:
        cid = str(item.get("id") or "").strip()
        if cid:
            merged_map[cid] = item

    raw_list = list(merged_map.values())
    deduped_list, _ = _deduplicate_and_combine_crm_contacts(raw_list)

    with CONTACTS_CRM_LOCK:
        CONTACTS_CRM_STATE["contacts"] = deduped_list
        CONTACTS_CRM_STATE["loaded_from_cloud"] = True

    for item in deduped_list:
        _upsert_crm_contact_in_db(item, sync_cloud=False)

    return CONTACTS_CRM_STATE["contacts"]


@router.get("/api/contacts")
def api_get_crm_contacts(refresh: bool = False):
    contacts = _load_crm_contacts_state(force_cloud=bool(refresh))
    imported_count = 0
    if refresh:
        imported_count = _harvest_contacts_from_whatsapp_telegram_and_zernio(force_refresh=True)
        with CONTACTS_CRM_LOCK:
            contacts = list(CONTACTS_CRM_STATE.get("contacts") or [])
    return {
        "status": "success",
        "contacts": contacts,
        "count": len(contacts),
        "imported_count": imported_count
    }


@router.post("/api/contacts/sync")
def api_sync_all_crm_contacts():
    """
    Syncs CRM contacts from:
    1) Database + Cloudinary saved/manual contacts
    2) Connected WhatsApp & Telegram accounts (via Zernio API) + social conversations with phone/email
    3) Automatically identifies duplicate Phone Numbers or Email Addresses and combines them into 1 contact!
    """
    _load_crm_contacts_state(force_cloud=True)
    with CONTACTS_CRM_LOCK:
        before_count = len(CONTACTS_CRM_STATE.get("contacts") or [])

    harvested = _harvest_contacts_from_whatsapp_telegram_and_zernio(force_refresh=True)

    with CONTACTS_CRM_LOCK:
        current_list = list(CONTACTS_CRM_STATE.get("contacts") or [])

    deduped_list, merged_dups = _deduplicate_and_combine_crm_contacts(current_list)
    with CONTACTS_CRM_LOCK:
        CONTACTS_CRM_STATE["contacts"] = deduped_list

    for item in deduped_list:
        _upsert_crm_contact_in_db(item, sync_cloud=False)
    threading.Thread(target=_save_crm_contacts_to_cloudinary, daemon=True).start()

    return {
        "status": "success",
        "message": f"Synced {len(deduped_list)} contact(s) from Cloudinary, WhatsApp, Telegram & Social Inbox!",
        "contacts": deduped_list,
        "count": len(deduped_list),
        "before_count": before_count,
        "harvested_candidates": harvested,
        "merged_duplicates": merged_dups
    }


@router.post("/api/contacts")
async def api_create_or_update_crm_contact(request: Request):
    body = await request.json()
    return await run_in_threadpool(lambda: _create_or_update_crm_contact_sync(body))


def _create_or_update_crm_contact_sync(body: Dict[str, Any]):
    _load_crm_contacts_state(force_cloud=False)

    first_name = str(body.get("first_name") or "").strip()
    middle_name = str(body.get("middle_name") or "").strip()
    last_name = str(body.get("last_name") or "").strip()
    contact_number = str(body.get("contact_number") or "").strip()
    email_address = str(body.get("email_address") or "").strip()
    platform = str(body.get("platform") or "manual").strip().lower()
    social_username = str(body.get("social_username") or "").strip()
    account_name = str(body.get("account_name") or "").strip()
    category = str(body.get("category") or "New Lead").strip()
    company = str(body.get("company") or "").strip()
    notes = str(body.get("notes") or "").strip()
    source_type = str(body.get("source_type") or platform or "manual").strip()
    source_ref_id = str(body.get("source_ref_id") or "").strip()
    avatar_url = str(body.get("avatar_url") or "").strip()

    if not any([first_name, last_name, social_username, email_address, contact_number]):
        return JSONResponse({
            "status": "error",
            "message": "Please provide at least a Name, Username, Email Address, or Contact Number."
        }, status_code=400)

    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    contact_id = str(body.get("id") or "").strip()
    created_at = now_str

    norm_phone = _normalize_phone_key(contact_number)
    norm_email = _normalize_email_key(email_address)

    # Check if updating existing contact by ID or deduplicating/combining by same Phone Number, Email Address, or Username
    existing_match = None
    matched_reason = ""
    with CONTACTS_CRM_LOCK:
        for ex in CONTACTS_CRM_STATE["contacts"]:
            if contact_id and str(ex.get("id")) == contact_id:
                existing_match = ex
                matched_reason = "id"
                break
            if not contact_id:
                ex_phone = _normalize_phone_key(ex.get("contact_number") or "")
                ex_email = _normalize_email_key(ex.get("email_address") or "")
                if norm_phone and ex_phone and norm_phone == ex_phone:
                    existing_match = ex
                    matched_reason = "Duplicate Contact Number Combined"
                    break
                if norm_email and ex_email and norm_email == ex_email:
                    existing_match = ex
                    matched_reason = "Duplicate Email Address Combined"
                    break
                if social_username and str(ex.get("social_username") or "").strip().lower() == social_username.lower() and str(ex.get("platform") or "").lower() == platform:
                    existing_match = ex
                    matched_reason = "Existing Social Profile Combined"
                    break

    incoming_record = {
        "id": contact_id or f"crm_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "contact_number": contact_number,
        "email_address": email_address,
        "platform": platform,
        "social_username": social_username,
        "account_name": account_name,
        "category": category or "New Lead",
        "company": company,
        "notes": notes,
        "source_type": source_type,
        "source_ref_id": source_ref_id,
        "avatar_url": avatar_url,
        "created_at": created_at,
        "updated_at": now_str
    }

    if existing_match and matched_reason != "id":
        # Combine the existing contact with the newly submitted info into 1 unified contact
        record = _combine_two_contact_records(existing_match, incoming_record)
        # Prefer explicitly typed non-empty fields from user modal
        if first_name:
            record["first_name"] = first_name
        if middle_name:
            record["middle_name"] = middle_name
        if last_name:
            record["last_name"] = last_name
        if contact_number:
            record["contact_number"] = contact_number
        if email_address:
            record["email_address"] = email_address
        if category:
            record["category"] = category
        if company:
            record["company"] = company
    elif existing_match and matched_reason == "id":
        incoming_record["id"] = str(existing_match.get("id"))
        incoming_record["created_at"] = str(existing_match.get("created_at") or now_str)
        if not incoming_record["avatar_url"]:
            incoming_record["avatar_url"] = str(existing_match.get("avatar_url") or "")
        record = incoming_record
    else:
        record = incoming_record

    saved = _upsert_crm_contact_in_db(record, sync_cloud=True)
    if "_dispatch_outbound_n8n_webhook_async" in globals():
        _dispatch_outbound_n8n_webhook_async("contact.saved", {
            "contact": saved,
            "updated_existing": bool(existing_match),
            "combined_duplicate": bool(existing_match and matched_reason != "id"),
            "matched_reason": matched_reason
        })
    return {
        "status": "success",
        "message": f"Contact combined & saved ({matched_reason})!" if (existing_match and matched_reason != "id") else "Contact saved to CRM Database & Cloudinary!",
        "contact": saved,
        "updated_existing": bool(existing_match),
        "combined_duplicate": bool(existing_match and matched_reason != "id"),
        "matched_reason": matched_reason
    }


@router.put("/api/contacts/{contact_id}")
async def api_update_crm_contact(contact_id: str, request: Request):
    body = await request.json()
    return await run_in_threadpool(lambda: _update_crm_contact_sync(contact_id, body))


def _update_crm_contact_sync(contact_id: str, body: Dict[str, Any]):
    _load_crm_contacts_state(force_cloud=False)
    clean_id = str(contact_id or "").strip()
    existing = next((c for c in CONTACTS_CRM_STATE["contacts"] if str(c.get("id")) == clean_id), None)
    if not existing:
        return JSONResponse({"status": "error", "message": "Contact not found."}, status_code=404)

    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    updated_record = {
        "id": clean_id,
        "first_name": str(body.get("first_name", existing.get("first_name", ""))).strip(),
        "middle_name": str(body.get("middle_name", existing.get("middle_name", ""))).strip(),
        "last_name": str(body.get("last_name", existing.get("last_name", ""))).strip(),
        "contact_number": str(body.get("contact_number", existing.get("contact_number", ""))).strip(),
        "email_address": str(body.get("email_address", existing.get("email_address", ""))).strip(),
        "platform": str(body.get("platform", existing.get("platform", "manual"))).strip().lower(),
        "social_username": str(body.get("social_username", existing.get("social_username", ""))).strip(),
        "account_name": str(body.get("account_name", existing.get("account_name", ""))).strip(),
        "category": str(body.get("category", existing.get("category", "New Lead"))).strip(),
        "company": str(body.get("company", existing.get("company", ""))).strip(),
        "notes": str(body.get("notes", existing.get("notes", ""))).strip(),
        "source_type": str(body.get("source_type", existing.get("source_type", "manual"))).strip(),
        "source_ref_id": str(body.get("source_ref_id", existing.get("source_ref_id", ""))).strip(),
        "avatar_url": str(body.get("avatar_url", existing.get("avatar_url", ""))).strip(),
        "created_at": str(existing.get("created_at") or now_str),
        "updated_at": now_str
    }
    saved = _upsert_crm_contact_in_db(updated_record, sync_cloud=True)
    return {
        "status": "success",
        "message": "Contact updated!",
        "contact": saved
    }


@router.post("/api/contacts/open-chat")
async def api_open_crm_contact_chat_in_messages(request: Request):
    """
    Opens or initializes a conversation in the Messages Tab for a CRM Contact
    on the selected platform ('sms', 'whatsapp', or 'telegram').
    - Facebook & Instagram contacts cannot be messaged directly via FB/IG from Contacts.
    - SMS & WhatsApp require a valid Mobile Number (contact_number).
    - Telegram requires a Social Username / Handle (social_username); if the username format
      is invalid, the chat still opens in the Messages Tab so the user can see it, and
      sending a message will return a Telegram username validation error.
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}

        contact_id = str(body.get("contact_id") or "").strip()
        target_platform = str(body.get("platform") or "").strip().lower()

        if target_platform in ("facebook", "instagram"):
            return {
                "status": "error",
                "message": "Contacts saved via Facebook or Instagram cannot be messaged on FB/IG from Contacts unless they have a Mobile Number (SMS/WhatsApp), Email Address, or Social Username (Telegram)."
            }
        if target_platform not in ("sms", "whatsapp", "telegram"):
            return {"status": "error", "message": f"Unsupported chat platform: {target_platform}"}

        # Look up CRM contact if contact_id was provided
        crm_contact: Dict[str, Any] = {}
        if contact_id:
            all_contacts = _load_crm_contacts_state(force_cloud=False) or []
            for c in all_contacts:
                if isinstance(c, dict) and str(c.get("id") or "") == contact_id:
                    crm_contact = c
                    break

        first_name = str(crm_contact.get("first_name") or "").strip()
        middle_name = str(crm_contact.get("middle_name") or "").strip()
        last_name = str(crm_contact.get("last_name") or "").strip()
        computed_name = " ".join(x for x in (first_name, middle_name, last_name) if x).strip()
        participant_name = str(
            body.get("participant_name")
            or computed_name
            or crm_contact.get("social_username")
            or crm_contact.get("contact_number")
            or "Contact"
        ).strip()

        contact_number = str(body.get("contact_number") or crm_contact.get("contact_number") or "").strip()
        social_username = str(body.get("social_username") or crm_contact.get("social_username") or "").strip()
        avatar_url = str(crm_contact.get("avatar_url") or "").strip()
        source_ref_id = str(crm_contact.get("source_ref_id") or "").strip()

        if target_platform in ("sms", "whatsapp"):
            digits_only = re.sub(r"\D", "", contact_number)
            if len(digits_only) < 7:
                return {
                    "status": "error",
                    "message": f"{target_platform.upper()} requires a valid Mobile Number on this contact."
                }
        elif target_platform == "telegram":
            if not social_username:
                return {
                    "status": "error",
                    "message": "Telegram requires a Social Username / Handle on this contact."
                }

        if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
            load_messages_store_from_cloudinary()

        convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
        now_dt = datetime.now(MANILA_TZ)
        now_iso = now_dt.isoformat()
        disp_time = now_dt.strftime("%b %d, %Y %I:%M %p")

        # 1. Try to find an existing conversation in CLOUDINARY_MESSAGES_STORE for this contact & platform
        matched_conv: Optional[Dict[str, Any]] = None
        norm_phone = _normalize_sms_phone_number(contact_number) if contact_number else ""
        norm_phone_digits = re.sub(r"\D", "", norm_phone or contact_number)
        clean_uname_low = social_username.lstrip("@").strip().lower()

        for ckey, c_obj in list(convs_store.items()):
            if not isinstance(c_obj, dict):
                continue
            c_plat = str(c_obj.get("platform") or "").strip().lower()
            if c_plat != target_platform:
                continue

            c_pid = str(c_obj.get("participant_id") or "").strip()
            c_handle = str(c_obj.get("participant_handle") or "").strip()
            c_cid = str(c_obj.get("conversation_id") or "").strip()

            if target_platform in ("sms", "whatsapp") and norm_phone_digits:
                c_digits = re.sub(r"\D", "", f"{c_pid} {c_handle} {c_cid}")
                if norm_phone_digits and (norm_phone_digits in c_digits or (len(norm_phone_digits) >= 10 and norm_phone_digits[-10:] in c_digits)):
                    matched_conv = c_obj
                    break
            elif target_platform == "telegram" and clean_uname_low:
                cand_handles = [
                    c_handle.lstrip("@").strip().lower(),
                    c_pid.lstrip("@").strip().lower(),
                    c_cid.replace("tg_", "").lstrip("@").strip().lower()
                ]
                if clean_uname_low in cand_handles or (source_ref_id and source_ref_id in (c_cid, ckey)):
                    matched_conv = c_obj
                    break

        if matched_conv is not None:
            matched_ckey = str(matched_conv.get("conv_key") or f"{matched_conv.get('account_id')}_{matched_conv.get('conversation_id')}").strip()
            matched_conv["conv_key"] = matched_ckey
            matched_conv["hidden"] = False
            matched_conv["opened_from_crm"] = True
            if participant_name and (not matched_conv.get("participant_name") or matched_conv.get("participant_name") == matched_conv.get("participant_id")):
                matched_conv["participant_name"] = participant_name
            if target_platform == "telegram" and social_username:
                matched_conv["participant_handle"] = social_username if social_username.startswith("@") else f"@{social_username}"
            elif target_platform in ("sms", "whatsapp") and norm_phone:
                matched_conv["participant_handle"] = norm_phone
                matched_conv["participant_phone"] = norm_phone
                if not matched_conv.get("participant_id"):
                    matched_conv["participant_id"] = norm_phone
            try:
                save_messages_store_async()
            except Exception:
                pass
            conv_out = dict(matched_conv)
            conv_out["recent_messages"] = (conv_out.get("messages") or [])[-30:]
            return {
                "status": "success",
                "conversation": conv_out
            }

        # 2. Otherwise, create a new conversation entry for the selected platform so it opens immediately in the Messages Tab
        if target_platform == "sms":
            sim_id = str(TEXTBEE_RUNTIME_CONFIG.get("sim_subscription_id") or TEXTBEE_SIM_SUBSCRIPTION_ID or "2").strip()
            acc_id = TEXTBEE_ACCOUNT_ID
            acc_name = f"TextBee SMS (SIM {sim_id})"
            z_acc_id = TEXTBEE_ACCOUNT_ID
            z_key = ""
            clean_digits = re.sub(r"\D+", "", norm_phone or contact_number) or re.sub(r"\W+", "", norm_phone or contact_number) or "unknown"
            conv_id = f"sms_{clean_digits}"
            part_id = norm_phone or contact_number
            part_handle = norm_phone or contact_number
        else:
            # Find a connected WhatsApp or Telegram account if available
            msg_accounts = refresh_connected_accounts_cache(force=False) or []
            plat_acc = next((a for a in msg_accounts if isinstance(a, dict) and str(a.get("platform") or "").strip().lower() == target_platform), None)
            if plat_acc:
                acc_id = str(plat_acc.get("account_id") or plat_acc.get("zernio_account_id") or f"{target_platform}_direct")
                acc_name = str(plat_acc.get("account_name") or f"{target_platform.capitalize()}")
                z_acc_id = str(plat_acc.get("zernio_account_id") or acc_id)
                z_key = str(plat_acc.get("api_key") or "")
            else:
                acc_id = f"{target_platform}_crm_direct"
                acc_name = "WhatsApp Business" if target_platform == "whatsapp" else "Telegram"
                z_acc_id = acc_id
                z_key = ""

            if target_platform == "whatsapp":
                clean_digits = re.sub(r"\D", "", norm_phone or contact_number)
                conv_id = f"wa_{clean_digits}"
                part_id = norm_phone or contact_number
                part_handle = norm_phone or contact_number
            else:
                # telegram
                formatted_handle = social_username if (social_username.startswith("@") or re.fullmatch(r"-?\d{5,20}", social_username)) else f"@{social_username}"
                safe_slug = re.sub(r"[^a-zA-Z0-9_]", "_", social_username.lstrip("@")).strip("_") or str(int(time.time()))
                conv_id = f"tg_{safe_slug}"
                part_id = formatted_handle
                part_handle = formatted_handle

        conv_key = f"{acc_id}_{conv_id}"
        new_conv: Dict[str, Any] = {
            "conv_key": conv_key,
            "conversation_id": conv_id,
            "platform_conversation_id": conv_id,
            "zernio_conversation_id": conv_id,
            "alternate_conversation_ids": [conv_id, part_id],
            "platform": target_platform,
            "account_id": acc_id,
            "zernio_account_id": z_acc_id,
            "zernio_api_key": z_key,
            "account_name": acc_name,
            "account_avatar": "",
            "participant_id": part_id,
            "participant_name": participant_name,
            "participant_handle": part_handle,
            "participant_phone": norm_phone or contact_number,
            "participant_email": str(crm_contact.get("email_address") or ""),
            "participant_avatar": avatar_url,
            "participant_picture": avatar_url,
            "social_username": social_username,
            "last_message_text": f"Chat opened from Contacts ({part_handle})",
            "last_message_is_own": False,
            "updated_iso": now_iso,
            "display_time": disp_time,
            "relative_time": "Just now",
            "has_authoritative_ts": True,
            "api_order_index": 0,
            "unread_count": 0,
            "is_read": True,
            "hidden": False,
            "opened_from_crm": True,
            "crm_contact_id": contact_id,
            "messages": []
        }
        convs_store[conv_key] = new_conv
        try:
            save_messages_store_async()
        except Exception:
            pass

        conv_out = dict(new_conv)
        conv_out["recent_messages"] = []
        return {
            "status": "success",
            "conversation": conv_out
        }
    except Exception as exc:
        print(f"[Contacts Open Chat Error]: {exc}")
        return {
            "status": "error",
            "message": f"Failed to open chat: {str(exc)}"
        }




# ==============================================================================
# --- COMPOSIO GOOGLE CONTACTS OAUTH2 & AUTO-IMPORT ENGINE ---
# ==============================================================================

GOOGLE_CONTACTS_AUTH_CONFIG_CACHE: Dict[str, Any] = {
    "auth_config_id": "",
    "pending_sessions": {}  # entity_id -> {"connected_account_id": str, "created_at": float}
}

def _get_or_create_google_contacts_composio_auth_config_id(force_lookup: bool = False) -> List[str]:
    """
    Returns an ordered list of candidate Composio OAuth2 auth_config_ids for Google Contacts login
    using the active COMPOSIO_API_KEY from .env:
    1) Any existing 'googlecontacts' / 'google_contacts' auth_config on the user's Composio API key
    2) Newly created 'googlecontacts' managed auth_config (or custom OAuth2 using Google client credentials)
    3) The active 'gmail' / 'googlecalendar' Composio Managed Google OAuth2 auth_config (e.g. ac_Nk5guPh9u7VB)
       so OAuth popup creation NEVER fails even if 'googlecontacts' managed auth is not enabled on the key.
    """
    _load_email_hub_state()
    headers = _get_composio_headers()
    candidates: List[str] = []

    cached_id = str(GOOGLE_CONTACTS_AUTH_CONFIG_CACHE.get("auth_config_id") or "").strip()
    if cached_id and not force_lookup:
        candidates.append(cached_id)

    target_toolkits = ("googlecontacts", "google_contacts", "people", "google_people")
    gmail_fallback_ids: List[str] = []

    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/auth_configs", headers=headers, timeout=15)
        if r.status_code == 200:
            items = r.json().get("items") or []
            for item in items:
                tk = str((item.get("toolkit") or {}).get("slug") or "").strip().lower()
                scheme = str(item.get("auth_scheme") or "").upper()
                found_id = str(item.get("id") or "").strip()
                if not found_id or ("OAUTH" not in scheme and scheme):
                    continue
                if tk in target_toolkits:
                    if found_id not in candidates:
                        candidates.append(found_id)
                    GOOGLE_CONTACTS_AUTH_CONFIG_CACHE["auth_config_id"] = found_id
                elif tk in ("gmail", "googlecalendar", "google"):
                    if found_id not in gmail_fallback_ids:
                        gmail_fallback_ids.append(found_id)
    except Exception as e:
        print(f"[ContactsCRM] List auth_configs warning: {e}")

    if not candidates:
        for slug_candidate in ("googlecontacts", "google_contacts"):
            try:
                create_payload = {
                    "toolkit": {"slug": slug_candidate},
                    "auth_config": {
                        "type": "use_composio_managed_auth",
                        "name": "GlennBot Google Contacts OAuth2"
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
                        GOOGLE_CONTACTS_AUTH_CONFIG_CACHE["auth_config_id"] = new_id
                        if new_id not in candidates:
                            candidates.append(new_id)
                        break
            except Exception as e:
                print(f"[ContactsCRM] Create googlecontacts managed auth_config note ({slug_candidate}): {e}")

    # Always include the working Gmail / Google OAuth config from Composio as guaranteed fallback
    try:
        gmail_ac = _get_or_create_composio_auth_config_id("gmail", force_lookup=force_lookup)
        if gmail_ac and gmail_ac not in candidates:
            candidates.append(gmail_ac)
    except Exception:
        pass

    for g_id in gmail_fallback_ids:
        if g_id and g_id not in candidates:
            candidates.append(g_id)

    if EMAIL_HUB_STATE.get("gmail_auth_config_id"):
        default_g = str(EMAIL_HUB_STATE["gmail_auth_config_id"]).strip()
        if default_g and default_g not in candidates:
            candidates.append(default_g)

    return candidates


def _create_composio_google_contacts_oauth_link(request: Request) -> Dict[str, Any]:
    """
    Generates a Composio v3 OAuth2 login link for Google Contacts using COMPOSIO_API_KEY from .env.
    """
    _load_email_hub_state()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:5001"
    proto = request.headers.get("x-forwarded-proto") or ("https" if ("ngrok" in host or "onrender" in host or "run.app" in host) else "http")
    base_url = f"{proto}://{host}"
    entity_id = f"glennbot_gcontacts_{int(time.time())}"
    callback_url = f"{base_url}/api/oauth/google-contacts/callback?entity_id={urllib.parse.quote(entity_id)}"
    headers = _get_composio_headers()

    last_err = ""
    for force_flag in (False, True):
        candidate_configs = _get_or_create_google_contacts_composio_auth_config_id(force_lookup=force_flag)
        for auth_config_id in candidate_configs:
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
                    GOOGLE_CONTACTS_AUTH_CONFIG_CACHE["auth_config_id"] = auth_config_id
                    GOOGLE_CONTACTS_AUTH_CONFIG_CACHE.setdefault("pending_sessions", {})[entity_id] = {
                        "connected_account_id": conn_id,
                        "entity_id": entity_id,
                        "created_at": time.time()
                    }
                    return {
                        "status": "success",
                        "provider": "google_contacts",
                        "auth_url": redirect_url,
                        "connected_account_id": conn_id,
                        "entity_id": entity_id,
                        "auth_config_id": auth_config_id
                    }
                last_err = (data.get("error") or {}).get("message") or data.get("message") or f"HTTP {r.status_code}"
            except Exception as e:
                last_err = str(e)

    return {
        "status": "error",
        "message": f"Could not start Google Contacts OAuth via Composio ({last_err or 'No auth config responded'})."
    }


def _extract_person_nodes_from_payload(raw_payload: Any) -> List[Dict[str, Any]]:
    """
    Extracts Google People API person objects from Composio tool responses or proxy responses.
    """
    persons: List[Dict[str, Any]] = []

    def _walk(node: Any):
        if isinstance(node, dict):
            if any(k in node for k in ("names", "emailAddresses", "phoneNumbers", "resourceName")):
                if isinstance(node.get("names"), list) or isinstance(node.get("emailAddresses"), list) or isinstance(node.get("phoneNumbers"), list):
                    persons.append(node)
                    return
            for key in ("connections", "otherContacts", "contacts", "people", "items", "results", "data", "response_data"):
                if key in node:
                    _walk(node[key])
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(raw_payload)
    return persons


def _parse_google_person_to_crm_record(person: Dict[str, Any], account_email: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(person, dict):
        return None

    names = person.get("names") if isinstance(person.get("names"), list) else []
    emails = person.get("emailAddresses") if isinstance(person.get("emailAddresses"), list) else []
    phones = person.get("phoneNumbers") if isinstance(person.get("phoneNumbers"), list) else []
    orgs = person.get("organizations") if isinstance(person.get("organizations"), list) else []
    photos = person.get("photos") if isinstance(person.get("photos"), list) else []
    bios = person.get("biographies") if isinstance(person.get("biographies"), list) else []

    first_name = ""
    middle_name = ""
    last_name = ""
    display_name = ""

    if names and isinstance(names[0], dict):
        n0 = names[0]
        first_name = str(n0.get("givenName") or "").strip()
        middle_name = str(n0.get("middleName") or "").strip()
        last_name = str(n0.get("familyName") or "").strip()
        display_name = str(n0.get("displayName") or "").strip()

    if not first_name and not last_name and display_name:
        parsed_nm = _smart_parse_name_backend(display_name, platform="google_contacts")
        first_name = parsed_nm.get("first_name") or ""
        middle_name = parsed_nm.get("middle_name") or ""
        last_name = parsed_nm.get("last_name") or ""

    email_address = ""
    for em_obj in emails:
        if isinstance(em_obj, dict) and em_obj.get("value"):
            email_address = str(em_obj.get("value") or "").strip().lower()
            break

    contact_number = ""
    for ph_obj in phones:
        if isinstance(ph_obj, dict) and ph_obj.get("value"):
            contact_number = str(ph_obj.get("value") or "").strip()
            break

    company = ""
    for org_obj in orgs:
        if isinstance(org_obj, dict) and (org_obj.get("name") or org_obj.get("title")):
            org_nm = str(org_obj.get("name") or "").strip()
            org_title = str(org_obj.get("title") or "").strip()
            company = f"{org_nm} ({org_title})" if (org_nm and org_title) else (org_nm or org_title)
            break

    avatar_url = ""
    for ph in photos:
        if isinstance(ph, dict) and ph.get("url"):
            avatar_url = str(ph.get("url") or "").strip()
            break

    bio_note = ""
    for b in bios:
        if isinstance(b, dict) and b.get("value"):
            bio_note = str(b.get("value") or "").strip()
            break

    if not first_name and not last_name and email_address:
        first_name = email_address.split("@")[0]

    if not any([first_name, last_name, contact_number, email_address]):
        return None

    resource_name = str(person.get("resourceName") or person.get("etag") or f"{first_name}_{last_name}_{contact_number}_{email_address}").strip()
    clean_ref = re.sub(r"[^a-zA-Z0-9]", "", resource_name)[-24:] or uuid.uuid4().hex[:10]
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")

    note_parts = []
    if bio_note:
        note_parts.append(bio_note)
    note_parts.append(f"Imported from Google Contacts ({account_email or 'Google OAuth'})")

    return {
        "id": f"crm_gcontacts_{clean_ref}",
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "contact_number": contact_number,
        "email_address": email_address,
        "platform": "google_contacts",
        "social_username": email_address or display_name or first_name,
        "account_name": account_email or "Google Contacts",
        "category": "New Lead",
        "company": company,
        "notes": " | ".join(note_parts),
        "source_type": "google_contacts",
        "source_ref_id": resource_name,
        "avatar_url": avatar_url,
        "created_at": now_str,
        "updated_at": now_str
    }


def _harvest_google_correspondents_from_gmail_messages(conn_id: str, entity_id: str, account_email: str = "") -> List[Dict[str, Any]]:
    """
    Fallback harvester: if the Composio Google connection was authorized with Gmail scopes,
    extracts all unique people/contacts from recent Gmail messages (From / To / Reply-To headers)
    so the user always gets their Google contacts imported into CRM.
    """
    harvested: List[Dict[str, Any]] = []
    try:
        res = _composio_execute_tool(
            "GMAIL_FETCH_EMAILS",
            conn_id,
            entity_id,
            {"user_id": "me", "max_results": 50, "include_payload": True}
        )
        data_obj = (res.get("data") or {}).get("response_data") or res.get("data") or {}
        messages = data_obj.get("messages") if isinstance(data_obj, dict) else []
        if not isinstance(messages, list):
            return []

        now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
        own_email_low = (account_email or "").strip().lower()
        seen_emails = set()

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
            headers_list = payload.get("headers") if isinstance(payload.get("headers"), list) else []
            raw_candidates = []
            for k in ("sender", "from", "to", "reply_to"):
                if msg.get(k):
                    raw_candidates.append(str(msg.get(k)))
            for h in headers_list:
                if isinstance(h, dict) and str(h.get("name") or "").lower() in ("from", "to", "reply-to"):
                    raw_candidates.append(str(h.get("value") or ""))

            snippet_txt = str(msg.get("snippet") or msg.get("messageText") or "")
            for raw_hdr in raw_candidates:
                for addr_part in raw_hdr.split(","):
                    addr_part = addr_part.strip()
                    if not addr_part or "@" not in addr_part:
                        continue
                    m_em = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", addr_part)
                    if not m_em:
                        continue
                    em_val = m_em.group(1).strip().lower()
                    if not em_val or em_val == own_email_low or em_val in seen_emails:
                        continue
                    if any(skip_w in em_val for skip_w in ("noreply", "no-reply", "donotreply", "mailer-daemon", "notifications@")):
                        continue
                    seen_emails.add(em_val)
                    disp_part = re.sub(r"<[^>]+>", "", addr_part).replace('"', "").replace("'", "").strip()
                    if not disp_part or "@" in disp_part:
                        disp_part = em_val.split("@")[0]

                    parsed = _smart_parse_name_backend(
                        raw_name=disp_part,
                        platform="google_contacts",
                        sample_text=snippet_txt,
                        explicit_email=em_val
                    )
                    clean_ref = re.sub(r"[^a-zA-Z0-9]", "", em_val)[-24:]
                    harvested.append({
                        "id": f"crm_gcontacts_{clean_ref}",
                        "first_name": parsed.get("first_name") or em_val.split("@")[0],
                        "middle_name": parsed.get("middle_name") or "",
                        "last_name": parsed.get("last_name") or "",
                        "contact_number": parsed.get("contact_number") or "",
                        "email_address": em_val,
                        "platform": "google_contacts",
                        "social_username": em_val,
                        "account_name": account_email or "Google Contacts",
                        "category": "New Lead",
                        "company": "",
                        "notes": f"Imported from Google Account ({account_email or 'Google OAuth'})",
                        "source_type": "google_contacts",
                        "source_ref_id": em_val,
                        "avatar_url": "",
                        "created_at": now_str,
                        "updated_at": now_str
                    })
    except Exception as e:
        print(f"[ContactsCRM] Gmail correspondent harvest warning: {e}")

    return harvested


def _fetch_and_import_google_contacts_from_composio(preferred_connection_id: str = "", preferred_entity_id: str = "") -> Dict[str, Any]:
    """
    Discovers the active Google Contacts / Google OAuth connection on Composio, downloads all contacts
    via Composio tools, direct Google People API (using live OAuth token), and Google correspondent fallback,
    and merges/saves them into CRM Database & Cloudinary.
    """
    _load_email_hub_state()
    _load_crm_contacts_state(force_cloud=False)

    headers = _get_composio_headers()
    try:
        r = HTTP_SESSION.get(f"{COMPOSIO_BASE_URL}/connected_accounts", headers=headers, timeout=15)
        items = (r.json().get("items") or []) if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "message": f"Failed to query Composio connected accounts: {e}", "imported_count": 0}

    sorted_items = sorted(
        items,
        key=lambda x: (
            1 if (preferred_connection_id and str(x.get("id") or "") == preferred_connection_id) else 0,
            1 if (preferred_entity_id and str(x.get("user_id") or x.get("entity_id") or "") == preferred_entity_id) else 0,
            1 if str(x.get("user_id") or x.get("entity_id") or "").startswith("glennbot_gcontacts_") else 0,
            str(x.get("created_at") or x.get("updated_at") or "")
        ),
        reverse=True
    )

    target_conn_id = ""
    target_entity_id = preferred_entity_id or "glennbot_gcontacts_user"
    account_email = ""

    for item in sorted_items:
        status = str(item.get("status") or "").upper()
        cid = str(item.get("id") or "").strip()
        tk_slug = str((item.get("toolkit") or {}).get("slug") or "").strip().lower()
        uid = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "").strip()
        if status != "ACTIVE" or not cid:
            continue
        if preferred_connection_id and cid == preferred_connection_id:
            target_conn_id = cid
            target_entity_id = uid or target_entity_id
            account_email, _ = _extract_email_from_composio_item(item)
            break
        if preferred_entity_id and uid == preferred_entity_id:
            target_conn_id = cid
            target_entity_id = uid
            account_email, _ = _extract_email_from_composio_item(item)
            break
        if tk_slug in ("googlecontacts", "google_contacts") or uid.startswith("glennbot_gcontacts_"):
            target_conn_id = cid
            target_entity_id = uid or target_entity_id
            account_email, _ = _extract_email_from_composio_item(item)
            break

    # Fallback to any active Gmail / Google account on Composio if no dedicated gcontacts connection was matched yet
    if not target_conn_id:
        for item in sorted_items:
            status = str(item.get("status") or "").upper()
            cid = str(item.get("id") or "").strip()
            tk_slug = str((item.get("toolkit") or {}).get("slug") or "").strip().lower()
            uid = str(item.get("user_id") or item.get("entity_id") or item.get("clientUniqueUserId") or "").strip()
            if status == "ACTIVE" and cid and tk_slug in ("gmail", "googlecalendar", "google"):
                target_conn_id = cid
                target_entity_id = uid or "glennbot_email_user"
                account_email, _ = _extract_email_from_composio_item(item)
                break

    if not target_conn_id:
        return {
            "status": "error",
            "message": "No active Google OAuth connection found yet. Please complete the Google login popup.",
            "imported_count": 0
        }

    if not account_email or _is_placeholder_connected_email(account_email):
        try:
            prof_res = _composio_execute_tool("GMAIL_GET_PROFILE", target_conn_id, target_entity_id, {"user_id": "me"})
            d_obj = (prof_res.get("data") or {}).get("response_data") or prof_res.get("data") or {}
            if isinstance(d_obj, dict):
                cand_em = str(d_obj.get("emailAddress") or d_obj.get("email") or "").strip().lower()
                if cand_em and "@" in cand_em:
                    account_email = cand_em
        except Exception:
            pass

    raw_persons: List[Dict[str, Any]] = []

    # 1. Try Composio Google Contacts & Gmail Contacts tools
    for tool_slug, tool_args in (
        ("GOOGLECONTACTS_LIST_CONTACTS", {"pageSize": 1000, "personFields": "names,emailAddresses,phoneNumbers,organizations,photos,biographies"}),
        ("GOOGLECONTACTS_GET_CONTACTS", {"pageSize": 1000}),
        ("GOOGLECONTACTS_LIST_OTHER_CONTACTS", {"pageSize": 1000, "readMask": "names,emailAddresses,phoneNumbers"}),
        ("GMAIL_GET_CONTACTS", {"resource_name": "people/me", "person_fields": "names,emailAddresses,phoneNumbers,organizations,photos,biographies", "page_size": 1000}),
        ("GMAIL_GET_PEOPLE", {"resource_name": "people/me", "person_fields": "names,emailAddresses,phoneNumbers,organizations,photos,biographies", "other_contacts": True}),
    ):
        try:
            t_res = _composio_execute_tool(tool_slug, target_conn_id, target_entity_id, tool_args)
            if isinstance(t_res, dict) and t_res.get("data"):
                extracted = _extract_person_nodes_from_payload(t_res.get("data"))
                if extracted:
                    raw_persons.extend(extracted)
        except Exception:
            pass

    # 2. Direct Google People API v1 using live OAuth access_token from Composio connected_account
    access_tok = ""
    try:
        if "_fetch_composio_connection_access_token" in globals():
            access_tok = _fetch_composio_connection_access_token(target_conn_id)
    except Exception:
        access_tok = ""

    if access_tok:
        g_headers = {"Authorization": f"Bearer {access_tok}", "Accept": "application/json"}
        next_pt = ""
        for _ in range(10):
            url_conn = "https://people.googleapis.com/v1/people/me/connections?personFields=names,emailAddresses,phoneNumbers,organizations,photos,biographies&pageSize=1000"
            if next_pt:
                url_conn += f"&pageToken={urllib.parse.quote(next_pt)}"
            try:
                gr = HTTP_SESSION.get(url_conn, headers=g_headers, timeout=15)
                if gr.status_code == 200:
                    g_data = gr.json() or {}
                    conns = g_data.get("connections") or []
                    if isinstance(conns, list):
                        raw_persons.extend(conns)
                    next_pt = str(g_data.get("nextPageToken") or "").strip()
                    if not next_pt:
                        break
                else:
                    break
            except Exception:
                break

        try:
            gr_other = HTTP_SESSION.get(
                "https://people.googleapis.com/v1/otherContacts?readMask=names,emailAddresses,phoneNumbers&pageSize=1000",
                headers=g_headers,
                timeout=15
            )
            if gr_other.status_code == 200:
                o_data = gr_other.json() or {}
                if isinstance(o_data.get("otherContacts"), list):
                    raw_persons.extend(o_data["otherContacts"])
        except Exception:
            pass

    # 3. Also try Composio proxy for Google People API if raw_persons is still empty
    if not raw_persons:
        try:
            p_res = _composio_execute_proxy(
                target_conn_id,
                target_entity_id,
                "https://people.googleapis.com/v1/people/me/connections?personFields=names,emailAddresses,phoneNumbers,organizations,photos,biographies&pageSize=1000",
                "GET"
            )
            p_data = p_res.get("data") if isinstance(p_res, dict) else {}
            if isinstance(p_data, dict) and isinstance(p_data.get("connections"), list):
                raw_persons.extend(p_data["connections"])
        except Exception:
            pass

    parsed_records: List[Dict[str, Any]] = []
    seen_refs = set()
    for person in raw_persons:
        rec = _parse_google_person_to_crm_record(person, account_email=account_email)
        if not rec:
            continue
        ref_key = f"{rec.get('source_ref_id')}::{rec.get('email_address')}::{rec.get('contact_number')}::{rec.get('first_name')}_{rec.get('last_name')}"
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        parsed_records.append(rec)

    # 4. If Google People API returned 0 contacts (e.g. Gmail-scoped token or contacts live in Gmail threads),
    # automatically harvest contacts from the user's Google/Gmail messages!
    if not parsed_records:
        gmail_harvested = _harvest_google_correspondents_from_gmail_messages(
            target_conn_id,
            target_entity_id,
            account_email=account_email
        )
        for grec in gmail_harvested:
            ref_key = f"{grec.get('email_address')}::{grec.get('contact_number')}"
            if ref_key not in seen_refs:
                seen_refs.add(ref_key)
                parsed_records.append(grec)

    with CONTACTS_CRM_LOCK:
        current_list = list(CONTACTS_CRM_STATE.get("contacts") or [])

    combined_input = current_list + parsed_records
    deduped_list, merged_dups = _deduplicate_and_combine_crm_contacts(combined_input)

    with CONTACTS_CRM_LOCK:
        CONTACTS_CRM_STATE["contacts"] = deduped_list

    for item in deduped_list:
        _upsert_crm_contact_in_db(item, sync_cloud=False)
    threading.Thread(target=_save_crm_contacts_to_cloudinary, daemon=True).start()

    return {
        "status": "success",
        "message": f"Successfully imported {len(parsed_records)} Google Contact(s) into CRM!",
        "account_email": account_email or "Google Account",
        "imported_count": len(parsed_records),
        "merged_duplicates": merged_dups,
        "total_contacts": len(deduped_list),
        "contacts": deduped_list
    }


@router.post("/api/oauth/google-contacts/start")
async def api_start_google_contacts_oauth(request: Request):
    res = await run_in_threadpool(lambda: _create_composio_google_contacts_oauth_link(request))
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.get("/api/oauth/google-contacts/redirect", response_class=HTMLResponse)
async def api_redirect_google_contacts_oauth(request: Request):
    res = await run_in_threadpool(lambda: _create_composio_google_contacts_oauth_link(request))
    if res.get("status") == "success" and res.get("auth_url"):
        auth_url = res["auth_url"]
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Connecting Google Contacts...</title>
    <style>
        body {{ background: #050b14; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }}
        .card {{ background: rgba(15, 23, 42, 0.95); border: 1px solid rgba(0, 240, 255, 0.45); border-radius: 16px; padding: 32px 28px; max-width: 390px; box-shadow: 0 0 35px rgba(0, 240, 255, 0.2); }}
        .spinner {{ width: 38px; height: 38px; border: 3px solid rgba(0, 240, 255, 0.2); border-top-color: #00f0ff; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px auto; }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .title {{ color: #00f0ff; font-size: 17px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #94a3b8; font-size: 13px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <div class="title">Connecting to Google Contacts...</div>
        <p class="sub">Redirecting you to Google OAuth2 Login via Composio...</p>
    </div>
    <script>window.location.replace({json.dumps(auth_url)});</script>
</body>
</html>"""
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h3>Could not initialize Google Contacts OAuth.</h3>", status_code=400)


@router.get("/api/oauth/google-contacts/callback", response_class=HTMLResponse)
async def api_google_contacts_oauth_callback(request: Request):
    """
    OAuth callback landing page after Google login. Immediately downloads and imports
    all Google Contacts from the authenticated account, notifies the main window, and closes the popup.
    """
    qp = request.query_params
    conn_id = str(qp.get("connectedAccountId") or qp.get("connected_account_id") or qp.get("connectionId") or "").strip()
    entity_id = str(qp.get("entity_id") or "").strip()
    if not conn_id and entity_id:
        sess_info = (GOOGLE_CONTACTS_AUTH_CONFIG_CACHE.get("pending_sessions") or {}).get(entity_id) or {}
        conn_id = str(sess_info.get("connected_account_id") or "").strip()

    import_res = await run_in_threadpool(lambda: _fetch_and_import_google_contacts_from_composio(conn_id, entity_id))
    imported_cnt = int(import_res.get("imported_count") or 0)
    total_cnt = int(import_res.get("total_contacts") or 0)
    acc_email = str(import_res.get("account_email") or "Google Account")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Google Contacts Imported!</title>
    <style>
        body {{ background: #050b14; color: #e2e8f0; font-family: 'Segoe UI', system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }}
        .card {{ background: rgba(15, 23, 42, 0.94); border: 1px solid rgba(16, 185, 129, 0.55); border-radius: 16px; padding: 32px 28px; max-width: 400px; box-shadow: 0 0 35px rgba(16, 185, 129, 0.25); }}
        .title {{ color: #34d399; font-size: 18px; font-weight: 700; margin-bottom: 8px; }}
        .sub {{ color: #cbd5e1; font-size: 13px; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="title">✅ Google Contacts Imported!</div>
        <p class="sub">Imported <strong>{imported_cnt}</strong> contact(s) from <strong>{acc_email}</strong> into your GlennBot CRM. Closing window...</p>
    </div>
    <script>
        try {{
            if (window.opener) {{
                window.opener.postMessage({{
                    type: 'GLENNBOT_GOOGLE_CONTACTS_IMPORT_DONE',
                    imported_count: {imported_cnt},
                    total_contacts: {total_cnt},
                    account_email: {json.dumps(acc_email)}
                }}, '*');
            }}
        }} catch (e) {{}}
        setTimeout(function() {{ window.close(); }}, 1000);
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.post("/api/contacts/import/google")
async def api_import_google_contacts_now(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    conn_id = str(body.get("connected_account_id") or "").strip()
    entity_id = str(body.get("entity_id") or "").strip()
    res = await run_in_threadpool(lambda: _fetch_and_import_google_contacts_from_composio(conn_id, entity_id))
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.delete("/api/contacts/{contact_id}")
async def api_delete_crm_contact(contact_id: str):
    return await run_in_threadpool(lambda: _delete_crm_contact_sync(contact_id))


def _delete_crm_contact_sync(contact_id: str):
    _load_crm_contacts_state(force_cloud=False)
    clean_id = str(contact_id or "").strip()
    with CONTACTS_CRM_LOCK:
        CONTACTS_CRM_STATE["contacts"] = [c for c in CONTACTS_CRM_STATE["contacts"] if str(c.get("id")) != clean_id]

    try:
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM glennbot_crm_contacts WHERE id = :id"), {"id": clean_id})
    except Exception as e:
        print(f"[ContactsCRM] Delete DB warning: {e}")

    threading.Thread(target=_save_crm_contacts_to_cloudinary, daemon=True).start()
    return {"status": "success", "message": "Contact deleted from CRM."}


