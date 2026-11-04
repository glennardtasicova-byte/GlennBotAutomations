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
    _coerce_db_datetime,
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


# --- CUSTOM SELECTION PRESETS API ---
class PresetPayload(BaseModel):
    preset_name: str
    selection: Dict[str, Any]

@router.get("/api/presets")
def get_presets():
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, preset_name, selection_json, created_at 
                FROM glennbot_presets 
                ORDER BY created_at DESC
            """)).mappings().all()
            presets = []
            for r in rows:
                presets.append({
                    "id": r["id"],
                    "preset_name": r["preset_name"],
                    "selection": json.loads(r["selection_json"]) if r["selection_json"] else {}
                })
            return {"status": "success", "presets": presets}
    except Exception as e:
        return {"status": "error", "presets": [], "message": str(e)}

@router.post("/api/presets")
def save_preset(payload: PresetPayload):
    preset_id = f"preset_{uuid.uuid4().hex[:10]}"
    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO glennbot_presets (id, preset_name, selection_json)
                    VALUES (:id, :name, :json_data)
                """),
                {
                    "id": preset_id,
                    "name": payload.preset_name.strip(),
                    "json_data": json.dumps(payload.selection)
                }
            )
        return {"status": "success", "id": preset_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: str):
    try:
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM glennbot_presets WHERE id = :id"), {"id": preset_id})
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}



# --- SCHEDULED POSTS API & REAL-TIME ZERNIO / YOUTUBE STATUS SYNC ---
ZERNIO_DIRECT_POST_CHECK_CACHE: Dict[str, Dict[str, Any]] = {}

def _strip_invisible_guard_chars(text_val: str) -> str:
    if not text_val:
        return ""
    cleaned = re.sub(r"[\u2800\u2060\u200c\u200b\ufeff]+", "", str(text_val))
    cleaned = re.sub(r"\s*·\s*#[0-9A-Fa-f]{3}\s*$", "", cleaned)
    return cleaned.strip()


def _fetch_zernio_post_direct_by_id(z_post_id: str, platform: str = "", page_id: str = "", account_name: str = "", min_cache_sec: float = 4.0) -> Optional[Dict[str, Any]]:
    zid = str(z_post_id or "").strip()
    if not zid or zid == "OK":
        return None
    now_ts = time.time()
    cached = ZERNIO_DIRECT_POST_CHECK_CACHE.get(zid)
    if cached and (now_ts - float(cached.get("ts") or 0.0)) < min_cache_sec:
        return cached.get("post_obj")

    cand_keys = get_candidate_zernio_keys_for_account(page_id, account_name=account_name, platform=platform)
    for k in cand_keys:
        try:
            resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/posts/{zid}", headers=get_zernio_headers(k), timeout=12)
            if resp.status_code == 200 and resp.text:
                data = resp.json()
                post_obj = data.get("post") or data.get("data") or data
                if isinstance(post_obj, dict) and (post_obj.get("_id") or post_obj.get("id") or post_obj.get("status") or post_obj.get("platforms")):
                    ZERNIO_DIRECT_POST_CHECK_CACHE[zid] = {"ts": now_ts, "post_obj": post_obj}
                    ZERNIO_POSTS_CACHE["posts_map"][zid] = post_obj
                    return post_obj
        except Exception:
            continue
    return None


def sync_single_scheduled_row_with_zernio(
    r_dict: Dict[str, Any],
    z_map: Dict[str, Dict[str, Any]],
    z_list: List[Dict[str, Any]],
    now_manila: datetime
) -> Dict[str, Any]:
    manila_tz = pytz.timezone("Asia/Manila")
    plat = (r_dict.get("platform") or "").strip().lower()
    page_id = str(r_dict.get("page_id") or "").strip()
    acc_name = (r_dict.get("account_name") or "").strip()
    ext_id = extract_external_post_id(r_dict)
    cur_status = (r_dict.get("status") or "waiting").strip().lower()
    cur_msg = (r_dict.get("status_message") or "").strip()
    cur_permalink = (r_dict.get("permalink_url") or "").strip()
    sched_dt = _coerce_db_datetime(r_dict.get("scheduled_time"), manila_tz)

    rec_id_str = str(r_dict.get("id") or "").strip()
    if cur_status == "processing_payload":
        now_epoch = time.time()
        last_hb = float(LAST_UPLOAD_HEARTBEAT_TS.get(rec_id_str) or 0.0)
        has_active_session = (
            rec_id_str in CHUNKED_SCHEDULE_SESSIONS
            or ("ACTIVE_BACKGROUND_SCHEDULE_JOBS" in globals() and rec_id_str in ACTIVE_BACKGROUND_SCHEDULE_JOBS)
        )
        created_dt = _coerce_db_datetime(r_dict.get("created_at"), manila_tz)
        age_seconds = 0.0
        if created_dt:
            try:
                age_seconds = max(0.0, (now_manila - created_dt).total_seconds())
            except Exception:
                age_seconds = 0.0
        is_orphaned_after_restart = (not has_active_session and last_hb == 0.0 and age_seconds > 600.0)
        is_stalled_upload = (not has_active_session and last_hb > 0.0 and (now_epoch - last_hb) > 600.0)
        if is_orphaned_after_restart or is_stalled_upload:
            # Verify live DB status is STILL 'processing_payload' so we NEVER overwrite a completed 'waiting'/'published' row!
            still_processing_payload = False
            try:
                with db_engine.begin() as conn:
                    live_row = conn.execute(
                        text("SELECT status, status_message, external_post_id, permalink_url FROM glennbot_scheduled_posts WHERE id = :id"),
                        {"id": rec_id_str}
                    ).fetchone()
                    if live_row:
                        live_st = str(live_row[0] or "").strip().lower()
                        if live_st == "processing_payload":
                            still_processing_payload = True
                        else:
                            return {
                                "status": live_st,
                                "status_message": str(live_row[1] or ""),
                                "external_post_id": str(live_row[2] or ext_id or ""),
                                "permalink_url": str(live_row[3] or cur_permalink or "")
                            }
            except Exception:
                pass
            if still_processing_payload:
                fail_msg = "Upload interrupted (connection reset or server restarted during transfer). Please remove and re-upload."
                update_post_status(rec_id_str, "failed", fail_msg)
                return {
                    "status": "failed",
                    "status_message": fail_msg,
                    "external_post_id": ext_id,
                    "permalink_url": cur_permalink
                }

    is_due_waiting = bool(cur_status == "waiting" and sched_dt and now_manila >= (sched_dt - timedelta(seconds=15)))
    is_active_processing = bool(cur_status == "processing")
    needs_permalink_heal = bool(
        cur_status == "published"
        and (not _is_valid_final_permalink(cur_permalink, plat) or "Platform ID:" not in cur_msg)
        and sched_dt
        and (now_manila - sched_dt).total_seconds() < 86400
    )

    if not (is_due_waiting or is_active_processing or needs_permalink_heal):
        return {
            "status": cur_status,
            "status_message": cur_msg,
            "external_post_id": ext_id,
            "permalink_url": cur_permalink
        }

    m_z = re.search(r"(?:External API ID|Zernio ID):\s*([^\s,|]+)", cur_msg)
    z_lookup_id = m_z.group(1).strip() if m_z else (ext_id if (len(ext_id) == 24 and re.match(r"^[0-9a-f]{24}$", ext_id.lower())) else "")

    matched_zp: Optional[Dict[str, Any]] = None
    # 1. If we have a 24-char Zernio Post ID and the post is due/processing/healing, query Zernio directly to bypass stale list caches
    if z_lookup_id and (is_due_waiting or is_active_processing or needs_permalink_heal):
        matched_zp = _fetch_zernio_post_direct_by_id(
            z_lookup_id,
            platform=plat,
            page_id=page_id,
            account_name=acc_name,
            min_cache_sec=4.0 if (is_due_waiting or is_active_processing) else 15.0
        )

    if not matched_zp and (z_lookup_id or ext_id):
        matched_zp = z_map.get(z_lookup_id) or z_map.get(ext_id)

    # 2. If still not matched (e.g. ext_id was not saved yet), match in z_list by platform + caption
    if not matched_zp and (is_due_waiting or is_active_processing):
        row_cap_clean = _strip_invisible_guard_chars(r_dict.get("caption") or "").lower()
        row_first_line = next((ln.strip() for ln in row_cap_clean.splitlines() if ln.strip()), "")
        resolved_z_acc = resolve_zernio_account_id(plat, page_id, acc_name)
        for zp_cand in (z_list or []):
            if not isinstance(zp_cand, dict):
                continue
            zp_cap_clean = _strip_invisible_guard_chars(zp_cand.get("content") or zp_cand.get("caption") or "").lower()
            zp_first_line = next((ln.strip() for ln in zp_cap_clean.splitlines() if ln.strip()), "")
            if not row_first_line or not zp_first_line:
                continue
            if row_cap_clean != zp_cap_clean and row_first_line != zp_first_line:
                continue
            plat_matched = False
            for pl_entry in (zp_cand.get("platforms") or []):
                if not isinstance(pl_entry, dict):
                    continue
                pl_plat = (pl_entry.get("platform") or "").strip().lower()
                pl_acc = pl_entry.get("accountId")
                if isinstance(pl_acc, dict):
                    pl_acc = pl_acc.get("_id") or pl_acc.get("id")
                if pl_plat == plat and (not pl_acc or str(pl_acc) in (page_id, resolved_z_acc)):
                    plat_matched = True
                    break
            if plat_matched:
                matched_zp = zp_cand
                break

    outcome = (
        extract_zernio_post_outcome(matched_zp, target_platform=plat)
        if matched_zp
        else {"state": "processing", "zernio_id": z_lookup_id, "platform_post_id": "", "permalink": "", "error": ""}
    )

    # 3. For YouTube posts that are due/processing/missing permalink, also check direct live YouTube channel video discovery!
    if plat == "youtube" and (is_due_waiting or is_active_processing or needs_permalink_heal):
        if outcome["state"] != "published" or not _is_valid_final_permalink(outcome.get("permalink") or cur_permalink, "youtube"):
            if "discover_youtube_video_id_direct" in globals():
                yt_vid_live = discover_youtube_video_id_direct(r_dict)
                if yt_vid_live and re.match(r"^[A-Za-z0-9_-]{11}$", yt_vid_live):
                    outcome["state"] = "published"
                    outcome["platform_post_id"] = yt_vid_live
                    outcome["permalink"] = f"https://www.youtube.com/watch?v={yt_vid_live}"

    if outcome["state"] == "failed":
        cur_status = "failed"
        cur_msg = f"External API Failed: {outcome['error'] or 'Failed to publish'}"
        update_post_status(r_dict["id"], "failed", cur_msg, external_post_id=outcome.get("zernio_id") or ext_id or None)
    elif outcome["state"] == "published":
        new_plat_id = outcome.get("platform_post_id") or ""
        new_z_id = outcome.get("zernio_id") or z_lookup_id
        new_permalink = outcome.get("permalink") if _is_valid_final_permalink(outcome.get("permalink") or "", plat) else (cur_permalink if _is_valid_final_permalink(cur_permalink, plat) else "")
        new_ext_id = new_plat_id or (ext_id if ext_id and len(ext_id) != 24 else "") or new_z_id or ext_id

        updated_msg = cur_msg
        if new_z_id and "External API ID:" not in updated_msg and "Zernio ID:" not in updated_msg:
            updated_msg = f"External API ID: {new_z_id} | {updated_msg}".strip(" |")
        if new_plat_id and f"Platform ID: {new_plat_id}" not in updated_msg:
            updated_msg = re.sub(r"\|\s*Platform ID:\s*[^\s,|]+", "", updated_msg).strip(" |")
            updated_msg = f"{updated_msg} | Platform ID: {new_plat_id}".strip(" |")

        if (
            cur_status != "published"
            or (new_permalink and new_permalink != cur_permalink)
            or (new_ext_id and new_ext_id != ext_id)
            or updated_msg != cur_msg
        ):
            update_post_status(
                r_dict["id"],
                "published",
                updated_msg,
                external_post_id=new_ext_id or None,
                permalink_url=new_permalink or None
            )
        cur_status = "published"
        cur_msg = updated_msg
        ext_id = new_ext_id or ext_id
        if new_permalink:
            cur_permalink = new_permalink
    elif outcome["state"] == "processing" and is_due_waiting and (matched_zp or z_lookup_id):
        eff_zid = outcome.get("zernio_id") or z_lookup_id
        cur_status = "processing"
        cur_msg = f"Publishing & rendering on {plat.capitalize()}... | External API ID: {eff_zid}" if eff_zid else f"Publishing & rendering on {plat.capitalize()}..."
        update_post_status(r_dict["id"], "processing", cur_msg, external_post_id=eff_zid or ext_id or None)

    return {
        "status": cur_status,
        "status_message": cur_msg,
        "external_post_id": ext_id,
        "permalink_url": cur_permalink
    }


def sync_pending_scheduled_posts_with_zernio() -> None:
    """
    Background synchronizer called every 8 seconds so due 'waiting' posts, 'processing' posts (including 1.4GB+ videos),
    and recently 'published' posts waiting for their final Facebook/YouTube permalink are automatically updated in Supabase
    even when the user is not viewing the Queue tab.
    """
    if not get_all_zernio_keys():
        return
    manila_tz = pytz.timezone("Asia/Manila")
    now_manila = datetime.now(manila_tz)
    try:
        max_sched = now_manila + timedelta(minutes=2)
        min_sched = now_manila - timedelta(hours=24)
        with db_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, post_type, caption,
                           media_preview_url, scheduled_time, status, status_message,
                           external_post_id, permalink_url, created_at
                    FROM glennbot_scheduled_posts
                    WHERE status IN ('waiting', 'processing', 'processing_payload', 'published')
                      AND (status = 'processing_payload' OR scheduled_time <= :max_sched)
                      AND scheduled_time >= :min_sched
                    ORDER BY scheduled_time DESC
                    LIMIT 30
                """),
                {"max_sched": max_sched, "min_sched": min_sched}
            ).mappings().all()
        if not rows:
            return
        connected_items = refresh_connected_accounts_cache(force=False)
        z_map = get_zernio_posts_map(force=False)
        z_list = ZERNIO_POSTS_CACHE.get("posts_list") or []
        for r in rows:
            r_dict = dict(r)
            if str(r_dict.get("id") or "").startswith("post_ext_"):
                continue
            if not is_post_account_connected(r_dict, connected_items):
                continue
            sync_single_scheduled_row_with_zernio(r_dict, z_map, z_list, now_manila)
    except Exception as e:
        print(f"[⚠️ BACKGROUND SCHEDULED POST SYNC WARNING]: {e}")


@router.get("/api/scheduled")
def get_scheduled_posts(month: Optional[int] = None, year: Optional[int] = None):
    manila_tz = pytz.timezone("Asia/Manila")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, post_type, caption, 
                           media_preview_url, scheduled_time, status, status_message,
                           external_post_id, permalink_url, created_at
                    FROM glennbot_scheduled_posts
                    ORDER BY scheduled_time ASC
                """)
            ).mappings().all()

            connected_items = refresh_connected_accounts_cache(force=False)
            z_map = get_zernio_posts_map(force=False)
            z_list = ZERNIO_POSTS_CACHE.get("posts_list") or []
            now_manila = datetime.now(manila_tz)
            items = []

            for r in rows:
                r_dict = dict(r)
                if str(r_dict["id"]).startswith("post_ext_"):
                    continue
                if not is_post_account_connected(r_dict, connected_items):
                    continue

                sched_dt = _coerce_db_datetime(r_dict.get("scheduled_time"), manila_tz)
                if month and year and (not sched_dt or sched_dt.month != int(month) or sched_dt.year != int(year)):
                    continue
                synced_info = sync_single_scheduled_row_with_zernio(r_dict, z_map, z_list, now_manila)
                cur_status = synced_info["status"]
                cur_msg = synced_info["status_message"]
                ext_id = synced_info["external_post_id"]
                cur_permalink = synced_info["permalink_url"]

                clean_status_msg = _strip_internal_ids_from_status_message(cur_msg, cur_status)
                raw_preview_url = r_dict["media_preview_url"] or ""
                live_preview_url = raw_preview_url
                items.append({
                    "id": r_dict["id"],
                    "platform": r_dict["platform"],
                    "page_id": r_dict["page_id"],
                    "account_name": r_dict["account_name"] or r_dict["platform"].upper(),
                    "post_type": r_dict["post_type"],
                    "caption": r_dict["caption"] or "",
                    "media_preview_url": live_preview_url,
                    "external_post_id": ext_id,
                    "permalink_url": cur_permalink,
                    "scheduled_iso": sched_dt.isoformat() if sched_dt else "",
                    "date_str": sched_dt.strftime("%Y-%m-%d") if sched_dt else "",
                    "display_date": sched_dt.strftime("%b %d, %Y") if sched_dt else "",
                    "time_str": sched_dt.strftime("%I:%M %p") if sched_dt else "",
                    "display_datetime": sched_dt.strftime("%b %d, %Y • %I:%M %p") if sched_dt else "",
                    "day": sched_dt.day if sched_dt else 1,
                    "month": sched_dt.month if sched_dt else 1,
                    "year": sched_dt.year if sched_dt else 2026,
                    "status": cur_status,
                    "status_message": clean_status_msg
                })
            return {"status": "success", "items": items}
    except Exception as e:
        return {"status": "error", "items": [], "message": str(e)}

@router.get("/api/storage/gdrive-status")
def get_gdrive_storage_status():
    state = _load_gdrive_auth_store(force_cloud=False)
    return {
        "status": "connected" if state.get("refresh_token") else "oauth_pending",
        "gdrive_configured": is_gdrive_media_configured(),
        "gdrive_authorized": bool(state.get("refresh_token")),
        "bucket_name": GOOGLE_DRIVE_FOLDER_NAME,
        "bucket_id": state.get("folder_id") or "",
        "connected_email": state.get("connected_email") or "",
        "cloudinary_json_files_preserved": 6
    }

@router.delete("/api/scheduled/{record_id}")
def delete_scheduled_post(record_id: str):
    try:
        queued_media_to_clean = []
        try:
            existing_job = scheduler.get_job(record_id)
            if existing_job and existing_job.args:
                for arg_item in existing_job.args:
                    if isinstance(arg_item, list) and arg_item and isinstance(arg_item[0], dict) and ("url" in arg_item[0] or "public_id" in arg_item[0]):
                        queued_media_to_clean = arg_item
                        break
            scheduler.remove_job(record_id)
        except Exception:
            pass

        if queued_media_to_clean:
            threading.Thread(target=cleanup_cloudinary, args=(queued_media_to_clean,), daemon=True).start()

        # Also cancel pre-registered scheduled post on Zernio if it has not been published yet
        try:
            with db_engine.connect() as conn:
                row_del = conn.execute(
                    text("SELECT status, external_post_id, status_message, platform, page_id FROM glennbot_scheduled_posts WHERE id = :id"),
                    {"id": record_id}
                ).fetchone()
            if row_del and str(row_del[0] or "").strip().lower() != "published":
                cand_zid = str(row_del[1] or "").strip()
                s_msg_del = str(row_del[2] or "").strip()
                m_z_del = re.search(r"(?:External API ID|Zernio ID):\s*([^\s,|]+)", s_msg_del)
                z_to_cancel = m_z_del.group(1).strip() if m_z_del else cand_zid
                if z_to_cancel:
                    threading.Thread(
                        target=_cancel_zernio_scheduled_post,
                        args=(z_to_cancel, str(row_del[3] or ""), str(row_del[4] or "")),
                        daemon=True
                    ).start()
        except Exception:
            pass

        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM glennbot_scheduled_posts WHERE id = :id"), {"id": record_id})
        if record_id in (CLOUDINARY_COMMENTS_STORE.get("posts") or {}):
            CLOUDINARY_COMMENTS_STORE["posts"].pop(record_id, None)
            save_comments_store_async()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

_VAULT_TRANSFER_LOCKS_GUARD = threading.Lock()
_VAULT_TRANSFER_LOCKS: Dict[str, threading.Lock] = {}
# Short-lived (10-minute) in-memory cache so multi-platform batch posts (e.g. FB + IG + TikTok + YT submitted at once)
# only transfer a Vault file from Google Drive -> Zernio once per batch, while never polluting the Files Vault JSON with a 7-day expiring Zernio URL!
_RECENT_VAULT_ZERNIO_BATCH_CACHE: Dict[str, Dict[str, Any]] = {}

def _get_vault_transfer_lock(file_id: str) -> threading.Lock:
    with _VAULT_TRANSFER_LOCKS_GUARD:
        lk = _VAULT_TRANSFER_LOCKS.get(file_id)
        if lk is None:
            lk = threading.Lock()
            _VAULT_TRANSFER_LOCKS[file_id] = lk
        return lk

def _transfer_vault_file_to_zernio_media_item(
    file_id: str,
    platform: str,
    account_id: str,
    is_thumb: bool = False,
    record_id: str = "",
    defer_to_runtime: bool = False,
    preferred_api_key: str = "",
    **kwargs
) -> Optional[Dict[str, Any]]:
    """
    Looks up an already-uploaded file from the 'Files' modal (Google Drive Vault) by its
    Python-generated file_id (e.g. file_...) and transfers/streams it directly from Google Drive
    into Zernio's native presigned media cloud (media.zernio.com) at publish/schedule time.
    If 'defer_to_runtime' is True (e.g. for posts scheduled >6 days in advance), returns a
    Google Drive Vault media reference so Zernio's 7-day media expiration is never hit early!
    Marks 'is_vault_file': True so post-publish cleanup NEVER deletes the user's Google Drive Vault file!
    """
    fid = (file_id or "").strip()
    if not fid:
        return None

    file_lock = _get_vault_transfer_lock(fid)
    with file_lock:
        store = _load_files_vault_store(force_cloud=False)
        target = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == fid), None)
        if not target:
            store = _load_files_vault_store(force_cloud=True)
            target = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == fid), None)
        if not target:
            raise RuntimeError(f"Vault File ID '{fid}' was not found in the Files Vault.")

        refreshed = _refresh_vault_file_entry_urls(target)
        dl_url = str(refreshed.get("download_url") or "").strip()
        gdrive_fname = str(refreshed.get("gdrive_file_name") or refreshed.get("filename") or "").strip()
        gdrive_fid = str(refreshed.get("gdrive_file_id") or "").strip()
        orig_name = str(refreshed.get("filename") or os.path.basename(gdrive_fname) or fid).strip()
        if orig_name.startswith("file_") and "_" in orig_name[5:]:
            orig_name = re.sub(r"^file_[a-fA-F0-9]+_", "", orig_name)
        ctype = str(refreshed.get("content_type") or "").strip().lower()
        permanent_preview_url = f"/api/files/{fid}/stream"

        if is_thumb:
            media_type = "image"
        else:
            media_type = _detect_attachment_media_category(orig_name, ctype, fallback_type="file")

        if record_id and "LAST_UPLOAD_HEARTBEAT_TS" in globals():
            LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()

        # If scheduled >6 days in advance, do NOT upload to Zernio yet (since Zernio deletes temp media after 7 days).
        # Keep the item pointing to Google Drive so APScheduler bridges it to Zernio on the scheduled day!
        if defer_to_runtime:
            print(f"[📅 DEFERRED GOOGLE DRIVE -> ZERNIO] Holding '{orig_name}' ({fid}) in Google Drive until scheduled publish day.")
            return {
                "url": permanent_preview_url,
                "preview_url": permanent_preview_url,
                "public_id": gdrive_fid or gdrive_fname or permanent_preview_url,
                "gdrive_file_id": gdrive_fid,
                "gdrive_file_name": gdrive_fname,
                "filename": orig_name,
                "content_type": ctype,
                "storage": "google_drive",
                "type": "image" if is_thumb else media_type,
                "is_thumb": bool(is_thumb),
                "is_vault_file": True,
                "vault_file_id": fid
            }

        # Check short-lived 10-minute batch cache (when publishing the same file to multiple platforms at the same moment)
        batch_entry = _RECENT_VAULT_ZERNIO_BATCH_CACHE.get(fid)
        if batch_entry and (time.time() - float(batch_entry.get("ts") or 0) < 600):
            cached_z_url = str(batch_entry.get("url") or "").strip()
            if cached_z_url and "media.zernio.com" in cached_z_url:
                print(f"[⚡ VAULT MULTI-PLATFORM BATCH HIT] Reusing fresh Zernio URL for {orig_name} ({fid}) -> {cached_z_url[:80]}")
                return {
                    "url": cached_z_url,
                    "preview_url": permanent_preview_url,
                    "public_id": cached_z_url,
                    "gdrive_file_id": gdrive_fid,
                    "gdrive_file_name": gdrive_fname,
                    "filename": orig_name,
                    "content_type": ctype,
                    "storage": "zernio",
                    "type": "image" if is_thumb else media_type,
                    "is_thumb": bool(is_thumb),
                    "is_vault_file": True,
                    "vault_file_id": fid
                }

        api_key_for_acc = (preferred_api_key or "").strip()
        if not api_key_for_acc:
            try:
                resolved_acc = resolve_zernio_account_id(platform, account_id)
                api_key_for_acc = get_zernio_key_for_account(resolved_acc, platform=platform)
            except Exception:
                api_key_for_acc = ""
        if not api_key_for_acc:
            all_k = get_all_zernio_keys()
            api_key_for_acc = all_k[0] if all_k else ENV_EXTERNAL_API_KEY

        if record_id and not is_thumb:
            update_post_status(
                record_id,
                "processing_payload",
                f"Processing Payload • Transferring '{orig_name}' [{fid}] from Google Drive Vault to Zernio Cloud..."
            )

        gdrive_source_url = str(dl_url or "").strip()
        expected_size = int(refreshed.get("size_bytes") or 0)
        bridged_url, bridge_err = bridge_gdrive_media_to_zernio_presign(
            source_url=gdrive_source_url,
            filename=orig_name or gdrive_fname,
            media_type=media_type,
            api_key=api_key_for_acc,
            record_id=(record_id if not is_thumb else ""),
            vault_file_id=fid,
            expected_file_size=expected_size,
            platform=platform,
            account_id=account_id,
            gdrive_file_id=gdrive_fid
        )
        if not bridged_url and bridge_err:
            raise RuntimeError(bridge_err)

        final_url = bridged_url if (bridged_url and bridged_url.startswith("http")) else dl_url
        if not final_url or not final_url.startswith("http"):
            raise RuntimeError(bridge_err or f"Could not resolve downloadable URL for Vault file '{fid}' ({orig_name}).")

        if bridged_url and "media.zernio.com" in bridged_url:
            _RECENT_VAULT_ZERNIO_BATCH_CACHE[fid] = {
                "url": bridged_url,
                "ts": time.time()
            }

        storage_used = "zernio" if "media.zernio.com" in final_url else "google_drive"
        print(f"[📦->🚀 GOOGLE DRIVE TO ZERNIO TRANSFER] {orig_name} ({fid}) | Storage: {storage_used.upper()} | URL: {final_url[:90]}")
        return {
            "url": final_url,
            "preview_url": permanent_preview_url,
            "public_id": final_url if storage_used == "zernio" else (gdrive_fid or gdrive_fname or final_url),
            "gdrive_file_id": gdrive_fid,
            "gdrive_file_name": gdrive_fname,
            "filename": orig_name,
            "content_type": ctype,
            "storage": storage_used,
            "type": "image" if is_thumb else media_type,
            "is_thumb": bool(is_thumb),
            "is_vault_file": True,
            "vault_file_id": fid
        }


def _process_schedule_payload_background(
    record_id: str,
    platform: str,
    post_type: str,
    pageId: str,
    accountName: str,
    title: str,
    caption: str,
    scheduled_time: datetime,
    media_bytes: Optional[bytes],
    media_filename: str,
    thumb_bytes: Optional[bytes],
    thumb_filename: str,
    image_buffers: List[Dict[str, Any]],
    vault_media_file_id: str = "",
    vault_thumb_file_id: str = "",
    vault_media_file_ids: Optional[List[str]] = None
):
    manila_tz = pytz.timezone("Asia/Manila")
    now_manila_init = datetime.now(manila_tz)
    sched_local_init = scheduled_time.astimezone(manila_tz) if getattr(scheduled_time, "tzinfo", None) else manila_tz.localize(scheduled_time)
    defer_zernio_for_long_schedule = (sched_local_init - now_manila_init).total_seconds() > 6 * 86400
    media_items = []
    preview_url = ""
    use_gdrive = is_gdrive_media_configured()
    if "LAST_UPLOAD_HEARTBEAT_TS" in globals():
        LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    if "ACTIVE_BACKGROUND_SCHEDULE_JOBS" in globals():
        ACTIVE_BACKGROUND_SCHEDULE_JOBS.add(record_id)

    try:
        if post_type in ['reels', 'video169']:
            if (vault_media_file_id or "").strip():
                v_item = _transfer_vault_file_to_zernio_media_item(
                    file_id=vault_media_file_id.strip(),
                    platform=platform,
                    account_id=pageId,
                    is_thumb=False,
                    record_id=record_id,
                    defer_to_runtime=defer_zernio_for_long_schedule
                )
                if v_item:
                    media_items.append(v_item)
                    preview_url = v_item.get("preview_url") or v_item["url"]
            elif media_bytes and media_filename:
                z_vid = None if defer_zernio_for_long_schedule else upload_bytes_to_zernio_presign(
                    media_bytes,
                    media_filename,
                    media_type="video",
                    is_thumb=False,
                    platform=platform,
                    account_id=pageId
                )
                if z_vid:
                    media_items.append(z_vid)
                    preview_url = z_vid["url"]
                elif use_gdrive:
                    gd_vid = upload_media_to_gdrive(media_bytes, media_filename, media_type="video", is_thumb=False)
                    media_items.append(gd_vid)
                    preview_url = gd_vid["url"]
                else:
                    res = cloudinary.uploader.upload(io.BytesIO(media_bytes), resource_type="video", folder="glennbot")
                    media_items.append({'url': res['secure_url'], 'public_id': res['public_id'], 'type': 'video', 'storage': 'cloudinary'})
                    preview_url = res['secure_url']

            if (vault_thumb_file_id or "").strip():
                vt_item = _transfer_vault_file_to_zernio_media_item(
                    file_id=vault_thumb_file_id.strip(),
                    platform=platform,
                    account_id=pageId,
                    is_thumb=True,
                    record_id=record_id,
                    defer_to_runtime=defer_zernio_for_long_schedule
                )
                if vt_item:
                    media_items.append(vt_item)
                    preview_url = vt_item.get("preview_url") or vt_item["url"]
                    print(f"[✅ VAULT THUMBNAIL READY FOR ZERNIO] Platform: {platform.upper()} | File ID: {vault_thumb_file_id} | URL: {vt_item['url']}")
            elif thumb_bytes and thumb_filename:
                z_thumb = None if defer_zernio_for_long_schedule else upload_bytes_to_zernio_presign(
                    thumb_bytes,
                    thumb_filename,
                    media_type="image",
                    is_thumb=True,
                    platform=platform,
                    account_id=pageId
                )
                if z_thumb:
                    media_items.append(z_thumb)
                    preview_url = z_thumb["url"]
                    print(f"[✅ ZERNIO THUMBNAIL UPLOADED] Platform: {platform.upper()} | URL: {z_thumb['url']}")
                elif use_gdrive:
                    gd_thumb = upload_media_to_gdrive(thumb_bytes, thumb_filename, media_type="image", is_thumb=True)
                    media_items.append(gd_thumb)
                    preview_url = gd_thumb["url"]
                    print(f"[✅ GOOGLE DRIVE THUMBNAIL UPLOADED] Platform: {platform.upper()} | URL: {gd_thumb['url']}")
                else:
                    try:
                        # Normalize thumbnail to JPEG so Facebook, Instagram, YouTube, and TikTok always accept the image format
                        res_t = cloudinary.uploader.upload(io.BytesIO(thumb_bytes), resource_type="image", folder="glennbot", format="jpg")
                    except Exception:
                        res_t = cloudinary.uploader.upload(io.BytesIO(thumb_bytes), resource_type="image", folder="glennbot")
                    media_items.append({'url': res_t['secure_url'], 'public_id': res_t['public_id'], 'type': 'image', 'is_thumb': True, 'storage': 'cloudinary'})
                    preview_url = res_t['secure_url']
                    print(f"[✅ CLOUDINARY THUMBNAIL UPLOADED] Platform: {platform.upper()} | URL: {res_t['secure_url']}")

        elif post_type == 'image':
            if vault_media_file_ids:
                for vf_id in vault_media_file_ids:
                    clean_vf = str(vf_id or "").strip()
                    if not clean_vf:
                        continue
                    v_img = _transfer_vault_file_to_zernio_media_item(
                        file_id=clean_vf,
                        platform=platform,
                        account_id=pageId,
                        is_thumb=False,
                        record_id=record_id,
                        defer_to_runtime=defer_zernio_for_long_schedule
                    )
                    if v_img:
                        v_img["type"] = "image"
                        media_items.append(v_img)
                        if not preview_url:
                            preview_url = v_img.get("preview_url") or v_img["url"]
            if image_buffers:
                for img_obj in image_buffers:
                    if img_obj.get("bytes") and img_obj.get("filename"):
                        z_img = upload_bytes_to_zernio_presign(
                            img_obj["bytes"],
                            img_obj["filename"],
                            media_type="image",
                            is_thumb=False,
                            platform=platform,
                            account_id=pageId
                        )
                        if z_img:
                            media_items.append(z_img)
                            if not preview_url:
                                preview_url = z_img["url"]
                        elif use_gdrive:
                            gd_img = upload_media_to_gdrive(img_obj["bytes"], img_obj["filename"], media_type="image", is_thumb=False)
                            media_items.append(gd_img)
                            if not preview_url:
                                preview_url = gd_img["url"]
                        else:
                            res = cloudinary.uploader.upload(io.BytesIO(img_obj["bytes"]), resource_type="image", folder="glennbot")
                            media_items.append({'url': res['secure_url'], 'public_id': res['public_id'], 'type': 'image', 'storage': 'cloudinary'})
                            if not preview_url:
                                preview_url = res['secure_url']
    except Exception as e:
        err_msg = f"Failed to upload media payload: {e}"
        print(f"[❌ BACKGROUND PAYLOAD UPLOAD ERROR] {record_id}: {err_msg}")
        update_post_status(record_id, "failed", err_msg)
        if "ACTIVE_BACKGROUND_SCHEDULE_JOBS" in globals():
            ACTIVE_BACKGROUND_SCHEDULE_JOBS.discard(record_id)
        if "LAST_UPLOAD_HEARTBEAT_TS" in globals():
            LAST_UPLOAD_HEARTBEAT_TS.pop(record_id, None)
        return

    # Check if the user cancelled/deleted the post while it was uploading
    try:
        with db_engine.begin() as conn:
            row_exists = conn.execute(
                text("SELECT id FROM glennbot_scheduled_posts WHERE id = :id"),
                {"id": record_id}
            ).fetchone()
            if not row_exists:
                print(f"[ℹ️ SCHEDULE CANCELLED DURING UPLOAD] {record_id} was removed by user.")
                if media_items:
                    cleanup_cloudinary(media_items)
                return

            conn.execute(
                text("""
                    UPDATE glennbot_scheduled_posts
                    SET media_preview_url = :preview,
                        status = 'waiting',
                        status_message = 'Waiting for schedule...'
                    WHERE id = :id
                """),
                {
                    "id": record_id,
                    "preview": preview_url
                }
            )
    except Exception as e:
        print(f"[⚠️ DB UPDATE AFTER PAYLOAD UPLOAD ERROR]: {e}")
    finally:
        if "ACTIVE_BACKGROUND_SCHEDULE_JOBS" in globals():
            ACTIVE_BACKGROUND_SCHEDULE_JOBS.discard(record_id)
        if "LAST_UPLOAD_HEARTBEAT_TS" in globals():
            LAST_UPLOAD_HEARTBEAT_TS.pop(record_id, None)

    # Pre-register future scheduled post on Zernio so Zernio holds the media and publishes on schedule
    register_scheduled_post_on_zernio(
        record_id=record_id,
        platform=platform,
        account_id=pageId,
        post_type=post_type,
        caption=caption,
        media_items=media_items,
        title=title,
        scheduled_time=scheduled_time
    )

    now_manila = datetime.now(manila_tz)
    effective_run_date = max(scheduled_time, now_manila + timedelta(seconds=3))

    if platform == "facebook":
        scheduler.add_job(post_to_facebook, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, post_type, caption, media_items], misfire_grace_time=3600)
    elif platform == "instagram":
        scheduler.add_job(post_to_instagram, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, post_type, caption, media_items], misfire_grace_time=3600)
    elif platform == "tiktok":
        scheduler.add_job(post_to_tiktok, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, caption, media_items], misfire_grace_time=3600)
    elif platform == "youtube":
        scheduler.add_job(post_to_youtube, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, post_type, caption, media_items, title], misfire_grace_time=3600)

    base_cleanup_time = max(effective_run_date, now_manila)
    cleanup_time = base_cleanup_time + timedelta(minutes=20)
    scheduler.add_job(cleanup_cloudinary, 'date', run_date=cleanup_time, args=[media_items], misfire_grace_time=3600)


# ==============================================================================
# --- CHUNKED LARGE-VIDEO SCHEDULE UPLOAD ENGINE (ZERNIO / GOOGLE DRIVE) ---
# Prevents 1.4GB - 5GB+ videos from hitting proxy timeouts, browser fetch drops,
# or server Out-Of-Memory (OOM) crashes, and registers the DB row BEFORE upload starts
# so scheduled posts NEVER vanish from Queue & Calendar!
# ==============================================================================
CHUNKED_SCHEDULE_SESSIONS: Dict[str, Dict[str, Any]] = {}
CHUNKED_SCHEDULE_LOCK = threading.Lock()
LAST_UPLOAD_HEARTBEAT_TS: Dict[str, float] = {}
ACTIVE_BACKGROUND_SCHEDULE_JOBS: set = set()

def _format_bytes_label(num_bytes: int) -> str:
    b = max(0, int(num_bytes or 0))
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024.0 ** 3):.2f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024.0 ** 2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024.0:.1f} KB"
    return f"{b} B"

def _schedule_chunked_init_sync(
    platform: str,
    post_type: str,
    pageId: str,
    accountName: str,
    date_val: str,
    time_val: str,
    title: str,
    caption: str,
    media_filename: str,
    media_total_size: int,
    total_parts: int,
    thumb_bytes: Optional[bytes],
    thumb_filename: str,
    vault_thumb_file_id: str = ""
):
    manila_tz = pytz.timezone("Asia/Manila")
    now_manila = datetime.now(manila_tz)

    if date_val and time_val:
        scheduled_time = manila_tz.localize(datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M"))
    else:
        scheduled_time = now_manila + timedelta(seconds=10)

    record_id = f"post_{uuid.uuid4().hex[:12]}"
    LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    display_caption = (
        f"{title.strip()}\n{caption.strip()}".strip()
        if (platform == "youtube" and title.strip() and caption.strip() and title.strip() != caption.strip())
        else (title.strip() or caption)
    )

    size_label = _format_bytes_label(media_total_size)
    init_status_msg = f"Processing Payload • Initializing {size_label} Direct Cloud Upload (0%)..."

    # 1. Immediately persist row in Database so it NEVER vanishes from Queue or Calendar!
    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO glennbot_scheduled_posts 
                    (id, platform, page_id, account_name, post_type, caption, media_preview_url, scheduled_time, status, status_message)
                    VALUES (:id, :platform, :page_id, :account_name, :post_type, :caption, :preview, :sched_time, 'processing_payload', :status_msg)
                """),
                {
                    "id": record_id,
                    "platform": platform,
                    "page_id": pageId,
                    "account_name": accountName or platform.capitalize(),
                    "post_type": post_type,
                    "caption": display_caption,
                    "preview": "",
                    "sched_time": scheduled_time,
                    "status_msg": init_status_msg
                }
            )
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Database insert failed: {e}"}, status_code=500)

    use_gdrive = is_gdrive_media_configured()
    safe_orig = re.sub(r"[^a-zA-Z0-9._-]", "_", os.path.basename(media_filename or "video.mp4"))
    if "." not in safe_orig:
        safe_orig = f"{safe_orig}.mp4"
    gdrive_file_name = f"glennbot/videos/{int(time.time())}_{uuid.uuid4().hex[:8]}_{safe_orig}"
    guessed_mime, _ = mimetypes.guess_type(safe_orig)
    content_type = _normalize_zernio_content_type(safe_orig, guessed_mime or "", "video")

    # PRIMARY FOR ALL SCHEDULED SOCIAL MEDIA POSTS: Zernio Native Presigned Media Cloud (POST /v1/media/presign)
    # Supports up to 5GB (4GB on Facebook) and prevents Facebook error 389/1363057!
    z_target = get_zernio_presigned_upload_target(
        filename=safe_orig,
        content_type=content_type,
        file_size=int(media_total_size or 0),
        platform=platform,
        account_id=pageId
    )
    zernio_upload_url = z_target.get("upload_url") or ""
    zernio_public_url = z_target.get("public_url") or ""
    if z_target.get("content_type"):
        content_type = z_target["content_type"]
    if zernio_upload_url and zernio_public_url:
        print(f"[🚀 ZERNIO DIRECT CLOUD INIT] {record_id} | {safe_orig} ({size_label}) -> {zernio_public_url}")

    mode = "zernio_direct" if (zernio_upload_url and zernio_public_url) else ("gdrive_single" if use_gdrive else "cloudinary_single")
    cors_ready = False
    direct_upload_url = ""
    direct_upload_auth_token = ""

    with CHUNKED_SCHEDULE_LOCK:
        CHUNKED_SCHEDULE_SESSIONS[record_id] = {
            "record_id": record_id,
            "platform": platform,
            "post_type": post_type,
            "pageId": pageId,
            "accountName": accountName,
            "title": title,
            "caption": caption,
            "scheduled_time": scheduled_time,
            "media_filename": media_filename,
            "media_total_size": int(media_total_size or 0),
            "total_parts": max(1, int(total_parts or 1)),
            "thumb_bytes": thumb_bytes,
            "thumb_filename": thumb_filename,
            "vault_thumb_file_id": (vault_thumb_file_id or "").strip(),
            "mode": mode,
            "zernio_upload_url": zernio_upload_url,
            "zernio_public_url": zernio_public_url,
            "zernio_http_conn": None,
            "zernio_stream_failed": False,
            "gdrive_file_name": gdrive_file_name,
            "content_type": content_type,
            "part_sha1_map": {},
            "uploaded_video_item": None,
            "fallback_buffer": bytearray(),
            "created_at": time.time()
        }

    return {
        "status": "success",
        "id": record_id,
        "mode": mode,
        "zernio_upload_url": zernio_upload_url,
        "zernio_public_url": zernio_public_url,
        "gdrive_file_name": gdrive_file_name,
        "content_type": content_type,
        "upload_url": direct_upload_url,
        "upload_auth_token": direct_upload_auth_token,
        "cors_ready": cors_ready,
        "queue_status": "processing_payload"
    }


@router.post("/api/schedule/chunked/init")
async def schedule_chunked_init(
    platform: str = Form(...),
    post_type: str = Form(...),
    pageId: str = Form(""),
    accountName: str = Form(""),
    date_val: str = Form("", alias="date"),
    time_val: str = Form("", alias="time"),
    title: str = Form(""),
    caption: str = Form(""),
    media_filename: str = Form(""),
    media_total_size: int = Form(0),
    total_parts: int = Form(1),
    thumbnail: Optional[UploadFile] = File(None),
    vault_thumb_file_id: str = Form("")
):
    thumb_bytes: Optional[bytes] = None
    thumb_filename = ""
    if thumbnail and thumbnail.filename:
        try:
            thumb_filename = thumbnail.filename
            thumb_bytes = await thumbnail.read()
        except Exception as e:
            print(f"[⚠️ CHUNKED INIT THUMB READ WARNING]: {e}")

    return await run_in_threadpool(
        _schedule_chunked_init_sync,
        platform,
        post_type,
        pageId,
        accountName,
        date_val,
        time_val,
        title,
        caption,
        media_filename,
        media_total_size,
        total_parts,
        thumb_bytes,
        thumb_filename,
        vault_thumb_file_id
    )


@router.post("/api/schedule/chunked/zernio-presign")
def schedule_chunked_zernio_presign(
    record_id: str = Form(...),
    media_filename: str = Form("video.mp4"),
    media_total_size: int = Form(0),
    platform: str = Form(""),
    pageId: str = Form("")
):
    """
    Generates a fresh Zernio Presigned PUT URL (media.zernio.com) if the browser's XHR PUT
    needs to retry after a network drop on a 1.4GB+ video—keeping 100% of video traffic off Render.com!
    """
    LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    with CHUNKED_SCHEDULE_LOCK:
        session = CHUNKED_SCHEDULE_SESSIONS.get(record_id)
    eff_fname = (session.get("media_filename") if session else "") or media_filename or "video.mp4"
    eff_size = int((session.get("media_total_size") if session else 0) or media_total_size or 0)
    eff_plat = (session.get("platform") if session else "") or platform
    eff_page = (session.get("pageId") if session else "") or pageId
    safe_orig = re.sub(r"[^a-zA-Z0-9._-]", "_", os.path.basename(eff_fname))
    if "." not in safe_orig:
        safe_orig = f"{safe_orig}.mp4"
    guessed_mime, _ = mimetypes.guess_type(safe_orig)
    ct = _normalize_zernio_content_type(safe_orig, guessed_mime or "", "video")
    z_target = get_zernio_presigned_upload_target(
        filename=safe_orig,
        content_type=ct,
        file_size=eff_size,
        platform=eff_plat,
        account_id=eff_page
    )
    up_url = z_target.get("upload_url") or ""
    pub_url = z_target.get("public_url") or ""
    eff_ct = z_target.get("content_type") or ct
    if session and up_url and pub_url:
        with CHUNKED_SCHEDULE_LOCK:
            session["zernio_upload_url"] = up_url
            session["zernio_public_url"] = pub_url
            session["content_type"] = eff_ct
    return {
        "status": "success" if (up_url and pub_url) else "error",
        "id": record_id,
        "zernio_upload_url": up_url,
        "zernio_public_url": pub_url,
        "content_type": eff_ct
    }


@router.post("/api/schedule/chunked/part-url")
def schedule_chunked_part_url(
    record_id: str = Form(...),
    mode: str = Form("gdrive_single")
):
    """
    Returns upload status for chunked schedule sessions.
    """
    LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    with CHUNKED_SCHEDULE_LOCK:
        session = CHUNKED_SCHEDULE_SESSIONS.get(record_id)
    eff_mode = (session.get("mode") if session else mode) or "gdrive_single"
    if eff_mode == "zernio_direct":
        eff_mode = "gdrive_single"
        if session:
            with CHUNKED_SCHEDULE_LOCK:
                session["mode"] = eff_mode
    return {
        "status": "success",
        "id": record_id,
        "mode": eff_mode,
        "upload_url": "",
        "upload_auth_token": ""
    }


@router.post("/api/schedule/chunked/part-confirm")
def schedule_chunked_part_confirm(
    record_id: str = Form(...),
    part_number: int = Form(...),
    total_parts: int = Form(1),
    sha1: str = Form(""),
    gdrive_file_id: str = Form(""),
    gdrive_file_name: str = Form(""),
    media_total_size: int = Form(0),
    storage_target: str = Form("")
):
    """
    Lightweight metadata confirmation after the browser finishes uploading a part or progress step
    DIRECTLY to Zernio Media Cloud or Google Drive.
    """
    LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    with CHUNKED_SCHEDULE_LOCK:
        session = CHUNKED_SCHEDULE_SESSIONS.get(record_id)

    # Check if user deleted/cancelled the post from Queue while uploading
    try:
        with db_engine.connect() as conn:
            row_exists = conn.execute(
                text("SELECT id FROM glennbot_scheduled_posts WHERE id = :id"),
                {"id": record_id}
            ).fetchone()
            if not row_exists:
                with CHUNKED_SCHEDULE_LOCK:
                    CHUNKED_SCHEDULE_SESSIONS.pop(record_id, None)
                return {"status": "cancelled", "message": "Scheduled post was cancelled by user."}
    except Exception:
        pass

    p_num = int(part_number)
    tot_parts = max(1, int(total_parts or (session.get("total_parts") if session else 1) or 1))
    clean_sha1 = (sha1 or "").strip().lower()

    if session:
        with CHUNKED_SCHEDULE_LOCK:
            if clean_sha1:
                session["part_sha1_map"][p_num] = clean_sha1
            if session.get("mode") == "gdrive_single" and tot_parts == 1 and clean_sha1:
                eff_fname = (gdrive_file_name or session.get("gdrive_file_name") or "").strip()
                eff_fid = (gdrive_file_id or "").strip()
                if eff_fid or eff_fname:
                    signed_u = build_gdrive_file_url(eff_fid or eff_fname)
                    session["uploaded_video_item"] = {
                        "url": signed_u,
                        "public_id": eff_fid or eff_fname,
                        "gdrive_file_id": eff_fid,
                        "gdrive_file_name": eff_fname,
                        "storage": "google_drive",
                        "type": "video",
                        "is_thumb": False
                    }

    eff_size = int(media_total_size or (session.get("media_total_size") if session else 0) or 0)
    pct = min(99, max(1, int(round((p_num / float(tot_parts)) * 100))))
    size_label = _format_bytes_label(eff_size)
    if (storage_target or "").lower() == "zernio" or (session and session.get("mode") == "zernio_direct" and not clean_sha1):
        progress_msg = f"Processing Payload • Direct-Uploading {size_label} to Zernio Media Cloud ({pct}%)..."
    else:
        progress_msg = f"Processing Payload • Direct-Uploading {size_label} to Google Drive ({pct}% • Part {p_num}/{tot_parts})..."
    update_post_status(record_id, "processing_payload", progress_msg)

    return {
        "status": "success",
        "id": record_id,
        "part_number": p_num,
        "total_parts": tot_parts,
        "percent": pct,
        "status_message": progress_msg
    }


@router.post("/api/schedule/chunked/part")
async def schedule_chunked_part(
    record_id: str = Form(...),
    part_number: int = Form(...),
    total_parts: int = Form(1),
    chunk: UploadFile = File(...)
):
    LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    chunk_bytes = await chunk.read()
    if not chunk_bytes:
        return JSONResponse({"status": "error", "message": f"Empty chunk received for part #{part_number}."}, status_code=400)

    return await run_in_threadpool(
        _schedule_chunked_part_sync,
        record_id,
        part_number,
        total_parts,
        chunk_bytes
    )


def _schedule_chunked_part_sync(
    record_id: str,
    part_number: int,
    total_parts: int,
    chunk_bytes: bytes
):
    with CHUNKED_SCHEDULE_LOCK:
        session = CHUNKED_SCHEDULE_SESSIONS.get(record_id)
    if not session:
        return JSONResponse({"status": "error", "message": f"Upload session '{record_id}' not found or expired."}, status_code=404)

    # Check if user deleted/cancelled the post from Queue while uploading
    try:
        with db_engine.connect() as conn:
            row_exists = conn.execute(
                text("SELECT id FROM glennbot_scheduled_posts WHERE id = :id"),
                {"id": record_id}
            ).fetchone()
            if not row_exists:
                z_conn_old = session.get("zernio_http_conn")
                if z_conn_old:
                    try:
                        z_conn_old.close()
                    except Exception:
                        pass
                with CHUNKED_SCHEDULE_LOCK:
                    CHUNKED_SCHEDULE_SESSIONS.pop(record_id, None)
                return {"status": "cancelled", "message": "Scheduled post was cancelled by user."}
    except Exception:
        pass

    mode = session.get("mode")
    tot_parts = max(1, int(total_parts or session.get("total_parts") or 1))
    p_num = int(part_number)
    used_zernio_stream = False

    try:
        # 1. Zero-RAM Chunked Stream Pipe directly into Zernio's Presigned Media Cloud (if browser direct PUT fell back due to CORS)
        z_up_url = str(session.get("zernio_upload_url") or "").strip()
        z_pub_url = str(session.get("zernio_public_url") or "").strip()
        total_expected_bytes = int(session.get("media_total_size") or 0)
        if z_up_url and z_pub_url and total_expected_bytes > 0 and not session.get("zernio_stream_failed"):
            try:
                z_conn = session.get("zernio_http_conn")
                if p_num == 1 or z_conn is None:
                    if z_conn is not None:
                        try:
                            z_conn.close()
                        except Exception:
                            pass
                    parsed_z = urllib.parse.urlparse(z_up_url)
                    z_conn = http.client.HTTPSConnection(parsed_z.netloc, timeout=600)
                    z_path = parsed_z.path + (f"?{parsed_z.query}" if parsed_z.query else "")
                    z_conn.putrequest("PUT", z_path)
                    z_conn.putheader("Content-Type", str(session.get("content_type") or "video/mp4"))
                    z_conn.putheader("Content-Length", str(total_expected_bytes))
                    z_conn.endheaders()
                    with CHUNKED_SCHEDULE_LOCK:
                        session["zernio_http_conn"] = z_conn
                        session["mode"] = "zernio_stream"
                z_conn.send(chunk_bytes)
                used_zernio_stream = True
            except Exception as z_stream_err:
                print(f"[⚠️ ZERNIO STREAM PIPE FALLBACK] Part #{p_num} error ({z_stream_err}); falling back to Google Drive if part 1.")
                with CHUNKED_SCHEDULE_LOCK:
                    session["zernio_stream_failed"] = True
                    old_c = session.pop("zernio_http_conn", None)
                if old_c:
                    try:
                        old_c.close()
                    except Exception:
                        pass
                if p_num > 1:
                    raise RuntimeError(f"Zernio stream interrupted at part #{p_num}: {z_stream_err}")
                mode = "gdrive_single" if is_gdrive_media_configured() else "cloudinary_single"
                with CHUNKED_SCHEDULE_LOCK:
                    session["mode"] = mode

        if not used_zernio_stream:
            if is_gdrive_media_configured():
                if tot_parts == 1:
                    gd_vid = upload_media_to_gdrive(chunk_bytes, session["media_filename"], media_type="video", is_thumb=False)
                    with CHUNKED_SCHEDULE_LOCK:
                        session["uploaded_video_item"] = gd_vid
                else:
                    # Stream each chunk directly to Google Drive Resumable Upload API (0 MB RAM accumulation!)
                    resumable_uri = str(session.get("gdrive_resumable_url") or "").strip()
                    if not resumable_uri:
                        resumable_uri = gdrive_init_resumable_upload(
                            filename=session["media_filename"],
                            content_type=session.get("media_content_type") or "video/mp4",
                            total_size=int(session.get("media_total_size") or 0)
                        )
                        with CHUNKED_SCHEDULE_LOCK:
                            session["gdrive_resumable_url"] = resumable_uri
                            session["gdrive_uploaded_offset"] = 0

                    start_b = int(session.get("gdrive_uploaded_offset") or 0)
                    end_b = start_b + len(chunk_bytes) - 1
                    tot_sz = int(session.get("media_total_size") or 0)
                    if p_num >= tot_parts or (tot_sz > 0 and (end_b + 1) >= tot_sz):
                        tot_sz_str = str(end_b + 1)
                    else:
                        tot_sz_str = str(tot_sz) if tot_sz > 0 else "*"

                    gd_put = requests.put(
                        resumable_uri,
                        headers={
                            "Content-Type": session.get("media_content_type") or "video/mp4",
                            "Content-Length": str(len(chunk_bytes)),
                            "Content-Range": f"bytes {start_b}-{end_b}/{tot_sz_str}"
                        },
                        data=chunk_bytes,
                        timeout=300
                    )
                    if gd_put.status_code not in (200, 201, 308):
                        raise RuntimeError(f"Google Drive chunk #{p_num} PUT failed ({gd_put.status_code}): {gd_put.text[:250]}")

                    with CHUNKED_SCHEDULE_LOCK:
                        session["gdrive_uploaded_offset"] = end_b + 1

                    if gd_put.status_code in (200, 201):
                        gd_json = gd_put.json() if gd_put.text else {}
                        gd_fid = str(gd_json.get("id") or "").strip()
                        if gd_fid:
                            gdrive_set_file_public_reader(gd_fid)
                            stream_u = build_gdrive_direct_stream_url(gd_fid)
                            with CHUNKED_SCHEDULE_LOCK:
                                session["uploaded_video_item"] = {
                                    "url": stream_u,
                                    "public_id": gd_fid,
                                    "gdrive_file_id": gd_fid,
                                    "gdrive_file_name": session["media_filename"],
                                    "web_view_link": str(gd_json.get("webViewLink") or f"https://drive.google.com/file/d/{gd_fid}/view"),
                                    "storage": "google_drive",
                                    "type": "video",
                                    "is_thumb": False
                                }
            else:
                with CHUNKED_SCHEDULE_LOCK:
                    session["fallback_buffer"].extend(chunk_bytes)
    except Exception as e:
        del chunk_bytes
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    del chunk_bytes
    pct = min(99, max(1, int(round((p_num / float(tot_parts)) * 100))))
    size_label = _format_bytes_label(session.get("media_total_size") or 0)
    target_cloud_label = "Zernio Media Cloud" if used_zernio_stream else "Google Drive"
    progress_msg = f"Processing Payload • Uploading {size_label} to {target_cloud_label} ({pct}% • Part {p_num}/{tot_parts})..."
    update_post_status(record_id, "processing_payload", progress_msg)

    return {
        "status": "success",
        "id": record_id,
        "part_number": p_num,
        "total_parts": tot_parts,
        "percent": pct,
        "status_message": progress_msg
    }


@router.post("/api/schedule/chunked/complete")
def schedule_chunked_complete(
    record_id: str = Form(...),
    zernio_public_url: str = Form(""),
    gdrive_file_name: str = Form(""),
    gdrive_single_file_id: str = Form(""),
    part_sha1_json: str = Form("")
):
    LAST_UPLOAD_HEARTBEAT_TS.pop(record_id, None)
    with CHUNKED_SCHEDULE_LOCK:
        session = CHUNKED_SCHEDULE_SESSIONS.pop(record_id, None)

    manila_tz = pytz.timezone("Asia/Manila")
    use_gdrive = is_gdrive_media_configured()

    # Stateless DB recovery if session was cleared (e.g., if server restarted during a long direct browser upload)
    if not session:
        try:
            with db_engine.connect() as conn:
                db_row = conn.execute(
                    text("SELECT platform, page_id, account_name, post_type, caption, scheduled_time FROM glennbot_scheduled_posts WHERE id = :id"),
                    {"id": record_id}
                ).fetchone()
            if not db_row:
                return JSONResponse({"status": "error", "message": f"Upload session '{record_id}' not found."}, status_code=404)
            sched_dt = _coerce_db_datetime(db_row[5], manila_tz)
            parsed_sha1s: List[str] = []
            if part_sha1_json:
                try:
                    parsed_sha1s = [str(x).strip() for x in (json.loads(part_sha1_json) or []) if str(x).strip()]
                except Exception:
                    parsed_sha1s = []
            rec_mode = "zernio_direct" if zernio_public_url.strip() else "gdrive_single"
            rec_plat = str(db_row[0] or "facebook")
            rec_cap = str(db_row[4] or "")
            rec_title = (rec_cap.splitlines()[0].strip() if rec_plat == "youtube" and rec_cap.strip() else "")
            session = {
                "record_id": record_id,
                "platform": rec_plat,
                "pageId": str(db_row[1] or ""),
                "accountName": str(db_row[2] or ""),
                "post_type": str(db_row[3] or "video169"),
                "title": rec_title,
                "caption": rec_cap,
                "scheduled_time": sched_dt or (datetime.now(manila_tz) + timedelta(seconds=10)),
                "thumb_bytes": None,
                "thumb_filename": "",
                "mode": rec_mode,
                "zernio_public_url": zernio_public_url.strip(),
                "gdrive_file_name": gdrive_file_name,
                "total_parts": max(1, len(parsed_sha1s)),
                "part_sha1_map": {idx + 1: h for idx, h in enumerate(parsed_sha1s)},
                "uploaded_video_item": None
            }
        except Exception as rec_err:
            return JSONResponse({"status": "error", "message": f"Upload session '{record_id}' recovery error: {rec_err}"}, status_code=404)

    platform = session["platform"]
    post_type = session["post_type"]
    pageId = session["pageId"]
    title = session["title"]
    caption = session["caption"]
    scheduled_time = session["scheduled_time"]
    thumb_bytes = session.get("thumb_bytes")
    thumb_filename = session.get("thumb_filename") or ""
    mode = session.get("mode")

    if part_sha1_json:
        try:
            client_sha1_list = [str(x).strip().lower() for x in (json.loads(part_sha1_json) or []) if str(x).strip()]
            if client_sha1_list:
                sha_map = session.get("part_sha1_map") or {}
                for idx, h_val in enumerate(client_sha1_list):
                    sha_map[idx + 1] = h_val
                session["part_sha1_map"] = sha_map
                session["total_parts"] = max(int(session.get("total_parts") or 1), len(client_sha1_list))
                if not zernio_public_url.strip() and mode == "zernio_direct":
                    mode = "gdrive_single"
        except Exception:
            pass

    media_items: List[Dict[str, Any]] = []
    preview_url = ""

    try:
        eff_zernio_pub = (zernio_public_url or session.get("zernio_public_url") or "").strip()
        z_conn = session.get("zernio_http_conn")

        # Case A: Zero-RAM Chunked Stream Pipe into Zernio Presigned Cloud finished
        if z_conn is not None and eff_zernio_pub:
            try:
                z_resp = z_conn.getresponse()
                z_resp.read()
                if z_resp.status not in (200, 201, 204):
                    raise RuntimeError(f"Zernio R2 stream finalize returned HTTP {z_resp.status}")
            finally:
                try:
                    z_conn.close()
                except Exception:
                    pass
            z_vid = {
                "url": eff_zernio_pub,
                "public_id": eff_zernio_pub,
                "storage": "zernio",
                "type": "video",
                "is_thumb": False
            }
            media_items.append(z_vid)
            preview_url = eff_zernio_pub
            print(f"[✅ ZERNIO STREAM LARGE VIDEO COMPLETED] {record_id} -> {eff_zernio_pub}")

        # Case B: Direct Browser-to-Zernio PUT finished (0 bytes passed through server)
        elif zernio_public_url.strip() or (mode == "zernio_direct" and eff_zernio_pub):
            z_vid = {
                "url": eff_zernio_pub,
                "public_id": eff_zernio_pub,
                "storage": "zernio",
                "type": "video",
                "is_thumb": False
            }
            media_items.append(z_vid)
            preview_url = eff_zernio_pub
            print(f"[✅ ZERNIO DIRECT LARGE VIDEO COMPLETED] {record_id} -> {eff_zernio_pub}")

        # Case C: Google Drive Single/Chunked Item
        elif mode == "gdrive_single":
            if session.get("uploaded_video_item"):
                gd_vid = session["uploaded_video_item"]
                media_items.append(gd_vid)
                preview_url = gd_vid["url"]
            elif (gdrive_file_name or session.get("gdrive_file_name")):
                eff_fname = (gdrive_file_name or session.get("gdrive_file_name") or "").strip()
                eff_fid = (gdrive_single_file_id or "").strip()
                signed_url = build_gdrive_file_url(eff_fid or eff_fname)
                gd_vid = {
                    "url": signed_url,
                    "public_id": eff_fid or eff_fname,
                    "gdrive_file_id": eff_fid,
                    "gdrive_file_name": eff_fname,
                    "storage": "google_drive",
                    "type": "video",
                    "is_thumb": False
                }
                media_items.append(gd_vid)
                preview_url = signed_url

        else:
            raw_buf = bytes(session.get("fallback_buffer") or b"")
            if raw_buf:
                res = cloudinary.uploader.upload(io.BytesIO(raw_buf), resource_type="video", folder="glennbot")
                media_items.append({"url": res["secure_url"], "public_id": res["public_id"], "type": "video", "storage": "cloudinary"})
                preview_url = res["secure_url"]

        # Upload optional thumbnail if provided (prefer Zernio Media Cloud or Google Drive)
        vault_thumb_id = str(session.get("vault_thumb_file_id") or "").strip()
        if thumb_bytes and thumb_filename:
            z_thumb = upload_bytes_to_zernio_presign(
                thumb_bytes,
                thumb_filename,
                media_type="image",
                is_thumb=True,
                platform=platform,
                account_id=pageId
            )
            if z_thumb:
                media_items.append(z_thumb)
                preview_url = z_thumb["url"]
            elif use_gdrive:
                gd_thumb = upload_media_to_gdrive(thumb_bytes, thumb_filename, media_type="image", is_thumb=True)
                media_items.append(gd_thumb)
                preview_url = gd_thumb["url"]
            else:
                try:
                    res_t = cloudinary.uploader.upload(io.BytesIO(thumb_bytes), resource_type="image", folder="glennbot", format="jpg")
                except Exception:
                    res_t = cloudinary.uploader.upload(io.BytesIO(thumb_bytes), resource_type="image", folder="glennbot")
                media_items.append({"url": res_t["secure_url"], "public_id": res_t["public_id"], "type": "image", "is_thumb": True, "storage": "cloudinary"})
                preview_url = res_t["secure_url"]
        elif vault_thumb_id:
            v_thumb = _transfer_vault_file_to_zernio_media_item(
                file_id=vault_thumb_id,
                platform=platform,
                account_id=pageId,
                is_thumb=True,
                record_id=record_id
            )
            if v_thumb:
                media_items.append(v_thumb)
                preview_url = v_thumb["url"]

    except Exception as e:
        err_msg = f"Failed to finalize cloud video upload: {e}"
        print(f"[❌ CHUNKED COMPLETE ERROR] {record_id}: {err_msg}")
        update_post_status(record_id, "failed", err_msg)
        return JSONResponse({"status": "error", "id": record_id, "message": err_msg}, status_code=500)

    # Check if user cancelled the post right before finish
    try:
        with db_engine.begin() as conn:
            row_exists = conn.execute(
                text("SELECT id FROM glennbot_scheduled_posts WHERE id = :id"),
                {"id": record_id}
            ).fetchone()
            if not row_exists:
                if media_items:
                    cleanup_cloudinary(media_items)
                return {"status": "cancelled", "id": record_id}

            conn.execute(
                text("""
                    UPDATE glennbot_scheduled_posts
                    SET media_preview_url = :preview,
                        status = 'waiting',
                        status_message = 'Waiting for schedule...'
                    WHERE id = :id
                """),
                {"id": record_id, "preview": preview_url}
            )
    except Exception as e:
        print(f"[⚠️ CHUNKED COMPLETE DB UPDATE ERROR]: {e}")

    # Pre-register future scheduled post on Zernio so Zernio locks the media (even >7 days out) and publishes on schedule
    register_scheduled_post_on_zernio(
        record_id=record_id,
        platform=platform,
        account_id=pageId,
        post_type=post_type,
        caption=caption,
        media_items=media_items,
        title=title,
        scheduled_time=scheduled_time
    )

    now_manila = datetime.now(manila_tz)
    effective_run_date = max(scheduled_time, now_manila + timedelta(seconds=3))

    if platform == "facebook":
        scheduler.add_job(post_to_facebook, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, post_type, caption, media_items], misfire_grace_time=3600)
    elif platform == "instagram":
        scheduler.add_job(post_to_instagram, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, post_type, caption, media_items], misfire_grace_time=3600)
    elif platform == "tiktok":
        scheduler.add_job(post_to_tiktok, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, caption, media_items], misfire_grace_time=3600)
    elif platform == "youtube":
        scheduler.add_job(post_to_youtube, 'date', id=record_id, run_date=effective_run_date, args=[record_id, pageId, post_type, caption, media_items, title], misfire_grace_time=3600)

    base_cleanup_time = max(effective_run_date, now_manila)
    cleanup_time = base_cleanup_time + timedelta(minutes=20)
    scheduler.add_job(cleanup_cloudinary, 'date', run_date=cleanup_time, args=[media_items], misfire_grace_time=3600)

    return {
        "status": "success",
        "id": record_id,
        "queue_status": "waiting",
        "media_preview_url": preview_url
    }


@router.post("/api/schedule/chunked/fail")
def schedule_chunked_fail(
    record_id: str = Form(...),
    error_message: str = Form("Upload interrupted before completion.")
):
    LAST_UPLOAD_HEARTBEAT_TS.pop(record_id, None)
    with CHUNKED_SCHEDULE_LOCK:
        CHUNKED_SCHEDULE_SESSIONS.pop(record_id, None)
    clean_err = (error_message or "Upload failed").strip()
    update_post_status(record_id, "failed", f"Upload Failed: {clean_err}")
    return {"status": "failed", "id": record_id, "message": clean_err}


@router.post("/api/schedule")
async def receive_schedule(
    platform: str = Form(...), post_type: str = Form(...), pageId: str = Form(""),
    accountName: str = Form(""),
    date_val: str = Form("", alias="date"), time_val: str = Form("", alias="time"), title: str = Form(""), caption: str = Form(""),
    thumbnail: Optional[UploadFile] = File(None), media: Optional[UploadFile] = File(None),
    media_files: Optional[List[UploadFile]] = File(None),
    vault_media_file_id: str = Form(""),
    vault_thumb_file_id: str = Form(""),
    vault_media_file_ids: str = Form("")
):
    manila_tz = pytz.timezone("Asia/Manila")
    now_manila = datetime.now(manila_tz)

    if date_val and time_val:
        scheduled_time = manila_tz.localize(datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M"))
    else:
        scheduled_time = now_manila + timedelta(seconds=10)

    record_id = f"post_{uuid.uuid4().hex[:12]}"
    LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
    ACTIVE_BACKGROUND_SCHEDULE_JOBS.add(record_id)

    display_caption = (
        f"{title.strip()}\n{caption.strip()}".strip()
        if (platform == "youtube" and title.strip() and caption.strip() and title.strip() != caption.strip())
        else (title.strip() or caption)
    )

    clean_vault_media_id = (vault_media_file_id or "").strip()
    clean_vault_thumb_id = (vault_thumb_file_id or "").strip()
    parsed_vault_media_ids: List[str] = []
    if (vault_media_file_ids or "").strip():
        try:
            raw_list = json.loads(vault_media_file_ids)
            if isinstance(raw_list, list):
                parsed_vault_media_ids = [str(x).strip() for x in raw_list if str(x).strip()]
        except Exception:
            parsed_vault_media_ids = [x.strip() for x in vault_media_file_ids.split(",") if x.strip()]

    initial_vault_preview_id = clean_vault_media_id or clean_vault_thumb_id or (parsed_vault_media_ids[0] if parsed_vault_media_ids else "")
    initial_preview_url = f"/api/files/{initial_vault_preview_id}/stream" if initial_vault_preview_id else ""
    initial_status_msg = (
        f"Processing Payload • Transferring Vault file ({clean_vault_media_id or (parsed_vault_media_ids[0] if parsed_vault_media_ids else 'vault')}) from Google Drive to Zernio..."
        if (clean_vault_media_id or parsed_vault_media_ids)
        else "Processing Payload • Uploading media & queueing..."
    )

    # Insert DB row FIRST in worker threadpool before reading large media bytes so event loop never blocks
    def _insert_initial_sched_row():
        try:
            with db_engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO glennbot_scheduled_posts 
                        (id, platform, page_id, account_name, post_type, caption, media_preview_url, scheduled_time, status, status_message)
                        VALUES (:id, :platform, :page_id, :account_name, :post_type, :caption, :preview, :sched_time, 'processing_payload', :status_msg)
                    """),
                    {
                        "id": record_id,
                        "platform": platform,
                        "page_id": pageId,
                        "account_name": accountName or platform.capitalize(),
                        "post_type": post_type,
                        "caption": display_caption,
                        "preview": initial_preview_url,
                        "sched_time": scheduled_time,
                        "status_msg": initial_status_msg
                    }
                )
        except Exception as e:
            print(f"[⚠️ DB INSERT ERROR]: {e}")

    await run_in_threadpool(_insert_initial_sched_row)

    media_bytes = None
    media_filename = ""
    thumb_bytes = None
    thumb_filename = ""
    image_buffers: List[Dict[str, Any]] = []

    try:
        if post_type in ['reels', 'video169']:
            if media and media.filename and not clean_vault_media_id:
                media_filename = media.filename
                media_bytes = await media.read()
            if thumbnail and thumbnail.filename and not clean_vault_thumb_id:
                thumb_filename = thumbnail.filename
                thumb_bytes = await thumbnail.read()
        elif post_type == 'image' and media_files:
            for img in media_files:
                if img and img.filename:
                    img_b = await img.read()
                    image_buffers.append({"filename": img.filename, "bytes": img_b})
    except Exception as e:
        err_msg = f"Failed to read uploaded media payload: {e}"
        ACTIVE_BACKGROUND_SCHEDULE_JOBS.discard(record_id)
        LAST_UPLOAD_HEARTBEAT_TS.pop(record_id, None)
        update_post_status(record_id, "failed", err_msg)
        return {"status": "error", "id": record_id, "message": err_msg}

    threading.Thread(
        target=_process_schedule_payload_background,
        args=(
            record_id,
            platform,
            post_type,
            pageId,
            accountName,
            title,
            caption,
            scheduled_time,
            media_bytes,
            media_filename,
            thumb_bytes,
            thumb_filename,
            image_buffers,
            clean_vault_media_id,
            clean_vault_thumb_id,
            parsed_vault_media_ids
        ),
        daemon=True
    ).start()

    return {
        "status": "success",
        "id": record_id,
        "queue_status": "processing_payload"
    }






# ==============================================================================
# --- CROSS-MODULE ROUTER NAMESPACE WIRING & RE-EXPORTS ---
# ==============================================================================
from routers import (
    comments_routes as _comments_routes,
    messages_routes as _messages_routes,
    sms_routes as _sms_routes,
    webhooks_routes as _webhooks_routes,
    comment_actions_routes as _comment_actions_routes,
    analytics_routes as _analytics_routes,
    email_accounts_routes as _email_accounts_routes,
    email_send_webhooks_routes as _email_send_webhooks_routes,
    contacts_routes as _contacts_routes,
    internal_api_routes as _internal_api_routes,
    settings_rbac_routes as _settings_rbac_routes,
    automations_routes as _automations_routes,
    files_routes as _files_routes,
    spreadsheet_routes as _spreadsheet_routes,
    calendar_sync_routes as _calendar_sync_routes,
    calendar_booking_routes as _calendar_booking_routes,
)

_ALL_ROUTER_SUBMODULES = [
    sys.modules[__name__],
    _comments_routes,
    _messages_routes,
    _sms_routes,
    _webhooks_routes,
    _comment_actions_routes,
    _analytics_routes,
    _email_accounts_routes,
    _email_send_webhooks_routes,
    _contacts_routes,
    _internal_api_routes,
    _settings_rbac_routes,
    _automations_routes,
    _files_routes,
    _spreadsheet_routes,
    _calendar_sync_routes,
    _calendar_booking_routes,
]

_SHARED_ROUTER_SYMBOLS = {}
for _mod in _ALL_ROUTER_SUBMODULES:
    for _k, _v in list(_mod.__dict__.items()):
        if not _k.startswith("__") and _k not in ("router", "_ALL_ROUTER_SUBMODULES", "_SHARED_ROUTER_SYMBOLS"):
            _SHARED_ROUTER_SYMBOLS[_k] = _v

for _mod in _ALL_ROUTER_SUBMODULES:
    for _k, _v in _SHARED_ROUTER_SYMBOLS.items():
        _mod.__dict__.setdefault(_k, _v)
