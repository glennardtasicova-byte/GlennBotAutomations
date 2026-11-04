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


def _evaluate_spreadsheet_formula(raw_val: str, cells_map: Dict[str, str], depth: int = 0) -> str:
    s = str(raw_val if raw_val is not None else "")
    if not s.startswith("=") or depth > 4:
        return s
    expr = s[1:].strip()

    def _resolve_num(ref_coord: str) -> float:
        v_str = _evaluate_spreadsheet_formula(cells_map.get(ref_coord.upper(), ""), cells_map, depth + 1)
        try:
            return float(str(v_str).replace(",", "").strip())
        except Exception:
            return 0.0

    m = re.match(r"^(SUM|AVERAGE|AVG|MIN|MAX|COUNT)\(([A-Za-z]+\d+):([A-Za-z]+\d+)\)$", expr, re.IGNORECASE)
    if m:
        fn = m.group(1).upper()
        s_coord = _split_cell_coord(m.group(2))
        e_coord = _split_cell_coord(m.group(3))
        if not s_coord or not e_coord:
            return "0"
        c_min, c_max = min(s_coord[1], e_coord[1]), max(s_coord[1], e_coord[1])
        r_min, r_max = min(s_coord[2], e_coord[2]), max(s_coord[2], e_coord[2])
        nums: List[float] = []
        for r_i in range(r_min, r_max + 1):
            for c_i in range(c_min, c_max + 1):
                nums.append(_resolve_num(f"{_col_idx_to_letter(c_i)}{r_i}"))
        if not nums:
            return "0"
        if fn == "SUM":
            res = sum(nums)
        elif fn in ("AVERAGE", "AVG"):
            res = round(sum(nums) / len(nums), 4)
        elif fn == "MIN":
            res = min(nums)
        elif fn == "MAX":
            res = max(nums)
        else:
            res = float(len(nums))
        return str(int(res)) if res == int(res) else str(res)
    return s


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
    Computes a deterministic canonical JSON signature of sheet names and cells
    so we can accurately detect when any cell or sheet in Google Sheets / Drive changed.
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
        norm.append({
            "name": str(sh.get("name") or "Sheet1"),
            "cells": clean_cells
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
                max_row = 25
                max_col = 10

                if w_path and w_path in names:
                    ws_root = ET.fromstring(zf.read(w_path))
                    row_seq = 0
                    for row_el in ws_root.iter():
                        if not (row_el.tag.endswith("}row") or row_el.tag == "row"):
                            continue
                        row_seq += 1
                        r_num = int(row_el.attrib.get("r") or row_seq)
                        max_row = max(max_row, r_num)
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
                            if formula_text and re.match(r"^=(SUM|AVERAGE|AVG|MIN|MAX|COUNT)\b", formula_text, re.IGNORECASE):
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
                    "row_count": max(25, min(max_row + 5, 500)),
                    "col_count": max(10, min(max_col + 2, 52))
                })

            if not parsed_sheets:
                parsed_sheets.append({
                    "id": f"sheet_1_{uuid.uuid4().hex[:6]}",
                    "name": "Sheet1",
                    "cells": {},
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
    from GlennBot's custom spreadsheet sheets (Columns A, B, C, D... and Rows 1, 2, 3, 4... + custom sheet names).
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
            "cells": dict(sh.get("cells") or {})
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

        # 5. xl/styles.xml
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '</styleSheet>'
        )
        zf.writestr("xl/styles.xml", styles_xml)

        # 6. xl/worksheets/sheet{i}.xml
        for i, sh in enumerate(normalized_sheets, start=1):
            cells_dict: Dict[str, str] = sh["cells"]
            rows_bucket: Dict[int, List[tuple]] = {}
            for coord_key, raw_val in cells_dict.items():
                val_str = _format_spreadsheet_cell_value(raw_val, "")
                if val_str == "":
                    continue
                parsed = _split_cell_coord(coord_key)
                if not parsed:
                    continue
                col_l, col_idx, row_n = parsed
                rows_bucket.setdefault(row_n, []).append((col_idx, f"{col_l}{row_n}", val_str))

            row_xml_chunks: List[str] = []
            for r_num in sorted(rows_bucket.keys()):
                row_cells = sorted(rows_bucket[r_num], key=lambda x: x[0])
                cell_xml_chunks: List[str] = []
                for _, ref_str, v_str in row_cells:
                    clean_v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", v_str)
                    stripped_v = clean_v.strip()
                    if stripped_v.startswith("=") and len(stripped_v) > 1:
                        f_body = xml_escape(stripped_v[1:].strip())
                        cell_xml_chunks.append(f'<c r="{ref_str}"><f>{f_body}</f></c>')
                    elif (
                        re.match(r"^-?\d+(\.\d+)?$", stripped_v)
                        and not (len(stripped_v) > 1 and stripped_v.startswith("0") and not stripped_v.startswith("0."))
                        and len(stripped_v.lstrip("-").split(".")[0]) <= 11
                    ):
                        cell_xml_chunks.append(f'<c r="{ref_str}" t="n"><v>{stripped_v}</v></c>')
                    else:
                        escaped_text = xml_escape(clean_v)
                        cell_xml_chunks.append(f'<c r="{ref_str}" t="inlineStr"><is><t xml:space="preserve">{escaped_text}</t></is></c>')
                row_xml_chunks.append(f'<row r="{r_num}">{"".join(cell_xml_chunks)}</row>')

            ws_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
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


def _upload_or_update_spreadsheet_on_gdrive(
    xlsx_bytes: bytes,
    filename: str,
    existing_gdrive_file_id: str = "",
    py_file_id: str = ""
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

    # 1. If we already have a Google Drive File ID, update its binary content in-place via PATCH
    if clean_gd_id and "/" not in clean_gd_id:
        try:
            patch_url = (
                f"https://www.googleapis.com/upload/drive/v3/files/{urllib.parse.quote(clean_gd_id, safe='')}"
                f"?uploadType=media&fields=id,name,mimeType,modifiedTime,md5Checksum,size,webViewLink"
            )
            patch_resp = requests.patch(
                patch_url,
                headers={
                    "Authorization": f"Bearer {acc_tok}",
                    "Content-Type": XLSX_MIME_TYPE,
                    "Content-Length": str(len(xlsx_bytes))
                },
                data=xlsx_bytes,
                timeout=120
            )
            if patch_resp.status_code in (200, 201):
                meta = patch_resp.json() or {}
                gd_id = str(meta.get("id") or clean_gd_id).strip()
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
                    # Skip pulling for 4 seconds immediately after a local save from GlennBot so we don't overwrite in-flight edits
                    last_local_save = float(wb.get("last_local_save_ts") or 0.0)
                    if (now_ts - last_local_save) < 4.0:
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

                        # When syncing the active target workbook (target_clean), ALWAYS pull live bytes
                        # because Google Sheets web editor buffers edits before Drive metadatamodifiedTime updates!
                        should_download_live = bool(target_clean) or is_meta_modified
                        if should_download_live:
                            # If the last edit was from GlennBot and Drive metadata hasn't changed yet, read alt=media;
                            # otherwise prefer Google Sheets live export so browser edits in Google Sheets appear immediately!
                            prefer_sheets_live = (wb.get("last_edit_source") != "glennbot") or is_meta_modified
                            fresh_sheets = _download_and_parse_gdrive_spreadsheet(
                                gd_id,
                                str(wb.get("title") or m_data.get("name") or "Spreadsheet.xlsx"),
                                remote_mime,
                                prefer_live_sheets_export=prefer_sheets_live
                            )
                            if fresh_sheets:
                                old_sig = _compute_sheets_signature(wb.get("sheets"))
                                new_sig = _compute_sheets_signature(fresh_sheets)
                                if new_sig != old_sig or is_meta_modified:
                                    wb["sheets"] = fresh_sheets
                                    wb["sheet_count"] = len(fresh_sheets)
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
            "cells": s_cells
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

        # 1. Build genuine .xlsx binary in Python
        xlsx_bytes = build_xlsx_bytes_from_sheets(normalized_sheets)

        # 2. Upload or update in-place in Google Drive ('GlennBot_Media_Vault')
        gd_info = _upload_or_update_spreadsheet_on_gdrive(
            xlsx_bytes=xlsx_bytes,
            filename=save_filename,
            existing_gdrive_file_id=existing_gd_id,
            py_file_id=py_file_id
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
        wb_record = {
            "workbook_id": final_wb_id,
            "file_id": vault_rec["file_id"],
            "gdrive_file_id": gd_info["gdrive_file_id"],
            "gdrive_file_name": gd_info["gdrive_file_name"],
            "gdrive_modified_time": gd_info.get("gdrive_modified_time") or "",
            "gdrive_md5": gd_info.get("gdrive_md5") or "",
            "last_local_save_ts": time.time(),
            "last_edit_source": "glennbot",
            "web_view_link": gd_info.get("web_view_link") or "",
            "title": save_filename,
            "storage_provider": "google_drive",
            "cloudinary_xlsx_url": f"/api/files/{vault_rec['file_id']}/stream",
            "size_bytes": len(xlsx_bytes),
            "size_formatted": _format_file_size_human(len(xlsx_bytes)),
            "sheet_count": len(normalized_sheets),
            "updated_at": now_str,
            "sheets": normalized_sheets
        }

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

            gd_info = _upload_or_update_spreadsheet_on_gdrive(
                xlsx_bytes=xlsx_bytes,
                filename=raw_title,
                existing_gdrive_file_id=gd_id,
                py_file_id=fid
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


