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
# --- TEXTBEE.DEV SMS GATEWAY INTEGRATION (SIM 2 + UNIFIED INBOX + WEBHOOKS) ---
# ==============================================================================
import hmac as _tb_hmac

TEXTBEE_RUNTIME_CONFIG: Dict[str, Any] = {
    "loaded": False,
    "api_key": TEXTBEE_API_KEY,
    "sim_subscription_id": TEXTBEE_SIM_SUBSCRIPTION_ID or "2",
    "device_id": TEXTBEE_DEVICE_ID,
    "webhook_secret": TEXTBEE_WEBHOOK_SECRET,
    "base_url": TEXTBEE_BASE_URL,
    "devices": [],
    "seen_sms_ids": set(),
    "webhook_hits_count": 0,
    "last_webhook_received_at": ""
}


def _normalize_sms_phone_number(raw_phone: str) -> str:
    """
    Normalizes Philippine (09... -> +639...) and international phone numbers
    for TextBee.dev SMS sending and conversation deduplication.
    """
    s = str(raw_phone or "").strip()
    if not s:
        return ""
    has_plus = s.startswith("+")
    digits = re.sub(r"\D+", "", s)
    if not digits:
        return s
    if digits.startswith("09") and len(digits) == 11:
        return "+63" + digits[1:]
    if digits.startswith("639") and len(digits) == 12:
        return "+" + digits
    if has_plus:
        return "+" + digits
    return "+" + digits if len(digits) >= 10 else digits


def _lookup_crm_contact_name_by_phone(phone_number: str) -> str:
    """
    Checks saved CRM Contacts to automatically resolve a human name for an incoming/outgoing SMS phone number.
    """
    norm_target = _normalize_sms_phone_number(phone_number)
    target_digits = re.sub(r"\D+", "", norm_target)
    if not target_digits:
        return ""
    target_last10 = target_digits[-10:] if len(target_digits) >= 10 else target_digits
    try:
        contacts_list = []
        if "_load_crm_contacts_state" in globals():
            contacts_list = _load_crm_contacts_state(force_cloud=False) or []
        elif "_load_crm_contacts_store" in globals():
            store = _load_crm_contacts_store(force_cloud=False) or {}
            contacts_list = store.get("contacts") or []

        for c in contacts_list:
            if not isinstance(c, dict):
                continue
            c_phone = str(c.get("contact_number") or c.get("phone") or "").strip()
            if not c_phone:
                continue
            c_digits = re.sub(r"\D+", "", _normalize_sms_phone_number(c_phone))
            if not c_digits:
                continue
            c_last10 = c_digits[-10:] if len(c_digits) >= 10 else c_digits
            if c_digits == target_digits or (len(target_last10) == 10 and c_last10 == target_last10):
                full_name = " ".join(
                    x for x in [
                        str(c.get("first_name") or "").strip(),
                        str(c.get("middle_name") or "").strip(),
                        str(c.get("last_name") or "").strip()
                    ] if x
                ).strip() or str(c.get("social_username") or c.get("display_name") or "").strip()
                if full_name:
                    return full_name
    except Exception:
        pass
    return ""


def _load_textbee_config_from_cloudinary() -> Dict[str, Any]:
    global TEXTBEE_API_KEY, TEXTBEE_SIM_SUBSCRIPTION_ID, TEXTBEE_DEVICE_ID, TEXTBEE_WEBHOOK_SECRET
    if TEXTBEE_RUNTIME_CONFIG.get("loaded"):
        return TEXTBEE_RUNTIME_CONFIG
    TEXTBEE_RUNTIME_CONFIG["loaded"] = True

    env_api_key = (os.getenv("TEXTBEE_API_KEY") or "").strip()
    env_dev_id = (os.getenv("TEXTBEE_DEVICE_ID") or "").strip()
    env_sim_id = (os.getenv("TEXTBEE_SIM_SUBSCRIPTION_ID") or "").strip()
    env_wh_sec = (os.getenv("TEXTBEE_WEBHOOK_SECRET") or os.getenv("TEXTBEE_SIGNING_SECRET") or "").strip()

    try:
        res = cloudinary.api.resource(CLOUDINARY_TEXTBEE_CONFIG_PUBLIC_ID, resource_type="raw")
        sec_url = res.get("secure_url") or res.get("url")
        if sec_url:
            resp = HTTP_SESSION.get(sec_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    cloud_key = str(data.get("api_key") or "").strip()
                    cloud_dev = str(data.get("device_id") or "").strip()
                    cloud_sim = str(data.get("sim_subscription_id") or "").strip()
                    cloud_sec = str(data.get("webhook_secret") or "").strip()

                    # Auto-heal if the 24-hex Device ID was previously stored inside cloud_key
                    if re.fullmatch(r"[0-9a-fA-F]{24}", cloud_key):
                        if not cloud_dev:
                            cloud_dev = cloud_key
                        cloud_key = ""

                    if env_api_key and not re.fullmatch(r"[0-9a-fA-F]{24}", env_api_key):
                        TEXTBEE_API_KEY = env_api_key
                    elif cloud_key:
                        TEXTBEE_API_KEY = cloud_key

                    if env_dev_id:
                        TEXTBEE_DEVICE_ID = env_dev_id
                    elif cloud_dev:
                        TEXTBEE_DEVICE_ID = cloud_dev

                    if env_sim_id:
                        TEXTBEE_SIM_SUBSCRIPTION_ID = env_sim_id
                    elif cloud_sim:
                        TEXTBEE_SIM_SUBSCRIPTION_ID = cloud_sim

                    if env_wh_sec:
                        TEXTBEE_WEBHOOK_SECRET = env_wh_sec
                    elif cloud_sec:
                        TEXTBEE_WEBHOOK_SECRET = cloud_sec
    except Exception:
        pass

    # Final safety auto-heal if TEXTBEE_API_KEY was a 24-hex device ID
    if re.fullmatch(r"[0-9a-fA-F]{24}", TEXTBEE_API_KEY):
        if not TEXTBEE_DEVICE_ID:
            TEXTBEE_DEVICE_ID = TEXTBEE_API_KEY
        TEXTBEE_API_KEY = env_api_key if (env_api_key and not re.fullmatch(r"[0-9a-fA-F]{24}", env_api_key)) else ""

    TEXTBEE_RUNTIME_CONFIG["api_key"] = TEXTBEE_API_KEY
    TEXTBEE_RUNTIME_CONFIG["sim_subscription_id"] = TEXTBEE_SIM_SUBSCRIPTION_ID or "2"
    TEXTBEE_RUNTIME_CONFIG["device_id"] = TEXTBEE_DEVICE_ID or ""
    TEXTBEE_RUNTIME_CONFIG["webhook_secret"] = TEXTBEE_WEBHOOK_SECRET or ""
    return TEXTBEE_RUNTIME_CONFIG


def _save_textbee_config_to_cloudinary(cfg: Dict[str, Any]):
    try:
        raw_bytes = json.dumps(cfg, indent=2).encode("utf-8")
        cloudinary.uploader.upload(
            io.BytesIO(raw_bytes),
            resource_type="raw",
            public_id=CLOUDINARY_TEXTBEE_CONFIG_PUBLIC_ID,
            overwrite=True,
            invalidate=True
        )
    except Exception as e:
        print(f"[⚠️ TEXTBEE CLOUDINARY CONFIG SAVE WARNING]: {e}")


def _discover_textbee_devices(api_key: str = "") -> List[Dict[str, Any]]:
    """
    Queries TextBee.dev API (`GET /api/v1/gateway/devices`) using `x-api-key`
    to automatically discover the user's registered Android gateway device(s).
    """
    global TEXTBEE_DEVICE_ID
    eff_key = (api_key or TEXTBEE_RUNTIME_CONFIG.get("api_key") or TEXTBEE_API_KEY).strip()
    if not eff_key:
        return []
    headers = {
        "x-api-key": eff_key,
        "Accept": "application/json"
    }
    devices_found: List[Dict[str, Any]] = []
    for ep in (f"{TEXTBEE_BASE_URL}/gateway/devices", "https://api.textbee.dev/api/v1/gateway/devices"):
        try:
            resp = HTTP_SESSION.get(ep, headers=headers, timeout=12)
            if resp.status_code == 200:
                payload = resp.json() if resp.text else {}
                raw_list = (
                    payload.get("data")
                    if isinstance(payload, dict) and isinstance(payload.get("data"), list)
                    else (payload if isinstance(payload, list) else extract_list_from_api_payload(payload))
                ) or []
                for d in raw_list:
                    if not isinstance(d, dict):
                        continue
                    did = str(d.get("_id") or d.get("id") or d.get("deviceId") or "").strip()
                    if not did:
                        continue
                    dname = str(d.get("name") or d.get("brand") or d.get("model") or f"Android Device ({did[-6:]})").strip()
                    brand = str(d.get("brand") or "").strip()
                    model = str(d.get("model") or "").strip()
                    if brand and model and brand.lower() not in dname.lower():
                        dname = f"{brand} {model} ({dname})"
                    devices_found.append({
                        "id": did,
                        "name": dname,
                        "brand": brand,
                        "model": model,
                        "enabled": bool(d.get("enabled", True))
                    })
                if devices_found:
                    break
        except Exception as e:
            print(f"[⚠️ TEXTBEE DEVICE DISCOVERY WARNING]: {e}")

    if devices_found:
        TEXTBEE_RUNTIME_CONFIG["devices"] = devices_found
        if not TEXTBEE_RUNTIME_CONFIG.get("device_id"):
            first_id = devices_found[0]["id"]
            TEXTBEE_DEVICE_ID = first_id
            TEXTBEE_RUNTIME_CONFIG["device_id"] = first_id
    return devices_found


def _upsert_textbee_sms_conversation_in_store(
    phone_number: str,
    message_text: str,
    is_own: bool,
    contact_name: str = "",
    message_id: str = "",
    sim_subscription_id: str = "",
    received_iso: str = "",
    save_async: bool = True
) -> Dict[str, Any]:
    """
    Creates or updates a Unified Inbox conversation under `TextBee SMS (SIM 2)`
    (`account_id = 'textbee_sms_sim_2'`, `platform = 'sms'`) in `CLOUDINARY_MESSAGES_STORE`.
    Returns {"conversation": target_conv, "message": msg_obj, "is_new_message": bool}.
    """
    if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
        load_messages_store_from_cloudinary()

    norm_phone = _normalize_sms_phone_number(phone_number)
    digits_only = re.sub(r"\D+", "", norm_phone) or re.sub(r"\W+", "", norm_phone) or "unknown"
    conv_id = f"sms_{digits_only}"
    conv_key = f"{TEXTBEE_ACCOUNT_ID}_{conv_id}"
    sim_id = str(sim_subscription_id or TEXTBEE_RUNTIME_CONFIG.get("sim_subscription_id") or TEXTBEE_SIM_SUBSCRIPTION_ID or "2").strip()
    acc_name = f"TextBee SMS (SIM {sim_id})"

    now_dt = datetime.now(pytz.timezone("Asia/Manila"))
    if received_iso:
        ts_parsed = parse_meta_timestamp(received_iso)
        msg_iso = ts_parsed.get("iso") or now_dt.isoformat()
        disp_time = ts_parsed.get("display") or now_dt.strftime("%b %d, %Y • %I:%M %p")
    else:
        msg_iso = now_dt.isoformat()
        disp_time = now_dt.strftime("%b %d, %Y • %I:%M %p")

    eff_msg_id = str(message_id or f"sms_msg_{int(time.time() * 1000)}").strip()

    convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
    existing_conv = convs_store.get(conv_key)

    display_person_name = (contact_name or "").strip()
    if not display_person_name:
        display_person_name = _lookup_crm_contact_name_by_phone(norm_phone)
    if not display_person_name and existing_conv:
        existing_pname = str(existing_conv.get("participant_name") or "").strip()
        if existing_pname and existing_pname != norm_phone:
            display_person_name = existing_pname
    if not display_person_name:
        display_person_name = norm_phone

    msg_obj = {
        "id": eff_msg_id,
        "platform_message_id": eff_msg_id,
        "sender_id": TEXTBEE_ACCOUNT_ID if is_own else norm_phone,
        "sender_name": acc_name if is_own else display_person_name,
        "sender_avatar": "",
        "is_own": bool(is_own),
        "message": message_text,
        "attachments": [],
        "created_iso": msg_iso,
        "display_time": disp_time
    }

    is_new_message = True
    if existing_conv and isinstance(existing_conv, dict):
        if _is_message_deleted_for_conversation(existing_conv, msg_obj):
            return {"conversation": existing_conv, "message": msg_obj, "is_new_message": False}
        msgs = _filter_out_deleted_messages(existing_conv, list(existing_conv.get("messages") or []))
        if any(
            str(m.get("id") or "") == eff_msg_id
            or str(m.get("platform_message_id") or "") == eff_msg_id
            or _are_messages_duplicate(m, msg_obj)
            for m in msgs if isinstance(m, dict)
        ):
            is_new_message = False

        existing_conv["messages"] = _filter_out_deleted_messages(existing_conv, _deduplicate_messages_list(msgs + [msg_obj]))
        existing_conv["participant_id"] = norm_phone
        existing_conv["participant_phone"] = norm_phone
        if display_person_name and display_person_name != norm_phone:
            existing_conv["participant_name"] = display_person_name
        existing_conv["account_name"] = acc_name
        existing_conv["hidden"] = False

        if is_new_message or _msg_iso_to_epoch(msg_iso) >= _msg_iso_to_epoch(existing_conv.get("updated_iso") or ""):
            existing_conv["last_message_text"] = message_text
            existing_conv["last_message_is_own"] = bool(is_own)
            existing_conv["updated_iso"] = now_dt.isoformat() if (is_new_message and not is_own) else msg_iso
            existing_conv["display_time"] = disp_time

        if is_own:
            existing_conv["is_read"] = True
            existing_conv["unread_count"] = 0
        elif is_new_message:
            existing_conv["is_read"] = False
            existing_conv["unread_count"] = int(existing_conv.get("unread_count") or 0) + 1
        target_conv = existing_conv
    else:
        target_conv = {
            "conv_key": conv_key,
            "conversation_id": conv_id,
            "platform_conversation_id": conv_id,
            "zernio_conversation_id": conv_id,
            "alternate_conversation_ids": [conv_id, norm_phone],
            "platform": "sms",
            "account_id": TEXTBEE_ACCOUNT_ID,
            "zernio_account_id": TEXTBEE_ACCOUNT_ID,
            "zernio_api_key": "",
            "account_name": acc_name,
            "account_avatar": "",
            "participant_id": norm_phone,
            "participant_name": display_person_name,
            "participant_handle": norm_phone,
            "participant_phone": norm_phone,
            "participant_email": "",
            "participant_avatar": "",
            "last_message_text": message_text,
            "last_message_is_own": bool(is_own),
            "updated_iso": now_dt.isoformat() if not is_own else msg_iso,
            "display_time": disp_time,
            "relative_time": "Just now",
            "has_authoritative_ts": True,
            "api_order_index": 0,
            "unread_count": 0 if is_own else 1,
            "is_read": bool(is_own),
            "hidden": False,
            "messages": [msg_obj]
        }
        convs_store[conv_key] = target_conv

    # When a new inbound SMS arrives (`is_own=False`), clear any older `glennbot_seen_messages` entry
    # so `get_inbox_conversations` immediately highlights the thread as Unread with notification badge!
    if is_new_message and not is_own:
        try:
            with db_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM glennbot_seen_messages WHERE conversation_id IN (:ck, :cid, :ph)"),
                    {"ck": conv_key, "cid": conv_id, "ph": norm_phone}
                )
        except Exception:
            pass

    if save_async and is_new_message:
        save_messages_store_async()
    return {"conversation": target_conv, "message": msg_obj, "is_new_message": is_new_message}


def _send_textbee_sms_and_upsert_conversation(
    recipient_phone: str,
    message_text: str,
    recipient_name: str = "",
    custom_device_id: str = "",
    custom_sim_id: str = "",
    trigger_n8n_webhook: bool = True
) -> Dict[str, Any]:
    """
    Sends an outbound SMS via TextBee.dev REST API:
    POST https://api.textbee.dev/api/v1/gateway/devices/{deviceId}/send-sms
    Headers: x-api-key: <TEXTBEE_API_KEY>
    Payload: {"recipients": ["+63..."], "message": "...", "simSubscriptionId": 2}
    and records the message in the Unified Inbox (`CLOUDINARY_MESSAGES_STORE`).
    When `trigger_n8n_webhook=True` (i.e. user initiated SMS from GUI), dispatches `sms.sent` to n8n!
    """
    _load_textbee_config_from_cloudinary()
    norm_phone = _normalize_sms_phone_number(recipient_phone)
    clean_msg = (message_text or "").strip()
    if not norm_phone:
        return {"status": "error", "message": "Recipient phone number is required (e.g., +639171234567 or 09171234567)."}
    if not clean_msg:
        return {"status": "error", "message": "SMS message text cannot be empty."}

    api_key = (TEXTBEE_RUNTIME_CONFIG.get("api_key") or TEXTBEE_API_KEY).strip()
    if not api_key:
        return {"status": "error", "message": "TextBee API Key is not configured."}

    sim_str = str(custom_sim_id or TEXTBEE_RUNTIME_CONFIG.get("sim_subscription_id") or TEXTBEE_SIM_SUBSCRIPTION_ID or "2").strip()
    dev_id = (custom_device_id or TEXTBEE_RUNTIME_CONFIG.get("device_id") or TEXTBEE_DEVICE_ID).strip()

    if not dev_id:
        discovered = _discover_textbee_devices(api_key)
        if discovered:
            dev_id = discovered[0]["id"]

    if not dev_id:
        return {
            "status": "error",
            "message": (
                "No TextBee Android Device ID found yet. Please open the TextBee Android App, log in with your "
                "TextBee account, or enter your Device ID in the TextBee SMS Settings modal."
            )
        }

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    sim_val: Any = int(sim_str) if sim_str.isdigit() else sim_str
    send_url = f"{TEXTBEE_BASE_URL}/gateway/devices/{requests.utils.quote(dev_id, safe='')}/send-sms"

    payload_variants = [
        {"recipients": [norm_phone], "message": clean_msg, "simSubscriptionId": sim_val},
        {"recipients": [norm_phone], "message": clean_msg}
    ]

    last_err = ""
    sent_msg_id = f"sms_{int(time.time() * 1000)}"
    sent_success = False

    for body_try in payload_variants:
        try:
            resp = HTTP_SESSION.post(send_url, headers=headers, json=body_try, timeout=20)
            if resp.status_code in (200, 201, 202):
                sent_success = True
                try:
                    rdata = resp.json() if resp.text else {}
                    inner = rdata.get("data") if isinstance(rdata, dict) else {}
                    if isinstance(inner, dict) and (inner.get("_id") or inner.get("id") or inner.get("smsBatchId")):
                        sent_msg_id = str(inner.get("_id") or inner.get("id") or inner.get("smsBatchId"))
                except Exception:
                    pass
                break
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            last_err = str(e)

    if not sent_success:
        return {
            "status": "error",
            "message": f"TextBee.dev SMS API Error: {last_err or 'Could not reach TextBee gateway device.'}"
        }

    seen_sms_set: set = TEXTBEE_RUNTIME_CONFIG.setdefault("seen_sms_ids", set())
    seen_sms_set.add(sent_msg_id)

    upserted = _upsert_textbee_sms_conversation_in_store(
        phone_number=norm_phone,
        message_text=clean_msg,
        is_own=True,
        contact_name=recipient_name,
        message_id=sent_msg_id,
        sim_subscription_id=sim_str
    )
    conv_obj = upserted["conversation"]
    msg_obj = upserted["message"]

    # When the user initiates an SMS from GlennBot GUI (trigger_n8n_webhook=True), notify n8n via `sms.sent`!
    if trigger_n8n_webhook and "_dispatch_outbound_n8n_webhook_async" in globals():
        try:
            _dispatch_outbound_n8n_webhook_async("sms.sent", {
                "event": "sms.sent",
                "platform": "sms",
                "direction": "outbound",
                "is_own": True,
                "account_id": TEXTBEE_ACCOUNT_ID,
                "account_name": conv_obj.get("account_name") or f"TextBee SMS (SIM {sim_str})",
                "conversation_id": conv_obj.get("conversation_id"),
                "recipient_phone": conv_obj.get("participant_id") or norm_phone,
                "recipient": conv_obj.get("participant_id") or norm_phone,
                "phone": conv_obj.get("participant_id") or norm_phone,
                "to": conv_obj.get("participant_id") or norm_phone,
                "participant_id": conv_obj.get("participant_id") or norm_phone,
                "recipient_name": conv_obj.get("participant_name") or recipient_name or norm_phone,
                "participant_name": conv_obj.get("participant_name") or recipient_name or norm_phone,
                "message": clean_msg,
                "text": clean_msg,
                "message_id": sent_msg_id,
                "sent_at": msg_obj.get("created_iso"),
                "device_id": dev_id,
                "sim_subscription_id": sim_str
            })
        except Exception as e:
            print(f"[⚠️ SMS.SENT N8N DISPATCH WARNING]: {e}")

    return {
        "status": "success",
        "message_id": sent_msg_id,
        "recipient": norm_phone,
        "sim_subscription_id": sim_str,
        "device_id": dev_id,
        "message": msg_obj,
        "conversation": {k: v for k, v in conv_obj.items() if k != "messages"}
    }


def _verify_textbee_webhook_signature(raw_bytes: bytes, req_headers: Dict[str, str]) -> Tuple[bool, str]:
    """
    Verifies TextBee.dev's `X-Signature` header (HMAC-SHA256 of raw request body
    signed with `TEXTBEE_WEBHOOK_SECRET`, e.g. '9ecc8025-55d2-4038-9873-42ebc67eca64').
    Returns (is_verified, status_reason).
    """
    _load_textbee_config_from_cloudinary()
    secret = str(TEXTBEE_RUNTIME_CONFIG.get("webhook_secret") or TEXTBEE_WEBHOOK_SECRET or "").strip()
    sig_header = str(
        req_headers.get("x-signature")
        or req_headers.get("x-textbee-signature")
        or req_headers.get("x-webhook-signature")
        or ""
    ).strip()

    if not secret:
        return True, "no_secret_configured"
    if not sig_header:
        return False, "missing_x_signature_header"

    clean_sig = sig_header
    if clean_sig.lower().startswith("sha256="):
        clean_sig = clean_sig.split("=", 1)[1].strip()

    try:
        expected_hex = _tb_hmac.new(secret.encode("utf-8"), raw_bytes or b"", hashlib.sha256).hexdigest()
        if _tb_hmac.compare_digest(expected_hex.lower(), clean_sig.lower()):
            return True, "valid_hmac_sha256"
        # Also allow direct token match if user passed the secret directly as a header
        if _tb_hmac.compare_digest(secret, clean_sig):
            return True, "valid_direct_secret"
    except Exception as e:
        return False, f"signature_check_error:{e}"

    return False, "signature_mismatch"


def _is_textbee_sms_webhook_payload(
    body: Any,
    req_headers: Optional[Dict[str, str]] = None,
    req_path: str = "",
    raw_bytes: bytes = b""
) -> bool:
    """
    Detects whether an incoming webhook request on `/webhooks`, `/webhook`, `/api/webhooks/textbee/sms`, etc.
    is an inbound SMS webhook from TextBee.dev.
    """
    path_low = str(req_path or "").lower()
    if "textbee" in path_low or "/webhooks/sms" in path_low or "/api/webhooks/sms" in path_low:
        return True

    headers_map = {str(k).lower(): str(v) for k, v in (req_headers or {}).items()}
    if raw_bytes and headers_map.get("x-signature"):
        verified_sig, _ = _verify_textbee_webhook_signature(raw_bytes, headers_map)
        if verified_sig:
            return True

    if not isinstance(body, dict):
        return False

    data_obj = body.get("data") if isinstance(body.get("data"), dict) else body
    wh_evt = str(
        body.get("webhookEvent")
        or data_obj.get("webhookEvent")
        or body.get("event")
        or body.get("type")
        or ""
    ).strip().upper()

    if wh_evt in ("MESSAGE_RECEIVED", "MESSAGE_SENT", "MESSAGE_FAILED", "SMS_RECEIVED", "SMS.RECEIVED"):
        return True

    if any(k in body or k in data_obj for k in ("smsId", "webhookSubscriptionId", "smsBatchId")):
        return True

    return False


def _handle_textbee_inbound_sms_webhook_event(
    body: Dict[str, Any],
    raw_bytes: bytes = b"",
    req_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Processes a real-time TextBee.dev webhook payload (`MESSAGE_RECEIVED`), verifies its `X-Signature`
    using `TEXTBEE_WEBHOOK_SECRET` (9ecc8025-55d2-4038-9873-42ebc67eca64), deduplicates by `idempotencyKey`/`smsId`,
    saves the incoming SMS into Unified Inbox (`TextBee SMS (SIM 2)`), and triggers n8n webhooks.
    """
    _load_textbee_config_from_cloudinary()
    headers_map = {str(k).lower(): str(v) for k, v in (req_headers or {}).items()}
    sig_verified, sig_reason = _verify_textbee_webhook_signature(raw_bytes, headers_map)

    data_obj = body.get("data") if isinstance(body.get("data"), dict) else body
    if not isinstance(data_obj, dict):
        data_obj = {}

    wh_event = str(
        body.get("webhookEvent")
        or data_obj.get("webhookEvent")
        or body.get("event")
        or "MESSAGE_RECEIVED"
    ).strip().upper()

    print(
        f"\n[📱 TEXTBEE.DEV WEBHOOK RECEIVED] Event={wh_event} | Signature={sig_reason} (verified={sig_verified}) | "
        f"Payload={json.dumps(body)[:400]}"
    )

    TEXTBEE_RUNTIME_CONFIG["webhook_hits_count"] = int(TEXTBEE_RUNTIME_CONFIG.get("webhook_hits_count") or 0) + 1
    TEXTBEE_RUNTIME_CONFIG["last_webhook_received_at"] = datetime.now(pytz.timezone("Asia/Manila")).strftime("%b %d, %Y • %I:%M:%S %p")

    # If a Device ID is included in the webhook payload, auto-heal TEXTBEE_DEVICE_ID if needed
    incoming_dev_id = str(data_obj.get("deviceId") or body.get("deviceId") or "").strip()
    if incoming_dev_id and not TEXTBEE_RUNTIME_CONFIG.get("device_id"):
        global TEXTBEE_DEVICE_ID
        TEXTBEE_DEVICE_ID = incoming_dev_id
        TEXTBEE_RUNTIME_CONFIG["device_id"] = incoming_dev_id

    if wh_event == "MESSAGE_FAILED":
        return {
            "status": "success",
            "event": wh_event,
            "signature_verified": sig_verified,
            "signature_status": sig_reason
        }

    is_outbound_sent_event = wh_event in ("MESSAGE_SENT", "SMS_SENT", "SMS.SENT")

    rcpts_list = data_obj.get("recipients") or body.get("recipients") or []
    first_rcpt = str(rcpts_list[0]).strip() if isinstance(rcpts_list, list) and rcpts_list else ""

    sender_phone = str(
        (
            data_obj.get("recipient")
            or data_obj.get("to")
            or first_rcpt
            or data_obj.get("phoneNumber")
            or data_obj.get("phone")
            or body.get("recipient")
            or body.get("to")
            or ""
        )
        if is_outbound_sent_event
        else (
            data_obj.get("sender")
            or data_obj.get("from")
            or data_obj.get("phoneNumber")
            or data_obj.get("phone")
            or body.get("sender")
            or body.get("from")
            or ""
        )
    ).strip()
    sms_text = str(
        data_obj.get("message")
        or data_obj.get("text")
        or data_obj.get("body")
        or body.get("message")
        or body.get("text")
        or ""
    ).strip()
    sender_name = str(
        data_obj.get("senderName")
        or data_obj.get("recipientName")
        or data_obj.get("contactName")
        or body.get("senderName")
        or ""
    ).strip()
    msg_id = str(
        data_obj.get("smsId")
        or body.get("smsId")
        or data_obj.get("smsBatchId")
        or body.get("smsBatchId")
        or data_obj.get("messageId")
        or data_obj.get("_id")
        or data_obj.get("id")
        or body.get("idempotencyKey")
        or f"{'out' if is_outbound_sent_event else 'in'}_sms_{int(time.time() * 1000)}"
    ).strip()
    idempotency_key = str(body.get("idempotencyKey") or data_obj.get("idempotencyKey") or msg_id).strip()
    received_at = str(
        data_obj.get("receivedAt")
        or body.get("receivedAt")
        or data_obj.get("sentAt")
        or body.get("sentAt")
        or data_obj.get("createdAt")
        or body.get("createdAt")
        or data_obj.get("timestamp")
        or ""
    ).strip()
    sim_id = str(
        data_obj.get("simSubscriptionId")
        or body.get("simSubscriptionId")
        or TEXTBEE_RUNTIME_CONFIG.get("sim_subscription_id")
        or TEXTBEE_SIM_SUBSCRIPTION_ID
        or "2"
    ).strip()

    if not sender_phone or not sms_text:
        return {
            "status": "ignored",
            "event": wh_event,
            "reason": "Missing phone number or message in TextBee webhook payload.",
            "signature_verified": sig_verified
        }

    seen_sms_set: set = TEXTBEE_RUNTIME_CONFIG.setdefault("seen_sms_ids", set())
    if idempotency_key in seen_sms_set or msg_id in seen_sms_set:
        return {
            "status": "success",
            "event": wh_event,
            "duplicate": True,
            "message_id": msg_id,
            "signature_verified": sig_verified
        }
    seen_sms_set.add(idempotency_key)
    seen_sms_set.add(msg_id)

    upserted = _upsert_textbee_sms_conversation_in_store(
        phone_number=sender_phone,
        message_text=sms_text,
        is_own=is_outbound_sent_event,
        contact_name=sender_name,
        message_id=msg_id,
        sim_subscription_id=sim_id,
        received_iso=received_at,
        save_async=True
    )
    conv_obj = upserted["conversation"]
    msg_obj = upserted["message"]

    if upserted.get("is_new_message", True):
        if is_outbound_sent_event:
            _dispatch_outbound_n8n_webhook_async("sms.sent", {
                "event": "sms.sent",
                "platform": "sms",
                "direction": "outbound",
                "is_own": True,
                "account_id": TEXTBEE_ACCOUNT_ID,
                "account_name": conv_obj.get("account_name"),
                "conversation_id": conv_obj.get("conversation_id"),
                "recipient_phone": conv_obj.get("participant_id"),
                "recipient": conv_obj.get("participant_id"),
                "phone": conv_obj.get("participant_id"),
                "to": conv_obj.get("participant_id"),
                "participant_id": conv_obj.get("participant_id"),
                "recipient_name": conv_obj.get("participant_name"),
                "participant_name": conv_obj.get("participant_name"),
                "message": sms_text,
                "text": sms_text,
                "message_id": msg_id,
                "sent_at": msg_obj.get("created_iso"),
                "device_id": incoming_dev_id or TEXTBEE_RUNTIME_CONFIG.get("device_id") or TEXTBEE_DEVICE_ID,
                "sim_subscription_id": sim_id
            })
        else:
            _dispatch_outbound_n8n_webhook_async("sms.received", {
                "event": "sms.received",
                "platform": "sms",
                "direction": "inbound",
                "is_own": False,
                "account_id": TEXTBEE_ACCOUNT_ID,
                "account_name": conv_obj.get("account_name"),
                "conversation_id": conv_obj.get("conversation_id"),
                "sender_phone": conv_obj.get("participant_id"),
                "sender": conv_obj.get("participant_id"),
                "phone": conv_obj.get("participant_id"),
                "from": conv_obj.get("participant_id"),
                "participant_id": conv_obj.get("participant_id"),
                "sender_name": conv_obj.get("participant_name"),
                "participant_name": conv_obj.get("participant_name"),
                "message": sms_text,
                "text": sms_text,
                "message_id": msg_id,
                "received_at": msg_obj.get("created_iso"),
                "device_id": incoming_dev_id or TEXTBEE_RUNTIME_CONFIG.get("device_id") or TEXTBEE_DEVICE_ID,
                "sim_subscription_id": sim_id
            })

    return {
        "status": "success",
        "event": wh_event,
        "signature_verified": sig_verified,
        "signature_status": sig_reason,
        "conversation_id": conv_obj.get("conversation_id"),
        "message_id": msg_id
    }


def _sync_received_textbee_sms_messages() -> bool:
    """
    Polls TextBee.dev API for recently received SMS messages (`GET /gateway/devices/{deviceId}/get-received-sms`
    and `GET /gateway/messages?direction=received&limit=20`) so that even if a webhook was missed while
    offline, incoming SMS messages still appear in Unified Inbox automatically.
    """
    _load_textbee_config_from_cloudinary()
    api_key = (TEXTBEE_RUNTIME_CONFIG.get("api_key") or TEXTBEE_API_KEY).strip()
    dev_id = (TEXTBEE_RUNTIME_CONFIG.get("device_id") or TEXTBEE_DEVICE_ID).strip()
    if not api_key or re.fullmatch(r"[0-9a-fA-F]{24}", api_key):
        return False

    headers = {
        "x-api-key": api_key,
        "Accept": "application/json"
    }
    endpoints: List[str] = []
    if dev_id:
        endpoints.append(f"{TEXTBEE_BASE_URL}/gateway/devices/{requests.utils.quote(dev_id, safe='')}/get-received-sms")
    endpoints.append(f"{TEXTBEE_BASE_URL}/gateway/messages?direction=received&limit=20")

    any_new = False
    seen_sms_set: set = TEXTBEE_RUNTIME_CONFIG.setdefault("seen_sms_ids", set())

    for ep in endpoints:
        try:
            resp = HTTP_SESSION.get(ep, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            payload = resp.json() if resp.text else {}
            raw_list = (
                payload.get("data")
                if isinstance(payload, dict) and isinstance(payload.get("data"), list)
                else (payload if isinstance(payload, list) else extract_list_from_api_payload(payload))
            ) or []
            if not isinstance(raw_list, list) or not raw_list:
                continue

            for item in reversed(raw_list[:25]):
                if not isinstance(item, dict):
                    continue
                direction = str(item.get("direction") or item.get("type") or "received").strip().lower()
                if direction in ("sent", "outbound", "outgoing"):
                    continue
                s_phone = str(item.get("sender") or item.get("from") or item.get("phoneNumber") or item.get("phone") or "").strip()
                s_msg = str(item.get("message") or item.get("text") or item.get("body") or "").strip()
                if not s_phone or not s_msg:
                    continue
                s_id = str(item.get("_id") or item.get("id") or item.get("smsId") or item.get("messageId") or "").strip()
                if not s_id:
                    s_id = "tb_rx_" + hashlib.md5(f"{s_phone}::{s_msg}::{item.get('receivedAt') or item.get('createdAt') or ''}".encode("utf-8")).hexdigest()[:16]
                if s_id in seen_sms_set:
                    continue
                seen_sms_set.add(s_id)

                rec_iso = str(item.get("receivedAt") or item.get("received_at") or item.get("createdAt") or item.get("created_at") or "").strip()
                up_res = _upsert_textbee_sms_conversation_in_store(
                    phone_number=s_phone,
                    message_text=s_msg,
                    is_own=False,
                    contact_name=str(item.get("senderName") or item.get("contactName") or "").strip(),
                    message_id=s_id,
                    received_iso=rec_iso,
                    save_async=False
                )
                if up_res.get("is_new_message"):
                    any_new = True
            if raw_list:
                break
        except Exception:
            continue

    if any_new:
        save_messages_store_async()
    return any_new


class TextBeeConfigPayload(BaseModel):
    api_key: Optional[str] = ""
    device_id: Optional[str] = ""
    sim_subscription_id: Optional[str] = "2"
    webhook_secret: Optional[str] = ""


class TextBeeSendSmsPayload(BaseModel):
    recipient: str
    message: str
    recipient_name: Optional[str] = ""
    device_id: Optional[str] = ""
    sim_subscription_id: Optional[str] = ""


@router.get("/api/sms/textbee/status")
def api_get_textbee_status(request: Request, discover: bool = True):
    _load_textbee_config_from_cloudinary()
    api_key = (TEXTBEE_RUNTIME_CONFIG.get("api_key") or TEXTBEE_API_KEY).strip()
    sim_id = str(TEXTBEE_RUNTIME_CONFIG.get("sim_subscription_id") or TEXTBEE_SIM_SUBSCRIPTION_ID or "2").strip()
    dev_id = (TEXTBEE_RUNTIME_CONFIG.get("device_id") or TEXTBEE_DEVICE_ID).strip()
    wh_sec = (TEXTBEE_RUNTIME_CONFIG.get("webhook_secret") or TEXTBEE_WEBHOOK_SECRET).strip()

    devices = TEXTBEE_RUNTIME_CONFIG.get("devices") or []
    if discover and api_key:
        discovered = _discover_textbee_devices(api_key)
        if discovered:
            devices = discovered
            if not dev_id:
                dev_id = discovered[0]["id"]

    pub_base = get_dynamic_base_url(request=request, prefer_public=True)
    webhook_url = f"{pub_base}/api/webhooks/textbee/sms"

    return {
        "status": "success",
        "configured": bool(api_key),
        "api_key": api_key,
        "sim_subscription_id": sim_id,
        "device_id": dev_id,
        "webhook_secret": wh_sec,
        "base_url": TEXTBEE_BASE_URL,
        "account_id": TEXTBEE_ACCOUNT_ID,
        "account_name": f"TextBee SMS (SIM {sim_id})",
        "devices": devices,
        "webhook_url": webhook_url,
        "alternate_webhook_url": f"{pub_base}/webhooks",
        "webhook_hits_count": int(TEXTBEE_RUNTIME_CONFIG.get("webhook_hits_count") or 0),
        "last_webhook_received_at": str(TEXTBEE_RUNTIME_CONFIG.get("last_webhook_received_at") or "")
    }


@router.post("/api/sms/textbee/config")
def api_save_textbee_config(payload: TextBeeConfigPayload, request: Request):
    global TEXTBEE_API_KEY, TEXTBEE_SIM_SUBSCRIPTION_ID, TEXTBEE_DEVICE_ID, TEXTBEE_WEBHOOK_SECRET
    _load_textbee_config_from_cloudinary()

    if payload.api_key is not None and payload.api_key.strip():
        TEXTBEE_API_KEY = payload.api_key.strip()
        TEXTBEE_RUNTIME_CONFIG["api_key"] = TEXTBEE_API_KEY
    if payload.sim_subscription_id is not None and str(payload.sim_subscription_id).strip():
        TEXTBEE_SIM_SUBSCRIPTION_ID = str(payload.sim_subscription_id).strip()
        TEXTBEE_RUNTIME_CONFIG["sim_subscription_id"] = TEXTBEE_SIM_SUBSCRIPTION_ID
    if payload.device_id is not None:
        TEXTBEE_DEVICE_ID = payload.device_id.strip()
        TEXTBEE_RUNTIME_CONFIG["device_id"] = TEXTBEE_DEVICE_ID
    if payload.webhook_secret is not None and payload.webhook_secret.strip():
        TEXTBEE_WEBHOOK_SECRET = payload.webhook_secret.strip()
        TEXTBEE_RUNTIME_CONFIG["webhook_secret"] = TEXTBEE_WEBHOOK_SECRET

    if TEXTBEE_API_KEY and not TEXTBEE_DEVICE_ID:
        discovered = _discover_textbee_devices(TEXTBEE_API_KEY)
        if discovered:
            TEXTBEE_DEVICE_ID = discovered[0]["id"]
            TEXTBEE_RUNTIME_CONFIG["device_id"] = TEXTBEE_DEVICE_ID

    cfg_to_save = {
        "api_key": TEXTBEE_API_KEY,
        "sim_subscription_id": TEXTBEE_SIM_SUBSCRIPTION_ID,
        "device_id": TEXTBEE_DEVICE_ID,
        "webhook_secret": TEXTBEE_WEBHOOK_SECRET,
        "updated_at": datetime.now(pytz.timezone("Asia/Manila")).isoformat()
    }
    threading.Thread(target=_save_textbee_config_to_cloudinary, args=(cfg_to_save,), daemon=True).start()
    refresh_connected_accounts_cache(force=True)

    return api_get_textbee_status(request=request, discover=True)


@router.post("/api/sms/textbee/send")
def api_send_textbee_sms(payload: TextBeeSendSmsPayload):
    """
    Initiates a brand-new SMS or replies to an existing phone number via TextBee.dev (SIM 2)
    and automatically creates/updates the conversation thread in Unified Inbox.
    """
    return _send_textbee_sms_and_upsert_conversation(
        recipient_phone=payload.recipient,
        message_text=payload.message,
        recipient_name=payload.recipient_name or "",
        custom_device_id=payload.device_id or "",
        custom_sim_id=payload.sim_subscription_id or ""
    )


@router.get("/api/webhooks/textbee/sms")
@router.get("/api/webhooks/textbee")
@router.get("/webhooks/textbee")
@router.get("/webhooks/sms")
@router.get("/api/webhooks/sms")
async def api_textbee_webhook_verify_get(request: Request):
    live_base = get_dynamic_base_url(request=request, prefer_public=True)
    return {
        "status": "active",
        "service": "TextBee.dev Inbound SMS Webhook Receiver",
        "webhook_url": f"{live_base}/api/webhooks/textbee/sms",
        "alternate_webhook_url": f"{live_base}/webhooks",
        "signing_secret_configured": bool(TEXTBEE_WEBHOOK_SECRET),
        "device_id": TEXTBEE_DEVICE_ID,
        "sim_subscription_id": TEXTBEE_SIM_SUBSCRIPTION_ID
    }


@router.post("/api/webhooks/textbee/sms")
@router.post("/api/webhooks/textbee")
@router.post("/webhooks/textbee")
@router.post("/webhooks/sms")
@router.post("/api/webhooks/sms")
async def api_textbee_inbound_sms_webhook(request: Request):
    """
    Receives real-time Inbound SMS webhooks from TextBee.dev (`MESSAGE_RECEIVED` / `sms.received`),
    verifies the `X-Signature` header using `TEXTBEE_WEBHOOK_SECRET` (9ecc8025-55d2-4038-9873-42ebc67eca64),
    adds the message into the Unified Inbox (`TextBee SMS (SIM 2)`), and forwards the event
    to any subscribed n8n outbound webhooks.
    """
    try:
        raw_bytes = await request.body()
        body = json.loads(raw_bytes.decode("utf-8")) if raw_bytes else {}
    except Exception:
        raw_bytes = b""
        body = {}
    req_headers = {str(k).lower(): str(v) for k, v in request.headers.items()}
    return await run_in_threadpool(lambda: _handle_textbee_inbound_sms_webhook_event(body, raw_bytes, req_headers))


@router.post("/api/v1/sms/send")
async def api_v1_send_textbee_sms(request: Request):
    """
    Internal API v1 endpoint for n8n workflows to send an SMS via TextBee.dev (SIM 2).
    JSON Body:
      - recipient / phone / to / recipient_phone (str, required): Phone number (e.g. "+639171234567" or "09171234567")
      - message / text (str, required): SMS text body
      - recipient_name (str, optional): Contact name for Unified Inbox
      - sim_subscription_id (str/int, optional): Defaults to "2"
      - trigger_webhook (bool, optional): Defaults to False so n8n's automated SMS doesn't loop back into n8n
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    rcpt = str(
        body.get("recipient")
        or body.get("recipient_phone")
        or body.get("phone")
        or body.get("to")
        or body.get("recipient_id")
        or body.get("participant_id")
        or ""
    ).strip()
    msg_txt = str(body.get("message") or body.get("text") or "").strip()
    rcpt_name = str(body.get("recipient_name") or body.get("participant_name") or body.get("name") or "").strip()
    sim_id = str(body.get("sim_subscription_id") or body.get("simSubscriptionId") or "").strip()
    dev_id = str(body.get("device_id") or body.get("deviceId") or "").strip()
    trigger_wh = bool(body.get("trigger_webhook", False))

    res = await run_in_threadpool(
        lambda: _send_textbee_sms_and_upsert_conversation(
            recipient_phone=rcpt,
            message_text=msg_txt,
            recipient_name=rcpt_name,
            custom_device_id=dev_id,
            custom_sim_id=sim_id,
            trigger_n8n_webhook=trigger_wh
        )
    )
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.get("/api/v1/sms/thread-status")
async def api_v1_check_textbee_sms_thread_status(
    request: Request,
    phone: str = "",
    recipient_phone: str = "",
    conversation_id: str = "",
    message_id: str = "",
    force: bool = True
):
    """
    Internal API v1 endpoint for n8n workflows to check if a recipient has replied to an SMS
    after a Wait timer (e.g. User Initiates SMS -> Wait 2 minutes -> Check SMS Thread Status -> If Yes / If No).
    Query Params:
      - phone / recipient_phone (str): Recipient's phone number (e.g. "+639175497760")
      - conversation_id (str, optional): SMS conversation ID (e.g. "sms_639175497760")
      - message_id (str, optional): The outbound SMS message_id that initiated the thread
      - force (bool, optional): If true, polls TextBee API for any new received SMS first
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    target_phone_raw = (phone or recipient_phone or "").strip()
    if not target_phone_raw and conversation_id.startswith("sms_"):
        target_phone_raw = conversation_id.replace("sms_", "").strip()
    norm_phone = _normalize_sms_phone_number(target_phone_raw) if target_phone_raw else ""

    # Support n8n simulated test payloads
    if str(message_id).startswith("test_sms_") or str(conversation_id).startswith("test_sms_"):
        return {
            "status": "success",
            "phone": norm_phone or "+639171234567",
            "conversation_id": conversation_id or "sms_639171234567",
            "has_reply_to_sms": True,
            "replied": True,
            "latest_reply_id": f"sim_reply_{int(time.time())}",
            "latest_reply_message": "Yes, I received your text message!",
            "latest_reply_sender": norm_phone or "+639171234567",
            "simulated_test": True
        }

    if force:
        await run_in_threadpool(_sync_received_textbee_sms_messages)

    if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
        await run_in_threadpool(load_messages_store_from_cloudinary)

    convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
    digits = re.sub(r"[^\d]", "", norm_phone)
    conv_id_lookup = conversation_id or (f"sms_{digits}" if digits else "")
    conv_key = f"{TEXTBEE_ACCOUNT_ID}_{conv_id_lookup}" if conv_id_lookup else ""

    target_conv = convs_store.get(conv_key) if conv_key else None
    if not target_conv and digits:
        for k, c_obj in convs_store.items():
            if not isinstance(c_obj, dict):
                continue
            if str(c_obj.get("platform") or "").lower() == "sms":
                p_digits = re.sub(r"[^\d]", "", str(c_obj.get("participant_id") or ""))
                if p_digits and (p_digits == digits or p_digits[-10:] == digits[-10:]):
                    target_conv = c_obj
                    break

    if not target_conv:
        return {
            "status": "success",
            "phone": norm_phone,
            "conversation_id": conv_id_lookup,
            "has_reply_to_sms": False,
            "replied": False,
            "latest_reply_id": "",
            "latest_reply_message": "",
            "latest_reply_sender": norm_phone
        }

    msgs = target_conv.get("messages") if isinstance(target_conv.get("messages"), list) else []
    anchor_idx = -1
    if message_id:
        for idx, m in enumerate(msgs):
            if isinstance(m, dict) and str(m.get("id") or "") == str(message_id):
                anchor_idx = idx
                break

    if anchor_idx == -1:
        # Find the most recent outbound (is_own=True) message index
        for idx in range(len(msgs) - 1, -1, -1):
            m = msgs[idx]
            if isinstance(m, dict) and bool(m.get("is_own", False)):
                anchor_idx = idx
                break

    latest_inbound_after_anchor: Optional[Dict[str, Any]] = None
    search_slice = msgs[anchor_idx + 1:] if anchor_idx >= 0 else msgs
    for m in search_slice:
        if isinstance(m, dict) and not bool(m.get("is_own", False)):
            latest_inbound_after_anchor = m

    has_reply = latest_inbound_after_anchor is not None
    return {
        "status": "success",
        "phone": target_conv.get("participant_id") or norm_phone,
        "conversation_id": target_conv.get("conversation_id") or conv_id_lookup,
        "has_reply_to_sms": has_reply,
        "replied": has_reply,
        "latest_reply_id": str((latest_inbound_after_anchor or {}).get("id") or ""),
        "latest_reply_message": str((latest_inbound_after_anchor or {}).get("text") or ""),
        "latest_reply_sender": str((latest_inbound_after_anchor or {}).get("sender_name") or target_conv.get("participant_name") or norm_phone),
        "latest_reply_timestamp": str((latest_inbound_after_anchor or {}).get("created_iso") or "")
    }


