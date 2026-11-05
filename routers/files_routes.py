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
# --- "FILES" MODAL: GOOGLE DRIVE FILE VAULT WITH PYTHON-GENERATED FILE IDs ---
# ==============================================================================
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from fastapi.responses import Response

MANILA_TZ = pytz.timezone("Asia/Manila")
manila_tz = MANILA_TZ

CLOUDINARY_FILES_VAULT_PUBLIC_ID = "glennbot_config/files_vault_v1.json"
LOCAL_FILES_VAULT_CACHE_PATH = os.path.join(BASE_DIR, "files_vault_cache.json")
FILES_VAULT_LOCK = threading.Lock()
FILES_VAULT_STORE: Dict[str, Any] = {
    "loaded": False,
    "updated_at": "",
    "files": []  # Strictly files uploaded from the "Files" modal with Python-generated file_id
}


def _format_file_size_human(size_bytes: int) -> str:
    b = max(0, int(size_bytes or 0))
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _generate_python_automation_file_id(existing_ids: Optional[set] = None) -> str:
    """
    Python-generated unique File ID for automation purposes (e.g. file_9f8a7b6c5d4e).
    """
    seen = existing_ids or set()
    for _ in range(20):
        candidate = f"file_{uuid.uuid4().hex[:12]}"
        if candidate not in seen:
            return candidate
    return f"file_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def _load_files_vault_store(force_cloud: bool = False) -> Dict[str, Any]:
    with FILES_VAULT_LOCK:
        if FILES_VAULT_STORE.get("loaded") and not force_cloud:
            return FILES_VAULT_STORE

        loaded_files: List[Dict[str, Any]] = []
        loaded_from_cloud = False

        # 1. Try loading from Cloudinary JSON store
        if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
            try:
                res = cloudinary.api.resource(
                    CLOUDINARY_FILES_VAULT_PUBLIC_ID,
                    resource_type="raw"
                )
                sec_url = (res or {}).get("secure_url")
                if sec_url:
                    sep = "&" if "?" in sec_url else "?"
                    r = HTTP_SESSION.get(f"{sec_url}{sep}_ts={int(time.time())}", timeout=15)
                    if r.status_code == 200:
                        data = r.json() or {}
                        if isinstance(data.get("files"), list):
                            loaded_files = data["files"]
                            loaded_from_cloud = True
            except Exception:
                pass

        # 2. Fallback to local disk cache if Cloudinary resource not created yet
        if not loaded_from_cloud and os.path.exists(LOCAL_FILES_VAULT_CACHE_PATH):
            try:
                with open(LOCAL_FILES_VAULT_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                    if isinstance(data.get("files"), list):
                        loaded_files = data["files"]
            except Exception:
                pass

        FILES_VAULT_STORE["files"] = loaded_files
        FILES_VAULT_STORE["loaded"] = True
        FILES_VAULT_STORE["updated_at"] = datetime.now(manila_tz).strftime("%Y-%m-%d %I:%M:%S %p")
        return FILES_VAULT_STORE


def _save_files_vault_store() -> bool:
    with FILES_VAULT_LOCK:
        payload = {
            "version": 1,
            "updated_at": datetime.now(manila_tz).strftime("%Y-%m-%d %I:%M:%S %p"),
            "files": FILES_VAULT_STORE.get("files") or []
        }
        raw_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        try:
            with open(LOCAL_FILES_VAULT_CACHE_PATH, "w", encoding="utf-8") as f:
                f.write(raw_bytes.decode("utf-8"))
        except Exception:
            pass

    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        def _bg_upload_vault_cloud():
            try:
                cloudinary.uploader.upload(
                    io.BytesIO(raw_bytes),
                    resource_type="raw",
                    public_id=CLOUDINARY_FILES_VAULT_PUBLIC_ID,
                    overwrite=True,
                    invalidate=True
                )
            except Exception as e:
                print(f"[⚠️ FILES VAULT CLOUDINARY SAVE WARNING]: {e}")
        threading.Thread(target=_bg_upload_vault_cloud, daemon=True).start()
        return True
    return True



def _refresh_vault_file_entry_urls(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry)
    fid = str(out.get("file_id") or "").strip()
    clean_fname = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", str(out.get("filename") or out.get("gdrive_file_name") or "").strip())
    if clean_fname:
        out["filename"] = clean_fname
        out["gdrive_file_name"] = clean_fname
    gdrive_fid = str(out.get("gdrive_file_id") or "").strip()
    if "/" in gdrive_fid:
        gdrive_fid = ""
    dl_url = str(out.get("download_url") or "").strip()

    # Never expose or rely on a 7-day expiring Zernio URL in the Files Vault;
    # all Files Vault & Create Post previews use permanent Google Drive streaming!
    out["zernio_media_url"] = ""
    out["zernio_media_ts"] = 0.0

    stream_route = f"/api/files/{urllib.parse.quote(fid, safe='')}/stream" if fid else ""
    if gdrive_fid:
        out["gdrive_file_id"] = gdrive_fid
        out["web_view_link"] = out.get("web_view_link") or f"https://drive.google.com/file/d/{gdrive_fid}/view"
        out["gdrive_stream_url"] = f"/api/gdrive-media/{urllib.parse.quote(gdrive_fid, safe='')}"
        out["preview_url"] = stream_route or out["gdrive_stream_url"]
        out["download_url"] = stream_route or out["gdrive_stream_url"]
    elif dl_url and "media.zernio.com" not in dl_url:
        out["preview_url"] = dl_url
        out["download_url"] = dl_url
    else:
        out["preview_url"] = stream_route or dl_url
        out["download_url"] = stream_route or dl_url

    out["storage_provider"] = "google_drive"
    out["bucket_name"] = GOOGLE_DRIVE_FOLDER_NAME
    return out


# ==============================================================================
# --- GOOGLE DRIVE OAUTH 2.0 ENDPOINTS & LIVE MEDIA STREAM PROXY ---
# ==============================================================================
def _exchange_gdrive_oauth_code_and_persist(raw_code_or_url: str, redirect_uri: str = "http://localhost") -> Dict[str, Any]:
    val = (raw_code_or_url or "").strip()
    if not val:
        raise ValueError("Authorization code or callback URL is empty.")

    actual_code = val
    eff_redirect_uri = (redirect_uri or "http://localhost").strip()
    if val.startswith("http://") or val.startswith("https://") or "code=" in val:
        parsed = urllib.parse.urlparse(val if "://" in val else f"http://localhost/?{val.lstrip('?')}")
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get("code"):
            actual_code = str(qs["code"][0]).strip()
        if parsed.scheme and parsed.netloc:
            eff_redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if eff_redirect_uri == "http://localhost":
                eff_redirect_uri = "http://localhost"

    resp = HTTP_SESSION.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": actual_code,
            "client_id": GOOGLE_DRIVE_CLIENT_ID,
            "client_secret": GOOGLE_DRIVE_CLIENT_SECRET,
            "redirect_uri": eff_redirect_uri,
            "grant_type": "authorization_code"
        },
        timeout=25
    )
    if resp.status_code != 200 and eff_redirect_uri != "http://localhost":
        resp = HTTP_SESSION.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": actual_code,
                "client_id": GOOGLE_DRIVE_CLIENT_ID,
                "client_secret": GOOGLE_DRIVE_CLIENT_SECRET,
                "redirect_uri": "http://localhost",
                "grant_type": "authorization_code"
            },
            timeout=25
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Google OAuth token exchange failed ({resp.status_code}): {resp.text[:300]}")

    tok_data = resp.json() or {}
    acc_tok = str(tok_data.get("access_token") or "").strip()
    ref_tok = str(tok_data.get("refresh_token") or "").strip()
    expires_in = int(tok_data.get("expires_in") or 3500)

    if acc_tok:
        with GDRIVE_AUTH_LOCK:
            GDRIVE_AUTH_CACHE["access_token"] = acc_tok
            GDRIVE_AUTH_CACHE["expires_at"] = time.time() + expires_in

    user_email = ""
    if acc_tok:
        try:
            ab_resp = HTTP_SESSION.get(
                "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress,displayName),storageQuota",
                headers={"Authorization": f"Bearer {acc_tok}"},
                timeout=15
            )
            if ab_resp.status_code == 200:
                u_info = (ab_resp.json() or {}).get("user") or {}
                user_email = str(u_info.get("emailAddress") or u_info.get("displayName") or "").strip()
        except Exception:
            pass

    if ref_tok:
        _save_gdrive_auth_store(refresh_token=ref_tok, connected_email=user_email)
    elif user_email:
        _save_gdrive_auth_store(connected_email=user_email)

    folder_id = ""
    try:
        folder_id = gdrive_ensure_vault_folder()
    except Exception:
        pass

    return {
        "status": "success",
        "authorized": is_gdrive_authorized(),
        "connected_email": user_email,
        "folder_name": GOOGLE_DRIVE_FOLDER_NAME,
        "folder_id": folder_id
    }


@router.get("/api/gdrive/status")
def api_gdrive_status():
    state = _load_gdrive_auth_store(force_cloud=False)
    return {
        "status": "success",
        "configured": is_gdrive_media_configured(),
        "authorized": bool(state.get("refresh_token")),
        "client_id": GOOGLE_DRIVE_CLIENT_ID,
        "project_id": GOOGLE_DRIVE_PROJECT_ID,
        "folder_name": GOOGLE_DRIVE_FOLDER_NAME,
        "folder_id": state.get("folder_id") or "",
        "connected_email": state.get("connected_email") or ""
    }


@router.get("/api/gdrive/auth-url")
def api_gdrive_auth_url(request: Request):
    host_hdr = str(request.headers.get("host") or "").strip().lower()
    if host_hdr.startswith("localhost") or host_hdr.startswith("127.0.0.1"):
        port_part = f":{host_hdr.split(':', 1)[1]}" if ":" in host_hdr else ""
        redirect_uri = f"http://localhost{port_part}/api/gdrive/oauth/callback"
        is_local = True
    else:
        redirect_uri = "http://localhost"
        is_local = False

    params = {
        "client_id": GOOGLE_DRIVE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/drive",
        "access_type": "offline",
        "prompt": "consent"
    }
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urllib.parse.urlencode(params)}"
    return {
        "status": "success",
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "is_local_callback": is_local
    }


@router.get("/api/gdrive/oauth/callback")
def api_gdrive_oauth_callback(request: Request, code: str = "", error: str = ""):
    if error:
        return HTMLResponse(f"<html><body style='background:#020617;color:#f43f5e;font-family:sans-serif;padding:40px;text-align:center;'><h2>Google Drive Authorization Error</h2><p>{error}</p></body></html>")
    host_hdr = str(request.headers.get("host") or "localhost").strip()
    port_part = f":{host_hdr.split(':', 1)[1]}" if ":" in host_hdr else ""
    redirect_uri = f"http://localhost{port_part}/api/gdrive/oauth/callback"
    try:
        res = _exchange_gdrive_oauth_code_and_persist(code, redirect_uri=redirect_uri)
        email_txt = res.get("connected_email") or "Google Account"
        return HTMLResponse(
            f"""<html><body style="background:#020617;color:#10b981;font-family:sans-serif;padding:40px;text-align:center;">
            <h2>✅ Google Drive Connected! ({email_txt})</h2>
            <p style="color:#94a3b8;">Folder: <b>{GOOGLE_DRIVE_FOLDER_NAME}</b> — Refresh Token saved to .env &amp; Cloud Config.</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{ type: 'GDRIVE_AUTH_SUCCESS', email: '{email_txt}' }}, '*');
                    setTimeout(() => window.close(), 1200);
                }}
            </script>
            </body></html>"""
        )
    except Exception as e:
        return HTMLResponse(f"<html><body style='background:#020617;color:#f43f5e;font-family:sans-serif;padding:40px;text-align:center;'><h2>Google Drive Exchange Failed</h2><p>{e}</p></body></html>")


@router.post("/api/gdrive/exchange-code")
def api_gdrive_exchange_code(
    code_or_url: str = Form(""),
    refresh_token_direct: str = Form("")
):
    try:
        if refresh_token_direct and refresh_token_direct.strip():
            _save_gdrive_auth_store(refresh_token=refresh_token_direct.strip())
            fid = ""
            try:
                fid = gdrive_ensure_vault_folder()
            except Exception:
                pass
            return {
                "status": "success",
                "authorized": is_gdrive_authorized(),
                "folder_name": GOOGLE_DRIVE_FOLDER_NAME,
                "folder_id": fid,
                "message": "Google Drive Refresh Token saved!"
            }
        res = _exchange_gdrive_oauth_code_and_persist(code_or_url, redirect_uri="http://localhost")
        return res
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


@router.get("/api/gdrive-media/{gdrive_file_id:path}")
def api_stream_gdrive_media(gdrive_file_id: str, request: Request):
    """
    Live HTTP Range-Capable Media Streamer for Google Drive files so <video controls>
    and <img> previews in Create Post and the Files modal play and seek smoothly!
    """
    clean_id = (gdrive_file_id or "").strip().strip("/")
    if not clean_id:
        return JSONResponse({"status": "error", "message": "Missing Google Drive file ID."}, status_code=400)

    store = _load_files_vault_store(force_cloud=False)
    vault_match = next(
        (
            f for f in (store.get("files") or [])
            if str(f.get("gdrive_file_id") or "") == clean_id
            or str(f.get("file_id") or "") == clean_id
        ),
        None
    )
    if vault_match:
        if vault_match.get("gdrive_file_id"):
            cand_id = str(vault_match.get("gdrive_file_id") or "").strip()
            if cand_id and "/" not in cand_id:
                clean_id = cand_id

    if not is_gdrive_authorized():
        return RedirectResponse(f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(clean_id, safe='')}")

    try:
        acc_tok = gdrive_get_access_token(force_refresh=False)
        req_headers = {"Authorization": f"Bearer {acc_tok}"}
        range_hdr = request.headers.get("range") or request.headers.get("Range")
        if range_hdr:
            req_headers["Range"] = range_hdr

        g_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(clean_id, safe='')}?alt=media"
        upstream = requests.get(g_url, headers=req_headers, stream=True, timeout=60)
        if upstream.status_code not in (200, 206):
            upstream.close()
            return RedirectResponse(f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(clean_id, safe='')}")

        resp_headers: Dict[str, str] = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600"
        }
        for h_name in ("Content-Length", "Content-Range", "Content-Type"):
            if upstream.headers.get(h_name):
                resp_headers[h_name] = upstream.headers[h_name]

        media_ct = resp_headers.get("Content-Type") or (vault_match.get("content_type") if vault_match else None) or "application/octet-stream"

        def _iter_stream():
            try:
                for chunk in upstream.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        yield chunk
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass

        return StreamingResponse(
            _iter_stream(),
            status_code=upstream.status_code,
            media_type=media_ct,
            headers=resp_headers
        )
    except Exception as e:
        print(f"[⚠️ GDRIVE MEDIA STREAM WARNING] ({clean_id}): {e}")
        return RedirectResponse(f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(clean_id, safe='')}")


@router.get("/api/files/{file_id}/stream")
def api_stream_vault_file_by_id(file_id: str, request: Request):
    clean_id = (file_id or "").strip()
    store = _load_files_vault_store(force_cloud=False)
    target = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == clean_id), None)
    if not target:
        return JSONResponse({"status": "error", "message": f"File ID '{clean_id}' not found."}, status_code=404)

    gdrive_fid = str(target.get("gdrive_file_id") or "").strip()
    if gdrive_fid and "/" not in gdrive_fid:
        return api_stream_gdrive_media(gdrive_fid, request)

    dl_url = str(target.get("download_url") or "").strip()
    if dl_url.startswith("http") and "media.zernio.com" not in dl_url:
        return RedirectResponse(dl_url)
    return JSONResponse({"status": "error", "message": "Google Drive stream source unavailable for this file."}, status_code=404)


def _sync_files_vault_with_gdrive(force: bool = False) -> List[Dict[str, Any]]:
    """
    Two-Way Sync between Google Drive ('GlennBot_Media_Vault') and Cloudinary ('glennbot_config/files_vault_v1.json'):
    - Stores Python-generated `file_id` mappings in Cloudinary while keeping Google Drive filenames clean (no `file_id` prefix).
    - If a client renames a file in Google Drive, updates `filename` in Cloudinary & Dashboard without changing or disconnecting `file_id`.
    - If files are deleted in Google Drive (e.g. fresh start), removes stale entries from Cloudinary & Spreadsheets store automatically.
    """
    store = _load_files_vault_store(force_cloud=force)
    existing_files: List[Dict[str, Any]] = list(store.get("files") or [])

    if not is_gdrive_authorized():
        return [_refresh_vault_file_entry_urls(f) for f in existing_files]

    try:
        folder_id = gdrive_ensure_vault_folder()
        if not folder_id:
            return [_refresh_vault_file_entry_urls(f) for f in existing_files]

        acc_tok = gdrive_get_access_token(force_refresh=False)
        headers = {"Authorization": f"Bearer {acc_tok}"}
        q_str = f"'{folder_id}' in parents and trashed=false and mimeType != 'application/vnd.google-apps.folder'"
        resp = HTTP_SESSION.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params={
                "q": q_str,
                "fields": "files(id,name,size,mimeType,createdTime,modifiedTime,md5Checksum,webViewLink,appProperties)",
                "pageSize": 500,
                "orderBy": "createdTime desc"
            },
            timeout=25
        )
        if resp.status_code != 200:
            return [_refresh_vault_file_entry_urls(f) for f in existing_files]

        drive_items = (resp.json() or {}).get("files") or []
    except Exception as e:
        print(f"[⚠️ FILES VAULT GDRIVE SYNC WARNING]: {e}")
        return [_refresh_vault_file_entry_urls(f) for f in existing_files]

    by_gdrive_id: Dict[str, Dict[str, Any]] = {}
    by_file_id: Dict[str, Dict[str, Any]] = {}
    existing_ids: set = set()
    for entry in existing_files:
        if not isinstance(entry, dict):
            continue
        fid = str(entry.get("file_id") or "").strip()
        gd_id = str(entry.get("gdrive_file_id") or "").strip()
        if fid:
            existing_ids.add(fid)
            by_file_id[fid] = entry
        if gd_id:
            by_gdrive_id[gd_id] = entry

    synced_files: List[Dict[str, Any]] = []
    vault_changed = False
    active_gdrive_ids: set = set()
    renamed_by_gdrive_id: Dict[str, str] = {}

    for ditem in drive_items:
        if not isinstance(ditem, dict) or not ditem.get("id"):
            continue
        gd_id = str(ditem["id"]).strip()
        active_gdrive_ids.add(gd_id)
        raw_name = str(ditem.get("name") or "uploaded_file").strip()
        clean_name = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", raw_name) or raw_name
        mime_type = str(ditem.get("mimeType") or "application/octet-stream").strip()
        size_bytes = int(ditem.get("size") or 0)
        web_link = str(ditem.get("webViewLink") or f"https://drive.google.com/file/d/{gd_id}/view").strip()
        app_props = ditem.get("appProperties") if isinstance(ditem.get("appProperties"), dict) else {}
        prop_fid = str(app_props.get("glennbot_file_id") or "").strip()

        matched = by_gdrive_id.get(gd_id) or (by_file_id.get(prop_fid) if prop_fid else None)
        if matched:
            fid = str(matched.get("file_id") or prop_fid or _generate_python_automation_file_id(existing_ids)).strip()
            existing_ids.add(fid)
            old_fname = str(matched.get("filename") or "").strip()
            if old_fname != clean_name or str(matched.get("gdrive_file_id") or "") != gd_id or int(matched.get("size_bytes") or 0) != size_bytes:
                vault_changed = True
                if old_fname != clean_name:
                    renamed_by_gdrive_id[gd_id] = clean_name
            rec = dict(matched)
            rec.update({
                "file_id": fid,
                "filename": clean_name,
                "gdrive_file_name": clean_name,
                "gdrive_file_id": gd_id,
                "content_type": mime_type,
                "size_bytes": size_bytes,
                "size_formatted": _format_file_size_human(size_bytes),
                "web_view_link": web_link,
                "download_url": f"/api/files/{fid}/stream",
                "preview_url": f"/api/files/{fid}/stream"
            })
            synced_files.append(rec)
        else:
            fid = prop_fid if (prop_fid and prop_fid.startswith("file_")) else _generate_python_automation_file_id(existing_ids)
            existing_ids.add(fid)
            now_manila = datetime.now(manila_tz)
            rec = {
                "file_id": fid,
                "filename": clean_name,
                "content_type": mime_type,
                "size_bytes": size_bytes,
                "size_formatted": _format_file_size_human(size_bytes),
                "storage_provider": "google_drive",
                "bucket_name": GOOGLE_DRIVE_FOLDER_NAME,
                "gdrive_file_id": gd_id,
                "gdrive_file_name": clean_name,
                "web_view_link": web_link,
                "download_url": f"/api/files/{fid}/stream",
                "preview_url": f"/api/files/{fid}/stream",
                "zernio_media_url": "",
                "zernio_media_ts": 0.0,
                "notes": "",
                "uploaded_at": now_manila.strftime("%b %d, %Y %I:%M %p"),
                "uploaded_iso": now_manila.isoformat()
            }
            synced_files.append(rec)
            vault_changed = True

    if len(synced_files) != len(existing_files):
        vault_changed = True

    if vault_changed:
        with FILES_VAULT_LOCK:
            FILES_VAULT_STORE["files"] = synced_files
        _save_files_vault_store()

        # Sync SPREADSHEETS_STORE if spreadsheets were deleted or renamed in Google Drive
        try:
            sp_store = _load_spreadsheets_store(force_cloud=False)
            wb_list = list(sp_store.get("workbooks") or [])
            new_wb_list = []
            sp_changed = False
            for wb in wb_list:
                wb_gd_id = str(wb.get("gdrive_file_id") or "").strip()
                if wb_gd_id and wb_gd_id not in active_gdrive_ids:
                    sp_changed = True
                    continue
                if wb_gd_id and wb_gd_id in renamed_by_gdrive_id:
                    wb["title"] = renamed_by_gdrive_id[wb_gd_id]
                    wb["gdrive_file_name"] = renamed_by_gdrive_id[wb_gd_id]
                    sp_changed = True
                new_wb_list.append(wb)
            if sp_changed:
                with SPREADSHEETS_LOCK:
                    SPREADSHEETS_STORE["workbooks"] = new_wb_list
                _save_spreadsheets_store()
        except Exception:
            pass

    return [_refresh_vault_file_entry_urls(f) for f in synced_files]


@router.get("/api/files")
def api_list_vault_files(force: bool = False):
    """
    Lists all files in the 'Files' modal synced with Google Drive ('GlennBot_Media_Vault'),
    keeping Python-generated File IDs saved in Cloudinary ('glennbot_config/files_vault_v1.json').
    """
    files_list = _sync_files_vault_with_gdrive(force=force)
    gdrive_state = _load_gdrive_auth_store(force_cloud=False)
    return {
        "status": "success",
        "count": len(files_list),
        "gdrive_configured": is_gdrive_media_configured(),
        "gdrive_authorized": bool(gdrive_state.get("refresh_token")),
        "gdrive_connected_email": gdrive_state.get("connected_email") or "",
        "gdrive_folder_name": GOOGLE_DRIVE_FOLDER_NAME,
        "files": files_list
    }


def _upload_vault_file_bytes_with_fallback(
    file_bytes: bytes,
    orig_name: str,
    py_file_id: str,
    mime_type: str = "application/octet-stream"
) -> Dict[str, Any]:
    """
    Uploads a 'Files' modal file strictly to Google Drive ('GlennBot_Media_Vault').
    Does NOT pre-stage to Zernio (so files in the 'Files' modal never expire after Zernio's 7-day limit);
    live previews stream directly from Google Drive API v3 (/api/files/{file_id}/stream), and
    transfer to Zernio happens only when publishing/scheduling a post!
    """
    if not is_gdrive_authorized():
        raise RuntimeError("Google Drive is not connected yet. Please click 'Connect Google Drive' in the Files modal first.")

    g_res = upload_media_to_gdrive(
        file_bytes=file_bytes,
        original_filename=orig_name,
        media_type="file",
        is_thumb=False,
        custom_subfolder="files_vault",
        custom_file_prefix=py_file_id
    )
    g_fid = str(g_res.get("gdrive_file_id") or "")
    stream_u = f"/api/files/{py_file_id}/stream"
    return {
        "gdrive_file_id": g_fid,
        "gdrive_file_name": str(g_res.get("gdrive_file_name") or orig_name),
        "web_view_link": str(g_res.get("web_view_link") or (f"https://drive.google.com/file/d/{g_fid}/view" if g_fid else "")),
        "download_url": stream_u,
        "preview_url": stream_u,
        "zernio_media_url": "",
        "zernio_media_ts": 0.0,
        "storage_provider": "google_drive",
        "bucket_name": GOOGLE_DRIVE_FOLDER_NAME
    }


@router.post("/api/files/upload")
async def api_upload_vault_files(
    files: List[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    notes: str = Form("")
):
    """
    Uploads one or more files from the 'Files' modal to Google Drive ('GlennBot_Media_Vault').
    Python automatically generates a unique 'file_id' (e.g. file_9f8a7b6c5d4e) per uploaded file
    for future automation use.
    """
    upload_list: List[UploadFile] = []
    if files:
        upload_list.extend([f for f in files if f and f.filename])
    if file and file.filename and file not in upload_list:
        upload_list.append(file)

    if not upload_list:
        return JSONResponse({"status": "error", "message": "No file selected for upload."}, status_code=400)

    file_payloads: List[Tuple[str, str, bytes]] = []
    for up_file in upload_list:
        orig_name = os.path.basename(up_file.filename or "uploaded_file")
        f_bytes = await up_file.read()
        if f_bytes:
            guessed_mime, _ = mimetypes.guess_type(orig_name)
            m_type = up_file.content_type or guessed_mime or "application/octet-stream"
            file_payloads.append((orig_name, m_type, f_bytes))

    if not file_payloads:
        return JSONResponse({"status": "error", "message": "Uploaded file is empty."}, status_code=400)

    def _sync_do_upload():
        store = _load_files_vault_store(force_cloud=False)
        existing_files: List[Dict[str, Any]] = list(store.get("files") or [])
        existing_ids = {str(x.get("file_id") or "") for x in existing_files}
        uploaded_records: List[Dict[str, Any]] = []

        for orig_name, mime_type, file_bytes in file_payloads:
            py_file_id = _generate_python_automation_file_id(existing_ids)
            existing_ids.add(py_file_id)
            size_bytes = len(file_bytes)

            up_info = _upload_vault_file_bytes_with_fallback(
                file_bytes=file_bytes,
                orig_name=orig_name,
                py_file_id=py_file_id,
                mime_type=mime_type
            )

            now_manila = datetime.now(manila_tz)
            record = {
                "file_id": py_file_id,
                "filename": orig_name,
                "content_type": mime_type,
                "size_bytes": size_bytes,
                "size_formatted": _format_file_size_human(size_bytes),
                "storage_provider": up_info["storage_provider"],
                "bucket_name": up_info["bucket_name"],
                "gdrive_file_id": up_info.get("gdrive_file_id") or "",
                "gdrive_file_name": up_info.get("gdrive_file_name") or orig_name,
                "web_view_link": up_info.get("web_view_link") or "",
                "download_url": up_info["download_url"],
                "preview_url": up_info.get("preview_url") or up_info["download_url"],
                "zernio_media_url": up_info.get("zernio_media_url") or "",
                "zernio_media_ts": up_info.get("zernio_media_ts") or 0.0,
                "notes": (notes or "").strip(),
                "uploaded_at": now_manila.strftime("%b %d, %Y %I:%M %p"),
                "uploaded_iso": now_manila.isoformat()
            }
            existing_files.insert(0, record)
            uploaded_records.append(record)

        with FILES_VAULT_LOCK:
            FILES_VAULT_STORE["files"] = existing_files
        _save_files_vault_store()
        return {
            "status": "success",
            "message": f"Uploaded {len(uploaded_records)} file(s) to Google Drive ({GOOGLE_DRIVE_FOLDER_NAME}) with Python-generated File ID(s)!",
            "uploaded": uploaded_records,
            "files": [_refresh_vault_file_entry_urls(f) for f in existing_files]
        }

    try:
        return await run_in_threadpool(_sync_do_upload)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


CHUNKED_VAULT_SESSIONS: Dict[str, Dict[str, Any]] = {}
CHUNKED_VAULT_LOCK = threading.Lock()

@router.post("/api/files/chunked/init")
def api_vault_chunked_init(
    request: Request,
    filename: str = Form(...),
    content_type: str = Form("application/octet-stream"),
    total_size: int = Form(0),
    total_parts: int = Form(1),
    notes: str = Form("")
):
    store = _load_files_vault_store(force_cloud=False)
    existing_files: List[Dict[str, Any]] = list(store.get("files") or [])
    existing_ids = {str(x.get("file_id") or "") for x in existing_files}
    py_file_id = _generate_python_automation_file_id(existing_ids)

    orig_name = os.path.basename(filename or "uploaded_file").strip()
    orig_name = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", orig_name) or "uploaded_file"
    guessed_mime, _ = mimetypes.guess_type(orig_name)
    mime_type = content_type or guessed_mime or "application/octet-stream"
    # Keep exact clean filename in Google Drive (without file_id prefix); py_file_id is saved in Cloudinary
    gdrive_file_name = orig_name

    if not is_gdrive_authorized():
        return JSONResponse(
            {
                "status": "error",
                "needs_oauth": True,
                "message": "Google Drive is not authorized yet. Click 'Connect Google Drive' in the Files modal first."
            },
            status_code=400
        )

    gdrive_resumable_url = ""
    try:
        origin_hdr = str(request.headers.get("origin") or "").strip()
        gdrive_resumable_url = gdrive_init_resumable_upload(
            filename=gdrive_file_name,
            content_type=mime_type,
            total_size=int(total_size or 0),
            origin=origin_hdr,
            vault_file_id=py_file_id
        )
    except Exception as gd_err:
        print(f"[⚠️ GDRIVE VAULT RESUMABLE INIT WARNING]: {gd_err}")

    mode = "gdrive_resumable" if gdrive_resumable_url else "gdrive_chunked"
    with CHUNKED_VAULT_LOCK:
        CHUNKED_VAULT_SESSIONS[py_file_id] = {
            "file_id": py_file_id,
            "filename": orig_name,
            "content_type": mime_type,
            "total_size": int(total_size or 0),
            "total_parts": max(1, int(total_parts or 1)),
            "notes": (notes or "").strip(),
            "mode": mode,
            "gdrive_file_name": gdrive_file_name,
            "gdrive_resumable_url": gdrive_resumable_url,
            "part_sha1_map": {},
            "fallback_buffer": bytearray(),
            "single_item": None,
            "zernio_public_url": ""
        }

    return {
        "status": "success",
        "file_id": py_file_id,
        "mode": mode,
        "gdrive_file_name": gdrive_file_name,
        "content_type": mime_type,
        "upload_url": "",
        "upload_auth_token": "",
        "cors_ready": False,
        "gdrive_resumable_url": gdrive_resumable_url,
        "gdrive_authorized": is_gdrive_authorized()
    }


@router.post("/api/files/chunked/part-url")
def api_vault_chunked_part_url(
    file_id: str = Form(...),
    mode: str = Form("gdrive_chunked")
):
    return {
        "status": "success",
        "file_id": file_id,
        "upload_url": "",
        "upload_auth_token": ""
    }


@router.post("/api/files/chunked/part-confirm")
def api_vault_chunked_part_confirm(
    file_id: str = Form(...),
    part_number: int = Form(...),
    total_parts: int = Form(1),
    sha1: str = Form("")
):
    p_num = int(part_number)
    tot_parts = max(1, int(total_parts or 1))
    pct = min(99, max(1, int(round((p_num / float(tot_parts)) * 100))))
    return {"status": "success", "file_id": file_id, "part_number": p_num, "percent": pct}


@router.post("/api/files/chunked/part")
async def api_vault_chunked_part(
    file_id: str = Form(...),
    part_number: int = Form(...),
    total_parts: int = Form(1),
    chunk: UploadFile = File(...)
):
    with CHUNKED_VAULT_LOCK:
        session = CHUNKED_VAULT_SESSIONS.get(file_id)
    if not session:
        return JSONResponse({"status": "error", "message": f"Vault upload session '{file_id}' not found."}, status_code=404)

    chunk_bytes = await chunk.read()
    if not chunk_bytes:
        return JSONResponse({"status": "error", "message": f"Empty chunk for part #{part_number}."}, status_code=400)

    def _sync_vault_part():
        p_num = int(part_number)
        tot_parts = max(1, int(total_parts or session.get("total_parts") or 1))

        if tot_parts == 1:
            up_info = _upload_vault_file_bytes_with_fallback(
                file_bytes=chunk_bytes,
                orig_name=session["filename"],
                py_file_id=file_id,
                mime_type=session.get("content_type") or "application/octet-stream"
            )
            with CHUNKED_VAULT_LOCK:
                session["single_item"] = {
                    "url": up_info["download_url"],
                    "preview_url": up_info.get("preview_url") or up_info["download_url"],
                    "zernio_media_url": up_info.get("zernio_media_url") or "",
                    "web_view_link": up_info.get("web_view_link") or "",
                    "public_id": up_info.get("gdrive_file_id") or up_info.get("gdrive_file_name") or "",
                    "gdrive_file_id": up_info.get("gdrive_file_id") or "",
                    "gdrive_file_name": up_info.get("gdrive_file_name") or "",
                    "storage": up_info["storage_provider"],
                    "bucket_name": up_info["bucket_name"],
                    "type": "file",
                    "is_thumb": False
                }
        else:
            # True Zero-RAM-Accumulation Resumable Streaming to Google Drive!
            # Each 15 MB chunk is immediately forwarded to Google Drive's resumable session URI
            # with Content-Range so 500 MB+ files use only ~15 MB of RAM even on Render Free Tier (512 MB RAM).
            resumable_url = str(session.get("gdrive_resumable_url") or "").strip()
            if not resumable_url:
                resumable_url = gdrive_init_resumable_upload(
                    filename=session.get("gdrive_file_name") or session["filename"],
                    content_type=session.get("content_type") or "application/octet-stream",
                    total_size=int(session.get("total_size") or 0),
                    vault_file_id=file_id
                )
                with CHUNKED_VAULT_LOCK:
                    session["gdrive_resumable_url"] = resumable_url
                    session["uploaded_offset"] = 0

            start_byte = int(session.get("uploaded_offset") or 0)
            end_byte = start_byte + len(chunk_bytes) - 1
            total_sz = int(session.get("total_size") or 0)
            if p_num >= tot_parts or (total_sz > 0 and (end_byte + 1) >= total_sz):
                total_sz_hdr = str(end_byte + 1)
            else:
                total_sz_hdr = str(total_sz) if total_sz > 0 else "*"

            put_resp = requests.put(
                resumable_url,
                headers={
                    "Content-Type": session.get("content_type") or "application/octet-stream",
                    "Content-Length": str(len(chunk_bytes)),
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{total_sz_hdr}"
                },
                data=chunk_bytes,
                timeout=300
            )
            if put_resp.status_code not in (200, 201, 308):
                raise RuntimeError(f"Google Drive chunk #{p_num}/{tot_parts} upload failed ({put_resp.status_code}): {put_resp.text[:250]}")

            with CHUNKED_VAULT_LOCK:
                session["uploaded_offset"] = end_byte + 1

            if put_resp.status_code in (200, 201):
                res_json = put_resp.json() if put_resp.text else {}
                gdrive_fid = str(res_json.get("id") or "").strip()
                if gdrive_fid:
                    gdrive_set_file_public_reader(gdrive_fid)
                stream_url = f"/api/files/{file_id}/stream"
                with CHUNKED_VAULT_LOCK:
                    session["single_item"] = {
                        "url": stream_url,
                        "preview_url": stream_url,
                        "zernio_media_url": "",
                        "web_view_link": str(res_json.get("webViewLink") or (f"https://drive.google.com/file/d/{gdrive_fid}/view" if gdrive_fid else "")),
                        "public_id": gdrive_fid,
                        "gdrive_file_id": gdrive_fid,
                        "gdrive_file_name": session.get("gdrive_file_name") or session["filename"],
                        "storage": "google_drive",
                        "bucket_name": GOOGLE_DRIVE_FOLDER_NAME,
                        "type": "file",
                        "is_thumb": False
                    }

        pct = min(99, max(1, int(round((p_num / float(tot_parts)) * 100))))
        return {"status": "success", "file_id": file_id, "part_number": p_num, "percent": pct}

    try:
        return await run_in_threadpool(_sync_vault_part)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/files/chunked/complete")
def api_vault_chunked_complete(
    file_id: str = Form(...),
    filename: str = Form(""),
    content_type: str = Form(""),
    total_size: int = Form(0),
    notes: str = Form(""),
    part_sha1_json: str = Form(""),
    zernio_public_url: str = Form(""),
    gdrive_file_id: str = Form("")
):
    with CHUNKED_VAULT_LOCK:
        session = CHUNKED_VAULT_SESSIONS.pop(file_id, None)

    if not session:
        session = {
            "file_id": file_id,
            "filename": filename or "uploaded_file",
            "content_type": content_type or "application/octet-stream",
            "total_size": int(total_size or 0),
            "total_parts": 1,
            "notes": (notes or "").strip(),
            "mode": "gdrive_chunked",
            "gdrive_file_name": filename or "uploaded_file",
            "part_sha1_map": {},
            "single_item": None
        }

    resolved_gdrive_id = (gdrive_file_id or "").strip()
    gd_fname = (session.get("gdrive_file_name") or filename or "").strip()
    storage_provider = "google_drive"
    bucket_name_used = GOOGLE_DRIVE_FOLDER_NAME
    web_view_link = ""

    if session.get("single_item"):
        s_item = session["single_item"]
        resolved_gdrive_id = str(s_item.get("gdrive_file_id") or resolved_gdrive_id)
        gd_fname = str(s_item.get("gdrive_file_name") or gd_fname)
        web_view_link = str(s_item.get("web_view_link") or "")
    elif resolved_gdrive_id:
        gdrive_set_file_public_reader(resolved_gdrive_id)
        web_view_link = f"https://drive.google.com/file/d/{resolved_gdrive_id}/view"

    stream_url = f"/api/files/{file_id}/stream"
    download_url = stream_url
    preview_url = stream_url

    manila_tz = pytz.timezone("Asia/Manila")
    now_manila = datetime.now(manila_tz)
    size_bytes = int(session.get("total_size") or total_size or 0)
    record = {
        "file_id": file_id,
        "filename": session["filename"],
        "content_type": session["content_type"],
        "size_bytes": size_bytes,
        "size_formatted": _format_file_size_human(size_bytes),
        "storage_provider": storage_provider,
        "bucket_name": bucket_name_used,
        "gdrive_file_id": resolved_gdrive_id,
        "gdrive_file_name": gd_fname,
        "web_view_link": web_view_link or (f"https://drive.google.com/file/d/{resolved_gdrive_id}/view" if resolved_gdrive_id else ""),
        "download_url": download_url,
        "preview_url": preview_url,
        "zernio_media_url": "",
        "zernio_media_ts": 0.0,
        "notes": session.get("notes") or "",
        "uploaded_at": now_manila.strftime("%b %d, %Y %I:%M %p"),
        "uploaded_iso": now_manila.isoformat()
    }

    store = _load_files_vault_store(force_cloud=False)
    existing_files: List[Dict[str, Any]] = list(store.get("files") or [])
    existing_files.insert(0, record)
    with FILES_VAULT_LOCK:
        FILES_VAULT_STORE["files"] = existing_files
    _save_files_vault_store()

    return {
        "status": "success",
        "uploaded": [record],
        "files": [_refresh_vault_file_entry_urls(f) for f in existing_files]
    }


@router.delete("/api/files/{file_id}")
def api_delete_vault_file(file_id: str):
    """
    Deletes a file uploaded via the 'Files' modal from Google Drive and removes its File ID record.
    If the deleted file is a linked spreadsheet (.xlsx/.xls), also removes it from SPREADSHEETS_STORE.
    """
    clean_id = (file_id or "").strip()
    store = _load_files_vault_store(force_cloud=False)
    existing_files: List[Dict[str, Any]] = list(store.get("files") or [])
    target = next((f for f in existing_files if str(f.get("file_id") or "") == clean_id), None)
    if not target:
        return JSONResponse({"status": "error", "message": f"File ID '{clean_id}' not found."}, status_code=404)

    gdrive_fid = str(target.get("gdrive_file_id") or "").strip()
    gd_fname = str(target.get("gdrive_file_name") or target.get("filename") or "").strip()
    if gdrive_fid:
        try:
            delete_media_from_gdrive(gdrive_fid, gd_fname)
        except Exception as e:
            print(f"[⚠️ FILES VAULT GDRIVE DELETE WARNING]: {e}")

    remaining = [f for f in existing_files if str(f.get("file_id") or "") != clean_id]
    with FILES_VAULT_LOCK:
        FILES_VAULT_STORE["files"] = remaining
    _save_files_vault_store()

    # Also remove from SPREADSHEETS_STORE if linked to this file_id or gdrive_file_id
    try:
        sp_store = _load_spreadsheets_store(force_cloud=False)
        wb_list = list(sp_store.get("workbooks") or [])
        filtered_wbs = [
            w for w in wb_list
            if str(w.get("file_id") or "") != clean_id
            and (not gdrive_fid or str(w.get("gdrive_file_id") or "") != gdrive_fid)
        ]
        if len(filtered_wbs) != len(wb_list):
            with SPREADSHEETS_LOCK:
                SPREADSHEETS_STORE["workbooks"] = filtered_wbs
            _save_spreadsheets_store()
    except Exception:
        pass

    return {
        "status": "success",
        "deleted_file_id": clean_id,
        "message": f"Deleted '{target.get('filename')}' ({clean_id}) from Google Drive ({GOOGLE_DRIVE_FOLDER_NAME})!",
        "files": [_refresh_vault_file_entry_urls(f) for f in remaining]
    }


@router.get("/api/files/{file_id}/download")
def api_download_vault_file_by_id(file_id: str, redirect: bool = True):
    clean_id = (file_id or "").strip()
    store = _load_files_vault_store(force_cloud=False)
    target = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == clean_id), None)
    if not target:
        return JSONResponse({"status": "error", "message": f"File ID '{clean_id}' not found."}, status_code=404)

    refreshed = _refresh_vault_file_entry_urls(target)
    dl_url = str(refreshed.get("download_url") or "").strip()
    if redirect and dl_url.startswith("http"):
        return RedirectResponse(dl_url)
    return {"status": "success", "file": refreshed}


@router.get("/api/v1/files")
async def api_v1_list_files(request: Request):
    """
    Internal API v1 endpoint for n8n / automations to list all files in the Google Drive File Vault by File ID.
    """
    key_obj = await run_in_threadpool(lambda: _verify_internal_api_key(request))
    if not key_obj:
        return _unauthorized_v1_response()
    def _list_vault_sync():
        store = _load_files_vault_store(force_cloud=False)
        return [_refresh_vault_file_entry_urls(f) for f in (store.get("files") or [])]
    files_list = await run_in_threadpool(_list_vault_sync)
    return {
        "status": "success",
        "count": len(files_list),
        "files": files_list
    }


@router.get("/api/v1/files/{file_id}")
async def api_v1_get_file_by_id(file_id: str, request: Request):
    """
    Internal API v1 endpoint for n8n / automations to fetch a specific file and its Google Drive stream URL using its Python-generated File ID.
    """
    key_obj = await run_in_threadpool(lambda: _verify_internal_api_key(request))
    if not key_obj:
        return _unauthorized_v1_response()
    clean_id = (file_id or "").strip()
    def _get_vault_file_sync():
        store = _load_files_vault_store(force_cloud=False)
        target = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == clean_id), None)
        return _refresh_vault_file_entry_urls(target) if target else None
    refreshed = await run_in_threadpool(_get_vault_file_sync)
    if not refreshed:
        return JSONResponse({"status": "error", "message": f"File ID '{clean_id}' not found in Files Vault."}, status_code=404)
    return {
        "status": "success",
        "file": refreshed
    }


