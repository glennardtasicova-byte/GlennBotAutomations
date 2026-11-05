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
import math
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
# --- "SPREAD SHEET" MODAL: CUSTOM A,B,C,D x 1,2,3,4 SPREADSHEET (.XLSX / .XLS) ---
# --- SAVES TO GOOGLE DRIVE + FILES VAULT (WITH FILE_ID) & TWO-WAY AUTO-SYNCS ---
# ==============================================================================
CLOUDINARY_SPREADSHEETS_STORE_PUBLIC_ID = "glennbot_config/spreadsheets_store_v1.json"
LOCAL_SPREADSHEETS_CACHE_PATH = os.path.join(BASE_DIR, "spreadsheets_store_cache.json")
SPREADSHEETS_LOCK = threading.Lock()
SPREADSHEETS_SYNC_LOCK = threading.Lock()
SPREADSHEETS_STORE: Dict[str, Any] = {
    "loaded": False,
    "last_gdrive_sync_ts": 0.0,
    "workbooks": []
}

XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME_TYPE = "application/vnd.ms-excel"
GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


def _is_spreadsheet_filename_or_mime(filename: str, mime_type: str = "") -> bool:
    lower_f = str(filename or "").strip().lower()
    lower_m = str(mime_type or "").strip().lower()
    if lower_f.endswith((".xlsx", ".xls")):
        return True
    if lower_m in (
        XLSX_MIME_TYPE,
        XLS_MIME_TYPE,
        GOOGLE_SHEETS_MIME_TYPE,
        "application/excel",
        "application/x-excel",
        "application/x-msexcel"
    ):
        return True
    return False


def _col_idx_to_letter(index: int) -> str:
    idx = max(0, int(index)) + 1
    letters = ""
    while idx > 0:
        rem = (idx - 1) % 26
        letters = chr(65 + rem) + letters
        idx = (idx - 1) // 26
    return letters or "A"


def _letter_to_col_idx(col_str: str) -> int:
    clean = re.sub(r"[^A-Za-z]", "", str(col_str or "")).upper()
    if not clean:
        return 0
    res = 0
    for ch in clean:
        res = res * 26 + (ord(ch) - 64)
    return max(0, res - 1)


def _split_cell_coord(coord: str):
    m = re.match(r"^([A-Za-z]+)(\d+)$", str(coord or "").strip())
    if not m:
        return None
    col_l = m.group(1).upper()
    row_n = int(m.group(2))
    if row_n < 1:
        return None
    return col_l, _letter_to_col_idx(col_l), row_n


def _sanitize_excel_sheet_name(name: str, fallback: str = "Sheet1") -> str:
    cleaned = re.sub(r"[\\/?*:\[\]]", "", str(name or "")).strip()[:31]
    return cleaned or fallback


_BLOCKED_IMAGE_FORMULA_NAMES = {
    "IMAGE", "SPARKLINE", "IMPORTIMAGE", "EMBEDIMAGE", "WEBIMAGE", "PICTURE"
}


def _split_top_level_formula_args(args_str: str) -> List[str]:
    args: List[str] = []
    cur: List[str] = []
    depth = 0
    in_quotes = False
    i = 0
    while i < len(args_str):
        ch = args_str[i]
        if ch == '"':
            if in_quotes and i + 1 < len(args_str) and args_str[i + 1] == '"':
                cur.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
            cur.append(ch)
        elif not in_quotes:
            if ch == '(':
                depth += 1
                cur.append(ch)
            elif ch == ')':
                depth = max(0, depth - 1)
                cur.append(ch)
            elif ch in (',', ';') and depth == 0:
                args.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        else:
            cur.append(ch)
        i += 1
    if cur or args_str.strip().endswith((',', ';')):
        args.append("".join(cur).strip())
    return args


def _format_formula_number(val: float) -> str:
    if not math.isfinite(val):
        return "#NUM!"
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    rounded = round(val, 6)
    s = f"{rounded:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _matches_excel_criteria(cell_val: Any, criteria_raw: Any) -> bool:
    crit_str = str(criteria_raw if criteria_raw is not None else "").strip()
    if len(crit_str) >= 2 and crit_str.startswith('"') and crit_str.endswith('"'):
        crit_str = crit_str[1:-1]
    c_str = str(cell_val if cell_val is not None else "").strip()

    op = "="
    rhs = crit_str
    for prefix in ("<>", ">=", "<=", ">", "<", "="):
        if crit_str.startswith(prefix):
            op = prefix
            rhs = crit_str[len(prefix):].strip()
            break

    try:
        lhs_num = float(c_str.replace(",", "")) if c_str != "" else None
        rhs_num = float(rhs.replace(",", "")) if rhs != "" else None
    except Exception:
        lhs_num = None
        rhs_num = None

    if lhs_num is not None and rhs_num is not None:
        if op == "=":
            return abs(lhs_num - rhs_num) < 1e-9
        if op == "<>":
            return abs(lhs_num - rhs_num) >= 1e-9
        if op == ">":
            return lhs_num > rhs_num
        if op == "<":
            return lhs_num < rhs_num
        if op == ">=":
            return lhs_num >= rhs_num
        if op == "<=":
            return lhs_num <= rhs_num

    lhs_l = c_str.lower()
    rhs_l = rhs.lower()
    if op in ("=", "<>") and ("*" in rhs_l or "?" in rhs_l):
        pat = "^" + re.escape(rhs_l).replace(r"\*", ".*").replace(r"\?", ".") + "$"
        matched = bool(re.match(pat, lhs_l))
        return matched if op == "=" else (not matched)

    if op == "=":
        return lhs_l == rhs_l
    if op == "<>":
        return lhs_l != rhs_l
    if op == ">":
        return lhs_l > rhs_l
    if op == "<":
        return lhs_l < rhs_l
    if op == ">=":
        return lhs_l >= rhs_l
    if op == "<=":
        return lhs_l <= rhs_l
    return False


def _evaluate_spreadsheet_formula(raw_val: str, cells_map: Dict[str, str], depth: int = 0) -> str:
    s = str(raw_val if raw_val is not None else "")
    if not s.startswith("="):
        return s
    if depth > 8:
        return "#REF!"
    expr = s[1:].strip()
    if not expr:
        return ""

    # Strictly block any image-related spreadsheet formulas
    for fn_match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*\(", expr):
        fn_candidate = fn_match.group(1).upper()
        if fn_candidate in _BLOCKED_IMAGE_FORMULA_NAMES or "IMAGE" in fn_candidate:
            return "#IMAGE_FORMULA_NOT_ALLOWED!"

    def _get_cell_eval(coord_str: str) -> str:
        clean_c = str(coord_str or "").replace("$", "").strip().upper()
        raw_c = cells_map.get(clean_c, "")
        return _evaluate_spreadsheet_formula(raw_c, cells_map, depth + 1)

    def _to_float(v: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        s_v = str(v if v is not None else "").strip()
        if s_v.upper() == "TRUE":
            return 1.0
        if s_v.upper() == "FALSE":
            return 0.0
        if not s_v:
            return default
        clean_n = re.sub(r"[$₱€£¥,\s]", "", s_v)
        if clean_n.endswith("%"):
            try:
                return float(clean_n[:-1]) / 100.0
            except Exception:
                return default
        try:
            return float(clean_n)
        except Exception:
            return default

    def _to_bool(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        s_v = str(v if v is not None else "").strip().upper()
        if s_v in ("TRUE", "1", "YES"):
            return True
        if s_v in ("FALSE", "0", "", "NO"):
            return False
        n_v = _to_float(s_v, None)
        return bool(n_v) if n_v is not None else True

    def _expand_range_coords(range_str: str) -> List[List[str]]:
        clean_r = str(range_str or "").replace("$", "").strip()
        parts = clean_r.split(":")
        if len(parts) != 2:
            return []
        s_c = _split_cell_coord(parts[0])
        e_c = _split_cell_coord(parts[1])
        if not s_c or not e_c:
            return []
        c_min, c_max = min(s_c[1], e_c[1]), max(s_c[1], e_c[1])
        r_min, r_max = min(s_c[2], e_c[2]), max(s_c[2], e_c[2])
        matrix: List[List[str]] = []
        for r_i in range(r_min, r_max + 1):
            row_list: List[str] = []
            for c_i in range(c_min, c_max + 1):
                row_list.append(f"{_col_idx_to_letter(c_i)}{r_i}")
            matrix.append(row_list)
        return matrix

    def _expand_arg_values(arg_expr: str) -> List[str]:
        a_clean = arg_expr.strip()
        if re.match(r"^\$?[A-Za-z]+\$?\d+:\$?[A-Za-z]+\$?\d+$", a_clean):
            mat = _expand_range_coords(a_clean)
            return [_get_cell_eval(c) for row in mat for c in row]
        return [str(_eval_expr(a_clean))]

    def _expand_arg_numbers(arg_expr: str) -> List[float]:
        a_clean = arg_expr.strip()
        if re.match(r"^\$?[A-Za-z]+\$?\d+:\$?[A-Za-z]+\$?\d+$", a_clean):
            mat = _expand_range_coords(a_clean)
            nums: List[float] = []
            for row in mat:
                for c in row:
                    raw_cell = str(cells_map.get(c, "")).strip()
                    if not raw_cell:
                        continue
                    v = _get_cell_eval(c)
                    fv = _to_float(v, None)
                    if fv is not None:
                        nums.append(fv)
            return nums
        if re.match(r"^\$?[A-Za-z]+\$?\d+$", a_clean):
            v = _get_cell_eval(a_clean)
            fv = _to_float(v, None)
            return [fv] if fv is not None else []
        v = _eval_expr(a_clean)
        fv = _to_float(v, None)
        return [fv] if fv is not None else []

    def _eval_function(fn_name: str, raw_args: List[str]) -> Any:
        fn = re.sub(r"^_XLFN\.", "", fn_name.upper())
        if fn in _BLOCKED_IMAGE_FORMULA_NAMES or "IMAGE" in fn:
            return "#IMAGE_FORMULA_NOT_ALLOWED!"

        # --- LOGICAL FUNCTIONS ---
        if fn == "TRUE":
            return "TRUE"
        if fn == "FALSE":
            return "FALSE"
        if fn == "IF":
            if not raw_args:
                return "#VALUE!"
            cond = _to_bool(_eval_expr(raw_args[0]))
            if cond:
                return _eval_expr(raw_args[1]) if len(raw_args) > 1 else "TRUE"
            return _eval_expr(raw_args[2]) if len(raw_args) > 2 else "FALSE"
        if fn == "IFS":
            for idx in range(0, len(raw_args) - 1, 2):
                if _to_bool(_eval_expr(raw_args[idx])):
                    return _eval_expr(raw_args[idx + 1])
            return "#N/A"
        if fn == "IFERROR":
            if not raw_args:
                return ""
            val = str(_eval_expr(raw_args[0]))
            if val.startswith("#"):
                return _eval_expr(raw_args[1]) if len(raw_args) > 1 else ""
            return val
        if fn == "IFNA":
            if not raw_args:
                return ""
            val = str(_eval_expr(raw_args[0]))
            if val == "#N/A":
                return _eval_expr(raw_args[1]) if len(raw_args) > 1 else ""
            return val
        if fn == "AND":
            vals = [v for a in raw_args for v in _expand_arg_values(a) if str(v).strip() != ""]
            return "TRUE" if (vals and all(_to_bool(v) for v in vals)) else "FALSE"
        if fn == "OR":
            vals = [v for a in raw_args for v in _expand_arg_values(a) if str(v).strip() != ""]
            return "TRUE" if any(_to_bool(v) for v in vals) else "FALSE"
        if fn == "XOR":
            vals = [v for a in raw_args for v in _expand_arg_values(a) if str(v).strip() != ""]
            trues = sum(1 for v in vals if _to_bool(v))
            return "TRUE" if (trues % 2 == 1) else "FALSE"
        if fn == "NOT":
            return "FALSE" if (raw_args and _to_bool(_eval_expr(raw_args[0]))) else "TRUE"
        if fn == "SWITCH":
            if len(raw_args) < 3:
                return "#VALUE!"
            target = str(_eval_expr(raw_args[0])).strip().lower()
            idx = 1
            while idx + 1 < len(raw_args):
                if str(_eval_expr(raw_args[idx])).strip().lower() == target:
                    return _eval_expr(raw_args[idx + 1])
                idx += 2
            return _eval_expr(raw_args[-1]) if (len(raw_args) % 2 == 0) else "#N/A"

        # --- AGGREGATE & STATISTICAL FUNCTIONS ---
        if fn in ("SUM", "AVERAGE", "AVG", "MIN", "MAX", "COUNT", "COUNTA", "COUNTBLANK", "MEDIAN", "MODE", "STDEV", "STDEV.S", "STDEVP", "STDEV.P", "VAR", "VAR.S", "VARP", "VAR.P", "PRODUCT"):
            if fn == "COUNTA":
                cnt = 0
                for a in raw_args:
                    for v in _expand_arg_values(a):
                        if str(v).strip() != "":
                            cnt += 1
                return str(cnt)
            if fn == "COUNTBLANK":
                cnt = 0
                for a in raw_args:
                    for v in _expand_arg_values(a):
                        if str(v).strip() == "":
                            cnt += 1
                return str(cnt)
            nums = [n for a in raw_args for n in _expand_arg_numbers(a)]
            if fn == "COUNT":
                return str(len(nums))
            if fn == "SUM":
                return _format_formula_number(sum(nums))
            if fn == "PRODUCT":
                if not nums:
                    return "0"
                prod = 1.0
                for n in nums:
                    prod *= n
                return _format_formula_number(prod)
            if not nums:
                return "#DIV/0!" if fn in ("AVERAGE", "AVG") else "0"
            if fn in ("AVERAGE", "AVG"):
                return _format_formula_number(sum(nums) / len(nums))
            if fn == "MIN":
                return _format_formula_number(min(nums))
            if fn == "MAX":
                return _format_formula_number(max(nums))
            if fn == "MEDIAN":
                s_nums = sorted(nums)
                mid = len(s_nums) // 2
                med = s_nums[mid] if len(s_nums) % 2 == 1 else (s_nums[mid - 1] + s_nums[mid]) / 2.0
                return _format_formula_number(med)
            if fn == "MODE":
                counts: Dict[float, int] = {}
                for n in nums:
                    counts[n] = counts.get(n, 0) + 1
                best = max(counts.items(), key=lambda x: x[1])[0]
                return _format_formula_number(best)
            if fn in ("VAR", "VAR.S", "STDEV", "STDEV.S"):
                if len(nums) < 2:
                    return "#DIV/0!"
                mean = sum(nums) / len(nums)
                var_s = sum((x - mean) ** 2 for x in nums) / (len(nums) - 1)
                return _format_formula_number(math.sqrt(var_s) if "STDEV" in fn else var_s)
            if fn in ("VARP", "VAR.P", "STDEVP", "STDEV.P"):
                mean = sum(nums) / len(nums)
                var_p = sum((x - mean) ** 2 for x in nums) / len(nums)
                return _format_formula_number(math.sqrt(var_p) if "STDEV" in fn else var_p)

        if fn in ("LARGE", "SMALL"):
            if len(raw_args) < 2:
                return "#VALUE!"
            nums = sorted(_expand_arg_numbers(raw_args[0]), reverse=(fn == "LARGE"))
            k = int(_to_float(_eval_expr(raw_args[1]), 1) or 1)
            if k < 1 or k > len(nums):
                return "#NUM!"
            return _format_formula_number(nums[k - 1])

        if fn == "SUMPRODUCT":
            if not raw_args:
                return "0"
            arrays = [[_to_float(v, 0.0) or 0.0 for v in _expand_arg_values(a)] for a in raw_args]
            min_len = min((len(arr) for arr in arrays), default=0)
            total = 0.0
            for idx in range(min_len):
                p = 1.0
                for arr in arrays:
                    p *= arr[idx]
                total += p
            return _format_formula_number(total)

        # --- CONDITIONAL AGGREGATES (COUNTIF, SUMIF, AVERAGEIF, *IFS) ---
        if fn in ("COUNTIF", "SUMIF", "AVERAGEIF"):
            if len(raw_args) < 2:
                return "#VALUE!"
            crit_coords = [c for row in _expand_range_coords(raw_args[0]) for c in row]
            crit_val = _eval_expr(raw_args[1])
            val_coords = [c for row in _expand_range_coords(raw_args[2]) for c in row] if len(raw_args) > 2 else crit_coords
            matched_nums: List[float] = []
            matched_count = 0
            for idx, c_coord in enumerate(crit_coords):
                c_eval = _get_cell_eval(c_coord)
                if _matches_excel_criteria(c_eval, crit_val):
                    matched_count += 1
                    if idx < len(val_coords):
                        fv = _to_float(_get_cell_eval(val_coords[idx]), None)
                        if fv is not None:
                            matched_nums.append(fv)
            if fn == "COUNTIF":
                return str(matched_count)
            if fn == "SUMIF":
                return _format_formula_number(sum(matched_nums))
            if not matched_nums:
                return "#DIV/0!"
            return _format_formula_number(sum(matched_nums) / len(matched_nums))

        if fn in ("COUNTIFS", "SUMIFS", "AVERAGEIFS", "MINIFS", "MAXIFS"):
            if fn == "COUNTIFS":
                if len(raw_args) < 2 or len(raw_args) % 2 != 0:
                    return "#VALUE!"
                first_coords = [c for row in _expand_range_coords(raw_args[0]) for c in row]
                pairs = []
                for idx in range(0, len(raw_args), 2):
                    r_coords = [c for row in _expand_range_coords(raw_args[idx]) for c in row]
                    c_val = _eval_expr(raw_args[idx + 1])
                    pairs.append((r_coords, c_val))
                cnt = 0
                for i in range(len(first_coords)):
                    if all(i < len(rc) and _matches_excel_criteria(_get_cell_eval(rc[i]), cv) for rc, cv in pairs):
                        cnt += 1
                return str(cnt)
            else:
                if len(raw_args) < 3 or len(raw_args) % 2 == 0:
                    return "#VALUE!"
                target_coords = [c for row in _expand_range_coords(raw_args[0]) for c in row]
                pairs = []
                for idx in range(1, len(raw_args), 2):
                    r_coords = [c for row in _expand_range_coords(raw_args[idx]) for c in row]
                    c_val = _eval_expr(raw_args[idx + 1])
                    pairs.append((r_coords, c_val))
                matched_nums = []
                for i, t_coord in enumerate(target_coords):
                    if all(i < len(rc) and _matches_excel_criteria(_get_cell_eval(rc[i]), cv) for rc, cv in pairs):
                        fv = _to_float(_get_cell_eval(t_coord), None)
                        if fv is not None:
                            matched_nums.append(fv)
                if fn == "SUMIFS":
                    return _format_formula_number(sum(matched_nums))
                if fn == "AVERAGEIFS":
                    return _format_formula_number(sum(matched_nums) / len(matched_nums)) if matched_nums else "#DIV/0!"
                if fn == "MINIFS":
                    return _format_formula_number(min(matched_nums)) if matched_nums else "0"
                if fn == "MAXIFS":
                    return _format_formula_number(max(matched_nums)) if matched_nums else "0"

        # --- MATH & TRIG FUNCTIONS ---
        if fn == "ABS":
            return _format_formula_number(abs(_to_float(_eval_expr(raw_args[0]), 0.0) or 0.0)) if raw_args else "0"
        if fn == "ROUND":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            d = int(_to_float(_eval_expr(raw_args[1]), 0.0) or 0) if len(raw_args) > 1 else 0
            return _format_formula_number(round(n, d))
        if fn == "ROUNDUP":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            d = int(_to_float(_eval_expr(raw_args[1]), 0.0) or 0) if len(raw_args) > 1 else 0
            factor = 10 ** d
            res = (math.ceil(n * factor) if n >= 0 else math.floor(n * factor)) / factor
            return _format_formula_number(res)
        if fn in ("ROUNDDOWN", "TRUNC"):
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            d = int(_to_float(_eval_expr(raw_args[1]), 0.0) or 0) if len(raw_args) > 1 else 0
            factor = 10 ** d
            res = math.trunc(n * factor) / factor
            return _format_formula_number(res)
        if fn == "INT":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            return _format_formula_number(math.floor(n))
        if fn == "MOD":
            if len(raw_args) < 2:
                return "#VALUE!"
            a = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            b = _to_float(_eval_expr(raw_args[1]), 0.0) or 0.0
            if b == 0:
                return "#DIV/0!"
            return _format_formula_number(a % b)
        if fn in ("POWER", "POW"):
            if len(raw_args) < 2:
                return "#VALUE!"
            a = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            b = _to_float(_eval_expr(raw_args[1]), 0.0) or 0.0
            return _format_formula_number(math.pow(a, b))
        if fn == "SQRT":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            return _format_formula_number(math.sqrt(n)) if n >= 0 else "#NUM!"
        if fn == "EXP":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            return _format_formula_number(math.exp(n))
        if fn == "LN":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            return _format_formula_number(math.log(n)) if n > 0 else "#NUM!"
        if fn == "LOG10":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            return _format_formula_number(math.log10(n)) if n > 0 else "#NUM!"
        if fn == "LOG":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            base = _to_float(_eval_expr(raw_args[1]), 10.0) if len(raw_args) > 1 else 10.0
            return _format_formula_number(math.log(n, base or 10.0)) if (n > 0 and (base or 10.0) > 0) else "#NUM!"
        if fn == "PI":
            return _format_formula_number(math.pi)
        if fn == "SIGN":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            return "1" if n > 0 else ("-1" if n < 0 else "0")
        if fn == "SIN":
            return _format_formula_number(math.sin(_to_float(_eval_expr(raw_args[0]), 0.0) or 0.0))
        if fn == "COS":
            return _format_formula_number(math.cos(_to_float(_eval_expr(raw_args[0]), 0.0) or 0.0))
        if fn == "TAN":
            return _format_formula_number(math.tan(_to_float(_eval_expr(raw_args[0]), 0.0) or 0.0))
        if fn == "RADIANS":
            return _format_formula_number(math.radians(_to_float(_eval_expr(raw_args[0]), 0.0) or 0.0))
        if fn == "DEGREES":
            return _format_formula_number(math.degrees(_to_float(_eval_expr(raw_args[0]), 0.0) or 0.0))
        if fn == "FACT":
            n = int(_to_float(_eval_expr(raw_args[0]), 0.0) or 0)
            return str(math.factorial(n)) if 0 <= n <= 170 else "#NUM!"
        if fn in ("CEILING", "CEIL"):
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            sig = _to_float(_eval_expr(raw_args[1]), 1.0) if len(raw_args) > 1 else 1.0
            if not sig:
                return "0"
            return _format_formula_number(math.ceil(n / sig) * sig)
        if fn == "FLOOR":
            n = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            sig = _to_float(_eval_expr(raw_args[1]), 1.0) if len(raw_args) > 1 else 1.0
            if not sig:
                return "0"
            return _format_formula_number(math.floor(n / sig) * sig)

        # --- LOOKUP & REFERENCE FUNCTIONS ---
        if fn == "VLOOKUP":
            if len(raw_args) < 3:
                return "#VALUE!"
            lookup_val = str(_eval_expr(raw_args[0])).strip()
            mat = _expand_range_coords(raw_args[1])
            col_idx = int(_to_float(_eval_expr(raw_args[2]), 1) or 1)
            if not mat or col_idx < 1 or col_idx > len(mat[0]):
                return "#REF!"
            for row in mat:
                cell_v = _get_cell_eval(row[0]).strip()
                if _matches_excel_criteria(cell_v, lookup_val):
                    return _get_cell_eval(row[col_idx - 1])
            return "#N/A"

        if fn == "HLOOKUP":
            if len(raw_args) < 3:
                return "#VALUE!"
            lookup_val = str(_eval_expr(raw_args[0])).strip()
            mat = _expand_range_coords(raw_args[1])
            row_idx = int(_to_float(_eval_expr(raw_args[2]), 1) or 1)
            if not mat or row_idx < 1 or row_idx > len(mat):
                return "#REF!"
            first_row = mat[0]
            for c_i, coord in enumerate(first_row):
                if _matches_excel_criteria(_get_cell_eval(coord).strip(), lookup_val):
                    return _get_cell_eval(mat[row_idx - 1][c_i])
            return "#N/A"

        if fn == "XLOOKUP":
            if len(raw_args) < 3:
                return "#VALUE!"
            lookup_val = str(_eval_expr(raw_args[0])).strip()
            lookup_coords = [c for row in _expand_range_coords(raw_args[1]) for c in row]
            return_coords = [c for row in _expand_range_coords(raw_args[2]) for c in row]
            not_found = _eval_expr(raw_args[3]) if len(raw_args) > 3 else "#N/A"
            for i, lc in enumerate(lookup_coords):
                if _matches_excel_criteria(_get_cell_eval(lc).strip(), lookup_val):
                    return _get_cell_eval(return_coords[i]) if i < len(return_coords) else "#REF!"
            return not_found

        if fn == "INDEX":
            if len(raw_args) < 2:
                return "#VALUE!"
            mat = _expand_range_coords(raw_args[0])
            if not mat:
                return "#REF!"
            r_num = int(_to_float(_eval_expr(raw_args[1]), 1) or 1)
            c_num = int(_to_float(_eval_expr(raw_args[2]), 1) or 1) if len(raw_args) > 2 else 1
            if len(mat) == 1 and r_num > 1 and c_num == 1:
                c_num = r_num
                r_num = 1
            if r_num < 1 or r_num > len(mat) or c_num < 1 or c_num > len(mat[0]):
                return "#REF!"
            return _get_cell_eval(mat[r_num - 1][c_num - 1])

        if fn == "MATCH":
            if len(raw_args) < 2:
                return "#VALUE!"
            lookup_val = str(_eval_expr(raw_args[0])).strip()
            lookup_coords = [c for row in _expand_range_coords(raw_args[1]) for c in row]
            for idx, lc in enumerate(lookup_coords, start=1):
                if _matches_excel_criteria(_get_cell_eval(lc).strip(), lookup_val):
                    return str(idx)
            return "#N/A"

        if fn == "CHOOSE":
            if len(raw_args) < 2:
                return "#VALUE!"
            idx = int(_to_float(_eval_expr(raw_args[0]), 0) or 0)
            if idx < 1 or idx >= len(raw_args):
                return "#VALUE!"
            return _eval_expr(raw_args[idx])

        if fn == "ROW":
            if not raw_args:
                return "1"
            parsed = _split_cell_coord(raw_args[0].replace("$", "").split(":")[0])
            return str(parsed[2]) if parsed else "#REF!"
        if fn == "COLUMN":
            if not raw_args:
                return "1"
            parsed = _split_cell_coord(raw_args[0].replace("$", "").split(":")[0])
            return str(parsed[1] + 1) if parsed else "#REF!"
        if fn == "ROWS":
            mat = _expand_range_coords(raw_args[0]) if raw_args else []
            return str(len(mat)) if mat else "1"
        if fn == "COLUMNS":
            mat = _expand_range_coords(raw_args[0]) if raw_args else []
            return str(len(mat[0])) if (mat and mat[0]) else "1"

        # --- TEXT / STRING FUNCTIONS ---
        if fn in ("CONCAT", "CONCATENATE"):
            parts = [str(v) for a in raw_args for v in _expand_arg_values(a)]
            return "".join(parts)
        if fn == "TEXTJOIN":
            if len(raw_args) < 3:
                return "#VALUE!"
            delim = str(_eval_expr(raw_args[0]))
            ignore_empty = _to_bool(_eval_expr(raw_args[1]))
            vals = [str(v) for a in raw_args[2:] for v in _expand_arg_values(a)]
            if ignore_empty:
                vals = [v for v in vals if v != ""]
            return delim.join(vals)
        if fn == "LEN":
            return str(len(str(_eval_expr(raw_args[0])))) if raw_args else "0"
        if fn == "LOWER":
            return str(_eval_expr(raw_args[0])).lower() if raw_args else ""
        if fn == "UPPER":
            return str(_eval_expr(raw_args[0])).upper() if raw_args else ""
        if fn == "PROPER":
            return str(_eval_expr(raw_args[0])).title() if raw_args else ""
        if fn == "TRIM":
            return re.sub(r"\s+", " ", str(_eval_expr(raw_args[0])).strip()) if raw_args else ""
        if fn == "LEFT":
            txt = str(_eval_expr(raw_args[0])) if raw_args else ""
            n = int(_to_float(_eval_expr(raw_args[1]), 1) or 1) if len(raw_args) > 1 else 1
            return txt[:max(0, n)]
        if fn == "RIGHT":
            txt = str(_eval_expr(raw_args[0])) if raw_args else ""
            n = int(_to_float(_eval_expr(raw_args[1]), 1) or 1) if len(raw_args) > 1 else 1
            return txt[len(txt) - max(0, n):] if n > 0 else ""
        if fn == "MID":
            if len(raw_args) < 3:
                return "#VALUE!"
            txt = str(_eval_expr(raw_args[0]))
            start = max(1, int(_to_float(_eval_expr(raw_args[1]), 1) or 1))
            length = max(0, int(_to_float(_eval_expr(raw_args[2]), 0) or 0))
            return txt[start - 1: start - 1 + length]
        if fn == "SUBSTITUTE":
            if len(raw_args) < 3:
                return "#VALUE!"
            txt = str(_eval_expr(raw_args[0]))
            old_s = str(_eval_expr(raw_args[1]))
            new_s = str(_eval_expr(raw_args[2]))
            return txt.replace(old_s, new_s)
        if fn == "REPLACE":
            if len(raw_args) < 4:
                return "#VALUE!"
            txt = str(_eval_expr(raw_args[0]))
            start = max(1, int(_to_float(_eval_expr(raw_args[1]), 1) or 1))
            num_chars = max(0, int(_to_float(_eval_expr(raw_args[2]), 0) or 0))
            new_s = str(_eval_expr(raw_args[3]))
            return txt[:start - 1] + new_s + txt[start - 1 + num_chars:]
        if fn in ("FIND", "SEARCH"):
            if len(raw_args) < 2:
                return "#VALUE!"
            needle = str(_eval_expr(raw_args[0]))
            haystack = str(_eval_expr(raw_args[1]))
            start = max(1, int(_to_float(_eval_expr(raw_args[2]), 1) or 1)) if len(raw_args) > 2 else 1
            pos = (haystack.lower().find(needle.lower(), start - 1) if fn == "SEARCH" else haystack.find(needle, start - 1))
            return str(pos + 1) if pos >= 0 else "#VALUE!"
        if fn == "REPT":
            if len(raw_args) < 2:
                return "#VALUE!"
            txt = str(_eval_expr(raw_args[0]))
            cnt = max(0, min(1000, int(_to_float(_eval_expr(raw_args[1]), 0) or 0)))
            return txt * cnt
        if fn == "EXACT":
            if len(raw_args) < 2:
                return "FALSE"
            return "TRUE" if str(_eval_expr(raw_args[0])) == str(_eval_expr(raw_args[1])) else "FALSE"
        if fn == "VALUE":
            fv = _to_float(_eval_expr(raw_args[0]) if raw_args else "", None)
            return _format_formula_number(fv) if fv is not None else "#VALUE!"
        if fn == "TEXT":
            if not raw_args:
                return ""
            return str(_eval_expr(raw_args[0]))

        # --- DATE & TIME FUNCTIONS ---
        if fn == "TODAY":
            return datetime.now(manila_tz).strftime("%Y-%m-%d")
        if fn == "NOW":
            return datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M")
        if fn == "DATE":
            if len(raw_args) < 3:
                return "#VALUE!"
            y = int(_to_float(_eval_expr(raw_args[0]), 2026) or 2026)
            m = int(_to_float(_eval_expr(raw_args[1]), 1) or 1)
            d = int(_to_float(_eval_expr(raw_args[2]), 1) or 1)
            try:
                return datetime(y, m, d).strftime("%Y-%m-%d")
            except Exception:
                return "#VALUE!"
        if fn in ("YEAR", "MONTH", "DAY"):
            d_str = str(_eval_expr(raw_args[0])).strip() if raw_args else ""
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d %H:%M", "%b %d, %Y"):
                try:
                    dt = datetime.strptime(d_str, fmt)
                    return str(dt.year if fn == "YEAR" else (dt.month if fn == "MONTH" else dt.day))
                except Exception:
                    continue
            return "#VALUE!"

        # --- FINANCIAL FUNCTIONS ---
        if fn == "PMT":
            if len(raw_args) < 3:
                return "#VALUE!"
            rate = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            nper = _to_float(_eval_expr(raw_args[1]), 0.0) or 0.0
            pv = _to_float(_eval_expr(raw_args[2]), 0.0) or 0.0
            fv = (_to_float(_eval_expr(raw_args[3]), 0.0) or 0.0) if len(raw_args) > 3 else 0.0
            if nper == 0:
                return "#DIV/0!"
            if rate == 0:
                return _format_formula_number(-(pv + fv) / nper)
            pmt = -(rate * (pv * ((1 + rate) ** nper) + fv)) / (((1 + rate) ** nper) - 1)
            return _format_formula_number(pmt)
        if fn == "FV":
            if len(raw_args) < 3:
                return "#VALUE!"
            rate = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            nper = _to_float(_eval_expr(raw_args[1]), 0.0) or 0.0
            pmt = _to_float(_eval_expr(raw_args[2]), 0.0) or 0.0
            pv = (_to_float(_eval_expr(raw_args[3]), 0.0) or 0.0) if len(raw_args) > 3 else 0.0
            if rate == 0:
                return _format_formula_number(-(pv + pmt * nper))
            fv = -(pv * ((1 + rate) ** nper) + pmt * (((1 + rate) ** nper) - 1) / rate)
            return _format_formula_number(fv)
        if fn == "PV":
            if len(raw_args) < 3:
                return "#VALUE!"
            rate = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            nper = _to_float(_eval_expr(raw_args[1]), 0.0) or 0.0
            pmt = _to_float(_eval_expr(raw_args[2]), 0.0) or 0.0
            fv = (_to_float(_eval_expr(raw_args[3]), 0.0) or 0.0) if len(raw_args) > 3 else 0.0
            if rate == 0:
                return _format_formula_number(-(fv + pmt * nper))
            pv = -(fv + pmt * (((1 + rate) ** nper) - 1) / rate) / ((1 + rate) ** nper)
            return _format_formula_number(pv)
        if fn == "NPV":
            if len(raw_args) < 2:
                return "#VALUE!"
            rate = _to_float(_eval_expr(raw_args[0]), 0.0) or 0.0
            cashflows = [n for a in raw_args[1:] for n in _expand_arg_numbers(a)]
            npv = sum(cf / ((1 + rate) ** (idx + 1)) for idx, cf in enumerate(cashflows))
            return _format_formula_number(npv)

        # --- INFORMATION FUNCTIONS ---
        if fn == "ISBLANK":
            if not raw_args:
                return "TRUE"
            a_c = raw_args[0].strip()
            if re.match(r"^\$?[A-Za-z]+\$?\d+$", a_c):
                return "TRUE" if str(cells_map.get(a_c.replace("$", "").upper(), "")).strip() == "" else "FALSE"
            return "TRUE" if str(_eval_expr(a_c)).strip() == "" else "FALSE"
        if fn == "ISNUMBER":
            if not raw_args:
                return "FALSE"
            v = _eval_expr(raw_args[0])
            return "TRUE" if _to_float(v, None) is not None else "FALSE"
        if fn == "ISTEXT":
            if not raw_args:
                return "FALSE"
            v = str(_eval_expr(raw_args[0])).strip()
            return "TRUE" if (v != "" and _to_float(v, None) is None and not v.startswith("#")) else "FALSE"
        if fn == "ISERROR":
            if not raw_args:
                return "FALSE"
            return "TRUE" if str(_eval_expr(raw_args[0])).startswith("#") else "FALSE"
        if fn == "ISNA":
            if not raw_args:
                return "FALSE"
            return "TRUE" if str(_eval_expr(raw_args[0])) == "#N/A" else "FALSE"
        if fn == "ISEVEN":
            n = _to_float(_eval_expr(raw_args[0]) if raw_args else "", None)
            return "TRUE" if (n is not None and int(math.trunc(n)) % 2 == 0) else "FALSE"
        if fn == "ISODD":
            n = _to_float(_eval_expr(raw_args[0]) if raw_args else "", None)
            return "TRUE" if (n is not None and int(math.trunc(n)) % 2 != 0) else "FALSE"

        # --- EXTENDED ALL-10-CATEGORIES BACKEND SUPPORT ---
        if fn == "NA":
            return "#N/A"
        if fn == "ISERR":
            if not raw_args:
                return "FALSE"
            v = str(_eval_expr(raw_args[0]))
            return "TRUE" if (v.startswith("#") and v != "#N/A") else "FALSE"
        if fn == "ISLOGICAL":
            if not raw_args:
                return "FALSE"
            return "TRUE" if str(_eval_expr(raw_args[0])).strip().upper() in ("TRUE", "FALSE") else "FALSE"
        if fn == "ISNONTEXT":
            if not raw_args:
                return "TRUE"
            v = str(_eval_expr(raw_args[0])).strip()
            return "FALSE" if (v != "" and _to_float(v, None) is None and v.upper() not in ("TRUE", "FALSE") and not v.startswith("#")) else "TRUE"
        if fn == "ISFORMULA":
            if not raw_args:
                return "FALSE"
            c_ref = raw_args[0].strip().replace("$", "").upper()
            return "TRUE" if str(cells_map.get(c_ref, "")).strip().startswith("=") else "FALSE"
        if fn == "FORMULATEXT":
            if not raw_args:
                return "#N/A"
            c_ref = raw_args[0].strip().replace("$", "").upper()
            raw_f = str(cells_map.get(c_ref, "")).strip()
            return raw_f if raw_f.startswith("=") else "#N/A"
        if fn in ("XMATCH", "LOOKUP"):
            if len(raw_args) < 2:
                return "#VALUE!"
            lv = str(_eval_expr(raw_args[0])).strip()
            l_coords = [c for row in _expand_range_coords(raw_args[1]) for c in row]
            r_coords = [c for row in _expand_range_coords(raw_args[2]) for c in row] if len(raw_args) > 2 else l_coords
            for i_c, lc in enumerate(l_coords):
                if _matches_excel_criteria(_get_cell_eval(lc).strip(), lv):
                    return str(i_c + 1) if fn == "XMATCH" else (_get_cell_eval(r_coords[i_c]) if i_c < len(r_coords) else "#REF!")
            return "#N/A"
        if fn in ("UNIQUE", "SORT", "TOCOL", "TOROW", "TRANSPOSE"):
            vals = [v for a in (raw_args[:1] if raw_args else []) for v in _expand_arg_values(a) if str(v).strip() != ""]
            if fn == "UNIQUE":
                seen = []
                for v in vals:
                    if v not in seen:
                        seen.append(v)
                return ", ".join(seen)
            if fn == "SORT":
                return ", ".join(sorted(vals, key=lambda x: (_to_float(x, None) is None, _to_float(x, 0.0) if _to_float(x, None) is not None else str(x).lower())))
            return ", ".join(vals)
        if fn == "FILTER":
            if len(raw_args) < 2:
                return "#VALUE!"
            arr_c = [c for row in _expand_range_coords(raw_args[0]) for c in row]
            inc_c = [c for row in _expand_range_coords(raw_args[1]) for c in row]
            not_f = str(_eval_expr(raw_args[2])) if len(raw_args) > 2 else "#CALC!"
            out = [_get_cell_eval(c) for idx, c in enumerate(arr_c) if idx < len(inc_c) and _to_bool(_get_cell_eval(inc_c[idx]))]
            return ", ".join(out) if out else not_f
        if fn in ("TEXTBEFORE", "TEXTAFTER", "TEXTSPLIT"):
            if len(raw_args) < 2:
                return "#VALUE!"
            txt = str(_eval_expr(raw_args[0]))
            delim = str(_eval_expr(raw_args[1]))
            if not delim:
                return txt
            if fn == "TEXTSPLIT":
                return ", ".join(txt.split(delim))
            pos = txt.find(delim)
            if pos < 0:
                return str(_eval_expr(raw_args[5])) if len(raw_args) > 5 else "#N/A"
            return txt[:pos] if fn == "TEXTBEFORE" else txt[pos + len(delim):]
        if fn in ("DEC2BIN", "DEC2HEX", "DEC2OCT", "BIN2DEC", "HEX2DEC", "OCT2DEC"):
            if not raw_args:
                return "#VALUE!"
            s_v = str(_eval_expr(raw_args[0])).strip()
            try:
                if fn == "DEC2BIN":
                    return bin(int(_to_float(s_v, 0) or 0))[2:]
                if fn == "DEC2HEX":
                    return hex(int(_to_float(s_v, 0) or 0))[2:].upper()
                if fn == "DEC2OCT":
                    return oct(int(_to_float(s_v, 0) or 0))[2:]
                if fn == "BIN2DEC":
                    return str(int(s_v, 2))
                if fn == "HEX2DEC":
                    return str(int(s_v, 16))
                if fn == "OCT2DEC":
                    return str(int(s_v, 8))
            except Exception:
                return "#NUM!"
        if fn in ("GCD", "LCM"):
            nums_i = [abs(int(_to_float(n, 0) or 0)) for a in raw_args for n in _expand_arg_numbers(a)]
            if not nums_i:
                return "0"
            res_i = nums_i[0]
            for x in nums_i[1:]:
                res_i = math.gcd(res_i, x) if fn == "GCD" else ((res_i * x) // math.gcd(res_i, x) if (res_i and x) else 0)
            return str(res_i)
        if fn == "COMBIN":
            if len(raw_args) < 2:
                return "#VALUE!"
            n_c = int(_to_float(_eval_expr(raw_args[0]), 0) or 0)
            k_c = int(_to_float(_eval_expr(raw_args[1]), 0) or 0)
            return str(math.comb(n_c, k_c)) if (0 <= k_c <= n_c) else "#NUM!"
        if fn == "PERMUT":
            if len(raw_args) < 2:
                return "#VALUE!"
            n_p = int(_to_float(_eval_expr(raw_args[0]), 0) or 0)
            k_p = int(_to_float(_eval_expr(raw_args[1]), 0) or 0)
            return str(math.perm(n_p, k_p)) if (0 <= k_p <= n_p) else "#NUM!"
        if fn == "SEQUENCE":
            r_s = max(1, int(_to_float(_eval_expr(raw_args[0]), 1) or 1)) if raw_args else 1
            c_s = max(1, int(_to_float(_eval_expr(raw_args[1]), 1) or 1)) if len(raw_args) > 1 else 1
            st_s = _to_float(_eval_expr(raw_args[2]), 1.0) if len(raw_args) > 2 else 1.0
            sp_s = _to_float(_eval_expr(raw_args[3]), 1.0) if len(raw_args) > 3 else 1.0
            return ", ".join(_format_formula_number((st_s or 1.0) + i * (sp_s or 1.0)) for i in range(min(200, r_s * c_s)))

        return "#NAME?"

    def _eval_expr(sub_expr: str) -> Any:
        t = sub_expr.strip()
        if not t:
            return ""
        # Strip redundant outer parentheses if balanced
        while t.startswith("(") and t.endswith(")"):
            depth_p = 0
            in_q = False
            balanced_outer = True
            for i_c, ch in enumerate(t):
                if ch == '"':
                    in_q = not in_q
                elif not in_q:
                    if ch == '(':
                        depth_p += 1
                    elif ch == ')':
                        depth_p -= 1
                        if depth_p == 0 and i_c < len(t) - 1:
                            balanced_outer = False
                            break
            if balanced_outer and depth_p == 0:
                t = t[1:-1].strip()
            else:
                break

        # String literal
        if len(t) >= 2 and t.startswith('"') and t.endswith('"'):
            # Verify no unescaped quotes inside
            inner = t[1:-1]
            if '"' not in inner.replace('""', ''):
                return inner.replace('""', '"')

        # Top-level comparison operators: <>, >=, <=, =, >, <
        in_q = False
        depth_p = 0
        i_c = 0
        while i_c < len(t):
            ch = t[i_c]
            if ch == '"':
                in_q = not in_q
            elif not in_q:
                if ch == '(':
                    depth_p += 1
                elif ch == ')':
                    depth_p = max(0, depth_p - 1)
                elif depth_p == 0:
                    for op_str in ("<>", ">=", "<=", "=", ">", "<"):
                        if t[i_c:].startswith(op_str):
                            lhs = _eval_expr(t[:i_c])
                            rhs = _eval_expr(t[i_c + len(op_str):])
                            res_b = _matches_excel_criteria(lhs, f"{op_str}{rhs}")
                            return "TRUE" if res_b else "FALSE"
            i_c += 1

        # Top-level string concatenation operator: &
        in_q = False
        depth_p = 0
        for i_c, ch in enumerate(t):
            if ch == '"':
                in_q = not in_q
            elif not in_q:
                if ch == '(':
                    depth_p += 1
                elif ch == ')':
                    depth_p = max(0, depth_p - 1)
                elif ch == '&' and depth_p == 0:
                    return f"{_eval_expr(t[:i_c])}{_eval_expr(t[i_c + 1:])}"

        # Top-level addition / subtraction (+ / -) scanning right-to-left
        in_q = False
        depth_p = 0
        for i_c in range(len(t) - 1, -1, -1):
            ch = t[i_c]
            if ch == '"':
                in_q = not in_q
            elif not in_q:
                if ch == ')':
                    depth_p += 1
                elif ch == '(':
                    depth_p = max(0, depth_p - 1)
                elif depth_p == 0 and ch in ('+', '-') and i_c > 0:
                    prev_non_space = t[:i_c].rstrip()
                    if prev_non_space and prev_non_space[-1] not in ('+', '-', '*', '/', '^', '(', ',', ';', '=', '<', '>'):
                        lhs_v = _eval_expr(t[:i_c])
                        rhs_v = _eval_expr(t[i_c + 1:])
                        if str(lhs_v).startswith("#"):
                            return lhs_v
                        if str(rhs_v).startswith("#"):
                            return rhs_v
                        ln = _to_float(lhs_v, None)
                        rn = _to_float(rhs_v, None)
                        if ln is None or rn is None:
                            return "#VALUE!"
                        return _format_formula_number(ln + rn if ch == '+' else ln - rn)

        # Top-level multiplication / division (* / /) scanning right-to-left
        in_q = False
        depth_p = 0
        for i_c in range(len(t) - 1, -1, -1):
            ch = t[i_c]
            if ch == '"':
                in_q = not in_q
            elif not in_q:
                if ch == ')':
                    depth_p += 1
                elif ch == '(':
                    depth_p = max(0, depth_p - 1)
                elif depth_p == 0 and ch in ('*', '/') and i_c > 0:
                    lhs_v = _eval_expr(t[:i_c])
                    rhs_v = _eval_expr(t[i_c + 1:])
                    if str(lhs_v).startswith("#"):
                        return lhs_v
                    if str(rhs_v).startswith("#"):
                        return rhs_v
                    ln = _to_float(lhs_v, None)
                    rn = _to_float(rhs_v, None)
                    if ln is None or rn is None:
                        return "#VALUE!"
                    if ch == '/':
                        if rn == 0:
                            return "#DIV/0!"
                        return _format_formula_number(ln / rn)
                    return _format_formula_number(ln * rn)

        # Top-level exponentiation (^)
        in_q = False
        depth_p = 0
        for i_c in range(len(t) - 1, -1, -1):
            ch = t[i_c]
            if ch == '"':
                in_q = not in_q
            elif not in_q:
                if ch == ')':
                    depth_p += 1
                elif ch == '(':
                    depth_p = max(0, depth_p - 1)
                elif depth_p == 0 and ch == '^' and i_c > 0:
                    ln = _to_float(_eval_expr(t[:i_c]), None)
                    rn = _to_float(_eval_expr(t[i_c + 1:]), None)
                    if ln is None or rn is None:
                        return "#VALUE!"
                    return _format_formula_number(math.pow(ln, rn))

        # Unary + or -
        if t.startswith("-"):
            uv = _to_float(_eval_expr(t[1:]), None)
            return _format_formula_number(-uv) if uv is not None else "#VALUE!"
        if t.startswith("+"):
            uv = _to_float(_eval_expr(t[1:]), None)
            return _format_formula_number(uv) if uv is not None else "#VALUE!"

        # Percentage suffix (e.g. 15%)
        if t.endswith("%") and re.match(r"^-?\d+(\.\d+)?%$", t):
            return _format_formula_number(float(t[:-1]) / 100.0)

        # Function call: FUNC_NAME(arg1, arg2, ...)
        fn_call = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*\((.*)\)$", t, re.DOTALL)
        if fn_call:
            fn_name = fn_call.group(1)
            args_body = fn_call.group(2).strip()
            parsed_args = _split_top_level_formula_args(args_body) if args_body else []
            return _eval_function(fn_name, parsed_args)

        # Single Cell Reference (e.g. A1, $B$12)
        if re.match(r"^\$?[A-Za-z]+\$?\d+$", t):
            return _get_cell_eval(t)

        # Plain number or boolean literal
        if t.upper() in ("TRUE", "FALSE"):
            return t.upper()
        try:
            num_val = float(t)
            return _format_formula_number(num_val)
        except Exception:
            pass

        return t

    try:
        res = _eval_expr(expr)
        return str(res if res is not None else "")
    except Exception:
        return "#ERROR!"



def _parse_legacy_xls_bytes(file_bytes: bytes, filename: str = "uploaded.xls") -> Dict[str, Any]:
    """
    Parses .xls spreadsheet files (supports xlrd if installed, XML Spreadsheet 2003,
    HTML-table .xls exports, CSV/TSV text .xls, and pure-Python BIFF8 record extraction).
    """
    # 1. Try xlrd if installed in Python environment
    try:
        import xlrd  # type: ignore
        wb = xlrd.open_workbook(file_contents=file_bytes)
        parsed_sheets: List[Dict[str, Any]] = []
        for s_idx in range(wb.nsheets):
            sh = wb.sheet_by_index(s_idx)
            cells_map: Dict[str, str] = {}
            max_r = max(25, sh.nrows + 5)
            max_c = max(10, sh.ncols + 2)
            for r_i in range(sh.nrows):
                for c_i in range(sh.ncols):
                    val = sh.cell_value(r_i, c_i)
                    if val is not None and str(val).strip() != "":
                        if isinstance(val, float) and val.is_integer():
                            val_str = str(int(val))
                        else:
                            val_str = str(val).strip()
                        coord = f"{_col_idx_to_letter(c_i)}{r_i + 1}"
                        cells_map[coord] = val_str
            parsed_sheets.append({
                "id": f"sheet_{s_idx + 1}_{uuid.uuid4().hex[:6]}",
                "name": _sanitize_excel_sheet_name(sh.name, f"Sheet{s_idx + 1}"),
                "cells": cells_map,
                "row_count": min(max_r, 500),
                "col_count": min(max_c, 52)
            })
        if parsed_sheets:
            return {
                "status": "success",
                "rejected": False,
                "filename": filename,
                "sheets": parsed_sheets,
                "message": f"Successfully imported '{filename}' ({len(parsed_sheets)} sheet(s))!"
            }
    except Exception:
        pass

    # 2. Check if it's XML Spreadsheet 2003, HTML Table .xls, or TSV/CSV text with .xls extension
    text_sample = ""
    try:
        text_sample = file_bytes.decode("utf-8-sig", errors="ignore").strip()
    except Exception:
        text_sample = ""

    if text_sample and not file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        # 2a. XML Spreadsheet 2003 (<Workbook ...><Worksheet ss:Name="..."><Table><Row><Cell><Data>...)
        if "<Workbook" in text_sample or "<Worksheet" in text_sample:
            try:
                root = ET.fromstring(text_sample)
                parsed_sheets = []
                ws_idx = 0
                for ws in root.iter():
                    if ws.tag.endswith("}Worksheet") or ws.tag == "Worksheet":
                        ws_idx += 1
                        s_name = f"Sheet{ws_idx}"
                        for k, v in ws.attrib.items():
                            if k.endswith("}Name") or k == "ss:Name" or k == "Name":
                                s_name = _sanitize_excel_sheet_name(v, s_name)
                        cells_map = {}
                        r_num = 0
                        max_c = 10
                        for r_el in ws.iter():
                            if r_el.tag.endswith("}Row") or r_el.tag == "Row":
                                r_num += 1
                                c_num = 0
                                for c_el in r_el:
                                    if c_el.tag.endswith("}Cell") or c_el.tag == "Cell":
                                        for ak, av in c_el.attrib.items():
                                            if ak.endswith("}Index") or ak == "ss:Index":
                                                try:
                                                    c_num = int(av) - 1
                                                except Exception:
                                                    pass
                                        c_num += 1
                                        max_c = max(max_c, c_num)
                                        txt_parts = [d.text for d in c_el.iter() if (d.tag.endswith("}Data") or d.tag == "Data") and d.text]
                                        val_s = "".join(txt_parts).strip()
                                        if val_s:
                                            cells_map[f"{_col_idx_to_letter(c_num - 1)}{r_num}"] = val_s
                        parsed_sheets.append({
                            "id": f"sheet_{ws_idx}_{uuid.uuid4().hex[:6]}",
                            "name": s_name,
                            "cells": cells_map,
                            "row_count": max(25, min(r_num + 5, 500)),
                            "col_count": max(10, min(max_c + 2, 52))
                        })
                if parsed_sheets:
                    return {"status": "success", "rejected": False, "filename": filename, "sheets": parsed_sheets, "message": f"Successfully imported '{filename}'!"}
            except Exception:
                pass

        # 2b. HTML Table .xls
        if "<table" in text_sample.lower() and "<tr" in text_sample.lower():
            rows_matches = re.findall(r"<tr[^>]*>(.*?)</tr>", text_sample, flags=re.IGNORECASE | re.DOTALL)
            cells_map = {}
            max_c = 10
            for r_idx, tr_inner in enumerate(rows_matches, start=1):
                td_matches = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_inner, flags=re.IGNORECASE | re.DOTALL)
                for c_idx, td_inner in enumerate(td_matches):
                    clean_txt = re.sub(r"<[^>]+>", "", td_inner).strip()
                    if clean_txt:
                        cells_map[f"{_col_idx_to_letter(c_idx)}{r_idx}"] = clean_txt
                        max_c = max(max_c, c_idx + 1)
            return {
                "status": "success",
                "rejected": False,
                "filename": filename,
                "sheets": [{
                    "id": f"sheet_1_{uuid.uuid4().hex[:6]}",
                    "name": "Sheet1",
                    "cells": cells_map,
                    "row_count": max(25, min(len(rows_matches) + 5, 500)),
                    "col_count": max(10, min(max_c + 2, 52))
                }],
                "message": f"Successfully imported '{filename}'!"
            }

        # 2c. Tab-separated or Comma-separated .xls
        import csv
        delim = "\t" if "\t" in text_sample.splitlines()[0] else ","
        reader = csv.reader(io.StringIO(text_sample), delimiter=delim)
        cells_map = {}
        max_r = 0
        max_c = 10
        for r_idx, row_vals in enumerate(reader, start=1):
            max_r = r_idx
            for c_idx, cell_v in enumerate(row_vals):
                if str(cell_v or "").strip() != "":
                    cells_map[f"{_col_idx_to_letter(c_idx)}{r_idx}"] = str(cell_v).strip()
                    max_c = max(max_c, c_idx + 1)
        if cells_map:
            return {
                "status": "success",
                "rejected": False,
                "filename": filename,
                "sheets": [{
                    "id": f"sheet_1_{uuid.uuid4().hex[:6]}",
                    "name": "Sheet1",
                    "cells": cells_map,
                    "row_count": max(25, min(max_r + 5, 500)),
                    "col_count": max(10, min(max_c + 2, 52))
                }],
                "message": f"Successfully imported '{filename}'!"
            }

    # 3. Pure-Python BIFF8 OLE2 .xls parser fallback (extracts SST shared strings, LABELSST, LABEL, RK, NUMBER records)
    if file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        import struct
        sst_strings: List[str] = []
        cells_map: Dict[str, str] = {}
        max_r = 25
        max_c = 10
        pos = 512
        n_len = len(file_bytes)
        while pos + 4 <= n_len:
            rec_id, rec_len = struct.unpack_from("<HH", file_bytes, pos)
            if rec_len > 8228 or pos + 4 + rec_len > n_len:
                pos += 1
                continue
            rec_data = file_bytes[pos + 4 : pos + 4 + rec_len]
            # SST Record (0x00FC)
            if rec_id == 0x00FC and len(rec_data) >= 8:
                try:
                    _, uniq_cnt = struct.unpack_from("<II", rec_data, 0)
                    s_off = 8
                    for _ in range(min(uniq_cnt, 5000)):
                        if s_off + 3 > len(rec_data):
                            break
                        char_cnt, flags = struct.unpack_from("<HB", rec_data, s_off)
                        s_off += 3
                        rt_runs = 0
                        ext_sz = 0
                        if flags & 0x08 and s_off + 2 <= len(rec_data):
                            rt_runs = struct.unpack_from("<H", rec_data, s_off)[0]
                            s_off += 2
                        if flags & 0x04 and s_off + 4 <= len(rec_data):
                            ext_sz = struct.unpack_from("<I", rec_data, s_off)[0]
                            s_off += 4
                        if flags & 0x01:
                            byte_len = char_cnt * 2
                            s_val = rec_data[s_off : s_off + byte_len].decode("utf-16le", errors="ignore")
                            s_off += byte_len
                        else:
                            byte_len = char_cnt
                            s_val = rec_data[s_off : s_off + byte_len].decode("latin1", errors="ignore")
                            s_off += byte_len
                        s_off += rt_runs * 4 + ext_sz
                        sst_strings.append(s_val)
                except Exception:
                    pass
            # LABELSST Record (0x00FD): row(2), col(2), xf(2), sst_idx(4)
            elif rec_id == 0x00FD and len(rec_data) == 10:
                r_idx, c_idx, _, sst_idx = struct.unpack("<HHHI", rec_data)
                if r_idx < 1000 and c_idx < 100 and 0 <= sst_idx < len(sst_strings):
                    val_s = sst_strings[sst_idx].strip()
                    if val_s:
                        cells_map[f"{_col_idx_to_letter(c_idx)}{r_idx + 1}"] = val_s
                        max_r = max(max_r, r_idx + 5)
                        max_c = max(max_c, c_idx + 2)
            # NUMBER Record (0x0203): row(2), col(2), xf(2), ieee_float(8)
            elif rec_id == 0x0203 and len(rec_data) == 14:
                r_idx, c_idx, _, d_val = struct.unpack("<HHHd", rec_data)
                if r_idx < 1000 and c_idx < 100:
                    val_s = str(int(d_val)) if d_val == int(d_val) else str(round(d_val, 6))
                    cells_map[f"{_col_idx_to_letter(c_idx)}{r_idx + 1}"] = val_s
                    max_r = max(max_r, r_idx + 5)
                    max_c = max(max_c, c_idx + 2)
            pos += 4 + rec_len

        return {
            "status": "success",
            "rejected": False,
            "filename": filename,
            "sheets": [{
                "id": f"sheet_1_{uuid.uuid4().hex[:6]}",
                "name": "Sheet1",
                "cells": cells_map,
                "row_count": min(max_r, 500),
                "col_count": min(max_c, 52)
            }],
            "message": f"Successfully imported '{filename}' (.xls spreadsheet)!"
        }

    return {
        "status": "error",
        "rejected": True,
        "detected_items": [f"Unrecognized .xls structure ({filename})"],
        "message": f"Could not parse '{filename}'. Please save as standard .xlsx or .xls tabular spreadsheet."
    }


def _format_spreadsheet_cell_value(val: Any, c_type: str = "") -> str:
    """
    Normalizes Excel / Google Sheets numeric values so scientific notation
    (e.g. '1.3453184631841E13', '1.554878515441E+12') and trailing '.0' floats
    are converted into clean, exact numbers ('13453184631841', '1554878515441')
    matching what the user sees in Google Sheets without unwanted decimals or 'E' alphabets.
    """
    if val is None:
        return ""
    raw_str = str(val)
    s = raw_str.strip()
    if not s or s.startswith("="):
        return raw_str
    # Preserve leading-zero strings like '09175497760'
    if len(s) > 1 and s[0] == "0" and s[1].isdigit():
        return raw_str
    # Normalize if XML cell type is numeric ('', 'n') OR if string is in scientific notation (e.g. 1.3453184631841E+12)
    is_sci = bool(re.match(r"^[+-]?(?:\d+\.?\d*|\.\d+)[eE][+-]?\d+$", s))
    if c_type in ("", "n") or is_sci:
        if re.match(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$", s):
            try:
                from decimal import Decimal
                d = Decimal(s)
                if d == d.to_integral_value():
                    return str(d.to_integral_value())
                norm_d = d.normalize()
                fixed_str = format(norm_d, "f")
                if "." in fixed_str and len(fixed_str.split(".")[1]) > 10:
                    d2 = Decimal(f"{float(s):.15g}")
                    if d2 == d2.to_integral_value():
                        return str(d2.to_integral_value())
                    fixed_str = format(d2.normalize(), "f")
                return fixed_str
            except Exception:
                pass
    return raw_str


def _sanitize_workbook_sheets_cells(wb: Dict[str, Any]) -> bool:
    """
    Cleans any scientific-notation or float-artifact strings across all sheets in a workbook.
    Returns True if any cell value was normalized.
    """
    if not isinstance(wb, dict):
        return False
    changed = False
    for sh in (wb.get("sheets") or []):
        if not isinstance(sh, dict):
            continue
        cells = sh.get("cells")
        if not isinstance(cells, dict):
            continue
        for k in list(cells.keys()):
            old_v = str(cells[k] if cells[k] is not None else "")
            new_v = _format_spreadsheet_cell_value(old_v, "")
            if new_v != old_v:
                cells[k] = new_v
                changed = True
    return changed


def _compute_sheets_signature(sheets: Any) -> str:
    """
    Computes a deterministic canonical JSON signature of sheet names, cells, and layout
    (wrap_cells, col_widths, row_heights) so we can accurately detect changes.
    """
    if not isinstance(sheets, list):
        return ""
    norm = []
    for sh in sheets:
        if not isinstance(sh, dict):
            continue
        raw_cells = sh.get("cells") or {}
        clean_cells = {
            str(k).upper(): _format_spreadsheet_cell_value(v, "")
            for k, v in sorted(raw_cells.items())
            if v is not None and str(v).strip() != ""
        }
        raw_wrap = sh.get("wrap_cells") or {}
        clean_wrap = {
            str(k).upper(): True
            for k, v in sorted(raw_wrap.items())
            if v
        } if isinstance(raw_wrap, dict) else {}
        raw_cw = sh.get("col_widths") or {}
        clean_cw = {
            str(k).upper(): int(float(v))
            for k, v in sorted(raw_cw.items())
            if v is not None and str(v).strip() != ""
        } if isinstance(raw_cw, dict) else {}
        raw_rh = sh.get("row_heights") or {}
        clean_rh = {
            str(k): int(float(v))
            for k, v in sorted(raw_rh.items())
            if v is not None and str(v).strip() != ""
        } if isinstance(raw_rh, dict) else {}
        norm.append({
            "name": str(sh.get("name") or "Sheet1"),
            "cells": clean_cells,
            "wrap_cells": clean_wrap,
            "col_widths": clean_cw,
            "row_heights": clean_rh
        })
    try:
        return json.dumps(norm, sort_keys=True, ensure_ascii=False)
    except Exception:
        return ""


def validate_and_parse_xlsx_bytes(file_bytes: bytes, filename: str = "uploaded.xlsx", strict_reject_media: bool = True) -> Dict[str, Any]:
    """
    Validates and parses .xlsx and .xls spreadsheet files:
      - Supports both .xlsx (OpenXML) and .xls (Excel 97-2004 / XML / tabular) files.
      - When strict_reject_media=True (local import), rejects if the .xlsx contains graphs/charts,
        images/media, drawings/shapes, or macros.
      - Parses all sheets, sheet names, and A1/B1 cells, normalizing scientific notation numbers.
    """
    if not file_bytes:
        return {
            "status": "error",
            "rejected": True,
            "detected_items": ["Empty file"],
            "message": "Import Rejected by Python: Empty file uploaded."
        }

    lower_fname = str(filename or "").strip().lower()
    if not lower_fname.endswith((".xlsx", ".xls")):
        return {
            "status": "error",
            "rejected": True,
            "detected_items": [f"Unsupported extension ({filename})"],
            "message": "Import Rejected by Python: Only '.xlsx' and '.xls' spreadsheet files are supported."
        }

    bio = io.BytesIO(file_bytes)
    if not zipfile.is_zipfile(bio):
        if lower_fname.endswith(".xls"):
            res_xls = _parse_legacy_xls_bytes(file_bytes, filename)
            if res_xls.get("status") == "success":
                _sanitize_workbook_sheets_cells(res_xls)
            return res_xls
        return {
            "status": "error",
            "rejected": True,
            "detected_items": ["Invalid .xlsx ZIP structure"],
            "message": "Import Rejected by Python: The uploaded file is not a valid .xlsx spreadsheet archive."
        }

    bio.seek(0)
    detected_non_tabular: List[str] = []

    try:
        with zipfile.ZipFile(bio, "r") as zf:
            names = zf.namelist()
            if strict_reject_media:
                for raw_entry in names:
                    entry = str(raw_entry or "").replace("\\", "/").lower()
                    if entry.startswith("xl/charts/") or entry.startswith("xl/chartsheets/"):
                        detected_non_tabular.append(f"Graphs / Charts ({raw_entry})")
                    elif entry.startswith("xl/media/") or re.search(r"\.(png|jpg|jpeg|gif|bmp|webp|svg|emf|wmf|tiff|tif)$", entry):
                        detected_non_tabular.append(f"Images / Media ({raw_entry})")
                    elif entry.startswith("xl/drawings/") or entry.startswith("xl/diagrams/"):
                        detected_non_tabular.append(f"Drawings / Shapes / SmartArt ({raw_entry})")
                    elif (
                        entry.startswith("xl/embeddings/")
                        or entry.startswith("xl/activex/")
                        or entry.startswith("xl/ctrlprops/")
                        or entry.startswith("xl/pivottables/")
                        or entry.startswith("xl/slicers/")
                        or entry.endswith("vbaproject.bin")
                    ):
                        detected_non_tabular.append(f"Embedded Objects / Macros / PivotTables ({raw_entry})")

                for raw_entry in names:
                    entry = str(raw_entry or "").replace("\\", "/").lower()
                    if entry.startswith("xl/worksheets/") and entry.endswith(".xml"):
                        try:
                            xml_text = zf.read(raw_entry).decode("utf-8", errors="ignore")
                            if re.search(r"<(?:\w+:)?(drawing|legacydrawing|picture|oleobjects|controls)\b", xml_text, re.IGNORECASE):
                                if not any("Drawings" in d or "Graphs" in d or "Images" in d for d in detected_non_tabular):
                                    detected_non_tabular.append(f"Worksheet Embedded Graph / Image / Drawing ({raw_entry})")
                        except Exception:
                            pass

                if detected_non_tabular:
                    unique_reasons = list(dict.fromkeys(detected_non_tabular))
                    return {
                        "status": "error",
                        "rejected": True,
                        "detected_items": unique_reasons,
                        "message": (
                            f"Import Rejected by Python: The uploaded file '{filename}' contains "
                            f"Graphs/Charts, Images, or Embedded Objects ({', '.join(unique_reasons[:3])}). "
                            f"Only plain tabular spreadsheet data (Columns A, B, C, D... and Rows 1, 2, 3, 4...) is accepted."
                        )
                    }

            # --- PARSE CLEAN TABULAR .XLSX WORKBOOK ---
            # 1. Shared Strings (xl/sharedStrings.xml)
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in names:
                try:
                    ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in ss_root.iter():
                        if si.tag.endswith("}si") or si.tag == "si":
                            parts: List[str] = []
                            for t_node in si.iter():
                                if t_node.tag.endswith("}t") or t_node.tag == "t":
                                    if t_node.text:
                                        parts.append(t_node.text)
                            shared_strings.append("".join(parts))
                except Exception as ss_err:
                    print(f"[⚠️ XLSX SHARED STRINGS PARSE WARNING]: {ss_err}")

            # 1b. Parse Wrap Text styles from xl/styles.xml (if present)
            wrapped_xf_indices = set()
            if "xl/styles.xml" in names:
                try:
                    st_root = ET.fromstring(zf.read("xl/styles.xml"))
                    for node in st_root.iter():
                        if node.tag.endswith("}cellXfs") or node.tag == "cellXfs":
                            xf_idx = 0
                            for xf in node:
                                if xf.tag.endswith("}xf") or xf.tag == "xf":
                                    for child in xf:
                                        if child.tag.endswith("}alignment") or child.tag == "alignment":
                                            wt = str(child.attrib.get("wrapText") or "").lower()
                                            if wt in ("1", "true"):
                                                wrapped_xf_indices.add(xf_idx)
                                    xf_idx += 1
                except Exception:
                    pass

            # 2. Workbook Relationships (xl/_rels/workbook.xml.rels)
            rid_to_target: Dict[str, str] = {}
            rels_path = "xl/_rels/workbook.xml.rels"
            if rels_path in names:
                try:
                    rels_root = ET.fromstring(zf.read(rels_path))
                    for rel in rels_root.iter():
                        if rel.tag.endswith("}Relationship") or rel.tag == "Relationship":
                            r_id = rel.attrib.get("Id") or ""
                            target = (rel.attrib.get("Target") or "").lstrip("/")
                            if target and not target.startswith("xl/"):
                                target = f"xl/{target}"
                            if r_id and target:
                                rid_to_target[r_id] = target
                except Exception:
                    pass

            # 3. Sheet Names & Order (xl/workbook.xml)
            sheet_entries: List[Dict[str, str]] = []
            if "xl/workbook.xml" in names:
                try:
                    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
                    idx_counter = 1
                    for sh in wb_root.iter():
                        if sh.tag.endswith("}sheet") or sh.tag == "sheet":
                            sh_name = sh.attrib.get("name") or f"Sheet{idx_counter}"
                            r_id = ""
                            for k, v in sh.attrib.items():
                                if k.endswith("}id") or k == "r:id" or k == "id":
                                    r_id = v
                                    break
                            target_xml = rid_to_target.get(r_id) or f"xl/worksheets/sheet{idx_counter}.xml"
                            sheet_entries.append({"name": _sanitize_excel_sheet_name(sh_name, f"Sheet{idx_counter}"), "path": target_xml})
                            idx_counter += 1
                except Exception:
                    pass

            if not sheet_entries:
                ws_files = sorted([n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
                for idx_w, w_path in enumerate(ws_files, start=1):
                    sheet_entries.append({"name": f"Sheet{idx_w}", "path": w_path})

            parsed_sheets: List[Dict[str, Any]] = []
            for idx_s, s_info in enumerate(sheet_entries, start=1):
                w_path = s_info["path"]
                if w_path not in names:
                    alt_path = f"xl/worksheets/sheet{idx_s}.xml"
                    w_path = alt_path if alt_path in names else ""
                cells_map: Dict[str, str] = {}
                wrap_cells_map: Dict[str, bool] = {}
                col_widths_map: Dict[str, int] = {}
                row_heights_map: Dict[str, int] = {}
                max_row = 25
                max_col = 10

                if w_path and w_path in names:
                    ws_root = ET.fromstring(zf.read(w_path))
                    # Parse custom column widths from <cols><col min="..." max="..." width="..."/></cols>
                    for col_el in ws_root.iter():
                        if col_el.tag.endswith("}col") or col_el.tag == "col":
                            try:
                                c_min = int(col_el.attrib.get("min") or 0)
                                c_max = int(col_el.attrib.get("max") or c_min)
                                w_char = float(col_el.attrib.get("width") or 0)
                                if c_min >= 1 and w_char > 0:
                                    px_w = max(55, min(1400, int(round(w_char * 7.0))))
                                    for c_1idx in range(c_min, min(c_max, 52) + 1):
                                        col_widths_map[_col_idx_to_letter(c_1idx - 1)] = px_w
                                        max_col = max(max_col, c_1idx)
                            except Exception:
                                pass

                    row_seq = 0
                    for row_el in ws_root.iter():
                        if not (row_el.tag.endswith("}row") or row_el.tag == "row"):
                            continue
                        row_seq += 1
                        r_num = int(row_el.attrib.get("r") or row_seq)
                        max_row = max(max_row, r_num)

                        # Parse custom row height if present
                        ht_attr = row_el.attrib.get("ht")
                        if ht_attr is not None:
                            try:
                                ht_pt = float(ht_attr)
                                if ht_pt > 0:
                                    px_h = max(24, min(900, int(round(ht_pt / 0.75))))
                                    row_heights_map[str(r_num)] = px_h
                            except Exception:
                                pass

                        col_seq = 0
                        for c_el in row_el:
                            if not (c_el.tag.endswith("}c") or c_el.tag == "c"):
                                continue
                            col_seq += 1
                            ref = c_el.attrib.get("r") or f"{_col_idx_to_letter(col_seq - 1)}{r_num}"
                            parsed_coord = _split_cell_coord(ref)
                            if parsed_coord:
                                c_let, c_idx, r_n = parsed_coord
                                max_col = max(max_col, c_idx + 1)
                                max_row = max(max_row, r_n)
                                ref_key = f"{c_let}{r_n}"
                            else:
                                ref_key = ref.upper()

                            s_attr = c_el.attrib.get("s")
                            if s_attr is not None and wrapped_xf_indices:
                                try:
                                    if int(s_attr) in wrapped_xf_indices:
                                        wrap_cells_map[ref_key] = True
                                except Exception:
                                    pass

                            c_type = c_el.attrib.get("t") or ""
                            val_text = ""
                            formula_text = ""
                            inline_parts: List[str] = []

                            for child in c_el:
                                tag_clean = child.tag.split("}")[-1]
                                if tag_clean == "f" and child.text:
                                    formula_text = f"={child.text.lstrip('=')}"
                                elif tag_clean == "v" and child.text is not None:
                                    val_text = child.text
                                elif tag_clean == "is":
                                    for t_sub in child.iter():
                                        if t_sub.tag.endswith("}t") or t_sub.tag == "t":
                                            if t_sub.text:
                                                inline_parts.append(t_sub.text)

                            final_val = ""
                            if formula_text and not re.match(r"^=(IMAGE|SPARKLINE|IMPORTIMAGE|EMBEDIMAGE|WEBIMAGE|PICTURE)\b", formula_text, re.IGNORECASE):
                                final_val = formula_text
                            elif c_type == "s":
                                try:
                                    ss_idx = int(val_text)
                                    if 0 <= ss_idx < len(shared_strings):
                                        final_val = shared_strings[ss_idx]
                                except Exception:
                                    final_val = val_text
                            elif c_type == "inlineStr":
                                final_val = "".join(inline_parts)
                            elif c_type == "b":
                                final_val = "TRUE" if val_text == "1" else "FALSE"
                            elif val_text != "":
                                final_val = _format_spreadsheet_cell_value(val_text, c_type)
                            elif formula_text:
                                final_val = formula_text

                            if str(final_val).strip() != "":
                                cells_map[ref_key] = str(final_val)

                parsed_sheets.append({
                    "id": f"sheet_{idx_s}_{uuid.uuid4().hex[:6]}",
                    "name": s_info["name"],
                    "cells": cells_map,
                    "wrap_cells": wrap_cells_map,
                    "col_widths": col_widths_map,
                    "row_heights": row_heights_map,
                    "row_count": max(25, min(max_row + 5, 500)),
                    "col_count": max(10, min(max_col + 2, 52))
                })

            if not parsed_sheets:
                parsed_sheets.append({
                    "id": f"sheet_1_{uuid.uuid4().hex[:6]}",
                    "name": "Sheet1",
                    "cells": {},
                    "wrap_cells": {},
                    "col_widths": {},
                    "row_heights": {},
                    "row_count": 25,
                    "col_count": 10
                })

            return {
                "status": "success",
                "rejected": False,
                "filename": filename,
                "sheets": parsed_sheets,
                "message": f"Successfully imported '{filename}' ({len(parsed_sheets)} sheet(s)) — verified clean tabular data!"
            }
    except Exception as e:
        return {
            "status": "error",
            "rejected": True,
            "detected_items": [str(e)],
            "message": f"Import Rejected by Python: Could not parse '{filename}' ({e})."
        }


def build_xlsx_bytes_from_sheets(sheets: List[Dict[str, Any]]) -> bytes:
    """
    Generates a genuine, standards-compliant OpenXML .xlsx workbook binary in memory
    from GlennBot's custom spreadsheet sheets (Columns A, B, C, D... and Rows 1, 2, 3, 4... +
    custom sheet names, formulas, column widths, row heights, and per-cell wrap text).
    Works in pure Python without requiring external C libraries.
    """
    valid_sheets = list(sheets or [])
    if not valid_sheets:
        valid_sheets = [{"name": "Sheet1", "cells": {}}]

    used_names = set()
    normalized_sheets: List[Dict[str, Any]] = []
    for idx, sh in enumerate(valid_sheets, start=1):
        base_name = _sanitize_excel_sheet_name(sh.get("name") or f"Sheet{idx}", f"Sheet{idx}")
        candidate_name = base_name
        suffix = 2
        while candidate_name.lower() in used_names:
            candidate_name = f"{base_name[:27]}_{suffix}"
            suffix += 1
        used_names.add(candidate_name.lower())
        normalized_sheets.append({
            "name": candidate_name,
            "cells": dict(sh.get("cells") or {}),
            "wrap_cells": dict(sh.get("wrap_cells") or {}) if isinstance(sh.get("wrap_cells"), dict) else {},
            "col_widths": dict(sh.get("col_widths") or {}) if isinstance(sh.get("col_widths"), dict) else {},
            "row_heights": dict(sh.get("row_heights") or {}) if isinstance(sh.get("row_heights"), dict) else {}
        })

    out_bio = io.BytesIO()
    with zipfile.ZipFile(out_bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. [Content_Types].xml
        sheet_overrides = "".join([
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(normalized_sheets) + 1)
        ])
        content_types_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f'{sheet_overrides}'
            '</Types>'
        )
        zf.writestr("[Content_Types].xml", content_types_xml)

        # 2. _rels/.rels
        root_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        zf.writestr("_rels/.rels", root_rels_xml)

        # 3. xl/workbook.xml
        quot_entity_map = {'"': "&quot;"}
        sheets_xml_tags = "".join([
            f'<sheet name="{xml_escape(sh["name"], quot_entity_map)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, sh in enumerate(normalized_sheets, start=1)
        ])
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{sheets_xml_tags}</sheets>'
            '</workbook>'
        )
        zf.writestr("xl/workbook.xml", workbook_xml)

        # 4. xl/_rels/workbook.xml.rels
        wb_rels_tags = "".join([
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(normalized_sheets) + 1)
        ])
        style_rid = f"rId{len(normalized_sheets) + 1}"
        wb_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{wb_rels_tags}'
            f'<Relationship Id="{style_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        )
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)

        # 5. xl/styles.xml (s="0" default, s="1" Wrap Text enabled)
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
            '</cellXfs>'
            '</styleSheet>'
        )
        zf.writestr("xl/styles.xml", styles_xml)

        # 6. xl/worksheets/sheet{i}.xml
        for i, sh in enumerate(normalized_sheets, start=1):
            cells_dict: Dict[str, str] = sh["cells"]
            wrap_dict: Dict[str, Any] = {str(k).upper(): bool(v) for k, v in (sh.get("wrap_cells") or {}).items() if v}
            col_widths_dict: Dict[str, Any] = sh.get("col_widths") or {}
            row_heights_dict: Dict[str, Any] = sh.get("row_heights") or {}

            # Build <cols> XML if custom column widths exist
            col_xml_items: List[str] = []
            for col_key, raw_w in sorted(col_widths_dict.items(), key=lambda x: _letter_to_col_idx(str(x[0]))):
                try:
                    px_w = float(raw_w)
                    if px_w >= 45:
                        c_1idx = _letter_to_col_idx(str(col_key)) + 1
                        excel_w = round(px_w / 7.0, 2)
                        col_xml_items.append(f'<col min="{c_1idx}" max="{c_1idx}" width="{excel_w}" customWidth="1"/>')
                except Exception:
                    pass
            cols_xml_block = f'<cols>{"".join(col_xml_items)}</cols>' if col_xml_items else ""

            rows_bucket: Dict[int, Dict[int, Tuple[str, str]]] = {}
            for coord_key, raw_val in cells_dict.items():
                val_str = _format_spreadsheet_cell_value(raw_val, "")
                if val_str == "":
                    continue
                parsed = _split_cell_coord(coord_key)
                if not parsed:
                    continue
                col_l, col_idx, row_n = parsed
                rows_bucket.setdefault(row_n, {})[col_idx] = (f"{col_l}{row_n}", val_str)

            # Also include wrapped cells even if currently empty so their wrap formatting persists
            for coord_key in wrap_dict.keys():
                parsed = _split_cell_coord(coord_key)
                if not parsed:
                    continue
                col_l, col_idx, row_n = parsed
                row_map = rows_bucket.setdefault(row_n, {})
                if col_idx not in row_map:
                    row_map[col_idx] = (f"{col_l}{row_n}", "")

            # Also include rows that have custom row heights
            for r_key in row_heights_dict.keys():
                try:
                    r_n = int(r_key)
                    if r_n >= 1:
                        rows_bucket.setdefault(r_n, {})
                except Exception:
                    pass

            row_xml_chunks: List[str] = []
            for r_num in sorted(rows_bucket.keys()):
                row_map = rows_bucket[r_num]
                cell_xml_chunks: List[str] = []
                for col_idx in sorted(row_map.keys()):
                    ref_str, v_str = row_map[col_idx]
                    style_attr = ' s="1"' if wrap_dict.get(ref_str.upper()) else ''
                    clean_v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v_str)
                    stripped_v = clean_v.strip()
                    if stripped_v == "":
                        if style_attr:
                            cell_xml_chunks.append(f'<c r="{ref_str}"{style_attr}/>')
                    elif stripped_v.startswith("=") and len(stripped_v) > 1:
                        f_body = xml_escape(stripped_v[1:].strip())
                        eval_v = _evaluate_spreadsheet_formula(stripped_v, cells_dict)
                        if re.match(r"^-?\d+(\.\d+)?$", str(eval_v)):
                            cell_xml_chunks.append(f'<c r="{ref_str}"{style_attr}><f>{f_body}</f><v>{eval_v}</v></c>')
                        else:
                            esc_eval = xml_escape(str(eval_v))
                            cell_xml_chunks.append(f'<c r="{ref_str}" t="str"{style_attr}><f>{f_body}</f><v>{esc_eval}</v></c>')
                    elif (
                        re.match(r"^-?\d+(\.\d+)?$", stripped_v)
                        and not (len(stripped_v) > 1 and stripped_v.startswith("0") and not stripped_v.startswith("0."))
                        and len(stripped_v.lstrip("-").split(".")[0]) <= 11
                    ):
                        cell_xml_chunks.append(f'<c r="{ref_str}" t="n"{style_attr}><v>{stripped_v}</v></c>')
                    else:
                        escaped_text = xml_escape(clean_v)
                        cell_xml_chunks.append(f'<c r="{ref_str}" t="inlineStr"{style_attr}><is><t xml:space="preserve">{escaped_text}</t></is></c>')

                row_ht_attr = ""
                raw_rh = row_heights_dict.get(str(r_num)) if str(r_num) in row_heights_dict else row_heights_dict.get(r_num)
                if raw_rh is not None:
                    try:
                        px_h = float(raw_rh)
                        if px_h >= 20:
                            pt_h = round(px_h * 0.75, 2)
                            row_ht_attr = f' ht="{pt_h}" customHeight="1"'
                    except Exception:
                        pass

                row_xml_chunks.append(f'<row r="{r_num}"{row_ht_attr}>{"".join(cell_xml_chunks)}</row>')

            ws_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'{cols_xml_block}'
                f'<sheetData>{"".join(row_xml_chunks)}</sheetData>'
                '</worksheet>'
            )
            zf.writestr(f"xl/worksheets/sheet{i}.xml", ws_xml)

    return out_bio.getvalue()


def _create_default_spreadsheet_workbook() -> Dict[str, Any]:
    now_str = datetime.now(manila_tz).strftime("%b %d, %Y %I:%M %p")
    return {
        "workbook_id": "",
        "file_id": "",
        "gdrive_file_id": "",
        "title": "Untitled_Spreadsheet.xlsx",
        "updated_at": now_str,
        "sheets": [
            {
                "id": "sheet_1",
                "name": "Sheet1",
                "row_count": 25,
                "col_count": 10,
                "cells": {}
            }
        ]
    }


def _is_unsaved_legacy_default_workbook(wb: Dict[str, Any]) -> bool:
    """
    Identifies the old placeholder 'wb_default_glennbot' if it was never saved to Google Drive
    and has no file_id in the Files Vault, so the dropdown only lists real spreadsheet files.
    """
    if not isinstance(wb, dict):
        return True
    wb_id = str(wb.get("workbook_id") or "").strip()
    fid = str(wb.get("file_id") or "").strip()
    gd_id = str(wb.get("gdrive_file_id") or "").strip()
    if wb_id == "wb_default_glennbot" and not fid and not gd_id:
        sheets = wb.get("sheets") or []
        if len(sheets) == 1:
            cells = (sheets[0] or {}).get("cells") or {}
            default_keys = {"A1", "B1", "C1", "D1", "E1"}
            if set(cells.keys()).issubset(default_keys) and cells.get("A1") == "Client Name":
                return True
    return False


def _load_spreadsheets_store(force_cloud: bool = False) -> Dict[str, Any]:
    with SPREADSHEETS_LOCK:
        # Once loaded in memory, keep the live in-memory state as the source of truth
        # so stale Cloudinary CDN caches never revert recent Google Drive syncs!
        if SPREADSHEETS_STORE.get("loaded"):
            for w in (SPREADSHEETS_STORE.get("workbooks") or []):
                _sanitize_workbook_sheets_cells(w)
            return SPREADSHEETS_STORE

        workbooks: List[Dict[str, Any]] = []
        loaded_local = False

        if os.path.exists(LOCAL_SPREADSHEETS_CACHE_PATH):
            try:
                with open(LOCAL_SPREADSHEETS_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                    if isinstance(data.get("workbooks"), list):
                        workbooks = data["workbooks"]
                        loaded_local = True
            except Exception:
                pass

        if not loaded_local and CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
            try:
                res = cloudinary.api.resource(
                    CLOUDINARY_SPREADSHEETS_STORE_PUBLIC_ID,
                    resource_type="raw"
                )
                sec_url = (res or {}).get("secure_url")
                if sec_url:
                    sep = "&" if "?" in sec_url else "?"
                    r = HTTP_SESSION.get(f"{sec_url}{sep}_ts={int(time.time())}", timeout=15)
                    if r.status_code == 200:
                        data = r.json() or {}
                        if isinstance(data.get("workbooks"), list):
                            workbooks = data["workbooks"]
            except Exception:
                pass

        # Filter out any unsaved placeholder workbook and normalize all numeric cells
        clean_workbooks: List[Dict[str, Any]] = []
        for w in workbooks:
            if isinstance(w, dict) and not _is_unsaved_legacy_default_workbook(w):
                _sanitize_workbook_sheets_cells(w)
                clean_workbooks.append(w)

        SPREADSHEETS_STORE["workbooks"] = clean_workbooks
        SPREADSHEETS_STORE["loaded"] = True
        return SPREADSHEETS_STORE


def _save_spreadsheets_store() -> bool:
    with SPREADSHEETS_LOCK:
        clean_wbs = []
        for w in (SPREADSHEETS_STORE.get("workbooks") or []):
            if isinstance(w, dict) and not _is_unsaved_legacy_default_workbook(w):
                _sanitize_workbook_sheets_cells(w)
                clean_wbs.append(w)
        SPREADSHEETS_STORE["workbooks"] = clean_wbs
        payload = {
            "version": 2,
            "updated_at": datetime.now(manila_tz).strftime("%Y-%m-%d %I:%M:%S %p"),
            "workbooks": clean_wbs
        }
        raw_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        try:
            with open(LOCAL_SPREADSHEETS_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(raw_bytes.decode("utf-8"))
        except Exception:
            pass

    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        def _bg_upload_cloud():
            try:
                cloudinary.uploader.upload(
                    io.BytesIO(raw_bytes),
                    resource_type="raw",
                    public_id=CLOUDINARY_SPREADSHEETS_STORE_PUBLIC_ID,
                    overwrite=True,
                    invalidate=True
                )
            except Exception as e:
                print(f"[⚠️ SPREADSHEETS STORE CLOUDINARY SAVE WARNING]: {e}")
        threading.Thread(target=_bg_upload_cloud, daemon=True).start()
    return True


def _push_live_cells_to_google_sheets_api(
    gdrive_file_id: str,
    sheets: Optional[List[Dict[str, Any]]] = None,
    wb_ref: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Pushes sheet cell values directly via Google Sheets API v4 (`values:batchUpdate`)
    and warms the Google Docs live `.xlsx` export endpoint so open Google Sheets browser
    tabs reflect Dashboard edits immediately without waiting for Drive blob polling.
    """
    clean_gd_id = (gdrive_file_id or "").strip()
    if not clean_gd_id or "/" in clean_gd_id or not sheets or not is_gdrive_authorized():
        return False

    try:
        acc_tok = gdrive_get_access_token(force_refresh=False)
        headers = {
            "Authorization": f"Bearer {acc_tok}",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache, no-store, max-age=0"
        }

        data_entries: List[Dict[str, Any]] = []
        for idx, sh in enumerate(sheets, start=1):
            if not isinstance(sh, dict):
                continue
            s_name = _sanitize_excel_sheet_name(sh.get("name") or f"Sheet{idx}", f"Sheet{idx}")
            cells_map = sh.get("cells") or {}
            max_data_r = 1
            max_data_c = 1
            parsed_coords: Dict[Tuple[int, int], str] = {}
            for coord_str, raw_v in cells_map.items():
                sp = _split_cell_coord(coord_str)
                if not sp:
                    continue
                _, c_idx, r_num = sp
                val_s = "" if raw_v is None else str(raw_v)
                parsed_coords[(r_num, c_idx)] = val_s
                if val_s != "":
                    if r_num > max_data_r:
                        max_data_r = r_num
                    if (c_idx + 1) > max_data_c:
                        max_data_c = c_idx + 1

            grid_rows = min(300, max(int(sh.get("row_count") or 25), max_data_r, 25))
            grid_cols = min(52, max(int(sh.get("col_count") or 10), max_data_c, 10))

            values_matrix: List[List[Any]] = []
            for r_num in range(1, grid_rows + 1):
                row_vals: List[Any] = []
                for c_idx in range(grid_cols):
                    v_str = parsed_coords.get((r_num, c_idx), "")
                    if (
                        v_str != ""
                        and not v_str.startswith("=")
                        and re.match(r"^-?\d+(\.\d+)?$", v_str)
                        and not (len(v_str) > 1 and v_str.startswith("0") and not v_str.startswith("0."))
                        and len(v_str.lstrip("-").split(".")[0]) <= 11
                    ):
                        try:
                            row_vals.append(float(v_str) if "." in v_str else int(v_str))
                        except Exception:
                            row_vals.append(v_str)
                    else:
                        row_vals.append(v_str)
                values_matrix.append(row_vals)

            safe_sh_name = s_name.replace("'", "''")
            end_col_letter = _col_idx_to_letter(grid_cols - 1)
            range_a1 = f"'{safe_sh_name}'!A1:{end_col_letter}{grid_rows}"
            data_entries.append({
                "range": range_a1,
                "majorDimension": "ROWS",
                "values": values_matrix
            })

        pushed_ok = False
        if data_entries:
            batch_url = f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(clean_gd_id, safe='')}/values:batchUpdate"
            r_batch = HTTP_SESSION.post(
                batch_url,
                headers=headers,
                json={
                    "valueInputOption": "USER_ENTERED",
                    "data": data_entries
                },
                timeout=8
            )
            if r_batch.status_code == 200:
                pushed_ok = True
                if isinstance(wb_ref, dict):
                    wb_ref["last_local_save_ts"] = time.time()
                    wb_ref["last_edit_source"] = "glennbot"

        # Warm the Google Docs live export cache so subsequent export fetches return the latest state
        try:
            live_sheets_url = f"https://docs.google.com/spreadsheets/d/{urllib.parse.quote(clean_gd_id, safe='')}/export"
            HTTP_SESSION.get(
                live_sheets_url,
                headers={"Authorization": f"Bearer {acc_tok}", "Cache-Control": "no-cache, no-store, max-age=0"},
                params={"format": "xlsx", "_cb": str(int(time.time() * 1000))},
                timeout=8
            )
        except Exception:
            pass

        if isinstance(wb_ref, dict):
            wb_ref["last_local_save_ts"] = time.time()
        return pushed_ok
    except Exception:
        return False


def _upload_or_update_spreadsheet_on_gdrive(
    xlsx_bytes: bytes,
    filename: str,
    existing_gdrive_file_id: str = "",
    py_file_id: str = "",
    sheets: Optional[List[Dict[str, Any]]] = None,
    wb_ref: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Uploads a new .xlsx file OR updates an existing file in-place on Google Drive ('GlennBot_Media_Vault')
    so that client edits in Google Drive / Google Sheets and GlennBot dashboard edits share the exact same Google Drive file!
    """
    if not is_gdrive_authorized():
        raise RuntimeError("Google Drive is not connected yet. Please click 'Connect Google Drive' in the Files modal first.")

    acc_tok = gdrive_get_access_token(force_refresh=False)
    clean_gd_id = (existing_gdrive_file_id or "").strip()
    clean_orig = os.path.basename(str(filename or "Spreadsheet.xlsx").strip())
    clean_orig = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", clean_orig) or "Spreadsheet.xlsx"
    if not clean_orig.lower().endswith((".xlsx", ".xls")):
        clean_orig = f"{clean_orig}.xlsx"
    safe_orig = clean_orig
    gdrive_fname = clean_orig

    # 1. If we already have a Google Drive File ID, update its binary content in-place via HTTP_SESSION.patch (keep-alive pool)
    if clean_gd_id and "/" not in clean_gd_id:
        try:
            patch_url = (
                f"https://www.googleapis.com/upload/drive/v3/files/{urllib.parse.quote(clean_gd_id, safe='')}"
                f"?uploadType=media&supportsAllDrives=true&fields=id,name,mimeType,modifiedTime,md5Checksum,size,webViewLink"
            )
            patch_headers = {
                "Authorization": f"Bearer {acc_tok}",
                "Content-Type": XLSX_MIME_TYPE,
                "Content-Length": str(len(xlsx_bytes)),
                "Cache-Control": "no-cache"
            }
            patch_resp = HTTP_SESSION.patch(
                patch_url,
                headers=patch_headers,
                data=xlsx_bytes,
                timeout=45
            )
            if patch_resp.status_code == 401:
                acc_tok = gdrive_get_access_token(force_refresh=True)
                patch_headers["Authorization"] = f"Bearer {acc_tok}"
                patch_resp = HTTP_SESSION.patch(
                    patch_url,
                    headers=patch_headers,
                    data=xlsx_bytes,
                    timeout=45
                )
            if patch_resp.status_code in (200, 201):
                meta = patch_resp.json() or {}
                gd_id = str(meta.get("id") or clean_gd_id).strip()
                if sheets:
                    threading.Thread(
                        target=_push_live_cells_to_google_sheets_api,
                        args=(gd_id, sheets, wb_ref),
                        daemon=True
                    ).start()
                return {
                    "gdrive_file_id": gd_id,
                    "gdrive_file_name": str(meta.get("name") or gdrive_fname),
                    "gdrive_modified_time": str(meta.get("modifiedTime") or ""),
                    "gdrive_md5": str(meta.get("md5Checksum") or ""),
                    "web_view_link": str(meta.get("webViewLink") or f"https://drive.google.com/file/d/{gd_id}/view"),
                    "mime_type": str(meta.get("mimeType") or XLSX_MIME_TYPE)
                }
        except Exception as patch_err:
            print(f"[⚠️ GDRIVE SPREADSHEET IN-PLACE PATCH WARNING] ({clean_gd_id}): {patch_err}")

    # 2. Otherwise upload a new .xlsx file into the Google Drive Vault folder
    up_res = upload_media_to_gdrive(
        file_bytes=xlsx_bytes,
        original_filename=safe_orig,
        media_type="file",
        is_thumb=False,
        custom_subfolder="spreadsheets",
        custom_file_prefix=py_file_id
    )
    new_gd_id = str(up_res.get("gdrive_file_id") or "").strip()
    mod_time = ""
    md5_val = ""
    web_link = str(up_res.get("web_view_link") or (f"https://drive.google.com/file/d/{new_gd_id}/view" if new_gd_id else ""))
    if new_gd_id:
        try:
            meta_r = HTTP_SESSION.get(
                f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(new_gd_id, safe='')}",
                headers={"Authorization": f"Bearer {acc_tok}"},
                params={"fields": "id,name,mimeType,modifiedTime,md5Checksum,webViewLink"},
                timeout=15
            )
            if meta_r.status_code == 200:
                m_json = meta_r.json() or {}
                mod_time = str(m_json.get("modifiedTime") or "")
                md5_val = str(m_json.get("md5Checksum") or "")
                web_link = str(m_json.get("webViewLink") or web_link)
        except Exception:
            pass
        if sheets:
            threading.Thread(
                target=_push_live_cells_to_google_sheets_api,
                args=(new_gd_id, sheets, wb_ref),
                daemon=True
            ).start()

    return {
        "gdrive_file_id": new_gd_id,
        "gdrive_file_name": str(up_res.get("gdrive_file_name") or gdrive_fname),
        "gdrive_modified_time": mod_time,
        "gdrive_md5": md5_val,
        "web_view_link": web_link,
        "mime_type": XLSX_MIME_TYPE
    }


def _register_or_update_spreadsheet_in_files_vault(
    py_file_id: str,
    filename: str,
    size_bytes: int,
    gdrive_info: Dict[str, Any],
    workbook_id: str = ""
) -> Dict[str, Any]:
    """
    Ensures every saved spreadsheet in the Spread Sheet modal also exists in the 'Files' modal (FILES_VAULT_STORE)
    with its own unique Python-generated File ID (`file_...`) and Google Drive link.
    """
    v_store = _load_files_vault_store(force_cloud=False)
    existing_files: List[Dict[str, Any]] = list(v_store.get("files") or [])
    existing_ids = {str(x.get("file_id") or "") for x in existing_files}

    clean_fid = (py_file_id or "").strip()
    gd_id = str(gdrive_info.get("gdrive_file_id") or "").strip()

    # Check if an entry already exists by file_id or gdrive_file_id
    target_idx = -1
    for idx, f_entry in enumerate(existing_files):
        if clean_fid and str(f_entry.get("file_id") or "") == clean_fid:
            target_idx = idx
            break
        if gd_id and str(f_entry.get("gdrive_file_id") or "") == gd_id:
            target_idx = idx
            clean_fid = str(f_entry.get("file_id") or clean_fid)
            break

    if not clean_fid:
        clean_fid = _generate_python_automation_file_id(existing_ids)

    stream_u = f"/api/files/{clean_fid}/stream"
    now_manila = datetime.now(manila_tz)
    lower_fn = str(filename or "Spreadsheet.xlsx").lower()
    mime_str = XLS_MIME_TYPE if lower_fn.endswith(".xls") else XLSX_MIME_TYPE

    record = {
        "file_id": clean_fid,
        "workbook_id": workbook_id,
        "filename": filename,
        "content_type": mime_str,
        "size_bytes": int(size_bytes or 0),
        "size_formatted": _format_file_size_human(int(size_bytes or 0)),
        "storage_provider": "google_drive",
        "bucket_name": GOOGLE_DRIVE_FOLDER_NAME,
        "gdrive_file_id": gd_id,
        "gdrive_file_name": str(gdrive_info.get("gdrive_file_name") or filename),
        "gdrive_modified_time": str(gdrive_info.get("gdrive_modified_time") or ""),
        "gdrive_md5": str(gdrive_info.get("gdrive_md5") or ""),
        "web_view_link": str(gdrive_info.get("web_view_link") or (f"https://drive.google.com/file/d/{gd_id}/view" if gd_id else "")),
        "download_url": stream_u,
        "preview_url": stream_u,
        "zernio_media_url": "",
        "zernio_media_ts": 0.0,
        "notes": "Synced GlennBot Spreadsheet (Auto-Synced with Google Drive)",
        "uploaded_at": now_manila.strftime("%b %d, %Y %I:%M %p"),
        "uploaded_iso": now_manila.isoformat()
    }

    if target_idx >= 0:
        prev_notes = str(existing_files[target_idx].get("notes") or "").strip()
        if prev_notes:
            record["notes"] = prev_notes
        existing_files[target_idx] = record
    else:
        existing_files.insert(0, record)

    with FILES_VAULT_LOCK:
        FILES_VAULT_STORE["files"] = existing_files
    _save_files_vault_store()
    return record


def _download_and_parse_gdrive_spreadsheet(
    gdrive_file_id: str,
    filename: str,
    mime_type: str = "",
    prefer_live_sheets_export: bool = True
) -> Optional[List[Dict[str, Any]]]:
    """
    Downloads the latest binary bytes of a spreadsheet (.xlsx, .xls, or Google Sheets native document)
    and parses its sheets & cells with exact number formatting.
    When prefer_live_sheets_export=True, queries Google Sheets' live export endpoint
    ('https://docs.google.com/spreadsheets/d/{id}/export?format=xlsx') first so edits made inside
    Google Sheets' web editor (even on .XLSX files in Office Editing mode) are picked up immediately
    without waiting 1-3 minutes for Google Drive's blob storage flush!
    """
    clean_gd_id = (gdrive_file_id or "").strip()
    if not clean_gd_id or "/" in clean_gd_id or not is_gdrive_authorized():
        return None

    try:
        acc_tok = gdrive_get_access_token(force_refresh=False)
        cb_ms = str(int(time.time() * 1000))
        headers = {
            "Authorization": f"Bearer {acc_tok}",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache"
        }
        raw_bytes = b""
        effective_filename = filename or "Spreadsheet.xlsx"

        # 1. Try live Google Sheets server export first when requested (instantaneous for files open in Google Sheets!)
        if prefer_live_sheets_export or mime_type == GOOGLE_SHEETS_MIME_TYPE:
            try:
                live_sheets_url = f"https://docs.google.com/spreadsheets/d/{urllib.parse.quote(clean_gd_id, safe='')}/export"
                r_live = HTTP_SESSION.get(
                    live_sheets_url,
                    headers=headers,
                    params={"format": "xlsx", "_cb": cb_ms},
                    timeout=20
                )
                if r_live.status_code == 200 and r_live.content and zipfile.is_zipfile(io.BytesIO(r_live.content)):
                    raw_bytes = r_live.content
                    if not effective_filename.lower().endswith(".xlsx"):
                        effective_filename = f"{os.path.splitext(effective_filename)[0]}.xlsx"
            except Exception:
                pass

        # 2. Fallback to Drive API v3 export (for native Google Sheets) or alt=media (for .xlsx / .xls binary)
        if not raw_bytes:
            if mime_type == GOOGLE_SHEETS_MIME_TYPE:
                exp_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(clean_gd_id, safe='')}/export"
                r = HTTP_SESSION.get(exp_url, headers=headers, params={"mimeType": XLSX_MIME_TYPE, "_cb": cb_ms}, timeout=30)
                if r.status_code == 200 and r.content:
                    raw_bytes = r.content
                    if not effective_filename.lower().endswith((".xlsx", ".xls")):
                        effective_filename = f"{effective_filename}.xlsx"
            else:
                dl_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(clean_gd_id, safe='')}"
                r = HTTP_SESSION.get(dl_url, headers=headers, params={"alt": "media", "_cb": cb_ms}, timeout=30)
                if r.status_code == 200 and r.content:
                    raw_bytes = r.content
                elif r.status_code in (400, 403):
                    exp_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(clean_gd_id, safe='')}/export"
                    r_exp = HTTP_SESSION.get(exp_url, headers=headers, params={"mimeType": XLSX_MIME_TYPE, "_cb": cb_ms}, timeout=30)
                    if r_exp.status_code == 200 and r_exp.content:
                        raw_bytes = r_exp.content
                        if not effective_filename.lower().endswith(".xlsx"):
                            effective_filename = f"{os.path.splitext(effective_filename)[0]}.xlsx"

        if not raw_bytes:
            return None

        parsed = validate_and_parse_xlsx_bytes(raw_bytes, effective_filename, strict_reject_media=False)
        if parsed.get("status") == "success" and isinstance(parsed.get("sheets"), list) and parsed["sheets"]:
            return parsed["sheets"]
    except Exception as e:
        print(f"[⚠️ GDRIVE SPREADSHEET DOWNLOAD/PARSE WARNING] ({clean_gd_id}): {e}")
    return None


def _sync_spreadsheets_with_gdrive_and_vault(
    force_gdrive_check: bool = False,
    target_id: str = ""
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Two-Way Live Auto-Sync Engine between:
      1) 'Files' Modal (FILES_VAULT_STORE)
      2) Client's Google Drive / Google Sheets ('GlennBot_Media_Vault' folder & tracked gdrive_file_ids)
      3) 'Spread Sheet' Modal (SPREADSHEETS_STORE)
    Returns (workbooks_list, any_changed).
    """
    with SPREADSHEETS_SYNC_LOCK:
        sp_store = _load_spreadsheets_store(force_cloud=False)
        v_store = _load_files_vault_store(force_cloud=False)
        workbooks: List[Dict[str, Any]] = [
            w for w in list(sp_store.get("workbooks") or [])
            if isinstance(w, dict) and not _is_unsaved_legacy_default_workbook(w)
        ]
        for w in workbooks:
            if _sanitize_workbook_sheets_cells(w):
                pass
        vault_files: List[Dict[str, Any]] = list(v_store.get("files") or [])
        any_changed = False
        vault_changed = False

        # 1. Link any spreadsheet (.xlsx / .xls) uploaded in the 'Files' modal into SPREADSHEETS_STORE
        for vf in vault_files:
            if not isinstance(vf, dict):
                continue
            v_fid = str(vf.get("file_id") or "").strip()
            v_fname = str(vf.get("filename") or "").strip()
            v_mime = str(vf.get("content_type") or "").strip()
            v_gd_id = str(vf.get("gdrive_file_id") or "").strip()
            if not _is_spreadsheet_filename_or_mime(v_fname, v_mime):
                continue

            existing_wb = next(
                (
                    w for w in workbooks
                    if (v_fid and str(w.get("file_id") or "") == v_fid)
                    or (v_gd_id and str(w.get("gdrive_file_id") or "") == v_gd_id)
                ),
                None
            )
            if not existing_wb:
                wb_id = str(vf.get("workbook_id") or f"wb_{v_fid or uuid.uuid4().hex[:8]}").strip()
                parsed_sheets = _download_and_parse_gdrive_spreadsheet(v_gd_id, v_fname, v_mime, prefer_live_sheets_export=True) if v_gd_id else None
                if not parsed_sheets:
                    parsed_sheets = [{"id": "sheet_1", "name": "Sheet1", "row_count": 25, "col_count": 10, "cells": {}}]
                new_wb = {
                    "workbook_id": wb_id,
                    "file_id": v_fid,
                    "gdrive_file_id": v_gd_id,
                    "gdrive_file_name": str(vf.get("gdrive_file_name") or v_fname),
                    "gdrive_modified_time": str(vf.get("gdrive_modified_time") or ""),
                    "gdrive_md5": str(vf.get("gdrive_md5") or ""),
                    "web_view_link": str(vf.get("web_view_link") or (f"https://drive.google.com/file/d/{v_gd_id}/view" if v_gd_id else "")),
                    "title": v_fname,
                    "storage_provider": "google_drive",
                    "size_bytes": int(vf.get("size_bytes") or 0),
                    "size_formatted": str(vf.get("size_formatted") or "0 B"),
                    "sheet_count": len(parsed_sheets),
                    "updated_at": str(vf.get("uploaded_at") or datetime.now(manila_tz).strftime("%b %d, %Y %I:%M %p")),
                    "sheets": parsed_sheets
                }
                workbooks.insert(0, new_wb)
                any_changed = True
            else:
                if v_fid and not existing_wb.get("file_id"):
                    existing_wb["file_id"] = v_fid
                    any_changed = True
                if v_gd_id and not existing_wb.get("gdrive_file_id"):
                    existing_wb["gdrive_file_id"] = v_gd_id
                    any_changed = True

        # 2. Check Google Drive / Google Sheets for external edits made by the client
        now_ts = time.time()
        last_sync_ts = float(SPREADSHEETS_STORE.get("last_gdrive_sync_ts") or 0.0)
        target_clean = (target_id or "").strip()
        should_query_gdrive = is_gdrive_authorized() and (
            force_gdrive_check
            or bool(target_clean)
            or (now_ts - last_sync_ts >= 3.0)
        )

        if should_query_gdrive:
            SPREADSHEETS_STORE["last_gdrive_sync_ts"] = now_ts
            try:
                acc_tok = gdrive_get_access_token(force_refresh=False)
                headers = {
                    "Authorization": f"Bearer {acc_tok}",
                    "Cache-Control": "no-cache, no-store, max-age=0",
                    "Pragma": "no-cache"
                }

                wbs_to_check = workbooks
                if target_clean:
                    matched_wbs = [
                        w for w in workbooks
                        if str(w.get("workbook_id") or "") == target_clean
                        or str(w.get("file_id") or "") == target_clean
                        or str(w.get("gdrive_file_id") or "") == target_clean
                        or str(w.get("title") or "").lower() == target_clean.lower()
                    ]
                    if matched_wbs:
                        wbs_to_check = matched_wbs

                for wb in list(wbs_to_check):
                    gd_id = str(wb.get("gdrive_file_id") or "").strip()
                    if not gd_id or "/" in gd_id:
                        continue
                    # Skip pulling for 2.5 seconds immediately after a local save from GlennBot so we don't interrupt active typing
                    last_local_save = float(wb.get("last_local_save_ts") or 0.0)
                    if (now_ts - last_local_save) < 2.5:
                        continue
                    try:
                        meta_r = HTTP_SESSION.get(
                            f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(gd_id, safe='')}",
                            headers=headers,
                            params={
                                "fields": "id,name,mimeType,modifiedTime,md5Checksum,size,webViewLink,trashed",
                                "_cb": str(int(now_ts * 1000))
                            },
                            timeout=10
                        )
                        if meta_r.status_code == 404:
                            continue
                        m_data = meta_r.json() if meta_r.status_code == 200 else {}
                        if m_data.get("trashed"):
                            continue

                        remote_name_raw = str(m_data.get("name") or "").strip()
                        if remote_name_raw:
                            clean_remote_name = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", remote_name_raw) or remote_name_raw
                            if clean_remote_name != str(wb.get("title") or "").strip():
                                wb["title"] = clean_remote_name
                                wb["gdrive_file_name"] = clean_remote_name
                                any_changed = True
                                for vf_item in vault_files:
                                    if isinstance(vf_item, dict) and (
                                        str(vf_item.get("gdrive_file_id") or "") == gd_id
                                        or (wb.get("file_id") and str(vf_item.get("file_id") or "") == str(wb.get("file_id")))
                                    ):
                                        vf_item["filename"] = clean_remote_name
                                        vf_item["gdrive_file_name"] = clean_remote_name
                                        vault_changed = True
                        remote_mod = str(m_data.get("modifiedTime") or "").strip()
                        remote_md5 = str(m_data.get("md5Checksum") or "").strip()
                        local_mod = str(wb.get("gdrive_modified_time") or "").strip()
                        local_md5 = str(wb.get("gdrive_md5") or "").strip()
                        remote_mime = str(m_data.get("mimeType") or "").strip()

                        is_meta_modified = (
                            (remote_mod and remote_mod != local_mod)
                            or (remote_md5 and local_md5 and remote_md5 != local_md5)
                        )
                        if is_meta_modified:
                            wb["last_edit_source"] = "gdrive"

                        # Clean up expired obsolete signatures (> 120s old)
                        raw_obsolete = wb.get("obsolete_replaced_sigs")
                        obsolete_sigs: Dict[str, float] = {}
                        if isinstance(raw_obsolete, dict):
                            for k_sig, ts_val in raw_obsolete.items():
                                try:
                                    if (now_ts - float(ts_val)) < 120.0:
                                        obsolete_sigs[str(k_sig)] = float(ts_val)
                                except Exception:
                                    pass
                        wb["obsolete_replaced_sigs"] = obsolete_sigs

                        # When syncing the active target workbook (target_clean), ALWAYS pull live bytes
                        # because Google Sheets web editor buffers edits before Drive metadata modifiedTime updates!
                        should_download_live = bool(target_clean) or is_meta_modified
                        if should_download_live:
                            wb_title_str = str(wb.get("title") or m_data.get("name") or "Spreadsheet.xlsx")
                            fresh_sheets = _download_and_parse_gdrive_spreadsheet(
                                gd_id,
                                wb_title_str,
                                remote_mime,
                                prefer_live_sheets_export=True
                            )
                            old_sig = _compute_sheets_signature(wb.get("sheets"))
                            new_sig = _compute_sheets_signature(fresh_sheets) if fresh_sheets else ""

                            # Guard against stale Google Docs live export cache returning an old pre-GlennBot-save snapshot:
                            if fresh_sheets and new_sig and new_sig in obsolete_sigs and new_sig != old_sig:
                                direct_sheets = _download_and_parse_gdrive_spreadsheet(
                                    gd_id,
                                    wb_title_str,
                                    remote_mime,
                                    prefer_live_sheets_export=False
                                )
                                direct_sig = _compute_sheets_signature(direct_sheets) if direct_sheets else ""
                                if direct_sheets and direct_sig and direct_sig not in obsolete_sigs:
                                    fresh_sheets = direct_sheets
                                    new_sig = direct_sig
                                else:
                                    fresh_sheets = None
                                    new_sig = ""

                            if fresh_sheets and new_sig:
                                if new_sig == old_sig:
                                    # Live export has caught up with our latest state; clear obsolete history
                                    wb["obsolete_replaced_sigs"] = {}
                                old_sheets_list = list(wb.get("sheets") or [])
                                for idx_fs, fs_item in enumerate(fresh_sheets):
                                    if not isinstance(fs_item, dict):
                                        continue
                                    matched_old = next(
                                        (
                                            os_item for os_item in old_sheets_list
                                            if isinstance(os_item, dict) and str(os_item.get("name") or "") == str(fs_item.get("name") or "")
                                        ),
                                        old_sheets_list[idx_fs] if idx_fs < len(old_sheets_list) and isinstance(old_sheets_list[idx_fs], dict) else None
                                    )
                                    if matched_old:
                                        if isinstance(matched_old.get("wrap_cells"), dict):
                                            fs_item["wrap_cells"] = dict(matched_old["wrap_cells"])
                                        if isinstance(matched_old.get("col_widths"), dict):
                                            fs_item["col_widths"] = dict(matched_old["col_widths"])
                                        if isinstance(matched_old.get("row_heights"), dict):
                                            fs_item["row_heights"] = dict(matched_old["row_heights"])
                                if new_sig != old_sig or is_meta_modified:
                                    wb["sheets"] = fresh_sheets
                                    wb["sheet_count"] = len(fresh_sheets)
                                    wb["obsolete_replaced_sigs"] = {}
                                    if remote_mod:
                                        wb["gdrive_modified_time"] = remote_mod
                                    if remote_md5:
                                        wb["gdrive_md5"] = remote_md5
                                    if m_data.get("webViewLink"):
                                        wb["web_view_link"] = str(m_data["webViewLink"])
                                    if m_data.get("size"):
                                        wb["size_bytes"] = int(m_data["size"])
                                        wb["size_formatted"] = _format_file_size_human(int(m_data["size"]))
                                    wb["updated_at"] = datetime.now(manila_tz).strftime("%b %d, %Y %I:%M %p")
                                    if new_sig != old_sig:
                                        any_changed = True
                                        print(f"[🔄 SPREADSHEET AUTO-SYNC] Live cell update pulled from Google Sheets/Drive for '{wb.get('title')}' ({gd_id})")
                    except Exception as wb_sync_err:
                        print(f"[⚠️ SPREADSHEET GDRIVE CHECK WARNING] ({gd_id}): {wb_sync_err}")

                # 2b. When scanning all spreadsheets (no single target_id), also scan the Google Drive Vault folder for any new spreadsheet files
                if force_gdrive_check and not target_clean:
                    folder_id = gdrive_ensure_vault_folder()
                    if folder_id:
                        q_str = (
                            f"'{folder_id}' in parents and trashed=false and ("
                            f"mimeType='{XLSX_MIME_TYPE}' or mimeType='{XLS_MIME_TYPE}' or mimeType='{GOOGLE_SHEETS_MIME_TYPE}' "
                            f"or name contains '.xlsx' or name contains '.xls')"
                        )
                        list_r = HTTP_SESSION.get(
                            "https://www.googleapis.com/drive/v3/files",
                            headers=headers,
                            params={
                                "q": q_str,
                                "fields": "files(id,name,mimeType,modifiedTime,md5Checksum,size,webViewLink)",
                                "pageSize": 50
                            },
                            timeout=15
                        )
                        if list_r.status_code == 200:
                            remote_files = (list_r.json() or {}).get("files") or []
                            known_gd_ids = {str(w.get("gdrive_file_id") or "") for w in workbooks if w.get("gdrive_file_id")}
                            existing_vault_ids = {str(x.get("file_id") or "") for x in vault_files}
                            for rf in remote_files:
                                r_id = str(rf.get("id") or "").strip()
                                r_name = str(rf.get("name") or "Spreadsheet.xlsx").strip()
                                r_mime = str(rf.get("mimeType") or "").strip()
                                if not r_id or r_id in known_gd_ids:
                                    continue
                                if not _is_spreadsheet_filename_or_mime(r_name, r_mime):
                                    continue
                                display_title = re.sub(r"^file_[a-f0-9]{10,16}_", "", r_name)
                                if not display_title.lower().endswith((".xlsx", ".xls")):
                                    display_title = f"{display_title}.xlsx"
                                parsed_sh = _download_and_parse_gdrive_spreadsheet(r_id, display_title, r_mime, prefer_live_sheets_export=True)
                                if not parsed_sh:
                                    continue
                                new_fid = _generate_python_automation_file_id(existing_vault_ids)
                                existing_vault_ids.add(new_fid)
                                new_wb_id = f"wb_{new_fid}"
                                sz_b = int(rf.get("size") or 0)
                                gd_info = {
                                    "gdrive_file_id": r_id,
                                    "gdrive_file_name": r_name,
                                    "gdrive_modified_time": str(rf.get("modifiedTime") or ""),
                                    "gdrive_md5": str(rf.get("md5Checksum") or ""),
                                    "web_view_link": str(rf.get("webViewLink") or f"https://drive.google.com/file/d/{r_id}/view")
                                }
                                _register_or_update_spreadsheet_in_files_vault(
                                    py_file_id=new_fid,
                                    filename=display_title,
                                    size_bytes=sz_b,
                                    gdrive_info=gd_info,
                                    workbook_id=new_wb_id
                                )
                                vault_changed = True
                                workbooks.insert(0, {
                                    "workbook_id": new_wb_id,
                                    "file_id": new_fid,
                                    "gdrive_file_id": r_id,
                                    "gdrive_file_name": r_name,
                                    "gdrive_modified_time": str(rf.get("modifiedTime") or ""),
                                    "gdrive_md5": str(rf.get("md5Checksum") or ""),
                                    "web_view_link": gd_info["web_view_link"],
                                    "title": display_title,
                                    "storage_provider": "google_drive",
                                    "size_bytes": sz_b,
                                    "size_formatted": _format_file_size_human(sz_b),
                                    "sheet_count": len(parsed_sh),
                                    "updated_at": datetime.now(manila_tz).strftime("%b %d, %Y %I:%M %p"),
                                    "sheets": parsed_sh
                                })
                                known_gd_ids.add(r_id)
                                any_changed = True
            except Exception as gd_sync_err:
                print(f"[⚠️ SPREADSHEET GDRIVE FOLDER SYNC WARNING]: {gd_sync_err}")

        if vault_changed:
            with FILES_VAULT_LOCK:
                FILES_VAULT_STORE["files"] = vault_files
            _save_files_vault_store()
        with SPREADSHEETS_LOCK:
            SPREADSHEETS_STORE["workbooks"] = workbooks
        if any_changed:
            _save_spreadsheets_store()

        return workbooks, (any_changed or vault_changed)


@router.get("/api/spreadsheets")
async def api_list_spreadsheets(force: bool = False, sync_gdrive: bool = True):
    def _sync_list():
        _load_spreadsheets_store(force_cloud=False)
        _load_files_vault_store(force_cloud=False)
        workbooks, changed = _sync_spreadsheets_with_gdrive_and_vault(force_gdrive_check=bool(force or sync_gdrive))
        return {
            "status": "success",
            "count": len(workbooks),
            "synced_with_gdrive": is_gdrive_authorized(),
            "changed": changed,
            "workbooks": workbooks
        }
    return await run_in_threadpool(_sync_list)


@router.get("/api/spreadsheets/{workbook_id}/sync")
async def api_sync_single_spreadsheet(workbook_id: str, force: bool = True):
    """
    Live Two-Way Auto-Sync endpoint polled by the Spread Sheet modal when a spreadsheet is selected.
    Checks Google Sheets / Google Drive for any external edits made by the client and returns the latest workbook & cells.
    """
    clean_id = (workbook_id or "").strip()
    if not clean_id:
        return JSONResponse({"status": "error", "message": "Missing workbook_id."}, status_code=400)

    def _do_single_sync():
        workbooks, changed = _sync_spreadsheets_with_gdrive_and_vault(
            force_gdrive_check=bool(force),
            target_id=clean_id
        )
        target = next(
            (
                w for w in workbooks
                if str(w.get("workbook_id") or "") == clean_id
                or str(w.get("file_id") or "") == clean_id
                or str(w.get("gdrive_file_id") or "") == clean_id
            ),
            None
        )
        if not target:
            return None, workbooks, changed
        return target, workbooks, changed

    target_wb, all_wbs, was_changed = await run_in_threadpool(_do_single_sync)
    if not target_wb:
        return JSONResponse({"status": "error", "message": f"Spreadsheet '{clean_id}' not found."}, status_code=404)

    return JSONResponse(
        {
            "status": "success",
            "changed": was_changed,
            "synced_with_gdrive": is_gdrive_authorized(),
            "workbook": target_wb,
            "workbooks": all_wbs
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


@router.post("/api/spreadsheets/save")
async def api_save_spreadsheet_to_gdrive(request: Request):
    """
    Saves the custom spreadsheet (Columns A, B, C, D..., Rows 1, 2, 3, 4..., and renamed bottom sheet tabs)
    as a real .xlsx file directly to the connected Google Drive ('GlennBot_Media_Vault'),
    registers/updates it in the 'Files' modal (FILES_VAULT_STORE) with its own unique `file_id`,
    and updates SPREADSHEETS_STORE for two-way live auto-sync!
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    if not is_gdrive_authorized():
        return JSONResponse(
            {
                "status": "error",
                "needs_oauth": True,
                "message": "Google Drive is not connected yet. Please connect your Google Drive in the 'Files' modal first."
            },
            status_code=400
        )

    wb_id = str(body.get("workbook_id") or "").strip()
    if wb_id == "wb_default_glennbot":
        wb_id = ""
    req_file_id = str(body.get("file_id") or "").strip()
    req_gdrive_id = str(body.get("gdrive_file_id") or "").strip()

    raw_title = str(body.get("title") or "GlennBot_Spreadsheet.xlsx").strip()
    if not raw_title.lower().endswith((".xlsx", ".xls")):
        raw_title = f"{raw_title}.xlsx"
    # Always save as standard OpenXML .xlsx binary
    save_filename = f"{os.path.splitext(raw_title)[0]}.xlsx" if raw_title.lower().endswith(".xls") else raw_title

    raw_sheets = body.get("sheets") or []
    if not isinstance(raw_sheets, list) or not raw_sheets:
        raw_sheets = [{"id": "sheet_1", "name": "Sheet1", "cells": {}, "row_count": 25, "col_count": 10}]

    normalized_sheets: List[Dict[str, Any]] = []
    for idx, sh in enumerate(raw_sheets, start=1):
        s_name = _sanitize_excel_sheet_name(sh.get("name") or f"Sheet{idx}", f"Sheet{idx}")
        s_cells = {}
        for k, v in (sh.get("cells") or {}).items():
            if v is not None and str(v).strip() != "":
                s_cells[str(k).upper()] = _format_spreadsheet_cell_value(v, "")
        normalized_sheets.append({
            "id": str(sh.get("id") or f"sheet_{idx}"),
            "name": s_name,
            "row_count": max(10, min(int(sh.get("row_count") or 25), 500)),
            "col_count": max(5, min(int(sh.get("col_count") or 10), 52)),
            "cells": s_cells,
            "wrap_cells": dict(sh.get("wrap_cells") or {}) if isinstance(sh.get("wrap_cells"), dict) else {},
            "col_widths": dict(sh.get("col_widths") or {}) if isinstance(sh.get("col_widths"), dict) else {},
            "row_heights": dict(sh.get("row_heights") or {}) if isinstance(sh.get("row_heights"), dict) else {},
        })

    def _sync_save_to_gdrive():
        store = _load_spreadsheets_store(force_cloud=False)
        workbooks: List[Dict[str, Any]] = list(store.get("workbooks") or [])
        v_store = _load_files_vault_store(force_cloud=False)
        vault_files: List[Dict[str, Any]] = list(v_store.get("files") or [])
        existing_fids = {str(x.get("file_id") or "") for x in vault_files}

        existing_idx = -1
        existing_wb = None
        for i, w in enumerate(workbooks):
            if (wb_id and str(w.get("workbook_id") or "") == wb_id) or (req_file_id and str(w.get("file_id") or "") == req_file_id):
                existing_idx = i
                existing_wb = w
                break

        py_file_id = req_file_id or (str(existing_wb.get("file_id") or "") if existing_wb else "")
        if not py_file_id:
            py_file_id = _generate_python_automation_file_id(existing_fids)

        final_wb_id = wb_id or (str(existing_wb.get("workbook_id") or "") if existing_wb else "") or f"wb_{py_file_id}"
        existing_gd_id = req_gdrive_id or (str(existing_wb.get("gdrive_file_id") or "") if existing_wb else "")

        # Track previous signature so stale Google Docs export cache never reverts this save
        now_save_ts = time.time()
        obsolete_sigs: Dict[str, float] = {}
        if existing_wb and isinstance(existing_wb.get("obsolete_replaced_sigs"), dict):
            for k_sig, ts_val in existing_wb["obsolete_replaced_sigs"].items():
                try:
                    if (now_save_ts - float(ts_val)) < 120.0:
                        obsolete_sigs[str(k_sig)] = float(ts_val)
                except Exception:
                    pass
        prev_sig = _compute_sheets_signature(existing_wb.get("sheets")) if existing_wb else ""
        new_save_sig = _compute_sheets_signature(normalized_sheets)
        if prev_sig and prev_sig != new_save_sig:
            obsolete_sigs[prev_sig] = now_save_ts
        obsolete_sigs.pop(new_save_sig, None)

        # 1. Build genuine .xlsx binary in Python
        xlsx_bytes = build_xlsx_bytes_from_sheets(normalized_sheets)

        wb_record: Dict[str, Any] = {
            "workbook_id": final_wb_id,
            "last_local_save_ts": now_save_ts,
            "last_edit_source": "glennbot",
            "obsolete_replaced_sigs": obsolete_sigs
        }

        # 2. Upload or update in-place in Google Drive ('GlennBot_Media_Vault') + push live cells via Google Sheets API v4
        gd_info = _upload_or_update_spreadsheet_on_gdrive(
            xlsx_bytes=xlsx_bytes,
            filename=save_filename,
            existing_gdrive_file_id=existing_gd_id,
            py_file_id=py_file_id,
            sheets=normalized_sheets,
            wb_ref=wb_record
        )

        # 3. Register or update in 'Files' modal (FILES_VAULT_STORE) with its own file_id
        vault_rec = _register_or_update_spreadsheet_in_files_vault(
            py_file_id=py_file_id,
            filename=save_filename,
            size_bytes=len(xlsx_bytes),
            gdrive_info=gd_info,
            workbook_id=final_wb_id
        )

        now_str = datetime.now(manila_tz).strftime("%b %d, %Y %I:%M %p")
        wb_record.update({
            "workbook_id": final_wb_id,
            "file_id": vault_rec["file_id"],
            "gdrive_file_id": gd_info["gdrive_file_id"],
            "gdrive_file_name": gd_info["gdrive_file_name"],
            "gdrive_modified_time": gd_info.get("gdrive_modified_time") or "",
            "gdrive_md5": gd_info.get("gdrive_md5") or "",
            "last_local_save_ts": time.time(),
            "last_edit_source": "glennbot",
            "obsolete_replaced_sigs": obsolete_sigs,
            "web_view_link": gd_info.get("web_view_link") or "",
            "title": save_filename,
            "storage_provider": "google_drive",
            "cloudinary_xlsx_url": f"/api/files/{vault_rec['file_id']}/stream",
            "size_bytes": len(xlsx_bytes),
            "size_formatted": _format_file_size_human(len(xlsx_bytes)),
            "sheet_count": len(normalized_sheets),
            "updated_at": now_str,
            "sheets": normalized_sheets
        })

        if existing_idx >= 0:
            workbooks[existing_idx] = wb_record
        else:
            workbooks.insert(0, wb_record)

        with SPREADSHEETS_LOCK:
            SPREADSHEETS_STORE["workbooks"] = workbooks
        _save_spreadsheets_store()

        refreshed_vault = [_refresh_vault_file_entry_urls(f) for f in (FILES_VAULT_STORE.get("files") or [])]
        return wb_record, workbooks, vault_rec, refreshed_vault

    try:
        wb_record, workbooks, vault_rec, refreshed_vault = await run_in_threadpool(_sync_save_to_gdrive)
        return {
            "status": "success",
            "message": f"Saved '{wb_record['title']}' to Google Drive ({GOOGLE_DRIVE_FOLDER_NAME}) with File ID {wb_record['file_id']}!",
            "workbook": wb_record,
            "workbooks": workbooks,
            "vault_file": vault_rec,
            "files": refreshed_vault
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/spreadsheets/import")
async def api_import_local_xlsx_spreadsheet(file: UploadFile = File(...)):
    """
    Imports a local .xlsx or .xls file into the custom Spread Sheet modal.
    Strictly rejects .xlsx files if Python detects graphs/charts, images, drawings, shapes, or embedded objects.
    """
    if not file or not file.filename:
        return JSONResponse({"status": "error", "rejected": True, "message": "No spreadsheet file (.xlsx or .xls) provided."}, status_code=400)

    file_bytes = await file.read()
    validation_res = await run_in_threadpool(lambda: validate_and_parse_xlsx_bytes(file_bytes, file.filename, strict_reject_media=True))
    if validation_res.get("status") != "success" or validation_res.get("rejected"):
        return JSONResponse(validation_res, status_code=400)

    return validation_res


@router.get("/api/spreadsheets/{workbook_id}/download")
async def api_download_spreadsheet_xlsx(workbook_id: str):
    return await run_in_threadpool(lambda: _download_spreadsheet_xlsx_sync(workbook_id))


def _download_spreadsheet_xlsx_sync(workbook_id: str):
    clean_id = (workbook_id or "").strip()
    store = _load_spreadsheets_store(force_cloud=False)
    target = next(
        (
            w for w in (store.get("workbooks") or [])
            if str(w.get("workbook_id") or "") == clean_id
            or str(w.get("file_id") or "") == clean_id
        ),
        None
    )
    if not target:
        return JSONResponse({"status": "error", "message": f"Workbook '{clean_id}' not found."}, status_code=404)

    xlsx_bytes = build_xlsx_bytes_from_sheets(target.get("sheets") or [])
    dl_name = str(target.get("title") or f"{clean_id}.xlsx")
    if not dl_name.lower().endswith(".xlsx"):
        dl_name = f"{os.path.splitext(dl_name)[0]}.xlsx"
    safe_dl = re.sub(r'[^a-zA-Z0-9._-]', '_', dl_name)

    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MIME_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{safe_dl}"'}
    )


@router.post("/api/spreadsheets/export-xlsx")
async def api_export_current_spreadsheet_xlsx(request: Request):
    """
    Exports any in-memory or saved workbook directly as a standards-compliant .xlsx binary,
    preserving all cells, formulas, column widths, row heights, and wrap_cells.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = str(body.get("title") or "GlennBot_Spreadsheet.xlsx").strip()
    if not title.lower().endswith(".xlsx"):
        title = f"{os.path.splitext(title)[0] or 'GlennBot_Spreadsheet'}.xlsx"
    safe_dl = re.sub(r'[^a-zA-Z0-9._-]', '_', title)
    raw_sheets = body.get("sheets") or []
    xlsx_bytes = await run_in_threadpool(lambda: build_xlsx_bytes_from_sheets(raw_sheets))
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MIME_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{safe_dl}"'}
    )


@router.post("/api/spreadsheets/save-layout")
async def api_save_spreadsheet_layout_state(request: Request):
    """
    Persists custom column widths, row heights, and per-cell wrap text into SPREADSHEETS_STORE
    (and local/cloud cache) immediately when the user resizes a row/column or toggles Wrap Text.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    wb_id = str(body.get("workbook_id") or "").strip()
    file_id = str(body.get("file_id") or "").strip()
    title = str(body.get("title") or "").strip()
    incoming_sheets = body.get("sheets") or []
    if not isinstance(incoming_sheets, list):
        return JSONResponse({"status": "error", "message": "sheets must be a list."}, status_code=400)

    def _sync_update_layout():
        store = _load_spreadsheets_store(force_cloud=False)
        workbooks: List[Dict[str, Any]] = list(store.get("workbooks") or [])
        target_wb = None
        for w in workbooks:
            if (wb_id and str(w.get("workbook_id") or "") == wb_id) or (file_id and str(w.get("file_id") or "") == file_id):
                target_wb = w
                break
            if not wb_id and not file_id and title and str(w.get("title") or "").lower() == title.lower():
                target_wb = w
                break
        if not target_wb:
            return False

        by_name = {str(s.get("name") or ""): s for s in incoming_sheets if isinstance(s, dict)}
        for idx, sh in enumerate(target_wb.get("sheets") or []):
            inc = by_name.get(str(sh.get("name") or "")) or (incoming_sheets[idx] if idx < len(incoming_sheets) else None)
            if isinstance(inc, dict):
                if isinstance(inc.get("wrap_cells"), dict):
                    sh["wrap_cells"] = dict(inc.get("wrap_cells") or {})
                if isinstance(inc.get("col_widths"), dict):
                    sh["col_widths"] = dict(inc.get("col_widths") or {})
                if isinstance(inc.get("row_heights"), dict):
                    sh["row_heights"] = dict(inc.get("row_heights") or {})
                if isinstance(inc.get("row_count"), int):
                    sh["row_count"] = max(10, min(int(inc["row_count"]), 500))
                if isinstance(inc.get("col_count"), int):
                    sh["col_count"] = max(5, min(int(inc["col_count"]), 52))
        target_wb["last_local_save_ts"] = time.time()
        with SPREADSHEETS_LOCK:
            SPREADSHEETS_STORE["workbooks"] = workbooks
        _save_spreadsheets_store()
        return True

    updated = await run_in_threadpool(_sync_update_layout)
    return {"status": "success", "updated_in_store": updated}


@router.delete("/api/spreadsheets/{workbook_id}")
async def api_delete_spreadsheet_workbook(workbook_id: str):
    return await run_in_threadpool(lambda: _delete_spreadsheet_workbook_sync(workbook_id))


def _delete_spreadsheet_workbook_sync(workbook_id: str):
    clean_id = (workbook_id or "").strip()
    store = _load_spreadsheets_store(force_cloud=False)
    workbooks: List[Dict[str, Any]] = list(store.get("workbooks") or [])
    target = next(
        (
            w for w in workbooks
            if str(w.get("workbook_id") or "") == clean_id
            or str(w.get("file_id") or "") == clean_id
        ),
        None
    )
    if not target:
        return JSONResponse({"status": "error", "message": f"Workbook '{clean_id}' not found."}, status_code=404)

    target_wb_id = str(target.get("workbook_id") or "")
    target_fid = str(target.get("file_id") or "").strip()
    target_gd_id = str(target.get("gdrive_file_id") or "").strip()
    target_gd_name = str(target.get("gdrive_file_name") or target.get("title") or "").strip()

    if target_gd_id:
        try:
            delete_media_from_gdrive(target_gd_id, target_gd_name)
        except Exception as e:
            print(f"[⚠️ SPREADSHEET GDRIVE DELETE WARNING]: {e}")

    pub_id = str(target.get("cloudinary_public_id") or "").strip()
    if pub_id and CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        try:
            cloudinary.uploader.destroy(pub_id, resource_type="raw", invalidate=True)
        except Exception:
            pass

    remaining = [
        w for w in workbooks
        if str(w.get("workbook_id") or "") != target_wb_id
        and (not target_fid or str(w.get("file_id") or "") != target_fid)
    ]

    with SPREADSHEETS_LOCK:
        SPREADSHEETS_STORE["workbooks"] = remaining
    _save_spreadsheets_store()

    # Also remove from FILES_VAULT_STORE so 'Files' modal stays in sync
    refreshed_vault = []
    try:
        v_store = _load_files_vault_store(force_cloud=False)
        v_files = list(v_store.get("files") or [])
        rem_vault = [
            f for f in v_files
            if (not target_fid or str(f.get("file_id") or "") != target_fid)
            and (not target_gd_id or str(f.get("gdrive_file_id") or "") != target_gd_id)
        ]
        if len(rem_vault) != len(v_files):
            with FILES_VAULT_LOCK:
                FILES_VAULT_STORE["files"] = rem_vault
            _save_files_vault_store()
        refreshed_vault = [_refresh_vault_file_entry_urls(f) for f in rem_vault]
    except Exception:
        pass

    return {
        "status": "success",
        "deleted_workbook_id": target_wb_id,
        "deleted_file_id": target_fid,
        "message": f"Deleted '{target.get('title')}' from Google Drive & Files Vault!",
        "workbooks": remaining,
        "files": refreshed_vault
    }


# ==============================================================================
# --- ADDITIONAL /api/v1/* ENDPOINTS FOR FULL N8N COVERAGE OF ALL MODALS ---
# ==============================================================================
def _extract_sheet_headers_and_next_row(sheet_obj: Dict[str, Any]) -> Tuple[Dict[str, str], int]:
    """
    Inspects a GlennBot spreadsheet sheet's `cells` dict (e.g. {"A1": "Client Name", "B1": "Email Address"})
    and returns (col_letter_to_header_map, next_empty_row_number).
    """
    cells_map = sheet_obj.get("cells") or {}
    headers_by_col: Dict[str, str] = {}
    max_used_row = 0
    for coord_str, val in cells_map.items():
        if val is None or str(val).strip() == "":
            continue
        parsed = _split_cell_coord(coord_str)
        if not parsed:
            continue
        col_let, _, row_num = parsed
        if row_num == 1:
            headers_by_col[col_let] = str(val).strip()
        if row_num > max_used_row:
            max_used_row = row_num
    return headers_by_col, max(1, max_used_row + 1)


def _build_sheet_structured_rows(sheet_obj: Dict[str, Any]) -> Tuple[Dict[str, str], List[Dict[str, Any]], Dict[str, str]]:
    """
    Builds structured row dictionaries from a sheet's `cells` map so n8n workflows can easily
    read values by cell coordinate (`cells.B2`), by column letter (`row.B`), or by Row 1 header name (`row['Phone']`).
    """
    raw_cells: Dict[str, str] = dict(sheet_obj.get("cells") or {})
    evaluated_cells: Dict[str, str] = {}
    headers_by_col: Dict[str, str] = {}
    rows_by_num: Dict[int, Dict[str, str]] = {}

    for coord_str, raw_val in raw_cells.items():
        if raw_val is None or str(raw_val).strip() == "":
            continue
        parsed = _split_cell_coord(coord_str)
        if not parsed:
            continue
        col_let, _, row_num = parsed
        eval_v = _evaluate_spreadsheet_formula(str(raw_val), raw_cells)
        evaluated_cells[f"{col_let}{row_num}"] = eval_v
        if row_num == 1:
            headers_by_col[col_let] = eval_v.strip()
        rows_by_num.setdefault(row_num, {})[col_let] = eval_v

    structured_rows: List[Dict[str, Any]] = []
    start_row = 2 if (headers_by_col and len(rows_by_num) > 1) else 1
    for r_num in sorted(rows_by_num.keys()):
        if r_num < start_row:
            continue
        col_vals = rows_by_num[r_num]
        row_obj: Dict[str, Any] = {"_row_number": r_num}
        for c_let, val_str in col_vals.items():
            row_obj[c_let] = val_str
            hdr_name = headers_by_col.get(c_let)
            if hdr_name and hdr_name not in row_obj:
                row_obj[hdr_name] = val_str
        structured_rows.append(row_obj)

    return headers_by_col, structured_rows, evaluated_cells


def _find_workbook_by_query(workbooks: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return workbooks[0] if workbooks else None
    q_low = q.lower()
    for w in workbooks:
        if (
            str(w.get("workbook_id") or "") == q
            or str(w.get("file_id") or "") == q
            or str(w.get("gdrive_file_id") or "") == q
            or str(w.get("title") or "").lower() == q_low
            or q_low in str(w.get("title") or "").lower()
        ):
            return w
    return workbooks[0] if workbooks else None


def _sync_updated_workbook_to_cloudinary(target_wb: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synchronizes any workbook updated via /api/v1/spreadsheets/* directly to Google Drive
    and the 'Files' modal (FILES_VAULT_STORE), keeping the client's Google Drive file 100% in sync!
    """
    wb_id = str(target_wb.get("workbook_id") or "").strip()
    fid = str(target_wb.get("file_id") or "").strip()
    gd_id = str(target_wb.get("gdrive_file_id") or "").strip()
    raw_title = str(target_wb.get("title") or "GlennBot_Spreadsheet.xlsx").strip()
    if not raw_title.lower().endswith(".xlsx"):
        raw_title = f"{os.path.splitext(raw_title)[0]}.xlsx"

    sheets_list = target_wb.get("sheets") or []
    xlsx_bytes = build_xlsx_bytes_from_sheets(sheets_list)

    if is_gdrive_authorized():
        try:
            v_store = _load_files_vault_store(force_cloud=False)
            existing_fids = {str(x.get("file_id") or "") for x in (v_store.get("files") or [])}
            if not fid:
                fid = _generate_python_automation_file_id(existing_fids)
            if not wb_id:
                wb_id = f"wb_{fid}"

            target_wb["last_local_save_ts"] = time.time()
            target_wb["last_edit_source"] = "glennbot"
            gd_info = _upload_or_update_spreadsheet_on_gdrive(
                xlsx_bytes=xlsx_bytes,
                filename=raw_title,
                existing_gdrive_file_id=gd_id,
                py_file_id=fid,
                sheets=sheets_list,
                wb_ref=target_wb
            )
            vault_rec = _register_or_update_spreadsheet_in_files_vault(
                py_file_id=fid,
                filename=raw_title,
                size_bytes=len(xlsx_bytes),
                gdrive_info=gd_info,
                workbook_id=wb_id
            )
            target_wb["workbook_id"] = wb_id
            target_wb["file_id"] = vault_rec["file_id"]
            target_wb["gdrive_file_id"] = gd_info["gdrive_file_id"]
            target_wb["gdrive_file_name"] = gd_info["gdrive_file_name"]
            target_wb["gdrive_modified_time"] = gd_info.get("gdrive_modified_time") or ""
            target_wb["gdrive_md5"] = gd_info.get("gdrive_md5") or ""
            target_wb["last_local_save_ts"] = time.time()
            target_wb["last_edit_source"] = "glennbot"
            target_wb["web_view_link"] = gd_info.get("web_view_link") or ""
            target_wb["storage_provider"] = "google_drive"
        except Exception as e:
            print(f"[⚠️ V1 SPREADSHEET GDRIVE SYNC WARNING]: {e}")

    target_wb["size_bytes"] = len(xlsx_bytes)
    target_wb["size_formatted"] = _format_file_size_human(len(xlsx_bytes))
    target_wb["sheet_count"] = len(sheets_list)
    target_wb["updated_at"] = datetime.now(manila_tz).strftime("%b %d, %Y %I:%M %p")
    _save_spreadsheets_store()
    return target_wb


@router.get("/api/v1/spreadsheets")
async def api_v1_list_spreadsheets(
    request: Request,
    workbook_id: str = "",
    file_id: str = "",
    force: bool = False,
    sync_gdrive: bool = True
):
    """
    Lists all saved/synced .xlsx & .xls workbooks in the Spread Sheet modal (View 10),
    automatically syncing latest edits from Google Drive first so n8n always sees live cell values!
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    query_id = (workbook_id or file_id or "").strip()
    workbooks, _ = await run_in_threadpool(
        lambda: _sync_spreadsheets_with_gdrive_and_vault(
            force_gdrive_check=bool(force or sync_gdrive),
            target_id=query_id
        )
    )

    if query_id:
        matched = _find_workbook_by_query(workbooks, query_id)
        workbooks = [matched] if matched else []

    enriched = []
    for wb in workbooks:
        wb_copy = dict(wb)
        sheet_summaries = []
        for sh in (wb.get("sheets") or []):
            hdrs, next_r = _extract_sheet_headers_and_next_row(sh)
            _, s_rows, eval_cells = _build_sheet_structured_rows(sh)
            sheet_summaries.append({
                "id": sh.get("id"),
                "name": sh.get("name"),
                "headers_row_1": hdrs,
                "next_empty_row": next_r,
                "cell_count": len(eval_cells),
                "row_count": len(s_rows),
                "cells": eval_cells,
                "rows": s_rows
            })
        wb_copy["sheet_summaries"] = sheet_summaries
        enriched.append(wb_copy)

    return {
        "status": "success",
        "count": len(enriched),
        "workbooks": enriched
    }


@router.api_route("/api/v1/spreadsheets/read", methods=["GET", "POST"])
async def api_v1_read_spreadsheet_cells(
    request: Request,
    workbook_id: str = "",
    file_id: str = "",
    sheet_name: str = "",
    cell: str = "",
    row: int = 0,
    column: str = "",
    lookup_column: str = "",
    lookup_value: str = "",
    sync_gdrive: bool = True
):
    """
    Reads live cell values, row objects, or column lookups from a Google Drive synced spreadsheet (.xlsx / .xls) for n8n automations!
    Supports both GET query params and POST JSON body.
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    body: Dict[str, Any] = {}
    if request.method == "POST":
        try:
            body = await request.json() or {}
        except Exception:
            body = {}

    q_wb = str(body.get("workbook_id") or body.get("file_id") or body.get("title") or workbook_id or file_id or "").strip()
    q_sheet = str(body.get("sheet_name") or body.get("sheet") or sheet_name or "").strip()
    q_cell = str(body.get("cell") or body.get("coord") or cell or "").strip().upper()
    q_row = int(body.get("row") or row or 0)
    q_col = str(body.get("column") or body.get("col") or column or "").strip()
    q_lookup_col = str(body.get("lookup_column") or lookup_column or "").strip()
    q_lookup_val = str(body.get("lookup_value") if body.get("lookup_value") is not None else lookup_value).strip()
    do_sync = bool(body.get("sync_gdrive", sync_gdrive))

    workbooks, _ = await run_in_threadpool(
        lambda: _sync_spreadsheets_with_gdrive_and_vault(
            force_gdrive_check=do_sync,
            target_id=q_wb
        )
    )
    target_wb = _find_workbook_by_query(workbooks, q_wb)
    if not target_wb:
        return JSONResponse({"status": "error", "message": f"Spreadsheet '{q_wb or 'default'}' not found in Google Drive / Files Vault."}, status_code=404)

    sheets_list = target_wb.get("sheets") or []
    if not sheets_list:
        return JSONResponse({"status": "error", "message": "Spreadsheet has no sheets."}, status_code=404)

    target_sheet = next(
        (s for s in sheets_list if q_sheet and (str(s.get("name") or "").lower() == q_sheet.lower() or str(s.get("id") or "") == q_sheet)),
        sheets_list[0]
    )

    headers_by_col, structured_rows, evaluated_cells = _build_sheet_structured_rows(target_sheet)
    _, next_empty_row = _extract_sheet_headers_and_next_row(target_sheet)

    cell_val = evaluated_cells.get(q_cell, "") if q_cell else ""
    matched_row_data: Dict[str, Any] = {}

    if q_row > 0:
        for r_obj in structured_rows:
            if int(r_obj.get("_row_number") or 0) == q_row:
                matched_row_data = r_obj
                break
        if not matched_row_data:
            # Construct directly from evaluated_cells for that row number
            temp_r: Dict[str, Any] = {"_row_number": q_row}
            for c_coord, c_v in evaluated_cells.items():
                parsed_c = _split_cell_coord(c_coord)
                if parsed_c and parsed_c[2] == q_row:
                    c_let = parsed_c[0]
                    temp_r[c_let] = c_v
                    if headers_by_col.get(c_let):
                        temp_r[headers_by_col[c_let]] = c_v
            if len(temp_r) > 1:
                matched_row_data = temp_r
    elif q_lookup_col and q_lookup_val:
        lk_low = q_lookup_val.lower()
        for r_obj in structured_rows:
            cand = str(r_obj.get(q_lookup_col) or r_obj.get(q_lookup_col.upper()) or "").strip()
            if cand.lower() == lk_low or ( len(lk_low) >= 7 and lk_low in cand.lower() ):
                matched_row_data = r_obj
                break
    elif structured_rows:
        matched_row_data = structured_rows[0]

    column_values: List[str] = []
    if q_col:
        for r_obj in structured_rows:
            v_c = r_obj.get(q_col) or r_obj.get(q_col.upper())
            if v_c is not None and str(v_c).strip() != "":
                column_values.append(str(v_c))

    if not cell_val and q_col and matched_row_data:
        cell_val = str(matched_row_data.get(q_col) or matched_row_data.get(q_col.upper()) or "")

    return {
        "status": "success",
        "workbook_id": target_wb.get("workbook_id"),
        "file_id": target_wb.get("file_id") or "",
        "gdrive_file_id": target_wb.get("gdrive_file_id") or "",
        "title": target_wb.get("title"),
        "sheet_name": target_sheet.get("name"),
        "cell": q_cell,
        "value": cell_val,
        "headers": headers_by_col,
        "row_data": matched_row_data,
        "column_values": column_values,
        "cells": evaluated_cells,
        "rows": structured_rows,
        "row_count": len(structured_rows),
        "next_empty_row": next_empty_row
    }


@router.post("/api/v1/spreadsheets/append-row")
async def api_v1_append_spreadsheet_row(request: Request):
    """
    Appends a new row to a GlennBot .xlsx workbook in the Spread Sheet modal (View 10) from n8n
    and automatically syncs the updated .xlsx file to Google Drive & Files Vault!
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    wb_query = str(body.get("workbook_id") or body.get("file_id") or body.get("title") or "").strip()
    workbooks, _ = await run_in_threadpool(
        lambda: _sync_spreadsheets_with_gdrive_and_vault(force_gdrive_check=True, target_id=wb_query)
    )
    target_wb = _find_workbook_by_query(workbooks, wb_query)
    if not target_wb:
        target_wb = {
            "workbook_id": f"wb_{uuid.uuid4().hex[:8]}",
            "title": wb_query if wb_query.lower().endswith((".xlsx", ".xls")) else "GlennBot_Automation_Sheet.xlsx",
            "sheets": [{"id": "sheet_1", "name": "Sheet1", "row_count": 25, "col_count": 10, "cells": {}}]
        }
        workbooks.insert(0, target_wb)
        with SPREADSHEETS_LOCK:
            SPREADSHEETS_STORE["workbooks"] = workbooks

    sheets_list: List[Dict[str, Any]] = list(target_wb.get("sheets") or [])
    if not sheets_list:
        sheets_list = [{"id": "sheet_1", "name": "Sheet1", "row_count": 25, "col_count": 10, "cells": {}}]
        target_wb["sheets"] = sheets_list

    sheet_query = str(body.get("sheet_name") or body.get("sheet") or "").strip()
    target_sheet = None
    if sheet_query:
        target_sheet = next(
            (s for s in sheets_list if str(s.get("name") or "").lower() == sheet_query.lower() or str(s.get("id") or "") == sheet_query),
            None
        )
    if not target_sheet:
        target_sheet = sheets_list[0]

    cells_map: Dict[str, str] = target_sheet.setdefault("cells", {})
    headers_by_col, target_row = _extract_sheet_headers_and_next_row(target_sheet)
    header_name_to_col = {str(h_val).strip().lower(): c_let for c_let, h_val in headers_by_col.items() if h_val}

    raw_row_data = body.get("row") or body.get("values") or body.get("cells") or body.get("data")
    if not raw_row_data and (body.get("colA") is not None or body.get("colB") is not None):
        raw_row_data = {
            "A": body.get("colA") or "",
            "B": body.get("colB") or ""
        }
    written_cells: Dict[str, str] = {}

    explicit_row_num = int(body.get("row_number") or body.get("target_row") or body.get("targetRowNumber") or 0)
    if explicit_row_num >= 1:
        target_row = explicit_row_num

    # Optional native thread grouping: if thread_id is passed (or [Thread: ...] in Column A),
    # find any existing row in cells_map that belongs to the same comment thread and update that row in-place!
    req_thread_id = str(body.get("thread_id") or body.get("threadId") or "").strip()
    existing_thread_row: Optional[int] = None
    if req_thread_id:
        norm_req_tid = req_thread_id.split("_")[-1].strip()
        for coord_k, cell_v in list(cells_map.items()):
            parsed_c = _split_cell_coord(coord_k)
            if not parsed_c:
                continue
            c_let_k, _, r_num_k = parsed_c
            if c_let_k == "A" and r_num_k >= 1:
                cell_str = str(cell_v or "")
                m_th = re.search(r"\[Thread:\s*([^\]]+)\]", cell_str, re.I)
                if m_th:
                    tracked_ids = [x.strip().split("_")[-1] for x in m_th.group(1).split(",") if x.strip()]
                    if norm_req_tid in tracked_ids or req_thread_id in tracked_ids:
                        existing_thread_row = r_num_k
                        break
    if existing_thread_row is not None:
        target_row = existing_thread_row
        if isinstance(raw_row_data, dict) and "B" in raw_row_data and f"B{target_row}" in cells_map:
            prev_b = str(cells_map.get(f"B{target_row}") or "").strip()
            new_b = str(raw_row_data.get("B") or "").strip()
            if prev_b and new_b and new_b not in prev_b:
                raw_row_data = dict(raw_row_data)
                raw_row_data["B"] = f"{prev_b}\n{new_b}"

    if isinstance(raw_row_data, list):
        for col_idx, val in enumerate(raw_row_data):
            if val is not None and str(val).strip() != "":
                c_let = _col_idx_to_letter(col_idx)
                coord = f"{c_let}{target_row}"
                cells_map[coord] = str(val).strip()
                written_cells[coord] = str(val).strip()
    elif isinstance(raw_row_data, dict):
        for k_raw, v_raw in raw_row_data.items():
            if v_raw is None or str(v_raw).strip() == "":
                continue
            k_str = str(k_raw).strip()
            val_str = str(v_raw).strip()
            parsed_coord = _split_cell_coord(k_str)
            if parsed_coord:
                c_let, _, r_num = parsed_coord
                coord = f"{c_let}{r_num}"
                target_row = r_num
            elif re.match(r"^[A-Za-z]{1,2}$", k_str) and k_str.lower() not in header_name_to_col:
                coord = f"{k_str.upper()}{target_row}"
            elif k_str.lower() in header_name_to_col:
                coord = f"{header_name_to_col[k_str.lower()]}{target_row}"
            else:
                used_col_indices = [_letter_to_col_idx(c) for c in headers_by_col.keys()]
                next_col_idx = (max(used_col_indices) + 1) if used_col_indices else 0
                new_col_let = _col_idx_to_letter(next_col_idx)
                cells_map[f"{new_col_let}1"] = k_str
                headers_by_col[new_col_let] = k_str
                header_name_to_col[k_str.lower()] = new_col_let
                coord = f"{new_col_let}{target_row}"
            cells_map[coord] = val_str
            written_cells[coord] = val_str

    if not written_cells:
        default_col_mapping = [
            ("A", body.get("client_name") or body.get("name") or body.get("author_id") or body.get("author_name") or body.get("sender_name") or body.get("participant_name") or req_thread_id or ""),
            ("B", body.get("email_address") or body.get("email") or body.get("sender_email") or body.get("thread_transcript") or body.get("message") or ""),
            ("C", body.get("contact_number") or body.get("phone") or ""),
            ("D", body.get("platform") or ""),
            ("E", body.get("status") or body.get("category") or body.get("notes") or "")
        ]
        for c_let, v_val in default_col_mapping:
            if v_val is not None and str(v_val).strip() != "":
                coord = f"{c_let}{target_row}"
                cells_map[coord] = str(v_val).strip()
                written_cells[coord] = str(v_val).strip()

    if not written_cells:
        return JSONResponse({"status": "error", "message": "No row values provided. Pass 'row': {'A': '...', 'B': '...'} or top-level 'client_name', 'email_address', 'platform', 'status'."}, status_code=400)

    target_sheet["row_count"] = max(int(target_sheet.get("row_count") or 25), target_row + 5)
    await run_in_threadpool(lambda: _sync_updated_workbook_to_cloudinary(target_wb))

    return {
        "status": "success",
        "workbook_id": target_wb.get("workbook_id"),
        "file_id": target_wb.get("file_id") or "",
        "gdrive_file_id": target_wb.get("gdrive_file_id") or "",
        "title": target_wb.get("title"),
        "sheet_name": target_sheet.get("name"),
        "appended_row_number": target_row,
        "written_cells": written_cells,
        "message": f"Appended row #{target_row} ({len(written_cells)} cell(s)) to '{target_wb.get('title')}' [{target_sheet.get('name')}] and synced to Google Drive!"
    }


@router.post("/api/v1/spreadsheets/update-cells")
async def api_v1_update_spreadsheet_cells(request: Request):
    """
    Updates specific cell coordinates (e.g. {"A2": "Juan Dela Cruz", "E2": "Replied"}) in a GlennBot .xlsx spreadsheet from n8n
    and syncs the updated .xlsx file directly to Google Drive!
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body."}, status_code=400)

    wb_query = str(body.get("workbook_id") or body.get("file_id") or body.get("title") or "").strip()
    workbooks, _ = await run_in_threadpool(
        lambda: _sync_spreadsheets_with_gdrive_and_vault(force_gdrive_check=True, target_id=wb_query)
    )
    target_wb = _find_workbook_by_query(workbooks, wb_query)
    if not target_wb:
        return JSONResponse({"status": "error", "message": f"Spreadsheet '{wb_query}' not found."}, status_code=404)

    sheets_list = target_wb.setdefault("sheets", [{"id": "sheet_1", "name": "Sheet1", "row_count": 25, "col_count": 10, "cells": {}}])
    sheet_query = str(body.get("sheet_name") or body.get("sheet") or "").strip()
    target_sheet = next(
        (s for s in sheets_list if sheet_query and str(s.get("name") or "").lower() == sheet_query.lower()),
        sheets_list[0]
    )

    raw_cells = body.get("cells") if isinstance(body.get("cells"), dict) else {
        k: v for k, v in body.items() if _split_cell_coord(k) is not None
    }
    if not raw_cells:
        return JSONResponse({"status": "error", "message": "Provide 'cells' dict with cell coordinates (e.g. {'A2': 'Value', 'B2': '100'})."}, status_code=400)

    cells_map = target_sheet.setdefault("cells", {})
    updated_coords: Dict[str, str] = {}
    for coord_k, val_v in raw_cells.items():
        parsed = _split_cell_coord(coord_k)
        if not parsed:
            continue
        c_let, c_idx, r_num = parsed
        norm_coord = f"{c_let}{r_num}"
        v_str = str(val_v if val_v is not None else "").strip()
        if v_str == "":
            cells_map.pop(norm_coord, None)
        else:
            cells_map[norm_coord] = v_str
        updated_coords[norm_coord] = v_str
        target_sheet["row_count"] = max(int(target_sheet.get("row_count") or 25), r_num + 5)
        target_sheet["col_count"] = max(int(target_sheet.get("col_count") or 10), c_idx + 2)

    await run_in_threadpool(lambda: _sync_updated_workbook_to_cloudinary(target_wb))
    return {
        "status": "success",
        "workbook_id": target_wb.get("workbook_id"),
        "file_id": target_wb.get("file_id") or "",
        "gdrive_file_id": target_wb.get("gdrive_file_id") or "",
        "title": target_wb.get("title"),
        "sheet_name": target_sheet.get("name"),
        "updated_cells": updated_coords,
        "message": f"Updated {len(updated_coords)} cell(s) in '{target_wb.get('title')}' [{target_sheet.get('name')}] and synced to Google Drive!"
    }


@router.get("/api/v1/analytics")
async def api_v1_get_analytics(request: Request, period: str = "90d", force: bool = False):
    """
    Returns Social Media Analytics & Per-Page Insights (View 6) for n8n reporting/digest workflows.
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await run_in_threadpool(lambda: get_social_media_analytics(period=period, force=force))


@router.get("/api/v1/presets")
async def api_v1_get_presets(request: Request):
    """
    Returns saved platform/page selection presets (#preset-modal) for n8n workflows.
    """
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await run_in_threadpool(get_presets)


@router.delete("/api/v1/posts/{record_id}")
async def api_v1_delete_post_by_path(record_id: str, request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await run_in_threadpool(lambda: delete_scheduled_post(record_id))


@router.post("/api/v1/posts/delete")
async def api_v1_delete_post_by_body(request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    rec_id = str(body.get("record_id") or body.get("id") or "").strip()
    if not rec_id:
        return JSONResponse({"status": "error", "message": "'record_id' is required."}, status_code=400)
    return await run_in_threadpool(lambda: delete_scheduled_post(rec_id))


@router.post("/api/v1/comments/mark-read")
async def api_v1_mark_comments_read(request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    c_ids = body.get("comment_ids") or ([body["comment_id"]] if body.get("comment_id") else [])
    rec_id = str(body.get("record_id") or "").strip()
    plat = str(body.get("platform") or "").strip()
    return await run_in_threadpool(
        lambda: mark_comments_as_read(MarkReadPayload(comment_ids=c_ids, record_id=rec_id, platform=plat))
    )


@router.post("/api/v1/comments/dismiss")
async def api_v1_dismiss_comments(request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    c_ids = body.get("comment_ids") or ([body["comment_id"]] if body.get("comment_id") else [])
    clear_all_flag = bool(body.get("clear_all", False))
    return await run_in_threadpool(
        lambda: dismiss_or_clear_comment_notifications(DismissCommentsPayload(comment_ids=c_ids, clear_all=clear_all_flag))
    )


@router.post("/api/v1/messages/mark-read")
async def api_v1_mark_messages_read(request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    conv_ids = body.get("conversation_ids") or ([body["conversation_id"]] if body.get("conversation_id") else [])
    mark_all_flag = bool(body.get("mark_all", False))
    return await run_in_threadpool(
        lambda: mark_conversations_as_read(MarkMessagesReadPayload(conversation_ids=conv_ids, mark_all=mark_all_flag))
    )


@router.post("/api/v1/emails/trash")
async def api_v1_trash_email(request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await api_trash_single_account_email(request)


@router.delete("/api/v1/contacts/{contact_id}")
async def api_v1_delete_contact(contact_id: str, request: Request):
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await api_delete_crm_contact(contact_id)


