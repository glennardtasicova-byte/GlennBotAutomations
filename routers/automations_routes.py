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
# --- IN-DASHBOARD "AUTOMATIONS" MODAL & NATIVE N8N JSON EXECUTION ENGINE ---
# Supports uploading/importing any n8n .json workflow (from "Ask AI" or n8n),
# editing generic nodes (Dashboard Trigger/Webhook, IF, Wait, Code, HTTP Request, Set),
# and executing the workflow graph natively inside GlennBot!
# ==============================================================================

AUTOMATIONS_CANVAS_LOCK = threading.Lock()
CLOUDINARY_AUTOMATIONS_CANVAS_PUBLIC_ID = "glennbot_config/automations_canvas_workflows_v1.json"
LOCAL_AUTOMATIONS_CANVAS_CACHE_PATH = os.path.join(BASE_DIR, "automations_canvas_workflows_cache.json")
AUTOMATIONS_CANVAS_STATE: Dict[str, Any] = {
    "loaded": False,
    "workflows": [],
    "execution_history": []
}


def _load_automations_canvas_state(force_cloud: bool = False) -> Dict[str, Any]:
    with AUTOMATIONS_CANVAS_LOCK:
        if AUTOMATIONS_CANVAS_STATE.get("loaded") and not force_cloud:
            return AUTOMATIONS_CANVAS_STATE

        wf_list: List[Dict[str, Any]] = []
        exec_hist: List[Dict[str, Any]] = []
        loaded_cloud = False

        if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
            try:
                res = cloudinary.api.resource(CLOUDINARY_AUTOMATIONS_CANVAS_PUBLIC_ID, resource_type="raw")
                sec_url = (res or {}).get("secure_url")
                if sec_url:
                    sep = "&" if "?" in sec_url else "?"
                    r = HTTP_SESSION.get(f"{sec_url}{sep}_ts={int(time.time())}", timeout=10)
                    if r.status_code == 200:
                        c_data = r.json() or {}
                        if isinstance(c_data.get("workflows"), list):
                            wf_list = c_data["workflows"]
                            loaded_cloud = True
                        if isinstance(c_data.get("execution_history"), list):
                            exec_hist = c_data["execution_history"][:40]
            except Exception:
                pass

        if not loaded_cloud and os.path.exists(LOCAL_AUTOMATIONS_CANVAS_CACHE_PATH):
            try:
                with open(LOCAL_AUTOMATIONS_CANVAS_CACHE_PATH, "r", encoding="utf-8") as f:
                    l_data = json.load(f) or {}
                    if isinstance(l_data.get("workflows"), list):
                        wf_list = l_data["workflows"]
                    if isinstance(l_data.get("execution_history"), list):
                        exec_hist = l_data["execution_history"][:40]
            except Exception:
                pass

        AUTOMATIONS_CANVAS_STATE["workflows"] = wf_list
        AUTOMATIONS_CANVAS_STATE["execution_history"] = exec_hist
        AUTOMATIONS_CANVAS_STATE["loaded"] = True
        return AUTOMATIONS_CANVAS_STATE


def _save_automations_canvas_state() -> bool:
    with AUTOMATIONS_CANVAS_LOCK:
        payload = {
            "version": 1,
            "updated_at": datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p"),
            "workflows": AUTOMATIONS_CANVAS_STATE.get("workflows") or [],
            "execution_history": (AUTOMATIONS_CANVAS_STATE.get("execution_history") or [])[:40]
        }
        raw_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        try:
            with open(LOCAL_AUTOMATIONS_CANVAS_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(raw_bytes.decode("utf-8"))
        except Exception:
            pass

    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        try:
            cloudinary.uploader.upload(
                io.BytesIO(raw_bytes),
                resource_type="raw",
                public_id=CLOUDINARY_AUTOMATIONS_CANVAS_PUBLIC_ID,
                overwrite=True,
                invalidate=True
            )
            return True
        except Exception as e:
            print(f"[AutomationsCanvas] Cloudinary save warning: {e}")
    return False


def _deep_get_path(obj: Any, path_str: str) -> Any:
    """Resolves dot/bracket notation paths like `body.account_name` or `data.comment_id` against a dict/list."""
    if obj is None:
        return None
    clean = str(path_str or "").strip()
    if not clean:
        return obj
    # Normalize bracket indexing like rows[0] -> rows.0
    clean = re.sub(r"\[(\d+)\]", r".\1", clean)
    clean = re.sub(r"\['([^']+)'\]", r".\1", clean)
    clean = re.sub(r'\["([^"]+)"\]', r".\1", clean)
    parts = [p for p in clean.split(".") if p != ""]
    curr = obj
    for p in parts:
        if isinstance(curr, dict):
            if p in curr:
                curr = curr[p]
            else:
                return None
        elif isinstance(curr, list) and p.isdigit():
            idx = int(p)
            if 0 <= idx < len(curr):
                curr = curr[idx]
            else:
                return None
        else:
            return None
    return curr


def _eval_single_n8n_js_token(token_expr: str, current_json: Dict[str, Any], node_outputs: Dict[str, Dict[str, Any]]) -> Any:
    """Evaluates a single n8n JS expression token (without `||` or `??`)."""
    t = str(token_expr or "").strip()
    if not t:
        return ""
    # Strip outer parentheses if balanced
    while t.startswith("(") and t.endswith(")"):
        depth = 0
        balanced = True
        for i, ch in enumerate(t):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i < len(t) - 1:
                    balanced = False
                    break
        if balanced:
            t = t[1:-1].strip()
        else:
            break

    if t in ("true", "True"):
        return True
    if t in ("false", "False"):
        return False
    if t in ("null", "undefined", "None"):
        return None
    if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
        return t[1:-1]
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)

    # Handle encodeURIComponent(...)
    m_enc = re.match(r"^encodeURIComponent\((.+)\)$", t, re.DOTALL)
    if m_enc:
        inner_val = _eval_n8n_js_expression(m_enc.group(1), current_json, node_outputs)
        return urllib.parse.quote(str(inner_val if inner_val is not None else ""))

    # Handle Boolean(...)
    m_bool = re.match(r"^Boolean\((.+)\)$", t, re.DOTALL)
    if m_bool:
        inner_b = m_bool.group(1).strip()
        # Special support for the Savvy Finds comment/reply filter:
        # Boolean(!($json.body.is_own_comment ?? $json.is_own_comment) || ($json.body.is_reply_to_comment ?? $json.is_reply_to_comment) || ($json.body.parent_comment_id ?? $json.parent_comment_id))
        if "is_own_comment" in inner_b and ("is_reply_to_comment" in inner_b or "parent_comment_id" in inner_b):
            is_own = bool(_deep_get_path(current_json, "body.is_own_comment") or _deep_get_path(current_json, "is_own_comment"))
            is_rep = bool(_deep_get_path(current_json, "body.is_reply_to_comment") or _deep_get_path(current_json, "is_reply_to_comment"))
            p_cid = str(_deep_get_path(current_json, "body.parent_comment_id") or _deep_get_path(current_json, "parent_comment_id") or "").strip()
            return bool((not is_own) or is_rep or bool(p_cid))
        val = _eval_n8n_js_expression(inner_b, current_json, node_outputs)
        if isinstance(val, str):
            return val.lower() not in ("", "false", "0", "null", "undefined", "none")
        return bool(val)

    # Negation !expr
    if t.startswith("!"):
        inner_v = _eval_n8n_js_expression(t[1:].strip(), current_json, node_outputs)
        return not bool(inner_v)

    # $('Node Name').item.json.xyz or $('Node Name').first().json.xyz
    m_node = re.match(r"^\$\(\s*['\"]([^'\"]+)['\"]\s*\)\.(?:item|first\(\))\.json\.?(.*)$", t)
    if m_node:
        ref_node_name = m_node.group(1).strip()
        ref_path = m_node.group(2).strip()
        target_data = node_outputs.get(ref_node_name)
        if target_data is None:
            # Fallback to any trigger node output if name differs slightly (e.g. 'Webhook' vs 'Webhook Trigger')
            for k_out, v_out in node_outputs.items():
                if "webhook" in k_out.lower() or "trigger" in k_out.lower():
                    target_data = v_out
                    break
        if target_data is None:
            target_data = current_json
        return _deep_get_path(target_data, ref_path)

    # $json.xyz or $input.first().json.xyz or $input.item.json.xyz
    m_json = re.match(r"^(?:\$json|\$input\.(?:first\(\)|item)\.json)\.?(.*)$", t)
    if m_json:
        return _deep_get_path(current_json, m_json.group(1).strip())

    return t


def _eval_n8n_js_expression(expr: str, current_json: Dict[str, Any], node_outputs: Dict[str, Dict[str, Any]]) -> Any:
    """
    Evaluates n8n JS expressions inside `{{ ... }}`, supporting fallback chains (`||`, `??`),
    ternary operators (`cond ? a : b`), `JSON.stringify({...})`, and string concatenation.
    """
    s = str(expr or "").strip()
    if not s:
        return ""

    # Handle JSON.stringify({ ... })
    m_strf = re.match(r"^JSON\.stringify\(\s*(\{.*\})\s*\)$", s, re.DOTALL)
    if m_strf:
        obj_literal = m_strf.group(1).strip()
        evaluated_dict = _eval_n8n_object_literal(obj_literal, current_json, node_outputs)
        return json.dumps(evaluated_dict, ensure_ascii=False)

    # Handle fallback chains with || or ?? at top level (ignoring inside quotes/parens)
    parts: List[str] = []
    depth = 0
    in_quote: Optional[str] = None
    curr_buf: List[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if in_quote:
            curr_buf.append(ch)
            if ch == in_quote and (i == 0 or s[i - 1] != "\\"):
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_quote = ch
            curr_buf.append(ch)
            i += 1
            continue
        if ch in ("(", "{", "["):
            depth += 1
            curr_buf.append(ch)
            i += 1
            continue
        if ch in (")", "}", "]"):
            depth = max(0, depth - 1)
            curr_buf.append(ch)
            i += 1
            continue
        if depth == 0 and s[i:i + 2] in ("||", "??"):
            parts.append("".join(curr_buf).strip())
            curr_buf = []
            i += 2
            continue
        curr_buf.append(ch)
        i += 1
    if curr_buf:
        parts.append("".join(curr_buf).strip())

    if len(parts) > 1:
        for candidate in parts:
            val = _eval_single_n8n_js_token(candidate, current_json, node_outputs)
            if val is not None and val != "":
                return val
        return ""

    return _eval_single_n8n_js_token(s, current_json, node_outputs)


def _eval_n8n_object_literal(obj_str: str, current_json: Dict[str, Any], node_outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Parses a JS object literal inside `JSON.stringify({ ... })` into a Python dict."""
    s = str(obj_str or "").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    result: Dict[str, Any] = {}
    # Split top-level key: value pairs by comma
    pairs: List[str] = []
    depth = 0
    in_quote: Optional[str] = None
    buf: List[str] = []
    for idx, ch in enumerate(s):
        if in_quote:
            buf.append(ch)
            if ch == in_quote and (idx == 0 or s[idx - 1] != "\\"):
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            buf.append(ch)
            continue
        if ch in ("(", "{", "["):
            depth += 1
            buf.append(ch)
            continue
        if ch in (")", "}", "]"):
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            pairs.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        pairs.append("".join(buf).strip())

    for pair in pairs:
        if ":" not in pair:
            continue
        # Split on first colon outside quotes
        colon_idx = -1
        in_q = None
        for idx, ch in enumerate(pair):
            if in_q:
                if ch == in_q and (idx == 0 or pair[idx - 1] != "\\"):
                    in_q = None
                continue
            if ch in ("'", '"'):
                in_q = ch
                continue
            if ch == ":":
                colon_idx = idx
                break
        if colon_idx < 0:
            continue
        raw_k = pair[:colon_idx].strip().strip('"').strip("'")
        raw_v = pair[colon_idx + 1:].strip()
        if raw_v.startswith("{") and raw_v.endswith("}"):
            result[raw_k] = _eval_n8n_object_literal(raw_v, current_json, node_outputs)
        else:
            result[raw_k] = _eval_n8n_js_expression(raw_v, current_json, node_outputs)
    return result


def _resolve_n8n_parameter_value(raw_val: Any, current_json: Dict[str, Any], node_outputs: Dict[str, Dict[str, Any]]) -> Any:
    """Resolves an n8n parameter string (which may start with `=` and contain `{{ ... }}` blocks)."""
    if isinstance(raw_val, dict):
        return {k: _resolve_n8n_parameter_value(v, current_json, node_outputs) for k, v in raw_val.items()}
    if isinstance(raw_val, list):
        return [_resolve_n8n_parameter_value(x, current_json, node_outputs) for x in raw_val]
    if not isinstance(raw_val, str):
        return raw_val

    s = raw_val
    is_expr_prefixed = s.startswith("=")
    if is_expr_prefixed:
        s = s[1:].strip()

    # Exact single {{ ... }} block
    m_single = re.match(r"^\{\{\s*(.*?)\s*\}\}$", s, re.DOTALL)
    if m_single:
        return _eval_n8n_js_expression(m_single.group(1), current_json, node_outputs)

    # Multiple {{ ... }} blocks interpolated inside a string (e.g. URL query params)
    if "{{" in s and "}}" in s:
        def _repl(match_obj):
            inner = match_obj.group(1).strip()
            val = _eval_n8n_js_expression(inner, current_json, node_outputs)
            if val is None:
                return ""
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val)
        return re.sub(r"\{\{\s*(.*?)\s*\}\}", _repl, s, flags=re.DOTALL)

    return s


def _evaluate_n8n_if_node(node: Dict[str, Any], current_json: Dict[str, Any], node_outputs: Dict[str, Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Evaluates an `n8n-nodes-base.if` or `n8n-nodes-base.filter` node (both v1 and v2 schemas).
    Returns (passed_boolean, condition_details).
    """
    params = node.get("parameters") or {}
    conds_root = params.get("conditions") or {}
    combine_op = str(params.get("combineOperation") or conds_root.get("combinator") or "all").strip().lower()
    use_any = combine_op in ("any", "or")

    results: List[bool] = []
    details: List[Dict[str, Any]] = []

    def _check_single(v1_raw: Any, op: str, v2_raw: Any, data_type: str = "string") -> bool:
        v1 = _resolve_n8n_parameter_value(v1_raw, current_json, node_outputs)
        v2 = _resolve_n8n_parameter_value(v2_raw, current_json, node_outputs)
        op_low = str(op or "equal").strip().lower()

        if data_type == "boolean" or isinstance(v2_raw, bool) or op_low in ("true", "false"):
            b1 = bool(v1) if not isinstance(v1, str) else v1.strip().lower() in ("true", "1", "yes")
            b2 = True if op_low == "true" else (False if op_low == "false" else (bool(v2) if not isinstance(v2, str) else v2.strip().lower() in ("true", "1", "yes")))
            res_b = (b1 == b2) if op_low not in ("notequal", "notequals") else (b1 != b2)
            details.append({"left": b1, "operation": op_low, "right": b2, "passed": res_b})
            return res_b

        if data_type == "number":
            try:
                n1 = float(v1 or 0)
                n2 = float(v2 or 0)
            except Exception:
                n1, n2 = 0.0, 0.0
            if op_low in ("larger", "gt", ">"):
                res_n = n1 > n2
            elif op_low in ("largerequal", "gte", ">="):
                res_n = n1 >= n2
            elif op_low in ("smaller", "lt", "<"):
                res_n = n1 < n2
            elif op_low in ("smallerequal", "lte", "<="):
                res_n = n1 <= n2
            elif op_low in ("notequal", "notequals", "!="):
                res_n = n1 != n2
            else:
                res_n = n1 == n2
            details.append({"left": n1, "operation": op_low, "right": n2, "passed": res_n})
            return res_n

        s1 = str(v1 if v1 is not None else "").strip()
        s2 = str(v2 if v2 is not None else "").strip()
        s1_low = s1.lower()
        s2_low = s2.lower()

        if op_low == "contains":
            res_s = s2_low in s1_low
        elif op_low in ("notcontains", "not_contains"):
            res_s = s2_low not in s1_low
        elif op_low in ("startswith", "starts_with"):
            res_s = s1_low.startswith(s2_low)
        elif op_low in ("endswith", "ends_with"):
            res_s = s1_low.endswith(s2_low)
        elif op_low in ("isempty", "empty"):
            res_s = len(s1) == 0
        elif op_low in ("isnotempty", "notempty", "not_empty"):
            res_s = len(s1) > 0
        elif op_low in ("notequal", "notequals", "!="):
            res_s = s1_low != s2_low
        elif op_low == "regex":
            try:
                res_s = bool(re.search(s2, s1, re.IGNORECASE))
            except Exception:
                res_s = False
        else:
            res_s = s1_low == s2_low

        details.append({"left": s1[:120], "operation": op_low, "right": s2[:120], "passed": res_s})
        return res_s

    # v1 schema: conditions.string, conditions.boolean, conditions.number
    for dtype in ("string", "boolean", "number"):
        c_list = conds_root.get(dtype)
        if isinstance(c_list, list):
            for c_item in c_list:
                if isinstance(c_item, dict):
                    results.append(_check_single(
                        c_item.get("value1"),
                        c_item.get("operation", "equal"),
                        c_item.get("value2", True if dtype == "boolean" else ""),
                        dtype
                    ))

    # v2 schema: conditions.conditions (list of {leftValue, rightValue, operator: {type, operation}})
    v2_list = conds_root.get("conditions")
    if isinstance(v2_list, list):
        for c_item in v2_list:
            if isinstance(c_item, dict):
                op_obj = c_item.get("operator") or {}
                dtype = str(op_obj.get("type") or "string").lower()
                op_name = str(op_obj.get("operation") or "equals").lower()
                results.append(_check_single(
                    c_item.get("leftValue"),
                    op_name,
                    c_item.get("rightValue"),
                    dtype
                ))

    if not results:
        return True, details

    passed = any(results) if use_any else all(results)
    return passed, details


def _execute_n8n_code_node(node: Dict[str, Any], current_json: Dict[str, Any], node_outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executes an `n8n-nodes-base.code` or `n8n-nodes-base.function` node.
    Supports:
    1) Thread-grouping JS code (like `Group Thread & Find Matching Row` for Conversations.xlsx) natively in Python!
    2) General JavaScript `jsCode` via Node.js subprocess (if `node` binary is available on host) or Python fallback.
    """
    params = node.get("parameters") or {}
    js_code = str(params.get("jsCode") or params.get("functionCode") or "").strip()
    if not js_code:
        return current_json

    # 1. Native fast-path for ANY Thread-Grouping Code node (`Group Comment Thread into Single Row` / `Group Thread & Find Matching Row`)
    node_name_low = str(node.get("name") or "").lower()
    is_thread_grouping_code = (
        any(k in js_code for k in (
            "targetRowNumber",
            "matchedRow",
            "target_row",
            "[Thread:",
            "thread_transcript",
            "updated_existing_thread_row",
            "created_new_thread_row"
        ))
        or ("thread" in node_name_low and "row" in node_name_low)
    )
    if is_thread_grouping_code:
        wh_data = (
            node_outputs.get("Webhook Trigger")
            or node_outputs.get("Webhook")
            or next((v for k, v in node_outputs.items() if "webhook" in k.lower() or "trigger" in k.lower()), None)
            or current_json
        )
        wb_body = wh_data.get("body") if isinstance(wh_data.get("body"), dict) else wh_data
        if isinstance(wb_body.get("data"), dict) and not wb_body.get("comment_id"):
            wb_body = {**wb_body["data"], **wb_body}

        sheet_resp = current_json if isinstance(current_json, dict) else {}
        existing_rows = sheet_resp.get("rows") if isinstance(sheet_resp.get("rows"), list) else []
        cells_dict = sheet_resp.get("cells") if isinstance(sheet_resp.get("cells"), dict) else {}

        def _norm_id(v: Any) -> str:
            s_id = str(v or "").strip()
            return s_id.split("_")[-1].strip() if "_" in s_id else s_id

        cid = str(wb_body.get("comment_id") or "").strip()
        parent_cid = str(wb_body.get("parent_comment_id") or wb_body.get("replied_to_id") or "").strip()
        raw_root = str(wb_body.get("thread_id") or wb_body.get("root_comment_id") or parent_cid or cid).strip()
        thread_id = _norm_id(raw_root) or _norm_id(cid) or "unknown_thread"

        candidate_ids: List[str] = []
        for cand_raw in [thread_id, _norm_id(parent_cid), _norm_id(cid)] + list(wb_body.get("thread_comment_ids") or []):
            c_norm = _norm_id(cand_raw)
            if c_norm and c_norm not in candidate_ids:
                candidate_ids.append(c_norm)

        is_own = bool(wb_body.get("is_own_comment") or wb_body.get("is_own"))
        acc_name = str(wb_body.get("account_name") or "Savvy Finds").strip()
        commenter_id = str(
            (wb_body.get("parent_author_id") or wb_body.get("author_id") or wb_body.get("author_name") or "Commenter")
            if is_own
            else (wb_body.get("author_id") or wb_body.get("author_name") or "Commenter")
        ).strip()
        commenter_name = str(
            (wb_body.get("parent_author_name") or "Commenter")
            if is_own
            else (wb_body.get("author_name") or "Commenter")
        ).strip()
        speaker_label = f"{acc_name} (Page)" if is_own else commenter_name
        msg_text = str(wb_body.get("message") or "").strip()
        new_line = f"{speaker_label}: {msg_text}" if msg_text else f"{speaker_label}: (Comment)"
        full_transcript = str(wb_body.get("thread_transcript") or "").strip()
        parent_msg = str(wb_body.get("parent_message") or "").strip()

        # Normalize rows from either structured_rows (`_row_number`, `A`, `B`) or legacy (`row_number`, `values.A`, `values.B`)
        normalized_sheet_rows: List[Tuple[int, str, str]] = []
        seen_row_nums = set()
        for r_item in existing_rows:
            if not isinstance(r_item, dict):
                continue
            r_num = int(r_item.get("_row_number") or r_item.get("row_number") or 0)
            if r_num < 1:
                continue
            vals = r_item.get("values") if isinstance(r_item.get("values"), dict) else r_item
            a_val = str(vals.get("A") or "").strip()
            b_val = str(vals.get("B") or "").strip()
            normalized_sheet_rows.append((r_num, a_val, b_val))
            seen_row_nums.add(r_num)

        # Also inspect `cells` map if any row wasn't in `rows`
        row_nums_from_cells = set()
        for coord_k in cells_dict.keys():
            m_c = re.match(r"^([A-Za-z]+)(\d+)$", str(coord_k).strip())
            if m_c:
                row_nums_from_cells.add(int(m_c.group(2)))
        for r_num in sorted(row_nums_from_cells):
            if r_num not in seen_row_nums:
                a_val = str(cells_dict.get(f"A{r_num}") or "").strip()
                b_val = str(cells_dict.get(f"B{r_num}") or "").strip()
                normalized_sheet_rows.append((r_num, a_val, b_val))
                seen_row_nums.add(r_num)

        matched_row_num: Optional[int] = None
        existing_col_a = ""
        existing_col_b = ""

        # Pass 1: Match by `[Thread: ...]` tag in Column A
        for r_num, a_val, b_val in normalized_sheet_rows:
            m_th = re.search(r"\[Thread:\s*([^\]]+)\]", a_val, re.I)
            if m_th:
                tracked = [_norm_id(x) for x in m_th.group(1).split(",") if x.strip()]
                if any(cid_cand in tracked for cid_cand in candidate_ids):
                    matched_row_num = r_num
                    existing_col_a = a_val
                    existing_col_b = b_val
                    break

        # Pass 2: Legacy row fallback (if top-level comment was logged before `[Thread: ...]` tag was added)
        if matched_row_num is None and (parent_cid or is_own):
            for r_num, a_val, b_val in normalized_sheet_rows:
                if "[Thread:" in a_val:
                    continue
                clean_a = re.sub(r"\s*\[Thread:[^\]]*\]", "", a_val).strip()
                if parent_msg and parent_msg in b_val:
                    matched_row_num = r_num
                    existing_col_a = a_val
                    existing_col_b = b_val
                    break
                if commenter_id and clean_a and clean_a == commenter_id:
                    matched_row_num = r_num
                    existing_col_a = a_val
                    existing_col_b = b_val
                    break

        # Build updated `[Thread: id1,id2]` tag
        merged_thread_ids: List[str] = []
        if existing_col_a:
            m_ex = re.search(r"\[Thread:\s*([^\]]+)\]", existing_col_a, re.I)
            if m_ex:
                for x in m_ex.group(1).split(","):
                    nx = _norm_id(x)
                    if nx and nx not in merged_thread_ids:
                        merged_thread_ids.append(nx)
        for c_id_item in candidate_ids:
            if c_id_item and c_id_item not in merged_thread_ids:
                merged_thread_ids.append(c_id_item)
        if not merged_thread_ids:
            merged_thread_ids.append(thread_id)

        base_author_a = re.sub(r"\s*\[Thread:[^\]]*\]", "", existing_col_a).strip() if existing_col_a else ""
        if not base_author_a or base_author_a.lower() == "savvy finds":
            base_author_a = commenter_id or commenter_name or "Commenter"

        final_col_a = f"{base_author_a} [Thread: {','.join(merged_thread_ids)}]".strip()

        max_existing_row = max((r_num for r_num, _, _ in normalized_sheet_rows), default=0)
        next_empty = int(sheet_resp.get("next_empty_row") or (max_existing_row + 1) or 2)
        target_row_num = matched_row_num if matched_row_num is not None else max(1, next_empty)

        if matched_row_num is not None and existing_col_b:
            if full_transcript and len(full_transcript) >= len(existing_col_b):
                final_col_b = full_transcript
            else:
                lines = [ln.strip() for ln in existing_col_b.splitlines() if ln.strip()]
                if new_line and new_line not in existing_col_b:
                    lines.append(new_line)
                final_col_b = "\n".join(lines)
        elif full_transcript:
            final_col_b = full_transcript
        elif is_own and parent_msg and parent_msg not in new_line:
            final_col_b = f"{commenter_name}: {parent_msg}\n{new_line}"
        else:
            final_col_b = new_line

        row_dict_payload = (
            {f"A{matched_row_num}": final_col_a, f"B{matched_row_num}": final_col_b}
            if matched_row_num is not None
            else {"A": final_col_a, "B": final_col_b}
        )

        return {
            "action": "updated_existing_thread_row" if matched_row_num is not None else "created_new_thread_row",
            "thread_id": thread_id,
            "threadId": thread_id,
            "target_row": target_row_num,
            "targetRowNumber": target_row_num,
            "colA": final_col_a,
            "colB": final_col_b,
            "row": row_dict_payload,
            "isUpdate": matched_row_num is not None
        }

    # 2. Try running custom JS via `node` CLI using stdin (avoids OS argv length/quoting issues on Windows)
    try:
        import subprocess
        runner_payload = {
            "current_json": current_json,
            "node_outputs": node_outputs,
            "js_code": js_code
        }
        wrapper_js = """
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf-8'));
const $json = payload.current_json || {};
const $input = {
  first: () => ({ json: $json }),
  all: () => ([{ json: $json }]),
  item: { json: $json }
};
const $ = (name) => {
  const out = (payload.node_outputs && payload.node_outputs[name]) || $json;
  return {
    first: () => ({ json: out }),
    item: { json: out }
  };
};
(async () => {
  const fn = new Function('$json', '$input', '$', `return (async () => { ${payload.js_code} })();`);
  const res = await fn($json, $input, $);
  if (Array.isArray(res) && res.length > 0) {
    const first = res[0];
    console.log(JSON.stringify(first && first.json ? first.json : first));
  } else if (res && typeof res === 'object') {
    console.log(JSON.stringify(res.json ? res.json : res));
  } else {
    console.log(JSON.stringify($json));
  }
})().catch(err => {
  console.error(err.message || String(err));
  process.exit(1);
});
"""
        proc = subprocess.run(
            ["node", "-e", wrapper_js],
            input=json.dumps(runner_payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=6
        )
        if proc.returncode == 0 and proc.stdout.strip():
            last_line = proc.stdout.strip().splitlines()[-1]
            parsed_out = json.loads(last_line)
            if isinstance(parsed_out, dict):
                return parsed_out
    except Exception:
        pass

    return current_json


def _execute_n8n_workflow_json_natively(
    workflow_json: Dict[str, Any],
    event_type: str,
    event_data: Dict[str, Any],
    is_test_run: bool = False
) -> Dict[str, Any]:
    """
    Executes an n8n Workflow `.json` graph directly inside GlennBot's Python engine!
    Supports:
    - `n8n-nodes-base.webhook` / `glennbot.dashboardTrigger` (In-Dashboard Event Trigger)
    - `n8n-nodes-base.if` / `n8n-nodes-base.filter` (Conditional branching with True/False ports)
    - `n8n-nodes-base.wait` (Timer wait node)
    - `n8n-nodes-base.code` / `n8n-nodes-base.function` (JavaScript / Thread Grouping / Transformation)
    - `n8n-nodes-base.httpRequest` (Calls GlennBot `/api/v1/*` or external REST endpoints)
    - `n8n-nodes-base.set` (Edit / Set fields)
    """
    start_ts = time.time()
    now_dt = datetime.now(MANILA_TZ)
    now_str = now_dt.strftime("%Y-%m-%d %I:%M:%S %p")

    nodes_list = workflow_json.get("nodes") if isinstance(workflow_json.get("nodes"), list) else []
    connections_map = workflow_json.get("connections") if isinstance(workflow_json.get("connections"), dict) else {}

    if not nodes_list:
        return {
            "status": "error",
            "message": "Workflow JSON has no nodes to execute.",
            "trace": []
        }

    # Build lookup maps by node name and node id
    nodes_by_name: Dict[str, Dict[str, Any]] = {}
    for n in nodes_list:
        if isinstance(n, dict) and n.get("name"):
            nodes_by_name[str(n["name"])] = n

    # Find entry trigger node (Webhook / Dashboard Trigger / Schedule Trigger / or first node without incoming edges)
    incoming_counts: Dict[str, int] = {name: 0 for name in nodes_by_name}
    for src_name, conn_obj in connections_map.items():
        if not isinstance(conn_obj, dict):
            continue
        main_branches = conn_obj.get("main")
        if isinstance(main_branches, list):
            for branch in main_branches:
                if isinstance(branch, list):
                    for edge in branch:
                        if isinstance(edge, dict) and edge.get("node") in incoming_counts:
                            incoming_counts[str(edge["node"])] += 1

    trigger_node = None
    for n in nodes_list:
        if not isinstance(n, dict):
            continue
        ntype = str(n.get("type") or "").lower()
        if any(k in ntype for k in ("webhook", "trigger", "manual")):
            trigger_node = n
            break
    if not trigger_node:
        for name, cnt in incoming_counts.items():
            if cnt == 0:
                trigger_node = nodes_by_name[name]
                break
    if not trigger_node:
        trigger_node = nodes_list[0]

    # Build initial trigger output matching n8n's exact Webhook item structure (`$json.body.<field>` and `$json.<field>`)
    envelope_body: Dict[str, Any] = {
        "event": event_type,
        "source": "glennbot_automations_canvas",
        "timestamp_manila": now_str,
        "timestamp_iso": now_dt.isoformat(),
        "data": event_data
    }
    if isinstance(event_data, dict):
        for k_f, v_f in event_data.items():
            if k_f not in envelope_body:
                envelope_body[k_f] = v_f

    initial_item_json: Dict[str, Any] = {
        "headers": {"x-glennbot-event": event_type},
        "params": {},
        "query": {},
        "body": envelope_body,
        **envelope_body
    }

    node_outputs: Dict[str, Dict[str, Any]] = {}
    execution_trace: List[Dict[str, Any]] = []
    active_api_key = _get_active_internal_api_key_token()
    local_port = os.getenv("PORT", "5001").strip() or "5001"
    local_base_origin = f"http://127.0.0.1:{local_port}"

    # BFS / DFS execution queue: (node_name, input_json_dict)
    queue: List[Tuple[str, Dict[str, Any]]] = [(str(trigger_node.get("name")), initial_item_json)]
    steps_executed = 0
    max_steps = 35

    while queue and steps_executed < max_steps:
        curr_name, curr_input = queue.pop(0)
        node = nodes_by_name.get(curr_name)
        if not node:
            continue
        if node.get("disabled") is True:
            execution_trace.append({
                "node_id": node.get("id") or curr_name,
                "node_name": curr_name,
                "node_type": node.get("type") or "",
                "status": "skipped",
                "detail": "Node is disabled"
            })
            continue

        steps_executed += 1
        step_t0 = time.time()
        ntype = str(node.get("type") or "").strip()
        ntype_low = ntype.lower()
        params = node.get("parameters") or {}

        out_json: Dict[str, Any] = dict(curr_input) if isinstance(curr_input, dict) else {"value": curr_input}
        selected_branch_index: Optional[int] = 0
        step_status = "success"
        step_detail = ""

        try:
            # 1. TRIGGER / WEBHOOK NODE (Acts as Native GlennBot Dashboard Event Trigger!)
            if any(k in ntype_low for k in ("webhook", "trigger", "manual")):
                out_json = initial_item_json
                node_outputs[curr_name] = out_json
                # Also alias common trigger names so $('Webhook') and $('Webhook Trigger') both resolve
                node_outputs.setdefault("Webhook", out_json)
                node_outputs.setdefault("Webhook Trigger", out_json)
                step_detail = f"Dashboard Event Trigger received '{event_type}'"

            # 2. IF / FILTER NODE
            elif ntype_low.endswith(".if") or ntype_low.endswith(".filter") or ntype_low == "if":
                passed, cond_details = _evaluate_n8n_if_node(node, curr_input, node_outputs)
                node_outputs[curr_name] = out_json
                selected_branch_index = 0 if passed else 1
                branch_label = "TRUE (Branch 0)" if passed else "FALSE (Branch 1)"
                step_detail = f"Evaluated {len(cond_details)} condition(s) -> {branch_label}"

            # 3. WAIT NODE
            elif ntype_low.endswith(".wait") or ntype_low == "wait":
                amt = float(params.get("amount") or 1)
                unit = str(params.get("unit") or "seconds").strip().lower()
                wait_seconds = amt
                if unit.startswith("min"):
                    wait_seconds = amt * 60.0
                elif unit.startswith("hour"):
                    wait_seconds = amt * 3600.0
                if is_test_run:
                    # Cap test-run sleep at 1.0s so interactive UI testing responds quickly
                    time.sleep(min(wait_seconds, 1.0))
                    step_detail = f"Wait Timer ({amt} {unit}) — fast-forwarded in Test Mode"
                else:
                    # Cap live sleep at 300s per worker thread safety
                    time.sleep(min(max(0.0, wait_seconds), 300.0))
                    step_detail = f"Waited {amt} {unit}"
                node_outputs[curr_name] = out_json

            # 4. CODE / FUNCTION NODE
            elif ntype_low.endswith(".code") or ntype_low.endswith(".function") or ntype_low == "code":
                out_json = _execute_n8n_code_node(node, curr_input, node_outputs)
                node_outputs[curr_name] = out_json
                step_detail = f"Executed Code node ({len(out_json)} output keys)"

            # 5. SET / EDIT FIELDS NODE
            elif ntype_low.endswith(".set") or ntype_low == "set":
                out_json = dict(curr_input)
                # v3 assignments or v1 values
                assignments = ((params.get("assignments") or {}).get("assignments")) or []
                if isinstance(assignments, list):
                    for a_item in assignments:
                        if isinstance(a_item, dict) and a_item.get("name"):
                            out_json[str(a_item["name"])] = _resolve_n8n_parameter_value(a_item.get("value"), curr_input, node_outputs)
                vals_map = params.get("values") or {}
                if isinstance(vals_map, dict):
                    for _, v_list in vals_map.items():
                        if isinstance(v_list, list):
                            for v_entry in v_list:
                                if isinstance(v_entry, dict) and v_entry.get("name"):
                                    out_json[str(v_entry["name"])] = _resolve_n8n_parameter_value(v_entry.get("value"), curr_input, node_outputs)
                node_outputs[curr_name] = out_json
                step_detail = "Updated item fields"

            # 6. HTTP REQUEST / GLENNBOT API NODE
            elif "httprequest" in ntype_low or ntype_low == "http":
                method_str = str(params.get("method") or "GET").strip().upper()
                raw_url = str(params.get("url") or "").strip()
                resolved_url = str(_resolve_n8n_parameter_value(raw_url, curr_input, node_outputs) or "").strip()

                # Rewrite any external/ngrok `/api/v1/...` or `/api/...` URL to local GlennBot server for instant reliable execution
                m_api_path = re.search(r"(/api/v1/[^\s\"']+|/api/[^\s\"']+)", resolved_url)
                if m_api_path:
                    target_url = f"{local_base_origin}{m_api_path.group(1)}"
                else:
                    target_url = resolved_url

                req_headers: Dict[str, str] = {
                    "Content-Type": "application/json",
                    "X-API-Key": active_api_key
                }
                hdr_params = ((params.get("headerParameters") or {}).get("parameters")) or []
                if isinstance(hdr_params, list):
                    for hp in hdr_params:
                        if isinstance(hp, dict) and hp.get("name"):
                            h_name = str(hp["name"]).strip()
                            h_val = str(_resolve_n8n_parameter_value(hp.get("value", ""), curr_input, node_outputs) or "").strip()
                            if h_name.lower() == "x-api-key" and (not h_val or "YOUR_" in h_val):
                                h_val = active_api_key
                            req_headers[h_name] = h_val

                req_body_obj: Any = None
                if method_str in ("POST", "PUT", "PATCH", "DELETE"):
                    raw_json_body = params.get("jsonBody")
                    if raw_json_body is not None:
                        resolved_body = _resolve_n8n_parameter_value(raw_json_body, curr_input, node_outputs)
                        if isinstance(resolved_body, (dict, list)):
                            req_body_obj = resolved_body
                        elif isinstance(resolved_body, str):
                            s_body = resolved_body.strip()
                            try:
                                req_body_obj = json.loads(s_body)
                            except Exception:
                                req_body_obj = {"raw": s_body}
                    else:
                        body_params = ((params.get("bodyParameters") or {}).get("parameters")) or []
                        if isinstance(body_params, list) and body_params:
                            req_body_obj = {}
                            for bp in body_params:
                                if isinstance(bp, dict) and bp.get("name"):
                                    req_body_obj[str(bp["name"])] = _resolve_n8n_parameter_value(bp.get("value"), curr_input, node_outputs)

                if target_url.startswith("http"):
                    if method_str == "GET":
                        r_http = HTTP_SESSION.get(target_url, headers=req_headers, timeout=20)
                    else:
                        r_http = HTTP_SESSION.request(
                            method_str,
                            target_url,
                            headers=req_headers,
                            json=req_body_obj if req_body_obj is not None else {},
                            timeout=25
                        )
                    try:
                        out_json = r_http.json() if r_http.content else {"status_code": r_http.status_code}
                        if not isinstance(out_json, dict):
                            out_json = {"data": out_json, "status_code": r_http.status_code}
                    except Exception:
                        out_json = {"status_code": r_http.status_code, "text": (r_http.text or "")[:500]}
                    node_outputs[curr_name] = out_json
                    step_status = "success" if 200 <= r_http.status_code < 400 else "error"
                    step_detail = f"{method_str} {m_api_path.group(1) if m_api_path else target_url} -> HTTP {r_http.status_code}"
                else:
                    step_status = "error"
                    step_detail = f"Invalid HTTP URL: '{resolved_url}'"
                    node_outputs[curr_name] = out_json

            else:
                # Generic pass-through node (Merge, NoOp, Switch, etc.)
                node_outputs[curr_name] = out_json
                step_detail = f"Executed node ({ntype})"

        except Exception as step_exc:
            step_status = "error"
            step_detail = f"Error: {step_exc}"
            node_outputs[curr_name] = out_json

        step_ms = int((time.time() - step_t0) * 1000)
        execution_trace.append({
            "node_id": node.get("id") or curr_name,
            "node_name": curr_name,
            "node_type": ntype,
            "status": step_status,
            "branch_index": selected_branch_index,
            "duration_ms": step_ms,
            "detail": step_detail,
            "output_preview": json.dumps(out_json, ensure_ascii=False)[:360]
        })

        if step_status == "error":
            break

        # Enqueue connected downstream nodes on `selected_branch_index`
        conn_entry = connections_map.get(curr_name)
        if isinstance(conn_entry, dict):
            main_branches = conn_entry.get("main")
            if isinstance(main_branches, list) and selected_branch_index is not None:
                if 0 <= selected_branch_index < len(main_branches):
                    target_edges = main_branches[selected_branch_index]
                    if isinstance(target_edges, list):
                        for edge in target_edges:
                            if isinstance(edge, dict) and edge.get("node"):
                                queue.append((str(edge["node"]), out_json))

    total_ms = int((time.time() - start_ts) * 1000)
    any_err = any(t.get("status") == "error" for t in execution_trace)
    summary_record = {
        "execution_id": f"auto_exec_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "workflow_name": str(workflow_json.get("name") or "Automation Workflow"),
        "event_type": event_type,
        "is_test_run": is_test_run,
        "status": "error" if any_err else "success",
        "steps_count": len(execution_trace),
        "duration_ms": total_ms,
        "timestamp": now_str,
        "trace": execution_trace
    }

    with AUTOMATIONS_CANVAS_LOCK:
        hist = list(AUTOMATIONS_CANVAS_STATE.get("execution_history") or [])
        hist.insert(0, summary_record)
        AUTOMATIONS_CANVAS_STATE["execution_history"] = hist[:40]

    with INTERNAL_API_LOCK:
        logs = list(INTERNAL_API_STATE.get("recent_logs") or [])
        logs.insert(0, {
            "timestamp": now_str,
            "method": "AUTOMATIONS CANVAS",
            "endpoint": f"{event_type} -> {summary_record['workflow_name']}",
            "key_name": f"{len(execution_trace)} nodes ({total_ms}ms)",
            "status": "ERR" if any_err else "200 OK"
        })
        INTERNAL_API_STATE["recent_logs"] = logs[:40]

    return summary_record


def _execute_active_dashboard_automations_for_event(event_type: str, data: Dict[str, Any]):
    """
    Automatically runs any Active workflow inside the In-Dashboard 'Automations' Modal
    when a matching dashboard event (`comment.received`, `message.received`, `email.received`, etc.) occurs.
    """
    try:
        state = _load_automations_canvas_state(force_cloud=False)
        api_state = _load_internal_api_state(force_cloud=False)
        workflows: List[Dict[str, Any]] = list(state.get("workflows") or [])
        seen_wf_names = {str(w.get("name") or "").strip().lower() for w in workflows if isinstance(w, dict)}

        # Also include any active n8n workflows that have a full workflow_json graph so they work natively in-dashboard too
        for nw in (api_state.get("n8n_workflows") or []):
            if not isinstance(nw, dict) or not nw.get("active", False):
                continue
            nw_json = nw.get("workflow_json")
            if isinstance(nw_json, dict) and isinstance(nw_json.get("nodes"), list):
                nw_name = str(nw.get("name") or nw_json.get("name") or "").strip().lower()
                if nw_name and nw_name not in seen_wf_names:
                    workflows.append(nw)
                    seen_wf_names.add(nw_name)

        for wf in workflows:
            if not isinstance(wf, dict) or not wf.get("active", False):
                continue
            wf_json = wf.get("workflow_json")
            if not isinstance(wf_json, dict) or not isinstance(wf_json.get("nodes"), list):
                continue
            evts = wf.get("events") if isinstance(wf.get("events"), dict) else {}
            is_sms_evt = event_type in ("sms.sent", "sms.received")
            raw_wf_low = json.dumps(wf_json, ensure_ascii=False).lower()
            is_comment_wf = event_type == "comment.received" and any(
                k in raw_wf_low for k in ("comment", "author_name", "author_id", "savvy finds", "conversations")
            )
            if (
                event_type == "n8n.test"
                or evts.get(event_type, False)
                or (is_sms_evt and evts.get("message.received", False))
                or is_comment_wf
                or not any(evts.values())
            ):
                _execute_n8n_workflow_json_natively(wf_json, event_type, data, is_test_run=False)
    except Exception as e:
        print(f"[AutomationsCanvas] Event execution warning: {e}")


@router.get("/api/automations/workflows")
async def api_get_automations_canvas_workflows(request: Request):
    """Returns all workflows saved in the In-Dashboard 'Automations' Canvas plus any imported n8n workflows."""
    canvas_state = await run_in_threadpool(lambda: _load_automations_canvas_state(force_cloud=False))
    api_state = await run_in_threadpool(lambda: _load_internal_api_state(force_cloud=False))
    base_url = get_dynamic_base_url(request=request, prefer_public=True)
    live_base_api = f"{base_url}/api/v1"

    canvas_wfs = list(canvas_state.get("workflows") or [])
    existing_ids = {str(w.get("id")) for w in canvas_wfs if isinstance(w, dict)}

    # Also surface workflows from Internal API n8n list so user can load them into the Automations Canvas if desired
    for n8n_w in (api_state.get("n8n_workflows") or []):
        if isinstance(n8n_w, dict) and isinstance(n8n_w.get("workflow_json"), dict) and n8n_w["workflow_json"].get("nodes"):
            wid = str(n8n_w.get("id") or "")
            if wid and wid not in existing_ids:
                patched = _auto_inject_credentials_into_workflow_json(n8n_w["workflow_json"], live_base_api)
                canvas_wfs.append({
                    "id": wid,
                    "name": str(n8n_w.get("name") or patched.get("name") or "n8n Workflow"),
                    "active": bool(n8n_w.get("canvas_active", False)),
                    "events": n8n_w.get("events") or _analyze_n8n_workflow_json(patched).get("events") or {},
                    "detected_conditions": n8n_w.get("detected_conditions") or [],
                    "workflow_json": patched,
                    "updated_at": str(n8n_w.get("updated_at") or "")
                })

    return {
        "status": "success",
        "base_api_url": live_base_api,
        "active_api_key": _get_active_internal_api_key_token(),
        "workflows": canvas_wfs,
        "execution_history": canvas_state.get("execution_history") or []
    }


@router.post("/api/automations/workflows/save")
async def api_save_automations_canvas_workflow(request: Request):
    """Saves an uploaded or Ask-AI-generated `.json` workflow into the In-Dashboard 'Automations' Canvas."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    def _do_save():
        _load_automations_canvas_state(force_cloud=False)
        _load_internal_api_state(force_cloud=False)
        live_base_api = f"{get_dynamic_base_url(request=request, prefer_public=True)}/api/v1"

        raw_wf_json = body.get("workflow_json") if isinstance(body.get("workflow_json"), dict) else body
        if not isinstance(raw_wf_json, dict) or not isinstance(raw_wf_json.get("nodes"), list):
            return None, "Uploaded JSON must be a valid n8n workflow containing a 'nodes' array."

        patched_json = _auto_inject_credentials_into_workflow_json(raw_wf_json, live_base_api)
        analysis = _analyze_n8n_workflow_json(patched_json)

        wf_id = str(body.get("id") or "").strip() or f"auto_wf_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5]}"
        wf_name = str(body.get("name") or patched_json.get("name") or analysis.get("workflow_name") or "Automation Workflow").strip()
        patched_json["name"] = wf_name
        is_active = bool(body.get("active", patched_json.get("active", True)))
        patched_json["active"] = is_active

        evts = body.get("events") if isinstance(body.get("events"), dict) else (analysis.get("events") or _default_n8n_events_dict(False))
        now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")

        record = {
            "id": wf_id,
            "name": wf_name,
            "active": is_active,
            "events": evts,
            "detected_conditions": analysis.get("detected_conditions") or [],
            "webhook_path": analysis.get("webhook_path") or "",
            "workflow_json": patched_json,
            "updated_at": now_str
        }

        with AUTOMATIONS_CANVAS_LOCK:
            wfs = list(AUTOMATIONS_CANVAS_STATE.get("workflows") or [])
            replaced = False
            for idx, existing in enumerate(wfs):
                if isinstance(existing, dict) and str(existing.get("id")) == wf_id:
                    wfs[idx] = record
                    replaced = True
                    break
            if not replaced:
                wfs.insert(0, record)
            AUTOMATIONS_CANVAS_STATE["workflows"] = wfs

        _save_automations_canvas_state()
        return record, None

    saved_rec, err_msg = await run_in_threadpool(_do_save)
    if err_msg:
        return JSONResponse({"status": "error", "message": err_msg}, status_code=400)

    return {
        "status": "success",
        "message": f"Workflow '{saved_rec['name']}' saved to Automations Canvas!",
        "workflow": saved_rec,
        "workflows": AUTOMATIONS_CANVAS_STATE.get("workflows") or []
    }


@router.post("/api/automations/workflows/execute")
async def api_execute_automations_canvas_workflow(request: Request):
    """
    Runs a workflow JSON directly inside the GlennBot Automations Canvas engine (Test Run or Manual Trigger)
    and returns the node-by-node execution trace so the visual canvas can highlight every executed node!
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    def _do_exec():
        _load_automations_canvas_state(force_cloud=False)
        _load_internal_api_state(force_cloud=False)
        live_base_api = f"{get_dynamic_base_url(request=request, prefer_public=True)}/api/v1"

        wf_id = str(body.get("workflow_id") or body.get("id") or "").strip()
        wf_json = body.get("workflow_json") if isinstance(body.get("workflow_json"), dict) else None
        matched_wf = None

        if wf_id:
            matched_wf = next((w for w in (AUTOMATIONS_CANVAS_STATE.get("workflows") or []) if str(w.get("id")) == wf_id), None)
            if not wf_json and matched_wf:
                wf_json = matched_wf.get("workflow_json")

        if not isinstance(wf_json, dict) or not isinstance(wf_json.get("nodes"), list):
            return None, "Please load or upload a valid .JSON workflow on the Automations Canvas first."

        patched_json = _auto_inject_credentials_into_workflow_json(wf_json, live_base_api)
        analysis = _analyze_n8n_workflow_json(patched_json)
        evts = (matched_wf or {}).get("events") or analysis.get("events") or {}
        sim_event = str(body.get("event_type") or "").strip()
        if not sim_event:
            sim_event = next((k for k, v in evts.items() if v), "comment.received")

        custom_payload = body.get("test_payload") if isinstance(body.get("test_payload"), dict) else None
        if not custom_payload:
            custom_payload = _build_dynamic_test_payload_for_workflow(sim_event, {
                "name": patched_json.get("name"),
                "workflow_json": patched_json,
                "detected_conditions": analysis.get("detected_conditions") or []
            })
            # Ensure thread_id and thread_transcript are populated for comment.received tests
            if sim_event == "comment.received":
                c_id = str(custom_payload.get("comment_id") or "12209988776655").strip()
                norm_tid = _normalize_comment_key(c_id) or c_id
                custom_payload.setdefault("thread_id", norm_tid)
                custom_payload.setdefault("root_comment_id", c_id)
                acc_n = str(custom_payload.get("account_name") or "Savvy Finds").strip()
                auth_n = str(custom_payload.get("author_name") or "Maria Santos").strip()
                msg_t = str(custom_payload.get("message") or "Hm po ito? Available pa ba?").strip()
                custom_payload.setdefault("thread_transcript", f"{auth_n}: {msg_t}")

        exec_result = _execute_n8n_workflow_json_natively(
            patched_json,
            sim_event,
            custom_payload,
            is_test_run=True
        )
        threading.Thread(target=_save_automations_canvas_state, daemon=True).start()
        return exec_result, None

    res_obj, err_str = await run_in_threadpool(_do_exec)
    if err_str:
        return JSONResponse({"status": "error", "message": err_str}, status_code=400)

    return {
        "status": "success",
        "message": f"Executed '{res_obj.get('workflow_name')}' ({res_obj.get('steps_count')} nodes in {res_obj.get('duration_ms')}ms)!",
        "execution": res_obj,
        "execution_history": AUTOMATIONS_CANVAS_STATE.get("execution_history") or []
    }


@router.delete("/api/automations/workflows/{workflow_id}")
async def api_delete_automations_canvas_workflow(workflow_id: str, request: Request):
    def _do_del():
        _load_automations_canvas_state(force_cloud=False)
        _load_internal_api_state(force_cloud=False)
        clean_id = str(workflow_id or "").strip()
        base_url = get_dynamic_base_url(request=request, prefer_public=True)
        live_base_api = f"{base_url}/api/v1"

        with AUTOMATIONS_CANVAS_LOCK:
            AUTOMATIONS_CANVAS_STATE["workflows"] = [
                w for w in (AUTOMATIONS_CANVAS_STATE.get("workflows") or [])
                if isinstance(w, dict) and str(w.get("id")) != clean_id
            ]
        _save_automations_canvas_state()

        # Also remove from INTERNAL_API_STATE["n8n_workflows"] if present so it doesn't resurface in the dropdown
        removed_from_internal = False
        with INTERNAL_API_LOCK:
            old_n8n = list(INTERNAL_API_STATE.get("n8n_workflows") or [])
            new_n8n = [
                w for w in old_n8n
                if isinstance(w, dict) and str(w.get("id")) != clean_id
            ]
            if len(new_n8n) != len(old_n8n):
                INTERNAL_API_STATE["n8n_workflows"] = new_n8n
                removed_from_internal = True
        if removed_from_internal:
            _save_internal_api_state()

        canvas_wfs = list(AUTOMATIONS_CANVAS_STATE.get("workflows") or [])
        existing_ids = {str(w.get("id")) for w in canvas_wfs if isinstance(w, dict)}
        for n8n_w in (INTERNAL_API_STATE.get("n8n_workflows") or []):
            if isinstance(n8n_w, dict) and isinstance(n8n_w.get("workflow_json"), dict) and n8n_w["workflow_json"].get("nodes"):
                wid = str(n8n_w.get("id") or "")
                if wid and wid not in existing_ids:
                    patched = _auto_inject_credentials_into_workflow_json(n8n_w["workflow_json"], live_base_api)
                    canvas_wfs.append({
                        "id": wid,
                        "name": str(n8n_w.get("name") or patched.get("name") or "n8n Workflow"),
                        "active": bool(n8n_w.get("canvas_active", False)),
                        "events": n8n_w.get("events") or _analyze_n8n_workflow_json(patched).get("events") or {},
                        "detected_conditions": n8n_w.get("detected_conditions") or [],
                        "workflow_json": patched,
                        "updated_at": str(n8n_w.get("updated_at") or "")
                    })
        return canvas_wfs

    remaining = await run_in_threadpool(_do_del)
    return {
        "status": "success",
        "message": "Workflow removed from Automations Canvas.",
        "workflows": remaining
    }



# =========================================================================
# --- AUTHENTICATED EXTERNAL / N8N AUTOMATION ENDPOINTS (/api/v1/*) ---
# =========================================================================

def _unauthorized_v1_response():
    return JSONResponse({
        "status": "error",
        "code": "UNAUTHORIZED_API_KEY",
        "message": "Invalid or missing GlennBot Internal API Key. Pass 'X-API-Key: gb_live_...' or 'Authorization: Bearer gb_live_...' in your n8n HTTP Request node."
    }, status_code=401)


@router.get("/api/v1/status")
async def api_v1_status(request: Request):
    key_obj = await run_in_threadpool(lambda: _verify_internal_api_key(request))
    if not key_obj:
        return _unauthorized_v1_response()

    def _gather_v1_status():
        s_accs = refresh_connected_accounts_cache(force=False)
        _load_email_hub_state(force_cloud=False)
        e_accs = EMAIL_HUB_STATE.get("accounts") or []
        c_list = _load_crm_contacts_state(force_cloud=False)
        vs = _load_files_vault_store(force_cloud=False)
        ss = _load_spreadsheets_store(force_cloud=False)
        return s_accs, e_accs, c_list, vs, ss

    social_accs, email_accs, contacts, v_store, sp_store = await run_in_threadpool(_gather_v1_status)

    return {
        "status": "success",
        "service": "GlennBot Internal Automation API v1",
        "authenticated_key": key_obj.get("name"),
        "server_time_manila": datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p"),
        "counts": {
            "connected_social_accounts": len(social_accs),
            "connected_email_accounts": len(email_accs),
            "crm_contacts": len(contacts),
            "vault_files": len(v_store.get("files") or []),
            "spreadsheets": len(sp_store.get("workbooks") or [])
        },
        "available_endpoints": [
            "GET /api/v1/status",
            "GET /api/v1/accounts",
            "POST /api/v1/ai/ask",
            "GET /api/v1/posts",
            "POST /api/v1/posts/publish",
            "POST /api/v1/posts/schedule",
            "POST /api/v1/posts/delete",
            "DELETE /api/v1/posts/{record_id}",
            "GET /api/v1/messages",
            "POST /api/v1/messages/send",
            "POST /api/v1/messages/mark-read",
            "POST /api/v1/sms/send",
            "GET /api/v1/sms/thread-status",
            "GET /api/v1/comments",
            "GET /api/v1/comments/thread-status",
            "POST /api/v1/comments/reply",
            "POST /api/v1/comments/send-dm",
            "POST /api/v1/comments/like",
            "POST /api/v1/comments/hide",
            "POST /api/v1/comments/mark-read",
            "POST /api/v1/comments/dismiss",
            "GET /api/v1/emails",
            "POST /api/v1/emails/send",
            "POST /api/v1/emails/trash",
            "GET /api/v1/contacts",
            "POST /api/v1/contacts",
            "POST /api/v1/contacts/sync",
            "DELETE /api/v1/contacts/{contact_id}",
            "GET /api/v1/files",
            "GET /api/v1/files/{file_id}",
            "GET /api/v1/spreadsheets",
            "GET /api/v1/spreadsheets/read",
            "POST /api/v1/spreadsheets/read",
            "POST /api/v1/spreadsheets/append-row",
            "POST /api/v1/spreadsheets/update-cells",
            "GET /api/v1/calendar/events",
            "POST /api/v1/calendar/schedule",
            "POST /api/v1/calendar/reschedule",
            "POST /api/v1/calendar/cancel",
            "DELETE /api/v1/calendar/events/{event_id}",
            "GET /api/v1/analytics",
            "GET /api/v1/presets"
        ]
    }


@router.get("/api/v1/accounts")
async def api_v1_list_accounts(request: Request, platform: str = ""):
    key_obj = await run_in_threadpool(lambda: _verify_internal_api_key(request))
    if not key_obj:
        return _unauthorized_v1_response()

    clean_plat = (platform or "").strip().lower()
    def _gather_v1_accs():
        s_accs = refresh_connected_accounts_cache(force=False)
        _load_email_hub_state(force_cloud=False)
        return s_accs, (EMAIL_HUB_STATE.get("accounts") or [])
    social_accs, email_accs = await run_in_threadpool(_gather_v1_accs)

    clean_social = []
    for s in social_accs:
        p = str(s.get("platform") or "").lower()
        if clean_plat and p != clean_plat:
            continue
        clean_social.append({
            "account_id": s.get("account_id"),
            "platform": p,
            "account_name": s.get("account_name"),
            "username": s.get("username"),
            "avatar_url": s.get("avatar_url")
        })

    clean_emails = []
    for e in email_accs:
        p = str(e.get("provider") or "gmail").lower()
        if clean_plat and p != clean_plat and clean_plat != "email":
            continue
        clean_emails.append({
            "account_id": e.get("id"),
            "provider": p,
            "email_address": e.get("email_address"),
            "display_name": e.get("display_name"),
            "status": e.get("status", "ACTIVE")
        })

    return {
        "status": "success",
        "social_accounts": clean_social,
        "email_accounts": clean_emails,
        "total_social": len(clean_social),
        "total_email": len(clean_emails)
    }


@router.get("/api/v1/posts")
async def api_v1_list_posts(request: Request, status: str = "", platform: str = "", limit: int = 50):
    key_obj = await run_in_threadpool(lambda: _verify_internal_api_key(request))
    if not key_obj:
        return _unauthorized_v1_response()

    sched_res = await run_in_threadpool(get_scheduled_posts)
    items = list(sched_res.get("items") or [])
    if status:
        s_low = status.strip().lower()
        items = [x for x in items if str(x.get("status") or "").lower() == s_low]
    if platform:
        p_low = platform.strip().lower()
        items = [x for x in items if str(x.get("platform") or "").lower() == p_low]
    items.sort(key=lambda x: str(x.get("scheduled_iso") or ""), reverse=True)
    return {
        "status": "success",
        "count": len(items[:limit]),
        "posts": items[:max(1, min(limit, 200))]
    }


@router.post("/api/v1/posts/publish")
@router.post("/api/v1/posts/schedule")
async def api_v1_publish_or_schedule_post(request: Request):
    """
    Allows n8n to schedule or immediately publish social media posts via pure JSON payload!
    Body fields:
      - platform (str) or platforms (list of str): e.g. "facebook", ["facebook", "instagram"]
      - account_id / page_id (str, optional): target page/account ID (auto-selects connected account for platform if omitted)
      - post_type (str): "text", "image", "reels", "video169" (default: auto-detected from media_url or "text")
      - caption (str): Post text / caption
      - title (str, optional): Video title (for YouTube)
      - media_url / video_url (str, optional): Public URL to image or video file
      - image_urls (list of str, optional): Public URLs for multi-image posts
      - thumbnail_url (str, optional): Public URL for video thumbnail
      - date (str, optional): "YYYY-MM-DD" in Asia/Manila
      - time (str, optional): "HH:MM" (24h) in Asia/Manila
      - publish_now (bool, optional): True to publish immediately
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    return await run_in_threadpool(lambda: _v1_publish_or_schedule_post_sync(body))


def _v1_publish_or_schedule_post_sync(body: Dict[str, Any]):
    raw_platforms = body.get("platforms") or body.get("platform") or []
    if isinstance(raw_platforms, str):
        platforms_list = [p.strip().lower() for p in raw_platforms.split(",") if p.strip()]
    elif isinstance(raw_platforms, list):
        platforms_list = [str(p).strip().lower() for p in raw_platforms if str(p).strip()]
    else:
        platforms_list = []

    if not platforms_list:
        return JSONResponse({"status": "error", "message": "Please provide 'platform' (e.g. 'facebook') or 'platforms' (['facebook', 'instagram'])."}, status_code=400)

    caption = str(body.get("caption") or body.get("message") or body.get("content") or "").strip()
    title = str(body.get("title") or "").strip()
    media_url = str(body.get("media_url") or body.get("video_url") or "").strip()
    thumb_url = str(body.get("thumbnail_url") or "").strip()
    image_urls = body.get("image_urls") or ([] if not body.get("image_url") else [body.get("image_url")])
    if isinstance(image_urls, str):
        image_urls = [u.strip() for u in image_urls.split(",") if u.strip()]

    # Support Google Drive Files Vault file_id / file_ids directly from n8n
    vault_media_file_id = str(body.get("file_id") or body.get("vault_file_id") or body.get("media_file_id") or "").strip()
    vault_thumb_file_id = str(body.get("thumb_file_id") or body.get("vault_thumb_file_id") or "").strip()
    raw_vault_ids = body.get("file_ids") or body.get("vault_file_ids") or body.get("image_file_ids") or []
    if isinstance(raw_vault_ids, str):
        vault_media_file_ids = [x.strip() for x in raw_vault_ids.split(",") if x.strip()]
    elif isinstance(raw_vault_ids, list):
        vault_media_file_ids = [str(x).strip() for x in raw_vault_ids if str(x).strip()]
    else:
        vault_media_file_ids = []

    post_type = str(body.get("post_type") or "").strip().lower()
    if not post_type:
        if vault_media_file_id:
            try:
                v_store = _load_files_vault_store(force_cloud=False)
                v_match = next((f for f in (v_store.get("files") or []) if str(f.get("file_id")) == vault_media_file_id), None)
                v_ctype = str((v_match or {}).get("content_type") or "").lower()
                if v_ctype.startswith("image/"):
                    post_type = "image"
                    if not vault_media_file_ids:
                        vault_media_file_ids = [vault_media_file_id]
                else:
                    post_type = "reels"
            except Exception:
                post_type = "reels"
        elif vault_media_file_ids:
            post_type = "image"
        elif media_url and any(ext in media_url.lower() for ext in (".mp4", ".mov", ".webm", "video")):
            post_type = "reels"
        elif image_urls or (media_url and any(ext in media_url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp"))):
            post_type = "image"
            if media_url and not image_urls:
                image_urls = [media_url]
        else:
            post_type = "text"

    date_val = str(body.get("date") or "").strip()
    time_val = str(body.get("time") or "").strip()
    publish_now = bool(body.get("publish_now", not (date_val and time_val)))

    manila_tz = pytz.timezone("Asia/Manila")
    now_manila = datetime.now(manila_tz)
    if not publish_now and date_val and time_val:
        try:
            scheduled_time = manila_tz.localize(datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M"))
        except Exception as e:
            return JSONResponse({"status": "error", "message": f"Invalid date/time format (expected YYYY-MM-DD and HH:MM): {e}"}, status_code=400)
    else:
        scheduled_time = now_manila + timedelta(seconds=6)

    # Download remote media if URLs are provided
    media_bytes = None
    media_filename = ""
    thumb_bytes = None
    thumb_filename = ""
    image_buffers: List[Dict[str, Any]] = []

    try:
        if post_type in ("reels", "video169") and media_url:
            r_vid = HTTP_SESSION.get(media_url, timeout=45)
            if r_vid.status_code == 200:
                media_bytes = r_vid.content
                media_filename = "n8n_video.mp4"
            if thumb_url:
                r_th = HTTP_SESSION.get(thumb_url, timeout=25)
                if r_th.status_code == 200:
                    thumb_bytes = r_th.content
                    thumb_filename = "n8n_thumb.jpg"
        elif post_type == "image" and image_urls:
            for idx, img_u in enumerate(image_urls):
                r_img = HTTP_SESSION.get(str(img_u).strip(), timeout=30)
                if r_img.status_code == 200:
                    image_buffers.append({"filename": f"n8n_image_{idx+1}.jpg", "bytes": r_img.content})
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Failed to download media URL provided by n8n: {e}"}, status_code=400)

    connected_items = refresh_connected_accounts_cache(force=False)
    explicit_acc_id = str(body.get("account_id") or body.get("page_id") or "").strip()

    queued_records = []
    for plat in platforms_list:
        matching_accs = [
            a for a in connected_items
            if str(a.get("platform") or "").lower() == plat
            and (not explicit_acc_id or str(a.get("account_id")) == explicit_acc_id)
        ]
        if not matching_accs:
            matching_accs = [{
                "platform": plat,
                "account_id": explicit_acc_id or "",
                "account_name": str(body.get("account_name") or plat.capitalize())
            }]

        for acc in matching_accs:
            record_id = f"post_{uuid.uuid4().hex[:12]}"
            page_id_val = str(acc.get("account_id") or "")
            acc_name_val = str(acc.get("account_name") or plat.capitalize())
            display_caption = (
                f"{title}\n{caption}".strip()
                if (plat == "youtube" and title and caption and title != caption)
                else (title or caption)
            )
            try:
                with db_engine.begin() as conn:
                    conn.execute(
                        text("""
                            INSERT INTO glennbot_scheduled_posts
                            (id, platform, page_id, account_name, post_type, caption, media_preview_url, scheduled_time, status, status_message)
                            VALUES (:id, :platform, :page_id, :account_name, :post_type, :caption, :preview, :sched_time, 'processing_payload', 'Queued via Internal API (n8n)')
                        """),
                        {
                            "id": record_id,
                            "platform": plat,
                            "page_id": page_id_val,
                            "account_name": acc_name_val,
                            "post_type": post_type,
                            "caption": display_caption,
                            "preview": "",
                            "sched_time": scheduled_time
                        }
                    )
            except Exception as db_e:
                print(f"[InternalAPI] Post insert warning: {db_e}")

            threading.Thread(
                target=_process_schedule_payload_background,
                args=(
                    record_id,
                    plat,
                    post_type,
                    page_id_val,
                    acc_name_val,
                    title,
                    caption,
                    scheduled_time,
                    media_bytes,
                    media_filename,
                    thumb_bytes,
                    thumb_filename,
                    image_buffers,
                    vault_media_file_id,
                    vault_thumb_file_id,
                    vault_media_file_ids
                ),
                daemon=True
            ).start()

            queued_records.append({
                "record_id": record_id,
                "platform": plat,
                "account_id": page_id_val,
                "account_name": acc_name_val,
                "post_type": post_type,
                "scheduled_for_manila": scheduled_time.strftime("%Y-%m-%d %I:%M:%S %p"),
                "publish_now": publish_now
            })

    _dispatch_outbound_n8n_webhook_async("post.scheduled", {"queued_posts": queued_records})
    return {
        "status": "success",
        "message": f"Queued {len(queued_records)} post(s) via GlennBot Internal API!",
        "queued_posts": queued_records
    }


@router.get("/api/v1/messages")
async def api_v1_get_messages(
    request: Request,
    platform: str = "all",
    account_id: str = "all",
    unread_only: bool = False,
    limit: int = 25,
    force: bool = False
):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    res = await run_in_threadpool(
        lambda: get_inbox_conversations(
            force=force,
            account_id=account_id or "all",
            platform=platform or "all",
            limit_per_page=max(5, min(limit, 100))
        )
    )
    convs = list(res.get("conversations") or [])
    if unread_only:
        convs = [c for c in convs if not c.get("is_read") or int(c.get("unread_count") or 0) > 0]
    return {
        "status": "success",
        "count": len(convs[:limit]),
        "total_unread": res.get("total_unread", 0),
        "conversations": convs[:limit]
    }


@router.post("/api/v1/messages/send")
async def api_v1_send_message(request: Request):
    """
    Sends a Direct Message reply on Facebook, Instagram, WhatsApp, or Telegram from n8n.
    JSON Body:
      - conversation_id (str, required): Conversation ID or thread ID
      - account_id (str, required): Connected Social/WhatsApp/Telegram Account ID
      - message (str, required): Message text to send
      - recipient_id (str, optional): Participant / recipient ID
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    conv_id = str(body.get("conversation_id") or "").strip()
    acc_id = str(body.get("account_id") or "").strip()
    msg_text = _sanitize_outbound_social_or_email_text(body.get("message") or body.get("text") or "")
    rcpt_id = str(body.get("recipient_id") or "").strip()
    file_id_in = str(body.get("file_id") or body.get("vault_file_id") or "").strip()
    media_url_in = str(body.get("media_url") or body.get("attachment_url") or "").strip()

    if not msg_text and (file_id_in or media_url_in):
        msg_text = "Here is the file you requested:"

    if not conv_id or not acc_id or not msg_text:
        return JSONResponse({
            "status": "error",
            "message": "'conversation_id', 'account_id', and 'message' (or 'file_id') are required."
        }, status_code=400)

    if conv_id.startswith("test_") or acc_id.startswith("test_"):
        return {
            "status": "success",
            "simulated": True,
            "conversation_id": conv_id,
            "account_id": acc_id,
            "recipient_id": rcpt_id or "test_user_01",
            "sent_message": msg_text,
            "file_id": file_id_in,
            "message": f"Test Verified! In live production, GlennBot will send DM '{msg_text}' to conversation '{conv_id}'."
        }

    payload = SendMessagePayload(
        conversation_id=conv_id,
        account_id=acc_id,
        recipient_id=rcpt_id,
        message=msg_text,
        file_id=file_id_in,
        media_url=media_url_in
    )
    trigger_wh = bool(body.get("trigger_webhook", False))
    res = await run_in_threadpool(lambda: send_direct_message_reply(payload, trigger_n8n_webhook=trigger_wh))
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.get("/api/v1/comments")
async def api_v1_get_comments(
    request: Request,
    platform: str = "",
    record_id: str = "",
    comment_id: str = "",
    unread_only: bool = False,
    limit: int = 50,
    force: bool = False
):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    res = await run_in_threadpool(lambda: get_all_comments(force=force))
    comments = list(res.get("comments") or [])
    if platform:
        p_low = platform.strip().lower()
        comments = [c for c in comments if str(c.get("platform") or "").lower() == p_low]
    if record_id:
        r_clean = record_id.strip()
        comments = [c for c in comments if str(c.get("record_id") or "") == r_clean]
    if comment_id:
        c_clean = comment_id.strip()
        comments = [
            c for c in comments
            if str(c.get("comment_id") or "") == c_clean
            or any(str(r.get("id") or "") == c_clean for r in (c.get("replies") or []))
        ]
    if unread_only:
        comments = [c for c in comments if not c.get("is_read")]
    return {
        "status": "success",
        "count": len(comments[:limit]),
        "unread_count": res.get("unread_count", 0),
        "comments": comments[:limit]
    }


def _resolve_record_id_for_comment_v1(rec_id: str, comm_id: str, post_id_in: str = "") -> str:
    resolved = str(rec_id or "").strip()
    if resolved:
        return resolved
    try:
        if not CLOUDINARY_COMMENTS_STORE.get("loaded"):
            load_comments_store_from_cloudinary()
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        for cand_rid, p_entry in posts_store.items():
            c_map = p_entry.get("comments") or {}
            if comm_id in c_map:
                return str(cand_rid)
            for k_cid, c_val in c_map.items():
                if str(k_cid) == comm_id or any(str(r.get("id")) == comm_id for r in (c_val.get("replies") or [])):
                    return str(cand_rid)
                if post_id_in and post_id_in in (str(c_val.get("zernio_post_id") or ""), str(c_val.get("external_post_id") or "")):
                    return str(cand_rid)
    except Exception:
        pass
    return ""


@router.get("/api/v1/comments/thread-status")
async def api_v1_get_comment_thread_status(
    request: Request,
    record_id: str = "",
    comment_id: str = "",
    post_id: str = "",
    author_id: str = "",
    force: bool = True
):
    """
    Checks if a commenter has replied specifically inside a comment thread (`comment_id`)
    as opposed to merely posting a separate top-level comment on the post.
    Designed to be called after an `n8n-nodes-base.wait` node (e.g., "Wait 2 minutes till he replies to your comment").
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    comm_id = str(comment_id or "").strip()
    rec_id = str(record_id or "").strip()

    if not comm_id:
        return JSONResponse({
            "status": "error",
            "message": "'comment_id' query parameter is required (e.g. ?record_id=...&comment_id=...)."
        }, status_code=400)

    # Simulated test support so "Test step" in n8n returns a realistic response
    if comm_id.startswith("test_comment_") or rec_id.startswith("test_record_"):
        return {
            "status": "success",
            "simulated": True,
            "record_id": rec_id or "test_record_fb_01",
            "comment_id": comm_id,
            "has_reply_to_comment": True,
            "replied_on_comment_thread": True,
            "replied_on_post_only": False,
            "latest_reply_id": f"{comm_id}_reply_1",
            "reply_target_comment_id": f"{comm_id}_reply_1",
            "subthread_comment_id": f"{comm_id}_own_reply_1",
            "latest_reply_message": "Your Welcome!",
            "latest_reply_author": "Juan Dela Cruz",
            "user_replies_in_thread": [
                {
                    "id": f"{comm_id}_reply_1",
                    "parent_comment_id": comm_id,
                    "replied_to_id": f"{comm_id}_own_reply_1",
                    "author_name": "Juan Dela Cruz",
                    "message": "Your Welcome!",
                    "is_own": False
                }
            ],
            "replies_count": 1
        }

    rec_id = await run_in_threadpool(lambda: _resolve_record_id_for_comment_v1(rec_id, comm_id, post_id))
    if not rec_id:
        return JSONResponse({
            "status": "error",
            "message": f"Could not resolve post record_id for comment_id '{comm_id}'."
        }, status_code=404)

    # Perform a live sync on the post if force=True inside threadpool so event loop never blocks
    if force:
        def _sync_post_for_thread_status():
            try:
                with db_engine.connect() as conn:
                    row = conn.execute(
                        text("""
                            SELECT id, platform, page_id, account_name, caption, scheduled_time,
                                   external_post_id, permalink_url, status_message
                            FROM glennbot_scheduled_posts
                            WHERE id = :id
                        """),
                        {"id": rec_id}
                    ).mappings().first()
                if row:
                    sync_single_post_to_cloudinary(dict(row), force_unhide=False)
            except Exception as e:
                print(f"[InternalAPI] thread-status live sync warning: {e}")
        await run_in_threadpool(_sync_post_for_thread_status)

    posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
    post_entry = posts_store.get(rec_id) or {}
    parent_comm, _ = find_parent_and_target_comment(post_entry, comm_id)
    target_comm = parent_comm or (post_entry.get("comments") or {}).get(comm_id) or {}
    root_cid = str(target_comm.get("comment_id") or comm_id).strip()

    orig_author_id = str(author_id or target_comm.get("author_id") or "").strip()
    orig_author_name = str(target_comm.get("author_name") or "").strip().lower()
    orig_created_iso = str(target_comm.get("created_iso") or "").strip()

    all_replies = merge_buffered_own_replies(root_cid, list(target_comm.get("replies") or []))
    # Find if our page/bot has replied in this comment thread, and check for user replies inside this thread
    own_reply_indices = [idx for idx, r in enumerate(all_replies) if isinstance(r, dict) and bool(r.get("is_own") or r.get("is_own_comment"))]
    first_own_idx = own_reply_indices[0] if own_reply_indices else -1
    latest_own_rep = next(
        (
            r for r in reversed(all_replies)
            if isinstance(r, dict)
            and bool(r.get("is_own") or r.get("is_own_comment"))
            and str(r.get("id") or "").strip()
            and not str(r.get("id") or "").strip().startswith(("local_", "z_rep_"))
        ),
        {}
    )

    user_replies_in_thread: List[Dict[str, Any]] = []
    for idx, r in enumerate(all_replies):
        if not isinstance(r, dict):
            continue
        if bool(r.get("is_own") or r.get("is_own_comment")):
            continue
        # If our page already replied in this thread, only count user replies that came AFTER our page's first reply (or if timestamps/order show it's a response in the thread)
        if first_own_idx >= 0 and idx < first_own_idx:
            continue
        r_aid = str(r.get("author_id") or "").strip()
        r_aname = str(r.get("author_name") or "").strip().lower()
        if orig_author_id and r_aid and r_aid != orig_author_id:
            if orig_author_name and r_aname and r_aname != orig_author_name:
                continue
        user_replies_in_thread.append(r)

    # Check if the same commenter mistakenly posted a NEW top-level comment on the post instead of replying to the comment thread
    top_level_other_comments_by_author: List[Dict[str, Any]] = []
    for k_cid, c_val in (post_entry.get("comments") or {}).items():
        if not isinstance(c_val, dict) or str(k_cid) == root_cid:
            continue
        if bool(c_val.get("is_own_comment") or c_val.get("is_own")):
            continue
        c_aid = str(c_val.get("author_id") or "").strip()
        c_aname = str(c_val.get("author_name") or "").strip().lower()
        same_author = False
        if orig_author_id and c_aid and c_aid == orig_author_id:
            same_author = True
        elif orig_author_name and c_aname and c_aname == orig_author_name and orig_author_name not in ("user", "facebook user", "instagram user"):
            same_author = True
        if same_author:
            c_iso = str(c_val.get("created_iso") or "").strip()
            if not orig_created_iso or not c_iso or c_iso >= orig_created_iso:
                top_level_other_comments_by_author.append(c_val)

    has_thread_reply = len(user_replies_in_thread) > 0
    latest_rep = user_replies_in_thread[-1] if has_thread_reply else {}
    latest_rep_id_str = str(latest_rep.get("id") or "").strip()
    latest_own_id_str = str(latest_own_rep.get("id") or "").strip()
    subthread_cid_str = str(latest_rep.get("replied_to_id") or latest_own_id_str or "").strip()
    reply_target_cid_str = latest_rep_id_str or latest_own_id_str or root_cid

    return {
        "status": "success",
        "record_id": rec_id,
        "comment_id": root_cid,
        "has_reply_to_comment": has_thread_reply,
        "replied_on_comment_thread": has_thread_reply,
        "replied_on_post_only": (not has_thread_reply) and (len(top_level_other_comments_by_author) > 0),
        "latest_reply_id": latest_rep_id_str,
        "reply_target_comment_id": reply_target_cid_str,
        "subthread_comment_id": subthread_cid_str,
        "latest_reply_message": str(latest_rep.get("message") or ""),
        "latest_reply_author": str(latest_rep.get("author_name") or ""),
        "user_replies_in_thread": user_replies_in_thread,
        "replies_count": len(user_replies_in_thread)
    }


@router.post("/api/v1/comments/like")
async def api_v1_like_comment(request: Request):
    """
    Likes or unlikes a specific social media comment (`comment_id`) via n8n.
    JSON Body:
      - record_id (str, optional if comment_id is in store): GlennBot post record_id
      - comment_id (str, required): Comment ID to like
      - liked (bool, optional): True to like (default), False to unlike
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    rec_id = str(body.get("record_id") or "").strip()
    post_id_in = str(body.get("post_id") or "").strip()
    comm_id = str(body.get("comment_id") or "").strip()
    liked_flag = bool(body.get("liked", True) if body.get("liked") is not None else True)

    if not comm_id:
        return JSONResponse({
            "status": "error",
            "message": "'comment_id' is required (e.g. {{ $json.body.comment_id }})."
        }, status_code=400)

    if comm_id.startswith("test_comment_") or rec_id.startswith("test_record_"):
        return {
            "status": "success",
            "simulated": True,
            "action": "like_comment" if liked_flag else "unlike_comment",
            "comment_id": comm_id,
            "record_id": rec_id or "test_record_fb_01",
            "liked": liked_flag,
            "message": f"Test Verified! In live production, GlennBot will automatically {'like' if liked_flag else 'unlike'} comment ({comm_id})."
        }

    rec_id = _resolve_record_id_for_comment_v1(rec_id, comm_id, post_id_in)
    if not rec_id:
        return JSONResponse({
            "status": "error",
            "message": f"Could not resolve post record_id for comment_id '{comm_id}'. Pass 'record_id' from the comment.received webhook payload."
        }, status_code=400)

    res = await run_in_threadpool(
        lambda: like_or_unlike_comment(CommentLikePayload(record_id=rec_id, comment_id=comm_id, liked=liked_flag))
    )
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.post("/api/v1/comments/hide")
async def api_v1_hide_comment(request: Request):
    """
    Hides or unhides a specific social media comment (`comment_id`) via n8n.
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    rec_id = str(body.get("record_id") or "").strip()
    post_id_in = str(body.get("post_id") or "").strip()
    comm_id = str(body.get("comment_id") or "").strip()
    hidden_flag = bool(body.get("hidden", True) if body.get("hidden") is not None else True)

    if not comm_id:
        return JSONResponse({
            "status": "error",
            "message": "'comment_id' is required (e.g. {{ $json.body.comment_id }})."
        }, status_code=400)

    if comm_id.startswith("test_comment_") or rec_id.startswith("test_record_"):
        return {
            "status": "success",
            "simulated": True,
            "action": "hide_comment" if hidden_flag else "unhide_comment",
            "comment_id": comm_id,
            "record_id": rec_id or "test_record_fb_01",
            "hidden": hidden_flag,
            "message": f"Test Verified! In live production, GlennBot will automatically {'hide' if hidden_flag else 'unhide'} comment ({comm_id})."
        }

    rec_id = _resolve_record_id_for_comment_v1(rec_id, comm_id, post_id_in)
    if not rec_id:
        return JSONResponse({
            "status": "error",
            "message": f"Could not resolve post record_id for comment_id '{comm_id}'."
        }, status_code=400)

    res = await run_in_threadpool(
        lambda: hide_or_unhide_comment(CommentHidePayload(record_id=rec_id, comment_id=comm_id, hidden=hidden_flag))
    )
    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.post("/api/v1/comments/reply")
@router.post("/api/v1/comments/send-dm")
async def api_v1_reply_to_comment(request: Request):
    """
    Replies to a social media post comment or sends a Private DM to a commenter from n8n.
    JSON Body:
      - record_id (str, optional if comment_id or post_id is provided): GlennBot post record_id
      - post_id (str, optional): Platform post ID or Zernio post ID
      - comment_id (str, required): Comment ID to reply to or send Private DM to
      - message (str, optional): Reply / DM text (defaults to "Thank you for your comment here is our offers")
      - send_dm (bool, optional): If True (or if called via /api/v1/comments/send-dm), sends a Private Reply DM to the commenter
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    rec_id = str(body.get("record_id") or "").strip()
    post_id_in = str(body.get("post_id") or "").strip()
    comm_id = str(body.get("comment_id") or "").strip()
    file_id_in = str(body.get("file_id") or body.get("vault_file_id") or "").strip()
    media_url_in = str(body.get("media_url") or body.get("attachment_url") or "").strip()
    default_msg = "Here is the file you requested:" if (file_id_in or media_url_in) else "Thank you for your comment here is our offers"
    msg_text = _sanitize_outbound_social_or_email_text(body.get("message") or body.get("text") or default_msg) or default_msg
    is_send_dm_route = str(request.url.path or "").endswith("/send-dm")
    send_dm = True if is_send_dm_route else bool(body.get("send_dm", False))

    if not comm_id:
        ai_topic = str(body.get("topic") or body.get("prompt") or body.get("question") or body.get("query") or "").strip()
        if ai_topic:
            return await run_in_threadpool(
                lambda: _execute_glennbot_ask_ai_core(
                    user_topic=ai_topic,
                    tone_str=str(body.get("tone") or "Polite, friendly and professional").strip(),
                    lang_str=str(body.get("language") or "Taglish").strip(),
                    post_type_str="comment_reply",
                    platforms_list=body.get("platforms") if isinstance(body.get("platforms"), list) else ["facebook", "instagram"],
                    force_reply_mode=True,
                    use_search=bool(body.get("use_search", True))
                )
            )
        return JSONResponse({
            "status": "error",
            "message": "'comment_id' is required (e.g. {{ $json.body.comment_id }})."
        }, status_code=400)

    # Gracefully handle simulated n8n test comments so "Test step" in n8n returns 200 OK
    if comm_id.startswith("test_comment_") or rec_id.startswith("test_record_"):
        return {
            "status": "success",
            "simulated": True,
            "action": "private_dm_to_commenter" if send_dm else "public_comment_reply",
            "comment_id": comm_id,
            "record_id": rec_id or "test_record_fb_01",
            "file_id": file_id_in,
            "media_url": media_url_in,
            "sent_message": msg_text,
            "message": f"Test Verified! In live production, GlennBot will automatically send {'Private DM' if send_dm else 'Public Reply'}: '{msg_text}'{' with Vault File (' + file_id_in + ')' if file_id_in else ''} to commenter ({comm_id})."
        }

    # Auto-resolve record_id and execute reply / DM inside worker threadpool so event loop never blocks!
    def _execute_v1_comment_reply_or_dm():
        resolved_rid = _resolve_record_id_for_comment_v1(rec_id, comm_id, post_id_in)
        if not resolved_rid:
            return None
        if send_dm:
            return send_dm_to_commenter(CommentSendDmPayload(record_id=resolved_rid, comment_id=comm_id, message=msg_text, file_id=file_id_in, media_url=media_url_in))
        return reply_to_comment(CommentReplyPayload(record_id=resolved_rid, comment_id=comm_id, message=msg_text, file_id=file_id_in, media_url=media_url_in))

    res = await run_in_threadpool(_execute_v1_comment_reply_or_dm)
    if res is None:
        return JSONResponse({
            "status": "error",
            "message": f"Could not resolve post record_id for comment_id '{comm_id}'. Pass 'record_id' from the comment.received webhook payload."
        }, status_code=400)

    if res.get("status") == "success":
        return res
    return JSONResponse(res, status_code=400)


@router.get("/api/v1/emails")
async def api_v1_get_emails(
    request: Request,
    account_id: str = "",
    email_address: str = "",
    folder: str = "inbox",
    search: str = "",
    limit: int = 25,
    force: bool = False
):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    def _fetch_v1_emails_sync():
        _load_email_hub_state(force_cloud=False)
        accounts = EMAIL_HUB_STATE.get("accounts") or []
        if not accounts:
            accounts = _discover_composio_email_accounts()

        target_acc_id = str(account_id or "").strip()
        if not target_acc_id and email_address:
            em_low = email_address.strip().lower()
            matched = next((a for a in accounts if str(a.get("email_address") or "").lower() == em_low), None)
            if matched:
                target_acc_id = str(matched.get("id") or "")
        if not target_acc_id and accounts:
            target_acc_id = str(accounts[0].get("id") or "")

        if not target_acc_id:
            return JSONResponse({"status": "error", "message": "No connected email accounts found."}, status_code=404)

        return api_get_single_account_emails(
            account_id=target_acc_id,
            folder=folder,
            q=search,
            page_token="",
            max_results=limit,
            force=force
        )

    return await run_in_threadpool(_fetch_v1_emails_sync)


@router.post("/api/v1/emails/send")
async def api_v1_send_email(request: Request):
    """
    Sends a new email or replies to an existing email thread via n8n.
    JSON Body:
      - account_id (str, optional) or from_email (str, optional): Connected email account (uses primary account if omitted)
      - to (str or list of str, required): Recipient email address(es)
      - cc (str or list of str, optional): CC email address(es)
      - subject (str, required): Email subject line
      - body (str, required): Email body content
      - thread_id (str, optional): If provided, replies to this email thread
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    def _get_v1_email_accounts():
        _load_email_hub_state(force_cloud=False)
        accs = EMAIL_HUB_STATE.get("accounts") or []
        if not accs:
            accs = _discover_composio_email_accounts()
        return accs

    accounts = await run_in_threadpool(_get_v1_email_accounts)

    acc_id = str(body.get("account_id") or "").strip()
    from_em = str(
        body.get("from_email")
        or body.get("sender_email")
        or body.get("organizer_email")
        or body.get("account_email")
        or body.get("receiving_email")
        or ""
    ).strip().lower()
    raw_to_in = (
        body.get("to")
        or body.get("recipient_email")
        or body.get("primary_guest_email")
        or body.get("attendee_email")
        or body.get("guest_email")
        or ""
    )
    if isinstance(raw_to_in, list):
        raw_to = ", ".join(str(x).strip() for x in raw_to_in if str(x).strip())
    else:
        raw_to = str(raw_to_in or "").strip()
    body["to"] = raw_to
    msg_id_in = str(body.get("message_id") or "").strip()
    thread_id_in = str(body.get("thread_id") or "").strip()
    subj_in = str(body.get("subject") or "Re: INQUIRY").strip()
    body_text = _sanitize_outbound_social_or_email_text(body.get("body") or body.get("message") or body.get("text") or "Thank you for sending me a message") or "Thank you for sending me a message"
    body["body"] = body_text
    body["subject"] = subj_in

    # Merge any top-level file_id / attachment_file_id / file_ids (e.g. "file_3f5f4508e3d1") into body["attachments"]
    merged_attachments = _normalize_raw_attachments_with_file_ids(body)
    if merged_attachments:
        body["attachments"] = merged_attachments
    attached_file_ids = [
        str(att.get("file_id")).strip()
        for att in merged_attachments
        if isinstance(att, dict) and att.get("file_id")
    ]

    # Optional subject filter safeguard if passed by n8n
    req_kw = str(body.get("only_if_subject_contains") or "").strip().lower()
    orig_subj = str(body.get("original_subject") or subj_in).strip().lower()
    if req_kw and req_kw not in orig_subj:
        return {
            "status": "skipped",
            "reason": f"Email subject '{orig_subj}' does not contain '{req_kw}'.",
            "action": "no_reply_sent"
        }

    # Optional message body filter safeguard if passed by n8n (e.g. "Please send me a picture")
    req_body_kw = str(body.get("only_if_body_contains") or body.get("only_if_message_contains") or "").strip().lower()
    orig_body_in = str(body.get("original_body") or body.get("original_message") or body.get("incoming_body") or "").strip().lower()
    if req_body_kw and orig_body_in and req_body_kw not in orig_body_in:
        return {
            "status": "skipped",
            "reason": f"Email message body does not contain '{req_body_kw}'.",
            "action": "no_reply_sent"
        }

    # Resolve the exact connected email account in the dashboard that received the email
    matched_acc = None
    if acc_id:
        matched_acc = next(
            (
                a for a in accounts
                if str(a.get("id") or "") == acc_id
                or str(a.get("composio_connection_id") or "") == acc_id
                or str(a.get("email_address") or "").lower() == acc_id.lower()
            ),
            None
        )
    if not matched_acc and from_em:
        matched_acc = next(
            (a for a in accounts if str(a.get("email_address") or "").lower() == from_em),
            None
        )
    if not matched_acc and accounts:
        matched_acc = accounts[0]

    if matched_acc:
        acc_id = str(matched_acc.get("id") or "")
        from_em = str(matched_acc.get("email_address") or from_em)

    # Gracefully handle simulated n8n test email events so "Test step" in n8n returns 200 OK
    if (
        msg_id_in.startswith("test_msg_")
        or msg_id_in.startswith("test_email_")
        or thread_id_in.startswith("test_thread_")
        or "@example.com" in raw_to.lower()
        or bool(body.get("simulated_test"))
    ):
        att_info = f" with Google Drive Vault attachment {attached_file_ids}" if attached_file_ids else ""
        return {
            "status": "success",
            "simulated": True,
            "action": "email_auto_reply_with_vault_attachment" if attached_file_ids else "gmail_auto_reply",
            "account_id": acc_id,
            "from_email": from_em or "connected_dashboard_email@gmail.com",
            "to": raw_to or "test.sender@example.com",
            "subject": subj_in if subj_in.lower().startswith("re:") else f"Re: {subj_in}",
            "sent_body": body_text,
            "attached_file_ids": attached_file_ids,
            "message": f"Test Verified! In live production, receiving account '{from_em or 'connected_dashboard_email'}' will automatically reply '{body_text}'{att_info} to '{raw_to}'."
        }

    if not acc_id:
        return JSONResponse({"status": "error", "message": "No connected email account found to send from."}, status_code=404)

    body["account_id"] = acc_id

    class _ProxyReq:
        async def json(self_inner):
            return body

    if body.get("thread_id") or body.get("message_id"):
        return await api_reply_single_account_email(_ProxyReq())
    return await api_send_single_account_email(_ProxyReq())


@router.get("/api/v1/contacts")
async def api_v1_get_contacts(
    request: Request,
    search: str = "",
    platform: str = "",
    category: str = "",
    limit: int = 100,
    refresh: bool = False
):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    res = await run_in_threadpool(lambda: api_get_crm_contacts(refresh=refresh))
    contacts = list(res.get("contacts") or [])
    if platform:
        p_low = platform.strip().lower()
        contacts = [c for c in contacts if p_low in str(c.get("platform") or "").lower()]
    if category:
        cat_low = category.strip().lower()
        contacts = [c for c in contacts if str(c.get("category") or "").lower() == cat_low]
    if search:
        q_low = search.strip().lower()
        contacts = [
            c for c in contacts
            if q_low in f"{c.get('first_name','')} {c.get('last_name','')} {c.get('email_address','')} {c.get('contact_number','')} {c.get('social_username','')} {c.get('company','')}".lower()
        ]
    return {
        "status": "success",
        "count": len(contacts[:limit]),
        "total_contacts": len(res.get("contacts") or []),
        "contacts": contacts[:max(1, min(limit, 500))]
    }


@router.post("/api/v1/contacts")
async def api_v1_upsert_contact(request: Request):
    """
    Creates or updates/combines a CRM Contact from n8n (automatically deduplicating by phone/email).
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await api_create_or_update_crm_contact(request)


@router.post("/api/v1/contacts/sync")
async def api_v1_sync_contacts(request: Request):
    """
    Triggers full CRM Contact Sync & Deduplication across Cloudinary, WhatsApp, Telegram, and Social Inbox from n8n.
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await run_in_threadpool(api_sync_all_crm_contacts)


