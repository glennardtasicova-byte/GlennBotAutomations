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
# --- STRICT POST-MATCHED COMMENTS & CLOUDINARY NOTIFICATION ENGINE ---
# ==============================================================================

def format_relative_time_label(dt: datetime, now_m: Optional[datetime] = None) -> str:
    manila_tz = pytz.timezone("Asia/Manila")
    now_ref = now_m or datetime.now(manila_tz)
    diff_sec = max(0.0, (now_ref - dt).total_seconds())
    mins = int(diff_sec // 60)
    hours = int(diff_sec // 3600)
    days = int(diff_sec // 86400)
    if mins < 1:
        return "Just now"
    if mins < 60:
        return f"{mins}m"
    if hours < 24:
        return f"{hours}h"
    if days <= 7:
        return f"{days}d"
    return dt.strftime("%b %d").replace(" 0", " ")

def extract_snowflake_timestamp(item_id: str) -> Optional[datetime]:
    s = str(item_id or "").strip()
    if "_" in s:
        s = s.split("_")[-1]
    if s.isdigit() and 18 <= len(s) <= 20:
        try:
            val = int(s)
            ts_sec = val >> 32
            now_sec = int(time.time())
            if 1700000000 <= ts_sec <= (now_sec + 86400):
                return datetime.fromtimestamp(ts_sec, tz=pytz.timezone("Asia/Manila"))
        except Exception:
            pass
    return None

def parse_meta_timestamp(ts_str: str, fallback_offset_seconds: int = 0, item_id: str = "") -> Dict[str, Any]:
    manila_tz = pytz.timezone("Asia/Manila")
    now_m = datetime.now(manila_tz)
    snowflake_dt = extract_snowflake_timestamp(item_id) if item_id else None

    if not ts_str:
        if snowflake_dt is not None:
            return {
                "iso": snowflake_dt.isoformat(),
                "display": snowflake_dt.strftime("%b %d, %Y • %I:%M %p"),
                "relative": format_relative_time_label(snowflake_dt, now_m),
                "dt": snowflake_dt,
                "is_fallback": False
            }
        dt_fallback = now_m - timedelta(seconds=max(0, int(fallback_offset_seconds)))
        return {
            "iso": dt_fallback.isoformat(),
            "display": dt_fallback.strftime("%b %d, %Y • %I:%M %p"),
            "relative": format_relative_time_label(dt_fallback, now_m),
            "dt": dt_fallback,
            "is_fallback": True
        }
    try:
        if isinstance(ts_str, (int, float)) or (isinstance(ts_str, str) and ts_str.isdigit()):
            val = float(ts_str)
            if val > 1e11:
                val = val / 1000.0
            dt = datetime.fromtimestamp(val, tz=manila_tz)
        else:
            cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(ts_str).replace("Z", "+00:00"))
            dt = datetime.fromisoformat(cleaned).astimezone(manila_tz)

        if snowflake_dt is not None and abs((now_m - dt).total_seconds()) < 300 and abs((dt - snowflake_dt).total_seconds()) > 60:
            dt = snowflake_dt

        return {
            "iso": dt.isoformat(),
            "display": dt.strftime("%b %d, %Y • %I:%M %p"),
            "relative": format_relative_time_label(dt, now_m),
            "dt": dt,
            "is_fallback": False
        }
    except Exception:
        if snowflake_dt is not None:
            return {
                "iso": snowflake_dt.isoformat(),
                "display": snowflake_dt.strftime("%b %d, %Y • %I:%M %p"),
                "relative": format_relative_time_label(snowflake_dt, now_m),
                "dt": snowflake_dt,
                "is_fallback": False
            }
        dt_fallback = now_m - timedelta(seconds=max(0, int(fallback_offset_seconds)))
        return {
            "iso": dt_fallback.isoformat(),
            "display": str(ts_str),
            "relative": "",
            "dt": dt_fallback,
            "is_fallback": True
        }

def is_comment_timestamp_valid_for_post(comment_iso: str, post_scheduled_dt: Optional[Any], is_external_post: bool = False) -> bool:
    if not comment_iso:
        return True
    try:
        manila_tz = pytz.timezone("Asia/Manila")
        cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(comment_iso).replace("Z", "+00:00"))
        c_dt = datetime.fromisoformat(cleaned).astimezone(manila_tz)
        if c_dt.year < 2024:
            return False
        if not is_external_post and post_scheduled_dt:
            p_dt = _coerce_db_datetime(post_scheduled_dt, manila_tz) if "_coerce_db_datetime" in globals() else (
                post_scheduled_dt.astimezone(manila_tz) if hasattr(post_scheduled_dt, "astimezone") else None
            )
            if p_dt and c_dt < (p_dt - timedelta(hours=12)):
                return False
        return True
    except Exception:
        return True


def get_zernio_posts_map(force: bool = False) -> Dict[str, Dict[str, Any]]:
    now_ts = time.time()
    if not force and ZERNIO_POSTS_CACHE["posts_map"] and (now_ts - ZERNIO_POSTS_CACHE["last_fetched"] < 15):
        return ZERNIO_POSTS_CACHE["posts_map"]
    all_keys = get_all_zernio_keys()
    if not all_keys:
        return {}
    pmap = {}
    merged_list = []

    def _fetch_posts_for_key(k: str):
        try:
            res = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/posts", headers=get_zernio_headers(k), timeout=20)
            if res.status_code == 200:
                return k, extract_list_from_api_payload(res.json()) or []
        except Exception:
            pass
        return k, []

    with ThreadPoolExecutor(max_workers=max(1, len(all_keys))) as ex:
        futures = [ex.submit(_fetch_posts_for_key, k) for k in all_keys]
        for fut in as_completed(futures):
            k, posts_list = fut.result()
            for p in posts_list:
                if not isinstance(p, dict):
                    continue
                p_copy = dict(p)
                p_copy["_zernio_api_key"] = k
                merged_list.append(p_copy)
                pid = str(p.get("_id") or p.get("id") or "")
                if pid:
                    pmap[pid] = p_copy
                plat_pid = str(p.get("platformPostId") or "")
                if plat_pid:
                    pmap[plat_pid] = p_copy
                for pl in (p.get("platforms") or []):
                    if isinstance(pl, dict):
                        sub_pid = str(pl.get("platformPostId") or "")
                        if sub_pid:
                            pmap[sub_pid] = p_copy

    if pmap or not ZERNIO_POSTS_CACHE["posts_map"]:
        ZERNIO_POSTS_CACHE["posts_map"] = pmap
        ZERNIO_POSTS_CACHE["posts_list"] = merged_list
        ZERNIO_POSTS_CACHE["last_fetched"] = now_ts
    return ZERNIO_POSTS_CACHE["posts_map"]


def get_zernio_commented_posts_list(force: bool = False) -> List[Dict[str, Any]]:
    now_ts = time.time()
    if not force and ZERNIO_COMMENTED_POSTS_CACHE["items"] and (now_ts - ZERNIO_COMMENTED_POSTS_CACHE["last_fetched"] < 15):
        return ZERNIO_COMMENTED_POSTS_CACHE["items"]
    all_keys = get_all_zernio_keys()
    if not all_keys:
        return []
    merged_items = []

    def _fetch_inbox_for_key(k: str):
        try:
            res = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/inbox/comments", headers=get_zernio_headers(k), timeout=20)
            if res.status_code == 200:
                return k, extract_list_from_api_payload(res.json()) or []
        except Exception:
            pass
        return k, []

    with ThreadPoolExecutor(max_workers=max(1, len(all_keys))) as ex:
        futures = [ex.submit(_fetch_inbox_for_key, k) for k in all_keys]
        for fut in as_completed(futures):
            k, items = fut.result()
            for it in items:
                if isinstance(it, dict):
                    it_copy = dict(it)
                    it_copy["_zernio_api_key"] = k
                    merged_items.append(it_copy)

    if merged_items or not ZERNIO_COMMENTED_POSTS_CACHE["items"]:
        ZERNIO_COMMENTED_POSTS_CACHE["items"] = merged_items
        ZERNIO_COMMENTED_POSTS_CACHE["last_fetched"] = now_ts
    return ZERNIO_COMMENTED_POSTS_CACHE["items"]


def resolve_zernio_post_identifiers(r_dict: Dict[str, Any], force: bool = False, claimed_ids: Optional[set] = None) -> Dict[str, str]:
    platform = (r_dict.get("platform") or "").strip().lower()
    page_id = str(r_dict.get("page_id") or "").strip()
    account_name = (r_dict.get("account_name") or "").strip()
    caption = _strip_invisible_guard_chars(r_dict.get("caption") or "").lower()
    ext_id = extract_external_post_id(r_dict)
    status_msg = (r_dict.get("status_message") or "").strip()
    permalink = (r_dict.get("permalink_url") or "").strip()

    z_acc_id = resolve_zernio_account_id(platform, page_id, account_name)
    valid_page_ids = _collect_valid_account_ids_for_page(platform, page_id, account_name, z_acc_id)
    expected_page_key = get_zernio_key_for_account(z_acc_id or page_id, account_name=account_name, platform=platform)
    z_post_id = ""
    plat_post_id = ""
    inbox_post_id = ""
    inbox_plat_id = ""
    matched_api_key = ""

    m_z = re.search(r"(?:External API ID|Zernio ID):\s*([^\s,|]+)", status_msg)
    if m_z:
        z_post_id = m_z.group(1).strip()

    m_plat = re.search(r"Platform ID:\s*([^\s,|]+)", status_msg)
    if m_plat:
        plat_post_id = m_plat.group(1).strip()

    if permalink and not plat_post_id:
        m_link = re.search(r"(?:/videos/|/reel/|/posts/|/video/|story_fbid=|fbid=)(\d+)", permalink)
        if m_link:
            plat_post_id = m_link.group(1).strip()
        else:
            m_yt_link = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", permalink)
            if m_yt_link:
                plat_post_id = m_yt_link.group(1).strip()

    z_map = get_zernio_posts_map(force=force)
    matched_z_post = None

    for lookup_id in (ext_id, z_post_id, plat_post_id):
        if lookup_id and lookup_id in z_map:
            matched_z_post = z_map[lookup_id]
            break

    if matched_z_post:
        if matched_z_post.get("_zernio_api_key"):
            matched_api_key = str(matched_z_post["_zernio_api_key"])
        z_post_id = str(matched_z_post.get("_id") or matched_z_post.get("id") or z_post_id)
        cand_top_pid = str(matched_z_post.get("platformPostId") or matched_z_post.get("videoId") or matched_z_post.get("externalPostId") or "").strip()
        if not plat_post_id and cand_top_pid:
            plat_post_id = cand_top_pid
        cand_top_url = str(matched_z_post.get("platformPostUrl") or matched_z_post.get("permalink") or matched_z_post.get("url") or matched_z_post.get("videoUrl") or "").strip()
        if not permalink and cand_top_url:
            permalink = cand_top_url

        plat_entries = [pl for pl in (matched_z_post.get("platforms") or []) if isinstance(pl, dict)]
        for pl in plat_entries:
            pl_plat = (pl.get("platform") or "").strip().lower()
            if pl_plat and pl_plat != platform:
                continue
            pl_acc = pl.get("accountId")
            if isinstance(pl_acc, dict):
                pl_acc = pl_acc.get("_id") or pl_acc.get("id")
            pl_acc_str = str(pl_acc or "").strip()
            if pl_acc_str and valid_page_ids and len(plat_entries) > 1 and pl_acc_str not in valid_page_ids:
                continue
            if pl_acc_str and (not valid_page_ids or pl_acc_str in valid_page_ids):
                z_acc_id = pl_acc_str
            cand_pl_pid = str(pl.get("platformPostId") or pl.get("videoId") or pl.get("externalPostId") or "").strip()
            if not plat_post_id and cand_pl_pid:
                plat_post_id = cand_pl_pid
            cand_pl_url = str(pl.get("platformPostUrl") or pl.get("permalink") or pl.get("url") or pl.get("videoUrl") or "").strip()
            if not permalink and cand_pl_url:
                permalink = cand_pl_url

    if platform == "youtube":
        if permalink and not plat_post_id:
            m_yt_p = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", permalink)
            if m_yt_p:
                plat_post_id = m_yt_p.group(1).strip()
        if not plat_post_id and "discover_youtube_video_id_direct" in globals():
            yt_disc = discover_youtube_video_id_direct(r_dict)
            if yt_disc:
                plat_post_id = yt_disc
        if plat_post_id and re.match(r"^[A-Za-z0-9_-]{11}$", plat_post_id) and not permalink:
            permalink = f"https://www.youtube.com/watch?v={plat_post_id}"

    known_ids = {i for i in (ext_id, z_post_id, plat_post_id) if i and i != "OK"}
    for kid in list(known_ids):
        if "_" in kid:
            known_ids.add(kid.split("_")[-1])

    for cp in get_zernio_commented_posts_list(force=force):
        if not isinstance(cp, dict):
            continue
        cp_plat = (cp.get("platform") or "").strip().lower()
        if cp_plat and cp_plat != platform:
            continue
        cp_id = str(cp.get("id") or cp.get("_id") or cp.get("postId") or "")
        cp_plat_id = str(cp.get("platformPostId") or cp.get("videoId") or "")
        cp_content = _strip_invisible_guard_chars(cp.get("content") or cp.get("caption") or cp.get("message") or cp.get("text") or "").lower()
        cp_acc = cp.get("accountId")
        if isinstance(cp_acc, dict):
            cp_acc = cp_acc.get("_id") or cp_acc.get("id")
        cp_acc_str = str(cp_acc or "").strip()
        cp_key_str = str(cp.get("_zernio_api_key") or "").strip()

        cp_ids = {i for i in (cp_id, cp_plat_id) if i}
        if cp_plat_id and "_" in cp_plat_id:
            cp_ids.add(cp_plat_id.split("_")[-1])

        if claimed_ids and bool(cp_ids & claimed_ids):
            continue

        id_matched = bool(known_ids & cp_ids)
        has_conflicting_zernio_id = bool(
            z_post_id and cp_id and len(z_post_id) == 24 and len(cp_id) == 24 and z_post_id != cp_id
        )

        cp_belongs_to_page = bool(
            (cp_acc_str and cp_acc_str in valid_page_ids)
            or (not cp_acc_str and expected_page_key and cp_key_str == expected_page_key)
        )

        caption_matched = bool(
            not id_matched
            and not has_conflicting_zernio_id
            and not plat_post_id
            and caption
            and cp_content
            and (cp_content == caption or cp_content.splitlines()[0].strip() == caption.splitlines()[0].strip())
            and cp_belongs_to_page
        )

        if id_matched or caption_matched:
            if cp_key_str and (not matched_api_key) and (not valid_page_ids or not cp_acc_str or cp_acc_str in valid_page_ids):
                matched_api_key = cp_key_str
            if cp_id:
                inbox_post_id = cp_id
            if cp_plat_id:
                inbox_plat_id = cp_plat_id
                if not plat_post_id:
                    plat_post_id = cp_plat_id
            if cp_acc_str and (not valid_page_ids or cp_acc_str in valid_page_ids):
                z_acc_id = cp_acc_str
            if not permalink and (cp.get("platformPostUrl") or cp.get("permalink")):
                permalink = str(cp.get("platformPostUrl") or cp.get("permalink"))
            if claimed_ids is not None:
                claimed_ids.update(cp_ids)
            break

    if not z_post_id and ext_id and ext_id != "OK":
        z_post_id = ext_id

    if not matched_api_key:
        matched_api_key = expected_page_key or get_zernio_key_for_account(z_acc_id or page_id, account_name=account_name, platform=platform)

    return {
        "inbox_post_id": inbox_post_id,
        "inbox_plat_id": inbox_plat_id,
        "zernio_post_id": z_post_id,
        "platform_post_id": plat_post_id,
        "zernio_account_id": z_acc_id or page_id,
        "zernio_api_key": matched_api_key,
        "permalink_url": permalink
    }


def _parse_single_zernio_reply(rep: Dict[str, Any], clean_user: str, account_name: str, parent_comment_id: str = "", replied_to_id: str = "") -> Dict[str, Any]:
    r_id = str(rep.get("ID") or rep.get("id") or rep.get("commentId") or rep.get("_id") or rep.get("platform_id") or "")
    r_auth = rep.get("Author") or rep.get("author") or rep.get("from") or rep.get("user") or {}
    if not isinstance(r_auth, dict):
        r_auth = {}
    r_aid = str(r_auth.get("ID") or r_auth.get("id") or rep.get("author_id") or rep.get("authorId") or "").strip()
    r_handle = (
        rep.get("author_username")
        or rep.get("username")
        or r_auth.get("Username")
        or r_auth.get("username")
        or r_auth.get("unique_id")
        or ""
    ).strip().lstrip("@")
    r_nick = (
        rep.get("author_name")
        or r_auth.get("Name")
        or r_auth.get("name")
        or r_auth.get("displayName")
        or r_auth.get("nickname")
        or ""
    ).strip()
    r_is_own = bool(
        rep.get("IsOwner")
        or rep.get("isOwner")
        or rep.get("is_owner")
        or rep.get("isOwnAccount")
        or rep.get("fromOwner")
        or r_auth.get("IsOwner")
        or r_auth.get("isOwner")
        or r_auth.get("is_owner")
        or r_auth.get("isOwnAccount")
        or (clean_user and r_handle and r_handle.lower() == clean_user.lower())
        or (account_name and r_nick and r_nick.lower() == account_name.strip().lstrip("@").lower())
    )
    r_avatar = (
        rep.get("author_picture")
        or r_auth.get("Picture")
        or r_auth.get("picture")
        or r_auth.get("avatarUrl")
        or r_auth.get("profilePictureUrl")
        or r_auth.get("avatar")
        or ""
    )
    r_name = (
        f"{r_nick} (@{r_handle})"
        if (r_nick and r_handle and r_nick.lower() != r_handle.lower())
        else (r_nick or (f"@{r_handle}" if r_handle else (account_name if r_is_own else "User")))
    )
    if r_name == "User" and r_aid:
        known = lookup_known_author_identity(r_aid)
        if known and known.get("name"):
            r_name = known["name"]
            if not r_avatar and known.get("avatar"):
                r_avatar = known["avatar"]
    elif r_name not in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User") and r_aid and not r_is_own:
        remember_author_identity(r_aid, r_name, f"@{r_handle}" if r_handle else "", r_avatar)

    r_ts = parse_meta_timestamp(
        rep.get("CreatedAt") or rep.get("createdAt") or rep.get("created_at") or rep.get("timestamp") or rep.get("createdTime") or "",
        item_id=r_id
    )
    direct_replied_to = str(
        replied_to_id
        or rep.get("parentCommentId")
        or rep.get("parentId")
        or rep.get("parent_id")
        or rep.get("inReplyToId")
        or (rep.get("parent") or {}).get("id")
        or parent_comment_id
        or ""
    ).strip()
    return {
        "id": r_id,
        "parent_comment_id": str(parent_comment_id or ""),
        "replied_to_id": direct_replied_to,
        "author_id": r_aid,
        "author_name": r_name,
        "author_avatar": r_avatar,
        "is_own": r_is_own,
        "can_reply": True,
        "is_liked": bool(rep.get("isLiked") or rep.get("is_liked") or rep.get("liked") or rep.get("user_likes")),
        "is_hidden": bool(rep.get("isHidden") or rep.get("is_hidden") or rep.get("hidden")),
        "message": rep.get("Text") or rep.get("text") or rep.get("message") or rep.get("content") or "",
        "created_iso": r_ts["iso"],
        "display_time": r_ts["display"]
    }



YOUTUBE_LIVE_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}
YOUTUBE_DISCOVERED_VIDEO_ID_CACHE: Dict[str, str] = {}
YOUTUBE_CHANNEL_ID_CACHE: Dict[str, str] = {}
YOUTUBE_CHANNEL_RECENT_VIDEOS_CACHE: Dict[str, Dict[str, Any]] = {}

def _parse_youtube_relative_time(rel_str: str, existing_iso: str = "", existing_display: str = "") -> Dict[str, str]:
    manila_tz = pytz.timezone("Asia/Manila")
    now_m = datetime.now(manila_tz)
    if existing_iso and existing_display:
        return {"iso": existing_iso, "display": existing_display}
    raw = (rel_str or "").strip().lower()
    delta = timedelta(seconds=0)
    m_rel = re.search(r"(\d+)\s*(second|sec|minute|min|hour|hr|day|week|month|year)", raw)
    if m_rel:
        val = int(m_rel.group(1))
        unit = m_rel.group(2)
        if unit.startswith("sec"):
            delta = timedelta(seconds=val)
        elif unit.startswith("min"):
            delta = timedelta(minutes=val)
        elif unit.startswith("hour") or unit.startswith("hr"):
            delta = timedelta(hours=val)
        elif unit.startswith("day"):
            delta = timedelta(days=val)
        elif unit.startswith("week"):
            delta = timedelta(weeks=val)
        elif unit.startswith("month"):
            delta = timedelta(days=val * 30)
        elif unit.startswith("year"):
            delta = timedelta(days=val * 365)
    dt = now_m - delta
    return {
        "iso": dt.isoformat(),
        "display": dt.strftime("%b %d, %Y • %I:%M %p")
    }

def _collect_yt_comment_entities(node: Any, out_map: Dict[str, Dict[str, Any]]):
    if isinstance(node, dict):
        cep = node.get("commentEntityPayload")
        if isinstance(cep, dict):
            props = cep.get("properties") or {}
            cid = str(props.get("commentId") or "").strip()
            if cid:
                out_map[cid] = cep
        for v in node.values():
            _collect_yt_comment_entities(v, out_map)
    elif isinstance(node, list):
        for item in node:
            _collect_yt_comment_entities(item, out_map)

def _collect_yt_thread_reply_tokens(node: Any, reply_tokens: List[str]):
    if isinstance(node, dict):
        ctr = node.get("commentThreadRenderer")
        if isinstance(ctr, dict):
            replies_sec = ctr.get("replies")
            if isinstance(replies_sec, dict):
                toks = re.findall(r'"continuationCommand":\s*\{\s*"token":\s*"([^"]+)"', json.dumps(replies_sec))
                for tk in toks:
                    if tk and tk not in reply_tokens:
                        reply_tokens.append(tk)
        for v in node.values():
            _collect_yt_thread_reply_tokens(v, reply_tokens)
    elif isinstance(node, list):
        for item in node:
            _collect_yt_thread_reply_tokens(item, reply_tokens)


def resolve_youtube_channel_uc_id(page_id: str = "", acc_name: str = "", username: str = "") -> str:
    pid = str(page_id or "").strip()
    aname = (acc_name or "").strip()
    uname = (username or "").strip().lstrip("@")
    cache_key = pid or aname or uname
    if pid.startswith("UC") and len(pid) >= 20:
        return pid
    if cache_key and cache_key in YOUTUBE_CHANNEL_ID_CACHE:
        return YOUTUBE_CHANNEL_ID_CACHE[cache_key]

    # 1. Check live Zernio connected YouTube accounts for platformAccountId / channelId / username
    try:
        for za in fetch_zernio_connected_accounts(platform="youtube", force=False):
            if not isinstance(za, dict):
                continue
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("channelId") or za.get("externalId") or "").strip()
            za_uname = str(za.get("username") or "").strip().lstrip("@")
            za_dname = str(za.get("displayName") or za.get("name") or "").strip()
            if (pid and pid in (za_id, za_plat_id)) or (aname and aname.lower() in (za_dname.lower(), za_uname.lower())) or (uname and uname.lower() == za_uname.lower()):
                if za_plat_id.startswith("UC"):
                    if cache_key:
                        YOUTUBE_CHANNEL_ID_CACHE[cache_key] = za_plat_id
                    return za_plat_id
                if not uname and za_uname:
                    uname = za_uname
                if not aname and za_dname:
                    aname = za_dname
    except Exception:
        pass

    # 2. Check connected accounts cache for username
    if not uname:
        try:
            for acc in refresh_connected_accounts_cache(force=False):
                if (acc.get("platform") or "").strip().lower() == "youtube":
                    if str(acc.get("account_id") or "") == pid or (aname and (acc.get("account_name") or "").strip().lower() == aname.lower()):
                        cand_u = (acc.get("username") or "").strip().lstrip("@")
                        if cand_u.startswith("UC") and len(cand_u) >= 20:
                            YOUTUBE_CHANNEL_ID_CACHE[cache_key] = cand_u
                            return cand_u
                        if cand_u:
                            uname = cand_u
                        break
        except Exception:
            pass

    yt_ctx = {"client": {"clientName": "WEB", "clientVersion": "2.20250301.00.00", "hl": "en", "gl": "PH"}}
    yt_headers = {"User-Agent": "Mozilla/5.0"}

    for q_cand in ([f"@{uname}" if uname else "", aname]):
        q_clean = q_cand.strip()
        if not q_clean:
            continue
        try:
            ch_resp = HTTP_SESSION.post(
                "https://www.youtube.com/youtubei/v1/search?prettyPrint=false",
                json={"context": yt_ctx, "query": q_clean},
                headers=yt_headers,
                timeout=5
            )
            if ch_resp.status_code == 200 and ch_resp.text:
                m_uc = re.search(r'"channelId":"(UC[A-Za-z0-9_-]{20,})"', ch_resp.text)
                if m_uc:
                    uc_id = m_uc.group(1)
                    if cache_key:
                        YOUTUBE_CHANNEL_ID_CACHE[cache_key] = uc_id
                    return uc_id
        except Exception:
            pass
    return ""


def fetch_youtube_channel_recent_videos(page_id: str = "", acc_name: str = "", username: str = "", max_items: int = 12) -> List[Dict[str, str]]:
    uc_id = resolve_youtube_channel_uc_id(page_id=page_id, acc_name=acc_name, username=username)
    if not uc_id:
        return []
    now_ts = time.time()
    cached = YOUTUBE_CHANNEL_RECENT_VIDEOS_CACHE.get(uc_id)
    if cached and (now_ts - float(cached.get("ts") or 0.0)) < 15.0:
        return list(cached.get("videos") or [])[:max_items]

    yt_ctx = {"client": {"clientName": "WEB", "clientVersion": "2.20250301.00.00", "hl": "en", "gl": "PH"}}
    yt_headers = {"User-Agent": "Mozilla/5.0"}
    discovered: List[Dict[str, str]] = []
    seen_vids: set = set()

    def _extract_title_str(title_obj: Any) -> str:
        if isinstance(title_obj, str):
            return title_obj.strip()
        if isinstance(title_obj, dict):
            if isinstance(title_obj.get("simpleText"), str):
                return title_obj["simpleText"].strip()
            if isinstance(title_obj.get("content"), str):
                return title_obj["content"].strip()
            runs = title_obj.get("runs")
            if isinstance(runs, list):
                return "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict)).strip()
        return ""

    def _scan_channel_nodes(n: Any, is_shorts_tab: bool = False):
        if isinstance(n, dict):
            vr = n.get("videoRenderer") or n.get("reelItemRenderer") or n.get("gridVideoRenderer")
            if isinstance(vr, dict) and vr.get("videoId"):
                vid = str(vr["videoId"]).strip()
                if re.match(r"^[A-Za-z0-9_-]{11}$", vid) and vid not in seen_vids:
                    seen_vids.add(vid)
                    t_str = _extract_title_str(vr.get("title") or vr.get("headline"))
                    discovered.append({
                        "video_id": vid,
                        "title": t_str or "YouTube Video",
                        "permalink": f"https://www.youtube.com/shorts/{vid}" if is_shorts_tab else f"https://www.youtube.com/watch?v={vid}",
                        "preview_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    })
            slvm = n.get("shortsLockupViewModel")
            if isinstance(slvm, dict):
                s_dump = json.dumps(slvm)
                m_sv = re.search(r'"videoId":\s*"([A-Za-z0-9_-]{11})"', s_dump)
                if m_sv:
                    vid = m_sv.group(1)
                    if vid not in seen_vids:
                        seen_vids.add(vid)
                        m_txt = re.search(r'"text":\s*"([^"]+)"', s_dump)
                        t_str = m_txt.group(1).strip() if m_txt else "YouTube Short"
                        discovered.append({
                            "video_id": vid,
                            "title": t_str,
                            "permalink": f"https://www.youtube.com/shorts/{vid}",
                            "preview_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                        })
            for v_child in n.values():
                _scan_channel_nodes(v_child, is_shorts_tab=is_shorts_tab)
        elif isinstance(n, list):
            for it in n:
                _scan_channel_nodes(it, is_shorts_tab=is_shorts_tab)

    for tab_idx, tab_params in enumerate(("EgZzaG9ydHPyBgUKA5oBAA%3D%3D", "EgZ2aWRlb3PyBgQKAjoA")):
        try:
            b_resp = HTTP_SESSION.post(
                "https://www.youtube.com/youtubei/v1/browse?prettyPrint=false",
                json={"context": yt_ctx, "browseId": uc_id, "params": tab_params},
                headers=yt_headers,
                timeout=5
            )
            if b_resp.status_code == 200 and b_resp.text:
                _scan_channel_nodes(b_resp.json(), is_shorts_tab=(tab_idx == 0))
        except Exception:
            pass

    if discovered:
        YOUTUBE_CHANNEL_RECENT_VIDEOS_CACHE[uc_id] = {"ts": now_ts, "videos": discovered}
    return discovered[:max_items]


def discover_youtube_video_id_direct(r_dict: Dict[str, Any]) -> str:
    rec_id = str(r_dict.get("id") or "")
    if rec_id and rec_id in YOUTUBE_DISCOVERED_VIDEO_ID_CACHE:
        return YOUTUBE_DISCOVERED_VIDEO_ID_CACHE[rec_id]
    for src in (r_dict.get("permalink_url"), r_dict.get("external_post_id"), r_dict.get("status_message")):
        s_val = str(src or "").strip()
        if not s_val:
            continue
        m_v = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/|Platform ID:\s*)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", s_val)
        if m_v:
            vid = m_v.group(1).strip()
            if rec_id:
                YOUTUBE_DISCOVERED_VIDEO_ID_CACHE[rec_id] = vid
            return vid
        if re.match(r"^[A-Za-z0-9_-]{11}$", s_val):
            if rec_id:
                YOUTUBE_DISCOVERED_VIDEO_ID_CACHE[rec_id] = s_val
            return s_val

    raw_cap = _strip_invisible_guard_chars(r_dict.get("caption") or "")
    lines_clean = [ln.strip() for ln in raw_cap.splitlines() if ln.strip()]
    first_line = lines_clean[0] if lines_clean else ""
    acc_name = (r_dict.get("account_name") or "").strip()
    page_id = str(r_dict.get("page_id") or "").strip()
    if not first_line:
        return ""

    first_line_low = first_line.lower()
    # 1. Check connected YouTube channel's recent Shorts & Videos first
    channel_videos = fetch_youtube_channel_recent_videos(page_id=page_id, acc_name=acc_name, max_items=20)
    for cv in channel_videos:
        cv_title_low = _strip_invisible_guard_chars(cv.get("title") or "").lower()
        if cv_title_low and (first_line_low in cv_title_low or cv_title_low in first_line_low):
            vid = cv["video_id"]
            if rec_id:
                YOUTUBE_DISCOVERED_VIDEO_ID_CACHE[rec_id] = vid
            return vid

    # 2. Fallback to YouTube search by title + channel name
    yt_ctx = {"client": {"clientName": "WEB", "clientVersion": "2.20250301.00.00", "hl": "en", "gl": "PH"}}
    yt_headers = {"User-Agent": "Mozilla/5.0"}
    found_vids: List[str] = []

    def _scan_yt_items(n: Any):
        if isinstance(n, dict):
            vr = n.get("videoRenderer") or n.get("reelItemRenderer")
            if isinstance(vr, dict) and vr.get("videoId"):
                v_id_cand = str(vr["videoId"]).strip()
                v_title = _strip_invisible_guard_chars(json.dumps(vr.get("title") or vr.get("headline") or {})).lower()
                if first_line_low in v_title and re.match(r"^[A-Za-z0-9_-]{11}$", v_id_cand):
                    found_vids.append(v_id_cand)
            slvm = n.get("shortsLockupViewModel")
            if isinstance(slvm, dict):
                s_dump = _strip_invisible_guard_chars(json.dumps(slvm))
                if first_line_low in s_dump.lower():
                    m_sv = re.search(r'"videoId":\s*"([A-Za-z0-9_-]{11})"', s_dump)
                    if m_sv:
                        found_vids.append(m_sv.group(1))
            for v_child in n.values():
                _scan_yt_items(v_child)
        elif isinstance(n, list):
            for it in n:
                _scan_yt_items(it)

    try:
        q_str = f"{first_line} {acc_name}".strip()
        s_resp = HTTP_SESSION.post(
            "https://www.youtube.com/youtubei/v1/search?prettyPrint=false",
            json={"context": yt_ctx, "query": q_str},
            headers=yt_headers,
            timeout=5
        )
        if s_resp.status_code == 200 and s_resp.text:
            _scan_yt_items(s_resp.json())
            if found_vids:
                if rec_id:
                    YOUTUBE_DISCOVERED_VIDEO_ID_CACHE[rec_id] = found_vids[0]
                return found_vids[0]
    except Exception:
        pass
    return ""

def fetch_youtube_live_comments_direct(
    candidate_post_ids: List[str],
    account_id: str,
    r_dict: Dict[str, Any],
    seen_ids: set,
    deleted_comment_ids: set,
    preferred_api_key: str = ""
) -> Optional[List[Dict[str, Any]]]:
    video_id = ""
    for cid_cand in candidate_post_ids:
        c_str = str(cid_cand or "").strip()
        if re.match(r"^[A-Za-z0-9_-]{11}$", c_str):
            video_id = c_str
            break
        m_cand = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})", c_str)
        if m_cand:
            video_id = m_cand.group(1).strip()
            break
    if not video_id:
        video_id = discover_youtube_video_id_direct(r_dict)
    if not video_id:
        return None

    zernio_post_id = next((str(x).strip() for x in candidate_post_ids if x and len(str(x).strip()) == 24), "") or video_id
    record_id = str(r_dict.get("id") or "")
    page_id = str(r_dict.get("page_id") or "")
    account_name = r_dict.get("account_name") or "YouTube"
    post_type = r_dict.get("post_type") or "video"
    post_caption = r_dict.get("caption") or ""
    post_permalink = r_dict.get("permalink_url") or f"https://www.youtube.com/watch?v={video_id}"
    if not r_dict.get("permalink_url"):
        r_dict["permalink_url"] = post_permalink

    yt_ctx = {"client": {"clientName": "WEB", "clientVersion": "2.20250301.00.00", "hl": "en", "gl": "PH"}}
    yt_headers = {"User-Agent": "Mozilla/5.0"}
    now_ts = time.time()

    cached_tok_info = YOUTUBE_LIVE_TOKEN_CACHE.get(video_id)
    newest_token = ""
    if cached_tok_info and (now_ts - cached_tok_info.get("ts", 0)) < 5:
        newest_token = str(cached_tok_info.get("token") or "")

    try:
        if not newest_token:
            init_resp = HTTP_SESSION.post(
                "https://www.youtube.com/youtubei/v1/next?prettyPrint=false",
                json={"context": yt_ctx, "videoId": video_id},
                headers=yt_headers,
                timeout=6
            )
            if init_resp.status_code != 200 or not init_resp.text:
                return None
            m_sub = re.search(r'"subMenuItems":\[(.*?)\]', init_resp.text)
            if m_sub:
                sub_toks = re.findall(r'"token":"([^"]+)"', m_sub.group(1))
                if len(sub_toks) >= 2:
                    newest_token = sub_toks[1]
                elif sub_toks:
                    newest_token = sub_toks[0]
            if not newest_token:
                all_toks = re.findall(r'"continuationCommand":\{"token":"([^"]+)"\}', init_resp.text)
                if all_toks:
                    newest_token = all_toks[0]
            if not newest_token:
                YOUTUBE_LIVE_TOKEN_CACHE.pop(video_id, None)
                return []
            YOUTUBE_LIVE_TOKEN_CACHE[video_id] = {"token": newest_token, "ts": now_ts}

        c_resp = HTTP_SESSION.post(
            "https://www.youtube.com/youtubei/v1/next?prettyPrint=false",
            json={"context": yt_ctx, "continuation": newest_token},
            headers=yt_headers,
            timeout=6
        )
        if c_resp.status_code != 200 or not c_resp.text:
            YOUTUBE_LIVE_TOKEN_CACHE.pop(video_id, None)
            return None

        c_data = c_resp.json()
        entities_map: Dict[str, Dict[str, Any]] = {}
        reply_tokens: List[str] = []
        _collect_yt_comment_entities(c_data, entities_map)
        _collect_yt_thread_reply_tokens(c_data, reply_tokens)

        for r_tok in reply_tokens[:6]:
            try:
                r_resp = HTTP_SESSION.post(
                    "https://www.youtube.com/youtubei/v1/next?prettyPrint=false",
                    json={"context": yt_ctx, "continuation": r_tok},
                    headers=yt_headers,
                    timeout=5
                )
                if r_resp.status_code == 200 and r_resp.text:
                    _collect_yt_comment_entities(r_resp.json(), entities_map)
            except Exception:
                pass

        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        existing_c_map = ((posts_store.get(record_id) or {}).get("comments") or {}) if record_id else {}

        replies_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        for cid_k, cep in entities_map.items():
            if "." not in cid_k:
                continue
            parent_cid = cid_k.split(".")[0]
            r_props = cep.get("properties") or {}
            r_auth = cep.get("author") or {}
            r_msg = str((r_props.get("content") or {}).get("content") or "").strip()
            r_rel_time = str(r_props.get("publishedTime") or "").strip()
            r_aid = str(r_auth.get("channelId") or "").strip()
            r_disp = str(r_auth.get("displayName") or "").strip()
            r_handle = r_disp.lstrip("@")
            r_avatar = str(r_auth.get("avatarThumbnailUrl") or "").strip()
            r_is_creator = bool(r_auth.get("isCreator"))
            r_is_buffered = bool(
                r_msg
                and any(
                    (b_rep.get("message") or "").strip().lower() == r_msg.lower()
                    for b_list in RECENT_OWN_REPLIES_BUFFER.values()
                    for b_rep in b_list
                )
            )
            r_is_own = bool(r_is_creator or r_is_buffered)

            prev_parent = existing_c_map.get(parent_cid) or {}
            prev_rep = next((pr for pr in (prev_parent.get("replies") or []) if str(pr.get("id")) == cid_k), {})
            r_ts = _parse_youtube_relative_time(
                r_rel_time,
                existing_iso=str(prev_rep.get("created_iso") or ""),
                existing_display=str(prev_rep.get("display_time") or "")
            )
            r_name = (account_name if r_is_own else (r_disp or (f"@{r_handle}" if r_handle else "YouTube User")))
            if r_aid and not r_is_own and r_name != "YouTube User":
                remember_author_identity(r_aid, r_name, f"@{r_handle}" if r_handle else "", r_avatar)

            replies_by_parent.setdefault(parent_cid, []).append({
                "id": cid_k,
                "parent_comment_id": parent_cid,
                "author_id": r_aid,
                "author_name": r_name,
                "author_avatar": r_avatar,
                "is_own": r_is_own,
                "can_reply": True,
                "message": r_msg,
                "created_iso": r_ts["iso"],
                "display_time": r_ts["display"]
            })

        parsed_comments: List[Dict[str, Any]] = []
        for cid_k, cep in entities_map.items():
            if "." in cid_k or cid_k in deleted_comment_ids:
                continue
            props = cep.get("properties") or {}
            auth = cep.get("author") or {}
            toolbar = cep.get("toolbar") or {}
            msg_text = str((props.get("content") or {}).get("content") or "").strip()
            rel_time = str(props.get("publishedTime") or "").strip()
            u_aid = str(auth.get("channelId") or "").strip()
            u_disp = str(auth.get("displayName") or "").strip()
            u_handle = u_disp.lstrip("@")
            u_avatar = str(auth.get("avatarThumbnailUrl") or "").strip()
            commenter_name = u_disp or (f"@{u_handle}" if u_handle else "YouTube User")

            if u_aid and commenter_name != "YouTube User":
                remember_author_identity(u_aid, commenter_name, f"@{u_handle}" if u_handle else "", u_avatar)

            prev_c = existing_c_map.get(cid_k) or {}
            ts_info = _parse_youtube_relative_time(
                rel_time,
                existing_iso=str(prev_c.get("created_iso") or ""),
                existing_display=str(prev_c.get("display_time") or "")
            )
            replies_list = replies_by_parent.get(cid_k, [])
            like_str = str(toolbar.get("likeCountNotliked") or toolbar.get("likeCountLiked") or "0").strip()
            like_cnt = int(like_str) if like_str.isdigit() else 0

            is_read = (cid_k in seen_ids)
            parsed_comments.append({
                "comment_id": cid_k,
                "zernio_post_id": zernio_post_id,
                "zernio_account_id": account_id,
                "zernio_api_key": preferred_api_key,
                "auth_source": "youtube_direct_live",
                "record_id": record_id,
                "external_post_id": video_id,
                "platform": "youtube",
                "page_id": page_id,
                "account_name": account_name,
                "post_type": post_type,
                "post_caption": post_caption,
                "post_permalink": post_permalink,
                "comment_permalink": f"https://www.youtube.com/watch?v={video_id}&lc={cid_k}",
                "author_name": commenter_name,
                "author_handle": f"@{u_handle}" if u_handle else "",
                "author_id": u_aid or u_handle,
                "author_avatar": u_avatar,
                "is_own_comment": False,
                "can_reply": len(replies_list) == 0,
                "message": msg_text,
                "like_count": like_cnt,
                "created_iso": ts_info["iso"],
                "display_time": ts_info["display"],
                "is_read": is_read,
                "replies": replies_list
            })
        if not parsed_comments:
            YOUTUBE_LIVE_TOKEN_CACHE.pop(video_id, None)
        return parsed_comments
    except Exception as e:
        YOUTUBE_LIVE_TOKEN_CACHE.pop(video_id, None)
        print(f"[⚠️ YOUTUBE DIRECT LIVE COMMENTS WARNING ({video_id})]: {e}")
        return None


def _merge_youtube_comments_lists(
    zernio_list: Optional[List[Dict[str, Any]]],
    direct_list: Optional[List[Dict[str, Any]]]
) -> Optional[List[Dict[str, Any]]]:
    if zernio_list is None and direct_list is None:
        return None
    if not zernio_list:
        return direct_list if direct_list is not None else []
    if not direct_list:
        return zernio_list

    merged_by_id: Dict[str, Dict[str, Any]] = {}
    sig_to_id: Dict[str, str] = {}

    def _comm_sig(author_val: str, msg_val: str) -> str:
        a_clean = re.sub(r"[^a-z0-9]", "", (author_val or "").strip().lower())
        m_clean = (msg_val or "").strip().lower()
        return f"{a_clean}::{m_clean}" if m_clean else ""

    for c_item in zernio_list:
        cid = str(c_item.get("comment_id") or "").strip()
        if not cid:
            continue
        c_copy = dict(c_item)
        c_copy["replies"] = [dict(r) for r in (c_item.get("replies") or []) if isinstance(r, dict)]
        merged_by_id[cid] = c_copy
        sig = _comm_sig(c_copy.get("author_handle") or c_copy.get("author_name") or "", c_copy.get("message") or "")
        if sig:
            sig_to_id[sig] = cid

    for d_item in direct_list:
        d_cid = str(d_item.get("comment_id") or "").strip()
        if not d_cid:
            continue
        d_sig = _comm_sig(d_item.get("author_handle") or d_item.get("author_name") or "", d_item.get("message") or "")
        target_cid = d_cid if d_cid in merged_by_id else (sig_to_id.get(d_sig, "") if d_sig else "")

        if not target_cid:
            c_copy = dict(d_item)
            c_copy["replies"] = [dict(r) for r in (d_item.get("replies") or []) if isinstance(r, dict)]
            merged_by_id[d_cid] = c_copy
            if d_sig:
                sig_to_id[d_sig] = d_cid
        else:
            existing_c = merged_by_id[target_cid]
            if (not existing_c.get("author_avatar")) and d_item.get("author_avatar"):
                existing_c["author_avatar"] = d_item["author_avatar"]
            if existing_c.get("author_name") in ("User", "YouTube User", "") and d_item.get("author_name"):
                existing_c["author_name"] = d_item["author_name"]
            if (not existing_c.get("author_handle")) and d_item.get("author_handle"):
                existing_c["author_handle"] = d_item["author_handle"]

            existing_reps = list(existing_c.get("replies") or [])
            rep_ids = {str(r.get("id") or "").strip() for r in existing_reps}
            rep_sigs = {
                _comm_sig(r.get("author_name") or "", r.get("message") or "")
                for r in existing_reps
            }
            for d_rep in (d_item.get("replies") or []):
                if not isinstance(d_rep, dict):
                    continue
                dr_id = str(d_rep.get("id") or "").strip()
                dr_sig = _comm_sig(d_rep.get("author_name") or "", d_rep.get("message") or "")
                if (dr_id and dr_id in rep_ids) or (dr_sig and dr_sig in rep_sigs):
                    continue
                existing_reps.append(dict(d_rep))
                if dr_id:
                    rep_ids.add(dr_id)
                if dr_sig:
                    rep_sigs.add(dr_sig)
            existing_c["replies"] = existing_reps
            existing_c["can_reply"] = len(existing_reps) == 0

    return list(merged_by_id.values())


def fetch_zernio_comments_for_post(
    candidate_post_ids: List[str],
    account_id: str,
    r_dict: Dict[str, Any],
    seen_ids: set,
    deleted_comment_ids: set,
    clean_user: str = "",
    preferred_api_key: str = ""
) -> Optional[List[Dict[str, Any]]]:
    if not account_id:
        return None

    platform = (r_dict.get("platform") or "").strip().lower()
    account_name = r_dict.get("account_name") or platform.upper()
    sched_dt = r_dict.get("scheduled_time")
    is_ext_post = str(r_dict.get("id") or "").startswith("post_ext_")
    candidate_keys = get_candidate_zernio_keys_for_account(
        account_id,
        preferred_key=preferred_api_key,
        account_name=account_name,
        platform=platform
    )
    if not candidate_keys:
        return None

    valid_ids = []
    for cid_cand in candidate_post_ids:
        c_str = str(cid_cand or "").strip()
        if c_str and c_str != "OK" and c_str not in valid_ids:
            valid_ids.append(c_str)
            if "_" in c_str and platform == "facebook":
                story_part = c_str.split("_")[-1]
                if story_part and story_part not in valid_ids:
                    valid_ids.append(story_part)

    yt_live_comms: Optional[List[Dict[str, Any]]] = None
    if platform == "youtube":
        yt_vid = ""
        for cid_cand in list(valid_ids) + [str(r_dict.get("permalink_url") or ""), str(r_dict.get("external_post_id") or "")]:
            c_str = str(cid_cand or "").strip()
            if re.match(r"^[A-Za-z0-9_-]{11}$", c_str):
                yt_vid = c_str
                break
            m_yt = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})", c_str)
            if m_yt:
                yt_vid = m_yt.group(1).strip()
                break
        if not yt_vid:
            yt_vid = discover_youtube_video_id_direct(r_dict)
        if yt_vid and yt_vid not in valid_ids:
            valid_ids.append(yt_vid)

        yt_live_comms = fetch_youtube_live_comments_direct(
            valid_ids,
            account_id,
            r_dict,
            seen_ids,
            deleted_comment_ids,
            preferred_api_key=(candidate_keys[0] if candidate_keys else preferred_api_key)
        )

    if not valid_ids:
        return yt_live_comms

    record_id = r_dict["id"]
    page_id = str(r_dict.get("page_id") or "")
    post_type = r_dict.get("post_type") or "reels"
    post_caption = r_dict.get("caption") or ""
    had_valid_200 = False

    for api_key in candidate_keys:
        headers = get_zernio_headers(api_key)
        key_had_valid_200 = False

        for post_id in valid_ids:
            try:
                resp = HTTP_SESSION.get(
                    f"{ZERNIO_BASE_URL}/inbox/comments/{post_id}",
                    params={"accountId": account_id},
                    headers=headers,
                    timeout=18
                )
                if resp.status_code != 200:
                    continue

                payload = resp.json() if resp.text else {}
                raw_list = extract_list_from_api_payload(payload)
                if raw_list is None:
                    continue

                had_valid_200 = True
                key_had_valid_200 = True
                CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][str(account_id)] = api_key

                post_permalink = (
                    r_dict.get("permalink_url")
                    or ((payload.get("post") or {}).get("permalink") if isinstance(payload, dict) else "")
                    or ((payload.get("data") or {}).get("permalink") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else "")
                    or ""
                )

                top_level_map: Dict[str, Dict[str, Any]] = {}
                orphan_replies: List[Dict[str, Any]] = []

                nested_reply_ids: Dict[str, str] = {}
                nested_direct_parent_ids: Dict[str, str] = {}

                def _scan_nested_reply_tree(parent_node: Dict[str, Any], root_cid: str, immediate_parent_cid: str):
                    for r_scan in (extract_list_from_api_payload(parent_node.get("replies") or parent_node.get("comments") or parent_node.get("children")) or []):
                        if not isinstance(r_scan, dict):
                            continue
                        r_id_scan = str(r_scan.get("ID") or r_scan.get("id") or r_scan.get("commentId") or r_scan.get("_id") or r_scan.get("platform_id") or "").strip()
                        if r_id_scan and root_cid:
                            nested_reply_ids[r_id_scan] = root_cid
                            nested_direct_parent_ids[r_id_scan] = immediate_parent_cid or root_cid
                            _scan_nested_reply_tree(r_scan, root_cid, r_id_scan)

                for c_scan in raw_list:
                    if not isinstance(c_scan, dict):
                        continue
                    p_cid_scan = str(c_scan.get("ID") or c_scan.get("id") or c_scan.get("commentId") or c_scan.get("_id") or c_scan.get("platform_id") or "").strip()
                    if p_cid_scan:
                        _scan_nested_reply_tree(c_scan, p_cid_scan, p_cid_scan)

                for c in raw_list:
                    if not isinstance(c, dict):
                        continue
                    cid = str(c.get("ID") or c.get("id") or c.get("commentId") or c.get("_id") or c.get("platform_id") or "")
                    if not cid or cid in deleted_comment_ids:
                        continue

                    ts_info = parse_meta_timestamp(
                        c.get("CreatedAt") or c.get("createdAt") or c.get("created_at") or c.get("timestamp") or c.get("createdTime") or "",
                        item_id=cid
                    )

                    if not is_comment_timestamp_valid_for_post(ts_info["iso"], sched_dt, is_external_post=is_ext_post):
                        continue

                    explicit_parent_id = str(
                        c.get("parentCommentId")
                        or c.get("parentId")
                        or c.get("parent_id")
                        or c.get("inReplyToId")
                        or (c.get("parent") or {}).get("id")
                        or nested_direct_parent_ids.get(cid, "")
                        or (cid.split(".")[0] if (platform == "youtube" and "." in cid) else "")
                        or ""
                    ).strip()
                    parent_id = str(nested_reply_ids.get(cid, "") or explicit_parent_id).strip()
                    post_id_norms = {
                        str(x).strip()
                        for x in (
                            post_id,
                            post_id.split("_")[-1] if "_" in post_id else "",
                            extract_external_post_id(r_dict),
                            (extract_external_post_id(r_dict) or "").split("_")[-1] if "_" in (extract_external_post_id(r_dict) or "") else "",
                            cid
                        )
                        if x and str(x).strip()
                    }
                    if explicit_parent_id in post_id_norms or _normalize_comment_key(explicit_parent_id) in post_id_norms:
                        explicit_parent_id = ""
                    if parent_id in post_id_norms or _normalize_comment_key(parent_id) in post_id_norms:
                        parent_id = ""
                    is_reply_flag = bool(c.get("isReply") or c.get("is_reply") or parent_id or (cid in nested_reply_ids))

                    auth_obj = c.get("Author") or c.get("author") or c.get("from") or c.get("user") or {}
                    if not isinstance(auth_obj, dict):
                        auth_obj = {}

                    u_aid = str(auth_obj.get("ID") or auth_obj.get("id") or c.get("author_id") or c.get("authorId") or "").strip()
                    u_handle = (
                        c.get("author_username")
                        or c.get("username")
                        or auth_obj.get("Username")
                        or auth_obj.get("username")
                        or auth_obj.get("unique_id")
                        or ""
                    ).strip().lstrip("@")
                    u_name = (
                        c.get("author_name")
                        or auth_obj.get("Name")
                        or auth_obj.get("name")
                        or auth_obj.get("displayName")
                        or auth_obj.get("nickname")
                        or ""
                    ).strip()
                    u_avatar = (
                        c.get("author_picture")
                        or auth_obj.get("Picture")
                        or auth_obj.get("picture")
                        or auth_obj.get("avatarUrl")
                        or auth_obj.get("profilePictureUrl")
                        or auth_obj.get("avatar")
                        or ""
                    )

                    if u_name and u_handle and u_name.lower() != u_handle.lower():
                        commenter_name = f"{u_name} (@{u_handle})"
                    elif u_name:
                        commenter_name = u_name
                    elif u_handle:
                        commenter_name = f"@{u_handle}"
                    else:
                        commenter_name = "User"

                    explicit_not_own = (
                        c.get("isOwnAccount") is False
                        or auth_obj.get("isOwnAccount") is False
                        or c.get("isOwner") is False
                        or auth_obj.get("isOwner") is False
                    )
                    is_own = bool(
                        c.get("IsOwner")
                        or c.get("isOwner")
                        or c.get("is_owner")
                        or c.get("isOwnAccount")
                        or c.get("fromOwner")
                        or auth_obj.get("IsOwner")
                        or auth_obj.get("isOwner")
                        or auth_obj.get("is_owner")
                        or auth_obj.get("isOwnAccount")
                        or (not explicit_not_own and clean_user and u_handle and u_handle.lower() == clean_user.lower())
                        or (is_reply_flag and not explicit_not_own and account_name and u_name and u_name.lower() == account_name.strip().lstrip("@").lower())
                    )

                    if commenter_name not in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User") and u_aid and not is_own:
                        remember_author_identity(u_aid, commenter_name, f"@{u_handle}" if u_handle else "", u_avatar)
                    elif commenter_name == "User" and u_aid:
                        known = lookup_known_author_identity(u_aid, record_id)
                        if known and known.get("name"):
                            commenter_name = known["name"]
                            if not u_avatar and known.get("avatar"):
                                u_avatar = known["avatar"]

                    if not is_reply_flag and is_own:
                        # Top-level comment by the Page on its own post (NOT a reply to a comment) -> skip
                        continue

                    if is_reply_flag:
                        rep_obj = _parse_single_zernio_reply(
                            c,
                            clean_user,
                            account_name,
                            parent_comment_id=parent_id,
                            replied_to_id=(explicit_parent_id or parent_id)
                        )
                        rep_obj["parent_id"] = parent_id
                        rep_obj["direct_parent_id"] = explicit_parent_id or parent_id
                        rep_obj["_raw_sub_replies"] = list(extract_list_from_api_payload(c.get("replies") or c.get("comments") or c.get("children")) or [])
                        rep_obj["_has_sub_replies"] = bool(
                            c.get("hasReplies")
                            or c.get("has_replies")
                            or int(c.get("replyCount") or c.get("reply_count") or c.get("commentCount") or c.get("comment_count") or 0) > len(rep_obj["_raw_sub_replies"])
                        )
                        orphan_replies.append(rep_obj)
                        continue

                    replies_raw = list(extract_list_from_api_payload(c.get("replies") or c.get("comments") or c.get("children")) or [])
                    reply_count = int(c.get("replyCount") or c.get("reply_count") or c.get("commentCount") or c.get("comment_count") or 0)
                    has_replies = bool(c.get("hasReplies") or c.get("has_replies") or reply_count > len(replies_raw))

                    if has_replies or platform in ("facebook", "instagram"):
                        try:
                            sub_resp = HTTP_SESSION.get(
                                f"{ZERNIO_BASE_URL}/inbox/comments/{post_id}",
                                params={"accountId": account_id, "commentId": cid},
                                headers=headers,
                                timeout=15
                            )
                            if sub_resp.status_code == 200:
                                sub_list = extract_list_from_api_payload(sub_resp.json())
                                if sub_list:
                                    seen_raw_rids = {
                                        str(r.get("ID") or r.get("id") or r.get("commentId") or r.get("_id") or r.get("platform_id") or "").strip()
                                        for r in replies_raw if isinstance(r, dict)
                                    }
                                    for sr in sub_list:
                                        if isinstance(sr, dict):
                                            sr_id = str(sr.get("ID") or sr.get("id") or sr.get("commentId") or sr.get("_id") or sr.get("platform_id") or "").strip()
                                            if sr_id and sr_id != cid and sr_id not in seen_raw_rids:
                                                replies_raw.append(sr)
                                                seen_raw_rids.add(sr_id)
                        except Exception:
                            pass

                    replies_list: List[Dict[str, Any]] = []
                    seen_parsed_rids: set = set()

                    for rep in replies_raw:
                        if not isinstance(rep, dict):
                            continue
                        parsed_rep = _parse_single_zernio_reply(rep, clean_user, account_name, parent_comment_id=cid, replied_to_id=cid)
                        r_id_val = str(parsed_rep.get("id") or "").strip()
                        if r_id_val and r_id_val not in seen_parsed_rids:
                            seen_parsed_rids.add(r_id_val)
                            replies_list.append(parsed_rep)

                        # Also inspect 2nd-level nested replies only when the API explicitly indicates nested replies exist on this reply
                        sub_replies_raw = list(extract_list_from_api_payload(rep.get("replies") or rep.get("comments") or rep.get("children")) or [])
                        sub_reply_count = int(rep.get("replyCount") or rep.get("reply_count") or rep.get("commentCount") or rep.get("comment_count") or 0)
                        sub_has_replies = bool(rep.get("hasReplies") or rep.get("has_replies") or sub_reply_count > len(sub_replies_raw))

                        if r_id_val and not r_id_val.startswith(("local_", "z_rep_")) and sub_has_replies:
                            try:
                                sub2_resp = HTTP_SESSION.get(
                                    f"{ZERNIO_BASE_URL}/inbox/comments/{post_id}",
                                    params={"accountId": account_id, "commentId": r_id_val},
                                    headers=headers,
                                    timeout=8
                                )
                                if sub2_resp.status_code == 200:
                                    sub2_list = extract_list_from_api_payload(sub2_resp.json()) or []
                                    seen_sub2_ids = {
                                        str(sr.get("ID") or sr.get("id") or sr.get("commentId") or sr.get("_id") or sr.get("platform_id") or "").strip()
                                        for sr in sub_replies_raw if isinstance(sr, dict)
                                    }
                                    norm_r_id_val = _normalize_comment_key(r_id_val)
                                    for sr2 in sub2_list:
                                        if isinstance(sr2, dict):
                                            sr2_id = str(sr2.get("ID") or sr2.get("id") or sr2.get("commentId") or sr2.get("_id") or sr2.get("platform_id") or "").strip()
                                            sr2_parent = str(
                                                sr2.get("parentCommentId")
                                                or sr2.get("parentId")
                                                or sr2.get("parent_id")
                                                or sr2.get("inReplyToId")
                                                or (sr2.get("parent") or {}).get("id")
                                                or ""
                                            ).strip()
                                            if (
                                                sr2_id
                                                and sr2_id != r_id_val
                                                and sr2_id != cid
                                                and sr2_id not in seen_sub2_ids
                                                and (not sr2_parent or sr2_parent == r_id_val or _normalize_comment_key(sr2_parent) == norm_r_id_val)
                                            ):
                                                sub_replies_raw.append(sr2)
                                                seen_sub2_ids.add(sr2_id)
                            except Exception:
                                pass

                        for sub_rep in sub_replies_raw:
                            if not isinstance(sub_rep, dict):
                                continue
                            parsed_sub = _parse_single_zernio_reply(
                                sub_rep,
                                clean_user,
                                account_name,
                                parent_comment_id=cid,
                                replied_to_id=(r_id_val or cid)
                            )
                            sub_id_val = str(parsed_sub.get("id") or "").strip()
                            if sub_id_val and sub_id_val not in seen_parsed_rids:
                                seen_parsed_rids.add(sub_id_val)
                                replies_list.append(parsed_sub)

                    is_read = (cid in seen_ids) or is_own
                    top_level_map[cid] = {
                        "comment_id": cid,
                        "zernio_post_id": post_id,
                        "zernio_account_id": account_id,
                        "zernio_api_key": api_key,
                        "auth_source": "external_api",
                        "record_id": record_id,
                        "external_post_id": extract_external_post_id(r_dict) or post_id,
                        "platform": platform,
                        "page_id": page_id,
                        "account_name": account_name,
                        "post_type": post_type,
                        "post_caption": post_caption,
                        "post_permalink": post_permalink,
                        "comment_permalink": c.get("permalink") or c.get("permalinkUrl") or post_permalink,
                        "author_name": commenter_name,
                        "author_handle": f"@{u_handle}" if u_handle else "",
                        "author_id": u_aid or u_handle,
                        "author_avatar": u_avatar,
                        "is_own_comment": is_own,
                        "can_reply": len(replies_list) == 0,
                        "is_liked": bool(c.get("isLiked") or c.get("is_liked") or c.get("liked") or c.get("user_likes")),
                        "is_hidden": bool(c.get("isHidden") or c.get("is_hidden") or c.get("hidden")),
                        "message": c.get("Text") or c.get("text") or c.get("message") or c.get("content") or "",
                        "like_count": c.get("likeCount") or c.get("like_count") or 0,
                        "created_iso": ts_info["iso"],
                        "display_time": ts_info["display"],
                        "is_read": is_read,
                        "replies": replies_list
                    }

                # Build map of reply_id -> root top_level_map entry so 2nd-level orphan replies (replied to a reply) attach to the right thread
                reply_id_to_parent_comm: Dict[str, Dict[str, Any]] = {}
                for k_cid, p_comm in top_level_map.items():
                    for existing_r in (p_comm.get("replies") or []):
                        ex_rid = str(existing_r.get("id") or "").strip()
                        if ex_rid:
                            reply_id_to_parent_comm[ex_rid] = p_comm
                            reply_id_to_parent_comm[_normalize_comment_key(ex_rid)] = p_comm

                for rep_item in orphan_replies:
                    pid_target = rep_item.pop("parent_id", "")
                    direct_pid_target = rep_item.pop("direct_parent_id", "") or pid_target
                    raw_sub_reps = rep_item.pop("_raw_sub_replies", []) or []
                    has_sub_reps = bool(rep_item.pop("_has_sub_replies", False))
                    if direct_pid_target:
                        rep_item["replied_to_id"] = direct_pid_target
                    target_parent = None
                    if pid_target and pid_target in top_level_map:
                        target_parent = top_level_map[pid_target]
                    elif direct_pid_target and direct_pid_target in reply_id_to_parent_comm:
                        target_parent = reply_id_to_parent_comm[direct_pid_target]
                    elif pid_target and pid_target in reply_id_to_parent_comm:
                        target_parent = reply_id_to_parent_comm[pid_target]
                    elif pid_target:
                        norm_p = _normalize_comment_key(pid_target)
                        norm_dp = _normalize_comment_key(direct_pid_target)
                        if norm_dp in reply_id_to_parent_comm:
                            target_parent = reply_id_to_parent_comm[norm_dp]
                        elif norm_p in reply_id_to_parent_comm:
                            target_parent = reply_id_to_parent_comm[norm_p]
                        else:
                            for k_cid, p_comm in top_level_map.items():
                                if _normalize_comment_key(k_cid) in (norm_p, norm_dp):
                                    target_parent = p_comm
                                    break

                    if not target_parent and top_level_map and not rep_item.get("is_own"):
                        rep_iso = rep_item.get("created_iso") or ""
                        candidates = [
                            p_comm for p_comm in top_level_map.values()
                            if (p_comm.get("created_iso") or "") <= rep_iso
                        ]
                        if candidates:
                            candidates.sort(key=lambda x: x.get("created_iso") or "", reverse=True)
                            target_parent = candidates[0]
                        else:
                            target_parent = next(iter(top_level_map.values()))

                    if target_parent is not None:
                        root_parent_cid = str(target_parent.get("comment_id") or "")
                        rep_item["parent_comment_id"] = root_parent_cid
                        if not rep_item.get("replied_to_id"):
                            rep_item["replied_to_id"] = direct_pid_target or root_parent_cid
                        if not rep_item.get("is_own") and rep_item.get("author_name") in ("User", "TikTok User", "Facebook User", "Instagram User", ""):
                            p_author = target_parent.get("author_name") or ""
                            if p_author and p_author not in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"):
                                rep_item["author_name"] = p_author
                                if not rep_item.get("author_avatar") and target_parent.get("author_avatar"):
                                    rep_item["author_avatar"] = target_parent["author_avatar"]

                        existing_reps = target_parent.setdefault("replies", [])
                        rep_item_id = str(rep_item.get("id") or "").strip()
                        if not any(str(r.get("id")) == rep_item_id for r in existing_reps):
                            existing_reps.append(rep_item)
                            if rep_item_id:
                                reply_id_to_parent_comm[rep_item_id] = target_parent
                                reply_id_to_parent_comm[_normalize_comment_key(rep_item_id)] = target_parent

                        # If this orphan reply explicitly has 2nd-level nested replies, fetch and attach them too
                        if rep_item_id and not rep_item_id.startswith(("local_", "z_rep_")) and has_sub_reps:
                            try:
                                sub_orp_resp = HTTP_SESSION.get(
                                    f"{ZERNIO_BASE_URL}/inbox/comments/{post_id}",
                                    params={"accountId": account_id, "commentId": rep_item_id},
                                    headers=headers,
                                    timeout=8
                                )
                                if sub_orp_resp.status_code == 200:
                                    sub_orp_list = extract_list_from_api_payload(sub_orp_resp.json()) or []
                                    seen_orp_sub_ids = {
                                        str(sr.get("ID") or sr.get("id") or sr.get("commentId") or sr.get("_id") or sr.get("platform_id") or "").strip()
                                        for sr in raw_sub_reps if isinstance(sr, dict)
                                    }
                                    norm_rep_item_id = _normalize_comment_key(rep_item_id)
                                    for sr_o in sub_orp_list:
                                        if isinstance(sr_o, dict):
                                            sr_o_id = str(sr_o.get("ID") or sr_o.get("id") or sr_o.get("commentId") or sr_o.get("_id") or sr_o.get("platform_id") or "").strip()
                                            sr_o_parent = str(
                                                sr_o.get("parentCommentId")
                                                or sr_o.get("parentId")
                                                or sr_o.get("parent_id")
                                                or sr_o.get("inReplyToId")
                                                or (sr_o.get("parent") or {}).get("id")
                                                or ""
                                            ).strip()
                                            if (
                                                sr_o_id
                                                and sr_o_id != rep_item_id
                                                and sr_o_id != root_parent_cid
                                                and sr_o_id not in seen_orp_sub_ids
                                                and (not sr_o_parent or sr_o_parent == rep_item_id or _normalize_comment_key(sr_o_parent) == norm_rep_item_id)
                                            ):
                                                raw_sub_reps.append(sr_o)
                                                seen_orp_sub_ids.add(sr_o_id)
                            except Exception:
                                pass

                        for sub_o_rep in raw_sub_reps:
                            if not isinstance(sub_o_rep, dict):
                                continue
                            parsed_o_sub = _parse_single_zernio_reply(
                                sub_o_rep,
                                clean_user,
                                account_name,
                                parent_comment_id=root_parent_cid,
                                replied_to_id=(rep_item_id or root_parent_cid)
                            )
                            sub_o_id = str(parsed_o_sub.get("id") or "").strip()
                            if sub_o_id and not any(str(r.get("id")) == sub_o_id for r in existing_reps):
                                existing_reps.append(parsed_o_sub)
                                reply_id_to_parent_comm[sub_o_id] = target_parent
                                reply_id_to_parent_comm[_normalize_comment_key(sub_o_id)] = target_parent
                    elif not rep_item.get("is_own"):
                        # Fallback: if no parent comment exists in top_level_map, promote user comment so it is never lost
                        prom_cid = str(rep_item.get("id") or "").strip()
                        if prom_cid and prom_cid not in top_level_map:
                            top_level_map[prom_cid] = {
                                "comment_id": prom_cid,
                                "zernio_post_id": post_id,
                                "zernio_account_id": account_id,
                                "zernio_api_key": api_key,
                                "auth_source": "external_api",
                                "record_id": record_id,
                                "external_post_id": extract_external_post_id(r_dict) or post_id,
                                "platform": platform,
                                "page_id": page_id,
                                "account_name": account_name,
                                "post_type": post_type,
                                "post_caption": post_caption,
                                "post_permalink": post_permalink,
                                "comment_permalink": post_permalink,
                                "author_name": rep_item.get("author_name") or "User",
                                "author_handle": "",
                                "author_id": rep_item.get("author_id") or "",
                                "author_avatar": rep_item.get("author_avatar") or "",
                                "is_own_comment": False,
                                "can_reply": True,
                                "is_liked": False,
                                "is_hidden": False,
                                "message": rep_item.get("message") or "",
                                "like_count": 0,
                                "created_iso": rep_item.get("created_iso") or "",
                                "display_time": rep_item.get("display_time") or "",
                                "is_read": prom_cid in seen_ids,
                                "replies": []
                            }

                parsed_comments = list(top_level_map.values())
                if parsed_comments:
                    if platform == "youtube":
                        return _merge_youtube_comments_lists(parsed_comments, yt_live_comms)
                    return parsed_comments
            except Exception as e:
                print(f"[⚠️ EXTERNAL API COMMENTS FETCH WARNING ({post_id})]: {e}")

        if key_had_valid_200:
            break

    if platform == "youtube":
        return _merge_youtube_comments_lists([] if had_valid_200 else None, yt_live_comms)
    return [] if had_valid_200 else None


RECENT_OWN_REPLIES_BUFFER: Dict[str, List[Dict[str, Any]]] = {}

def _normalize_comment_key(comment_id: str) -> str:
    raw = str(comment_id or "").strip()
    return raw.split("_")[-1] if "_" in raw else raw

def find_parent_and_target_comment(post_entry: Dict[str, Any], target_comment_id: str):
    if not isinstance(post_entry, dict):
        return None, None
    c_map = post_entry.get("comments") or {}
    raw_target = str(target_comment_id or "").strip()
    norm_target = _normalize_comment_key(raw_target)
    if not raw_target:
        return None, None

    if raw_target in c_map:
        return c_map[raw_target], None

    for c_key, c_obj in c_map.items():
        if _normalize_comment_key(c_key) == norm_target:
            return c_obj, None
        for r in (c_obj.get("replies") or []):
            r_id = str(r.get("id") or "").strip()
            if r_id and (r_id == raw_target or _normalize_comment_key(r_id) == norm_target):
                return c_obj, r
    return None, None

def record_buffered_own_reply(record_id: str, comment_id: str, reply_id: str, author_name: str, message: str) -> Dict[str, Any]:
    now_dt = datetime.now(pytz.timezone("Asia/Manila"))
    now_ts = time.time()
    raw_cid = str(comment_id or "").strip()
    norm_cid = _normalize_comment_key(raw_cid)

    posts_store = CLOUDINARY_COMMENTS_STORE.setdefault("posts", {})
    post_entry = posts_store.get(record_id)
    parent_c_obj, matched_sub_reply = find_parent_and_target_comment(post_entry or {}, raw_cid)
    parent_cid = str((parent_c_obj or {}).get("comment_id") or raw_cid).strip()
    norm_parent_cid = _normalize_comment_key(parent_cid)

    rep_entry = {
        "id": str(reply_id or f"local_{int(now_ts * 1000)}"),
        "parent_comment_id": parent_cid,
        "replied_to_id": raw_cid,
        "author_name": author_name or "Page Reply",
        "author_avatar": "",
        "is_own": True,
        "is_read": True,
        "can_reply": True,
        "message": message.strip(),
        "created_iso": now_dt.isoformat(),
        "display_time": now_dt.strftime("%b %d, %Y • %I:%M %p"),
        "buffered_at": now_ts
    }

    for key in {norm_cid, raw_cid, parent_cid, norm_parent_cid}:
        if not key:
            continue
        lst = RECENT_OWN_REPLIES_BUFFER.setdefault(key, [])
        if not any(r.get("message") == rep_entry["message"] and (now_ts - r.get("buffered_at", 0) < 120) for r in lst):
            lst.append(rep_entry)

    if parent_c_obj is not None:
        reps = list(parent_c_obj.get("replies") or [])
        clean_rep = {k: v for k, v in rep_entry.items() if k != "buffered_at"}
        if not any(r.get("id") == clean_rep["id"] or (r.get("is_own") and r.get("message", "").strip() == clean_rep["message"]) for r in reps):
            reps.append(clean_rep)
            parent_c_obj["replies"] = reps
        parent_c_obj["can_reply"] = False
        save_comments_store_async()

    return rep_entry

def merge_buffered_own_replies(comment_id: str, replies_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now_ts = time.time()
    norm_cid = _normalize_comment_key(comment_id)
    raw_cid = str(comment_id or "").strip()
    buffered = []
    for k in {norm_cid, raw_cid}:
        if k in RECENT_OWN_REPLIES_BUFFER:
            RECENT_OWN_REPLIES_BUFFER[k] = [
                r for r in RECENT_OWN_REPLIES_BUFFER[k]
                if (now_ts - r.get("buffered_at", 0)) < 900
            ]
            buffered.extend(RECENT_OWN_REPLIES_BUFFER[k])

    if not buffered:
        return replies_list

    merged = list(replies_list)
    for b_rep in buffered:
        b_msg = (b_rep.get("message") or "").strip().lower()
        b_id = str(b_rep.get("id") or "")
        already_indexed = any(
            (b_id and not b_id.startswith("local_") and b_id != "ok" and str(r.get("id") or "") == b_id)
            or (r.get("is_own") and (r.get("message") or "").strip().lower() == b_msg)
            for r in merged
        )
        if not already_indexed:
            merged.append({k: v for k, v in b_rep.items() if k != "buffered_at"})
    return merged

def enrich_comment_with_reply_notifications(comment_obj: Dict[str, Any], seen_ids: set) -> Dict[str, Any]:
    cid_str = str(comment_obj.get("comment_id") or "")
    parent_sf_dt = extract_snowflake_timestamp(cid_str)
    if parent_sf_dt is not None:
        comment_obj["created_iso"] = parent_sf_dt.isoformat()
        comment_obj["display_time"] = parent_sf_dt.strftime("%b %d, %Y • %I:%M %p")

    reps = merge_buffered_own_replies(cid_str, list(comment_obj.get("replies") or []))
    for r in reps:
        r_id = str(r.get("id") or "")
        r_sf_dt = extract_snowflake_timestamp(r_id)
        if r_sf_dt is not None:
            r["created_iso"] = r_sf_dt.isoformat()
            r["display_time"] = r_sf_dt.strftime("%b %d, %Y • %I:%M %p")
        r["parent_comment_id"] = cid_str
        r["can_reply"] = True

    reps.sort(key=lambda r: r.get("created_iso") or "")

    unread_replies = []
    commenter_replies = []
    for r in reps:
        r_id = str(r.get("id") or "")
        r_is_own = bool(r.get("is_own"))
        r_is_read = r_is_own or (r_id in seen_ids)
        r["is_read"] = r_is_read
        if not r_is_own:
            commenter_replies.append(r)
            if not r_is_read:
                unread_replies.append(r)

    comment_obj["replies"] = reps
    comment_obj["can_reply"] = (len(reps) == 0)

    parent_is_read = (cid_str in seen_ids) or bool(comment_obj.get("is_own_comment"))
    comment_obj["parent_is_read"] = parent_is_read
    comment_obj["unread_reply_ids"] = [str(r.get("id")) for r in unread_replies if r.get("id")]
    comment_obj["unread_replies_count"] = len(unread_replies)
    comment_obj["has_unread_reply"] = len(unread_replies) > 0
    comment_obj["is_read"] = parent_is_read and not comment_obj["has_unread_reply"]

    latest_commenter_reply = commenter_replies[-1] if commenter_replies else None
    comment_obj["latest_commenter_reply"] = latest_commenter_reply

    parent_iso = comment_obj.get("created_iso") or ""
    latest_activity_iso = parent_iso
    latest_display_time = comment_obj.get("display_time") or ""
    latest_item_id = cid_str
    latest_item_text = comment_obj.get("message") or ""
    latest_item_author = comment_obj.get("author_name") or "User"

    if latest_commenter_reply and (latest_commenter_reply.get("created_iso") or "") > parent_iso:
        latest_activity_iso = latest_commenter_reply.get("created_iso") or parent_iso
        latest_display_time = latest_commenter_reply.get("display_time") or latest_display_time
        latest_item_id = str(latest_commenter_reply.get("id") or cid_str)
        latest_item_text = latest_commenter_reply.get("message") or latest_item_text
        latest_item_author = latest_commenter_reply.get("author_name") or latest_item_author

    comment_obj["latest_activity_iso"] = latest_activity_iso
    comment_obj["latest_display_time"] = latest_display_time
    comment_obj["latest_comment_or_reply_id"] = latest_item_id
    comment_obj["latest_comment_or_reply_text"] = latest_item_text
    comment_obj["latest_comment_or_reply_author"] = latest_item_author
    return comment_obj


def _get_cached_seen_comment_ids(ttl_sec: float = 3.0) -> set:
    now_ts = time.time()
    with FAST_DB_READ_CACHE_LOCK:
        if (now_ts - FAST_DB_READ_CACHE.get("seen_comments_ts", 0.0)) < ttl_sec and isinstance(FAST_DB_READ_CACHE.get("seen_comments"), set):
            return set(FAST_DB_READ_CACHE["seen_comments"])
    try:
        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT comment_id FROM glennbot_seen_comments")).mappings().all()
            seen_ids = {str(r["comment_id"]) for r in seen_rows}
        with FAST_DB_READ_CACHE_LOCK:
            FAST_DB_READ_CACHE["seen_comments"] = seen_ids
            FAST_DB_READ_CACHE["seen_comments_ts"] = now_ts
        return set(seen_ids)
    except Exception:
        with FAST_DB_READ_CACHE_LOCK:
            return set(FAST_DB_READ_CACHE.get("seen_comments") or set())


def _get_cached_published_posts(ttl_sec: float = 3.5, force: bool = False) -> List[Dict[str, Any]]:
    now_ts = time.time()
    if not force:
        with FAST_DB_READ_CACHE_LOCK:
            if (now_ts - FAST_DB_READ_CACHE.get("published_posts_ts", 0.0)) < ttl_sec and FAST_DB_READ_CACHE.get("published_posts"):
                return [dict(x) for x in FAST_DB_READ_CACHE["published_posts"]]
    try:
        with db_engine.connect() as conn:
            post_rows = conn.execute(text("""
                SELECT id, platform, page_id, account_name, post_type, caption,
                       media_preview_url, scheduled_time, status, status_message, external_post_id, permalink_url
                FROM glennbot_scheduled_posts
                WHERE status = 'published'
                ORDER BY scheduled_time DESC
                LIMIT 120
            """)).mappings().all()
        rows_list = [dict(r) for r in post_rows]
        with FAST_DB_READ_CACHE_LOCK:
            FAST_DB_READ_CACHE["published_posts"] = rows_list
            FAST_DB_READ_CACHE["published_posts_ts"] = now_ts
        return [dict(x) for x in rows_list]
    except Exception:
        with FAST_DB_READ_CACHE_LOCK:
            return [dict(x) for x in (FAST_DB_READ_CACHE.get("published_posts") or [])]


def _get_cached_seen_messages_map(ttl_sec: float = 3.0) -> Dict[str, str]:
    now_ts = time.time()
    with FAST_DB_READ_CACHE_LOCK:
        if (now_ts - FAST_DB_READ_CACHE.get("seen_messages_ts", 0.0)) < ttl_sec and isinstance(FAST_DB_READ_CACHE.get("seen_messages"), dict):
            return dict(FAST_DB_READ_CACHE["seen_messages"])
    try:
        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT conversation_id, last_seen_iso FROM glennbot_seen_messages")).mappings().all()
            seen_map = {str(r["conversation_id"]): str(r["last_seen_iso"] or "") for r in seen_rows}
        with FAST_DB_READ_CACHE_LOCK:
            FAST_DB_READ_CACHE["seen_messages"] = seen_map
            FAST_DB_READ_CACHE["seen_messages_ts"] = now_ts
        return dict(seen_map)
    except Exception:
        with FAST_DB_READ_CACHE_LOCK:
            return dict(FAST_DB_READ_CACHE.get("seen_messages") or {})


def update_cloudinary_store_for_post(
    r_dict: Dict[str, Any],
    fetched_comments: List[Dict[str, Any]],
    unhide_if_new: bool = True,
    force_unhide: bool = False
) -> bool:
    # CRITICAL FIX: Ensure existing comment IDs are seeded BEFORE we insert new comments into CLOUDINARY_COMMENTS_STORE!
    # Otherwise, the first comment (or a simultaneous burst) inserted into existing_comments_map gets marked as "already seeded"
    # and skipped by _notify_n8n_new_comment!
    if "_seed_existing_comment_ids_for_n8n" in globals() and not globals().get("N8N_COMMENT_SEED_DONE", False):
        try:
            _seed_existing_comment_ids_for_n8n()
        except Exception:
            pass

    notifications_to_fire: List[Tuple[Dict[str, Any], bool]] = []

    with COMMENTS_STORE_LOCK:
        record_id = str(r_dict["id"])
        sched_dt = r_dict.get("scheduled_time")
        is_ext_post = record_id.startswith("post_ext_")
        posts_store = CLOUDINARY_COMMENTS_STORE.setdefault("posts", {})
        post_entry = posts_store.get(record_id)

        if not post_entry:
            post_entry = {
                "record_id": record_id,
                "platform": r_dict.get("platform") or "",
                "page_id": str(r_dict.get("page_id") or ""),
                "account_name": r_dict.get("account_name") or "",
                "post_type": r_dict.get("post_type") or "reels",
                "post_caption": r_dict.get("caption") or "",
                "post_permalink": r_dict.get("permalink_url") or "",
                "notification_hidden": False,
                "deleted_comment_ids": [],
                "comments": {}
            }
            posts_store[record_id] = post_entry

        deleted_cids = set(str(x) for x in (post_entry.get("deleted_comment_ids") or []))
        existing_comments_map: Dict[str, Dict[str, Any]] = post_entry.get("comments") or {}
        generic_names = {"", "User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"}

        for old_cid, old_c in list(existing_comments_map.items()):
            if old_cid in deleted_cids or not is_comment_timestamp_valid_for_post(old_c.get("created_iso", ""), sched_dt, is_external_post=is_ext_post) or old_c.get("is_own_comment"):
                existing_comments_map.pop(old_cid, None)

        has_brand_new_activity = False
        changed = False

        for fc in fetched_comments:
            cid = str(fc.get("comment_id") or "").strip()
            if not cid or cid in deleted_cids or fc.get("is_own_comment"):
                continue
            if not is_comment_timestamp_valid_for_post(fc.get("created_iso", ""), sched_dt, is_external_post=is_ext_post):
                continue

            fc["record_id"] = record_id

            for other_rid, other_p in list(posts_store.items()):
                if other_rid != record_id and isinstance(other_p.get("comments"), dict) and cid in other_p["comments"]:
                    other_p["comments"].pop(cid, None)
                    changed = True

            if cid not in existing_comments_map:
                has_brand_new_activity = True
                changed = True
                existing_comments_map[cid] = fc
                if not fc.get("is_own_comment"):
                    notifications_to_fire.append((dict(fc), True))
                # Also check if this brand-new comment already came with replies (both user replies and Page replies to the comment)
                for init_rep in (fc.get("replies") or []):
                    ir_id = str(init_rep.get("id") or "").strip()
                    if ir_id:
                        ir_is_own = bool(init_rep.get("is_own"))
                        notifications_to_fire.append(({
                            "comment_id": ir_id,
                            "parent_comment_id": cid,
                            "replied_to_id": str(init_rep.get("replied_to_id") or cid),
                            "is_reply": True,
                            "is_reply_to_comment": True,
                            "record_id": record_id,
                            "zernio_post_id": fc.get("zernio_post_id") or r_dict.get("external_post_id") or "",
                            "zernio_account_id": fc.get("zernio_account_id") or str(r_dict.get("page_id") or ""),
                            "platform": fc.get("platform") or r_dict.get("platform") or "",
                            "page_id": str(r_dict.get("page_id") or ""),
                            "account_name": r_dict.get("account_name") or "",
                            "author_id": str(init_rep.get("author_id") or fc.get("author_id") or r_dict.get("page_id") or ""),
                            "author_name": str(init_rep.get("author_name") or (r_dict.get("account_name") if ir_is_own else "Commenter")),
                            "parent_author_id": str(fc.get("author_id") or ""),
                            "parent_author_name": str(fc.get("author_name") or ""),
                            "message": str(init_rep.get("message") or ""),
                            "created_iso": str(init_rep.get("created_iso") or fc.get("created_iso") or ""),
                            "is_own_comment": ir_is_own
                        }, True))
            else:
                prev_c = existing_comments_map[cid]
                if fc.get("author_name") in generic_names and prev_c.get("author_name") not in generic_names:
                    fc["author_name"] = prev_c["author_name"]
                    if prev_c.get("author_handle"):
                        fc["author_handle"] = prev_c["author_handle"]
                    if prev_c.get("author_avatar"):
                        fc["author_avatar"] = prev_c["author_avatar"]
                elif prev_c.get("author_name") in generic_names and fc.get("author_name") not in generic_names:
                    changed = True

                prev_reps = prev_c.get("replies") or []
                prev_rep_map = {str(r.get("id")): r for r in prev_reps if r.get("id")}
                new_reps = fc.get("replies") or []

                merged_reps = list(prev_reps)
                for nr in new_reps:
                    nr_id = str(nr.get("id") or "")
                    if not nr_id:
                        continue
                    if nr_id not in prev_rep_map:
                        upgraded_placeholder = False
                        # If this is a real own reply from the platform, upgrade any synthetic local_/z_rep_ placeholder with matching text
                        if nr.get("is_own") and not nr_id.startswith(("local_", "z_rep_")):
                            nr_msg_clean = (nr.get("message") or "").strip().lower()
                            for er in merged_reps:
                                if (
                                    er.get("is_own")
                                    and str(er.get("id") or "").startswith(("local_", "z_rep_"))
                                    and (er.get("message") or "").strip().lower() == nr_msg_clean
                                ):
                                    upgraded_placeholder = True
                                    break
                            merged_reps = [
                                er for er in merged_reps
                                if not (
                                    er.get("is_own")
                                    and str(er.get("id") or "").startswith(("local_", "z_rep_"))
                                    and (er.get("message") or "").strip().lower() == nr_msg_clean
                                )
                            ]
                        merged_reps.append(nr)
                        prev_rep_map[nr_id] = nr
                        changed = True
                        nr_is_own = bool(nr.get("is_own"))
                        if not nr_is_own:
                            has_brand_new_activity = True
                        if not upgraded_placeholder:
                            notifications_to_fire.append(({
                                "comment_id": nr_id,
                                "parent_comment_id": cid,
                                "replied_to_id": str(nr.get("replied_to_id") or cid),
                                "is_reply": True,
                                "is_reply_to_comment": True,
                                "record_id": record_id,
                                "zernio_post_id": fc.get("zernio_post_id") or prev_c.get("zernio_post_id") or r_dict.get("external_post_id") or "",
                                "zernio_account_id": fc.get("zernio_account_id") or prev_c.get("zernio_account_id") or str(r_dict.get("page_id") or ""),
                                "platform": fc.get("platform") or prev_c.get("platform") or r_dict.get("platform") or "",
                                "page_id": str(r_dict.get("page_id") or ""),
                                "account_name": r_dict.get("account_name") or "",
                                "author_id": str(nr.get("author_id") or fc.get("author_id") or prev_c.get("author_id") or r_dict.get("page_id") or ""),
                                "author_name": str(nr.get("author_name") or (r_dict.get("account_name") if nr_is_own else "Commenter")),
                                "parent_author_id": str(fc.get("author_id") or prev_c.get("author_id") or ""),
                                "parent_author_name": str(fc.get("author_name") or prev_c.get("author_name") or ""),
                                "message": str(nr.get("message") or ""),
                                "created_iso": str(nr.get("created_iso") or ""),
                                "is_own_comment": nr_is_own
                            }, True))
                    else:
                        existing_r = prev_rep_map[nr_id]
                        if nr.get("created_iso") and existing_r.get("created_iso") != nr.get("created_iso"):
                            existing_r["created_iso"] = nr["created_iso"]
                            existing_r["display_time"] = nr.get("display_time") or existing_r.get("display_time", "")
                            changed = True
                        if nr.get("replied_to_id") and not existing_r.get("replied_to_id"):
                            existing_r["replied_to_id"] = nr["replied_to_id"]
                        existing_r["can_reply"] = True
                        if existing_r.get("author_name") in generic_names and nr.get("author_name") not in generic_names:
                            existing_r["author_name"] = nr["author_name"]
                            if nr.get("author_avatar"):
                                existing_r["author_avatar"] = nr["author_avatar"]
                            changed = True
                        if nr.get("is_liked") and not existing_r.get("is_liked"):
                            existing_r["is_liked"] = True
                        if nr.get("is_hidden") and not existing_r.get("is_hidden"):
                            existing_r["is_hidden"] = True

                if prev_c.get("dm_sent"):
                    fc["dm_sent"] = True
                if "is_liked" in prev_c and not fc.get("is_liked"):
                    fc["is_liked"] = prev_c["is_liked"]
                if "is_hidden" in prev_c and not fc.get("is_hidden"):
                    fc["is_hidden"] = prev_c["is_hidden"]
                fc["replies"] = merged_reps
                existing_comments_map[cid] = fc

        post_entry["comments"] = existing_comments_map
        if r_dict.get("permalink_url"):
            post_entry["post_permalink"] = r_dict["permalink_url"]
        if r_dict.get("caption") and r_dict["caption"] != "Previous Post":
            post_entry["post_caption"] = r_dict["caption"]

        if repair_unknown_authors_in_post_entry(post_entry, r_dict):
            changed = True

        if (force_unhide or (has_brand_new_activity and unhide_if_new)) and post_entry.get("notification_hidden"):
            post_entry["notification_hidden"] = False
            changed = True
            print(f"[🔔 NOTIFICATION RESTORED] New comment activity on '{post_entry['account_name']}'! Restoring notification card with full comment history.")

    # Fire all queued n8n notifications outside COMMENTS_STORE_LOCK so lock is never held during dispatch
    if notifications_to_fire and "_notify_n8n_new_comment" in globals():
        for notif_obj, is_bg_flag in notifications_to_fire:
            try:
                _notify_n8n_new_comment(r_dict, notif_obj, is_background_sync=is_bg_flag)
            except Exception:
                pass

    return changed


def sync_single_post_to_cloudinary(r_dict: Dict[str, Any], force_unhide: bool = False):
    try:
        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT comment_id FROM glennbot_seen_comments")).mappings().all()
            seen_ids = {str(r["comment_id"]) for r in seen_rows}

        rec_id = str(r_dict["id"])
        posts_store = CLOUDINARY_COMMENTS_STORE.setdefault("posts", {})
        p_entry = posts_store.get(rec_id) or {}
        del_cids = set(str(x) for x in (p_entry.get("deleted_comment_ids") or []))
        account_name = r_dict.get("account_name") or ""
        clean_user = (account_name.lstrip("@") if account_name and account_name.lower() != "tiktok" else "").strip()

        z_info = resolve_zernio_post_identifiers(r_dict, force=bool(force_unhide))
        z_acc_id = z_info["zernio_account_id"]
        ext_id = extract_external_post_id(r_dict)

        cand_ids = [
            z_info.get("inbox_post_id"),
            z_info.get("inbox_plat_id"),
            z_info["platform_post_id"],
            z_info["zernio_post_id"],
            ext_id
        ]
        comms = fetch_zernio_comments_for_post(
            cand_ids,
            z_acc_id,
            r_dict,
            seen_ids,
            del_cids,
            clean_user=clean_user,
            preferred_api_key=z_info.get("zernio_api_key", "")
        )
        changed = False
        if comms is not None:
            if update_cloudinary_store_for_post(r_dict, comms, unhide_if_new=True, force_unhide=force_unhide):
                changed = True
        if p_entry and repair_unknown_authors_in_post_entry(p_entry, r_dict):
            changed = True
        if changed:
            save_comments_store_async()
    except Exception as e:
        print(f"[⚠️ SINGLE POST SYNC ERROR]: {e}")


def _ensure_recent_youtube_channel_videos_registered(connected_items: List[Dict[str, Any]], max_per_channel: int = 6) -> None:
    yt_accounts = [a for a in (connected_items or []) if (a.get("platform") or "").strip().lower() == "youtube"]
    if not yt_accounts:
        return
    try:
        with db_engine.connect() as conn:
            yt_rows = conn.execute(text("""
                SELECT id, page_id, account_name, caption, status, status_message, external_post_id, permalink_url
                FROM glennbot_scheduled_posts
                WHERE LOWER(platform) = 'youtube'
                ORDER BY scheduled_time DESC
                LIMIT 50
            """)).mappings().all()
        known_yt_vids: set = set()
        unlinked_yt_rows: List[Dict[str, Any]] = []
        for yr in yt_rows:
            yd = dict(yr)
            for k_id in extract_all_known_ids_for_row(yd):
                if re.match(r"^[A-Za-z0-9_-]{11}$", str(k_id)):
                    known_yt_vids.add(str(k_id))
            if not any(re.match(r"^[A-Za-z0-9_-]{11}$", str(k)) for k in extract_all_known_ids_for_row(yd)):
                unlinked_yt_rows.append(yd)

        for acc in yt_accounts:
            aid = str(acc.get("account_id") or "").strip()
            aname = str(acc.get("account_name") or "").strip()
            uname = str(acc.get("username") or "").strip()
            recent_vids = fetch_youtube_channel_recent_videos(page_id=aid, acc_name=aname, username=uname, max_items=max_per_channel)
            for rv in recent_vids:
                vid = str(rv.get("video_id") or "").strip()
                if not vid or vid in known_yt_vids:
                    continue
                rv_title_clean = _strip_invisible_guard_chars(rv.get("title") or "").lower()
                matched_existing_row = None
                for u_row in unlinked_yt_rows:
                    u_cap_clean = _strip_invisible_guard_chars(u_row.get("caption") or "").lower()
                    u_first = next((ln.strip() for ln in u_cap_clean.splitlines() if ln.strip()), "")
                    if u_first and rv_title_clean and (u_first in rv_title_clean or rv_title_clean in u_first):
                        matched_existing_row = u_row
                        break
                if matched_existing_row:
                    rec_id_u = str(matched_existing_row["id"])
                    cur_s_msg = str(matched_existing_row.get("status_message") or "").strip()
                    if f"Platform ID: {vid}" not in cur_s_msg:
                        cur_s_msg = f"{cur_s_msg} | Platform ID: {vid}".strip(" |")
                    update_post_status(
                        rec_id_u,
                        "published",
                        cur_s_msg,
                        external_post_id=vid,
                        permalink_url=rv.get("permalink") or f"https://www.youtube.com/watch?v={vid}"
                    )
                    known_yt_vids.add(vid)
                else:
                    ensure_external_post_record_in_db(
                        platform="youtube",
                        plat_post_id=vid,
                        z_post_id="",
                        account_id=aid,
                        account_name=aname,
                        caption=rv.get("title") or "YouTube Video",
                        permalink=rv.get("permalink") or f"https://www.youtube.com/watch?v={vid}",
                        preview_url=rv.get("preview_url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                        connected_items=connected_items
                    )
                    known_yt_vids.add(vid)
    except Exception as e:
        print(f"[⚠️ YOUTUBE CHANNEL VIDEO AUTO-REGISTER WARNING]: {e}")


def sync_all_connected_posts_to_cloudinary(force_refresh: bool = False) -> bool:
    if not get_all_zernio_keys():
        return False

    try:
        connected_items = refresh_connected_accounts_cache(force=force_refresh)
        fetch_zernio_connected_accounts(force=force_refresh)
        get_zernio_posts_map(force=force_refresh)
        commented_posts = get_zernio_commented_posts_list(force=force_refresh)
        sync_pending_scheduled_posts_with_zernio()
        _ensure_recent_youtube_channel_videos_registered(connected_items, max_per_channel=6)

        try:
            for cp in (commented_posts or []):
                if not isinstance(cp, dict):
                    continue
                cp_plat = (cp.get("platform") or "").strip().lower()
                cp_plat_id = str(cp.get("platformPostId") or cp.get("id") or cp.get("_id") or "").strip()
                if cp_plat in ("youtube", "tiktok", "facebook", "instagram") and cp_plat_id:
                    cp_acc_raw = cp.get("accountId") or cp.get("account")
                    cp_acc_id = ""
                    cp_acc_name = str(cp.get("accountName") or cp.get("pageName") or "").strip()
                    if isinstance(cp_acc_raw, dict):
                        cp_acc_id = str(cp_acc_raw.get("_id") or cp_acc_raw.get("id") or cp_acc_raw.get("accountId") or "").strip()
                        if not cp_acc_name:
                            cp_acc_name = str(cp_acc_raw.get("displayName") or cp_acc_raw.get("name") or cp_acc_raw.get("username") or "").strip()
                    elif cp_acc_raw:
                        cp_acc_id = str(cp_acc_raw).strip()
                    ensure_external_post_record_in_db(
                        platform=cp_plat,
                        plat_post_id=cp_plat_id,
                        z_post_id=str(cp.get("id") or cp.get("_id") or ""),
                        account_id=cp_acc_id,
                        account_name=cp_acc_name,
                        caption=str(cp.get("content") or cp.get("caption") or ""),
                        permalink=str(cp.get("permalink") or cp.get("platformPostUrl") or ""),
                        preview_url=str(cp.get("imageUrl") or cp.get("thumbnailUrl") or ""),
                        connected_items=connected_items
                    )
        except Exception:
            pass

        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT comment_id FROM glennbot_seen_comments")).mappings().all()
            seen_ids = {str(r["comment_id"]) for r in seen_rows}

            post_rows = conn.execute(text("""
                SELECT id, platform, page_id, account_name, post_type, caption,
                       media_preview_url, scheduled_time, status, status_message,
                       external_post_id, permalink_url
                FROM glennbot_scheduled_posts
                WHERE status = 'published'
                  AND platform IN ('facebook', 'instagram', 'tiktok', 'youtube')
                ORDER BY scheduled_time DESC
                LIMIT 60
            """)).mappings().all()

        valid_post_dicts = [dict(r) for r in post_rows if is_post_account_connected(dict(r), connected_items)]
        posts_store = CLOUDINARY_COMMENTS_STORE.setdefault("posts", {})
        any_store_change = False

        claimed_ids: set = set()
        resolved_plans = []
        for vd in valid_post_dicts:
            z_info = resolve_zernio_post_identifiers(vd, force=False, claimed_ids=claimed_ids)
            resolved_plans.append((vd, z_info))

        def _fetch_for_plan(plan_tuple):
            r_dict, z_info = plan_tuple
            rec_id = str(r_dict["id"])
            p_entry = posts_store.get(rec_id) or {}
            del_cids = set(str(x) for x in (p_entry.get("deleted_comment_ids") or []))
            account_name = r_dict.get("account_name") or ""
            clean_user = (account_name.lstrip("@") if account_name and account_name.lower() != "tiktok" else "").strip()

            z_acc_id = z_info["zernio_account_id"]
            ext_id = extract_external_post_id(r_dict)

            discovered_plat_id = z_info["platform_post_id"] or z_info.get("inbox_plat_id") or z_info.get("inbox_post_id")
            status_msg = r_dict.get("status_message") or ""
            if discovered_plat_id and "Platform ID:" not in status_msg:
                new_status_msg = f"{status_msg} | Platform ID: {discovered_plat_id}".strip(" |")
                update_post_status(
                    rec_id,
                    r_dict["status"],
                    new_status_msg,
                    external_post_id=discovered_plat_id,
                    permalink_url=z_info["permalink_url"] or r_dict.get("permalink_url") or None
                )

            cand_ids = [
                z_info.get("inbox_post_id"),
                z_info.get("inbox_plat_id"),
                z_info["platform_post_id"],
                z_info["zernio_post_id"],
                ext_id
            ]
            comms = fetch_zernio_comments_for_post(
                cand_ids,
                z_acc_id,
                r_dict,
                seen_ids,
                del_cids,
                clean_user=clean_user,
                preferred_api_key=z_info.get("zernio_api_key", "")
            )
            return r_dict, comms or []

        if resolved_plans:
            max_workers = min(6, len(resolved_plans))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_fetch_for_plan, plan) for plan in resolved_plans]
                for fut in as_completed(futures):
                    try:
                        r_dict, p_comms = fut.result()
                        if update_cloudinary_store_for_post(r_dict, p_comms, unhide_if_new=True):
                            any_store_change = True
                    except Exception as e:
                        print(f"[⚠️ POST SYNC WARNING]: {e}")

        if any_store_change or force_refresh:
            save_comments_store_async()
        return True
    except Exception as e:
        print(f"[❌ SYNC TO CLOUDINARY ERROR]: {e}")
        return False


# ==============================================================================
# --- DELETE / CLEAR COMMENT NOTIFICATIONS ENDPOINT ---
# ==============================================================================

class DismissCommentsPayload(BaseModel):
    record_id: Optional[str] = ""
    comment_ids: Optional[List[str]] = []
    clear_all: Optional[bool] = False
    single_comment: Optional[bool] = False

@router.post("/api/comments/dismiss")
def dismiss_or_clear_comment_notifications(payload: DismissCommentsPayload):
    try:
        ids_to_mark_seen = set(str(cid) for cid in (payload.comment_ids or []) if cid)
        rec_id = (payload.record_id or "").strip()
        posts_store = CLOUDINARY_COMMENTS_STORE.setdefault("posts", {})

        if payload.clear_all:
            for p_key, p_entry in posts_store.items():
                p_entry["notification_hidden"] = True
                for c_key, c_obj in (p_entry.get("comments") or {}).items():
                    ids_to_mark_seen.add(str(c_key))
                    for rep in (c_obj.get("replies") or []):
                        if rep.get("id"):
                            ids_to_mark_seen.add(str(rep["id"]))
        elif payload.single_comment and ids_to_mark_seen:
            for p_key, p_entry in posts_store.items():
                if rec_id and p_key != rec_id:
                    continue
                c_map = p_entry.get("comments") or {}
                del_list = list(p_entry.get("deleted_comment_ids") or [])
                for target_cid in ids_to_mark_seen:
                    c_map.pop(target_cid, None)
                    if target_cid not in del_list:
                        del_list.append(target_cid)
                p_entry["deleted_comment_ids"] = del_list
        elif rec_id:
            p_entry = posts_store.get(rec_id)
            if p_entry:
                p_entry["notification_hidden"] = True
                for c_key, c_obj in (p_entry.get("comments") or {}).items():
                    ids_to_mark_seen.add(str(c_key))
                    for rep in (c_obj.get("replies") or []):
                        if rep.get("id"):
                            ids_to_mark_seen.add(str(rep["id"]))

        save_comments_store_async()

        if ids_to_mark_seen:
            with db_engine.begin() as conn:
                for cid in ids_to_mark_seen:
                    conn.execute(
                        text("""
                            INSERT INTO glennbot_seen_comments (comment_id, record_id, platform)
                            VALUES (:cid, :rid, 'zernio')
                            ON CONFLICT (comment_id) DO NOTHING
                        """),
                        {"cid": cid, "rid": rec_id}
                    )

        return {"status": "success", "dismissed_count": len(ids_to_mark_seen)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


