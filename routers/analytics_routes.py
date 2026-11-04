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
# --- SOCIAL MEDIA ANALYTICS ENGINE (ZERNIO /v1/analytics + PER-PAGE METRICS) ---
# ==============================================================================



def _safe_int(val: Any) -> int:
    if val is None or isinstance(val, bool):
        return 0
    if isinstance(val, (int, float)):
        return max(0, int(val))
    s = str(val).strip().replace(",", "")
    if not s:
        return 0
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmMbB])?$", s)
    if m:
        num = float(m.group(1))
        suf = (m.group(2) or "").upper()
        if suf == "K":
            num *= 1_000
        elif suf == "M":
            num *= 1_000_000
        elif suf == "B":
            num *= 1_000_000_000
        return max(0, int(num))
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits.isdigit() else 0


def _safe_float(val: Any) -> float:
    if val is None or isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    s = str(val).strip().replace("%", "").replace(",", "")
    try:
        return max(0.0, float(s))
    except Exception:
        return 0.0


def _extract_single_dict_metrics(raw_obj: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_obj, dict):
        return {}
    ana = (
        raw_obj.get("analytics")
        or raw_obj.get("metrics")
        or raw_obj.get("insights")
        or raw_obj.get("stats")
        or raw_obj.get("statistics")
        or {}
    )
    if not isinstance(ana, dict):
        ana = {}

    views = max(
        _safe_int(ana.get("views")),
        _safe_int(ana.get("videoViews")),
        _safe_int(ana.get("video_views")),
        _safe_int(ana.get("playCount")),
        _safe_int(ana.get("play_count")),
        _safe_int(raw_obj.get("views")),
        _safe_int(raw_obj.get("videoViews")),
        _safe_int(raw_obj.get("playCount"))
    )
    impressions = max(
        _safe_int(ana.get("impressions")),
        _safe_int(ana.get("impressionCount")),
        _safe_int(raw_obj.get("impressions")),
        views
    )
    reach = max(
        _safe_int(ana.get("reach")),
        _safe_int(ana.get("uniqueViews")),
        _safe_int(raw_obj.get("reach")),
        impressions
    )
    if views == 0 and impressions > 0:
        views = impressions

    likes = max(
        _safe_int(ana.get("likes")),
        _safe_int(ana.get("likeCount")),
        _safe_int(ana.get("like_count")),
        _safe_int(ana.get("reactions")),
        _safe_int(ana.get("diggCount")),
        _safe_int(raw_obj.get("likes")),
        _safe_int(raw_obj.get("likeCount")),
        _safe_int(raw_obj.get("like_count"))
    )
    comments = max(
        _safe_int(ana.get("comments")),
        _safe_int(ana.get("commentCount")),
        _safe_int(ana.get("comment_count")),
        _safe_int(ana.get("replies")),
        _safe_int(raw_obj.get("comments")),
        _safe_int(raw_obj.get("commentCount")),
        _safe_int(raw_obj.get("comment_count"))
    )
    shares = max(
        _safe_int(ana.get("shares")),
        _safe_int(ana.get("shareCount")),
        _safe_int(ana.get("share_count")),
        _safe_int(ana.get("reposts")),
        _safe_int(raw_obj.get("shares")),
        _safe_int(raw_obj.get("shareCount"))
    )
    saves = max(
        _safe_int(ana.get("saves")),
        _safe_int(ana.get("saveCount")),
        _safe_int(ana.get("bookmarks")),
        _safe_int(ana.get("collectCount")),
        _safe_int(raw_obj.get("saves")),
        _safe_int(raw_obj.get("saveCount"))
    )
    clicks = max(
        _safe_int(ana.get("clicks")),
        _safe_int(ana.get("linkClicks")),
        _safe_int(raw_obj.get("clicks"))
    )
    eng_rate = max(
        _safe_float(ana.get("engagementRate")),
        _safe_float(ana.get("engagement_rate")),
        _safe_float(raw_obj.get("engagementRate"))
    )
    return {
        "views": views,
        "impressions": impressions,
        "reach": reach,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "saves": saves,
        "clicks": clicks,
        "engagement_rate": round(eng_rate, 2)
    }


def _extract_metrics_dict(raw_obj: Dict[str, Any], target_platform: str = "") -> Dict[str, Any]:
    if not isinstance(raw_obj, dict):
        return {
            "views": 0, "impressions": 0, "reach": 0, "likes": 0,
            "comments": 0, "shares": 0, "saves": 0, "clicks": 0, "engagement_rate": 0.0
        }
    base = _extract_single_dict_metrics(raw_obj)
    t_plat = (target_platform or "").strip().lower()
    platforms_list = raw_obj.get("platforms")
    if isinstance(platforms_list, list) and platforms_list:
        for pl in platforms_list:
            if not isinstance(pl, dict):
                continue
            pl_plat = (pl.get("platform") or "").strip().lower()
            if t_plat and pl_plat and pl_plat != t_plat:
                continue
            pl_m = _extract_single_dict_metrics(pl)
            for k in ("views", "impressions", "reach", "likes", "comments", "shares", "saves", "clicks"):
                base[k] = max(base.get(k, 0), pl_m.get(k, 0))
            base["engagement_rate"] = max(base.get("engagement_rate", 0.0), pl_m.get("engagement_rate", 0.0))
    return base


def _fetch_youtube_public_video_metrics(video_id: str, allow_network: bool = True) -> Dict[str, int]:
    vid = str(video_id or "").strip()
    if not re.match(r"^[A-Za-z0-9_-]{11}$", vid):
        return {"views": 0, "likes": 0}
    now_ts = time.time()
    cached = ANALYTICS_CACHE["yt_video_stats"].get(vid)
    if cached and (now_ts - cached.get("ts", 0) < 1800):
        return {"views": cached.get("views", 0), "likes": cached.get("likes", 0)}
    if not allow_network:
        return {"views": (cached or {}).get("views", 0), "likes": (cached or {}).get("likes", 0)}
    try:
        resp = HTTP_SESSION.get(
            f"https://www.youtube.com/watch?v={vid}&hl=en",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            },
            timeout=4
        )
        if resp.status_code == 200 and resp.text:
            html = resp.text
            views = 0
            likes = 0
            m_v = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
            if m_v:
                views = _safe_int(m_v.group(1))
            m_l = re.search(r'"likeCount"\s*:\s*"?(\d+)"?', html)
            if m_l:
                likes = _safe_int(m_l.group(1))
            if likes == 0:
                m_l2 = re.search(r'"label"\s*:\s*"([\d,]+)\s+likes"', html, re.IGNORECASE)
                if m_l2:
                    likes = _safe_int(m_l2.group(1))
            ANALYTICS_CACHE["yt_video_stats"][vid] = {"views": views, "likes": likes, "ts": now_ts}
            return {"views": views, "likes": likes}
    except Exception:
        pass
    return {"views": (cached or {}).get("views", 0), "likes": (cached or {}).get("likes", 0)}


def _extract_yt_video_id_from_candidates(candidates: List[Any]) -> str:
    for cand_v in candidates:
        s = str(cand_v or "").strip()
        if not s:
            continue
        m_yt = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})", s)
        if m_yt:
            return m_yt.group(1)
        if re.match(r"^[A-Za-z0-9_-]{11}$", s):
            return s
    return ""


def _extract_post_candidate_ids_fast(
    r_dict: Dict[str, Any],
    z_posts_map: Dict[str, Dict[str, Any]],
    inbox_by_post_id: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """O(1) in-memory identifier & permalink resolver for Analytics (avoids per-row network/loop overhead)."""
    platform = (r_dict.get("platform") or "").strip().lower()
    ext_id = extract_external_post_id(r_dict)
    status_msg = (r_dict.get("status_message") or "").strip()
    permalink = (r_dict.get("permalink_url") or "").strip()

    z_post_id = ""
    plat_post_id = ""

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

    matched_z_post = None
    for lookup_id in (ext_id, z_post_id, plat_post_id):
        if lookup_id and lookup_id != "OK" and lookup_id in z_posts_map:
            matched_z_post = z_posts_map[lookup_id]
            break

    if matched_z_post and isinstance(matched_z_post, dict):
        z_post_id = str(matched_z_post.get("_id") or matched_z_post.get("id") or z_post_id).strip()
        if not plat_post_id and matched_z_post.get("platformPostId"):
            plat_post_id = str(matched_z_post["platformPostId"]).strip()
        if not permalink and matched_z_post.get("platformPostUrl"):
            permalink = str(matched_z_post["platformPostUrl"]).strip()

        for pl in (matched_z_post.get("platforms") or []):
            if not isinstance(pl, dict):
                continue
            pl_plat = (pl.get("platform") or "").strip().lower()
            if pl_plat and pl_plat != platform:
                continue
            if not plat_post_id and pl.get("platformPostId"):
                plat_post_id = str(pl["platformPostId"]).strip()
            if not permalink and pl.get("platformPostUrl"):
                permalink = str(pl["platformPostUrl"]).strip()

    cand_ids = []
    for raw_cid in (z_post_id, plat_post_id, ext_id):
        s_cid = str(raw_cid or "").strip()
        if s_cid and s_cid != "OK" and s_cid not in cand_ids:
            cand_ids.append(s_cid)
            if "_" in s_cid:
                suf = s_cid.split("_")[-1].strip()
                if suf and suf not in cand_ids:
                    cand_ids.append(suf)

    for cid_x in list(cand_ids):
        cp_match = inbox_by_post_id.get(cid_x)
        if isinstance(cp_match, dict):
            cp_id = str(cp_match.get("id") or cp_match.get("_id") or cp_match.get("postId") or "").strip()
            cp_plat_id = str(cp_match.get("platformPostId") or "").strip()
            for extra_id in (cp_id, cp_plat_id):
                if extra_id and extra_id not in cand_ids:
                    cand_ids.append(extra_id)
            if not permalink and (cp_match.get("platformPostUrl") or cp_match.get("permalink")):
                permalink = str(cp_match.get("platformPostUrl") or cp_match.get("permalink")).strip()
            break

    return {
        "cand_ids": cand_ids,
        "permalink_url": permalink,
        "matched_z_post": matched_z_post
    }


def _sync_external_analytics_snapshot(force: bool = False) -> None:
    """Fetches all Zernio analytics, follower stats, accounts, posts, and comments in parallel."""
    now_ts = time.time()
    snap = ANALYTICS_CACHE["ext_snapshot"]
    if not force and snap["ts"] > 0 and (now_ts - snap["ts"] < 180):
        return

    with ANALYTICS_SYNC_LOCK:
        now_ts = time.time()
        if not force and snap["ts"] > 0 and (now_ts - snap["ts"] < 180):
            return
        snap["is_syncing"] = True

    try:
        manila_tz = pytz.timezone("Asia/Manila")
        now_m = datetime.now(manila_tz)
        from_date_str = (now_m - timedelta(days=365)).strftime("%Y-%m-%d")
        to_date_str = now_m.strftime("%Y-%m-%d")

        all_keys = get_all_zernio_keys()
        analytics_posts_raw: List[Dict[str, Any]] = []
        follower_stats_by_acc: Dict[str, Dict[str, Any]] = {}
        api_permissions_notes: List[str] = []

        def _fetch_analytics_for_key(k: str):
            k_posts: List[Dict[str, Any]] = []
            k_note = ""
            try:
                resp = HTTP_SESSION.get(
                    f"{ZERNIO_BASE_URL}/analytics",
                    params={"fromDate": from_date_str, "toDate": to_date_str, "limit": 100},
                    headers=get_zernio_headers(k),
                    timeout=8
                )
                if resp.status_code == 200 and resp.text:
                    payload = resp.json()
                    raw_list = []
                    if isinstance(payload, dict):
                        raw_list = (
                            payload.get("posts")
                            or payload.get("data")
                            or payload.get("items")
                            or payload.get("analytics")
                            or []
                        )
                        if isinstance(raw_list, dict):
                            raw_list = raw_list.get("posts") or raw_list.get("items") or []
                    elif isinstance(payload, list):
                        raw_list = payload
                    if isinstance(raw_list, list):
                        for item in raw_list:
                            if isinstance(item, dict):
                                icopy = dict(item)
                                icopy["_zernio_api_key"] = k
                                k_posts.append(icopy)
                elif resp.status_code == 402:
                    k_note = "Zernio Analytics add-on not active on one or more API keys — combining live External API post, comment, and platform metrics automatically."
            except Exception:
                pass
            return k_posts, k_note

        def _fetch_followers_for_key(k: str):
            k_followers: Dict[str, Dict[str, Any]] = {}
            try:
                f_resp = HTTP_SESSION.get(
                    f"{ZERNIO_BASE_URL}/accounts/follower-stats",
                    params={"fromDate": from_date_str, "toDate": to_date_str, "granularity": "daily"},
                    headers=get_zernio_headers(k),
                    timeout=8
                )
                if f_resp.status_code == 200 and f_resp.text:
                    f_payload = f_resp.json()
                    f_list = extract_list_from_api_payload(f_payload) or []
                    for f_item in f_list:
                        if not isinstance(f_item, dict):
                            continue
                        aid = str(f_item.get("accountId") or f_item.get("_id") or f_item.get("id") or "").strip()
                        uname = (f_item.get("username") or "").strip().lstrip("@").lower()
                        cur_f = _safe_int(f_item.get("currentFollowers") or f_item.get("followers") or f_item.get("followerCount"))
                        net_g = int(f_item.get("netGrowth") or 0) if isinstance(f_item.get("netGrowth"), (int, float)) else 0
                        stat_obj = {
                            "followers": cur_f,
                            "net_growth": net_g,
                            "history": f_item.get("history") if isinstance(f_item.get("history"), list) else []
                        }
                        if aid:
                            k_followers[aid] = stat_obj
                        if uname:
                            k_followers[f"uname:{uname}"] = stat_obj
            except Exception:
                pass
            return k_followers

        # Execute all external cache refreshes & Zernio analytics calls concurrently in ONE pool
        max_workers = max(4, len(all_keys) * 2 + 4)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_conn = ex.submit(refresh_connected_accounts_cache, force)
            fut_z_acc = ex.submit(fetch_zernio_connected_accounts, force) if all_keys else None
            fut_z_posts = ex.submit(get_zernio_posts_map, force) if all_keys else None
            fut_z_inbox = ex.submit(get_zernio_commented_posts_list, force) if all_keys else None

            ana_futures = [ex.submit(_fetch_analytics_for_key, k) for k in all_keys]
            fol_futures = [ex.submit(_fetch_followers_for_key, k) for k in all_keys]

            for fut in as_completed(ana_futures):
                try:
                    k_posts, k_note = fut.result()
                    analytics_posts_raw.extend(k_posts)
                    if k_note and k_note not in api_permissions_notes:
                        api_permissions_notes.append(k_note)
                except Exception:
                    pass

            for fut in as_completed(fol_futures):
                try:
                    follower_stats_by_acc.update(fut.result())
                except Exception:
                    pass

            for helper_fut in (fut_conn, fut_z_acc, fut_z_posts, fut_z_inbox):
                if helper_fut is not None:
                    try:
                        helper_fut.result()
                    except Exception:
                        pass

        snap["analytics_posts"] = analytics_posts_raw
        snap["follower_stats"] = follower_stats_by_acc
        snap["permissions_notes"] = api_permissions_notes
        snap["ts"] = time.time()
        # Clear computed period cache so next read uses the fresh external snapshot
        ANALYTICS_CACHE["by_period"].clear()
    finally:
        snap["is_syncing"] = False


def _trigger_background_analytics_sync(force: bool = False) -> None:
    snap = ANALYTICS_CACHE["ext_snapshot"]
    if snap.get("is_syncing"):
        return

    def _bg_worker():
        try:
            _sync_external_analytics_snapshot(force=force)
            for p_code in ("90d", "30d", "7d", "all"):
                try:
                    get_social_media_analytics(period=p_code, force=False)
                except Exception:
                    pass
        except Exception:
            pass

    threading.Thread(target=_bg_worker, daemon=True).start()


@router.get("/api/analytics")
def get_social_media_analytics(period: str = "90d", force: bool = False):
    manila_tz = pytz.timezone("Asia/Manila")
    now_m = datetime.now(manila_tz)
    now_ts = time.time()

    clean_period = (period or "90d").strip().lower()
    if clean_period not in ("7d", "30d", "90d", "all"):
        clean_period = "90d"

    snap = ANALYTICS_CACHE["ext_snapshot"]

    # 1. If user clicked "Refresh Data" (force=True), run parallel external sync now (~2s)
    if force:
        _sync_external_analytics_snapshot(force=True)
        now_ts = time.time()
    else:
        # 2. Fast-path: return cached period payload immediately (< 5ms) if available
        cached_entry = ANALYTICS_CACHE["by_period"].get(clean_period)
        if cached_entry and (now_ts - cached_entry.get("ts", 0) < 180):
            payload_out = dict(cached_entry["payload"])
            payload_out["syncing_external"] = bool(snap.get("is_syncing", False))
            return payload_out

        # 3. Stale-While-Revalidate: if external snapshot is cold or > 180s old, refresh in background
        if snap["ts"] == 0.0 or (now_ts - snap["ts"] >= 180):
            _trigger_background_analytics_sync(force=(snap["ts"] == 0.0))

    allow_blocking_network = bool(force or snap["ts"] > 0.0)

    days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365}
    days_back = days_map.get(clean_period, 90)
    cutoff_dt = now_m - timedelta(days=days_back)
    from_date_str = cutoff_dt.strftime("%Y-%m-%d")
    to_date_str = now_m.strftime("%Y-%m-%d")

    # Read from warm in-memory caches without blocking on sequential HTTP requests
    connected_items = CONNECTED_ACCOUNTS_CACHE.get("items") or refresh_connected_accounts_cache(force=False)
    z_accounts = ZERNIO_ACCOUNTS_CACHE.get("accounts") or []
    z_posts_map = ZERNIO_POSTS_CACHE.get("posts_map") or {}
    z_commented_posts = ZERNIO_COMMENTED_POSTS_CACHE.get("items") or []

    analytics_posts_raw: List[Dict[str, Any]] = list(snap.get("analytics_posts") or [])
    follower_stats_by_acc: Dict[str, Dict[str, Any]] = dict(snap.get("follower_stats") or {})
    api_permissions_notes: List[str] = list(snap.get("permissions_notes") or [])

    # Build lookup of connected pages in GlennBot
    pages_map: Dict[str, Dict[str, Any]] = {}
    alias_to_page_key: Dict[str, str] = {}

    for item in connected_items:
        plat = (item.get("platform") or "").strip().lower()
        acc_id = str(item.get("account_id") or "").strip()
        if not plat or not acc_id:
            continue
        acc_name = (item.get("account_name") or acc_id).strip()
        uname = (item.get("username") or "").strip().lstrip("@")
        avatar = (item.get("avatar_url") or "").strip()
        page_key = f"{plat}_{acc_id}"

        raw_tok = (item.get("access_token") or "").strip()
        bound_key = ""
        for prefix in ("EXTERNAL_API_MANAGED:", "ZERNIO_MANAGED:"):
            if raw_tok.startswith(prefix):
                bound_key = raw_tok.split(prefix, 1)[1].strip()
                break
        if not bound_key and z_accounts:
            bound_key = get_zernio_key_for_account(acc_id, account_name=acc_name, platform=plat)

        z_acc_followers = 0
        z_acc_growth = 0
        z_internal_ids = {acc_id}
        for za in z_accounts:
            if not isinstance(za, dict):
                continue
            za_plat = (za.get("platform") or "").strip().lower()
            if za_plat != plat:
                continue
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
            za_uname = (za.get("username") or "").strip().lstrip("@")
            za_dname = (za.get("displayName") or za.get("name") or "").strip()

            if (
                acc_id in (za_id, za_plat_id)
                or (uname and za_uname and uname.lower() == za_uname.lower())
                or (acc_name and za_dname and acc_name.lower() == za_dname.lower())
            ):
                if za_id:
                    z_internal_ids.add(za_id)
                if za_plat_id:
                    z_internal_ids.add(za_plat_id)
                if not avatar:
                    avatar = str(za.get("avatarUrl") or za.get("profilePictureUrl") or "").strip()
                if not uname and za_uname:
                    uname = za_uname
                z_acc_followers = max(
                    z_acc_followers,
                    _safe_int(za.get("followersCount")),
                    _safe_int(za.get("followerCount")),
                    _safe_int(za.get("followers")),
                    _safe_int(za.get("subscriberCount")),
                    _safe_int(za.get("fanCount")),
                    _safe_int((za.get("metrics") or {}).get("followers") if isinstance(za.get("metrics"), dict) else 0)
                )

        for zid in z_internal_ids:
            if zid in follower_stats_by_acc:
                f_stat = follower_stats_by_acc[zid]
                z_acc_followers = max(z_acc_followers, _safe_int(f_stat.get("followers")))
                z_acc_growth = f_stat.get("net_growth", 0)
                break
        if z_acc_followers == 0 and uname and f"uname:{uname.lower()}" in follower_stats_by_acc:
            f_stat = follower_stats_by_acc[f"uname:{uname.lower()}"]
            z_acc_followers = max(z_acc_followers, _safe_int(f_stat.get("followers")))
            z_acc_growth = f_stat.get("net_growth", 0)

        pages_map[page_key] = {
            "page_key": page_key,
            "account_id": acc_id,
            "platform": plat,
            "account_name": acc_name,
            "username": uname or acc_name,
            "avatar_url": avatar,
            "masked_key": _mask_api_key(bound_key) if bound_key else "Default API",
            "followers": z_acc_followers,
            "follower_growth": z_acc_growth,
            "published_posts_count": 0,
            "scheduled_waiting_count": 0,
            "views": 0,
            "impressions": 0,
            "reach": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "saves": 0,
            "clicks": 0,
            "messages_count": 0,
            "unread_messages_count": 0,
            "unread_comments_count": 0,
            "total_engagement": 0,
            "engagement_rate": 0.0,
            "top_post": None,
            "_internal_ids": list(z_internal_ids)
        }

        for zid in z_internal_ids:
            alias_to_page_key[f"{plat}:{zid}"] = page_key
            alias_to_page_key[zid] = page_key
        if uname:
            alias_to_page_key[f"{plat}:name:{uname.lower()}"] = page_key
        if acc_name:
            alias_to_page_key[f"{plat}:name:{acc_name.strip().lstrip('@').lower()}"] = page_key

    def _resolve_page_key(plat_val: str, acc_id_val: str, acc_name_val: str = "") -> Optional[str]:
        p_clean = (plat_val or "").strip().lower()
        a_clean = str(acc_id_val or "").strip()
        n_clean = (acc_name_val or "").strip().lstrip("@").lower()
        if p_clean and a_clean and f"{p_clean}:{a_clean}" in alias_to_page_key:
            return alias_to_page_key[f"{p_clean}:{a_clean}"]
        if a_clean and a_clean in alias_to_page_key:
            pk = alias_to_page_key[a_clean]
            if not p_clean or pages_map[pk]["platform"] == p_clean:
                return pk
        if p_clean and n_clean:
            if f"{p_clean}:name:{n_clean}" in alias_to_page_key:
                return alias_to_page_key[f"{p_clean}:name:{n_clean}"]
            for pk, p_obj in pages_map.items():
                if p_obj["platform"] != p_clean:
                    continue
                p_dname = p_obj["account_name"].strip().lstrip("@").lower()
                p_uname = p_obj["username"].strip().lstrip("@").lower()
                if n_clean in (p_dname, p_uname) or (p_dname and p_dname in n_clean) or (p_uname and f"@{p_uname}" in n_clean):
                    return pk
        if p_clean:
            plat_pks = [pk for pk, p_obj in pages_map.items() if p_obj["platform"] == p_clean]
            if len(plat_pks) == 1:
                return plat_pks[0]
        return None

    # Count direct messages per connected page from CLOUDINARY_MESSAGES_STORE
    convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
    for c_entry in convs_store.values():
        if not isinstance(c_entry, dict):
            continue
        c_plat = (c_entry.get("platform") or "").strip().lower()
        c_aid = str(c_entry.get("account_id") or "").strip()
        c_aname = (c_entry.get("account_name") or "").strip()
        pk = _resolve_page_key(c_plat, c_aid, c_aname)
        if pk and pk in pages_map:
            pages_map[pk]["messages_count"] += 1
            if not c_entry.get("is_read", True):
                pages_map[pk]["unread_messages_count"] += 1

    # Index Zernio /v1/analytics items and /v1/inbox/comments items by post ID in O(1)
    analytics_by_post_id: Dict[str, Dict[str, Any]] = {}
    for a_item in analytics_posts_raw:
        if not isinstance(a_item, dict):
            continue
        for id_k in ("_id", "id", "postId", "platformPostId", "externalPostId"):
            pid_val = str(a_item.get(id_k) or "").strip()
            if pid_val:
                analytics_by_post_id[pid_val] = a_item
                if "_" in pid_val:
                    analytics_by_post_id[pid_val.split("_")[-1]] = a_item
        for pl in (a_item.get("platforms") or []):
            if isinstance(pl, dict):
                pl_pid = str(pl.get("platformPostId") or pl.get("id") or "").strip()
                if pl_pid:
                    analytics_by_post_id[pl_pid] = a_item
                    if "_" in pl_pid:
                        analytics_by_post_id[pl_pid.split("_")[-1]] = a_item

    inbox_by_post_id: Dict[str, Dict[str, Any]] = {}
    for cp in z_commented_posts:
        if not isinstance(cp, dict):
            continue
        for id_k in ("id", "_id", "postId", "platformPostId"):
            pid_val = str(cp.get(id_k) or "").strip()
            if pid_val:
                inbox_by_post_id[pid_val] = cp
                if "_" in pid_val:
                    inbox_by_post_id[pid_val.split("_")[-1]] = cp

    # Collect local comments & likes counts per post record_id from CLOUDINARY_COMMENTS_STORE
    comments_store_posts = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
    seen_comment_ids = set(CLOUDINARY_COMMENTS_STORE.get("seen_ids") or [])
    local_post_comment_stats: Dict[str, Dict[str, int]] = {}

    for rec_id_k, p_store_entry in comments_store_posts.items():
        if not isinstance(p_store_entry, dict):
            continue
        c_dict = p_store_entry.get("comments") or {}
        total_c_and_r = 0
        total_c_likes = 0
        unread_c = 0
        for cid_k, c_obj in c_dict.items():
            if not isinstance(c_obj, dict):
                continue
            total_c_and_r += 1
            total_c_likes += _safe_int(c_obj.get("like_count"))
            if not c_obj.get("is_own_comment") and cid_k not in seen_comment_ids:
                unread_c += 1
            for rep_obj in (c_obj.get("replies") or []):
                if isinstance(rep_obj, dict):
                    total_c_and_r += 1
                    total_c_likes += _safe_int(rep_obj.get("like_count"))
                    r_id = str(rep_obj.get("id") or "").strip()
                    if not rep_obj.get("is_own") and r_id and r_id not in seen_comment_ids:
                        unread_c += 1
        local_post_comment_stats[str(rec_id_k)] = {
            "comments_count": total_c_and_r,
            "comment_likes": total_c_likes,
            "unread_count": unread_c
        }

    unified_posts_by_key: Dict[str, Dict[str, Any]] = {}
    claimed_post_ids: set = set()
    pending_yt_lookups: List[Tuple[str, str]] = []  # (unified_post_key, yt_vid)

    # Pass 1: Load posts from Supabase glennbot_scheduled_posts
    try:
        with db_engine.connect() as conn:
            db_rows = conn.execute(text("""
                SELECT id, platform, page_id, account_name, post_type, caption,
                       media_preview_url, external_post_id, permalink_url,
                       scheduled_time, status, status_message
                FROM glennbot_scheduled_posts
                ORDER BY scheduled_time DESC
            """)).mappings().all()
    except Exception:
        db_rows = []

    for r in db_rows:
        r_dict = dict(r)
        plat = (r_dict.get("platform") or "").strip().lower()
        page_id = str(r_dict.get("page_id") or "").strip()
        acc_name = (r_dict.get("account_name") or "").strip()
        pk = _resolve_page_key(plat, page_id, acc_name)
        if not pk or pk not in pages_map:
            continue

        page_info = pages_map[pk]
        status_val = (r_dict.get("status") or "waiting").strip().lower()
        if status_val in ("waiting", "processing"):
            page_info["scheduled_waiting_count"] += 1
            continue
        if status_val != "published":
            continue

        raw_sched_dt = r_dict.get("scheduled_time")
        if raw_sched_dt:
            if hasattr(raw_sched_dt, "astimezone"):
                sched_dt = raw_sched_dt.astimezone(manila_tz)
            elif "_coerce_db_datetime" in globals():
                sched_dt = _coerce_db_datetime(raw_sched_dt, manila_tz) or now_m
            else:
                sched_dt = now_m
        else:
            sched_dt = now_m

        if clean_period != "all" and sched_dt < cutoff_dt:
            continue

        rec_id = str(r_dict.get("id") or "").strip()
        fast_info = _extract_post_candidate_ids_fast(r_dict, z_posts_map, inbox_by_post_id)
        cand_ids = fast_info["cand_ids"]

        matched_ana_obj = None
        for cid_x in cand_ids:
            if cid_x in analytics_by_post_id:
                matched_ana_obj = analytics_by_post_id[cid_x]
                break
        if not matched_ana_obj:
            matched_ana_obj = fast_info.get("matched_z_post")
            if not matched_ana_obj:
                for cid_x in cand_ids:
                    if cid_x in z_posts_map:
                        matched_ana_obj = z_posts_map[cid_x]
                        break

        matched_inbox_obj = None
        for cid_x in cand_ids:
            if cid_x in inbox_by_post_id:
                matched_inbox_obj = inbox_by_post_id[cid_x]
                break

        metrics = _extract_metrics_dict(matched_ana_obj or {}, target_platform=plat)
        inbox_metrics = _extract_metrics_dict(matched_inbox_obj or {}, target_platform=plat)
        local_stats = local_post_comment_stats.get(rec_id, {"comments_count": 0, "comment_likes": 0, "unread_count": 0})

        views = max(metrics.get("views", 0), inbox_metrics.get("views", 0))
        impressions = max(metrics.get("impressions", 0), inbox_metrics.get("impressions", 0), views)
        reach = max(metrics.get("reach", 0), inbox_metrics.get("reach", 0), impressions)
        likes = max(metrics.get("likes", 0), inbox_metrics.get("likes", 0))
        comments_cnt = max(
            metrics.get("comments", 0),
            inbox_metrics.get("comments", 0),
            local_stats.get("comments_count", 0)
        )
        shares = max(metrics.get("shares", 0), inbox_metrics.get("shares", 0))
        saves = max(metrics.get("saves", 0), inbox_metrics.get("saves", 0))
        clicks = max(metrics.get("clicks", 0), inbox_metrics.get("clicks", 0))

        permalink = (
            fast_info.get("permalink_url")
            or (matched_ana_obj or {}).get("platformPostUrl")
            or (matched_ana_obj or {}).get("permalink")
            or ""
        )

        if plat == "youtube" and (views == 0 or likes == 0):
            yt_vid = _extract_yt_video_id_from_candidates(cand_ids + [permalink])
            if yt_vid:
                # Check in-memory cache first; queue any missing video IDs for parallel batch fetch
                yt_cached = _fetch_youtube_public_video_metrics(yt_vid, allow_network=False)
                views = max(views, yt_cached.get("views", 0))
                impressions = max(impressions, views)
                reach = max(reach, views)
                likes = max(likes, yt_cached.get("likes", 0))
                if (views == 0 or likes == 0) and allow_blocking_network:
                    pending_yt_lookups.append((rec_id, yt_vid))

        eng_total = likes + comments_cnt + shares + saves + clicks
        eng_rate = metrics.get("engagement_rate", 0.0)
        if eng_rate <= 0.0 and impressions > 0 and eng_total > 0:
            eng_rate = round((eng_total / impressions) * 100.0, 2)

        for cid_x in cand_ids:
            claimed_post_ids.add(cid_x)
        claimed_post_ids.add(rec_id)

        preview_url = (
            r_dict.get("media_preview_url")
            or (matched_ana_obj or {}).get("thumbnailUrl")
            or (matched_ana_obj or {}).get("mediaUrl")
            or ""
        )

        unified_posts_by_key[rec_id] = {
            "id": rec_id,
            "page_key": pk,
            "platform": plat,
            "account_id": page_info["account_id"],
            "account_name": page_info["account_name"],
            "username": page_info["username"],
            "avatar_url": page_info["avatar_url"],
            "post_type": r_dict.get("post_type") or "reels",
            "caption": (r_dict.get("caption") or "").strip(),
            "media_preview_url": preview_url,
            "permalink_url": permalink,
            "published_iso": sched_dt.isoformat(),
            "display_date": sched_dt.strftime("%b %d, %Y • %I:%M %p"),
            "views": views,
            "impressions": impressions,
            "reach": reach,
            "likes": likes,
            "comments": comments_cnt,
            "unread_comments": local_stats.get("unread_count", 0),
            "shares": shares,
            "saves": saves,
            "clicks": clicks,
            "total_engagement": eng_total,
            "engagement_rate": eng_rate
        }

    # Pass 2: Include any additional published posts returned directly by Zernio /v1/analytics or /v1/posts
    extra_zernio_sources = list(analytics_posts_raw) + list(ZERNIO_POSTS_CACHE.get("posts_list") or []) + list(z_commented_posts)
    for z_post in extra_zernio_sources:
        if not isinstance(z_post, dict):
            continue
        z_status = str(z_post.get("status") or "published").strip().lower()
        if z_status in ("draft", "failed", "cancelled", "scheduled", "pending"):
            continue

        z_id = str(z_post.get("_id") or z_post.get("id") or z_post.get("postId") or "").strip()
        z_plat_id = str(z_post.get("platformPostId") or "").strip()
        z_plat_suffix = z_plat_id.split("_")[-1] if "_" in z_plat_id else z_plat_id

        if any(x and x in claimed_post_ids for x in (z_id, z_plat_id, z_plat_suffix)):
            continue

        plat = (z_post.get("platform") or "").strip().lower()
        acc_id_raw = z_post.get("accountId")
        if isinstance(acc_id_raw, dict):
            acc_id_raw = acc_id_raw.get("_id") or acc_id_raw.get("id")
        acc_id_str = str(acc_id_raw or "").strip()

        if not plat and isinstance(z_post.get("platforms"), list) and z_post["platforms"]:
            first_pl = z_post["platforms"][0]
            if isinstance(first_pl, dict):
                plat = (first_pl.get("platform") or "").strip().lower()
                pl_acc = first_pl.get("accountId")
                if isinstance(pl_acc, dict):
                    pl_acc = pl_acc.get("_id") or pl_acc.get("id")
                if pl_acc and not acc_id_str:
                    acc_id_str = str(pl_acc).strip()
                if not z_plat_id and first_pl.get("platformPostId"):
                    z_plat_id = str(first_pl.get("platformPostId")).strip()

        pk = _resolve_page_key(plat, acc_id_str, "")
        if not pk or pk not in pages_map:
            continue

        pub_raw = (
            z_post.get("publishedAt")
            or z_post.get("scheduledFor")
            or z_post.get("createdAt")
            or z_post.get("timestamp")
            or ""
        )
        ts_parsed = parse_meta_timestamp(pub_raw, item_id=z_plat_id or z_id)
        pub_dt = ts_parsed["dt"]
        if clean_period != "all" and pub_dt < cutoff_dt:
            continue

        page_info = pages_map[pk]
        matched_ana = analytics_by_post_id.get(z_id) or analytics_by_post_id.get(z_plat_id) or z_post
        metrics = _extract_metrics_dict(matched_ana, target_platform=plat)

        views = metrics.get("views", 0)
        impressions = max(metrics.get("impressions", 0), views)
        reach = max(metrics.get("reach", 0), impressions)
        likes = metrics.get("likes", 0)
        comments_cnt = metrics.get("comments", 0)
        shares = metrics.get("shares", 0)
        saves = metrics.get("saves", 0)
        clicks = metrics.get("clicks", 0)

        permalink = str(
            z_post.get("platformPostUrl")
            or z_post.get("permalink")
            or (matched_ana or {}).get("platformPostUrl")
            or ""
        ).strip()

        synth_id = f"zpost_{z_id or z_plat_id or uuid.uuid4().hex[:8]}"

        if plat == "youtube" and (views == 0 or likes == 0):
            yt_vid = _extract_yt_video_id_from_candidates([z_plat_id, z_id, permalink])
            if yt_vid:
                yt_cached = _fetch_youtube_public_video_metrics(yt_vid, allow_network=False)
                views = max(views, yt_cached.get("views", 0))
                impressions = max(impressions, views)
                reach = max(reach, views)
                likes = max(likes, yt_cached.get("likes", 0))
                if (views == 0 or likes == 0) and allow_blocking_network:
                    pending_yt_lookups.append((synth_id, yt_vid))

        eng_total = likes + comments_cnt + shares + saves + clicks
        eng_rate = metrics.get("engagement_rate", 0.0)
        if eng_rate <= 0.0 and impressions > 0 and eng_total > 0:
            eng_rate = round((eng_total / impressions) * 100.0, 2)

        for x_id in (z_id, z_plat_id, z_plat_suffix):
            if x_id:
                claimed_post_ids.add(x_id)

        caption_str = str(z_post.get("content") or z_post.get("caption") or z_post.get("title") or "").strip()
        media_items_raw = z_post.get("mediaItems") or z_post.get("media") or []
        preview_url = str(z_post.get("thumbnailUrl") or z_post.get("mediaUrl") or "").strip()
        if not preview_url and isinstance(media_items_raw, list) and media_items_raw:
            first_m = media_items_raw[0]
            if isinstance(first_m, dict):
                preview_url = str(first_m.get("thumbnailUrl") or first_m.get("url") or "").strip()

        unified_posts_by_key[synth_id] = {
            "id": synth_id,
            "page_key": pk,
            "platform": plat,
            "account_id": page_info["account_id"],
            "account_name": page_info["account_name"],
            "username": page_info["username"],
            "avatar_url": page_info["avatar_url"],
            "post_type": "reels",
            "caption": caption_str,
            "media_preview_url": preview_url,
            "permalink_url": permalink,
            "published_iso": pub_dt.isoformat(),
            "display_date": pub_dt.strftime("%b %d, %Y • %I:%M %p"),
            "views": views,
            "impressions": impressions,
            "reach": reach,
            "likes": likes,
            "comments": comments_cnt,
            "unread_comments": 0,
            "shares": shares,
            "saves": saves,
            "clicks": clicks,
            "total_engagement": eng_total,
            "engagement_rate": eng_rate
        }

    # Resolve any uncached YouTube video metrics in PARALLEL (max 6 concurrent workers) instead of blocking loop
    if pending_yt_lookups:
        unique_vids = list({vid for _, vid in pending_yt_lookups if vid})
        yt_results_by_vid: Dict[str, Dict[str, int]] = {}
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(unique_vids)))) as yt_ex:
            yt_futs = {yt_ex.submit(_fetch_youtube_public_video_metrics, v, True): v for v in unique_vids}
            for fut in as_completed(yt_futs):
                vid_k = yt_futs[fut]
                try:
                    yt_results_by_vid[vid_k] = fut.result()
                except Exception:
                    yt_results_by_vid[vid_k] = {"views": 0, "likes": 0}

        for p_key, vid_k in pending_yt_lookups:
            p_item = unified_posts_by_key.get(p_key)
            yt_stat = yt_results_by_vid.get(vid_k)
            if p_item and yt_stat:
                p_item["views"] = max(p_item["views"], yt_stat.get("views", 0))
                p_item["impressions"] = max(p_item["impressions"], p_item["views"])
                p_item["reach"] = max(p_item["reach"], p_item["views"])
                p_item["likes"] = max(p_item["likes"], yt_stat.get("likes", 0))
                eng_t = p_item["likes"] + p_item["comments"] + p_item["shares"] + p_item["saves"] + p_item["clicks"]
                p_item["total_engagement"] = eng_t
                if p_item["impressions"] > 0 and eng_t > 0:
                    p_item["engagement_rate"] = round((eng_t / p_item["impressions"]) * 100.0, 2)

    # Roll up post metrics into each connected Social Media Page
    all_posts_list = list(unified_posts_by_key.values())
    all_posts_list.sort(key=lambda x: x.get("published_iso") or "", reverse=True)

    for p_item in all_posts_list:
        pk = p_item.get("page_key")
        if not pk or pk not in pages_map:
            continue
        pg = pages_map[pk]
        pg["published_posts_count"] += 1
        pg["views"] += p_item["views"]
        pg["impressions"] += p_item["impressions"]
        pg["reach"] += p_item["reach"]
        pg["likes"] += p_item["likes"]
        pg["comments"] += p_item["comments"]
        pg["unread_comments_count"] += p_item.get("unread_comments", 0)
        pg["shares"] += p_item["shares"]
        pg["saves"] += p_item["saves"]
        pg["clicks"] += p_item["clicks"]
        pg["total_engagement"] += p_item["total_engagement"]

        cur_top = pg.get("top_post")
        if cur_top is None or (
            (p_item["total_engagement"], p_item["views"]) > (cur_top["total_engagement"], cur_top["views"])
        ):
            pg["top_post"] = {
                "id": p_item["id"],
                "caption": p_item["caption"] or "Published Media Post",
                "display_date": p_item["display_date"],
                "permalink_url": p_item["permalink_url"],
                "views": p_item["views"],
                "likes": p_item["likes"],
                "comments": p_item["comments"],
                "total_engagement": p_item["total_engagement"]
            }

    pages_list: List[Dict[str, Any]] = []
    for pk, pg in pages_map.items():
        pg_copy = dict(pg)
        pg_copy.pop("_internal_ids", None)
        denom = max(pg_copy["impressions"], pg_copy["views"])
        if denom > 0 and pg_copy["total_engagement"] > 0:
            pg_copy["engagement_rate"] = round((pg_copy["total_engagement"] / denom) * 100.0, 2)
        pages_list.append(pg_copy)

    # Sort pages by total engagement + views descending, then platform
    pages_list.sort(
        key=lambda x: (x.get("total_engagement", 0) + x.get("views", 0), x.get("published_posts_count", 0)),
        reverse=True
    )

    total_views = sum(p["views"] for p in pages_list)
    total_impressions = sum(p["impressions"] for p in pages_list)
    total_reach = sum(p["reach"] for p in pages_list)
    total_likes = sum(p["likes"] for p in pages_list)
    total_comments = sum(p["comments"] for p in pages_list)
    total_shares = sum(p["shares"] for p in pages_list)
    total_saves = sum(p["saves"] for p in pages_list)
    total_clicks = sum(p["clicks"] for p in pages_list)
    total_engagement = sum(p["total_engagement"] for p in pages_list)
    total_published_posts = sum(p["published_posts_count"] for p in pages_list)
    total_waiting_posts = sum(p["scheduled_waiting_count"] for p in pages_list)
    total_followers = sum(p["followers"] for p in pages_list)
    total_messages = sum(p["messages_count"] for p in pages_list)

    overall_denom = max(total_impressions, total_views)
    overall_eng_rate = round((total_engagement / overall_denom) * 100.0, 2) if (overall_denom > 0 and total_engagement > 0) else 0.0

    connected_platforms = []
    for plat_cand in ("facebook", "instagram", "tiktok", "youtube"):
        if any(p["platform"] == plat_cand for p in pages_list):
            connected_platforms.append(plat_cand)

    is_currently_syncing = bool(snap.get("is_syncing", False))

    response_payload = {
        "status": "success",
        "period": clean_period,
        "from_date": from_date_str,
        "to_date": to_date_str,
        "updated_at": now_m.strftime("%b %d, %Y • %I:%M:%S %p"),
        "syncing_external": is_currently_syncing,
        "connected_platforms": connected_platforms,
        "permissions_notes": api_permissions_notes,
        "summary": {
            "connected_pages_count": len(pages_list),
            "published_posts_count": total_published_posts,
            "scheduled_waiting_count": total_waiting_posts,
            "followers": total_followers,
            "views": total_views,
            "impressions": total_impressions,
            "reach": total_reach,
            "likes": total_likes,
            "comments": total_comments,
            "shares": total_shares,
            "saves": total_saves,
            "clicks": total_clicks,
            "messages_count": total_messages,
            "total_engagement": total_engagement,
            "engagement_rate": overall_eng_rate
        },
        "pages": pages_list,
        "posts": all_posts_list
    }

    if snap["ts"] > 0.0:
        ANALYTICS_CACHE["by_period"][clean_period] = {
            "ts": now_ts,
            "payload": response_payload
        }
    return response_payload


