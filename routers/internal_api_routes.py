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
# --- GLENNBOT INTERNAL REST API (v1) & N8N AUTOMATION HUB ---
# =========================================================================
INTERNAL_API_CLOUDINARY_PUBLIC_ID = "glennbot_state/internal_api_v1.json"
INTERNAL_API_LOCK = threading.Lock()
INTERNAL_API_STATE: Dict[str, Any] = {
    "keys": [],
    "n8n_webhook_url": os.getenv("N8N_OUTBOUND_WEBHOOK_URL", "").strip(),
    "n8n_webhook_secret": os.getenv("N8N_OUTBOUND_WEBHOOK_SECRET", "gb_whsec_n8n_automation_2026").strip(),
    "n8n_events": {
        "email.received": True,
        "message.received": True,
        "comment.received": True,
        "sms.received": True,
        "sms.sent": True,
        "calendar.scheduled": True,
        "calendar.rescheduled": True,
        "calendar.cancelled": True,
        "contact.saved": True,
        "post.scheduled": True
    },
    "n8n_workflows": [],
    "deleted_workflow_ids": [],
    "recent_logs": [],
    "loaded_from_cloud": False,
    "table_initialized": False
}


def _default_n8n_events_dict(default_val: bool = False) -> Dict[str, bool]:
    return {
        "email.received": bool(default_val),
        "message.received": bool(default_val),
        "comment.received": bool(default_val),
        "sms.received": bool(default_val),
        "sms.sent": bool(default_val),
        "calendar.scheduled": bool(default_val),
        "calendar.rescheduled": bool(default_val),
        "calendar.cancelled": bool(default_val),
        "contact.saved": bool(default_val),
        "post.scheduled": bool(default_val)
    }


def _get_active_internal_api_key_token() -> str:
    with INTERNAL_API_LOCK:
        keys = list(INTERNAL_API_STATE.get("keys") or [])
    for k in keys:
        if isinstance(k, dict) and str(k.get("status") or "ACTIVE").upper() == "ACTIVE" and k.get("api_key"):
            return str(k["api_key"]).strip()
    env_internal_key = os.getenv("GLENNBOT_INTERNAL_API_KEY", "").strip()
    return env_internal_key or f"gb_live_{hashlib.sha256(b'glennbot_n8n_master_v1').hexdigest()[:36]}"


def _guess_n8n_base_url() -> str:
    """
    Infers the user's n8n base URL (e.g. 'http://localhost:5678' or 'https://...app.n8n.cloud')
    from any existing saved workflow, global n8n_webhook_url, or .env, defaulting to 'http://localhost:5678'.
    """
    candidates = [
        str(os.getenv("N8N_BASE_URL") or "").strip(),
        str(os.getenv("N8N_OUTBOUND_WEBHOOK_URL") or "").strip(),
        str(INTERNAL_API_STATE.get("n8n_webhook_url") or "").strip()
    ]
    for wf in (INTERNAL_API_STATE.get("n8n_workflows") or []):
        if isinstance(wf, dict) and wf.get("webhook_url"):
            candidates.append(str(wf.get("webhook_url")).strip())
    for c in candidates:
        if not c or not c.startswith("http"):
            continue
        m = re.match(r"^(https?://[^/]+)", c, re.IGNORECASE)
        if m:
            return m.group(1).rstrip("/")
    return "http://localhost:5678"


def _normalize_glennbot_node_url(raw_url: str, clean_base: str) -> str:
    """
    Replaces any old/placeholder base URL before `/api/v1/` with `clean_base`
    WITHOUT stripping leading `=` / `={{` expressions, and auto-heals broken JS string-concatenated URLs.
    """
    u = str(raw_url or "").strip()
    if not u or "/api/v1/" not in u:
        return u

    suffix = u.split("/api/v1/", 1)[1].lstrip("/")
    # Heal broken or JS-concatenated `/sms/thread-status` URLs into clean n8n template expressions
    if suffix.startswith("sms/thread-status") and ("' +" in suffix or "+ '" in suffix or suffix.endswith("}}")):
        return (
            f"={clean_base}/sms/thread-status?phone={{{{ encodeURIComponent($('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.sender_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || '') }}}}"
            f"&conversation_id={{{{ $('Webhook').item.json.body.conversation_id || '' }}}}"
            f"&message_id={{{{ $('Webhook').item.json.body.message_id || '' }}}}"
            f"&force=true"
        )
    if suffix.startswith("comments/thread-status") and ("' +" in suffix or "+ '" in suffix or (suffix.endswith("}}") and not u.startswith("="))):
        return (
            f"={clean_base}/comments/thread-status?record_id={{{{ $('Webhook').item.json.body.record_id || $json.body.record_id || '' }}}}"
            f"&comment_id={{{{ $('Webhook').item.json.body.comment_id || $json.body.comment_id || '' }}}}"
            f"&force=true"
        )

    # If the URL uses n8n `={{ '...' + ... }}` syntax
    if u.startswith("={{") and ("' +" in suffix or "+ '" in suffix):
        return f"={{ '{clean_base}/{suffix}"

    # Preserve leading `=` if the URL contains `{{ ... }}` expressions
    has_expr = "{{" in suffix and "}}" in suffix
    prefix = "=" if (u.startswith("=") or has_expr) else ""
    return f"{prefix}{clean_base}/{suffix}"


def _auto_heal_n8n_if_node(node: Dict[str, Any]) -> None:
    """
    Ensures every `n8n-nodes-base.if` node uses 100% valid n8n schema so IF nodes never fail
    due to v1/v2 schema mixups (e.g., `typeVersion: 1` with `conditions.conditions` or string `operator: 'equals'`).
    """
    params = node.get("parameters")
    if not isinstance(params, dict):
        return
    conds = params.get("conditions")
    if not isinstance(conds, dict):
        return

    v2_list = conds.get("conditions")
    if isinstance(v2_list, list) and v2_list:
        bool_items = list(conds.get("boolean") or []) if isinstance(conds.get("boolean"), list) else []
        str_items = list(conds.get("string") or []) if isinstance(conds.get("string"), list) else []
        num_items = list(conds.get("number") or []) if isinstance(conds.get("number"), list) else []

        for c in v2_list:
            if not isinstance(c, dict):
                continue
            left_v = c.get("leftValue") if c.get("leftValue") is not None else c.get("value1", "")
            right_v = c.get("rightValue") if "rightValue" in c else c.get("value2", "")
            op_raw = c.get("operator") if "operator" in c else c.get("operation", "equal")
            if isinstance(op_raw, dict):
                op_str = str(op_raw.get("operation") or "equal").strip()
            else:
                op_str = str(op_raw or "equal").strip()

            left_str = str(left_v or "")
            is_bool_check = (
                isinstance(right_v, bool)
                or str(right_v).strip().lower() in ("true", "false")
                or any(bk in left_str.lower() for bk in ("has_reply_to_sms", "has_reply_to_comment", "is_own", "replied"))
            )
            if is_bool_check:
                target_bool = True if (right_v is True or str(right_v).strip().lower() == "true") else False
                if left_str.startswith("={{") and left_str.endswith("}}") and "Boolean(" not in left_str:
                    inner_expr = left_str[3:-2].strip()
                    left_str = f"={{{{ Boolean({inner_expr}) }}}}"
                bool_items.append({
                    "value1": left_str,
                    "value2": target_bool
                })
            elif isinstance(right_v, (int, float)) and not isinstance(right_v, bool):
                num_items.append({
                    "value1": left_str,
                    "operation": "equal" if op_str in ("equals", "equal") else op_str,
                    "value2": right_v
                })
            else:
                v1_op = "equal" if op_str in ("equals", "equal") else ("notEqual" if op_str in ("notEquals", "notEqual") else op_str)
                if v1_op not in ("contains", "notContains", "equal", "notEqual", "startsWith", "endsWith", "regex", "isEmpty", "isNotEmpty"):
                    v1_op = "contains"
                str_items.append({
                    "value1": left_str,
                    "operation": v1_op,
                    "value2": str(right_v if right_v is not None else "")
                })

        new_conds: Dict[str, Any] = {}
        if bool_items:
            new_conds["boolean"] = bool_items
        if str_items:
            new_conds["string"] = str_items
        if num_items:
            new_conds["number"] = num_items

        if new_conds:
            comb = str(conds.get("combinator") or params.get("combineOperation") or "and").lower()
            node["typeVersion"] = 1
            params["conditions"] = new_conds
            if comb in ("or", "any"):
                params["combineOperation"] = "any"
            conds = new_conds

    #Also normalize v1 string operation 'equals' -> 'equal'
    if isinstance(conds.get("string"), list):
        for s_item in conds["string"]:
            if isinstance(s_item, dict) and s_item.get("operation") == "equals":
                s_item["operation"] = "equal"
    if isinstance(conds.get("boolean"), list):
        for b_item in conds["boolean"]:
            if isinstance(b_item, dict):
                v1_b = str(b_item.get("value1") or "")
                if v1_b.startswith("={{") and v1_b.endswith("}}") and "Boolean(" not in v1_b:
                    inner_b = v1_b[3:-2].strip()
                    b_item["value1"] = f"={{{{ Boolean({inner_b}) }}}}"
        node["typeVersion"] = 1
def _auto_inject_credentials_into_workflow_json(
    wf_json: Any,
    base_api_url: str = ""
) -> Dict[str, Any]:
    """
    Automatically edits/patches any uploaded or saved n8n Workflow JSON so that every HTTP Request node
    targeting GlennBot has:
    1. The exact live GlennBot API endpoint URL (`{dynamic_base_url}/api/v1/...`), even if
       the uploaded JSON had a blank URL, localhost, an old Render URL, or an old Ngrok tunnel!
    2. The active `X-API-Key` header (`gb_live_...`) automatically attached!
    3. Auto-healed IF combinators ("or" for multi-platform checks), v1/v2 IF condition schemas, and sub-thread `reply_target_comment_id`
       expressions on follow-up comment reply nodes after `GET /comments/thread-status`.
    """
    if isinstance(wf_json, str):
        try:
            wf_json = json.loads(wf_json)
        except Exception:
            wf_json = {}
    if not isinstance(wf_json, dict):
        return {}

    patched = json.loads(json.dumps(wf_json))
    active_key = _get_active_internal_api_key_token()
    default_live_api = f"{get_dynamic_base_url(prefer_public=True)}/api/v1"
    clean_base = str(base_api_url or default_live_api).rstrip("/")

    nodes = patched.get("nodes")
    if not isinstance(nodes, list):
        return patched

    # Identify nodes that are downstream of a `GET /comments/thread-status` or `n8n-nodes-base.wait` node
    connections = patched.get("connections") if isinstance(patched.get("connections"), dict) else {}
    wait_or_thread_node_names: set = set()
    for n_item in nodes:
        if not isinstance(n_item, dict):
            continue
        nt_low = str(n_item.get("type") or "").lower()
        nn_str = str(n_item.get("name") or "")
        np_url = str((n_item.get("parameters") or {}).get("url") or "").lower()
        if "wait" in nt_low or "thread-status" in np_url or "thread_status" in np_url:
            if nn_str:
                wait_or_thread_node_names.add(nn_str)

    downstream_of_wait_names: set = set()
    if wait_or_thread_node_names and connections:
        frontier = list(wait_or_thread_node_names)
        visited = set(frontier)
        while frontier:
            curr = frontier.pop(0)
            c_entry = connections.get(curr)
            if not isinstance(c_entry, dict):
                continue
            for branch_list in c_entry.values():
                if not isinstance(branch_list, list):
                    continue
                for out_group in branch_list:
                    if not isinstance(out_group, list):
                        continue
                    for target_link in out_group:
                        if isinstance(target_link, dict) and target_link.get("node"):
                            tn = str(target_link["node"])
                            downstream_of_wait_names.add(tn)
                            if tn not in visited:
                                visited.add(tn)
                                frontier.append(tn)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        n_type = str(node.get("type") or "").lower()
        n_name = str(node.get("name") or "").lower()
        orig_name = str(node.get("name") or "")
        params = node.get("parameters")
        if not isinstance(params, dict):
            params = {}
            node["parameters"] = params

        # Auto-heal IF nodes (both v1/v2 schema compatibility and multi-platform combinators)
        if n_type.endswith(".if") or ".if" in n_type:
            _auto_heal_n8n_if_node(node)
            conds = params.get("conditions")
            if isinstance(conds, dict):
                v1_str_list = conds.get("string")
                if isinstance(v1_str_list, list) and len(v1_str_list) >= 2:
                    left_vals_v1 = [str(c.get("value1") or "").strip().lower() for c in v1_str_list if isinstance(c, dict)]
                    right_vals_v1 = [str(c.get("value2") or "").strip().lower() for c in v1_str_list if isinstance(c, dict)]
                    if (
                        len(set(left_vals_v1)) == 1
                        and len(set(right_vals_v1)) > 1
                        and any(k in left_vals_v1[0] for k in ("platform", "event", "sender_email", "account_email", "account_name"))
                    ):
                        params["combineOperation"] = "any"

        if "httprequest" not in n_type:
            continue

        raw_url = str(params.get("url") or "").strip()
        j_body_raw = str(params.get("jsonBody") or params.get("body") or "")
        if j_body_raw and "($'" in j_body_raw:
            j_body_raw = re.sub(r"\(\$'([^']+)'\)", r"$('\1')", j_body_raw)
            if "jsonBody" in params:
                params["jsonBody"] = j_body_raw
            elif "body" in params:
                params["body"] = j_body_raw
        j_body = j_body_raw.lower()

        is_ai_ask_node = (
            "/api/ai/ask" in raw_url.lower()
            or "/api/v1/ai/ask" in raw_url.lower()
            or (
                any(k in n_name for k in ("gemini", "ask ai", "ai answer", "ai reply", "generate ai"))
                and "comment_id" not in j_body
                and "from_email" not in j_body
                and "conversation_id" not in j_body
            )
            or ("\"topic\"" in j_body and "comment_id" not in j_body)
        )

        # 1. Auto-detect or normalize the GlennBot API URL on this HTTP Request node
        if is_ai_ask_node:
            params["url"] = f"{clean_base}/ai/ask"
        elif "/api/v1/" in raw_url:
            params["url"] = _normalize_glennbot_node_url(raw_url, clean_base)
        elif not raw_url or any(p in raw_url.lower() for p in ("your_url", "paste_", "localhost", "127.0.0.1", "example.com", "glennbot")):
            if ("thread-status" in n_name or "thread_status" in n_name) and "sms" in n_name:
                params["url"] = (
                    f"={clean_base}/sms/thread-status?phone={{{{ encodeURIComponent($('Webhook').item.json.body.recipient_phone || $('Webhook').item.json.body.sender_phone || $('Webhook').item.json.body.phone || $('Webhook').item.json.body.participant_id || '') }}}}"
                    f"&conversation_id={{{{ $('Webhook').item.json.body.conversation_id || '' }}}}"
                    f"&message_id={{{{ $('Webhook').item.json.body.message_id || '' }}}}"
                    f"&force=true"
                )
            elif "thread-status" in n_name or "thread_status" in n_name:
                params["url"] = f"{clean_base}/comments/thread-status"
            elif "like" in n_name and "comment" in n_name:
                params["url"] = f"{clean_base}/comments/like"
            elif "hide" in n_name and "comment" in n_name:
                params["url"] = f"{clean_base}/comments/hide"
            elif any(k in j_body or k in n_name for k in ("spreadsheet", "workbook_id", "append-row", "append_row", "sheet_name")):
                params["url"] = f"{clean_base}/spreadsheets/append-row"
            elif any(k in j_body or k in n_name for k in ("from_email", "sender_email", "email", "gmail")):
                params["url"] = f"{clean_base}/emails/send"
            elif any(k in j_body or k in n_name for k in ("send-dm", "send_dm", "private dm")):
                params["url"] = f"{clean_base}/comments/send-dm"
            elif any(k in j_body or k in n_name for k in ("comment_id", "comment")):
                params["url"] = f"{clean_base}/comments/reply"
            elif any(k in j_body or k in n_name for k in ("recipient_phone", "sim_subscription_id", "textbee", "send sms", "sms")):
                params["url"] = f"{clean_base}/sms/send"
            elif any(k in j_body or k in n_name for k in ("conversation_id", "participant_id", "message", "chat")):
                params["url"] = f"{clean_base}/messages/send"
            elif any(k in j_body or k in n_name for k in ("contact", "crm")):
                params["url"] = f"{clean_base}/contacts"
            elif any(k in j_body or k in n_name for k in ("reschedule", "new_date", "new_start_time", "reschedule_reason")):
                params["url"] = f"{clean_base}/calendar/reschedule"
            elif any(k in j_body or k in n_name for k in ("cancel_appointment", "cancel_meeting", "cancellation_reason")) or ("cancel" in n_name and ("calendar" in n_name or "appointment" in n_name or "meeting" in n_name)):
                params["url"] = f"{clean_base}/calendar/cancel"
            elif any(k in j_body or k in n_name for k in ("meeting_platform", "google_meet", "microsoft_teams", "zoom", "attendees", "appointment", "calendar")):
                params["url"] = f"{clean_base}/calendar/schedule"
            elif any(k in j_body or k in n_name for k in ("post", "schedule")):
                params["url"] = f"{clean_base}/posts/publish"

        # 2. If this HTTP Request node points to our GlennBot API, auto-inject method, X-API-Key header, and sub-thread comment_id
        final_url = str(params.get("url") or "")
        if "/api/v1/" in final_url:
            if any(ep in final_url for ep in ("/comments/thread-status", "/sms/thread-status", "/api/v1/status", "/api/v1/accounts", "/api/v1/files", "/api/v1/analytics", "/api/v1/presets", "/api/v1/calendar/events")):
                params["method"] = "GET"
            elif not params.get("method"):
                params["method"] = "POST"

            # If this is a follow-up `/comments/reply` node running after a Wait / `thread-status` check,
            # ensure its `comment_id` expression prefers `$json.reply_target_comment_id || $json.subthread_comment_id || $json.latest_reply_id`
            if "/comments/reply" in final_url and orig_name in downstream_of_wait_names and j_body_raw:
                if "reply_target_comment_id" not in j_body_raw and "comment_id" in j_body_raw:
                    upgraded_body = re.sub(
                        r'("comment_id"\s*:\s*)(\$json\.latest_reply_id\s*\|\|\s*)?(\$\([\'"][^\'"]+[\'"]\)\.item\.json\.body\.comment_id)',
                        r'\1($json.reply_target_comment_id || $json.subthread_comment_id || $json.latest_reply_id || \3)',
                        j_body_raw
                    )
                    if upgraded_body != j_body_raw:
                        params["jsonBody"] = upgraded_body

            params["sendHeaders"] = True
            header_params = params.get("headerParameters")
            if not isinstance(header_params, dict):
                header_params = {"parameters": []}
                params["headerParameters"] = header_params
            h_list = header_params.get("parameters")
            if not isinstance(h_list, list):
                h_list = []
                header_params["parameters"] = h_list

            found_key_header = False
            for h_item in h_list:
                if isinstance(h_item, dict) and str(h_item.get("name") or "").lower() in ("x-api-key", "x-glennbot-api-key"):
                    h_item["name"] = "X-API-Key"
                    h_item["value"] = active_key
                    found_key_header = True
            if not found_key_header:
                h_list.append({
                    "name": "X-API-Key",
                    "value": active_key
                })

    return patched


def _analyze_n8n_workflow_json(wf_json: Any) -> Dict[str, Any]:
    """
    Inspects an uploaded n8n Workflow JSON object and auto-detects:
    - Workflow Name (`name`)
    - Webhook Path (`webhook_path`) from any `n8n-nodes-base.webhook` node
    - Which GlennBot `events` to forward to n8n (`email.received`, `comment.received`, `message.received`, `contact.saved`, `post.scheduled`)
    - Any IF-node or HTTP-Request filter conditions (`detected_conditions`) so test payloads can be generated dynamically without hardcoding!
    """
    if isinstance(wf_json, str):
        try:
            wf_json = json.loads(wf_json)
        except Exception:
            wf_json = {}
    if not isinstance(wf_json, dict):
        wf_json = {}

    wf_name = str(wf_json.get("name") or "").strip()
    nodes = wf_json.get("nodes") if isinstance(wf_json.get("nodes"), list) else []

    webhook_path = ""
    detected_events = _default_n8n_events_dict(False)
    explicit_trigger_events = _default_n8n_events_dict(False)
    detected_conditions: List[Dict[str, str]] = []
    target_endpoints: List[str] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        n_type = str(node.get("type") or "").lower()
        n_name = str(node.get("name") or "")
        params = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}

        # 1. Detect Webhook Node path & explicit trigger hints from webhook path
        if "webhook" in n_type:
            p_val = str(params.get("path") or node.get("webhookId") or "").strip().strip("/")
            if p_val and not webhook_path:
                webhook_path = p_val
            p_low = p_val.lower()
            if "cancel" in p_low and any(w in p_low for w in ("cal", "meet", "appoint", "zoom", "team")):
                explicit_trigger_events["calendar.cancelled"] = True
            if "resched" in p_low:
                explicit_trigger_events["calendar.rescheduled"] = True
            if any(w in p_low for w in ("calendar", "appointment", "meeting")) and "cancel" not in p_low and "resched" not in p_low:
                explicit_trigger_events["calendar.scheduled"] = True
            if "comment" in p_low:
                explicit_trigger_events["comment.received"] = True
            if any(w in p_low for w in ("sms-sent", "sms_sent", "outbound-sms")):
                explicit_trigger_events["sms.sent"] = True
            if "sms" in p_low and not explicit_trigger_events["sms.sent"]:
                explicit_trigger_events["sms.received"] = True
            if any(w in p_low for w in ("email", "gmail")) and "calendar" not in p_low and "appoint" not in p_low:
                explicit_trigger_events["email.received"] = True
            if any(w in p_low for w in ("message", "dm", "inbox")):
                explicit_trigger_events["message.received"] = True
            if any(w in p_low for w in ("contact", "crm")):
                explicit_trigger_events["contact.saved"] = True
            if "post" in p_low and "comment" not in p_low:
                explicit_trigger_events["post.scheduled"] = True

        # 2. Detect IF node conditions (v1 & v2)
        if n_type.endswith(".if") or "if" in n_name.lower():
            conds = params.get("conditions")
            if isinstance(conds, dict):
                # n8n IF v1 & v2: conditions.string / conditions.boolean / conditions.number / conditions.conditions
                for _, c_list in conds.items():
                    if isinstance(c_list, list):
                        for c_item in c_list:
                            if isinstance(c_item, dict):
                                v1 = str(c_item.get("value1") or c_item.get("leftValue") or "").strip()
                                op_raw = c_item.get("operation")
                                if not op_raw and isinstance(c_item.get("operator"), dict):
                                    op_raw = c_item["operator"].get("operation")
                                op = str(op_raw or "contains").strip()
                                v2 = str(c_item.get("value2") or c_item.get("rightValue") or "").strip()
                                v1_low = v1.lower()
                                v2_low = v2.lower()
                                if ".event" in v1_low or v1_low.endswith("event"):
                                    for ev_key in explicit_trigger_events.keys():
                                        if ev_key in v2_low:
                                            explicit_trigger_events[ev_key] = True
                                if v1 or v2:
                                    field_hint = "text"
                                    for candidate_f in ("account_name", "platform", "is_own_comment", "is_reply_to_comment", "has_reply_to_comment", "has_reply_to_sms", "subject", "account_email", "sender_email", "author_name", "participant_name", "recipient_phone", "sender_phone", "message", "body"):
                                        if candidate_f in v1_low:
                                            field_hint = candidate_f
                                            break
                                    # Don't treat post-wait thread-status check or `.event` check as an initial keyword condition
                                    if field_hint not in ("has_reply_to_comment", "has_reply_to_sms") and ".event" not in v1_low:
                                        detected_conditions.append({
                                            "field": field_hint,
                                            "expression": v1,
                                            "operation": op,
                                            "value": v2
                                        })

        # 3. Detect HTTP Request node target endpoints & inline filter keys
        if "httprequest" in n_type:
            u_val = str(params.get("url") or "").strip()
            if u_val:
                target_endpoints.append(u_val)
            j_body = str(params.get("jsonBody") or params.get("body") or "")
            if j_body:
                try:
                    # Extract static filter hints like "only_if_subject_contains", "only_if_body_contains", or "from_email"
                    m_subj = re.search(r'"only_if_subject_contains"\s*:\s*"([^"]+)"', j_body)
                    if m_subj and m_subj.group(1):
                        detected_conditions.append({
                            "field": "subject",
                            "expression": "only_if_subject_contains",
                            "operation": "contains",
                            "value": m_subj.group(1)
                        })
                    m_body_kw = re.search(r'"only_if_(?:body|message)_contains"\s*:\s*"([^"]+)"', j_body)
                    if m_body_kw and m_body_kw.group(1):
                        detected_conditions.append({
                            "field": "body",
                            "expression": "only_if_body_contains",
                            "operation": "contains",
                            "value": m_body_kw.group(1)
                        })
                    m_from = re.search(r'"from_email"\s*:\s*"([^"@]+@[^"]+)"', j_body)
                    if m_from and m_from.group(1):
                        detected_conditions.append({
                            "field": "account_email",
                            "expression": "from_email",
                            "operation": "equals",
                            "value": m_from.group(1)
                        })
                except Exception:
                    pass

    # 4. Auto-detect Events to Forward to n8n by prioritizing explicit trigger event signatures over downstream action endpoints
    raw_dump_low = json.dumps(wf_json, ensure_ascii=False).lower()

    for ev_key in explicit_trigger_events.keys():
        if f'"{ev_key}"' in raw_dump_low or f"'{ev_key}'" in raw_dump_low:
            explicit_trigger_events[ev_key] = True

    if not any(explicit_trigger_events.values()):
        if any(f"body.{k}" in raw_dump_low for k in ("cancellation_reason", "meeting_url_status")):
            explicit_trigger_events["calendar.cancelled"] = True
        if any(f"body.{k}" in raw_dump_low for k in ("reschedule_reason", "restructured_message_body", "previous_date_str", "previous_display_date", "old_display_date")):
            explicit_trigger_events["calendar.rescheduled"] = True
        if any(f"body.{k}" in raw_dump_low for k in ("meeting_platform", "primary_guest_email", "start_iso", "date_str")) and not explicit_trigger_events["calendar.cancelled"] and not explicit_trigger_events["calendar.rescheduled"]:
            explicit_trigger_events["calendar.scheduled"] = True
        if any(f"body.{k}" in raw_dump_low for k in ("comment_id", "is_own_comment", "is_reply_to_comment")):
            explicit_trigger_events["comment.received"] = True
        if any(f"body.{k}" in raw_dump_low for k in ("recipient_phone", "sim_subscription_id")) or "/sms/thread-status" in raw_dump_low:
            explicit_trigger_events["sms.sent"] = True
        if "body.sender_phone" in raw_dump_low:
            explicit_trigger_events["sms.received"] = True
        if any(f"body.{k}" in raw_dump_low for k in ("thread_id", "account_email", "sender_email")):
            explicit_trigger_events["email.received"] = True
        if any(f"body.{k}" in raw_dump_low for k in ("conversation_id", "participant_id")) and not explicit_trigger_events["sms.sent"] and not explicit_trigger_events["sms.received"]:
            explicit_trigger_events["message.received"] = True
        if "body.contact" in raw_dump_low:
            explicit_trigger_events["contact.saved"] = True
        if "body.queued_posts" in raw_dump_low:
            explicit_trigger_events["post.scheduled"] = True

    if any(explicit_trigger_events.values()):
        detected_events.update(explicit_trigger_events)
    else:
        if any(k in raw_dump_low for k in ("calendar.cancelled", "/calendar/cancel", "cancellation_reason", "appointment_cancelled")):
            detected_events["calendar.cancelled"] = True
        if any(k in raw_dump_low for k in ("calendar.rescheduled", "/calendar/reschedule", "old_display_date", "reschedule_reason", "appointment_rescheduled")):
            detected_events["calendar.rescheduled"] = True
        if any(k in raw_dump_low for k in ("calendar.scheduled", "/calendar/schedule", "appointment_booked", "meeting_scheduled")) and not detected_events["calendar.cancelled"] and not detected_events["calendar.rescheduled"]:
            detected_events["calendar.scheduled"] = True
        if any(k in raw_dump_low for k in ("/api/v1/calendar", "google_meet", "microsoft_teams", "zoom")) and not any(detected_events[k] for k in ("calendar.scheduled", "calendar.rescheduled", "calendar.cancelled")):
            detected_events["calendar.scheduled"] = True
        if any(k in raw_dump_low for k in ("/comments/reply", "/comments/like", "/comments/hide", "/comments/thread-status", "/api/v1/comments", "comment_id", "is_own_comment", "comment.received", "glennbot-comment", "comment-autodm")):
            detected_events["comment.received"] = True
        if any(k in raw_dump_low for k in ("sms.sent", "/sms/thread-status", "recipient_phone")):
            detected_events["sms.sent"] = True
        if any(k in raw_dump_low for k in ("sms.received", "sender_phone", "inbound_sms")):
            detected_events["sms.received"] = True
        if any(k in raw_dump_low for k in ("/sms/send", "/api/v1/sms", "textbee")) and not detected_events["sms.received"] and not detected_events["sms.sent"]:
            detected_events["sms.received"] = True
        if any(k in raw_dump_low for k in ("/messages/send", "/api/v1/messages", "conversation_id", "participant_id", "message.received", "glennbot-message")):
            detected_events["message.received"] = True
        if any(k in raw_dump_low for k in ("/emails/send", "/api/v1/emails", "sender_email", "account_email", "thread_id", "email.received", "glennbot-email", "gmail")) and not any(detected_events[k] for k in ("calendar.scheduled", "calendar.rescheduled", "calendar.cancelled")):
            detected_events["email.received"] = True
        if any(k in raw_dump_low for k in ("/contacts", "contact.saved", "glennbot-contact")) and not any(detected_events.values()):
            detected_events["contact.saved"] = True
        if any(k in raw_dump_low for k in ("/posts/schedule", "/posts/publish", "/api/v1/posts", "queued_posts", "post.scheduled", "glennbot-post")) and not any(detected_events.values()):
            detected_events["post.scheduled"] = True

    # Fallback if no specific event signature was matched
    if not any(detected_events.values()):
        name_low = wf_name.lower()
        if "resched" in name_low:
            detected_events["calendar.rescheduled"] = True
        elif "cancel" in name_low and ("cal" in name_low or "meet" in name_low or "appoint" in name_low):
            detected_events["calendar.cancelled"] = True
        elif "cal" in name_low or "meet" in name_low or "appoint" in name_low or "zoom" in name_low or "teams" in name_low:
            detected_events["calendar.scheduled"] = True
        elif "email" in name_low or "gmail" in name_low or "inquiry" in name_low:
            detected_events["email.received"] = True
        elif "sms" in name_low or "textbee" in name_low:
            detected_events["sms.received"] = True
        elif "message" in name_low or "chat" in name_low or "whatsapp" in name_low or "telegram" in name_low:
            detected_events["message.received"] = True
        elif "contact" in name_low or "crm" in name_low:
            detected_events["contact.saved"] = True
        elif "post" in name_low or "schedule" in name_low:
            detected_events["post.scheduled"] = True
        else:
            detected_events["comment.received"] = True

    # Deduplicate detected_conditions
    unique_conds: List[Dict[str, str]] = []
    seen_c = set()
    for c in detected_conditions:
        ck = f"{c.get('field')}:{c.get('value')}".lower()
        if ck not in seen_c and c.get("value"):
            seen_c.add(ck)
            unique_conds.append(c)

    primary_event = next((k for k, v in detected_events.items() if v), "comment.received")
    return {
        "name": wf_name,
        "webhook_path": webhook_path,
        "events": detected_events,
        "primary_event": primary_event,
        "detected_conditions": unique_conds,
        "target_endpoints": target_endpoints,
        "node_count": len(nodes)
    }


def _ensure_internal_api_table():
    if INTERNAL_API_STATE.get("table_initialized"):
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_internal_api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    scopes TEXT DEFAULT 'all',
                    status TEXT DEFAULT 'ACTIVE',
                    requests_count INTEGER DEFAULT 0,
                    last_used_at TEXT DEFAULT '',
                    created_at TEXT DEFAULT ''
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_n8n_workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    webhook_url TEXT DEFAULT '',
                    webhook_path TEXT DEFAULT '',
                    webhook_secret TEXT DEFAULT '',
                    events_json TEXT DEFAULT '{}',
                    detected_conditions_json TEXT DEFAULT '[]',
                    workflow_json TEXT DEFAULT '{}',
                    updated_at TEXT DEFAULT ''
                );
            """))
        INTERNAL_API_STATE["table_initialized"] = True
    except Exception as e:
        print(f"[InternalAPI] Table init warning: {e}")


def _save_internal_api_to_cloudinary():
    try:
        with INTERNAL_API_LOCK:
            payload = {
                "keys": list(INTERNAL_API_STATE.get("keys") or []),
                "n8n_webhook_url": INTERNAL_API_STATE.get("n8n_webhook_url") or "",
                "n8n_webhook_secret": INTERNAL_API_STATE.get("n8n_webhook_secret") or "",
                "n8n_events": dict(INTERNAL_API_STATE.get("n8n_events") or {}),
                "n8n_workflows": list(INTERNAL_API_STATE.get("n8n_workflows") or []),
                "deleted_workflow_ids": list(INTERNAL_API_STATE.get("deleted_workflow_ids") or []),
                "updated_at": datetime.now(MANILA_TZ).isoformat()
            }
        raw_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        cloudinary.uploader.upload(
            io.BytesIO(raw_bytes),
            resource_type="raw",
            public_id=INTERNAL_API_CLOUDINARY_PUBLIC_ID,
            overwrite=True,
            invalidate=True
        )
    except Exception as e:
        print(f"[InternalAPI] Cloudinary backup warning: {e}")


def _upsert_n8n_workflow_in_db(wf_obj: Dict[str, Any], sync_cloud: bool = True) -> Dict[str, Any]:
    _ensure_internal_api_table()
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    wf_json_raw = wf_obj.get("workflow_json")
    if isinstance(wf_json_raw, str):
        try:
            wf_json_obj = json.loads(wf_json_raw)
        except Exception:
            wf_json_obj = {}
    elif isinstance(wf_json_raw, dict):
        wf_json_obj = wf_json_raw
    else:
        wf_json_obj = {}

    if wf_json_obj:
        wf_json_obj = _auto_inject_credentials_into_workflow_json(wf_json_obj)

    analysis = _analyze_n8n_workflow_json(wf_json_obj) if wf_json_obj else {
        "name": "Custom n8n Workflow",
        "webhook_path": "",
        "events": _default_n8n_events_dict(False),
        "detected_conditions": []
    }

    events_in = wf_obj.get("events")
    merged_events = _default_n8n_events_dict(False)
    if isinstance(events_in, dict) and any(events_in.values()):
        for k in merged_events.keys():
            merged_events[k] = bool(events_in.get(k, False))
    else:
        merged_events.update(analysis["events"])

    custom_name = str(wf_obj.get("name") or analysis.get("name") or "Custom n8n Workflow").strip()
    if isinstance(wf_json_obj, dict) and wf_json_obj:
        wf_json_obj["name"] = custom_name

    resolved_wh_path = str(wf_obj.get("webhook_path") or analysis.get("webhook_path") or "").strip().strip("/")
    resolved_wh_url = str(wf_obj.get("webhook_url") or "").strip()
    if not resolved_wh_url and resolved_wh_path:
        resolved_wh_url = f"{_guess_n8n_base_url()}/webhook/{resolved_wh_path}"

    clean_wf = {
        "id": str(wf_obj.get("id") or f"wf_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}").strip(),
        "name": custom_name,
        "enabled": bool(wf_obj.get("enabled", True)),
        "webhook_url": resolved_wh_url,
        "webhook_path": resolved_wh_path,
        "webhook_secret": str(wf_obj.get("webhook_secret") or "").strip(),
        "events": merged_events,
        "detected_conditions": analysis.get("detected_conditions", []) if wf_json_obj else (wf_obj.get("detected_conditions") if isinstance(wf_obj.get("detected_conditions"), list) else []),
        "workflow_json": wf_json_obj,
        "updated_at": str(wf_obj.get("updated_at") or now_str)
    }

    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO glennbot_n8n_workflows
                (id, name, enabled, webhook_url, webhook_path, webhook_secret, events_json, detected_conditions_json, workflow_json, updated_at)
                VALUES (:id, :name, :enabled, :webhook_url, :webhook_path, :webhook_secret, :events_json, :detected_conditions_json, :workflow_json, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    enabled = EXCLUDED.enabled,
                    webhook_url = EXCLUDED.webhook_url,
                    webhook_path = EXCLUDED.webhook_path,
                    webhook_secret = EXCLUDED.webhook_secret,
                    events_json = EXCLUDED.events_json,
                    detected_conditions_json = EXCLUDED.detected_conditions_json,
                    workflow_json = EXCLUDED.workflow_json,
                    updated_at = EXCLUDED.updated_at
            """), {
                "id": clean_wf["id"],
                "name": clean_wf["name"],
                "enabled": clean_wf["enabled"],
                "webhook_url": clean_wf["webhook_url"],
                "webhook_path": clean_wf["webhook_path"],
                "webhook_secret": clean_wf["webhook_secret"],
                "events_json": json.dumps(clean_wf["events"], ensure_ascii=False),
                "detected_conditions_json": json.dumps(clean_wf["detected_conditions"], ensure_ascii=False),
                "workflow_json": json.dumps(clean_wf["workflow_json"], ensure_ascii=False),
                "updated_at": clean_wf["updated_at"]
            })
    except Exception as e:
        print(f"[InternalAPI] Workflow DB upsert warning: {e}")

    with INTERNAL_API_LOCK:
        deleted_ids = set(INTERNAL_API_STATE.get("deleted_workflow_ids") or [])
        if clean_wf["id"] in deleted_ids:
            deleted_ids.discard(clean_wf["id"])
            INTERNAL_API_STATE["deleted_workflow_ids"] = list(deleted_ids)
        existing_wfs = list(INTERNAL_API_STATE.get("n8n_workflows") or [])
        replaced = False
        for idx, item in enumerate(existing_wfs):
            if str(item.get("id")) == clean_wf["id"]:
                existing_wfs[idx] = clean_wf
                replaced = True
                break
        if not replaced:
            existing_wfs.append(clean_wf)
        INTERNAL_API_STATE["n8n_workflows"] = existing_wfs
        if clean_wf["webhook_url"] and not INTERNAL_API_STATE.get("n8n_webhook_url"):
            INTERNAL_API_STATE["n8n_webhook_url"] = clean_wf["webhook_url"]

    if sync_cloud:
        threading.Thread(target=_save_internal_api_to_cloudinary, daemon=True).start()
    return clean_wf


def _upsert_internal_api_key_in_db(key_obj: Dict[str, Any], sync_cloud: bool = True) -> Dict[str, Any]:
    _ensure_internal_api_table()
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    params = {
        "id": str(key_obj.get("id") or f"ikey_{int(time.time() * 1000)}"),
        "name": str(key_obj.get("name") or "n8n Automation Key").strip(),
        "api_key": str(key_obj.get("api_key") or "").strip(),
        "scopes": str(key_obj.get("scopes") or "all").strip(),
        "status": str(key_obj.get("status") or "ACTIVE").strip(),
        "requests_count": int(key_obj.get("requests_count") or 0),
        "last_used_at": str(key_obj.get("last_used_at") or "Never"),
        "created_at": str(key_obj.get("created_at") or now_str)
    }
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO glennbot_internal_api_keys
                (id, name, api_key, scopes, status, requests_count, last_used_at, created_at)
                VALUES (:id, :name, :api_key, :scopes, :status, :requests_count, :last_used_at, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    api_key = EXCLUDED.api_key,
                    scopes = EXCLUDED.scopes,
                    status = EXCLUDED.status,
                    requests_count = EXCLUDED.requests_count,
                    last_used_at = EXCLUDED.last_used_at
            """), params)
    except Exception as e:
        print(f"[InternalAPI] DB upsert warning: {e}")

    with INTERNAL_API_LOCK:
        existing = [k for k in INTERNAL_API_STATE["keys"] if str(k.get("id")) != params["id"]]
        existing.insert(0, params)
        INTERNAL_API_STATE["keys"] = existing

    if sync_cloud:
        threading.Thread(target=_save_internal_api_to_cloudinary, daemon=True).start()
    return params


def _load_internal_api_state(force_cloud: bool = False) -> Dict[str, Any]:
    _ensure_internal_api_table()
    with INTERNAL_API_LOCK:
        if INTERNAL_API_STATE["loaded_from_cloud"] and not force_cloud:
            return INTERNAL_API_STATE

    db_keys: List[Dict[str, Any]] = []
    db_workflows: List[Dict[str, Any]] = []
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, name, api_key, scopes, status, requests_count, last_used_at, created_at
                FROM glennbot_internal_api_keys
                ORDER BY created_at DESC
            """)).mappings().all()
            for r in rows:
                db_keys.append({
                    "id": str(r.get("id") or ""),
                    "name": str(r.get("name") or "n8n Automation Key"),
                    "api_key": str(r.get("api_key") or ""),
                    "scopes": str(r.get("scopes") or "all"),
                    "status": str(r.get("status") or "ACTIVE"),
                    "requests_count": int(r.get("requests_count") or 0),
                    "last_used_at": str(r.get("last_used_at") or "Never"),
                    "created_at": str(r.get("created_at") or "")
                })
            wf_rows = conn.execute(text("""
                SELECT id, name, enabled, webhook_url, webhook_path, webhook_secret, events_json, detected_conditions_json, workflow_json, updated_at
                FROM glennbot_n8n_workflows
                ORDER BY updated_at ASC
            """)).mappings().all()
            for wr in wf_rows:
                try:
                    ev_obj = json.loads(wr.get("events_json") or "{}")
                except Exception:
                    ev_obj = {}
                try:
                    dc_obj = json.loads(wr.get("detected_conditions_json") or "[]")
                except Exception:
                    dc_obj = []
                try:
                    wj_obj = json.loads(wr.get("workflow_json") or "{}")
                except Exception:
                    wj_obj = {}
                db_workflows.append({
                    "id": str(wr.get("id") or ""),
                    "name": str(wr.get("name") or "n8n Workflow"),
                    "enabled": bool(wr.get("enabled", True)),
                    "webhook_url": str(wr.get("webhook_url") or ""),
                    "webhook_path": str(wr.get("webhook_path") or ""),
                    "webhook_secret": str(wr.get("webhook_secret") or ""),
                    "events": ev_obj if isinstance(ev_obj, dict) else _default_n8n_events_dict(False),
                    "detected_conditions": dc_obj if isinstance(dc_obj, list) else [],
                    "workflow_json": wj_obj if isinstance(wj_obj, dict) else {},
                    "updated_at": str(wr.get("updated_at") or "")
                })
    except Exception as e:
        print(f"[InternalAPI] DB read warning: {e}")

    cloud_keys: List[Dict[str, Any]] = []
    cloud_workflows: List[Dict[str, Any]] = []
    cloud_deleted_wf_ids: List[str] = []
    try:
        res_info = cloudinary.api.resource(INTERNAL_API_CLOUDINARY_PUBLIC_ID, resource_type="raw")
        sec_url = res_info.get("secure_url")
        if sec_url:
            r = HTTP_SESSION.get(f"{sec_url}?_t={int(time.time())}", timeout=10)
            if r.status_code == 200:
                c_data = r.json()
                if isinstance(c_data, dict):
                    if isinstance(c_data.get("keys"), list):
                        cloud_keys = c_data["keys"]
                    if isinstance(c_data.get("n8n_workflows"), list):
                        cloud_workflows = c_data["n8n_workflows"]
                    if isinstance(c_data.get("deleted_workflow_ids"), list):
                        cloud_deleted_wf_ids = [str(x).strip() for x in c_data["deleted_workflow_ids"] if str(x).strip()]
                    if c_data.get("n8n_webhook_url") is not None and not INTERNAL_API_STATE.get("n8n_webhook_url"):
                        INTERNAL_API_STATE["n8n_webhook_url"] = str(c_data.get("n8n_webhook_url") or "").strip()
                    if c_data.get("n8n_webhook_secret"):
                        INTERNAL_API_STATE["n8n_webhook_secret"] = str(c_data.get("n8n_webhook_secret")).strip()
                    if isinstance(c_data.get("n8n_events"), dict):
                        INTERNAL_API_STATE["n8n_events"].update(c_data["n8n_events"])
    except Exception:
        pass

    merged_map: Dict[str, Dict[str, Any]] = {}
    for k_item in cloud_keys + db_keys:
        if not isinstance(k_item, dict):
            continue
        kid = str(k_item.get("id") or "").strip()
        kval = str(k_item.get("api_key") or "").strip()
        if kid and kval:
            merged_map[kid] = k_item

    # If no key exists yet, auto-seed a default ready-to-use Internal API Key for n8n
    if not merged_map:
        env_internal_key = os.getenv("GLENNBOT_INTERNAL_API_KEY", "").strip()
        default_token = env_internal_key or f"gb_live_{hashlib.sha256(b'glennbot_n8n_master_v1').hexdigest()[:36]}"
        seed_key = {
            "id": "ikey_master_n8n",
            "name": "n8n Master Automation Key",
            "api_key": default_token,
            "scopes": "all",
            "status": "ACTIVE",
            "requests_count": 0,
            "last_used_at": "Ready for n8n",
            "created_at": datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
        }
        merged_map[seed_key["id"]] = seed_key

    final_keys = list(merged_map.values())

    # Always exclude legacy starter workflow IDs and any user-deleted workflow IDs
    legacy_starter_ids = {"wf_starter_comment_autodm", "wf_starter_gmail_inquiry"}
    deleted_set = set(INTERNAL_API_STATE.get("deleted_workflow_ids") or []) | set(cloud_deleted_wf_ids) | legacy_starter_ids

    # Clean up any legacy starter workflows or deleted workflows from DB
    try:
        with db_engine.begin() as conn:
            for d_id in deleted_set:
                conn.execute(text("DELETE FROM glennbot_n8n_workflows WHERE id = :id"), {"id": d_id})
    except Exception:
        pass

    merged_wf_map: Dict[str, Dict[str, Any]] = {}
    for wf_item in cloud_workflows + db_workflows:
        if not isinstance(wf_item, dict):
            continue
        wid = str(wf_item.get("id") or "").strip()
        if wid and wid not in deleted_set:
            merged_wf_map[wid] = wf_item

    final_workflows = list(merged_wf_map.values())

    with INTERNAL_API_LOCK:
        INTERNAL_API_STATE["keys"] = final_keys
        INTERNAL_API_STATE["n8n_workflows"] = final_workflows
        INTERNAL_API_STATE["deleted_workflow_ids"] = list(deleted_set)
        INTERNAL_API_STATE["loaded_from_cloud"] = True

    for k_item in final_keys:
        _upsert_internal_api_key_in_db(k_item, sync_cloud=False)
    for wf_item in final_workflows:
        _upsert_n8n_workflow_in_db(wf_item, sync_cloud=False)

    return INTERNAL_API_STATE


def _verify_internal_api_key(request: Request) -> Optional[Dict[str, Any]]:
    """
    Authenticates incoming n8n / external REST requests to /api/v1/*.
    Supports:
    - Header: `X-API-Key: gb_live_...`
    - Header: `Authorization: Bearer gb_live_...`
    - Query parameter: `?api_key=gb_live_...`
    """
    _load_internal_api_state(force_cloud=False)
    h_low = {str(k).lower(): str(v).strip() for k, v in request.headers.items()}
    candidate = h_low.get("x-api-key") or h_low.get("x-glennbot-api-key") or ""
    if not candidate:
        auth_h = h_low.get("authorization") or ""
        if auth_h.lower().startswith("bearer "):
            candidate = auth_h[7:].strip()
        elif auth_h:
            candidate = auth_h.strip()
    if not candidate:
        candidate = str(request.query_params.get("api_key") or "").strip()

    if not candidate:
        return None

    matched_key = None
    with INTERNAL_API_LOCK:
        for k_obj in INTERNAL_API_STATE.get("keys") or []:
            if str(k_obj.get("status") or "ACTIVE").upper() == "ACTIVE" and str(k_obj.get("api_key") or "").strip() == candidate:
                matched_key = k_obj
                break

    if not matched_key:
        env_key = os.getenv("GLENNBOT_INTERNAL_API_KEY", "").strip()
        if env_key and candidate == env_key:
            matched_key = {
                "id": "ikey_env",
                "name": ".env Master Key",
                "api_key": env_key,
                "scopes": "all",
                "status": "ACTIVE",
                "requests_count": 0
            }

    if matched_key:
        now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
        matched_key["last_used_at"] = now_str
        matched_key["requests_count"] = int(matched_key.get("requests_count") or 0) + 1
        with INTERNAL_API_LOCK:
            logs = list(INTERNAL_API_STATE.get("recent_logs") or [])
            logs.insert(0, {
                "timestamp": now_str,
                "method": request.method,
                "endpoint": str(request.url.path),
                "key_name": matched_key.get("name") or "API Key",
                "status": "200 OK"
            })
            INTERNAL_API_STATE["recent_logs"] = logs[:30]
        if matched_key.get("id") != "ikey_env":
            threading.Thread(target=_upsert_internal_api_key_in_db, args=(dict(matched_key), False), daemon=True).start()

    return matched_key


def _dispatch_outbound_n8n_webhook_sync(
    event_type: str,
    data: Dict[str, Any],
    target_workflow_id: Optional[str] = None,
    override_url: Optional[str] = None,
    override_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Dispatches an outbound event (`email.received`, `comment.received`, `message.received`, `contact.saved`, `post.scheduled`)
    simultaneously to ALL active n8n workflow automations that have subscribed to `event_type` (or to a specific `target_workflow_id` during testing).
    """
    _load_internal_api_state(force_cloud=False)
    global_secret = str(INTERNAL_API_STATE.get("n8n_webhook_secret") or "gb_whsec_n8n_automation_2026").strip()
    workflows = list(INTERNAL_API_STATE.get("n8n_workflows") or [])

    targets_to_fire: List[Dict[str, str]] = []
    seen_urls: set = set()

    if target_workflow_id:
        matched_wf = next((w for w in workflows if str(w.get("id")) == str(target_workflow_id)), None)
        u_val = str(override_url or (matched_wf or {}).get("webhook_url") or "").strip()
        s_val = str(override_secret or (matched_wf or {}).get("webhook_secret") or global_secret).strip() or global_secret
        w_name = str((matched_wf or {}).get("name") or "n8n Workflow Test").strip()
        if u_val and u_val.startswith("http"):
            targets_to_fire.append({"name": w_name, "url": u_val, "secret": s_val, "id": str(target_workflow_id)})
    elif override_url and override_url.startswith("http"):
        targets_to_fire.append({
            "name": "Custom Webhook Test",
            "url": override_url.strip(),
            "secret": str(override_secret or global_secret).strip() or global_secret,
            "id": "custom"
        })
    else:
        # Normal live event fan-out: fire ALL enabled workflows that have `event_type` enabled and a valid URL
        n8n_base_guess = _guess_n8n_base_url()
        for wf in workflows:
            if not isinstance(wf, dict) or not wf.get("enabled", True):
                continue
            wf_path = str(wf.get("webhook_path") or "").strip().strip("/")
            wf_url = str(wf.get("webhook_url") or "").strip()
            if (not wf_url or not wf_url.startswith("http")) and wf_path:
                wf_url = f"{n8n_base_guess}/webhook/{wf_path}"
            if not wf_url or not wf_url.startswith("http"):
                continue
            wf_evts = wf.get("events") if isinstance(wf.get("events"), dict) else {}
            is_sms_evt = event_type in ("sms.sent", "sms.received")
            is_cal_evt = event_type in ("calendar.scheduled", "calendar.rescheduled", "calendar.cancelled")
            wf_raw_low = (
                f"{wf.get('name', '')} {wf_path} {wf_url} {json.dumps(wf.get('workflow_json') or {}, ensure_ascii=False)}"
            ).lower()
            has_sms_signature = is_sms_evt and any(
                k in wf_raw_low for k in ("sms.sent", "sms.received", "/sms/send", "/sms/thread-status", "textbee", "recipient_phone", "sender_phone")
            )
            has_cal_signature = is_cal_evt and any(
                k in wf_raw_low for k in ("calendar.scheduled", "calendar.rescheduled", "calendar.cancelled", "/calendar/", "appointment", "reschedule", "meeting_platform", "start_iso")
            )
            if (
                event_type == "n8n.test"
                or wf_evts.get(event_type, False)
                or (is_sms_evt and wf_evts.get("message.received", False))
                or has_sms_signature
                or has_cal_signature
            ):
                if wf_url not in seen_urls:
                    seen_urls.add(wf_url)
                    targets_to_fire.append({
                        "id": str(wf.get("id") or ""),
                        "name": str(wf.get("name") or "n8n Workflow"),
                        "url": wf_url,
                        "path": wf_path,
                        "secret": str(wf.get("webhook_secret") or global_secret).strip() or global_secret
                    })

        # Also check if the user recently generated a workflow in Ask AI and copied it directly to n8n without saving the card yet
        last_ai_wf = INTERNAL_API_STATE.get("last_ai_generated_workflow")
        if isinstance(last_ai_wf, dict) and last_ai_wf.get("webhook_path"):
            ai_path = str(last_ai_wf.get("webhook_path") or "").strip().strip("/")
            ai_url = f"{n8n_base_guess}/webhook/{ai_path}"
            ai_evts = last_ai_wf.get("events") if isinstance(last_ai_wf.get("events"), dict) else {}
            is_sms_evt = event_type in ("sms.sent", "sms.received")
            if ai_url not in seen_urls and (
                ai_evts.get(event_type, False)
                or (is_sms_evt and ai_evts.get("message.received", False))
                or (is_sms_evt and "sms" in ai_path.lower())
            ):
                seen_urls.add(ai_url)
                targets_to_fire.append({
                    "id": "ask_ai_recent",
                    "name": str(last_ai_wf.get("name") or "Ask AI Workflow"),
                    "url": ai_url,
                    "path": ai_path,
                    "secret": global_secret
                })

        # Legacy fallback: if global `n8n_webhook_url` is set and not already covered by `n8n_workflows`
        legacy_url = str(INTERNAL_API_STATE.get("n8n_webhook_url") or "").strip()
        legacy_evts = INTERNAL_API_STATE.get("n8n_events") or {}
        if legacy_url and legacy_url.startswith("http") and legacy_url not in seen_urls:
            is_sms_evt = event_type in ("sms.sent", "sms.received")
            if (
                event_type == "n8n.test"
                or legacy_evts.get(event_type, False)
                or (is_sms_evt and legacy_evts.get("message.received", True))
                or (not is_sms_evt and legacy_evts.get(event_type, True))
            ):
                targets_to_fire.append({
                    "id": "legacy_default",
                    "name": "Default Outbound Webhook",
                    "url": legacy_url,
                    "path": "",
                    "secret": global_secret
                })

    if not targets_to_fire:
        return {
            "dispatched": False,
            "reason": f"no_active_workflow_url_for_{event_type}",
            "results": []
        }

    now_dt = datetime.now(MANILA_TZ)
    now_str = now_dt.strftime("%Y-%m-%d %I:%M:%S %p")
    exec_event_id = f"gb_evt_{int(now_dt.timestamp() * 1000)}_{uuid.uuid4().hex[:8]}"
    payload: Dict[str, Any] = {
        "event": event_type,
        "execution_event_id": exec_event_id,
        "dispatched_at_epoch_ms": int(now_dt.timestamp() * 1000),
        "source": "glennbot_internal_api_v1",
        "timestamp_manila": now_str,
        "timestamp_iso": now_dt.isoformat(),
        "data": data
    }
    # Copy top-level convenience keys so n8n expressions work with either $json.body.comment_id or $json.body.data.comment_id
    if isinstance(data, dict):
        for k_flat, v_flat in data.items():
            if k_flat not in payload:
                payload[k_flat] = v_flat

    raw_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _fire_single_n8n_target(target: Dict[str, str]) -> Dict[str, Any]:
        t_url = target["url"]
        t_path = str(target.get("path") or "").strip().strip("/")
        t_sec = target["secret"] or global_secret
        t_name = target["name"]
        sig_hex = hmac.new(t_sec.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "GlennBot-n8n-Dispatcher/3.0-Concurrent",
            "X-GlennBot-Event": event_type,
            "X-GlennBot-Event-Id": exec_event_id,
            "X-GlennBot-Workflow": t_name,
            "X-GlennBot-Signature": sig_hex
        }
        # Build candidate URLs smartly:
        # In production (`event_type != "n8n.test"`), always prioritize the active `/webhook/` URL first
        # and retry it with fast exponential backoff on transient 429/502/503/504 or connection bursts
        # so simultaneous comments never fall through to an inactive `/webhook-test/` 404 endpoint!
        candidate_urls = [t_url]
        if "/webhook-test/" in t_url:
            prod_u = t_url.replace("/webhook-test/", "/webhook/")
            if event_type != "n8n.test":
                candidate_urls = [prod_u, t_url]
            else:
                candidate_urls.append(prod_u)
        elif "/webhook/" in t_url:
            candidate_urls.append(t_url.replace("/webhook/", "/webhook-test/"))

        if t_path and (_is_localhost_origin(t_url) or event_type == "n8n.test"):
            for local_u in (f"http://localhost:5678/webhook/{t_path}", f"http://localhost:5678/webhook-test/{t_path}"):
                if local_u not in candidate_urls:
                    candidate_urls.append(local_u)

        resp = None
        last_exc = None
        retry_delays = (0.0, 0.35, 0.85)

        for idx_u, try_u in enumerate(candidate_urls):
            # Primary production URL gets up to 3 attempts on transient 429/5xx/network saturation
            max_attempts = 3 if idx_u == 0 else 1
            for attempt_idx in range(max_attempts):
                if attempt_idx > 0:
                    time.sleep(retry_delays[min(attempt_idx, len(retry_delays) - 1)])
                try:
                    r_try = N8N_HTTP_SESSION.post(try_u, data=raw_bytes, headers=headers, timeout=(4.5, 18.0))
                    resp = r_try
                    t_url = try_u
                    if 200 <= r_try.status_code < 300:
                        break
                    # If production URL returned 429 or 5xx under burst load, retry the same production URL!
                    if r_try.status_code in (429, 500, 502, 503, 504) and attempt_idx < max_attempts - 1:
                        continue
                    # Only fall back to secondary candidate URL (/webhook-test/) if primary returned 404
                    break
                except Exception as e_try:
                    last_exc = e_try
                    if attempt_idx < max_attempts - 1:
                        continue
            if resp is not None and (200 <= resp.status_code < 300 or resp.status_code not in (404, 502, 503, 504)):
                break

        if resp is not None:
            with INTERNAL_API_LOCK:
                logs = list(INTERNAL_API_STATE.get("recent_logs") or [])
                logs.insert(0, {
                    "timestamp": now_str,
                    "method": "WEBHOOK -> n8n",
                    "endpoint": f"{event_type} ({resp.status_code})",
                    "key_name": t_name,
                    "status": f"HTTP {resp.status_code}"
                })
                INTERNAL_API_STATE["recent_logs"] = logs[:40]
            return {
                "workflow_id": target.get("id"),
                "workflow_name": t_name,
                "webhook_url": t_url,
                "execution_event_id": exec_event_id,
                "dispatched": 200 <= resp.status_code < 300,
                "status_code": resp.status_code,
                "response_preview": (resp.text or "")[:300]
            }
        else:
            with INTERNAL_API_LOCK:
                logs = list(INTERNAL_API_STATE.get("recent_logs") or [])
                logs.insert(0, {
                    "timestamp": now_str,
                    "method": "WEBHOOK -> n8n",
                    "endpoint": f"{event_type} (ERR)",
                    "key_name": t_name,
                    "status": "ERROR"
                })
                INTERNAL_API_STATE["recent_logs"] = logs[:40]
            return {
                "workflow_id": target.get("id"),
                "workflow_name": t_name,
                "webhook_url": t_url,
                "execution_event_id": exec_event_id,
                "dispatched": False,
                "error": str(last_exc or "Connection failed")
            }

    if len(targets_to_fire) == 1:
        dispatch_results = [_fire_single_n8n_target(targets_to_fire[0])]
    else:
        futures = [N8N_WEBHOOK_EXECUTOR.submit(_fire_single_n8n_target, t) for t in targets_to_fire]
        dispatch_results = [f.result() for f in futures]

    any_ok = any(r.get("dispatched") for r in dispatch_results)
    first_res = dispatch_results[0] if dispatch_results else {}
    return {
        "dispatched": any_ok,
        "execution_event_id": exec_event_id,
        "status_code": first_res.get("status_code", 0),
        "response_preview": first_res.get("response_preview", ""),
        "webhook_url": first_res.get("webhook_url", ""),
        "error": first_res.get("error"),
        "results": dispatch_results,
        "payload_sent": payload
    }


def _dispatch_outbound_n8n_webhook_async(event_type: str, data: Dict[str, Any]):
    # Snapshot data dict so concurrent mutations never affect queued n8n webhook payloads
    data_snapshot = dict(data) if isinstance(data, dict) else data
    try:
        N8N_WEBHOOK_EXECUTOR.submit(_dispatch_outbound_n8n_webhook_sync, event_type, data_snapshot)
    except Exception:
        threading.Thread(
            target=_dispatch_outbound_n8n_webhook_sync,
            args=(event_type, data_snapshot),
            daemon=True
        ).start()
    # Also trigger any active workflows saved inside the In-Dashboard "Automations" Modal Canvas
    try:
        N8N_WEBHOOK_EXECUTOR.submit(_execute_active_dashboard_automations_for_event, event_type, dict(data_snapshot) if isinstance(data_snapshot, dict) else data_snapshot)
    except Exception:
        threading.Thread(
            target=_execute_active_dashboard_automations_for_event,
            args=(event_type, dict(data_snapshot) if isinstance(data_snapshot, dict) else data_snapshot),
            daemon=True
        ).start()


def _build_dynamic_test_payload_for_workflow(event_type: str, wf_obj: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Dynamically constructs a realistic test payload for ANY uploaded n8n Workflow JSON!
    Inspects the workflow's `detected_conditions` (from n8n IF nodes / HTTP Request nodes)
    and automatically injects the required trigger keywords/emails/fields so testing never requires hardcoded samples.
    """
    wf_dict = wf_obj if isinstance(wf_obj, dict) else {}
    wf_json = wf_dict.get("workflow_json") if isinstance(wf_dict.get("workflow_json"), dict) else {}
    analysis = _analyze_n8n_workflow_json(wf_json) if wf_json else {
        "detected_conditions": wf_dict.get("detected_conditions") or []
    }
    conds = analysis.get("detected_conditions") if isinstance(analysis.get("detected_conditions"), list) else []

    # Extract any condition values required by the uploaded workflow's IF nodes
    cond_map: Dict[str, str] = {}
    for c in conds:
        if isinstance(c, dict) and c.get("field") and c.get("value"):
            f_name = str(c["field"]).strip().lower()
            if f_name not in cond_map:
                cond_map[f_name] = str(c["value"]).strip()

    if event_type == "email.received":
        _load_email_hub_state(force_cloud=False)
        email_accs = EMAIL_HUB_STATE.get("accounts") or []
        req_acc_email = cond_map.get("account_email", "glennardtasico@gmail.com").lower()
        matched_acc = next(
            (a for a in email_accs if req_acc_email in str(a.get("email_address") or "").lower()),
            email_accs[0] if email_accs else None
        )
        acc_id_val = str((matched_acc or {}).get("id") or "email_gmail_glennard")
        acc_email_val = str((matched_acc or {}).get("email_address") or cond_map.get("account_email") or "glennardtasico@gmail.com")
        req_subject_kw = cond_map.get("subject") or cond_map.get("text") or "INQUIRY"
        req_body_kw = cond_map.get("body") or cond_map.get("message") or req_subject_kw
        return {
            "account_id": acc_id_val,
            "account_email": acc_email_val,
            "account_name": str((matched_acc or {}).get("display_name") or "Glennard Tasico"),
            "provider": str((matched_acc or {}).get("provider") or "gmail"),
            "message_id": f"test_email_{int(time.time())}",
            "thread_id": f"test_thread_{int(time.time())}",
            "subject": f"{req_subject_kw} - Automated Workflow Test",
            "sender": f"Test Lead <{cond_map.get('sender_email') or 'test.sender@example.com'}>",
            "sender_name": "Test Lead",
            "sender_email": cond_map.get("sender_email") or "test.sender@example.com",
            "snippet": f"Hi! Testing workflow with keyword: {req_body_kw}",
            "body": f"Hi,\n\nThis is an automated test email containing '{req_body_kw}' for your uploaded n8n workflow.",
            "simulated_test": True
        }

    if event_type in ("message.received", "sms.sent", "sms.received"):
        raw_wf_str = json.dumps(wf_json, ensure_ascii=False).lower() if wf_json else ""
        is_sms_wf = event_type in ("sms.sent", "sms.received") or any(
            k in raw_wf_str for k in ("/sms/send", "/sms/thread-status", "sms.sent", "sms.received", "recipient_phone", "sender_phone", "textbee")
        )
        req_msg_kw = cond_map.get("message") or cond_map.get("text") or "Hello! Testing SMS & Direct Message workflow."
        if is_sms_wf:
            is_outbound_sms = event_type == "sms.sent" or "sms.sent" in raw_wf_str or "recipient_phone" in raw_wf_str or "/sms/thread-status" in raw_wf_str
            test_phone = cond_map.get("recipient_phone") or cond_map.get("sender_phone") or "+639175497760"
            return {
                "event": "sms.sent" if is_outbound_sms else "sms.received",
                "platform": "sms",
                "direction": "outbound" if is_outbound_sms else "inbound",
                "is_own": is_outbound_sms,
                "account_id": TEXTBEE_ACCOUNT_ID,
                "account_name": "TextBee SMS (SIM 2)",
                "conversation_id": f"test_sms_{int(time.time())}",
                "recipient_phone": test_phone,
                "sender_phone": test_phone,
                "recipient": test_phone,
                "sender": test_phone,
                "phone": test_phone,
                "to": test_phone,
                "from": test_phone,
                "participant_id": test_phone,
                "recipient_name": cond_map.get("participant_name") or "Juan Dela Cruz",
                "sender_name": cond_map.get("participant_name") or "Juan Dela Cruz",
                "participant_name": cond_map.get("participant_name") or "Juan Dela Cruz",
                "message": req_msg_kw,
                "text": req_msg_kw,
                "message_id": f"test_sms_{int(time.time())}",
                "sim_subscription_id": "2",
                "simulated_test": True
            }
        return {
            "platform": cond_map.get("platform") or "facebook",
            "account_id": "test_social_account",
            "account_name": "GlennBot Official Page",
            "conversation_id": "test_conv_01",
            "participant_id": "test_user_01",
            "participant_name": cond_map.get("participant_name") or "Juan Dela Cruz",
            "message": {
                "id": f"test_dm_{int(time.time())}",
                "text": req_msg_kw,
                "sender_name": cond_map.get("participant_name") or "Juan Dela Cruz",
                "is_own": False
            },
            "text": req_msg_kw,
            "simulated_test": True
        }

    if event_type == "contact.saved":
        return {
            "contact": {
                "id": f"test_contact_{int(time.time())}",
                "name": "Maria Santos",
                "email": "maria.santos@example.com",
                "phone": "+639171234567",
                "platform": "facebook",
                "notes": cond_map.get("text") or "VIP Lead"
            },
            "simulated_test": True
        }

    if event_type in ("calendar.scheduled", "calendar.rescheduled", "calendar.cancelled"):
        now_m = datetime.now(MANILA_TZ)
        test_ev_id = f"test_calev_{int(time.time())}"
        next_day_str = (now_m + timedelta(days=1)).strftime("%Y-%m-%d")
        next_disp_str = (now_m + timedelta(days=1)).strftime("%b %d, %Y")
        prev_day_str = now_m.strftime("%Y-%m-%d") if event_type == "calendar.rescheduled" else ""
        prev_disp_str = now_m.strftime("%b %d, %Y") if event_type == "calendar.rescheduled" else ""
        prev_time_range = "10:00 AM - 11:00 AM" if event_type == "calendar.rescheduled" else ""
        org_em_val = cond_map.get("account_email") or "glennard.tasico.va@gmail.com"
        guest_em_val = cond_map.get("sender_email") or "client@example.com"
        desc_val = cond_map.get("body") or cond_map.get("message") or "Updated agenda and project timeline discussion."
        base_cal_payload = {
            "event": event_type,
            "action": event_type.split(".")[-1],
            "event_id": test_ev_id,
            "external_event_id": f"ext_{test_ev_id}",
            "account_id": "cal_acc_test_01",
            "provider": "google_calendar",
            "meeting_platform": "google_meet",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "meeting_url_status": "invalidated_cancelled" if event_type == "calendar.cancelled" else "active",
            "location": "https://meet.google.com/abc-defg-hij",
            "subject": cond_map.get("subject") or cond_map.get("text") or "Client Discovery & Strategy Call",
            "description": desc_val,
            "message_body": desc_val,
            "restructured_message_body": desc_val if event_type == "calendar.rescheduled" else "",
            "reschedule_reason": "Updated schedule per client request" if event_type == "calendar.rescheduled" else "",
            "cancellation_reason": (cond_map.get("body") or "") if event_type == "calendar.cancelled" else "",
            "date": next_day_str,
            "date_str": next_day_str,
            "display_date": next_disp_str,
            "start_time": "14:00",
            "time_str": "14:00",
            "end_time": "15:00",
            "time_range_str": "2:00 PM - 3:00 PM",
            "start_iso": f"{next_day_str}T14:00:00+08:00",
            "end_iso": f"{next_day_str}T15:00:00+08:00",
            "duration_minutes": 60,
            "timezone": "Asia/Manila",
            "organizer_email": org_em_val,
            "sender_email": org_em_val,
            "attendee_email": guest_em_val,
            "primary_guest_email": guest_em_val,
            "attendee_name": "Juan Dela Cruz",
            "attendee_emails": [guest_em_val],
            "attendees": [{"email": guest_em_val, "name": "Juan Dela Cruz", "status": "invited"}],
            "old_date": prev_day_str,
            "previous_date_str": prev_day_str,
            "old_display_date": prev_disp_str,
            "previous_display_date": prev_disp_str,
            "old_time_range_str": prev_time_range,
            "previous_time_range_str": prev_time_range,
            "previous_time_str": "10:00" if event_type == "calendar.rescheduled" else "",
            "status": event_type.split(".")[-1],
            "simulated_test": True
        }
        base_cal_payload["appointment"] = dict(base_cal_payload)
        return base_cal_payload

    if event_type == "post.scheduled":
        return {
            "queued_posts": [
                {
                    "id": f"test_post_{int(time.time())}",
                    "platform": cond_map.get("platform") or "facebook",
                    "caption": cond_map.get("text") or "Scheduled post via GlennBot Automation!",
                    "status": "Queued"
                }
            ],
            "simulated_test": True
        }

    # Default: comment.received (uses a real FB/IG comment from store if available, injecting any IF-condition keyword)
    req_comment_kw = cond_map.get("message") or cond_map.get("text") or "Nice one!"
    req_acc_name = cond_map.get("account_name") or "Savvy Finds"
    sample_data: Dict[str, Any] = {
        "platform": cond_map.get("platform") or "facebook",
        "record_id": "test_record_fb_01",
        "post_id": "test_post_fb_01",
        "comment_id": "test_comment_fb_offers_01",
        "account_id": "test_fb_page",
        "account_name": req_acc_name,
        "author_id": "fb_user_1001",
        "author_name": cond_map.get("author_name") or "Juan Dela Cruz",
        "message": req_comment_kw,
        "is_own_comment": False,
        "is_reply_to_comment": False,
        "parent_comment_id": "",
        "simulated_test": True
    }
    try:
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        for r_id, p_entry in posts_store.items():
            p_plat = str(p_entry.get("platform") or "").strip().lower()
            p_acc_name = str(p_entry.get("account_name") or p_plat.upper()).strip()
            if cond_map.get("account_name") and cond_map["account_name"].lower() not in p_acc_name.lower():
                continue
            if p_plat in ("facebook", "instagram"):
                c_map = p_entry.get("comments") or {}
                for c_id, c_item in c_map.items():
                    if not c_item.get("is_own_comment"):
                        msg_val = str(c_item.get("message") or req_comment_kw)
                        if cond_map.get("message") and cond_map["message"].lower() not in msg_val.lower():
                            msg_val = f"{msg_val} ({cond_map['message']})"
                        sample_data = {
                            "platform": p_plat,
                            "record_id": str(r_id),
                            "post_id": str(c_item.get("zernio_post_id") or c_item.get("external_post_id") or ""),
                            "comment_id": str(c_id),
                            "account_id": str(c_item.get("zernio_account_id") or p_entry.get("page_id") or ""),
                            "account_name": p_acc_name,
                            "author_id": str(c_item.get("author_id") or ""),
                            "author_name": str(c_item.get("author_name") or "Commenter"),
                            "message": msg_val,
                            "is_own_comment": False,
                            "is_reply_to_comment": False,
                            "parent_comment_id": "",
                            "comment": c_item,
                            "simulated_test": True
                        }
                        break
                if sample_data.get("record_id") != "test_record_fb_01":
                    break
    except Exception:
        pass
    return sample_data


N8N_DISPATCHED_COMMENT_IDS: set = set()
N8N_COMMENT_SEED_DONE: bool = False


def _seed_existing_comment_ids_for_n8n():
    global N8N_COMMENT_SEED_DONE
    with N8N_DISPATCH_LOCK:
        if N8N_COMMENT_SEED_DONE:
            return
        try:
            posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
            for _, p_entry in posts_store.items():
                for cid_k, c_val in (p_entry.get("comments") or {}).items():
                    N8N_DISPATCHED_COMMENT_IDS.add(str(cid_k))
                    if isinstance(c_val, dict):
                        for rep_item in (c_val.get("replies") or []):
                            if isinstance(rep_item, dict) and rep_item.get("id"):
                                N8N_DISPATCHED_COMMENT_IDS.add(str(rep_item["id"]))
            N8N_COMMENT_SEED_DONE = True
        except Exception:
            N8N_COMMENT_SEED_DONE = True


def _notify_n8n_new_comment(r_dict: Dict[str, Any], comment_obj: Dict[str, Any], is_background_sync: bool = False):
    global N8N_COMMENT_SEED_DONE
    cid = str(comment_obj.get("comment_id") or "").strip()
    parent_cid = str(comment_obj.get("parent_comment_id") or comment_obj.get("parent_id") or "").strip()
    is_rep_to_comm = bool(parent_cid or comment_obj.get("is_reply") or comment_obj.get("is_reply_to_comment"))
    is_own_comm = bool(comment_obj.get("is_own_comment") or comment_obj.get("is_own"))

    # Block ONLY top-level comments by the Page on its own post (is_own_comm=True and is_rep_to_comm=False).
    # Allow all user comments/replies AND Page replies to comments (is_own_comm=True and is_rep_to_comm=True)!
    if not cid or (is_own_comm and not is_rep_to_comm):
        return

    rec_id = str(comment_obj.get("record_id") or r_dict.get("id") or "").strip()
    msg_text = str(comment_obj.get("message") or "").strip()
    norm_parent_key = _normalize_comment_key(parent_cid) if parent_cid else ""
    own_reply_sig = f"own_rep::{rec_id}::{norm_parent_key}::{msg_text.lower()}" if is_own_comm else ""

    with N8N_DISPATCH_LOCK:
        if not N8N_COMMENT_SEED_DONE:
            _seed_existing_comment_ids_for_n8n()
        if cid in N8N_DISPATCHED_COMMENT_IDS:
            return
        if own_reply_sig and own_reply_sig in N8N_DISPATCHED_COMMENT_IDS:
            N8N_DISPATCHED_COMMENT_IDS.add(cid)
            return

        # If discovered via background sync, only trigger n8n if the comment is recent (within last 20 minutes)
        if is_background_sync:
            c_iso = str(comment_obj.get("created_iso") or "").strip()
            if c_iso:
                try:
                    dt_c = datetime.fromisoformat(c_iso.replace("Z", "+00:00"))
                    age_sec = (datetime.now(timezone.utc) - dt_c.astimezone(timezone.utc)).total_seconds()
                    if age_sec > 1200:
                        N8N_DISPATCHED_COMMENT_IDS.add(cid)
                        if own_reply_sig:
                            N8N_DISPATCHED_COMMENT_IDS.add(own_reply_sig)
                        return
                except Exception:
                    pass

        N8N_DISPATCHED_COMMENT_IDS.add(cid)
        if own_reply_sig:
            N8N_DISPATCHED_COMMENT_IDS.add(own_reply_sig)

    plat = str(comment_obj.get("platform") or r_dict.get("platform") or "").strip().lower()
    post_id = str(comment_obj.get("zernio_post_id") or comment_obj.get("external_post_id") or r_dict.get("external_post_id") or "").strip()
    acc_id = str(comment_obj.get("zernio_account_id") or comment_obj.get("page_id") or r_dict.get("page_id") or "").strip()
    acc_name = str(comment_obj.get("account_name") or r_dict.get("account_name") or plat.upper()).strip()
    parent_author_id = str(comment_obj.get("parent_author_id") or "").strip()
    parent_author_name = str(comment_obj.get("parent_author_name") or "").strip()
    author_id = str(comment_obj.get("author_id") or (parent_author_id if is_own_comm else "") or acc_id or "").strip()
    author_name = str(comment_obj.get("author_name") or (acc_name if is_own_comm else "Commenter")).strip()

    # Build thread_id and full chronological thread_transcript for single-row conversation grouping
    root_cid = parent_cid if parent_cid else cid
    norm_thread_id = _normalize_comment_key(root_cid) or root_cid
    parent_msg_text = str(comment_obj.get("parent_message") or "").strip()
    thread_lines: List[str] = []
    thread_member_ids: List[str] = []
    try:
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts")
        if isinstance(posts_store, dict) and rec_id in posts_store:
            raw_post_comments = posts_store[rec_id].get("comments") or {}
            flat_comments: List[Dict[str, Any]] = []
            if isinstance(raw_post_comments, dict):
                for top_cid, top_c in raw_post_comments.items():
                    if not isinstance(top_c, dict):
                        continue
                    top_copy = dict(top_c)
                    top_copy.setdefault("comment_id", str(top_cid))
                    flat_comments.append(top_copy)
                    for rep_c in (top_c.get("replies") or []):
                        if isinstance(rep_c, dict):
                            rep_copy = dict(rep_c)
                            rep_copy["comment_id"] = str(rep_c.get("comment_id") or rep_c.get("id") or "")
                            rep_copy["parent_comment_id"] = str(rep_c.get("parent_comment_id") or top_copy["comment_id"] or "")
                            rep_copy["is_own_comment"] = bool(rep_c.get("is_own_comment") or rep_c.get("is_own"))
                            flat_comments.append(rep_copy)
            elif isinstance(raw_post_comments, list):
                flat_comments = [c for c in raw_post_comments if isinstance(c, dict)]

            if flat_comments:
                by_norm_id: Dict[str, Dict[str, Any]] = {}
                for c_item in flat_comments:
                    ck = _normalize_comment_key(str(c_item.get("comment_id") or ""))
                    if ck:
                        by_norm_id[ck] = c_item
                curr_walk = norm_thread_id
                visited_walk = set()
                while curr_walk and curr_walk in by_norm_id and curr_walk not in visited_walk:
                    visited_walk.add(curr_walk)
                    p_walk = _normalize_comment_key(str(by_norm_id[curr_walk].get("parent_comment_id") or by_norm_id[curr_walk].get("parent_id") or ""))
                    if p_walk and p_walk != curr_walk:
                        curr_walk = p_walk
                    else:
                        break
                if curr_walk:
                    norm_thread_id = curr_walk
                    root_obj = by_norm_id.get(norm_thread_id)
                    if root_obj:
                        root_cid = str(root_obj.get("comment_id") or root_cid)
                        if not parent_msg_text and is_rep_to_comm:
                            parent_msg_text = str(root_obj.get("message") or "").strip()
                        if not parent_author_id and is_own_comm:
                            parent_author_id = str(root_obj.get("author_id") or "").strip()
                        if not parent_author_name and is_own_comm:
                            parent_author_name = str(root_obj.get("author_name") or "").strip()

                # Collect all comments belonging to this root thread
                thread_set = {norm_thread_id} if norm_thread_id else set()
                changed = True
                while changed:
                    changed = False
                    for c_item in flat_comments:
                        c_norm = _normalize_comment_key(str(c_item.get("comment_id") or ""))
                        p_norm = _normalize_comment_key(str(c_item.get("parent_comment_id") or c_item.get("parent_id") or c_item.get("replied_to_id") or ""))
                        if c_norm and p_norm and p_norm in thread_set and c_norm not in thread_set:
                            thread_set.add(c_norm)
                            changed = True

                matched_thread_objs = [
                    c_item for c_item in flat_comments
                    if _normalize_comment_key(str(c_item.get("comment_id") or "")) in thread_set
                ]
                matched_thread_objs.sort(key=lambda x: str(x.get("created_iso") or x.get("created_at") or ""))
                for t_item in matched_thread_objs:
                    t_cid_norm = _normalize_comment_key(str(t_item.get("comment_id") or ""))
                    if t_cid_norm and t_cid_norm not in thread_member_ids:
                        thread_member_ids.append(t_cid_norm)
                    t_own = bool(t_item.get("is_own_comment") or t_item.get("is_own"))
                    t_speaker = f"{acc_name} (Page)" if t_own else str(t_item.get("author_name") or "Commenter").strip()
                    t_msg = str(t_item.get("message") or "").strip()
                    if t_msg:
                        line_str = f"{t_speaker}: {t_msg}"
                        if not thread_lines or thread_lines[-1] != line_str:
                            thread_lines.append(line_str)
    except Exception:
        pass

    curr_speaker = f"{acc_name} (Page)" if is_own_comm else (author_name or "Commenter")
    curr_line = f"{curr_speaker}: {msg_text}" if msg_text else ""
    if curr_line and (not thread_lines or thread_lines[-1] != curr_line):
        thread_lines.append(curr_line)
    curr_norm_cid = _normalize_comment_key(cid)
    if curr_norm_cid and curr_norm_cid not in thread_member_ids:
        thread_member_ids.append(curr_norm_cid)
    if norm_thread_id and norm_thread_id not in thread_member_ids:
        thread_member_ids.insert(0, norm_thread_id)

    _dispatch_outbound_n8n_webhook_async("comment.received", {
        "platform": plat,
        "record_id": rec_id,
        "post_id": post_id,
        "comment_id": cid,
        "parent_comment_id": parent_cid,
        "root_comment_id": root_cid,
        "thread_id": norm_thread_id,
        "thread_comment_ids": thread_member_ids,
        "replied_to_id": str(comment_obj.get("replied_to_id") or parent_cid or ""),
        "is_reply_to_comment": is_rep_to_comm,
        "account_id": acc_id,
        "account_name": acc_name,
        "author_id": author_id,
        "author_name": author_name,
        "parent_author_id": parent_author_id,
        "parent_author_name": parent_author_name,
        "parent_message": parent_msg_text,
        "message": msg_text,
        "thread_transcript": "\n".join(thread_lines),
        "is_own_comment": is_own_comm,
        "comment": dict(comment_obj)
    })


N8N_DISPATCHED_MESSAGE_IDS: set = set()
N8N_MESSAGE_SEED_DONE: bool = False


def _seed_existing_message_ids_for_n8n():
    global N8N_MESSAGE_SEED_DONE
    with N8N_DISPATCH_LOCK:
        if N8N_MESSAGE_SEED_DONE:
            return
        try:
            convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
            for _, c_entry in convs_store.items():
                for m_obj in (c_entry.get("messages") or []):
                    mid = str(m_obj.get("id") or "").strip()
                    if mid:
                        N8N_DISPATCHED_MESSAGE_IDS.add(mid)
            N8N_MESSAGE_SEED_DONE = True
        except Exception:
            N8N_MESSAGE_SEED_DONE = True


def _notify_n8n_new_message(conv_obj: Dict[str, Any], msg_obj: Dict[str, Any], is_background_sync: bool = False):
    global N8N_MESSAGE_SEED_DONE
    mid = str(msg_obj.get("id") or "").strip()
    if not mid or msg_obj.get("is_own"):
        return

    with N8N_DISPATCH_LOCK:
        if not N8N_MESSAGE_SEED_DONE:
            _seed_existing_message_ids_for_n8n()
        if mid in N8N_DISPATCHED_MESSAGE_IDS:
            return

        if is_background_sync:
            m_iso = str(msg_obj.get("created_iso") or "").strip()
            if m_iso:
                try:
                    dt_m = datetime.fromisoformat(m_iso.replace("Z", "+00:00"))
                    age_sec = (datetime.now(timezone.utc) - dt_m.astimezone(timezone.utc)).total_seconds()
                    if age_sec > 1200:
                        N8N_DISPATCHED_MESSAGE_IDS.add(mid)
                        return
                except Exception:
                    pass

        N8N_DISPATCHED_MESSAGE_IDS.add(mid)

    plat = str(conv_obj.get("platform") or "").strip().lower()
    acc_id = str(conv_obj.get("account_id") or conv_obj.get("zernio_account_id") or "").strip()
    acc_name = str(conv_obj.get("account_name") or plat.upper()).strip()
    conv_id = str(conv_obj.get("conversation_id") or conv_obj.get("platform_conversation_id") or "").strip()
    part_id = str(conv_obj.get("participant_id") or msg_obj.get("sender_id") or "").strip()
    part_name = str(conv_obj.get("participant_name") or msg_obj.get("sender_name") or "User").strip()

    _dispatch_outbound_n8n_webhook_async("message.received", {
        "platform": plat,
        "account_id": acc_id,
        "account_name": acc_name,
        "conversation_id": conv_id,
        "participant_id": part_id,
        "participant_name": part_name,
        "message": dict(msg_obj)
    })


