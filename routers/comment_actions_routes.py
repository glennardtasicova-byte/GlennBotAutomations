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


@router.get("/api/comments")
def get_all_comments(force: bool = False, active_record_id: str = ""):
    try:
        if not CLOUDINARY_COMMENTS_STORE.get("loaded"):
            load_comments_store_from_cloudinary()

        if force:
            sync_all_connected_posts_to_cloudinary(force_refresh=True)
        else:
            trigger_auto_youtube_and_active_sync(active_record_id=active_record_id, min_interval=3.0)

        seen_ids = _get_cached_seen_comment_ids(ttl_sec=3.0)
        post_rows = _get_cached_published_posts(ttl_sec=3.5, force=force)

        connected_items = refresh_connected_accounts_cache(force=False)
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}

        # Merge any post entries present in CLOUDINARY_COMMENTS_STORE that weren't in post_rows (e.g. newly received webhook or older external post)
        combined_posts: List[Dict[str, Any]] = [dict(r) for r in post_rows]
        seen_post_rec_ids = {str(r.get("id") or "") for r in combined_posts}
        for store_rec_id, store_entry in list(posts_store.items()):
            if store_rec_id not in seen_post_rec_ids and isinstance(store_entry, dict):
                combined_posts.append({
                    "id": store_rec_id,
                    "platform": store_entry.get("platform") or "facebook",
                    "page_id": str(store_entry.get("page_id") or ""),
                    "account_name": store_entry.get("account_name") or "",
                    "post_type": store_entry.get("post_type") or "reels",
                    "caption": store_entry.get("post_caption") or "",
                    "permalink_url": store_entry.get("post_permalink") or "",
                    "scheduled_time": None,
                    "status": "published"
                })
                seen_post_rec_ids.add(store_rec_id)

        seen_global_comment_ids = set()
        visible_comments: List[Dict[str, Any]] = []
        store_cleaned = False

        for db_post in combined_posts:
            rec_id = str(db_post["id"])
            if not is_post_account_connected(db_post, connected_items):
                continue

            p_entry = posts_store.get(rec_id)
            if not p_entry:
                continue

            del_cids = set(str(x) for x in (p_entry.get("deleted_comment_ids") or []))
            c_map = p_entry.get("comments") or {}

            # Auto-unhide if there is any unread user comment or unread user reply in this post
            if p_entry.get("notification_hidden"):
                has_unread_activity = False
                for chk_cid, chk_obj in c_map.items():
                    if chk_cid in del_cids or not isinstance(chk_obj, dict) or chk_obj.get("is_own_comment"):
                        continue
                    if chk_cid not in seen_ids:
                        has_unread_activity = True
                        break
                    for chk_rep in (chk_obj.get("replies") or []):
                        if isinstance(chk_rep, dict) and not chk_rep.get("is_own"):
                            r_chk_id = str(chk_rep.get("id") or "").strip()
                            if r_chk_id and r_chk_id not in seen_ids:
                                has_unread_activity = True
                                break
                    if has_unread_activity:
                        break
                if has_unread_activity:
                    p_entry["notification_hidden"] = False
                    store_cleaned = True
                else:
                    continue

            if repair_unknown_authors_in_post_entry(p_entry, db_post):
                store_cleaned = True

            sched_dt = db_post.get("scheduled_time")
            is_ext_post = rec_id.startswith("post_ext_")

            for cid, c_obj in list(c_map.items()):
                if cid in del_cids or c_obj.get("is_own_comment"):
                    continue
                if not is_comment_timestamp_valid_for_post(c_obj.get("created_iso", ""), sched_dt, is_external_post=is_ext_post):
                    continue
                if cid in seen_global_comment_ids:
                    c_map.pop(cid, None)
                    store_cleaned = True
                    continue
                seen_global_comment_ids.add(cid)

                c_copy = dict(c_obj)
                c_copy["record_id"] = rec_id
                if db_post.get("page_id"):
                    c_copy["page_id"] = str(db_post["page_id"])
                if db_post.get("account_name"):
                    c_copy["account_name"] = db_post["account_name"]
                if db_post.get("caption") and db_post["caption"] != "Previous Post":
                    c_copy["post_caption"] = db_post["caption"]
                if db_post.get("permalink_url"):
                    c_copy["post_permalink"] = db_post["permalink_url"]
                enriched = enrich_comment_with_reply_notifications(c_copy, seen_ids)
                visible_comments.append(enriched)

        if store_cleaned:
            save_comments_store_async()

        visible_comments.sort(key=lambda x: x.get("latest_activity_iso") or x["created_iso"], reverse=True)
        unread_count = sum(
            (0 if item.get("parent_is_read") else 1) + int(item.get("unread_replies_count") or 0)
            for item in visible_comments
        )
        return {
            "status": "success",
            "cached": not force,
            "unread_count": unread_count,
            "total_count": len(visible_comments),
            "comments": visible_comments,
            "permissions_warnings": []
        }
    except Exception as e:
        return {
            "status": "error",
            "unread_count": 0,
            "total_count": 0,
            "comments": [],
            "message": str(e)
        }


@router.get("/api/posts/{record_id}/live_details")
def get_live_post_details(record_id: str):
    now_ts = time.time()
    if record_id in LIVE_DETAILS_CACHE and (now_ts - LIVE_DETAILS_CACHE[record_id]["ts"] < 1800):
        return {"status": "success", "details": LIVE_DETAILS_CACHE[record_id]["details"]}

    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, post_type, caption,
                           media_preview_url, scheduled_time, status, status_message,
                           external_post_id, permalink_url, created_at
                    FROM glennbot_scheduled_posts
                    WHERE id = :id
                """),
                {"id": record_id}
            ).mappings().first()

        if not row:
            return {"status": "error", "message": "Post record not found in Supabase."}

        r_dict = dict(row)
        if not is_post_account_connected(r_dict):
            return {
                "status": "error",
                "message": "This social media page/account is no longer connected in GlennBot."
            }

        platform = r_dict["platform"]
        post_type = r_dict["post_type"]
        status_msg = r_dict.get("status_message") or ""
        ext_id = extract_external_post_id(r_dict)

        result = {
            "record_id": r_dict["id"],
            "platform": platform,
            "account_name": r_dict["account_name"] or platform.upper(),
            "post_type": post_type,
            "caption": r_dict["caption"] or "",
            "external_post_id": ext_id,
            "permalink_url": r_dict.get("permalink_url") or "",
            "video_url": "",
            "thumbnail_url": "",
            "images": [],
            "fallback_preview_url": r_dict.get("media_preview_url") or ""
        }

        z_info = resolve_zernio_post_identifiers(r_dict, force=False)
        z_map = get_zernio_posts_map(force=False)
        z_post = z_map.get(z_info["zernio_post_id"]) or z_map.get(z_info["platform_post_id"]) or z_map.get(ext_id)

        if z_post:
            media_Urls = []
            for m_item in (z_post.get("mediaItems") or []):
                m_url = m_item.get("url") if isinstance(m_item, dict) else str(m_item)
                if m_url:
                    media_Urls.append(m_url)
            if media_Urls:
                if post_type == "image":
                    result["images"] = media_Urls
                else:
                    result["video_url"] = media_Urls[0]

            if not result["permalink_url"] and z_post.get("platformPostUrl"):
                result["permalink_url"] = z_post["platformPostUrl"]

        if not result["permalink_url"] and z_info["permalink_url"]:
            result["permalink_url"] = z_info["permalink_url"]

        if platform == "tiktok" and not result["video_url"] and ext_id and ext_id.isdigit():
            tk_meta = fetch_tikwm_video_metadata(ext_id, (r_dict.get("account_name") or "").lstrip("@"))
            if tk_meta.get("video_url"):
                result["video_url"] = tk_meta["video_url"]
            if tk_meta.get("cover_url"):
                result["thumbnail_url"] = tk_meta["cover_url"]
            if tk_meta.get("caption") and (not result["caption"] or result["caption"] == "Previous Post"):
                result["caption"] = tk_meta["caption"]
            if tk_meta.get("permalink") and not result["permalink_url"]:
                result["permalink_url"] = tk_meta["permalink"]

        if result["permalink_url"] and not r_dict.get("permalink_url"):
            update_post_status(
                record_id,
                r_dict["status"],
                status_msg,
                external_post_id=ext_id or None,
                permalink_url=result["permalink_url"]
            )

        LIVE_DETAILS_CACHE[record_id] = {"ts": now_ts, "details": result}
        return {"status": "success", "details": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class MarkReadPayload(BaseModel):
    comment_ids: List[str]
    record_id: Optional[str] = ""
    platform: Optional[str] = ""

@router.post("/api/comments/mark_read")
def mark_comments_as_read(payload: MarkReadPayload):
    try:
        if not payload.comment_ids:
            return {"status": "success"}

        ids_to_mark = set(str(cid) for cid in payload.comment_ids if cid)
        rec_id = (payload.record_id or "").strip()
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        if rec_id and rec_id in posts_store:
            p_entry = posts_store[rec_id]
            for cid in list(ids_to_mark):
                parent_c, _ = find_parent_and_target_comment(p_entry, cid)
                if parent_c:
                    if parent_c.get("comment_id"):
                        ids_to_mark.add(str(parent_c["comment_id"]))
                    for rep in (parent_c.get("replies") or []):
                        if rep.get("id"):
                            ids_to_mark.add(str(rep["id"]))

        with db_engine.begin() as conn:
            for cid in ids_to_mark:
                conn.execute(
                    text("""
                        INSERT INTO glennbot_seen_comments (comment_id, record_id, platform)
                        VALUES (:cid, :rid, :plat)
                        ON CONFLICT (comment_id) DO NOTHING
                    """),
                    {"cid": str(cid), "rid": rec_id, "plat": payload.platform or ""}
                )
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class CommentReplyPayload(BaseModel):
    record_id: str
    comment_id: str
    message: str
    file_id: Optional[str] = ""
    media_url: Optional[str] = ""

def send_zernio_comment_reply(
    post_id: str,
    account_id: str,
    comment_id: str,
    reply_msg: str,
    preferred_api_key: str = "",
    platform: str = "",
    account_name: str = ""
) -> Dict[str, Any]:
    verified_pairs = resolve_live_zernio_account_and_key_pairs(
        platform=platform,
        account_id=account_id,
        account_name=account_name,
        stored_z_acc_id=account_id,
        preferred_key=preferred_api_key
    )
    if not verified_pairs and account_id:
        for k in get_candidate_zernio_keys_for_account(account_id, preferred_key=preferred_api_key, account_name=account_name, platform=platform):
            verified_pairs.append({"api_key": k, "account_id": account_id})

    url = f"{ZERNIO_BASE_URL}/inbox/comments/{post_id}"
    last_result: Dict[str, Any] = {"status_code": 500, "data": {}, "raw_text": "No External API key available."}
    best_non_404_result: Optional[Dict[str, Any]] = None

    for pair in verified_pairs:
        k = pair["api_key"]
        eff_acc_id = pair["account_id"]
        body = {
            "accountId": eff_acc_id,
            "commentId": comment_id,
            "message": reply_msg
        }
        try:
            resp = HTTP_SESSION.post(url, headers=get_zernio_headers(k), json=body, timeout=20)
            try:
                data = resp.json()
            except Exception:
                data = {}
            res_obj = {
                "status_code": resp.status_code,
                "data": data,
                "raw_text": resp.text,
                "used_account_id": eff_acc_id,
                "used_api_key": k
            }
            if resp.status_code in (200, 201):
                CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][str(eff_acc_id)] = k
                return res_obj

            last_result = res_obj
            err_code = str((data or {}).get("code") or "").strip().lower() if isinstance(data, dict) else ""
            if err_code != "account_not_found":
                best_non_404_result = res_obj
        except Exception as e:
            last_result = {"status_code": 500, "data": {}, "raw_text": str(e)}

    return best_non_404_result or last_result


@router.post("/api/comments/reply")
def reply_to_comment(payload: CommentReplyPayload):
    reply_msg = _sanitize_outbound_social_or_email_text(payload.message)
    payload.message = reply_msg
    has_file_or_media = bool((payload.file_id or "").strip() or (payload.media_url or "").strip())
    if not reply_msg and not has_file_or_media:
        return {"status": "error", "message": "Please type a message before sending a reply."}
    if not reply_msg and has_file_or_media:
        reply_msg = "Here is the file you requested:"

    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, caption, scheduled_time,
                           external_post_id, permalink_url, status_message
                    FROM glennbot_scheduled_posts
                    WHERE id = :id
                """),
                {"id": payload.record_id}
            ).mappings().first()

        if not row:
            return {"status": "error", "message": "Post record not found in database."}

        r_dict = dict(row)
        if not is_post_account_connected(r_dict):
            return {
                "status": "error",
                "message": "This social media page/account is no longer connected in GlennBot."
            }

        rec_id_str = str(payload.record_id or "").strip()
        is_ext_post = rec_id_str.startswith("post_ext_")
        platform = (r_dict.get("platform") or "").strip().lower()
        page_id = str(r_dict.get("page_id") or "").strip()
        acc_name = (r_dict.get("account_name") or "").strip()
        ext_id = extract_external_post_id(r_dict)

        raw_target_cid = str(payload.comment_id or "").strip()
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        post_entry = posts_store.get(rec_id_str) or {}
        parent_comm, target_sub_reply = find_parent_and_target_comment(post_entry, raw_target_cid)
        cached_comm = parent_comm or (post_entry.get("comments") or {}).get(raw_target_cid)

        # FAST-PATH FOR SIMULTANEOUS N8N COMMENT REPLIES:
        # Only perform a synchronous pre-reply Zernio sync if the target comment is NOT yet in CLOUDINARY_COMMENTS_STORE
        # or if we are replying to a nested sub-reply whose ID isn't resolved yet.
        # When 5-20 users comment simultaneously on a post and n8n calls POST /api/v1/comments/reply for each comment_id,
        # `cached_comm` is already in memory from the webhook, so we skip the heavy full-post sync and reply immediately!
        norm_raw_target = _normalize_comment_key(raw_target_cid)
        is_direct_top_level_known = bool(
            cached_comm is not None
            and str(cached_comm.get("comment_id") or "") == raw_target_cid
        )
        if not is_direct_top_level_known and (
            cached_comm is None
            or (raw_target_cid and parent_comm is not None and target_sub_reply is None and str(parent_comm.get("comment_id") or "") != raw_target_cid)
        ):
            try:
                sync_single_post_to_cloudinary(r_dict, force_unhide=False)
                posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
                post_entry = posts_store.get(rec_id_str) or {}
                parent_comm, target_sub_reply = find_parent_and_target_comment(post_entry, raw_target_cid)
                cached_comm = parent_comm or (post_entry.get("comments") or {}).get(raw_target_cid)
            except Exception as sync_pre_err:
                print(f"[⚠️ PRE-REPLY THREAD SYNC WARNING]: {sync_pre_err}")

        z_info = resolve_zernio_post_identifiers(r_dict, force=False)
        if not z_info.get("inbox_post_id") and not (cached_comm or {}).get("zernio_post_id") and not ext_id:
            z_info = resolve_zernio_post_identifiers(r_dict, force=True)

        valid_page_ids_reply = _collect_valid_account_ids_for_page(platform, page_id, acc_name)
        cached_z_acc_reply = str((cached_comm or {}).get("zernio_account_id") or "").strip()
        if cached_z_acc_reply and valid_page_ids_reply and cached_z_acc_reply not in valid_page_ids_reply:
            cached_z_acc_reply = ""

        z_acc_id = str(z_info.get("zernio_account_id") or cached_z_acc_reply or page_id).strip()
        if valid_page_ids_reply and z_acc_id not in valid_page_ids_reply:
            z_acc_id = str(z_info.get("zernio_account_id") or page_id).strip()

        bound_page_key_reply = get_zernio_key_for_account(page_id, account_name=acc_name, platform=platform)
        pref_key = str(bound_page_key_reply or z_info.get("zernio_api_key") or (cached_comm or {}).get("zernio_api_key") or "").strip()

        resolved_media = _resolve_vault_file_for_dm_or_comment(
            file_id=payload.file_id or "",
            media_url=payload.media_url or "",
            platform=platform,
            account_id=z_acc_id or page_id,
            preferred_api_key=pref_key
        )
        resolved_media_url = ""
        resolved_media_type = "image"
        resolved_attachments: List[Dict[str, Any]] = []
        if resolved_media and resolved_media.get("url"):
            resolved_media_url = str(resolved_media["url"]).strip()
            resolved_media_type = str(resolved_media.get("type") or "image").strip()
            resolved_attachments.append({
                "type": resolved_media_type,
                "url": resolved_media_url,
                "name": str(resolved_media.get("filename") or ""),
                "file_id": str(resolved_media.get("file_id") or "")
            })
            if resolved_media_url and resolved_media_url not in reply_msg:
                reply_msg = f"{reply_msg}\n{resolved_media_url}".strip()

        explicit_parent_cid = str(
            (parent_comm or {}).get("comment_id")
            or (cached_comm or {}).get("parent_comment_id")
            or (cached_comm or {}).get("parentId")
            or (cached_comm or {}).get("parent_id")
            or raw_target_cid
        ).strip()
        parent_cid = explicit_parent_cid or raw_target_cid

        def _is_real_platform_cid(cid_val: str) -> bool:
            s = str(cid_val or "").strip()
            return bool(s and not s.startswith(("local_", "z_rep_")) and s.lower() not in ("ok", "true", "none"))

        all_thread_reps = merge_buffered_own_replies(
            parent_cid,
            list((parent_comm or cached_comm or {}).get("replies") or [])
        )
        real_thread_reps = [
            r for r in all_thread_reps
            if isinstance(r, dict) and _is_real_platform_cid(str(r.get("id") or ""))
        ]

        # Build Tier 1 (active sub-thread reply IDs: latest reply first, then its sub-thread parent / Page's own reply)
        # and Tier 2 (root comment fallback). This ensures follow-up replies ALWAYS continue the active conversation thread!
        subthread_raw_cids: List[str] = []

        def _add_subthread_cand(c_val: str):
            c_clean = str(c_val or "").strip()
            if _is_real_platform_cid(c_clean) and c_clean != parent_cid and c_clean not in subthread_raw_cids:
                subthread_raw_cids.append(c_clean)

        if target_sub_reply is not None or (raw_target_cid and raw_target_cid != parent_cid):
            _add_subthread_cand(raw_target_cid)
            if isinstance(target_sub_reply, dict):
                _add_subthread_cand(str(target_sub_reply.get("replied_to_id") or ""))

        if real_thread_reps:
            latest_rep_obj = real_thread_reps[-1]
            _add_subthread_cand(str(latest_rep_obj.get("id") or ""))
            _add_subthread_cand(str(latest_rep_obj.get("replied_to_id") or ""))
            for r_item in reversed(real_thread_reps):
                if r_item.get("is_own"):
                    _add_subthread_cand(str(r_item.get("id") or ""))
            for r_item in reversed(real_thread_reps):
                _add_subthread_cand(str(r_item.get("id") or ""))

        def _clean_cid_list(raw_list_in: List[str]) -> List[str]:
            out: List[str] = []
            for c_cand in raw_list_in:
                clean_c = c_cand.split("_")[-1] if (platform == "tiktok" and "_" in c_cand) else c_cand
                if clean_c and clean_c not in out:
                    out.append(clean_c)
            return out

        subthread_priority_cids = _clean_cid_list(subthread_raw_cids)
        root_fallback_cids = [
            c for c in _clean_cid_list([parent_cid, raw_target_cid])
            if c not in subthread_priority_cids
        ]
        candidate_comment_ids = subthread_priority_cids + root_fallback_cids
        priority_cid_tiers = [t for t in (subthread_priority_cids, root_fallback_cids) if t]

        permalink_str = str(r_dict.get("permalink_url") or z_info.get("permalink_url") or "").strip()
        fbid_from_link = ""
        if permalink_str:
            m_fbid = re.search(r"(?:fbid=|story_fbid=|/posts/|/videos/|/reel/|/video/)(\d+)", permalink_str)
            if m_fbid:
                fbid_from_link = m_fbid.group(1).strip()

        base_post_ids = []
        for pid in [
            (cached_comm or {}).get("zernio_post_id"),
            z_info.get("inbox_post_id"),
            z_info.get("inbox_plat_id"),
            z_info.get("platform_post_id"),
            z_info.get("zernio_post_id"),
            ext_id,
            fbid_from_link
        ]:
            p_str = str(pid or "").strip()
            if p_str and p_str != "OK" and p_str not in base_post_ids:
                base_post_ids.append(p_str)

        def _expand_post_ids_for_account(raw_pids: List[str], target_acc_id: str, target_acc_name: str) -> List[str]:
            expanded: List[str] = []
            fb_prefixes: List[str] = []
            if platform == "facebook":
                for force_f in (False, True):
                    for za in fetch_zernio_connected_accounts(platform="facebook", force=force_f):
                        if not isinstance(za, dict):
                            continue
                        za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
                        if za_plat_id and _does_zernio_account_match_page(za, page_id, target_acc_id, target_acc_name or acc_name):
                            if za_plat_id not in fb_prefixes:
                                fb_prefixes.append(za_plat_id)
                    if fb_prefixes:
                        break
                if page_id and len(page_id) != 24 and page_id.isdigit() and page_id not in fb_prefixes:
                    fb_prefixes.append(page_id)

            for p_item in raw_pids:
                if p_item not in expanded:
                    expanded.append(p_item)
                if platform == "facebook":
                    if "_" in p_item:
                        bare_suffix = p_item.split("_")[-1].strip()
                        for fb_p in fb_prefixes:
                            re_prefixed = f"{fb_p}_{bare_suffix}"
                            if re_prefixed not in expanded:
                                expanded.append(re_prefixed)
                        if bare_suffix and bare_suffix not in expanded:
                            expanded.append(bare_suffix)
                    elif len(p_item) != 24:
                        for fb_p in fb_prefixes:
                            comp = f"{fb_p}_{p_item}"
                            if comp not in expanded:
                                expanded.append(comp)
            return expanded

        def _expand_comment_ids_for_post(target_pid: str, base_cids: List[str], extra_Format: bool = False) -> List[str]:
            expanded_cids: List[str] = []
            if not extra_Format or platform != "facebook":
                for c_id in base_cids:
                    if c_id and c_id not in expanded_cids:
                        expanded_cids.append(c_id)
                return expanded_cids

            post_suffix = target_pid.split("_")[-1].strip() if "_" in target_pid else target_pid.strip()
            prefix_candidates = []
            for pref in (post_suffix, fbid_from_link, target_pid):
                if pref and len(pref) != 24 and pref not in prefix_candidates:
                    prefix_candidates.append(pref)

            # Expand each candidate ID completely before moving to the next candidate so priority order is strictly preserved
            for c_id in base_cids:
                if not c_id:
                    continue
                if c_id not in expanded_cids:
                    expanded_cids.append(c_id)
                c_suffix = c_id.split("_")[-1].strip() if "_" in c_id else c_id.strip()
                if not c_suffix:
                    continue
                for pref in prefix_candidates:
                    if pref != c_suffix:
                        re_cid = f"{pref}_{c_suffix}"
                        if re_cid not in expanded_cids:
                            expanded_cids.append(re_cid)
                if c_suffix not in expanded_cids:
                    expanded_cids.append(c_suffix)
            return expanded_cids

        cand_post_ids = _expand_post_ids_for_account(base_post_ids, z_acc_id or page_id, acc_name)

        def _extract_reply_id_from_zernio_response(r_data: Any) -> str:
            if not isinstance(r_data, dict):
                return ""
            for cand_obj in (
                r_data,
                r_data.get("data"),
                r_data.get("comment"),
                r_data.get("reply"),
                (r_data.get("data") or {}).get("comment") if isinstance(r_data.get("data"), dict) else None,
                (r_data.get("data") or {}).get("reply") if isinstance(r_data.get("data"), dict) else None,
            ):
                if isinstance(cand_obj, dict):
                    for key_name in ("commentId", "id", "ID", "_id", "comment_id", "replyId", "reply_id", "platformCommentId", "platform_id"):
                        val = str(cand_obj.get(key_name) or "").strip()
                        if val and val.lower() not in ("ok", "true", "success", "none"):
                            return val
            return ""

        def _finalize_successful_reply(z_res: Dict[str, Any], winning_acc_id: str = "", winning_acc_name: str = "", winning_api_key: str = "", winning_pid: str = "", winning_cid: str = ""):
            eff_name = winning_acc_name or r_dict.get("account_name") or platform.capitalize()
            if winning_acc_id and is_ext_post and (winning_acc_id != page_id or (winning_acc_name and winning_acc_name != acc_name)):
                try:
                    with db_engine.begin() as conn_h:
                        conn_h.execute(
                            text("""
                                UPDATE glennbot_scheduled_posts
                                SET page_id = :pid, account_name = :aname
                                WHERE id = :id
                            """),
                            {"pid": winning_acc_id, "aname": eff_name, "id": rec_id_str}
                        )
                    _invalidate_fast_db_cache(["published_posts"])
                    if isinstance(post_entry, dict):
                        post_entry["page_id"] = winning_acc_id
                        post_entry["account_name"] = eff_name
                        for c_obj_h in (post_entry.get("comments") or {}).values():
                            if isinstance(c_obj_h, dict):
                                c_obj_h["zernio_account_id"] = winning_acc_id
                                c_obj_h["page_id"] = winning_acc_id
                                c_obj_h["account_name"] = eff_name
                                if winning_api_key:
                                    c_obj_h["zernio_api_key"] = winning_api_key
                                if winning_pid:
                                    c_obj_h["zernio_post_id"] = winning_pid
                        save_comments_store_async()
                    print(f"[🛠️ AUTO-HEALED EXTERNAL POST OWNER] {rec_id_str} -> {eff_name} ({winning_acc_id})")
                except Exception as heal_err:
                    print(f"[⚠️ EXTERNAL POST HEAL WARNING]: {heal_err}")

            r_data = z_res["data"]
            extracted_rid = _extract_reply_id_from_zernio_response(r_data)
            reply_id = extracted_rid or f"z_rep_{int(time.time()*1000)}"
            effective_replied_to = str(winning_cid or raw_target_cid or parent_cid).strip()
            buffered_rep = record_buffered_own_reply(
                rec_id_str,
                effective_replied_to,
                reply_id,
                eff_name,
                reply_msg
            )
            mark_comments_as_read(MarkReadPayload(comment_ids=[effective_replied_to, raw_target_cid, parent_cid], record_id=payload.record_id, platform=platform))
            if "_notify_n8n_new_comment" in globals():
                parent_author_id_val = str((parent_comm or cached_comm or {}).get("author_id") or "").strip()
                parent_author_name_val = str((parent_comm or cached_comm or {}).get("author_name") or "").strip()
                own_reply_notif = {
                    "comment_id": reply_id,
                    "parent_comment_id": parent_cid,
                    "replied_to_id": effective_replied_to,
                    "is_reply": True,
                    "is_reply_to_comment": True,
                    "record_id": rec_id_str,
                    "zernio_post_id": str(winning_pid or ext_id or ""),
                    "zernio_account_id": str(winning_acc_id or z_acc_id or page_id or ""),
                    "platform": platform,
                    "page_id": str(winning_acc_id or page_id or ""),
                    "account_name": eff_name,
                    "author_id": parent_author_id_val or str(winning_acc_id or page_id or ""),
                    "author_name": eff_name,
                    "parent_author_id": parent_author_id_val,
                    "parent_author_name": parent_author_name_val,
                    "message": reply_msg,
                    "created_iso": buffered_rep.get("created_iso") or "",
                    "display_time": buffered_rep.get("display_time") or "",
                    "is_own_comment": True
                }
                _notify_n8n_new_comment(r_dict, own_reply_notif, is_background_sync=False)
            return {
                "status": "success",
                "reply_id": reply_id,
                "parent_comment_id": parent_cid,
                "replied_to_id": effective_replied_to,
                "reply": buffered_rep
            }

        last_err = "Could not resolve External API Post ID."
        tried_combinations = set()

        # Pass 1: Standard Reply Loop locked strictly to this Page (tries sub-thread Tier 1 across all post IDs before root Tier 2)
        for tier_cids in priority_cid_tiers:
            for target_pid in cand_post_ids:
                p1_cids = _expand_comment_ids_for_post(target_pid, tier_cids, extra_Format=True)
                for api_cid in p1_cids:
                    if (target_pid, z_acc_id, api_cid) in tried_combinations:
                        continue
                    tried_combinations.add((target_pid, z_acc_id, api_cid))
                    z_res = send_zernio_comment_reply(
                        target_pid,
                        z_acc_id,
                        api_cid,
                        reply_msg,
                        preferred_api_key=pref_key,
                        platform=platform,
                        account_name=acc_name
                    )
                    if z_res["status_code"] in (200, 201):
                        return _finalize_successful_reply(
                            z_res,
                            winning_acc_id=str(z_res.get("used_account_id") or z_acc_id),
                            winning_acc_name=acc_name,
                            winning_api_key=str(z_res.get("used_api_key") or pref_key),
                            winning_pid=target_pid,
                            winning_cid=api_cid
                        )
                    last_err = str(z_res["data"] or z_res["raw_text"])

        # Pass 2: Fresh Commented Posts & Page-Scoped Account Discovery (strictly restricted to the post's Page!)
        known_suffixes = {p.split("_")[-1].strip() for p in base_post_ids if p and p != "OK"}
        for cp in get_zernio_commented_posts_list(force=True):
            if not isinstance(cp, dict):
                continue
            cp_plat = (cp.get("platform") or "").strip().lower()
            if cp_plat and cp_plat != platform:
                continue
            cp_id = str(cp.get("id") or cp.get("_id") or cp.get("postId") or "").strip()
            cp_plat_id = str(cp.get("platformPostId") or "").strip()
            cp_suffix = cp_plat_id.split("_")[-1].strip() if "_" in cp_plat_id else cp_plat_id
            if bool({cp_id, cp_plat_id, cp_suffix} & (set(base_post_ids) | known_suffixes)):
                for new_p in (cp_id, cp_plat_id):
                    if new_p and new_p not in base_post_ids:
                        base_post_ids.insert(0, new_p)

        all_plat_accounts = fetch_zernio_connected_accounts(platform=platform or None, force=True)
        matching_plat_accounts = [
            za for za in all_plat_accounts
            if isinstance(za, dict) and _does_zernio_account_match_page(za, page_id, z_acc_id, acc_name)
        ]
        # Only fall back to scanning other accounts if this is an unowned external post with no matched page
        candidate_plat_accounts = matching_plat_accounts if matching_plat_accounts else (all_plat_accounts if is_ext_post and not acc_name else [])

        for tier_cids in priority_cid_tiers:
            for za in candidate_plat_accounts:
                if not isinstance(za, dict):
                    continue
                za_id = str(za.get("_id") or za.get("id") or "").strip()
                za_key = str(za.get("_zernio_api_key") or "").strip()
                za_dname = str(za.get("displayName") or za.get("name") or za.get("username") or acc_name or platform.upper()).strip()
                if not za_id or not za_key:
                    continue

                za_post_ids = _expand_post_ids_for_account(base_post_ids, za_id, za_dname)
                for target_pid in za_post_ids:
                    p2_cids = _expand_comment_ids_for_post(target_pid, tier_cids, extra_Format=True)
                    for api_cid in p2_cids:
                        if (target_pid, za_id, api_cid) in tried_combinations:
                            continue
                        tried_combinations.add((target_pid, za_id, api_cid))
                        z_res = send_zernio_comment_reply(
                            target_pid,
                            za_id,
                            api_cid,
                            reply_msg,
                            preferred_api_key=za_key,
                            platform=platform,
                            account_name=acc_name or za_dname
                        )
                        if z_res["status_code"] in (200, 201):
                            return _finalize_successful_reply(
                                z_res,
                                winning_acc_id=za_id,
                                winning_acc_name=acc_name or za_dname,
                                winning_api_key=za_key,
                                winning_pid=target_pid,
                                winning_cid=api_cid
                            )
                        err_data = z_res.get("data")
                        err_code = str((err_data or {}).get("code") or "").strip().lower() if isinstance(err_data, dict) else ""
                        if err_code != "account_not_found":
                            last_err = str(z_res["data"] or z_res["raw_text"])

        # Pass 3: Live Comment Thread Inspection on the post's Page
        target_cid_suffixes = {c.split("_")[-1].strip() for c in candidate_comment_ids if c}
        for za in candidate_plat_accounts:
            if not isinstance(za, dict):
                continue
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_key = str(za.get("_zernio_api_key") or "").strip()
            za_dname = str(za.get("displayName") or za.get("name") or za.get("username") or acc_name or platform.upper()).strip()
            if not za_id or not za_key:
                continue
            za_post_ids = _expand_post_ids_for_account(base_post_ids, za_id, za_dname)
            for target_pid in za_post_ids:
                try:
                    encoded_pid = urllib.parse.quote(str(target_pid), safe="")
                    c_url = f"{ZERNIO_BASE_URL}/inbox/comments/{encoded_pid}?accountId={urllib.parse.quote(za_id, safe='')}"
                    c_resp = HTTP_SESSION.get(c_url, headers=get_zernio_headers(za_key), timeout=12)
                    if c_resp.status_code != 200:
                        continue
                    live_comments = extract_list_from_api_payload(c_resp.json()) or []
                    discovered_sub_cids: List[str] = []
                    discovered_root_cids: List[str] = []
                    for lc in live_comments:
                        if not isinstance(lc, dict):
                            continue
                        lc_id = str(lc.get("id") or lc.get("_id") or lc.get("commentId") or "").strip()
                        lc_parent = str(lc.get("parentId") or lc.get("parent_id") or lc.get("parentCommentId") or "").strip()
                        lc_suffix = lc_id.split("_")[-1].strip() if "_" in lc_id else lc_id
                        for sub_r in (lc.get("replies") or lc.get("children") or lc.get("comments") or []):
                            if not isinstance(sub_r, dict):
                                continue
                            sr_id = str(sub_r.get("id") or sub_r.get("_id") or sub_r.get("commentId") or "").strip()
                            sr_suffix = sr_id.split("_")[-1].strip() if "_" in sr_id else sr_id
                            if sr_id and (sr_id in candidate_comment_ids or sr_suffix in target_cid_suffixes or lc_id in candidate_comment_ids or lc_suffix in target_cid_suffixes):
                                if sr_id not in discovered_sub_cids:
                                    discovered_sub_cids.append(sr_id)
                                if lc_id and lc_id not in discovered_root_cids:
                                    discovered_root_cids.append(lc_id)
                        if lc_id and (lc_id in candidate_comment_ids or lc_suffix in target_cid_suffixes):
                            if lc_parent:
                                if lc_id not in discovered_sub_cids:
                                    discovered_sub_cids.append(lc_id)
                                if lc_parent not in discovered_root_cids:
                                    discovered_root_cids.append(lc_parent)
                            else:
                                if lc_id not in discovered_root_cids:
                                    discovered_root_cids.append(lc_id)
                    discovered_live_cids = list(reversed(discovered_sub_cids)) + [rc for rc in discovered_root_cids if rc not in discovered_sub_cids]
                    for live_cid in discovered_live_cids:
                        if (target_pid, za_id, live_cid) in tried_combinations:
                            continue
                        tried_combinations.add((target_pid, za_id, live_cid))
                        z_res = send_zernio_comment_reply(
                            target_pid,
                            za_id,
                            live_cid,
                            reply_msg,
                            preferred_api_key=za_key,
                            platform=platform,
                            account_name=acc_name or za_dname
                        )
                        if z_res["status_code"] in (200, 201):
                            return _finalize_successful_reply(
                                z_res,
                                winning_acc_id=za_id,
                                winning_acc_name=acc_name or za_dname,
                                winning_api_key=za_key,
                                winning_pid=target_pid,
                                winning_cid=live_cid
                            )
                except Exception:
                    continue

        return {"status": "error", "message": f"External API Reply Error ({platform.upper()}): {last_err}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class CommentSendDmPayload(BaseModel):
    record_id: str
    comment_id: str
    message: str
    file_id: Optional[str] = ""
    media_url: Optional[str] = ""
    filename: Optional[str] = ""
    media_type: Optional[str] = ""


def send_zernio_private_reply(
    post_id: str,
    account_id: str,
    comment_id: str,
    dm_msg: str,
    preferred_api_key: str = "",
    platform: str = "",
    account_name: str = "",
    media_url: str = "",
    media_type: str = "image",
    media_name: str = ""
) -> Dict[str, Any]:
    verified_pairs = resolve_live_zernio_account_and_key_pairs(
        platform=platform,
        account_id=account_id,
        account_name=account_name,
        stored_z_acc_id=account_id,
        preferred_key=preferred_api_key
    )
    if not verified_pairs and account_id:
        for k in get_candidate_zernio_keys_for_account(account_id, preferred_key=preferred_api_key, account_name=account_name, platform=platform):
            verified_pairs.append({"api_key": k, "account_id": account_id})

    p_enc = urllib.parse.quote(str(post_id).strip(), safe="")
    c_enc = urllib.parse.quote(str(comment_id).strip(), safe="")
    url = f"{ZERNIO_BASE_URL}/inbox/comments/{p_enc}/{c_enc}/private-reply"
    last_result: Dict[str, Any] = {"status_code": 500, "data": {}, "raw_text": "No External API key available."}
    best_non_404_result: Optional[Dict[str, Any]] = None

    eff_text = (dm_msg or "").strip()
    if not eff_text and media_name:
        eff_text = f"📎 {media_name}"

    for pair in verified_pairs:
        k = pair["api_key"]
        eff_acc_id = pair["account_id"]
        body: Dict[str, Any] = {
            "accountId": eff_acc_id,
            "message": eff_text
        }
        try:
            resp = HTTP_SESSION.post(url, headers=get_zernio_headers(k), json=body, timeout=20)
            try:
                data = resp.json()
            except Exception:
                data = {}
            res_obj = {
                "status_code": resp.status_code,
                "data": data,
                "raw_text": resp.text,
                "used_account_id": eff_acc_id,
                "used_api_key": k
            }
            if resp.status_code in (200, 201):
                CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][str(eff_acc_id)] = k
                return res_obj

            last_result = res_obj
            err_code = str((data or {}).get("code") or "").strip().lower() if isinstance(data, dict) else ""
            if err_code != "account_not_found":
                best_non_404_result = res_obj
        except Exception as e:
            last_result = {"status_code": 500, "data": {}, "raw_text": str(e)}

    return best_non_404_result or last_result


@router.post("/api/comments/send_dm")
def send_dm_to_commenter(payload: CommentSendDmPayload):
    dm_msg = _sanitize_outbound_social_or_email_text(payload.message)
    payload.message = dm_msg
    has_file_or_media = bool((payload.file_id or "").strip() or (payload.media_url or "").strip())
    if not dm_msg and not has_file_or_media:
        return {"status": "error", "message": "Please type a Direct Message or attach a file before sending."}

    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, caption, scheduled_time,
                           external_post_id, permalink_url, status_message
                    FROM glennbot_scheduled_posts
                    WHERE id = :id
                """),
                {"id": payload.record_id}
            ).mappings().first()

        if not row:
            return {"status": "error", "message": "Post record not found in database."}

        r_dict = dict(row)
        if not is_post_account_connected(r_dict):
            return {
                "status": "error",
                "message": "This social media page/account is no longer connected in GlennBot."
            }

        rec_id_str = str(payload.record_id or "").strip()
        is_ext_post = rec_id_str.startswith("post_ext_")
        platform = (r_dict.get("platform") or "").strip().lower()
        if platform not in ("facebook", "instagram"):
            return {
                "status": "error",
                "message": "Send a DM from comments is only supported on Facebook and Instagram."
            }

        page_id = str(r_dict.get("page_id") or "").strip()
        acc_name = (r_dict.get("account_name") or "").strip()
        ext_id = extract_external_post_id(r_dict)

        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        post_entry = posts_store.get(rec_id_str) or {}
        parent_comm, target_sub_reply = find_parent_and_target_comment(post_entry, str(payload.comment_id))
        cached_comm = parent_comm or (post_entry.get("comments") or {}).get(str(payload.comment_id))

        z_info = resolve_zernio_post_identifiers(r_dict, force=False)
        if not z_info.get("inbox_post_id") or not z_info.get("zernio_account_id"):
            z_info = resolve_zernio_post_identifiers(r_dict, force=True)

        # Strictly validate cached zernio_account_id & API key against the post's actual Page
        valid_page_ids = _collect_valid_account_ids_for_page(platform, page_id, acc_name)
        cached_z_acc = str((cached_comm or {}).get("zernio_account_id") or "").strip()
        if cached_z_acc and valid_page_ids and cached_z_acc not in valid_page_ids:
            cached_z_acc = ""

        z_acc_id = str(z_info.get("zernio_account_id") or cached_z_acc or page_id).strip()
        if valid_page_ids and z_acc_id not in valid_page_ids:
            z_acc_id = str(z_info.get("zernio_account_id") or page_id).strip()

        bound_page_key = get_zernio_key_for_account(page_id, account_name=acc_name, platform=platform)
        pref_key = str(bound_page_key or z_info.get("zernio_api_key") or (cached_comm or {}).get("zernio_api_key") or "").strip()

        resolved_media = _resolve_vault_file_for_dm_or_comment(
            file_id=payload.file_id or "",
            media_url=payload.media_url or "",
            platform=platform,
            account_id=z_acc_id or page_id,
            preferred_api_key=pref_key,
            filename=payload.filename or "",
            media_type=payload.media_type or ""
        )
        resolved_media_url = ""
        resolved_media_type = "file"
        resolved_media_name = ""
        resolved_attachments: List[Dict[str, Any]] = []
        if resolved_media and resolved_media.get("url"):
            resolved_media_url = str(resolved_media["url"]).strip()
            resolved_media_type = str(resolved_media.get("type") or "file").strip()
            resolved_media_name = str(resolved_media.get("filename") or "attachment").strip()
            resolved_attachments.append({
                "type": resolved_media_type,
                "url": resolved_media_url,
                "name": resolved_media_name,
                "file_id": str(resolved_media.get("file_id") or ""),
                "gdrive_file_id": str(resolved_media.get("gdrive_file_id") or ""),
                "content_type": str(resolved_media.get("content_type") or "")
            })

        raw_target_cid = str(payload.comment_id or "").strip()
        explicit_parent_cid = str(
            (parent_comm or {}).get("comment_id")
            or (cached_comm or {}).get("parent_comment_id")
            or (cached_comm or {}).get("parentId")
            or (cached_comm or {}).get("parent_id")
            or raw_target_cid
        ).strip()
        parent_cid = explicit_parent_cid or raw_target_cid

        commenter_author_id = str(
            (target_sub_reply or {}).get("author_id")
            or (cached_comm or {}).get("author_id")
            or ""
        ).strip()
        commenter_author_name = str(
            (target_sub_reply or {}).get("author_name")
            or (cached_comm or {}).get("author_name")
            or ""
        ).strip()
        commenter_author_avatar = str(
            (target_sub_reply or {}).get("author_avatar")
            or (cached_comm or {}).get("author_avatar")
            or ""
        ).strip()

        # Helper to discover the commenter's conversationId strictly on the SAME Social Media Page
        def _discover_commenter_conversations(hint_conv_id: str = "", hint_acc_id: str = "", hint_api_key: str = "") -> List[Tuple[str, str, str]]:
            """
            Returns ordered list of (api_key, zernio_account_id, conversation_id) candidates for this commenter,
            strictly scoped to the post's Social Media Page (`page_id` / `acc_name`).
            NEVER returns a conversation belonging to a different Facebook/Instagram Page.
            """
            results: List[Tuple[str, str, str]] = []
            seen_tuples = set()

            def _add_cand(k_str: str, a_str: str, c_str: str):
                k_s, a_s, c_s = (k_str or "").strip(), (a_str or "").strip(), (c_str or "").strip()
                if not k_s or not a_s or not c_s:
                    return
                if valid_page_ids and a_s not in valid_page_ids:
                    return
                for v_cid in ([c_s, c_s[5:].strip()] if c_s.startswith("conv_") and c_s[5:].strip() else [c_s]):
                    tup = (k_s, a_s, v_cid)
                    if tup not in seen_tuples:
                        seen_tuples.add(tup)
                        results.append(tup)

            verified_pairs = resolve_live_zernio_account_and_key_pairs(
                platform=platform,
                account_id=hint_acc_id or z_acc_id or page_id,
                account_name=acc_name,
                stored_z_acc_id=hint_acc_id or z_acc_id,
                preferred_key=hint_api_key or pref_key
            )
            if hint_api_key and hint_acc_id and (not valid_page_ids or hint_acc_id in valid_page_ids):
                if not any(p["api_key"] == hint_api_key and p["account_id"] == hint_acc_id for p in verified_pairs):
                    verified_pairs.insert(0, {"api_key": hint_api_key, "account_id": hint_acc_id})

            if hint_conv_id:
                for pair in verified_pairs:
                    _add_cand(pair["api_key"], pair["account_id"], hint_conv_id)

            target_name_norm = _normalize_participant_name_key(commenter_author_name)

            # 1. Live Zernio conversations lookup (newest first) strictly on verified_pairs for this Page
            for pair in verified_pairs:
                p_key = pair["api_key"]
                p_acc = pair["account_id"]
                try:
                    l_resp = HTTP_SESSION.get(
                        f"{ZERNIO_BASE_URL}/inbox/conversations",
                        params={"accountId": p_acc, "limit": 60},
                        headers=get_zernio_headers(p_key),
                        timeout=14
                    )
                    if l_resp.status_code == 200:
                        live_convs = extract_list_from_api_payload(l_resp.json() if l_resp.text else {}) or []
                        matched_live: List[Tuple[float, str]] = []
                        recent_generic: List[Tuple[float, str]] = []
                        now_ep = time.time()
                        for idx_lc, lc in enumerate(live_convs):
                            if not isinstance(lc, dict):
                                continue
                            lc_id = str(lc.get("id") or lc.get("conversationId") or lc.get("platformConversationId") or "").strip()
                            if not lc_id:
                                continue
                            lc_pinfo = _extract_participant_from_conversation_obj(lc, p_acc, acc_name, platform)
                            lc_pid = str(lc_pinfo.get("participant_id") or lc.get("participantId") or "").strip()
                            lc_pname_norm = _normalize_participant_name_key(lc_pinfo.get("participant_name") or lc.get("participantName") or "")
                            raw_ts = lc.get("updatedTime") or lc.get("updatedAt") or lc.get("lastMessageAt") or ""
                            ts_ep = _msg_iso_to_epoch(parse_meta_timestamp(raw_ts, fallback_offset_seconds=idx_lc)["iso"])

                            id_match = bool(commenter_author_id and lc_pid and commenter_author_id == lc_pid)
                            name_match = bool(target_name_norm and lc_pname_norm and target_name_norm == lc_pname_norm)
                            if id_match or name_match:
                                matched_live.append((ts_ep, lc_id))
                                plat_lc_id = str(lc.get("platformConversationId") or "").strip()
                                if plat_lc_id and plat_lc_id != lc_id:
                                    matched_live.append((ts_ep - 0.1, plat_lc_id))
                            elif (now_ep - ts_ep) < 60 and lc_pname_norm in ("", "facebookuser", "instagramuser", "metauser", "user"):
                                recent_generic.append((ts_ep, lc_id))

                        matched_live.sort(key=lambda x: x[0], reverse=True)
                        for _, m_cid in matched_live:
                            _add_cand(p_key, p_acc, m_cid)
                        if not matched_live and recent_generic:
                            recent_generic.sort(key=lambda x: x[0], reverse=True)
                            for _, g_cid in recent_generic[:2]:
                                _add_cand(p_key, p_acc, g_cid)
                except Exception:
                    pass

            # 2. Local CLOUDINARY_MESSAGES_STORE lookup — STRICTLY filtered to the same Social Media Page!
            if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
                load_messages_store_from_cloudinary()
            convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
            for c_obj in convs_store.values():
                if not isinstance(c_obj, dict):
                    continue
                if (c_obj.get("platform") or "").strip().lower() != platform:
                    continue
                # CRITICAL: Verify this conversation actually belongs to the SAME Page as the post!
                c_db_acc = str(c_obj.get("account_id") or "").strip()
                c_z_acc = str(c_obj.get("zernio_account_id") or "").strip()
                c_acc_name = str(c_obj.get("account_name") or "").strip()
                belongs_to_same_page = False
                if valid_page_ids and ((c_db_acc and c_db_acc in valid_page_ids) or (c_z_acc and c_z_acc in valid_page_ids)):
                    belongs_to_same_page = True
                elif acc_name and c_acc_name and _is_same_social_page_name(c_acc_name, acc_name):
                    belongs_to_same_page = True
                if not belongs_to_same_page:
                    continue

                c_part_id = str(c_obj.get("participant_id") or "").strip()
                c_part_norm = _normalize_participant_name_key(c_obj.get("participant_name") or "")
                if (commenter_author_id and c_part_id and commenter_author_id == c_part_id) or (target_name_norm and c_part_norm and target_name_norm == c_part_norm):
                    for cid_cand in (
                        c_obj.get("conversation_id"),
                        c_obj.get("zernio_conversation_id"),
                        c_obj.get("platform_conversation_id"),
                        *(c_obj.get("alternate_conversation_ids") or [])
                    ):
                        if cid_cand:
                            for cp in verified_pairs:
                                _add_cand(cp["api_key"], cp["account_id"], str(cid_cand))

            return results

        def _deliver_attachment_to_commenter(hint_conv_id: str = "", hint_acc_id: str = "", hint_api_key: str = "", caption_text: str = "") -> Optional[Dict[str, Any]]:
            """
            Sends the native file/image/video/audio attachment to the commenter's conversation thread
            via `POST /v1/inbox/conversations/{conversationId}/messages`.
            """
            if not resolved_attachments:
                return None
            att = resolved_attachments[0]
            candidates = _discover_commenter_conversations(hint_conv_id=hint_conv_id, hint_acc_id=hint_acc_id, hint_api_key=hint_api_key)
            for c_key, c_acc, c_cid in candidates:
                safe_cid = urllib.parse.quote(c_cid, safe="")
                send_ep = f"{ZERNIO_BASE_URL}/inbox/conversations/{safe_cid}/messages"
                try:
                    if caption_text and platform in ("facebook", "instagram"):
                        HTTP_SESSION.post(
                            send_ep,
                            headers=get_zernio_headers(c_key),
                            json={"accountId": c_acc, "message": caption_text},
                            timeout=20
                        )
                        att_resp = _post_zernio_conversation_attachment_request(send_ep, c_key, c_acc, att, caption_text="")
                    else:
                        att_resp = _post_zernio_conversation_attachment_request(send_ep, c_key, c_acc, att, caption_text=caption_text)
                    if att_resp.status_code in (200, 201):
                        try:
                            a_data = att_resp.json()
                        except Exception:
                            a_data = {}
                        print(f"[📎->✅ COMMENTER DM NATIVE ATTACHMENT DELIVERED] {att.get('name')} -> Conv {c_cid}")
                        return {
                            "status_code": att_resp.status_code,
                            "data": a_data,
                            "raw_text": att_resp.text,
                            "used_account_id": c_acc,
                            "used_api_key": c_key,
                            "conversation_id": c_cid
                        }
                except Exception as e:
                    print(f"[⚠️ COMMENTER DM ATTACHMENT SEND WARNING] ({c_cid}): {e}")
            return None

        # For Private Reply, try the exact comment/reply ID clicked first, then parent_cid
        candidate_comment_ids = []
        for c_cand in (raw_target_cid, parent_cid):
            if c_cand and c_cand not in candidate_comment_ids:
                candidate_comment_ids.append(c_cand)

        permalink_str = str(r_dict.get("permalink_url") or z_info.get("permalink_url") or "").strip()
        fbid_from_link = ""
        if permalink_str:
            m_fbid = re.search(r"(?:fbid=|story_fbid=|/posts/|/videos/|/reel/|/video/)(\d+)", permalink_str)
            if m_fbid:
                fbid_from_link = m_fbid.group(1).strip()

        base_post_ids = []
        for pid in [
            (cached_comm or {}).get("zernio_post_id"),
            z_info.get("inbox_post_id"),
            z_info.get("inbox_plat_id"),
            z_info.get("platform_post_id"),
            z_info.get("zernio_post_id"),
            ext_id,
            fbid_from_link
        ]:
            p_str = str(pid or "").strip()
            if p_str and p_str != "OK" and p_str not in base_post_ids:
                base_post_ids.append(p_str)

        def _expand_post_ids_for_dm(raw_pids: List[str], target_acc_id: str, target_acc_name: str) -> List[str]:
            expanded: List[str] = []
            fb_prefixes: List[str] = []
            if platform == "facebook":
                for force_f in (False, True):
                    for za in fetch_zernio_connected_accounts(platform="facebook", force=force_f):
                        if not isinstance(za, dict):
                            continue
                        za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
                        if za_plat_id and _does_zernio_account_match_page(za, page_id, target_acc_id, target_acc_name or acc_name):
                            if za_plat_id not in fb_prefixes:
                                fb_prefixes.append(za_plat_id)
                    if fb_prefixes:
                        break
                if page_id and len(page_id) != 24 and page_id.isdigit() and page_id not in fb_prefixes:
                    fb_prefixes.append(page_id)

            for p_item in raw_pids:
                if p_item not in expanded:
                    expanded.append(p_item)
                if platform == "facebook":
                    if "_" in p_item:
                        bare_suffix = p_item.split("_")[-1].strip()
                        for fb_p in fb_prefixes:
                            re_prefixed = f"{fb_p}_{bare_suffix}"
                            if re_prefixed not in expanded:
                                expanded.append(re_prefixed)
                        if bare_suffix and bare_suffix not in expanded:
                            expanded.append(bare_suffix)
                    elif len(p_item) != 24:
                        for fb_p in fb_prefixes:
                            comp = f"{fb_p}_{p_item}"
                            if comp not in expanded:
                                expanded.append(comp)
            return expanded

        def _expand_comment_ids_for_dm(target_pid: str, base_cids: List[str], extra_format: bool = False) -> List[str]:
            expanded_cids: List[str] = []
            for c_id in base_cids:
                if c_id and c_id not in expanded_cids:
                    expanded_cids.append(c_id)
            if not extra_format or platform != "facebook":
                return expanded_cids

            post_suffix = target_pid.split("_")[-1].strip() if "_" in target_pid else target_pid.strip()
            prefix_candidates = []
            for pref in (post_suffix, fbid_from_link, target_pid):
                if pref and len(pref) != 24 and pref not in prefix_candidates:
                    prefix_candidates.append(pref)

            for c_id in list(expanded_cids):
                c_suffix = c_id.split("_")[-1].strip() if "_" in c_id else c_id.strip()
                if not c_suffix:
                    continue
                for pref in prefix_candidates:
                    if pref != c_suffix:
                        re_cid = f"{pref}_{c_suffix}"
                        if re_cid not in expanded_cids:
                            expanded_cids.append(re_cid)
                if c_suffix not in expanded_cids:
                    expanded_cids.append(c_suffix)
            return expanded_cids

        def _finalize_successful_dm(z_res: Dict[str, Any], attachment_already_sent: bool = False):
            r_data = z_res.get("data") if isinstance(z_res.get("data"), dict) else {}
            inner = r_data.get("data") if isinstance(r_data.get("data"), dict) else r_data
            msg_id = str((inner or {}).get("messageId") or (inner or {}).get("id") or f"dm_{int(time.time()*1000)}")
            dm_conv_id = str(
                z_res.get("conversation_id")
                or (inner or {}).get("conversationId")
                or (inner or {}).get("threadId")
                or (inner or {}).get("recipientId")
                or r_data.get("conversationId")
                or ""
            ).strip()

            # If a file was attached and we just sent the text Private Reply, immediately dispatch
            # the native attachment to the commenter's conversation thread!
            if resolved_attachments and not attachment_already_sent:
                att_delivery = _deliver_attachment_to_commenter(
                    hint_conv_id=dm_conv_id,
                    hint_acc_id=str(z_res.get("used_account_id") or z_acc_id or page_id),
                    hint_api_key=str(z_res.get("used_api_key") or pref_key),
                    caption_text=""
                )
                if att_delivery and att_delivery.get("conversation_id") and not dm_conv_id:
                    dm_conv_id = str(att_delivery["conversation_id"])

            preview_dm_label = dm_msg if dm_msg else (f"📎 {resolved_media_name}" if resolved_media_name else "Direct Message sent")
            if target_sub_reply is not None and isinstance(target_sub_reply, dict):
                target_sub_reply["dm_sent"] = True
                target_sub_reply["last_dm_message"] = preview_dm_label
            elif cached_comm is not None and isinstance(cached_comm, dict):
                cached_comm["dm_sent"] = True
                cached_comm["last_dm_message"] = preview_dm_label
            save_comments_store_async()
            mark_comments_as_read(MarkReadPayload(comment_ids=[raw_target_cid, parent_cid], record_id=payload.record_id, platform=platform))

            # Register the commenter's real name ('Glenn Tasico') so any Private Reply webhook or sync
            # immediately maps 'Facebook User' -> 'Glenn Tasico' and merges into their conversation
            register_private_reply_recipient(
                platform=platform,
                account_id=page_id or z_acc_id,
                account_name=acc_name,
                author_name=commenter_author_name,
                author_id=commenter_author_id,
                author_avatar=commenter_author_avatar,
                message_text=preview_dm_label,
                conversation_id=dm_conv_id,
                message_id=msg_id
            )

            # Immediately upsert/merge into CLOUDINARY_MESSAGES_STORE under the commenter's real name
            try:
                now_ts_info = parse_meta_timestamp(datetime.now(pytz.timezone("Asia/Manila")).isoformat())
                out_msg_obj = {
                    "id": msg_id,
                    "platform_message_id": msg_id,
                    "sender_id": page_id or z_acc_id,
                    "sender_name": acc_name or platform.capitalize(),
                    "sender_avatar": "",
                    "is_own": True,
                    "message": dm_msg,
                    "attachments": resolved_attachments,
                    "created_iso": now_ts_info["iso"],
                    "display_time": now_ts_info["display"]
                }
                convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
                existing_c = _find_existing_conversation_in_store(
                    convs_store,
                    db_acc_id=page_id or z_acc_id,
                    acc_name=acc_name,
                    platform=platform,
                    candidate_conv_ids=[dm_conv_id] if dm_conv_id else [],
                    participant_id=commenter_author_id,
                    participant_name=commenter_author_name
                )
                if existing_c is not None:
                    if _normalize_participant_name_key(commenter_author_name):
                        existing_c["participant_name"] = commenter_author_name
                    if commenter_author_id and not existing_c.get("participant_id"):
                        existing_c["participant_id"] = commenter_author_id
                    if commenter_author_avatar and not existing_c.get("participant_avatar"):
                        existing_c["participant_avatar"] = commenter_author_avatar
                    if dm_conv_id:
                        alt_l = list(existing_c.get("alternate_conversation_ids") or [])
                        if dm_conv_id not in alt_l:
                            alt_l.append(dm_conv_id)
                        existing_c["alternate_conversation_ids"] = alt_l
                    existing_c["messages"] = _deduplicate_messages_list((existing_c.get("messages") or []) + [out_msg_obj])
                    existing_c["last_message_text"] = preview_dm_label
                    existing_c["last_message_is_own"] = True
                    existing_c["updated_iso"] = now_ts_info["iso"]
                    existing_c["display_time"] = now_ts_info["display"]
                    existing_c["is_read"] = True
                    existing_c["unread_count"] = 0
                    existing_c["hidden"] = False
                deduplicate_and_merge_conversations_store()
                save_messages_store_async()
            except Exception as store_err:
                print(f"[⚠️ PRIVATE REPLY STORE UPSERT WARNING]: {store_err}")

            threading.Thread(target=sync_all_messages_to_cloudinary, kwargs={"force_refresh": True}, daemon=True).start()
            return {
                "status": "success",
                "message_id": msg_id,
                "comment_id": raw_target_cid
            }

        # Pass 0: If user attached a file WITHOUT typing text (`dm_msg == ""`) and an active conversation
        # with this commenter already exists on THIS SAME Page, send the pure native attachment directly!
        if resolved_attachments and not dm_msg:
            direct_att_res = _deliver_attachment_to_commenter(
                hint_conv_id="",
                hint_acc_id=z_acc_id or page_id,
                hint_api_key=pref_key,
                caption_text=""
            )
            if direct_att_res:
                return _finalize_successful_dm(direct_att_res, attachment_already_sent=True)

        cand_post_ids = _expand_post_ids_for_dm(base_post_ids, z_acc_id or page_id, acc_name)
        last_err = "Could not resolve External API Post or Comment ID for Private Reply."
        tried_dm_combos = set()

        # Pass 1: Standard Private Reply Loop (with full comment ID format expansion for all posts)
        for target_pid in cand_post_ids:
            p1_cids = _expand_comment_ids_for_dm(target_pid, candidate_comment_ids, extra_format=True)
            for api_cid in p1_cids:
                tried_dm_combos.add((target_pid, z_acc_id, api_cid))
                z_res = send_zernio_private_reply(
                    target_pid,
                    z_acc_id,
                    api_cid,
                    dm_msg,
                    preferred_api_key=pref_key,
                    platform=platform,
                    account_name=acc_name,
                    media_url=resolved_media_url,
                    media_type=resolved_media_type,
                    media_name=resolved_media_name
                )
                if z_res["status_code"] in (200, 201):
                    return _finalize_successful_dm(z_res, attachment_already_sent=False)
                last_err = str(z_res["data"] or z_res["raw_text"])

        # Refresh commented posts list in case the Zernio inbox post ID wasn't cached yet
        known_dm_suffixes = {p.split("_")[-1].strip() for p in base_post_ids if p and p != "OK"}
        for cp in get_zernio_commented_posts_list(force=True):
            if not isinstance(cp, dict):
                continue
            cp_plat = (cp.get("platform") or "").strip().lower()
            if cp_plat and cp_plat != platform:
                continue
            cp_id = str(cp.get("id") or cp.get("_id") or cp.get("postId") or "").strip()
            cp_plat_id = str(cp.get("platformPostId") or "").strip()
            cp_suffix = cp_plat_id.split("_")[-1].strip() if "_" in cp_plat_id else cp_plat_id
            if bool({cp_id, cp_plat_id, cp_suffix} & (set(base_post_ids) | known_dm_suffixes)):
                for new_p in (cp_id, cp_plat_id):
                    if new_p and new_p not in base_post_ids:
                        base_post_ids.insert(0, new_p)

        # Pass 2: Page-Scoped Account Discovery — strictly locked to the post's Social Media Page!
        # NEVER tries unrelated Facebook/Instagram Pages so another Page can never send the DM.
        all_dm_plat_accounts = fetch_zernio_connected_accounts(platform=platform or None, force=True)
        matching_dm_accounts = [
            za for za in all_dm_plat_accounts
            if isinstance(za, dict) and _does_zernio_account_match_page(za, page_id, z_acc_id, acc_name)
        ]

        for za in matching_dm_accounts:
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_key = str(za.get("_zernio_api_key") or "").strip()
            za_dname = str(za.get("displayName") or za.get("name") or za.get("username") or acc_name or platform.upper()).strip()
            if not za_id or not za_key:
                continue

            za_post_ids = _expand_post_ids_for_dm(base_post_ids, za_id, za_dname)
            for target_pid in za_post_ids:
                p2_cids = _expand_comment_ids_for_dm(target_pid, candidate_comment_ids, extra_format=True)
                for api_cid in p2_cids:
                    if (target_pid, za_id, api_cid) in tried_dm_combos:
                        continue
                    tried_dm_combos.add((target_pid, za_id, api_cid))
                    z_res = send_zernio_private_reply(
                        target_pid,
                        za_id,
                        api_cid,
                        dm_msg,
                        preferred_api_key=za_key,
                        platform=platform,
                        account_name=acc_name or za_dname,
                        media_url=resolved_media_url,
                        media_type=resolved_media_type,
                        media_name=resolved_media_name
                    )
                    if z_res["status_code"] in (200, 201):
                        return _finalize_successful_dm(z_res, attachment_already_sent=False)
                    err_data = z_res.get("data")
                    err_code = str((err_data or {}).get("code") or "").strip().lower() if isinstance(err_data, dict) else ""
                    if err_code != "account_not_found":
                        last_err = str(z_res["data"] or z_res["raw_text"])

        # Pass 2.5: Live Comment Thread Inspection on the post's Page to resolve canonical commentId
        target_dm_cid_suffixes = {c.split("_")[-1].strip() for c in candidate_comment_ids if c}
        for za in matching_dm_accounts:
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_key = str(za.get("_zernio_api_key") or "").strip()
            za_dname = str(za.get("displayName") or za.get("name") or za.get("username") or acc_name or platform.upper()).strip()
            if not za_id or not za_key:
                continue
            za_post_ids = _expand_post_ids_for_dm(base_post_ids, za_id, za_dname)
            for target_pid in za_post_ids:
                try:
                    encoded_pid = urllib.parse.quote(str(target_pid), safe="")
                    c_url = f"{ZERNIO_BASE_URL}/inbox/comments/{encoded_pid}?accountId={urllib.parse.quote(za_id, safe='')}"
                    c_resp = HTTP_SESSION.get(c_url, headers=get_zernio_headers(za_key), timeout=12)
                    if c_resp.status_code != 200:
                        continue
                    live_comments = extract_list_from_api_payload(c_resp.json()) or []
                    discovered_live_cids: List[str] = []
                    for lc in live_comments:
                        if not isinstance(lc, dict):
                            continue
                        lc_id = str(lc.get("id") or lc.get("_id") or lc.get("commentId") or "").strip()
                        lc_parent = str(lc.get("parentId") or lc.get("parent_id") or lc.get("parentCommentId") or "").strip()
                        lc_suffix = lc_id.split("_")[-1].strip() if "_" in lc_id else lc_id
                        if lc_id and (lc_id in candidate_comment_ids or lc_suffix in target_dm_cid_suffixes):
                            if lc_id not in discovered_live_cids:
                                discovered_live_cids.append(lc_id)
                            if lc_parent and lc_parent not in discovered_live_cids:
                                discovered_live_cids.append(lc_parent)
                        for sub_r in (lc.get("replies") or lc.get("children") or []):
                            if not isinstance(sub_r, dict):
                                continue
                            sr_id = str(sub_r.get("id") or sub_r.get("_id") or sub_r.get("commentId") or "").strip()
                            sr_suffix = sr_id.split("_")[-1].strip() if "_" in sr_id else sr_id
                            if sr_id and (sr_id in candidate_comment_ids or sr_suffix in target_dm_cid_suffixes):
                                if sr_id not in discovered_live_cids:
                                    discovered_live_cids.append(sr_id)
                                if lc_id and lc_id not in discovered_live_cids:
                                    discovered_live_cids.append(lc_id)
                    for live_cid in discovered_live_cids:
                        if (target_pid, za_id, live_cid) in tried_dm_combos:
                            continue
                        tried_dm_combos.add((target_pid, za_id, live_cid))
                        z_res = send_zernio_private_reply(
                            target_pid,
                            za_id,
                            live_cid,
                            dm_msg,
                            preferred_api_key=za_key,
                            platform=platform,
                            account_name=acc_name or za_dname,
                            media_url=resolved_media_url,
                            media_type=resolved_media_type,
                            media_name=resolved_media_name
                        )
                        if z_res["status_code"] in (200, 201):
                            return _finalize_successful_dm(z_res, attachment_already_sent=False)
                except Exception:
                    continue

        # Pass 3: Fallback to Existing DM Conversation ONLY if a thread with this commenter already exists on THIS SAME Page
        if resolved_attachments:
            fallback_att_res = _deliver_attachment_to_commenter(
                hint_conv_id="",
                hint_acc_id=z_acc_id or page_id,
                hint_api_key=pref_key,
                caption_text=dm_msg
            )
            if fallback_att_res:
                return _finalize_successful_dm(fallback_att_res, attachment_already_sent=True)
        else:
            for c_key, c_acc, c_cid in _discover_commenter_conversations(hint_acc_id=z_acc_id or page_id, hint_api_key=pref_key):
                conv_ep = f"{ZERNIO_BASE_URL}/inbox/conversations/{urllib.parse.quote(c_cid, safe='')}/messages"
                c_resp = HTTP_SESSION.post(
                    conv_ep,
                    headers=get_zernio_headers(c_key),
                    json={"accountId": c_acc, "message": dm_msg},
                    timeout=18
                )
                if c_resp.status_code in (200, 201):
                    try:
                        c_data = c_resp.json()
                    except Exception:
                        c_data = {}
                    return _finalize_successful_dm(
                        {"status_code": c_resp.status_code, "data": c_data, "raw_text": c_resp.text, "conversation_id": c_cid, "used_account_id": c_acc, "used_api_key": c_key},
                        attachment_already_sent=True
                    )

        return {"status": "error", "message": f"External API Private Reply (DM) Error ({platform.upper()}): {last_err}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class CommentLikePayload(BaseModel):
    record_id: str
    comment_id: str
    liked: Optional[bool] = True


class CommentHidePayload(BaseModel):
    record_id: str
    comment_id: str
    hidden: Optional[bool] = True


def send_zernio_comment_moderation_action(
    post_id: str,
    account_id: str,
    comment_id: str,
    action_type: str,
    enable: bool = True,
    preferred_api_key: str = "",
    platform: str = "",
    account_name: str = ""
) -> Dict[str, Any]:
    """
    Executes Zernio official comment moderation endpoints:
      - Like / Unlike (Facebook):
          POST   /v1/inbox/comments/{postId}/{commentId}/like
          DELETE /v1/inbox/comments/{postId}/{commentId}/like
      - Hide / Unhide (Facebook, Instagram, TikTok):
          POST   /v1/inbox/comments/{postId}/{commentId}/hide
          DELETE /v1/inbox/comments/{postId}/{commentId}/hide
    Passes `accountId` in both query params and JSON body for 100% compatibility.
    """
    verified_pairs = resolve_live_zernio_account_and_key_pairs(
        platform=platform,
        account_id=account_id,
        account_name=account_name,
        stored_z_acc_id=account_id,
        preferred_key=preferred_api_key
    )
    if not verified_pairs and account_id:
        for k in get_candidate_zernio_keys_for_account(account_id, preferred_key=preferred_api_key, account_name=account_name, platform=platform):
            verified_pairs.append({"api_key": k, "account_id": account_id})

    p_enc = urllib.parse.quote(str(post_id).strip(), safe="")
    c_enc = urllib.parse.quote(str(comment_id).strip(), safe="")
    url = f"{ZERNIO_BASE_URL}/inbox/comments/{p_enc}/{c_enc}/{action_type}"
    last_result: Dict[str, Any] = {"status_code": 500, "data": {}, "raw_text": "No External API key available."}
    best_non_404_result: Optional[Dict[str, Any]] = None

    for pair in verified_pairs:
        k = pair["api_key"]
        eff_acc_id = pair["account_id"]
        headers = get_zernio_headers(k)
        params = {"accountId": eff_acc_id}
        body: Dict[str, Any] = {"accountId": eff_acc_id}
        if action_type == "hide":
            body["hidden"] = bool(enable)

        try:
            if enable:
                resp = HTTP_SESSION.post(url, params=params, headers=headers, json=body, timeout=20)
            else:
                resp = HTTP_SESSION.delete(url, params=params, headers=headers, json=body, timeout=20)
                if resp.status_code in (404, 405) and action_type == "hide":
                    resp = HTTP_SESSION.post(
                        url,
                        params=params,
                        headers=headers,
                        json={"accountId": eff_acc_id, "hidden": False, "hide": False},
                        timeout=20
                    )

            try:
                data = resp.json() if resp.text else {}
            except Exception:
                data = {}
            res_obj = {
                "status_code": resp.status_code,
                "data": data,
                "raw_text": resp.text,
                "used_account_id": eff_acc_id,
                "used_api_key": k
            }
            if resp.status_code in (200, 201, 204):
                CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][str(eff_acc_id)] = k
                return res_obj

            last_result = res_obj
            err_code = str((data or {}).get("code") or "").strip().lower() if isinstance(data, dict) else ""
            if err_code != "account_not_found":
                best_non_404_result = res_obj
        except Exception as e:
            last_result = {"status_code": 500, "data": {}, "raw_text": str(e)}

    return best_non_404_result or last_result


def _perform_comment_moderation(record_id: str, comment_id: str, action_type: str, enable: bool) -> Dict[str, Any]:
    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, caption, scheduled_time,
                           external_post_id, permalink_url, status_message
                    FROM glennbot_scheduled_posts
                    WHERE id = :id
                """),
                {"id": record_id}
            ).mappings().first()

        if not row:
            return {"status": "error", "message": "Post record not found in database."}

        r_dict = dict(row)
        if not is_post_account_connected(r_dict):
            return {
                "status": "error",
                "message": "This social media page/account is no longer connected in GlennBot."
            }

        rec_id_str = str(record_id or "").strip()
        is_ext_post = rec_id_str.startswith("post_ext_")
        platform = (r_dict.get("platform") or "").strip().lower()

        if action_type == "like" and platform != "facebook":
            return {
                "status": "error",
                "message": "Comment Like via External API is only supported on Facebook."
            }
        if action_type == "hide" and platform not in ("facebook", "instagram", "tiktok"):
            return {
                "status": "error",
                "message": "Comment Hide via External API is only supported on Facebook, Instagram, and TikTok."
            }

        page_id = str(r_dict.get("page_id") or "").strip()
        acc_name = (r_dict.get("account_name") or "").strip()
        ext_id = extract_external_post_id(r_dict)

        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        post_entry = posts_store.get(rec_id_str) or {}
        parent_comm, target_sub_reply = find_parent_and_target_comment(post_entry, str(comment_id))
        cached_comm = parent_comm or (post_entry.get("comments") or {}).get(str(comment_id))

        z_info = resolve_zernio_post_identifiers(r_dict, force=False)
        if is_ext_post and not z_info.get("inbox_post_id"):
            z_info = resolve_zernio_post_identifiers(r_dict, force=True)

        z_acc_id = str((cached_comm or {}).get("zernio_account_id") or z_info.get("zernio_account_id") or page_id).strip()
        pref_key = str((cached_comm or {}).get("zernio_api_key") or z_info.get("zernio_api_key") or "").strip()

        raw_target_cid = str(comment_id or "").strip()
        explicit_parent_cid = str(
            (parent_comm or {}).get("comment_id")
            or (cached_comm or {}).get("parent_comment_id")
            or (cached_comm or {}).get("parentId")
            or (cached_comm or {}).get("parent_id")
            or raw_target_cid
        ).strip()
        parent_cid = explicit_parent_cid or raw_target_cid

        # For Like and Hide, always target the exact clicked comment/reply ID first!
        candidate_comment_ids: List[str] = []
        for c_cand in (raw_target_cid, parent_cid):
            clean_c = c_cand.split("_")[-1] if (platform == "tiktok" and "_" in c_cand) else c_cand
            if clean_c and clean_c not in candidate_comment_ids:
                candidate_comment_ids.append(clean_c)
            if c_cand and c_cand not in candidate_comment_ids:
                candidate_comment_ids.append(c_cand)

        permalink_str = str(r_dict.get("permalink_url") or z_info.get("permalink_url") or "").strip()
        fbid_from_link = ""
        if permalink_str:
            m_fbid = re.search(r"(?:fbid=|story_fbid=|/posts/|/videos/|/reel/|/video/)(\d+)", permalink_str)
            if m_fbid:
                fbid_from_link = m_fbid.group(1).strip()

        base_post_ids: List[str] = []
        for pid in [
            (cached_comm or {}).get("zernio_post_id"),
            z_info.get("inbox_post_id"),
            z_info.get("inbox_plat_id"),
            z_info.get("platform_post_id"),
            z_info.get("zernio_post_id"),
            ext_id,
            fbid_from_link
        ]:
            p_str = str(pid or "").strip()
            if p_str and p_str != "OK" and p_str not in base_post_ids:
                base_post_ids.append(p_str)

        def _expand_post_ids_for_mod(raw_pids: List[str], target_acc_id: str, target_acc_name: str) -> List[str]:
            expanded: List[str] = []
            fb_prefixes: List[str] = []
            if platform == "facebook":
                t_name_clean = (target_acc_name or "").strip().lstrip("@").lower()
                for za in fetch_zernio_connected_accounts(platform="facebook", force=False):
                    if not isinstance(za, dict):
                        continue
                    za_id = str(za.get("_id") or za.get("id") or "").strip()
                    za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
                    za_uname = (za.get("username") or "").strip().lstrip("@").lower()
                    za_dname = (za.get("displayName") or za.get("name") or "").strip().lstrip("@").lower()
                    if za_plat_id and (
                        (target_acc_id and target_acc_id in (za_id, za_plat_id))
                        or (t_name_clean and t_name_clean in (za_uname, za_dname))
                    ):
                        if za_plat_id not in fb_prefixes:
                            fb_prefixes.append(za_plat_id)

            for p_item in raw_pids:
                if p_item not in expanded:
                    expanded.append(p_item)
                if platform == "facebook":
                    if "_" in p_item:
                        bare_suffix = p_item.split("_")[-1].strip()
                        for fb_p in fb_prefixes:
                            re_prefixed = f"{fb_p}_{bare_suffix}"
                            if re_prefixed not in expanded:
                                expanded.append(re_prefixed)
                        if bare_suffix and bare_suffix not in expanded:
                            expanded.append(bare_suffix)
                    elif len(p_item) != 24:
                        for fb_p in fb_prefixes:
                            comp = f"{fb_p}_{p_item}"
                            if comp not in expanded:
                                expanded.append(comp)
            return expanded

        def _expand_comment_ids_for_mod(target_pid: str, base_cids: List[str], extra_format: bool = False) -> List[str]:
            expanded_cids: List[str] = []
            for c_id in base_cids:
                if c_id and c_id not in expanded_cids:
                    expanded_cids.append(c_id)
            if not extra_format or platform != "facebook":
                return expanded_cids

            post_suffix = target_pid.split("_")[-1].strip() if "_" in target_pid else target_pid.strip()
            prefix_candidates = []
            for pref in (post_suffix, fbid_from_link, target_pid):
                if pref and len(pref) != 24 and pref not in prefix_candidates:
                    prefix_candidates.append(pref)

            for c_id in list(expanded_cids):
                c_suffix = c_id.split("_")[-1].strip() if "_" in c_id else c_id.strip()
                if not c_suffix:
                    continue
                for pref in prefix_candidates:
                    if pref != c_suffix:
                        re_cid = f"{pref}_{c_suffix}"
                        if re_cid not in expanded_cids:
                            expanded_cids.append(re_cid)
                if c_suffix not in expanded_cids:
                    expanded_cids.append(c_suffix)
            return expanded_cids

        def _finalize_moderation_success():
            target_obj = target_sub_reply if (target_sub_reply is not None and isinstance(target_sub_reply, dict)) else (cached_comm if isinstance(cached_comm, dict) else None)
            if target_obj is not None:
                if action_type == "like":
                    prev_liked = bool(target_obj.get("is_liked"))
                    target_obj["is_liked"] = bool(enable)
                    if "like_count" in target_obj:
                        cur_cnt = int(target_obj.get("like_count") or 0)
                        if enable and not prev_liked:
                            target_obj["like_count"] = cur_cnt + 1
                        elif (not enable) and prev_liked and cur_cnt > 0:
                            target_obj["like_count"] = cur_cnt - 1
                elif action_type == "hide":
                    target_obj["is_hidden"] = bool(enable)
            save_comments_store_async()
            mark_comments_as_read(MarkReadPayload(comment_ids=[raw_target_cid, parent_cid], record_id=record_id, platform=platform))
            return {
                "status": "success",
                "comment_id": raw_target_cid,
                "action": action_type,
                "is_liked": bool(enable) if action_type == "like" else bool((target_obj or {}).get("is_liked")),
                "is_hidden": bool(enable) if action_type == "hide" else bool((target_obj or {}).get("is_hidden"))
            }

        cand_post_ids = _expand_post_ids_for_mod(base_post_ids, z_acc_id or page_id, acc_name)
        last_err = f"Could not resolve External API Post or Comment ID for {action_type}."
        tried_combos = set()

        # Pass 1: Standard Moderation Loop
        for target_pid in cand_post_ids:
            p1_cids = _expand_comment_ids_for_mod(target_pid, candidate_comment_ids, extra_format=True)
            for api_cid in p1_cids:
                tried_combos.add((target_pid, z_acc_id, api_cid))
                z_res = send_zernio_comment_moderation_action(
                    target_pid,
                    z_acc_id,
                    api_cid,
                    action_type=action_type,
                    enable=enable,
                    preferred_api_key=pref_key,
                    platform=platform,
                    account_name=acc_name
                )
                if z_res["status_code"] in (200, 201, 204):
                    return _finalize_moderation_success()
                last_err = str(z_res["data"] or z_res["raw_text"])

        # Pass 2: Multi-Account / Multi-Key Discovery across commented posts & connected pages
        known_suffixes = {p.split("_")[-1].strip() for p in base_post_ids if p and p != "OK"}
        for cp in get_zernio_commented_posts_list(force=True):
            if not isinstance(cp, dict):
                continue
            cp_plat = (cp.get("platform") or "").strip().lower()
            if cp_plat and cp_plat != platform:
                continue
            cp_id = str(cp.get("id") or cp.get("_id") or cp.get("postId") or "").strip()
            cp_plat_id = str(cp.get("platformPostId") or "").strip()
            cp_suffix = cp_plat_id.split("_")[-1].strip() if "_" in cp_plat_id else cp_plat_id
            if bool({cp_id, cp_plat_id, cp_suffix} & (set(base_post_ids) | known_suffixes)):
                for new_p in (cp_id, cp_plat_id):
                    if new_p and new_p not in base_post_ids:
                        base_post_ids.insert(0, new_p)

        connected_plat_accounts = fetch_zernio_connected_accounts(platform=platform or None, force=True)
        for za in connected_plat_accounts:
            if not isinstance(za, dict):
                continue
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_key = str(za.get("_zernio_api_key") or "").strip()
            za_dname = str(za.get("displayName") or za.get("name") or za.get("username") or acc_name or platform.upper()).strip()
            if not za_id or not za_key:
                continue

            za_post_ids = _expand_post_ids_for_mod(base_post_ids, za_id, za_dname)
            for target_pid in za_post_ids:
                p2_cids = _expand_comment_ids_for_mod(target_pid, candidate_comment_ids, extra_format=True)
                for api_cid in p2_cids:
                    if (target_pid, za_id, api_cid) in tried_combos:
                        continue
                    tried_combos.add((target_pid, za_id, api_cid))
                    z_res = send_zernio_comment_moderation_action(
                        target_pid,
                        za_id,
                        api_cid,
                        action_type=action_type,
                        enable=enable,
                        preferred_api_key=za_key,
                        platform=platform,
                        account_name=za_dname
                    )
                    if z_res["status_code"] in (200, 201, 204):
                        return _finalize_moderation_success()
                    err_data = z_res.get("data")
                    err_code = str((err_data or {}).get("code") or "").strip().lower() if isinstance(err_data, dict) else ""
                    if err_code != "account_not_found":
                        last_err = str(z_res["data"] or z_res["raw_text"])

        # Pass 3: Live Comment Thread Inspection
        target_cid_suffixes = {c.split("_")[-1].strip() for c in candidate_comment_ids if c}
        for za in connected_plat_accounts:
            if not isinstance(za, dict):
                continue
            za_id = str(za.get("_id") or za.get("id") or "").strip()
            za_key = str(za.get("_zernio_api_key") or "").strip()
            za_dname = str(za.get("displayName") or za.get("name") or za.get("username") or acc_name or platform.upper()).strip()
            if not za_id or not za_key:
                continue
            za_post_ids = _expand_post_ids_for_mod(base_post_ids, za_id, za_dname)
            for target_pid in za_post_ids:
                try:
                    encoded_pid = urllib.parse.quote(str(target_pid), safe="")
                    c_url = f"{ZERNIO_BASE_URL}/inbox/comments/{encoded_pid}?accountId={urllib.parse.quote(za_id, safe='')}"
                    c_resp = HTTP_SESSION.get(c_url, headers=get_zernio_headers(za_key), timeout=12)
                    if c_resp.status_code != 200:
                        continue
                    live_comments = extract_list_from_api_payload(c_resp.json()) or []
                    discovered_live_cids: List[str] = []
                    for lc in live_comments:
                        if not isinstance(lc, dict):
                            continue
                        lc_id = str(lc.get("id") or lc.get("_id") or lc.get("commentId") or "").strip()
                        lc_suffix = lc_id.split("_")[-1].strip() if "_" in lc_id else lc_id
                        if lc_id and (lc_id in candidate_comment_ids or lc_suffix in target_cid_suffixes):
                            if lc_id not in discovered_live_cids:
                                discovered_live_cids.append(lc_id)
                        for sub_r in (lc.get("replies") or lc.get("children") or []):
                            if not isinstance(sub_r, dict):
                                continue
                            sr_id = str(sub_r.get("id") or sub_r.get("_id") or sub_r.get("commentId") or "").strip()
                            sr_suffix = sr_id.split("_")[-1].strip() if "_" in sr_id else sr_id
                            if sr_id and (sr_id in candidate_comment_ids or sr_suffix in target_cid_suffixes):
                                if sr_id not in discovered_live_cids:
                                    discovered_live_cids.append(sr_id)
                    for live_cid in discovered_live_cids:
                        if (target_pid, za_id, live_cid) in tried_combos:
                            continue
                        tried_combos.add((target_pid, za_id, live_cid))
                        z_res = send_zernio_comment_moderation_action(
                            target_pid,
                            za_id,
                            live_cid,
                            action_type=action_type,
                            enable=enable,
                            preferred_api_key=za_key,
                            platform=platform,
                            account_name=za_dname
                        )
                        if z_res["status_code"] in (200, 201, 204):
                            return _finalize_moderation_success()
                except Exception:
                    continue

        return {"status": "error", "message": f"External API {action_type.capitalize()} Comment Error ({platform.upper()}): {last_err}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/api/comments/like")
def like_or_unlike_comment(payload: CommentLikePayload):
    return _perform_comment_moderation(
        record_id=payload.record_id,
        comment_id=payload.comment_id,
        action_type="like",
        enable=bool(payload.liked if payload.liked is not None else True)
    )


@router.post("/api/comments/hide")
def hide_or_unhide_comment(payload: CommentHidePayload):
    return _perform_comment_moderation(
        record_id=payload.record_id,
        comment_id=payload.comment_id,
        action_type="hide",
        enable=bool(payload.hidden if payload.hidden is not None else True)
    )


