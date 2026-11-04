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
# --- UNIFIED INBOX & DIRECT MESSAGES ENGINE (EXTERNAL API + CLOUDINARY) ---
# ==============================================================================
# Features:
# 1) Uses the same External API key pool connected to GlennBot
# 2) Supports per-page pagination: default 10 people (conversations) per Social Media Page
#    with "See More" (+10 per page) and Filter by Social Media Page
# 3) Real-time webhook message capture + Cloudinary persistence

MESSAGES_SYNC_LOCK = threading.Lock()

def _parse_single_message_item(
    m_raw: Dict[str, Any],
    account_id: str,
    account_name: str,
    platform: str,
    participant_fallback_name: str = "User",
    participant_fallback_avatar: str = ""
) -> Dict[str, Any]:
    m_id = str(
        m_raw.get("id")
        or m_raw.get("_id")
        or m_raw.get("messageId")
        or m_raw.get("platformMessageId")
        or m_raw.get("mid")
        or f"msg_{uuid.uuid4().hex[:10]}"
    ).strip()

    plat_m_id = str(
        m_raw.get("platformMessageId")
        or m_raw.get("messageId")
        or m_raw.get("mid")
        or ""
    ).strip()

    sender_obj = (
        m_raw.get("sender")
        or m_raw.get("from")
        or m_raw.get("author")
        or m_raw.get("user")
        or {}
    )
    if not isinstance(sender_obj, dict):
        sender_obj = {}

    sender_id = str(
        sender_obj.get("id")
        or sender_obj.get("_id")
        or m_raw.get("senderId")
        or m_raw.get("fromId")
        or ""
    ).strip()
    sender_name = str(
        sender_obj.get("name")
        or sender_obj.get("displayName")
        or sender_obj.get("username")
        or sender_obj.get("nickname")
        or m_raw.get("senderName")
        or m_raw.get("fromName")
        or ""
    ).strip()
    sender_avatar = str(
        sender_obj.get("avatar")
        or sender_obj.get("avatarUrl")
        or sender_obj.get("profilePictureUrl")
        or sender_obj.get("picture")
        or m_raw.get("senderAvatar")
        or ""
    ).strip()

    acc_clean = (account_name or "").strip().lstrip("@").lower()
    direction = str(m_raw.get("direction") or m_raw.get("type") or "").strip().lower()
    sent_via = m_raw.get("sentVia")
    is_own = bool(
        m_raw.get("isOwn")
        or m_raw.get("isOwner")
        or m_raw.get("isOwnAccount")
        or m_raw.get("fromOwner")
        or m_raw.get("fromMe")
        or m_raw.get("is_echo")
        or sender_obj.get("isOwn")
        or sender_obj.get("isOwner")
        or sender_obj.get("isOwnAccount")
        or direction in ("outbound", "sent", "outgoing", "reply")
        or (sent_via in ("api", "human", "broadcast", "sequence", "workflow", "comment_automation"))
        or (sender_id and account_id and sender_id == str(account_id))
        or (acc_clean and sender_name and sender_name.lstrip("@").lower() == acc_clean)
    )

    if is_own and not sender_name:
        sender_name = account_name or platform.capitalize()
    elif not is_own and (not sender_name or sender_name in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User")):
        sender_name = participant_fallback_name or f"{platform.capitalize()} User"
        if not sender_avatar and participant_fallback_avatar:
            sender_avatar = participant_fallback_avatar

    msg_text = str(
        m_raw.get("text")
        or m_raw.get("message")
        or m_raw.get("content")
        or m_raw.get("body")
        or ""
    ).strip()

    attachments = []
    raw_atts = m_raw.get("attachments") or m_raw.get("media") or m_raw.get("mediaItems") or []
    if isinstance(raw_atts, list):
        for att in raw_atts:
            if isinstance(att, dict):
                att_url = att.get("url") or att.get("mediaUrl") or att.get("imageUrl") or att.get("src") or ""
                if att_url:
                    attachments.append({
                        "type": att.get("type") or "media",
                        "url": str(att_url)
                    })
            elif isinstance(att, str) and att.startswith("http"):
                attachments.append({"type": "media", "url": att})

    if not msg_text and attachments:
        msg_text = "[Media Attachment]"

    ts_info = parse_meta_timestamp(
        m_raw.get("createdAt")
        or m_raw.get("created_at")
        or m_raw.get("timestamp")
        or m_raw.get("sentAt")
        or m_raw.get("createdTime")
        or ""
    )

    return {
        "id": m_id,
        "platform_message_id": plat_m_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_avatar": sender_avatar,
        "is_own": is_own,
        "message": msg_text,
        "attachments": attachments,
        "created_iso": ts_info["iso"],
        "display_time": ts_info["display"]
    }


def _msg_iso_to_epoch(iso_str: str) -> float:
    if not iso_str:
        return 0.0
    try:
        cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(iso_str).replace("Z", "+00:00"))
        return datetime.fromisoformat(cleaned).timestamp()
    except Exception:
        return 0.0


def _are_messages_duplicate(m1: Dict[str, Any], m2: Dict[str, Any]) -> bool:
    id1 = str(m1.get("id") or "").strip()
    id2 = str(m2.get("id") or "").strip()
    pid1 = str(m1.get("platform_message_id") or "").strip()
    pid2 = str(m2.get("platform_message_id") or "").strip()

    if id1 and id2 and id1 == id2:
        return True
    if pid1 and pid2 and pid1 == pid2:
        return True
    if pid1 and id2 and pid1 == id2:
        return True
    if id1 and pid2 and id1 == pid2:
        return True

    # Check if both have the same sender direction and identical text within a short window (e.g. API send + message.sent webhook echo)
    if bool(m1.get("is_own")) == bool(m2.get("is_own")):
        txt1 = (m1.get("message") or "").strip()
        txt2 = (m2.get("message") or "").strip()
        if txt1 and txt1 == txt2 and txt1 not in ("[Media Attachment]", "[Attachment]"):
            dt1 = str(m1.get("display_time") or "").strip()
            dt2 = str(m2.get("display_time") or "").strip()
            if dt1 and dt2 and dt1 == dt2:
                return True
            ep1 = _msg_iso_to_epoch(m1.get("created_iso") or "")
            ep2 = _msg_iso_to_epoch(m2.get("created_iso") or "")
            if ep1 > 0 and ep2 > 0 and abs(ep1 - ep2) <= 180:
                return True
    return False


def _deduplicate_messages_list(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not messages:
        return []
    valid_msgs = [
        m for m in messages
        if isinstance(m, dict) and ((m.get("message") or "").strip() or (m.get("attachments") or []))
    ]
    sorted_msgs = sorted(
        valid_msgs,
        key=lambda x: (_msg_iso_to_epoch(x.get("created_iso") or ""), x.get("created_iso") or "")
    )
    deduped: List[Dict[str, Any]] = []
    for msg in sorted_msgs:
        matched_existing = None
        for ex in deduped:
            if _are_messages_duplicate(ex, msg):
                matched_existing = ex
                break
        if matched_existing is not None:
            # Prefer real external ID over temporary local msg_... ID
            ex_id = str(matched_existing.get("id") or "")
            new_id = str(msg.get("id") or "")
            if ex_id.startswith("msg_") and new_id and not new_id.startswith("msg_"):
                matched_existing["id"] = new_id
            if not matched_existing.get("platform_message_id") and msg.get("platform_message_id"):
                matched_existing["platform_message_id"] = msg["platform_message_id"]
            if not matched_existing.get("attachments") and msg.get("attachments"):
                matched_existing["attachments"] = msg["attachments"]
        else:
            deduped.append(dict(msg))
    deduped.sort(key=lambda x: (_msg_iso_to_epoch(x.get("created_iso") or ""), x.get("created_iso") or ""))
    return deduped


def _normalize_participant_name_key(name: str) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"\s*\(@[^)]+\)\s*$", "", str(name)).strip().lstrip("@").lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in ("", "user", "facebook user", "instagram user", "tiktok user", "youtube user", "unknown", "customer"):
        return ""
    return cleaned


RECENT_PRIVATE_REPLY_RECIPIENTS: List[Dict[str, Any]] = []


def register_private_reply_recipient(
    platform: str,
    account_id: str,
    account_name: str,
    author_name: str,
    author_id: str = "",
    author_avatar: str = "",
    message_text: str = "",
    conversation_id: str = "",
    message_id: str = ""
):
    clean_author = str(author_name or "").strip()
    if not _normalize_participant_name_key(clean_author):
        return
    entry = {
        "platform": (platform or "").strip().lower(),
        "account_id": str(account_id or "").strip(),
        "account_name": (account_name or "").strip().lstrip("@").lower(),
        "author_name": clean_author,
        "author_id": str(author_id or "").strip(),
        "author_avatar": str(author_avatar or "").strip(),
        "message_text": (message_text or "").strip(),
        "conversation_id": str(conversation_id or "").strip(),
        "message_id": str(message_id or "").strip(),
        "ts": time.time()
    }
    RECENT_PRIVATE_REPLY_RECIPIENTS.insert(0, entry)
    if len(RECENT_PRIVATE_REPLY_RECIPIENTS) > 200:
        del RECENT_PRIVATE_REPLY_RECIPIENTS[200:]

    links = CLOUDINARY_MESSAGES_STORE.setdefault("private_reply_links", [])
    if isinstance(links, list):
        links.insert(0, dict(entry))
        if len(links) > 200:
            del links[200:]


def resolve_private_reply_participant(
    platform: str,
    account_id: str,
    account_name: str,
    participant_id: str = "",
    candidate_conv_ids: Optional[List[str]] = None,
    message_texts: Optional[List[str]] = None,
    is_outbound_only_thread: bool = False
) -> Optional[Dict[str, str]]:
    """
    Resolves a generic 'Facebook User' / 'Instagram User' participant on a Private Reply DM thread
    back to the real commenter's name (e.g. 'Glenn Tasico'), ID, and avatar using:
    1) Registered Private Reply links (in-memory + Cloudinary persisted)
    2) Comments/replies in CLOUDINARY_COMMENTS_STORE with `dm_sent == True` or matching `last_dm_message`
    3) Known commenter author_id lookup
    """
    plat_clean = (platform or "").strip().lower()
    acc_id_clean = str(account_id or "").strip()
    acc_name_clean = (account_name or "").strip().lstrip("@").lower()
    part_id_clean = str(participant_id or "").strip()
    cand_cids = {str(x).strip() for x in (candidate_conv_ids or []) if x and str(x).strip()}
    norm_texts = {
        re.sub(r"\s+", " ", str(t or "").strip()).lower()
        for t in (message_texts or [])
        if t and str(t).strip() and str(t).strip() not in ("Start a conversation", "[Media Attachment]")
    }

    # 1. Check RECENT_PRIVATE_REPLY_RECIPIENTS + persisted private_reply_links
    combined_links: List[Dict[str, Any]] = list(RECENT_PRIVATE_REPLY_RECIPIENTS)
    persisted_links = CLOUDINARY_MESSAGES_STORE.get("private_reply_links")
    if isinstance(persisted_links, list):
        combined_links.extend([x for x in persisted_links if isinstance(x, dict)])

    for item in combined_links:
        i_plat = (item.get("platform") or "").strip().lower()
        if plat_clean and i_plat and plat_clean != i_plat:
            continue
        i_acc_id = str(item.get("account_id") or "").strip()
        i_acc_name = (item.get("account_name") or "").strip().lstrip("@").lower()
        same_page = (
            (acc_id_clean and i_acc_id and acc_id_clean == i_acc_id)
            or (acc_name_clean and i_acc_name and acc_name_clean == i_acc_name)
        )
        if not same_page:
            continue

        i_cid = str(item.get("conversation_id") or "").strip()
        i_aid = str(item.get("author_id") or "").strip()
        i_txt = re.sub(r"\s+", " ", str(item.get("message_text") or "").strip()).lower()

        if (i_cid and i_cid in cand_cids) or (part_id_clean and i_aid and part_id_clean == i_aid) or (i_txt and i_txt in norm_texts):
            return {
                "author_name": str(item.get("author_name") or "").strip(),
                "author_id": i_aid,
                "author_avatar": str(item.get("author_avatar") or "").strip()
            }

    # 2. Check known author identity by participant_id
    if part_id_clean:
        known = lookup_known_author_identity(part_id_clean)
        if known and _normalize_participant_name_key(known.get("name") or ""):
            return {
                "author_name": str(known.get("name") or "").strip(),
                "author_id": part_id_clean,
                "author_avatar": str(known.get("avatar") or "").strip()
            }

    # 3. Scan CLOUDINARY_COMMENTS_STORE for comments/replies on this Page that had a DM sent (`dm_sent == True`)
    posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
    dm_sent_candidates_on_page: List[Dict[str, str]] = []
    for p_entry in posts_store.values():
        if not isinstance(p_entry, dict):
            continue
        c_map = p_entry.get("comments") or {}
        if not isinstance(c_map, dict):
            continue
        for c_obj in c_map.values():
            if not isinstance(c_obj, dict):
                continue
            c_plat = (c_obj.get("platform") or "").strip().lower()
            c_page_id = str(c_obj.get("page_id") or c_obj.get("zernio_account_id") or "").strip()
            c_acc_name = (c_obj.get("account_name") or "").strip().lstrip("@").lower()
            same_page = (
                (acc_id_clean and c_page_id and acc_id_clean == c_page_id)
                or (acc_name_clean and c_acc_name and acc_name_clean == c_acc_name)
                or (not c_acc_name and not c_page_id and (not plat_clean or not c_plat or plat_clean == c_plat))
            )
            if not same_page:
                continue

            # Check both parent comment and its sub-replies
            items_to_check = [c_obj] + [r for r in (c_obj.get("replies") or []) if isinstance(r, dict)]
            for comm_item in items_to_check:
                a_name = str(comm_item.get("author_name") or "").strip()
                if not _normalize_participant_name_key(a_name):
                    continue
                a_id = str(comm_item.get("author_id") or "").strip()
                a_av = str(comm_item.get("author_avatar") or "").strip()
                dm_txt = re.sub(r"\s+", " ", str(comm_item.get("last_dm_message") or "").strip()).lower()

                if dm_txt and dm_txt in norm_texts:
                    return {"author_name": a_name, "author_id": a_id, "author_avatar": a_av}
                if part_id_clean and a_id and part_id_clean == a_id:
                    return {"author_name": a_name, "author_id": a_id, "author_avatar": a_av}
                if comm_item.get("dm_sent"):
                    cand_info = {"author_name": a_name, "author_id": a_id, "author_avatar": a_av}
                    if not any(
                        _normalize_participant_name_key(x["author_name"]) == _normalize_participant_name_key(a_name)
                        for x in dm_sent_candidates_on_page
                    ):
                        dm_sent_candidates_on_page.append(cand_info)

    # If this thread on this Page has a generic name ('Facebook User') and is an outbound Private Reply thread,
    # and there is a commenter on this Page with `dm_sent == True` (e.g. 'Glenn Tasico'), link it!
    if is_outbound_only_thread and len(dm_sent_candidates_on_page) == 1:
        return dm_sent_candidates_on_page[0]

    return None


def _extract_participant_from_conversation_obj(
    conv_raw: Dict[str, Any],
    account_id: str,
    account_name: str,
    platform: str
) -> Dict[str, str]:
    acc_clean = (account_name or "").strip().lstrip("@").lower()
    p_id = ""
    p_name = ""
    p_uname = ""
    p_avatar = ""

    p_phone = ""
    p_email = ""

    # 1. Check direct participant / customer / contact / sender fields
    for field_key in ("participant", "customer", "contact", "recipient", "user", "sender", "from", "with"):
        cand = conv_raw.get(field_key)
        if isinstance(cand, dict):
            c_id = str(cand.get("id") or cand.get("_id") or cand.get("userId") or cand.get("wa_id") or cand.get("chatId") or "").strip()
            c_name = str(
                cand.get("name")
                or cand.get("displayName")
                or cand.get("pushName")
                or cand.get("fullName")
                or f"{cand.get('firstName') or cand.get('first_name') or ''} {cand.get('lastName') or cand.get('last_name') or ''}".strip()
                or cand.get("nickname")
                or ""
            ).strip()
            c_uname = str(cand.get("username") or cand.get("unique_id") or cand.get("telegramUsername") or "").strip().lstrip("@")
            c_phone = str(cand.get("phone") or cand.get("phoneNumber") or cand.get("wa_id") or "").strip()
            c_email = str(cand.get("email") or cand.get("emailAddress") or "").strip()
            c_av = str(cand.get("avatar") or cand.get("avatarUrl") or cand.get("profilePictureUrl") or cand.get("picture") or "").strip()
            if c_name.lstrip("@").lower() == acc_clean or (c_id and c_id == str(account_id)):
                continue
            p_id = c_id or p_id
            p_name = c_name or p_name
            p_uname = c_uname or p_uname
            p_phone = c_phone or p_phone
            p_email = c_email or p_email
            p_avatar = c_av or p_avatar
            if p_name or p_uname or p_phone:
                break

    # 2. Check participants array
    if not p_name and not p_uname:
        parts = conv_raw.get("participants") or (conv_raw.get("participants") or {})
        if isinstance(parts, dict):
            parts = parts.get("data") or parts.get("items") or []
        if isinstance(parts, list):
            for pt in parts:
                if not isinstance(pt, dict):
                    continue
                c_id = str(pt.get("id") or pt.get("_id") or pt.get("userId") or pt.get("wa_id") or pt.get("chatId") or "").strip()
                c_name = str(
                    pt.get("name")
                    or pt.get("displayName")
                    or pt.get("pushName")
                    or f"{pt.get('firstName') or pt.get('first_name') or ''} {pt.get('lastName') or pt.get('last_name') or ''}".strip()
                    or pt.get("nickname")
                    or ""
                ).strip()
                c_uname = str(pt.get("username") or pt.get("unique_id") or "").strip().lstrip("@")
                c_phone = str(pt.get("phone") or pt.get("phoneNumber") or pt.get("wa_id") or "").strip()
                c_email = str(pt.get("email") or pt.get("emailAddress") or "").strip()
                c_av = str(pt.get("avatar") or pt.get("avatarUrl") or pt.get("profilePictureUrl") or pt.get("picture") or "").strip()
                is_owner = bool(
                    pt.get("isOwner")
                    or pt.get("isOwn")
                    or pt.get("isOwnAccount")
                    or (c_id and c_id == str(account_id))
                    or (acc_clean and c_name and c_name.lstrip("@").lower() == acc_clean)
                    or (acc_clean and c_uname and c_uname.lower() == acc_clean)
                )
                if is_owner:
                    continue
                p_id = c_id or p_id
                p_name = c_name or p_name
                p_uname = c_uname or p_uname
                p_phone = c_phone or p_phone
                p_email = c_email or p_email
                p_avatar = c_av or p_avatar
                if p_name or p_uname or p_phone:
                    break

    # 3. Check top-level participant fields on conversation object
    if not p_name:
        p_name = str(
            conv_raw.get("participantName")
            or conv_raw.get("customerName")
            or conv_raw.get("contactName")
            or conv_raw.get("pushName")
            or conv_raw.get("senderName")
            or conv_raw.get("title")
            or conv_raw.get("name")
            or ""
        ).strip()
    if not p_uname:
        p_uname = str(
            conv_raw.get("participantUsername")
            or conv_raw.get("customerUsername")
            or conv_raw.get("username")
            or ""
        ).strip().lstrip("@")
    if not p_phone:
        p_phone = str(
            conv_raw.get("participantPhone")
            or conv_raw.get("customerPhone")
            or conv_raw.get("phoneNumber")
            or conv_raw.get("phone")
            or conv_raw.get("wa_id")
            or ""
        ).strip()
    if not p_email:
        p_email = str(conv_raw.get("participantEmail") or conv_raw.get("customerEmail") or conv_raw.get("email") or "").strip()
    if not p_id:
        p_id = str(
            conv_raw.get("participantId")
            or conv_raw.get("customerId")
            or conv_raw.get("senderId")
            or conv_raw.get("wa_id")
            or conv_raw.get("chatId")
            or ""
        ).strip()
    if not p_avatar:
        p_avatar = str(
            conv_raw.get("participantAvatar")
            or conv_raw.get("participantPicture")
            or conv_raw.get("avatarUrl")
            or conv_raw.get("picture")
            or ""
        ).strip()

    # Clean WhatsApp JID format (e.g. "639171234567@s.whatsapp.net" or "639171234567@c.us")
    for raw_wa_cand in (p_phone, p_id, p_uname, p_name):
        if raw_wa_cand and ("@s.whatsapp.net" in raw_wa_cand or "@c.us" in raw_wa_cand):
            cleaned_jid = raw_wa_cand.split("@")[0].strip()
            if cleaned_jid.isdigit() and not p_phone:
                p_phone = f"+{cleaned_jid}"
            if p_name == raw_wa_cand:
                p_name = f"+{cleaned_jid}" if cleaned_jid.isdigit() else cleaned_jid

    if platform == "whatsapp" and not p_phone:
        for cand_num in (p_id, p_uname, p_name):
            digits_only = re.sub(r"\D", "", str(cand_num or ""))
            if 9 <= len(digits_only) <= 15:
                p_phone = cand_num if str(cand_num).startswith("+") else f"+{digits_only}"
                break

    if p_name and p_uname and p_name.lower() != p_uname.lower():
        display_name = f"{p_name} (@{p_uname})"
    elif p_name:
        display_name = p_name
    elif p_uname:
        display_name = f"@{p_uname}"
    elif p_phone:
        display_name = p_phone
    else:
        display_name = f"{platform.capitalize()} User"

    return {
        "participant_id": p_id,
        "participant_name": display_name,
        "participant_handle": f"@{p_uname}" if p_uname else (p_phone if platform == "whatsapp" else ""),
        "participant_phone": p_phone,
        "participant_email": p_email,
        "participant_avatar": p_avatar
    }


def _fetch_conversations_for_connected_account(acc_item: Dict[str, Any], seen_conv_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Fetches all chat conversations for a connected social media page
    from the External API (/inbox/conversations) using the page's assigned API key.
    """
    platform = (acc_item.get("platform") or "").strip().lower()
    db_acc_id = str(acc_item.get("account_id") or "").strip()
    if platform == "sms" or db_acc_id == TEXTBEE_ACCOUNT_ID:
        return []
    acc_name = acc_item.get("account_name") or platform.upper()
    acc_avatar = acc_item.get("avatar_url") or ""

    verified_pairs = resolve_live_zernio_account_and_key_pairs(platform, db_acc_id, acc_name)
    if not verified_pairs:
        return []

    endpoints_to_try = [
        f"{ZERNIO_BASE_URL}/inbox/conversations",
        f"{ZERNIO_BASE_URL}/conversations"
    ]

    raw_conv_list = None
    used_api_key = verified_pairs[0]["api_key"]
    z_acc_id = verified_pairs[0]["account_id"]

    for pair in verified_pairs:
        api_key = pair["api_key"]
        cand_z_id = pair["account_id"]
        headers = get_zernio_headers(api_key)
        for ep in endpoints_to_try:
            try:
                resp = HTTP_SESSION.get(
                    ep,
                    params={"accountId": cand_z_id, "limit": 100},
                    headers=headers,
                    timeout=18
                )
                if resp.status_code == 200:
                    payload = resp.json() if resp.text else {}
                    extracted = extract_list_from_api_payload(payload)
                    if extracted is not None:
                        raw_conv_list = extracted
                        used_api_key = api_key
                        z_acc_id = cand_z_id
                        break
            except Exception:
                continue
        if raw_conv_list is not None:
            break

    if not raw_conv_list:
        return []

    parsed_conversations: Dict[str, Dict[str, Any]] = {}

    for order_idx, item in enumerate(raw_conv_list):
        if not isinstance(item, dict):
            continue

        # Check if item belongs to another account when API returns global list
        item_acc = item.get("accountId") or (item.get("account") or {}).get("id") or (item.get("account") or {}).get("_id")
        if isinstance(item_acc, dict):
            item_acc = item_acc.get("_id") or item_acc.get("id")
        if item_acc and str(item_acc) not in (db_acc_id, z_acc_id):
            continue

        effective_z_acc_id = str(item_acc).strip() if item_acc else str(z_acc_id or db_acc_id).strip()

        # According to Zernio OpenAPI spec, GET /v1/inbox/conversations returns `id` (the Zernio conversation id)
        # and `platformConversationId` (the native Meta thread id)
        conv_id = str(
            item.get("id")
            or item.get("conversationId")
            or item.get("_id")
            or item.get("platformConversationId")
            or item.get("threadId")
            or ""
        ).strip()
        if not conv_id:
            continue

        plat_conv_id = str(item.get("platformConversationId") or item.get("threadId") or conv_id).strip()
        z_internal_conv_id = str(item.get("id") or item.get("conversationId") or item.get("_id") or conv_id).strip()

        p_info = _extract_participant_from_conversation_obj(item, effective_z_acc_id, acc_name, platform)

        # Extract embedded messages or lastMessage
        inline_msgs_raw = extract_list_from_api_payload(item.get("messages")) or []
        parsed_msgs = [
            _parse_single_message_item(
                m_obj,
                effective_z_acc_id,
                acc_name,
                platform,
                participant_fallback_name=p_info["participant_name"],
                participant_fallback_avatar=p_info["participant_avatar"]
            )
            for m_obj in inline_msgs_raw if isinstance(m_obj, dict)
        ]

        raw_last_msg = item.get("lastMessage") if item.get("lastMessage") is not None else item.get("latestMessage")
        last_msg_obj = raw_last_msg if isinstance(raw_last_msg, dict) else {}
        last_msg_str = raw_last_msg.strip() if isinstance(raw_last_msg, str) else ""

        if last_msg_obj:
            lm_parsed = _parse_single_message_item(
                last_msg_obj,
                effective_z_acc_id,
                acc_name,
                platform,
                participant_fallback_name=p_info["participant_name"],
                participant_fallback_avatar=p_info["participant_avatar"]
            )
            parsed_msgs.append(lm_parsed)

        if not parsed_msgs and (item.get("text") or item.get("message") or item.get("content")):
            flat_msg = _parse_single_message_item(
                item,
                effective_z_acc_id,
                acc_name,
                platform,
                participant_fallback_name=p_info["participant_name"],
                participant_fallback_avatar=p_info["participant_avatar"]
            )
            parsed_msgs.append(flat_msg)
            if item.get("conversationId") or p_info["participant_id"]:
                conv_id = str(item.get("conversationId") or p_info["participant_id"])

        parsed_msgs = _deduplicate_messages_list(parsed_msgs)

        last_text = str(
            last_msg_str
            or item.get("lastMessageText")
            or item.get("snippet")
            or (last_msg_obj.get("text") or last_msg_obj.get("message") if isinstance(last_msg_obj, dict) else "")
            or (parsed_msgs[-1]["message"] if parsed_msgs else "")
            or "Start a conversation"
        ).strip()

        raw_updated_ts = (
            item.get("updatedTime")
            or item.get("updated_time")
            or item.get("updatedAt")
            or item.get("lastMessageAt")
            or item.get("timestamp")
            or (last_msg_obj.get("createdAt") or last_msg_obj.get("updatedTime") if isinstance(last_msg_obj, dict) else "")
            or (parsed_msgs[-1]["created_iso"] if parsed_msgs else "")
            or item.get("createdAt")
            or ""
        )
        ts_info = parse_meta_timestamp(raw_updated_ts, fallback_offset_seconds=order_idx)

        conv_key = f"{db_acc_id}_{conv_id}"
        last_seen_iso = seen_conv_map.get(conv_key) or seen_conv_map.get(conv_id) or ""
        api_unread = int(item.get("unreadCount") or item.get("unread_count") or 0)

        last_msg_is_own = parsed_msgs[-1]["is_own"] if parsed_msgs else False
        if not _normalize_participant_name_key(p_info["participant_name"]):
            resolved_fc_p = resolve_private_reply_participant(
                platform=platform,
                account_id=db_acc_id,
                account_name=acc_name,
                participant_id=p_info["participant_id"],
                candidate_conv_ids=[conv_id, z_internal_conv_id, plat_conv_id],
                message_texts=[last_text] + [str(m.get("message") or "") for m in parsed_msgs],
                is_outbound_only_thread=bool((parsed_msgs and all(bool(m.get("is_own")) for m in parsed_msgs)) or last_msg_is_own)
            )
            if resolved_fc_p and _normalize_participant_name_key(resolved_fc_p.get("author_name") or ""):
                p_info["participant_name"] = resolved_fc_p["author_name"]
                if resolved_fc_p.get("author_id") and not p_info["participant_id"]:
                    p_info["participant_id"] = resolved_fc_p["author_id"]
                if resolved_fc_p.get("author_avatar") and not p_info["participant_avatar"]:
                    p_info["participant_avatar"] = resolved_fc_p["author_avatar"]

        is_unread = False
        if not last_msg_is_own:
            if api_unread > 0:
                is_unread = True
            elif not last_seen_iso or _msg_iso_to_epoch(ts_info["iso"]) > _msg_iso_to_epoch(last_seen_iso):
                is_unread = bool(item.get("unread") or api_unread > 0)

        alt_ids = []
        for cid_cand in (conv_id, z_internal_conv_id, plat_conv_id, p_info["participant_id"]):
            if cid_cand and cid_cand not in alt_ids:
                alt_ids.append(cid_cand)

        if conv_key in parsed_conversations:
            existing_c = parsed_conversations[conv_key]
            existing_c["messages"] = _deduplicate_messages_list((existing_c.get("messages") or []) + parsed_msgs)
            if _msg_iso_to_epoch(ts_info["iso"]) > _msg_iso_to_epoch(existing_c.get("updated_iso") or ""):
                existing_c["updated_iso"] = ts_info["iso"]
                existing_c["display_time"] = ts_info["display"]
                existing_c["relative_time"] = ts_info.get("relative") or ""
                existing_c["last_message_text"] = last_text
        else:
            parsed_conversations[conv_key] = {
                "conv_key": conv_key,
                "conversation_id": conv_id,
                "platform_conversation_id": plat_conv_id,
                "zernio_conversation_id": z_internal_conv_id,
                "alternate_conversation_ids": alt_ids,
                "platform": platform,
                "account_id": db_acc_id,
                "zernio_account_id": effective_z_acc_id,
                "zernio_api_key": used_api_key,
                "account_name": acc_name,
                "account_avatar": acc_avatar,
                "participant_id": p_info["participant_id"],
                "participant_name": p_info["participant_name"],
                "participant_handle": p_info["participant_handle"],
                "participant_phone": p_info.get("participant_phone") or "",
                "participant_email": p_info.get("participant_email") or "",
                "participant_avatar": p_info["participant_avatar"],
                "last_message_text": last_text,
                "last_message_is_own": last_msg_is_own,
                "updated_iso": ts_info["iso"],
                "display_time": ts_info["display"],
                "relative_time": ts_info.get("relative") or "",
                "has_authoritative_ts": not ts_info.get("is_fallback", False),
                "api_order_index": order_idx,
                "unread_count": api_unread if is_unread else 0,
                "is_read": not is_unread,
                "hidden": False,
                "messages": parsed_msgs
            }

    return list(parsed_conversations.values())


def deduplicate_and_merge_conversations_store(connected_items: Optional[List[Dict[str, Any]]] = None) -> bool:
    """
    1. Heals any stale account_id / zernio_account_id / zernio_api_key on existing conversations
       in CLOUDINARY_MESSAGES_STORE so reconnected pages or multi-key accounts always match.
    2. Merges duplicate conversations for the same person (same participant_id or participant_name)
       under the same social media page into ONE continuous chat thread while keeping the NEWEST
       conversation_id as primary (never letting an older thread ID overwrite a newer one).
    3. Deduplicates message bubbles inside every conversation (eliminating double replies).
    """
    convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations")
    if not isinstance(convs_store, dict) or not convs_store:
        return False

    if connected_items is None:
        connected_items = refresh_connected_accounts_cache(force=False)

    acc_by_id: Dict[str, Dict[str, Any]] = {}
    acc_by_plat_name: Dict[str, Dict[str, Any]] = {}
    for acc in (connected_items or []):
        aid = str(acc.get("account_id") or "").strip()
        plat = (acc.get("platform") or "").strip().lower()
        aname = (acc.get("account_name") or "").strip().lstrip("@").lower()
        uname = (acc.get("username") or "").strip().lstrip("@").lower()
        if aid:
            acc_by_id[aid] = acc
        if plat and aname:
            acc_by_plat_name[f"{plat}::{aname}"] = acc
        if plat and uname:
            acc_by_plat_name[f"{plat}::{uname}"] = acc

    changed = False

    # Step 1: Heal account_id and deduplicate messages in each conversation
    for ckey, c_obj in list(convs_store.items()):
        if not isinstance(c_obj, dict):
            continue
        c_plat = (c_obj.get("platform") or "").strip().lower()
        c_acc_id = str(c_obj.get("account_id") or "").strip()
        c_acc_name = (c_obj.get("account_name") or "").strip()
        c_name_clean = c_acc_name.lstrip("@").lower()

        matched_connected = acc_by_id.get(c_acc_id)
        if not matched_connected and c_plat and c_name_clean:
            matched_connected = acc_by_plat_name.get(f"{c_plat}::{c_name_clean}")

        if matched_connected:
            live_db_acc_id = str(matched_connected.get("account_id") or "").strip()
            if live_db_acc_id and c_obj.get("account_id") != live_db_acc_id:
                c_obj["account_id"] = live_db_acc_id
                changed = True

        # Deduplicate messages inside this conversation (also strips any empty stub bubbles)
        orig_msgs = c_obj.get("messages") or []
        if orig_msgs:
            clean_msgs = _deduplicate_messages_list(orig_msgs)
            if len(clean_msgs) != len(orig_msgs):
                c_obj["messages"] = clean_msgs
                changed = True
            if clean_msgs:
                last_m = clean_msgs[-1]
                if last_m.get("message") and c_obj.get("last_message_text") in ("", "Start a conversation"):
                    c_obj["last_message_text"] = last_m["message"]
                    changed = True

        # Heal generic 'Facebook User' / 'Instagram User' participant names on Private Reply threads
        if not _normalize_participant_name_key(c_obj.get("participant_name") or ""):
            cur_msgs = c_obj.get("messages") or []
            msg_texts = [str(m.get("message") or "") for m in cur_msgs if isinstance(m, dict)]
            if c_obj.get("last_message_text"):
                msg_texts.append(str(c_obj.get("last_message_text") or ""))
            is_outbound_only = bool(
                (cur_msgs and all(bool(m.get("is_own")) for m in cur_msgs))
                or (not cur_msgs and c_obj.get("last_message_is_own"))
            )
            cand_cids = [
                str(c_obj.get("conversation_id") or ""),
                str(c_obj.get("platform_conversation_id") or ""),
                str(c_obj.get("zernio_conversation_id") or ""),
                *[str(x) for x in (c_obj.get("alternate_conversation_ids") or []) if x]
            ]
            resolved_p = resolve_private_reply_participant(
                platform=c_plat,
                account_id=str(c_obj.get("account_id") or ""),
                account_name=c_acc_name,
                participant_id=str(c_obj.get("participant_id") or ""),
                candidate_conv_ids=cand_cids,
                message_texts=msg_texts,
                is_outbound_only_thread=is_outbound_only
            )
            if resolved_p and _normalize_participant_name_key(resolved_p.get("author_name") or ""):
                c_obj["participant_name"] = resolved_p["author_name"]
                if resolved_p.get("author_id") and not c_obj.get("participant_id"):
                    c_obj["participant_id"] = resolved_p["author_id"]
                if resolved_p.get("author_avatar") and not c_obj.get("participant_avatar"):
                    c_obj["participant_avatar"] = resolved_p["author_avatar"]
                changed = True

    # Cross-pollinate participant_name by participant_id on the same Page before grouping
    known_name_by_page_pid: Dict[str, Dict[str, str]] = {}
    for ckey, c_obj in list(convs_store.items()):
        if not isinstance(c_obj, dict) or c_obj.get("hidden"):
            continue
        c_plat = (c_obj.get("platform") or "").strip().lower()
        c_acc_id = str(c_obj.get("account_id") or "").strip()
        c_acc_name = (c_obj.get("account_name") or "").strip().lstrip("@").lower()
        page_ident = c_acc_id or f"{c_plat}_{c_acc_name}"
        p_id = str(c_obj.get("participant_id") or "").strip()
        p_name = str(c_obj.get("participant_name") or "").strip()
        if p_id and _normalize_participant_name_key(p_name):
            known_name_by_page_pid[f"{c_plat}::{page_ident}::{p_id}"] = {
                "name": p_name,
                "avatar": str(c_obj.get("participant_avatar") or "").strip()
            }

    for ckey, c_obj in list(convs_store.items()):
        if not isinstance(c_obj, dict) or c_obj.get("hidden"):
            continue
        if not _normalize_participant_name_key(c_obj.get("participant_name") or ""):
            c_plat = (c_obj.get("platform") or "").strip().lower()
            c_acc_id = str(c_obj.get("account_id") or "").strip()
            c_acc_name = (c_obj.get("account_name") or "").strip().lstrip("@").lower()
            page_ident = c_acc_id or f"{c_plat}_{c_acc_name}"
            p_id = str(c_obj.get("participant_id") or "").strip()
            matched_info = known_name_by_page_pid.get(f"{c_plat}::{page_ident}::{p_id}") if p_id else None
            if matched_info:
                c_obj["participant_name"] = matched_info["name"]
                if matched_info.get("avatar") and not c_obj.get("participant_avatar"):
                    c_obj["participant_avatar"] = matched_info["avatar"]
                changed = True

    # Step 2: Group conversations by (page, person) and merge duplicates
    person_groups: Dict[str, List[str]] = {}
    for ckey, c_obj in list(convs_store.items()):
        if not isinstance(c_obj, dict) or c_obj.get("hidden"):
            continue
        c_plat = (c_obj.get("platform") or "").strip().lower()
        c_acc_id = str(c_obj.get("account_id") or "").strip()
        c_acc_name = (c_obj.get("account_name") or "").strip().lstrip("@").lower()
        page_ident = c_acc_id or f"{c_plat}_{c_acc_name}"

        p_name_norm = _normalize_participant_name_key(c_obj.get("participant_name") or "")
        p_id = str(c_obj.get("participant_id") or "").strip()
        if p_id and p_id in (c_acc_id, str(c_obj.get("zernio_account_id") or "")):
            p_id = ""

        # Prefer normalized participant name when available so webhook PSID vs thread ID still group together
        person_ident = p_name_norm or p_id
        if not person_ident:
            continue

        group_key = f"{c_plat}::{page_ident}::{person_ident}"
        person_groups.setdefault(group_key, []).append(ckey)

    for group_key, ckeys in person_groups.items():
        if len(ckeys) <= 1:
            continue

        # Sort keys so the conversation with the newest updated_iso is primary (index 0)
        ckeys.sort(
            key=lambda k: (
                _msg_iso_to_epoch((convs_store.get(k) or {}).get("updated_iso") or ""),
                len((convs_store.get(k) or {}).get("messages") or [])
            ),
            reverse=True
        )
        primary_key = ckeys[0]
        primary_conv = convs_store[primary_key]

        all_msgs = list(primary_conv.get("messages") or [])
        alt_ids = list(primary_conv.get("alternate_conversation_ids") or [])
        for cid_init in (
            primary_conv.get("conversation_id"),
            primary_conv.get("zernio_conversation_id"),
            primary_conv.get("platform_conversation_id")
        ):
            if cid_init and str(cid_init) not in alt_ids:
                alt_ids.append(str(cid_init))

        for dup_key in ckeys[1:]:
            dup_conv = convs_store.get(dup_key)
            if not isinstance(dup_conv, dict):
                continue
            all_msgs.extend(dup_conv.get("messages") or [])
            for d_cid in (
                dup_conv.get("conversation_id"),
                dup_conv.get("zernio_conversation_id"),
                dup_conv.get("platform_conversation_id"),
                *(dup_conv.get("alternate_conversation_ids") or [])
            ):
                if d_cid and str(d_cid) not in alt_ids:
                    alt_ids.append(str(d_cid))

            if not primary_conv.get("participant_id") and dup_conv.get("participant_id"):
                primary_conv["participant_id"] = dup_conv["participant_id"]
            if not primary_conv.get("participant_avatar") and dup_conv.get("participant_avatar"):
                primary_conv["participant_avatar"] = dup_conv["participant_avatar"]
            # IMPORTANT: Do NOT copy dup_conv's older platform_conversation_id or zernio_conversation_id
            # onto primary_conv, because dup_conv is an older thread! Keep them only in alternate_conversation_ids.

            convs_store.pop(dup_key, None)
            changed = True

        merged_msgs = _deduplicate_messages_list(all_msgs)
        primary_conv["messages"] = merged_msgs
        primary_conv["alternate_conversation_ids"] = alt_ids
        if merged_msgs:
            last_m = merged_msgs[-1]
            if last_m.get("message"):
                primary_conv["last_message_text"] = last_m["message"]
            primary_conv["last_message_is_own"] = bool(last_m.get("is_own"))
            if _msg_iso_to_epoch(last_m.get("created_iso") or "") >= _msg_iso_to_epoch(primary_conv.get("updated_iso") or ""):
                primary_conv["updated_iso"] = last_m["created_iso"]
                primary_conv["display_time"] = last_m.get("display_time") or primary_conv.get("display_time", "")

    return changed


def _find_existing_conversation_in_store(
    convs_store: Dict[str, Dict[str, Any]],
    db_acc_id: str,
    acc_name: str,
    platform: str,
    candidate_conv_ids: List[str],
    participant_id: str = "",
    participant_name: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Finds an existing conversation in convs_store for the same social media account
    by matching conversation_id, platform_conversation_id, zernio_conversation_id,
    alternate_conversation_ids, participant_id, or participant_name.
    """
    plat_clean = (platform or "").strip().lower()
    cand_id_set = {str(x).strip() for x in candidate_conv_ids if x and str(x).strip()}
    part_id_clean = str(participant_id or "").strip()
    part_name_norm = _normalize_participant_name_key(participant_name)
    valid_acc_ids = _collect_valid_account_ids_for_page(plat_clean, db_acc_id, acc_name) if (db_acc_id or acc_name) else set()
    if db_acc_id:
        valid_acc_ids.add(str(db_acc_id).strip())

    # 1. Direct key lookup
    for cid in cand_id_set:
        ck = f"{db_acc_id}_{cid}"
        if ck in convs_store:
            return convs_store[ck]

    def _conv_belongs_to_same_page(c_obj: Dict[str, Any]) -> bool:
        c_plat = (c_obj.get("platform") or "").strip().lower()
        if plat_clean and c_plat and plat_clean != c_plat:
            return False
        c_acc = str(c_obj.get("account_id") or "").strip()
        c_zacc = str(c_obj.get("zernio_account_id") or "").strip()
        c_aname = str(c_obj.get("account_name") or "").strip()
        if valid_acc_ids and ((c_acc and c_acc in valid_acc_ids) or (c_zacc and c_zacc in valid_acc_ids)):
            return True
        if acc_name and c_aname and _is_same_social_page_name(c_aname, acc_name):
            return True
        return False

    # 2. Match by any stored conversation ID on the same account/page
    for k, c_obj in convs_store.items():
        if not isinstance(c_obj, dict) or not _conv_belongs_to_same_page(c_obj):
            continue

        stored_ids = {
            str(c_obj.get("conversation_id") or "").strip(),
            str(c_obj.get("platform_conversation_id") or "").strip(),
            str(c_obj.get("zernio_conversation_id") or "").strip(),
            *(str(x).strip() for x in (c_obj.get("alternate_conversation_ids") or []) if x)
        }
        stored_ids.discard("")
        if cand_id_set & stored_ids:
            return c_obj

    # 3. Match by participant_id or participant_name on the same account/page
    for k, c_obj in convs_store.items():
        if not isinstance(c_obj, dict) or not _conv_belongs_to_same_page(c_obj):
            continue

        c_pid = str(c_obj.get("participant_id") or "").strip()
        if part_id_clean and c_pid and part_id_clean == c_pid and part_id_clean not in valid_acc_ids:
            return c_obj

        c_pname_norm = _normalize_participant_name_key(c_obj.get("participant_name") or "")
        if part_name_norm and c_pname_norm and part_name_norm == c_pname_norm:
            return c_obj

    return None


def sync_all_messages_to_cloudinary(force_refresh: bool = False) -> bool:
    if not get_all_zernio_keys():
        return False

    acquired = MESSAGES_SYNC_LOCK.acquire(blocking=force_refresh, timeout=10 if force_refresh else 0)
    if not acquired:
        return False

    try:
        connected_items = refresh_connected_accounts_cache(force=force_refresh)
        if not connected_items:
            return True

        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT conversation_id, last_seen_iso FROM glennbot_seen_messages")).mappings().all()
            seen_conv_map = {str(r["conversation_id"]): str(r["last_seen_iso"] or "") for r in seen_rows}

        convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
        any_change = False

        max_workers = min(6, max(1, len(connected_items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_fetch_conversations_for_connected_account, acc, seen_conv_map)
                for acc in connected_items
            ]
            for fut in as_completed(futures):
                try:
                    fetched_convs = fut.result()
                    for fc in (fetched_convs or []):
                        existing_c = _find_existing_conversation_in_store(
                            convs_store,
                            db_acc_id=str(fc.get("account_id") or ""),
                            acc_name=str(fc.get("account_name") or ""),
                            platform=str(fc.get("platform") or ""),
                            candidate_conv_ids=[
                                fc.get("conversation_id") or "",
                                fc.get("platform_conversation_id") or "",
                                fc.get("zernio_conversation_id") or ""
                            ],
                            participant_id=str(fc.get("participant_id") or ""),
                            participant_name=str(fc.get("participant_name") or "")
                        )
                        if existing_c is None:
                            convs_store[fc["conv_key"]] = fc
                            any_change = True
                            if "_notify_n8n_new_message" in globals():
                                for nm in (fc.get("messages") or []):
                                    if not nm.get("is_own"):
                                        _notify_n8n_new_message(fc, nm, is_background_sync=True)
                        else:
                            prev_c = existing_c
                            if fc.get("account_id"):
                                prev_c["account_id"] = fc["account_id"]
                            if fc.get("zernio_account_id"):
                                prev_c["zernio_account_id"] = fc["zernio_account_id"]
                            if fc.get("zernio_api_key"):
                                prev_c["zernio_api_key"] = fc["zernio_api_key"]

                            fc_epoch = _msg_iso_to_epoch(fc.get("updated_iso") or "")
                            prev_epoch = _msg_iso_to_epoch(prev_c.get("updated_iso") or "")
                            is_fc_newer = (fc_epoch >= prev_epoch) or (prev_epoch <= 0.0)

                            # CRITICAL FIX: Only update primary conversation_id / platform_conversation_id / zernio_conversation_id
                            # when `fc` is at least as new as `prev_c`! Never let an older pre-existing thread overwrite a newer thread's ID!
                            if is_fc_newer:
                                if fc.get("platform_conversation_id"):
                                    prev_c["platform_conversation_id"] = fc["platform_conversation_id"]
                                if fc.get("zernio_conversation_id"):
                                    prev_c["zernio_conversation_id"] = fc["zernio_conversation_id"]
                                if fc.get("conversation_id") and prev_c.get("conversation_id") != fc["conversation_id"]:
                                    prev_c["conversation_id"] = fc["conversation_id"]
                                    any_change = True
                            else:
                                if not prev_c.get("platform_conversation_id") and fc.get("platform_conversation_id"):
                                    prev_c["platform_conversation_id"] = fc["platform_conversation_id"]
                                if not prev_c.get("zernio_conversation_id") and fc.get("zernio_conversation_id"):
                                    prev_c["zernio_conversation_id"] = fc["zernio_conversation_id"]

                            alt_ids = list(prev_c.get("alternate_conversation_ids") or [])
                            for cid_c in (
                                prev_c.get("conversation_id"),
                                fc.get("conversation_id"),
                                fc.get("zernio_conversation_id"),
                                fc.get("platform_conversation_id")
                            ):
                                if cid_c and str(cid_c) not in alt_ids:
                                    alt_ids.append(str(cid_c))
                            prev_c["alternate_conversation_ids"] = alt_ids

                            prev_msgs = _filter_out_deleted_messages(prev_c, prev_c.get("messages") or [])
                            incoming_filtered = _filter_out_deleted_messages(prev_c, fc.get("messages") or [])
                            had_count = len(prev_msgs)
                            has_new_incoming = False
                            for nm in incoming_filtered:
                                if not any(_are_messages_duplicate(ex_m, nm) for ex_m in prev_msgs):
                                    if not nm.get("is_own"):
                                        has_new_incoming = True
                                        if "_notify_n8n_new_message" in globals():
                                            _notify_n8n_new_message(prev_c, nm, is_background_sync=True)

                            merged_msgs = _filter_out_deleted_messages(prev_c, _deduplicate_messages_list(prev_msgs + incoming_filtered))
                            if len(merged_msgs) != had_count:
                                any_change = True
                            prev_c["messages"] = merged_msgs

                            if fc.get("participant_name") and fc["participant_name"] not in ("User", "Facebook User", "Instagram User", "TikTok User"):
                                prev_c["participant_name"] = fc["participant_name"]
                            if fc.get("participant_id") and (is_fc_newer or not prev_c.get("participant_id")):
                                prev_c["participant_id"] = fc["participant_id"]
                            if fc.get("participant_avatar") and not prev_c.get("participant_avatar"):
                                prev_c["participant_avatar"] = fc["participant_avatar"]

                            prev_was_placeholder = (prev_c.get("last_message_text") in ("", "Start a conversation"))
                            if is_fc_newer or prev_was_placeholder:
                                if (
                                    prev_c.get("updated_iso") != fc.get("updated_iso")
                                    or prev_c.get("last_message_text") != fc.get("last_message_text")
                                    or prev_c.get("api_order_index") != fc.get("api_order_index")
                                ):
                                    any_change = True
                                prev_c["updated_iso"] = fc["updated_iso"]
                                prev_c["display_time"] = fc["display_time"]
                                prev_c["relative_time"] = fc.get("relative_time") or ""
                                prev_c["api_order_index"] = min(
                                    int(prev_c.get("api_order_index") if prev_c.get("api_order_index") is not None else 9999),
                                    int(fc.get("api_order_index") if fc.get("api_order_index") is not None else 9999)
                                )
                                if fc.get("last_message_text") and fc["last_message_text"] != "Start a conversation":
                                    prev_c["last_message_text"] = fc["last_message_text"]

                            if has_new_incoming:
                                prev_c["hidden"] = False
                                prev_c["is_read"] = False
                                prev_c["unread_count"] = max(1, int(prev_c.get("unread_count") or 0) + 1)
                except Exception as e:
                    print(f"[⚠️ MESSAGES SYNC WORKER WARNING]: {e}")

        try:
            if "_sync_received_textbee_sms_messages" in globals() and _sync_received_textbee_sms_messages():
                any_change = True
        except Exception as tb_sync_err:
            print(f"[⚠️ TEXTBEE SMS SYNC WARNING]: {tb_sync_err}")

        if deduplicate_and_merge_conversations_store(connected_items):
            any_change = True

        CLOUDINARY_MESSAGES_STORE["last_synced"] = time.time()
        if any_change or force_refresh:
            save_messages_store_async()
        return True
    except Exception as e:
        print(f"[❌ MESSAGES SYNC ERROR]: {e}")
        return False
    finally:
        MESSAGES_SYNC_LOCK.release()


def _conversation_sort_key(c_obj: Dict[str, Any]):
    iso_str = str(c_obj.get("updated_iso") or "")
    try:
        cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso_str.replace("Z", "+00:00"))
        ts_epoch = datetime.fromisoformat(cleaned).timestamp()
    except Exception:
        ts_epoch = 0.0
    order_idx = int(c_obj.get("api_order_index") if c_obj.get("api_order_index") is not None else 9999)
    return (ts_epoch, -order_idx)


@router.get("/api/messages/conversations")
def get_inbox_conversations(
    force: bool = False,
    account_id: str = "all",
    platform: str = "all",
    limit_per_page: int = 10,
    page_limits: str = ""
):
    """
    Returns conversations grouped and limited to `limit_per_page` (default 10 people)
    per Social Media Page, with support for 'See More' (`page_limits` JSON/string)
    and filtering by Social Media Page (`account_id`) or Platform (`platform`).
    """
    try:
        if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
            load_messages_store_from_cloudinary()

        if force:
            sync_all_messages_to_cloudinary(force_refresh=True)
        elif (CLOUDINARY_MESSAGES_STORE.get("last_synced", 0.0) == 0.0) or (
            (time.time() - CLOUDINARY_MESSAGES_STORE.get("last_synced", 0.0)) >= 4.0 and not MESSAGES_SYNC_LOCK.locked()
        ):
            try:
                BG_SYNC_EXECUTOR.submit(sync_all_messages_to_cloudinary, False)
            except Exception:
                threading.Thread(target=sync_all_messages_to_cloudinary, kwargs={"force_refresh": False}, daemon=True).start()

        connected_items = refresh_connected_accounts_cache(force=False)
        if deduplicate_and_merge_conversations_store(connected_items):
            save_messages_store_async()

        connected_by_acc_id = {str(a.get("account_id") or ""): a for a in connected_items}

        # Parse custom per-page limits (e.g., {"acc_123": 20, "acc_456": 10}) when user clicks "See More"
        custom_limits: Dict[str, int] = {}
        if page_limits:
            try:
                parsed_pl = json.loads(page_limits)
                if isinstance(parsed_pl, dict):
                    for k, v in parsed_pl.items():
                        custom_limits[str(k)] = max(1, int(v))
            except Exception:
                for pair in page_limits.split(","):
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        if v.strip().isdigit():
                            custom_limits[k.strip()] = max(1, int(v.strip()))

        seen_conv_map = _get_cached_seen_messages_map(ttl_sec=3.0)

        convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
        grouped_by_page: Dict[str, List[Dict[str, Any]]] = {str(a.get("account_id") or ""): [] for a in connected_items}

        for ckey, c_obj in list(convs_store.items()):
            if c_obj.get("hidden"):
                continue
            c_acc_id = str(c_obj.get("account_id") or "").strip()
            c_plat = (c_obj.get("platform") or "").strip().lower()
            if c_acc_id and c_acc_id not in connected_by_acc_id and (
                c_obj.get("opened_from_crm")
                or c_acc_id == TEXTBEE_ACCOUNT_ID
                or c_plat in ("sms", "whatsapp", "telegram")
            ):
                synth_acc = {
                    "account_id": c_acc_id,
                    "zernio_account_id": str(c_obj.get("zernio_account_id") or c_acc_id),
                    "platform": c_plat or "sms",
                    "account_name": str(c_obj.get("account_name") or (
                        "SMS Gateway (SIM 2)" if c_plat == "sms" else f"{c_plat.capitalize()} Direct"
                    )),
                    "username": str(c_obj.get("account_username") or ""),
                    "avatar_url": ""
                }
                connected_by_acc_id[c_acc_id] = synth_acc
                connected_items.append(synth_acc)
                grouped_by_page.setdefault(c_acc_id, [])
            if c_acc_id not in connected_by_acc_id:
                continue
            if platform != "all" and c_plat != platform.strip().lower():
                continue
            if account_id != "all" and c_acc_id != account_id.strip():
                continue

            c_copy = dict(c_obj)
            # Check seen status
            last_seen = seen_conv_map.get(ckey) or seen_conv_map.get(str(c_copy.get("conversation_id") or "")) or ""
            if last_seen and _msg_iso_to_epoch(c_copy.get("updated_iso") or "") <= _msg_iso_to_epoch(last_seen):
                c_copy["is_read"] = True
                c_copy["unread_count"] = 0

            # Keep last 30 messages in recent_messages so clicking a conversation in the UI opens in 0ms (1-click instant!)
            msgs_preview = c_copy.get("messages") or []
            c_copy["message_count"] = len(msgs_preview)
            if msgs_preview and not c_copy.get("last_message_text"):
                c_copy["last_message_text"] = msgs_preview[-1].get("message") or ""
            c_copy["recent_messages"] = msgs_preview[-30:]
            c_copy.pop("messages", None)

            grouped_by_page.setdefault(c_acc_id, []).append(c_copy)

        paginated_conversations: List[Dict[str, Any]] = []
        pages_summary: List[Dict[str, Any]] = []
        total_unread = 0
        has_more_any = False

        for acc in connected_items:
            aid = str(acc.get("account_id") or "")
            plat = (acc.get("platform") or "").strip().lower()
            aname = acc.get("account_name") or plat.upper()
            uname = acc.get("username") or ""
            avatar = acc.get("avatar_url") or ""

            page_convs = grouped_by_page.get(aid) or []
            page_convs.sort(key=_conversation_sort_key, reverse=True)

            page_unread = sum(1 for c in page_convs if not c.get("is_read"))
            total_unread += page_unread

            allowed_limit = custom_limits.get(aid, max(1, int(limit_per_page or 10)))
            total_for_page = len(page_convs)
            sliced_for_page = page_convs[:allowed_limit]
            has_more = total_for_page > allowed_limit
            remaining = max(0, total_for_page - len(sliced_for_page))

            if (account_id == "all" or account_id == aid) and (platform == "all" or platform == plat):
                paginated_conversations.extend(sliced_for_page)
                if has_more:
                    has_more_any = True

            pages_summary.append({
                "account_id": aid,
                "platform": plat,
                "account_name": aname,
                "username": uname,
                "avatar_url": avatar,
                "total_conversations": total_for_page,
                "displayed_count": len(sliced_for_page),
                "current_limit": allowed_limit,
                "has_more": has_more,
                "remaining_count": remaining,
                "unread_count": page_unread
            })

        paginated_conversations.sort(key=_conversation_sort_key, reverse=True)

        return {
            "status": "success",
            "total_unread": total_unread,
            "total_displayed": len(paginated_conversations),
            "has_more_any": has_more_any,
            "connected_pages": pages_summary,
            "conversations": paginated_conversations
        }
    except Exception as e:
        return {
            "status": "error",
            "total_unread": 0,
            "total_displayed": 0,
            "has_more_any": False,
            "connected_pages": [],
            "conversations": [],
            "message": str(e)
        }


@router.get("/api/messages/{conversation_id}/thread")
@router.get("/api/messages/{conversation_id}")
def get_conversation_messages_thread(
    conversation_id: str,
    account_id: str = "",
    force: bool = True
):
    """
    Fetches the full chat history for a selected person/conversation on the right panel
    and automatically marks the conversation as read. Also heals stale conversation IDs
    by checking the live Zernio conversation list so pre-existing & newer threads merge cleanly.
    """
    try:
        if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
            load_messages_store_from_cloudinary()

        if deduplicate_and_merge_conversations_store():
            save_messages_store_async()

        convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
        target_conv = None
        target_key = ""

        if account_id and f"{account_id}_{conversation_id}" in convs_store:
            target_key = f"{account_id}_{conversation_id}"
            target_conv = convs_store[target_key]
        else:
            for k, c_obj in convs_store.items():
                if not isinstance(c_obj, dict):
                    continue
                alt_ids = [str(x) for x in (c_obj.get("alternate_conversation_ids") or []) if x]
                if (
                    str(c_obj.get("conversation_id")) == str(conversation_id)
                    or str(c_obj.get("platform_conversation_id")) == str(conversation_id)
                    or str(c_obj.get("zernio_conversation_id")) == str(conversation_id)
                    or str(conversation_id) in alt_ids
                    or k == str(conversation_id)
                ):
                    if not account_id or str(c_obj.get("account_id")) == str(account_id):
                        target_key = k
                        target_conv = c_obj
                        break

        if not target_conv:
            return {"status": "error", "message": "Conversation not found."}

        acc_id = str(target_conv.get("account_id") or account_id or "")
        acc_name = target_conv.get("account_name") or ""
        platform = target_conv.get("platform") or "facebook"
        pref_key = target_conv.get("zernio_api_key") or ""
        stored_z_acc_id = str(target_conv.get("zernio_account_id") or "")
        real_conv_id = str(target_conv.get("conversation_id") or conversation_id)
        participant_id = str(target_conv.get("participant_id") or "").strip()
        participant_name = str(target_conv.get("participant_name") or "").strip()

        verified_pairs = (
            []
            if (platform == "sms" or acc_id == TEXTBEE_ACCOUNT_ID)
            else resolve_live_zernio_account_and_key_pairs(platform, acc_id, acc_name, stored_z_acc_id, pref_key)
        )

        if force and verified_pairs:
            cand_conv_ids: List[str] = []
            for cid_c in (
                real_conv_id,
                str(conversation_id).strip(),
                target_conv.get("zernio_conversation_id"),
                target_conv.get("platform_conversation_id"),
                *(target_conv.get("alternate_conversation_ids") or []),
                participant_id
            ):
                if cid_c:
                    s_cid = str(cid_c).strip()
                    if s_cid and s_cid not in cand_conv_ids:
                        cand_conv_ids.append(s_cid)
                    if s_cid.startswith("conv_"):
                        stripped = s_cid[5:].strip()
                        if stripped and stripped not in cand_conv_ids:
                            cand_conv_ids.append(stripped)

            all_fetched_raw_msgs: List[Dict[str, Any]] = []
            used_z_acc = stored_z_acc_id or acc_id
            newest_working_cid = ""

            for pair in verified_pairs:
                api_key = pair["api_key"]
                z_acc_id = pair["account_id"]
                headers = get_zernio_headers(api_key)

                # Also check live conversations for this participant so if a newer thread exists on Zernio, we heal the ID immediately
                try:
                    list_resp = HTTP_SESSION.get(
                        f"{ZERNIO_BASE_URL}/inbox/conversations",
                        params={"accountId": z_acc_id, "limit": 100},
                        headers=headers,
                        timeout=15
                    )
                    if list_resp.status_code == 200:
                        live_convs = extract_list_from_api_payload(list_resp.json() if list_resp.text else {}) or []
                        target_pname_norm = _normalize_participant_name_key(participant_name)
                        matched_live_cids: List[Tuple[float, str]] = []
                        for idx_lc, lc in enumerate(live_convs):
                            if not isinstance(lc, dict):
                                continue
                            lc_id = str(lc.get("id") or lc.get("conversationId") or lc.get("platformConversationId") or "").strip()
                            if not lc_id:
                                continue
                            lc_pinfo = _extract_participant_from_conversation_obj(lc, z_acc_id, acc_name, platform)
                            lc_pid = str(lc_pinfo.get("participant_id") or lc.get("participantId") or "").strip()
                            lc_pname_norm = _normalize_participant_name_key(lc_pinfo.get("participant_name") or lc.get("participantName") or "")
                            id_match = bool(participant_id and lc_pid and participant_id == lc_pid)
                            name_match = bool(target_pname_norm and lc_pname_norm and target_pname_norm == lc_pname_norm)
                            if id_match or name_match or lc_id in cand_conv_ids:
                                raw_ts = lc.get("updatedTime") or lc.get("updatedAt") or lc.get("lastMessageAt") or ""
                                ts_ep = _msg_iso_to_epoch(parse_meta_timestamp(raw_ts, fallback_offset_seconds=idx_lc)["iso"])
                                matched_live_cids.append((ts_ep, lc_id))
                        matched_live_cids.sort(key=lambda x: x[0], reverse=True)
                        for idx_m, (_, m_cid) in enumerate(matched_live_cids):
                            if idx_m == 0 and not newest_working_cid:
                                newest_working_cid = m_cid
                            if m_cid not in cand_conv_ids:
                                cand_conv_ids.insert(idx_m, m_cid)
                except Exception:
                    pass

                for c_id_try in cand_conv_ids[:6]:
                    safe_cid = requests.utils.quote(c_id_try, safe="")
                    ep = f"{ZERNIO_BASE_URL}/inbox/conversations/{safe_cid}/messages"
                    try:
                        resp = HTTP_SESSION.get(
                            ep,
                            params={"accountId": z_acc_id, "limit": 100},
                            headers=headers,
                            timeout=18
                        )
                        if resp.status_code == 200:
                            payload = resp.json() if resp.text else {}
                            extracted = extract_list_from_api_payload(payload)
                            if extracted:
                                all_fetched_raw_msgs.extend(extracted)
                                used_z_acc = z_acc_id
                                target_conv["zernio_account_id"] = z_acc_id
                                target_conv["zernio_api_key"] = api_key
                                if not newest_working_cid:
                                    newest_working_cid = c_id_try
                    except Exception:
                        continue
                if all_fetched_raw_msgs:
                    break

            if newest_working_cid:
                target_conv["conversation_id"] = newest_working_cid
                target_conv["zernio_conversation_id"] = newest_working_cid
                alt_list = list(target_conv.get("alternate_conversation_ids") or [])
                if newest_working_cid not in alt_list:
                    alt_list.insert(0, newest_working_cid)
                target_conv["alternate_conversation_ids"] = alt_list

            if all_fetched_raw_msgs:
                existing_msgs = list(target_conv.get("messages") or [])
                new_parsed_list = []
                for m_raw in all_fetched_raw_msgs:
                    if not isinstance(m_raw, dict):
                        continue
                    pm = _parse_single_message_item(
                        m_raw,
                        used_z_acc,
                        acc_name,
                        platform,
                        participant_fallback_name=target_conv.get("participant_name", "User"),
                        participant_fallback_avatar=target_conv.get("participant_avatar", "")
                    )
                    new_parsed_list.append(pm)

                merged_msgs = _filter_out_deleted_messages(target_conv, _deduplicate_messages_list(existing_msgs + new_parsed_list))
                target_conv["messages"] = merged_msgs
                if merged_msgs:
                    target_conv["last_message_text"] = merged_msgs[-1].get("message") or target_conv.get("last_message_text", "")
                    last_m_iso = merged_msgs[-1].get("created_iso") or ""
                    if _msg_iso_to_epoch(last_m_iso) >= _msg_iso_to_epoch(target_conv.get("updated_iso") or ""):
                        target_conv["updated_iso"] = last_m_iso
                        target_conv["display_time"] = merged_msgs[-1].get("display_time") or target_conv.get("display_time", "")
                save_messages_store_async()
            else:
                target_conv["messages"] = _filter_out_deleted_messages(target_conv, _deduplicate_messages_list(target_conv.get("messages") or []))
        else:
            target_conv["messages"] = _filter_out_deleted_messages(target_conv, _deduplicate_messages_list(target_conv.get("messages") or []))

        # Mark conversation as read
        now_iso = datetime.now(pytz.timezone("Asia/Manila")).isoformat()
        target_conv["is_read"] = True
        target_conv["unread_count"] = 0
        try:
            with db_engine.begin() as conn:
                for k_id in {target_key, real_conv_id, str(target_conv.get("conversation_id") or "")}:
                    if not k_id:
                        continue
                    conn.execute(
                        text("""
                            INSERT INTO glennbot_seen_messages (conversation_id, account_id, last_seen_iso)
                            VALUES (:cid, :aid, :iso)
                            ON CONFLICT (conversation_id) DO UPDATE SET
                                last_seen_iso = EXCLUDED.last_seen_iso,
                                seen_at = CURRENT_TIMESTAMP
                        """),
                        {"cid": k_id, "aid": acc_id, "iso": now_iso}
                    )
        except Exception:
            pass

        return {
            "status": "success",
            "conversation": {k: v for k, v in target_conv.items() if k != "messages"},
            "messages": target_conv.get("messages") or []
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


class SendMessagePayload(BaseModel):
    conversation_id: str
    account_id: str
    recipient_id: Optional[str] = ""
    message: str
    use_human_agent: Optional[bool] = True
    message_tag: Optional[str] = "HUMAN_AGENT"
    file_id: Optional[str] = ""
    media_url: Optional[str] = ""
    filename: Optional[str] = ""
    media_type: Optional[str] = ""


@router.post("/api/messages/upload_attachment")
async def upload_dm_or_chat_local_attachment(
    file: UploadFile = File(...),
    platform: str = Form("facebook"),
    account_id: str = Form("")
):
    """
    Uploads a file chosen from the user's Local Device inside the Messages Modal
    (Facebook, Instagram, Telegram, WhatsApp) or the 'Send a DM to Commenter' Modal
    directly to Zernio Media Cloud (with automatic Cloudinary / Google Drive fallback)
    and returns a ready-to-send public HTTPS `media_url` + accurate `media_type`.
    """
    try:
        orig_name = os.path.basename(file.filename or "attachment")
        file_bytes = await file.read()
        if not file_bytes:
            return JSONResponse({"status": "error", "message": "Selected file is empty."}, status_code=400)

        guessed_mime, _ = mimetypes.guess_type(orig_name)
        mime_type = (file.content_type or guessed_mime or "application/octet-stream").lower()
        detected_type = _detect_attachment_media_category(orig_name, mime_type, fallback_type="file")

        def _sync_upload():
            # 1. Primary: Zernio Presigned Media Cloud for all attachment types (image, video, audio, file)
            z_res = upload_bytes_to_zernio_presign(
                file_bytes=file_bytes,
                original_filename=orig_name,
                media_type=detected_type,
                is_thumb=False,
                platform=(platform or "facebook").strip().lower(),
                account_id=(account_id or "").strip()
            )
            if z_res and z_res.get("url"):
                return str(z_res["url"]).strip()

            # 2. Fallback: Cloudinary upload (supports image, video, and raw files)
            try:
                res_type = "image" if detected_type == "image" else ("video" if detected_type in ("video", "audio") else "raw")
                c_res = cloudinary.uploader.upload(
                    io.BytesIO(file_bytes),
                    resource_type=res_type,
                    public_id=re.sub(r"[^a-zA-Z0-9._-]", "_", orig_name),
                    use_filename=True,
                    unique_filename=True,
                    folder="glennbot_dm_attachments"
                )
                if c_res and c_res.get("secure_url"):
                    return str(c_res["secure_url"]).strip()
            except Exception as c_err:
                print(f"[⚠️ DM ATTACHMENT CLOUDINARY FALLBACK WARNING]: {c_err}")

            # 3. Secondary Fallback: Google Drive Vault upload
            temp_fid = f"dm_att_{int(time.time() * 1000)}"
            up_info = _upload_vault_file_bytes_with_fallback(
                file_bytes=file_bytes,
                orig_name=orig_name,
                py_file_id=temp_fid,
                mime_type=mime_type
            )
            return str(up_info.get("download_url") or up_info.get("web_view_link") or "").strip()

        final_url = await asyncio.to_thread(_sync_upload)
        if not final_url:
            return JSONResponse({"status": "error", "message": "Could not upload attachment to media cloud."}, status_code=500)

        return {
            "status": "success",
            "media_url": final_url,
            "filename": orig_name,
            "media_type": detected_type,
            "size_bytes": len(file_bytes),
            "size_formatted": _format_file_size_human(len(file_bytes))
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Attachment upload failed: {e}"}, status_code=500)


def _resolve_vault_file_for_dm_or_comment(
    file_id: str = "",
    media_url: str = "",
    platform: str = "facebook",
    account_id: str = "",
    preferred_api_key: str = "",
    **kwargs
) -> Optional[Dict[str, Any]]:
    """
    Resolves a Google Drive Vault `file_id` (e.g. 'file_c62491e3e8ba') or direct `media_url`
    by streaming the file in-memory directly from Google Drive to Zernio Media Cloud (zero local disk storage)
    and returning the public URL, clean original filename, accurate attachmentType ('image', 'video', 'audio', 'file'),
    and Google Drive file ID for native attachment delivery in Facebook, Instagram, Telegram, and WhatsApp.
    """
    fid = str(file_id or "").strip()
    m_url = str(media_url or "").strip()
    if not fid and not m_url:
        return None

    if fid:
        try:
            v_item = _transfer_vault_file_to_zernio_media_item(
                file_id=fid,
                platform=platform or "facebook",
                account_id=account_id or "",
                is_thumb=False,
                defer_to_runtime=False,
                preferred_api_key=preferred_api_key or ""
            )
            if v_item and v_item.get("url"):
                z_url = str(v_item["url"]).strip()
                g_fid = str(v_item.get("gdrive_file_id") or "").strip()
                raw_fname = str(v_item.get("filename") or kwargs.get("filename") or v_item.get("gdrive_file_name") or fid).strip()
                if raw_fname.startswith("file_") and "_" in raw_fname[5:]:
                    raw_fname = re.sub(r"^file_[a-fA-F0-9]+_", "", raw_fname)
                raw_ct = str(v_item.get("content_type") or "").strip()
                m_type = _detect_attachment_media_category(raw_fname, raw_ct, fallback_type=str(v_item.get("type") or "file"))
                return {
                    "file_id": fid,
                    "gdrive_file_id": g_fid,
                    "filename": raw_fname,
                    "content_type": _normalize_zernio_content_type(raw_fname, raw_ct, m_type),
                    "url": z_url,
                    "gdrive_view_url": f"https://drive.google.com/file/d/{g_fid}/view" if g_fid else z_url,
                    "type": m_type
                }
        except Exception as e:
            print(f"[⚠️ VAULT DM FILE RESOLVE WARNING] ({fid}): {e}")
            try:
                store = _load_files_vault_store(force_cloud=False)
                target = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == fid), None)
                if target:
                    g_fid = str(target.get("gdrive_file_id") or "").strip()
                    raw_fname = str(target.get("filename") or kwargs.get("filename") or fid).strip()
                    if raw_fname.startswith("file_") and "_" in raw_fname[5:]:
                        raw_fname = re.sub(r"^file_[a-fA-F0-9]+_", "", raw_fname)
                    raw_ct = str(target.get("content_type") or "").strip()
                    m_type = _detect_attachment_media_category(raw_fname, raw_ct, fallback_type="file")
                    dl_u = str(target.get("download_url") or (f"https://drive.google.com/uc?export=download&id={g_fid}" if g_fid else "")).strip()
                    if dl_u:
                        return {
                            "file_id": fid,
                            "gdrive_file_id": g_fid,
                            "filename": raw_fname,
                            "content_type": _normalize_zernio_content_type(raw_fname, raw_ct, m_type),
                            "url": dl_u,
                            "gdrive_view_url": f"https://drive.google.com/file/d/{g_fid}/view" if g_fid else dl_u,
                            "type": m_type
                        }
            except Exception:
                pass

    if m_url:
        low_u = m_url.lower().split("?")[0]
        passed_name = str(kwargs.get("filename") or "").strip()
        if not passed_name:
            base_u = os.path.basename(low_u)
            passed_name = base_u if base_u else "attachment"
        if passed_name.startswith("file_") and "_" in passed_name[5:]:
            passed_name = re.sub(r"^file_[a-fA-F0-9]+_", "", passed_name)
        passed_type = str(kwargs.get("media_type") or "").strip().lower()
        m_type = _detect_attachment_media_category(passed_name, "", fallback_type=(passed_type if passed_type in ("image", "video", "audio", "file") else "file"))
        return {
            "file_id": fid,
            "gdrive_file_id": "",
            "filename": passed_name,
            "content_type": _normalize_zernio_content_type(passed_name, "", m_type),
            "url": m_url,
            "gdrive_view_url": m_url,
            "type": m_type
        }
    return None


def _fetch_attachment_bytes_in_memory(att: Dict[str, Any]) -> Tuple[bytes, str, str]:
    """
    Streams attachment bytes strictly in-memory (RAM) from Google Drive or Zernio Media Cloud
    without ever writing to local disk, for multipart/form-data fallback if needed.
    Returns (file_bytes, filename, content_type).
    """
    att_name = str(att.get("name") or att.get("filename") or "attachment").strip()
    att_type = str(att.get("type") or "file").strip().lower()
    att_ct = str(att.get("content_type") or _normalize_zernio_content_type(att_name, "", att_type)).strip()
    g_fid = str(att.get("gdrive_file_id") or "").strip()
    att_url = str(att.get("url") or "").strip()

    if not g_fid and att.get("file_id"):
        try:
            store = _load_files_vault_store(force_cloud=False)
            t_entry = next((f for f in (store.get("files") or []) if str(f.get("file_id") or "") == str(att.get("file_id"))), None)
            if t_entry:
                g_fid = str(t_entry.get("gdrive_file_id") or "").strip()
        except Exception:
            pass

    if g_fid and is_gdrive_authorized():
        try:
            tok = gdrive_get_access_token(force_refresh=False)
            gd_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(g_fid, safe='')}?alt=media"
            r = requests.get(gd_url, headers={"Authorization": f"Bearer {tok}"}, timeout=60)
            if r.status_code == 200 and r.content:
                return r.content, att_name, att_ct
        except Exception as e:
            print(f"[⚠️ IN-MEMORY GDRIVE FETCH WARNING]: {e}")

    if att_url and att_url.startswith("http"):
        try:
            r = requests.get(att_url, timeout=60)
            if r.status_code == 200 and r.content:
                return r.content, att_name, att_ct
        except Exception as e:
            print(f"[⚠️ IN-MEMORY URL FETCH WARNING]: {e}")

    return b"", att_name, att_ct


def _post_zernio_conversation_attachment_request(
    send_ep: str,
    api_key: str,
    cand_acc_id: str,
    att: Dict[str, Any],
    caption_text: str = "",
    extra_fields: Optional[Dict[str, Any]] = None
) -> Any:
    """
    Dispatches a native file/image/video/audio attachment to Zernio's official
    POST /v1/inbox/conversations/{conversationId}/messages endpoint using Zernio's
    official schema fields: `attachmentUrl`, `attachmentType`, and `attachmentName`.
    Includes an automatic in-memory `multipart/form-data` binary stream fallback
    (Google Drive -> RAM -> Zernio Inbox) if the JSON URL payload is rejected.
    """
    headers = get_zernio_headers(api_key)
    att_url = str(att.get("url") or "").strip()
    att_type = str(att.get("type") or "file").strip().lower()
    if att_type not in ("image", "video", "audio", "file"):
        att_type = "file"
    att_name = str(att.get("name") or att.get("filename") or "attachment").strip()

    body: Dict[str, Any] = {
        "accountId": cand_acc_id,
        "attachmentUrl": att_url,
        "attachmentType": att_type,
        "attachmentName": att_name
    }
    if caption_text:
        body["message"] = caption_text
    if extra_fields:
        body.update(extra_fields)

    resp = HTTP_SESSION.post(send_ep, headers=headers, json=body, timeout=30)
    if resp.status_code in (200, 201):
        return resp

    # If Zernio schema validation requires `message` key to be present even when sending attachment only
    if "message" not in body and resp.status_code in (400, 422):
        body_with_empty = dict(body)
        body_with_empty["message"] = ""
        resp2 = HTTP_SESSION.post(send_ep, headers=headers, json=body_with_empty, timeout=30)
        if resp2.status_code in (200, 201):
            return resp2

    # If Zernio or platform rejected combined message + attachmentUrl, or rejected JSON attachmentUrl,
    # try in-memory multipart/form-data binary upload directly to /inbox/conversations/{id}/messages
    if resp.status_code in (400, 415, 422, 500):
        file_bytes, fname, fct = _fetch_attachment_bytes_in_memory(att)
        if file_bytes:
            mp_headers = {"Authorization": f"Bearer {api_key}"}
            mp_data: Dict[str, Any] = {
                "accountId": cand_acc_id,
                "attachmentType": att_type,
                "attachmentName": fname
            }
            if caption_text:
                mp_data["message"] = caption_text
            if extra_fields:
                for ek, ev in extra_fields.items():
                    mp_data[ek] = str(ev)
            for field_key in ("attachment", "file"):
                try:
                    mp_resp = HTTP_SESSION.post(
                        send_ep,
                        headers=mp_headers,
                        data=mp_data,
                        files={field_key: (fname, io.BytesIO(file_bytes), fct)},
                        timeout=60
                    )
                    if mp_resp.status_code in (200, 201):
                        print(f"[📎->✅ ZERNIO MULTIPART INBOX ATTACHMENT SENT] {fname} ({att_type})")
                        return mp_resp
                except Exception as mp_err:
                    print(f"[⚠️ ZERNIO MULTIPART INBOX ATTACHMENT WARNING] ({field_key}): {mp_err}")

    return resp


@router.post("/api/messages/send")
def send_direct_message_reply(payload: SendMessagePayload, trigger_n8n_webhook: bool = True):
    """
    Sends a direct chat message reply (with optional native file/image/video/audio attachment
    from Local Device or Google Drive Files Vault) via Zernio's official endpoint:
    POST /v1/inbox/conversations/{conversationId}/messages
    """
    msg_text = _sanitize_outbound_social_or_email_text(payload.message)
    payload.message = msg_text
    has_file_or_media = bool((payload.file_id or "").strip() or (payload.media_url or "").strip())
    if not msg_text and not has_file_or_media:
        return {"status": "error", "message": "Please type a message or attach a file before sending."}

    try:
        if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
            load_messages_store_from_cloudinary()

        deduplicate_and_merge_conversations_store()
        convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
        conv_key = f"{payload.account_id}_{payload.conversation_id}"
        target_conv = convs_store.get(conv_key)

        if not target_conv:
            for k, c_obj in convs_store.items():
                if not isinstance(c_obj, dict):
                    continue
                alt_ids = [str(x) for x in (c_obj.get("alternate_conversation_ids") or []) if x]
                if (
                    str(c_obj.get("conversation_id")) == str(payload.conversation_id)
                    or str(c_obj.get("platform_conversation_id")) == str(payload.conversation_id)
                    or str(c_obj.get("zernio_conversation_id")) == str(payload.conversation_id)
                    or str(payload.conversation_id) in alt_ids
                    or k == str(payload.conversation_id)
                ):
                    target_conv = c_obj
                    conv_key = k
                    break

        platform = ((target_conv or {}).get("platform") or "facebook").strip().lower()
        acc_name = (target_conv or {}).get("account_name") or platform.capitalize()
        stored_z_acc_id = str((target_conv or {}).get("zernio_account_id") or "").strip()
        pref_key = (target_conv or {}).get("zernio_api_key") or ""
        real_conv_id = str((target_conv or {}).get("conversation_id") or payload.conversation_id).strip()
        participant_id = str(payload.recipient_id or (target_conv or {}).get("participant_id") or "").strip()
        participant_name = str((target_conv or {}).get("participant_name") or "").strip()

        # If this conversation belongs to TextBee.dev SMS Gateway (platform == 'sms'), send directly via TextBee API
        if (
            platform == "sms"
            or str(payload.account_id).strip() == TEXTBEE_ACCOUNT_ID
            or str(payload.conversation_id).strip().startswith("sms_")
        ):
            target_phone = participant_id or str(payload.conversation_id).replace("sms_", "").strip()
            sms_res = _send_textbee_sms_and_upsert_conversation(
                recipient_phone=target_phone,
                message_text=msg_text or f"Attachment: {payload.filename or payload.media_url or ''}",
                recipient_name=participant_name or target_phone,
                trigger_n8n_webhook=trigger_n8n_webhook
            )
            if sms_res.get("status") == "success":
                return {
                    "status": "success",
                    "message_id": sms_res.get("message_id"),
                    "message": sms_res.get("message"),
                    "conversation": sms_res.get("conversation")
                }
            return {"status": "error", "message": sms_res.get("message") or "Failed to send SMS via TextBee.dev."}

        # Validate Telegram Social Username / Handle BEFORE attempting to send
        tg_handle_raw = str(
            (target_conv or {}).get("participant_handle")
            or (target_conv or {}).get("social_username")
            or participant_id
            or ""
        ).strip()
        if platform == "telegram":
            is_numeric_tg_chat_id = bool(re.fullmatch(r"-?\d{5,20}", tg_handle_raw))
            clean_tg_uname = tg_handle_raw.lstrip("@")
            is_valid_tg_uname = bool(
                clean_tg_uname
                and " " not in tg_handle_raw
                and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{4,31}", clean_tg_uname)
                and not clean_tg_uname.endswith("_")
                and "__" not in clean_tg_uname
            )
            if not is_numeric_tg_chat_id and not is_valid_tg_uname:
                return {
                    "status": "error",
                    "error_code": "INVALID_TELEGRAM_USERNAME",
                    "message": (
                        f"Telegram Error: Invalid Social Username / Handle ('{tg_handle_raw or 'Empty'}'). "
                        f"Telegram requires a valid @username (5–32 characters, letters, numbers, and underscores only, "
                        f"starting with a letter, no spaces). Please update the contact's Social Username / Handle in the Contacts tab."
                    )
                }

        # 1. Resolve ONLY the verified (api_key, zernio_account_id) pairs that actually own this Social Media Page
        verified_pairs = resolve_live_zernio_account_and_key_pairs(
            platform=platform,
            account_id=str(payload.account_id),
            account_name=acc_name,
            stored_z_acc_id=stored_z_acc_id,
            preferred_key=pref_key
        )
        if not verified_pairs:
            if platform == "telegram":
                return {
                    "status": "error",
                    "error_code": "TELEGRAM_SEND_ERROR",
                    "message": (
                        f"Telegram Error: Cannot send message to '{tg_handle_raw or participant_name}'. "
                        f"No active Telegram bot/account is connected or the username '{tg_handle_raw}' has not started a chat with your bot."
                    )
                }
            if platform == "whatsapp":
                return {
                    "status": "error",
                    "error_code": "WHATSAPP_SEND_ERROR",
                    "message": (
                        f"WhatsApp Error: Cannot send message to '{participant_id or participant_name}'. "
                        f"No connected WhatsApp Business account was found on your External API keys."
                    )
                }
            return {"status": "error", "message": "No External API key found for this Social Media Page."}

        resolved_media = _resolve_vault_file_for_dm_or_comment(
            file_id=payload.file_id or "",
            media_url=payload.media_url or "",
            platform=platform,
            account_id=str(payload.account_id),
            preferred_api_key=pref_key,
            filename=payload.filename or "",
            media_type=payload.media_type or ""
        )
        resolved_attachments: List[Dict[str, Any]] = []
        if resolved_media and resolved_media.get("url"):
            m_url = str(resolved_media["url"]).strip()
            m_type = str(resolved_media.get("type") or "file").strip()
            resolved_attachments.append({
                "type": m_type,
                "url": m_url,
                "name": str(resolved_media.get("filename") or "attachment"),
                "file_id": str(resolved_media.get("file_id") or ""),
                "gdrive_file_id": str(resolved_media.get("gdrive_file_id") or ""),
                "content_type": str(resolved_media.get("content_type") or "")
            })

        # 2. Build prioritized list of candidate conversationIds (prioritizing real_conv_id & payload.conversation_id first)
        candidate_conv_ids: List[str] = []

        def _add_candidate_cid(raw_val: Any, prepend: bool = False):
            if not raw_val:
                return
            s_val = str(raw_val).strip()
            if not s_val:
                return
            variants = [s_val]
            if s_val.startswith("conv_"):
                stripped = s_val[5:].strip()
                if stripped:
                    variants.append(stripped)
            for v in variants:
                if v in candidate_conv_ids:
                    if prepend:
                        candidate_conv_ids.remove(v)
                        candidate_conv_ids.insert(0, v)
                else:
                    if prepend:
                        candidate_conv_ids.insert(0, v)
                    else:
                        candidate_conv_ids.append(v)

        for raw_cid in (
            real_conv_id,
            str(payload.conversation_id).strip(),
            (target_conv or {}).get("zernio_conversation_id"),
            (target_conv or {}).get("platform_conversation_id"),
            *((target_conv or {}).get("alternate_conversation_ids") or []),
            participant_id,
            (target_conv or {}).get("participant_handle")
        ):
            _add_candidate_cid(raw_cid, prepend=False)

        if platform == "telegram" and tg_handle_raw:
            _add_candidate_cid(tg_handle_raw, prepend=False)
            _add_candidate_cid(tg_handle_raw.lstrip("@"), prepend=False)
            _add_candidate_cid(f"@{tg_handle_raw.lstrip('@')}", prepend=False)
        elif platform == "whatsapp" and participant_id:
            norm_wa = _normalize_sms_phone_number(participant_id)
            wa_digits = re.sub(r"\D", "", norm_wa or participant_id)
            if norm_wa:
                _add_candidate_cid(norm_wa, prepend=False)
            if wa_digits:
                _add_candidate_cid(wa_digits, prepend=False)
                _add_candidate_cid(f"{wa_digits}@s.whatsapp.net", prepend=False)

        sent_ok = False
        new_msg_id = f"msg_{int(time.time() * 1000)}"
        plat_msg_id = ""
        primary_error_text = ""
        primary_error_status = 0

        def _record_success_from_resp(resp_obj: Any, api_key: str, cand_acc_id: str, cid_used: str):
            nonlocal sent_ok, new_msg_id, plat_msg_id
            try:
                r_data = resp_obj.json() if resp_obj.text else {}
            except Exception:
                r_data = {}
            inner = r_data.get("data") or r_data.get("message") or r_data
            if isinstance(inner, dict):
                if inner.get("messageId") or inner.get("platformMessageId"):
                    plat_msg_id = str(inner.get("messageId") or inner.get("platformMessageId"))
                if inner.get("id") or inner.get("_id") or inner.get("messageId"):
                    new_msg_id = str(inner.get("id") or inner.get("_id") or inner.get("messageId"))
                if inner.get("conversationId") and target_conv is not None:
                    target_conv["zernio_conversation_id"] = str(inner.get("conversationId"))
            sent_ok = True
            if target_conv is not None:
                target_conv["zernio_account_id"] = cand_acc_id
                target_conv["zernio_api_key"] = api_key
                target_conv["conversation_id"] = cid_used

        def _execute_send_on_endpoint(send_ep: str, api_key: str, cand_acc_id: str, extra_fields: Optional[Dict[str, Any]] = None) -> Any:
            """
            Executes a message send (text-only, attachment-only, or text + native attachment)
            against `send_ep` (`POST /v1/inbox/conversations/{id}/messages`).
            Never appends raw URLs into `msg_text`.
            """
            headers = get_zernio_headers(api_key)
            if not resolved_attachments:
                body: Dict[str, Any] = {"accountId": cand_acc_id, "message": msg_text}
                if extra_fields:
                    body.update(extra_fields)
                return HTTP_SESSION.post(send_ep, headers=headers, json=body, timeout=25)

            att = resolved_attachments[0]
            # When user sends ONLY an attachment (no text message)
            if not msg_text:
                return _post_zernio_conversation_attachment_request(
                    send_ep=send_ep,
                    api_key=api_key,
                    cand_acc_id=cand_acc_id,
                    att=att,
                    caption_text="",
                    extra_fields=extra_fields
                )

            # When user sends BOTH text message AND an attachment:
            # On Facebook & Instagram, Meta's Messenger Graph API delivers text and media attachments
            # as separate message objects; sending the pure attachment request + text request guarantees
            # the recipient gets the native attachment bubble instead of dropping the attachment.
            if platform in ("facebook", "instagram"):
                txt_body: Dict[str, Any] = {"accountId": cand_acc_id, "message": msg_text}
                if extra_fields:
                    txt_body.update(extra_fields)
                txt_resp = HTTP_SESSION.post(send_ep, headers=headers, json=txt_body, timeout=20)
                att_resp = _post_zernio_conversation_attachment_request(
                    send_ep=send_ep,
                    api_key=api_key,
                    cand_acc_id=cand_acc_id,
                    att=att,
                    caption_text="",
                    extra_fields=extra_fields
                )
                if att_resp.status_code in (200, 201):
                    return att_resp
                return txt_resp if txt_resp.status_code not in (200, 201) else att_resp

            # On Telegram & WhatsApp, try combined caption + attachment first, then split if needed
            comb_resp = _post_zernio_conversation_attachment_request(
                send_ep=send_ep,
                api_key=api_key,
                cand_acc_id=cand_acc_id,
                att=att,
                caption_text=msg_text,
                extra_fields=extra_fields
            )
            if comb_resp.status_code in (200, 201):
                return comb_resp
            txt_body = {"accountId": cand_acc_id, "message": msg_text}
            if extra_fields:
                txt_body.update(extra_fields)
            HTTP_SESSION.post(send_ep, headers=headers, json=txt_body, timeout=20)
            return _post_zernio_conversation_attachment_request(
                send_ep=send_ep,
                api_key=api_key,
                cand_acc_id=cand_acc_id,
                att=att,
                caption_text="",
                extra_fields=extra_fields
            )

        def _try_send_with_pair_and_conv(api_key: str, cand_acc_id: str, cid_to_use: str) -> bool:
            nonlocal sent_ok, primary_error_text, primary_error_status
            headers = get_zernio_headers(api_key)
            safe_cid = requests.utils.quote(cid_to_use, safe="")
            send_ep = f"{ZERNIO_BASE_URL}/inbox/conversations/{safe_cid}/messages"
            thread_ctrl_ep = f"{ZERNIO_BASE_URL}/inbox/conversations/{safe_cid}/thread-control"
            accept_ep = f"{ZERNIO_BASE_URL}/inbox/conversations/{safe_cid}/accept"

            # ATTEMPT 1: Standard untagged send (Official Zernio payload with native attachmentUrl/attachmentType/attachmentName)
            first_status = 0
            first_err_text = ""
            try:
                resp = _execute_send_on_endpoint(send_ep, api_key, cand_acc_id)
                first_status = resp.status_code
                if resp.status_code in (200, 201):
                    _record_success_from_resp(resp, api_key, cand_acc_id, cid_to_use)
                    return True
                first_err_text = (resp.text or f"HTTP {resp.status_code}").strip()
                err_lower = first_err_text.lower()
                is_not_found_err = (
                    "account not found" in err_lower
                    or "conversation not found" in err_lower
                    or resp.status_code == 404
                )
                # Record ONLY the real primary error from the standard untagged attempt!
                if not primary_error_text or not is_not_found_err:
                    primary_error_text = first_err_text
                    primary_error_status = resp.status_code

                # If this conversation ID doesn't exist on this account, move to the next candidate ID immediately
                if resp.status_code in (401, 404) or is_not_found_err:
                    return False
            except Exception as req_err:
                if not primary_error_text:
                    primary_error_text = str(req_err)
                return False

            # ATTEMPT 2: Meta Handover Protocol (`POST /v1/inbox/conversations/{id}/thread-control` with action="take")
            if platform in ("facebook", "instagram") and first_status in (400, 403, 409, 422, 500):
                try:
                    tc_resp = HTTP_SESSION.post(
                        thread_ctrl_ep,
                        headers=headers,
                        json={"accountId": cand_acc_id, "action": "take"},
                        timeout=12
                    )
                    if tc_resp.status_code in (200, 201, 204):
                        retry_resp = _execute_send_on_endpoint(send_ep, api_key, cand_acc_id)
                        if retry_resp.status_code in (200, 201):
                            _record_success_from_resp(retry_resp, api_key, cand_acc_id, cid_to_use)
                            return True
                except Exception:
                    pass

            # ATTEMPT 3: Message Request Acceptance (`POST /v1/inbox/conversations/{id}/accept`)
            if first_status in (400, 403, 409, 422):
                try:
                    acc_resp = HTTP_SESSION.post(
                        accept_ep,
                        headers=headers,
                        json={"accountId": cand_acc_id, "message": msg_text or f"📎 {resolved_attachments[0]['name']}"},
                        timeout=15
                    )
                    if acc_resp.status_code in (200, 201):
                        if resolved_attachments:
                            _post_zernio_conversation_attachment_request(send_ep, api_key, cand_acc_id, resolved_attachments[0])
                        _record_success_from_resp(acc_resp, api_key, cand_acc_id, cid_to_use)
                        return True
                except Exception:
                    pass

            # ATTEMPT 4: Silent Tag Fallbacks (tried ONLY if standard send failed, and NEVER allowed to overwrite primary_error_text!)
            silent_tag_list: List[str] = []
            if platform == "facebook":
                silent_tag_list = ["ACCOUNT_UPDATE", "CONFIRMED_EVENT_UPDATE", "POST_PURCHASE_UPDATE", "HUMAN_AGENT"]
            elif platform == "instagram":
                silent_tag_list = ["HUMAN_AGENT"]

            for tag_name in silent_tag_list:
                try:
                    fb_resp = _execute_send_on_endpoint(
                        send_ep,
                        api_key,
                        cand_acc_id,
                        extra_fields={"messagingType": "MESSAGE_TAG", "messageTag": tag_name}
                    )
                    if fb_resp.status_code in (200, 201):
                        _record_success_from_resp(fb_resp, api_key, cand_acc_id, cid_to_use)
                        return True
                except Exception:
                    continue

            return False

        # Step 3: Live Conversation Discovery + Send Execution
        # Before relying on potentially old stored IDs, query Zernio's live conversations for this Page
        # so if the person has a NEWER active thread on Zernio, we try the NEWEST thread ID first!
        for pair in verified_pairs:
            api_key = pair["api_key"]
            cand_acc_id = pair["account_id"]
            headers = get_zernio_headers(api_key)

            try:
                list_resp = HTTP_SESSION.get(
                    f"{ZERNIO_BASE_URL}/inbox/conversations",
                    params={"accountId": cand_acc_id, "limit": 100},
                    headers=headers,
                    timeout=15
                )
                if list_resp.status_code == 200:
                    live_convs = extract_list_from_api_payload(list_resp.json() if list_resp.text else {}) or []
                    target_pname_norm = _normalize_participant_name_key(participant_name)
                    matched_live: List[Tuple[float, str]] = []
                    for idx_lc, lc in enumerate(live_convs):
                        if not isinstance(lc, dict):
                            continue
                        lc_id = str(lc.get("id") or lc.get("conversationId") or lc.get("platformConversationId") or "").strip()
                        if not lc_id:
                            continue
                        lc_pinfo = _extract_participant_from_conversation_obj(lc, cand_acc_id, acc_name, platform)
                        lc_pid = str(lc_pinfo.get("participant_id") or lc.get("participantId") or "").strip()
                        lc_pname_norm = _normalize_participant_name_key(lc_pinfo.get("participant_name") or lc.get("participantName") or "")

                        id_match = bool(participant_id and lc_pid and participant_id == lc_pid)
                        name_match = bool(target_pname_norm and lc_pname_norm and target_pname_norm == lc_pname_norm)
                        if id_match or name_match:
                            raw_ts = lc.get("updatedTime") or lc.get("updatedAt") or lc.get("lastMessageAt") or ""
                            ts_ep = _msg_iso_to_epoch(parse_meta_timestamp(raw_ts, fallback_offset_seconds=idx_lc)["iso"])
                            matched_live.append((ts_ep, lc_id))
                            plat_lc_id = str(lc.get("platformConversationId") or "").strip()
                            if plat_lc_id and plat_lc_id != lc_id:
                                matched_live.append((ts_ep - 0.1, plat_lc_id))

                    # Sort ascending so when we prepend each item, the NEWEST conversation ID ends up at index 0!
                    matched_live.sort(key=lambda x: x[0])
                    for _, m_cid in matched_live:
                        _add_candidate_cid(m_cid, prepend=True)
            except Exception:
                pass

            for cid_try in list(candidate_conv_ids):
                if _try_send_with_pair_and_conv(api_key, cand_acc_id, cid_try):
                    break
            if sent_ok:
                break

        # Step 4: Comment Private-Reply Fallback (if the person commented on any post of this Page, we can DM them via private-reply!)
        if not sent_ok and participant_name:
            try:
                target_pname_norm = _normalize_participant_name_key(participant_name)
                comments_map = CLOUDINARY_COMMENTS_STORE.get("comments") or {}
                matching_comments: List[Dict[str, Any]] = []
                for _, comm_obj in comments_map.items():
                    if not isinstance(comm_obj, dict):
                        continue
                    if str(comm_obj.get("account_id") or "") != str(payload.account_id):
                        continue
                    c_author_norm = _normalize_participant_name_key(comm_obj.get("author_name") or "")
                    c_author_id = str(comm_obj.get("author_id") or "").strip()
                    if (participant_id and c_author_id and participant_id == c_author_id) or (target_pname_norm and c_author_norm == target_pname_norm):
                        if comm_obj.get("post_id") and comm_obj.get("comment_id"):
                            matching_comments.append(comm_obj)

                matching_comments.sort(key=lambda x: _msg_iso_to_epoch(x.get("created_iso") or ""), reverse=True)
                for mc in matching_comments[:2]:
                    p_id_encoded = requests.utils.quote(str(mc["post_id"]), safe="")
                    c_id_encoded = requests.utils.quote(str(mc["comment_id"]), safe="")
                    pr_ep = f"{ZERNIO_BASE_URL}/inbox/comments/{p_id_encoded}/{c_id_encoded}/private-reply"
                    for pair in verified_pairs:
                        headers = get_zernio_headers(pair["api_key"])
                        pr_resp = HTTP_SESSION.post(
                            pr_ep,
                            headers=headers,
                            json={"accountId": pair["account_id"], "message": msg_text or f"📎 {resolved_attachments[0]['name']}"},
                            timeout=18
                        )
                        if pr_resp.status_code in (200, 201):
                            if resolved_attachments and real_conv_id:
                                safe_rcid = requests.utils.quote(real_conv_id, safe="")
                                _post_zernio_conversation_attachment_request(
                                    f"{ZERNIO_BASE_URL}/inbox/conversations/{safe_rcid}/messages",
                                    pair["api_key"],
                                    pair["account_id"],
                                    resolved_attachments[0]
                                )
                            _record_success_from_resp(pr_resp, pair["api_key"], pair["account_id"], real_conv_id)
                            break
                    if sent_ok:
                        break
            except Exception:
                pass

        if not sent_ok:
            readable_err = primary_error_text or "External API did not accept the message request."
            try:
                err_json = json.loads(readable_err)
                if isinstance(err_json, dict):
                    err_msg = (
                        err_json.get("message")
                        or err_json.get("error_description")
                        or err_json.get("error")
                        or readable_err
                    )
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message") or json.dumps(err_msg)
                    plat_err = err_json.get("platformError")
                    details = err_json.get("details") or err_json.get("error_user_msg") or ""
                    if isinstance(plat_err, dict) and plat_err.get("message"):
                        details = plat_err.get("message")
                    if details and str(details) not in str(err_msg):
                        readable_err = f"{err_msg} ({details})"
                    else:
                        readable_err = str(err_msg)
            except Exception:
                pass

            err_low = readable_err.lower()
            is_window_err = any(
                k in err_low
                for k in (
                    "outside of allowed window",
                    "allowed window",
                    "24 hour",
                    "24-hour",
                    "2018278",
                    "(#10)",
                    "(#100)",
                    "human_agent",
                    "cannot message",
                    "messaging window"
                )
            )
            if is_window_err:
                last_user_time = (target_conv or {}).get("display_time") or "more than 24 hours ago"
                msgs_in_conv = (target_conv or {}).get("messages") or []
                for m_rev in reversed(msgs_in_conv):
                    if isinstance(m_rev, dict) and not m_rev.get("is_own") and m_rev.get("display_time"):
                        last_user_time = m_rev["display_time"]
                        break
                return {
                    "status": "error",
                    "error_code": "META_24H_WINDOW_EXPIRED",
                    "message": (
                        f"Meta 24-Hour Messaging Window Limit: Meta (Facebook/Instagram Official API) does not allow "
                        f"third-party dashboards to reply to a conversation when more than 24 hours have passed since "
                        f"the customer's last message (Last message from {participant_name or 'customer'}: {last_user_time}). "
                        f"To reply to this older thread, please send a message directly in Meta Business Suite or Messenger first; "
                        f"once the customer replies again, real-time chat will automatically resume here in the dashboard."
                    )
                }

            if platform == "telegram":
                return {
                    "status": "error",
                    "error_code": "TELEGRAM_SEND_ERROR",
                    "message": (
                        f"Telegram Error: Failed to deliver message to Social Username / Handle '{tg_handle_raw or participant_name}'. "
                        f"Make sure the Telegram username is valid and that the user has started a conversation with your Telegram bot ({readable_err})."
                    )
                }

            return {"status": "error", "message": f"External API Message Error: {readable_err}"}

        now_dt = datetime.now(pytz.timezone("Asia/Manila"))
        preview_last_text = msg_text if msg_text else (f"📎 {resolved_attachments[0]['name']}" if resolved_attachments else "")
        sent_msg_obj = {
            "id": new_msg_id,
            "platform_message_id": plat_msg_id or new_msg_id,
            "sender_id": str(payload.account_id),
            "sender_name": acc_name,
            "sender_avatar": (target_conv or {}).get("account_avatar") or "",
            "is_own": True,
            "message": msg_text,
            "attachments": resolved_attachments,
            "created_iso": now_dt.isoformat(),
            "display_time": now_dt.strftime("%b %d, %Y • %I:%M %p")
        }

        if target_conv is not None:
            msgs = list(target_conv.get("messages") or [])
            target_conv["messages"] = _deduplicate_messages_list(msgs + [sent_msg_obj])
            target_conv["last_message_text"] = preview_last_text
            target_conv["last_message_is_own"] = True
            target_conv["updated_iso"] = sent_msg_obj["created_iso"]
            target_conv["display_time"] = sent_msg_obj["display_time"]
            target_conv["is_read"] = True
            target_conv["unread_count"] = 0
            save_messages_store_async()

        return {"status": "success", "message_id": new_msg_id, "message": sent_msg_obj}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class MarkMessagesReadPayload(BaseModel):
    conversation_ids: Optional[List[str]] = []
    mark_all: Optional[bool] = False

@router.post("/api/messages/mark_read")
def mark_conversations_as_read(payload: MarkMessagesReadPayload):
    try:
        now_iso = datetime.now(pytz.timezone("Asia/Manila")).isoformat()
        convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
        target_ids = set(str(x) for x in (payload.conversation_ids or []) if x)

        if payload.mark_all:
            for ckey, c_obj in convs_store.items():
                c_obj["is_read"] = True
                c_obj["unread_count"] = 0
                target_ids.add(ckey)
                if c_obj.get("conversation_id"):
                    target_ids.add(str(c_obj["conversation_id"]))
        else:
            for ckey, c_obj in convs_store.items():
                if ckey in target_ids or str(c_obj.get("conversation_id")) in target_ids:
                    c_obj["is_read"] = True
                    c_obj["unread_count"] = 0
                    target_ids.add(ckey)

        if target_ids:
            with db_engine.begin() as conn:
                for cid in target_ids:
                    conn.execute(
                        text("""
                            INSERT INTO glennbot_seen_messages (conversation_id, account_id, last_seen_iso)
                            VALUES (:cid, '', :iso)
                            ON CONFLICT (conversation_id) DO UPDATE SET
                                last_seen_iso = EXCLUDED.last_seen_iso,
                                seen_at = CURRENT_TIMESTAMP
                        """),
                        {"cid": cid, "iso": now_iso}
                    )
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class DeleteMessagesPayload(BaseModel):
    delete_all: Optional[bool] = False
    conversation_key: Optional[str] = ""
    conversation_id: Optional[str] = ""
    account_id: Optional[str] = ""
    platform: Optional[str] = ""
    message_id: Optional[str] = ""


@router.post("/api/messages/delete")
def delete_messages_or_conversations(payload: DeleteMessagesPayload):
    """
    Deletes:
    1. A single message bubble inside a conversation (when `message_id` is provided)
    2. An entire conversation thread (when `conversation_key` or `conversation_id` is provided without `message_id`)
    3. All conversations in the Messages modal (when `delete_all=True`, respecting optional `platform` / `account_id` filter)
    Records deleted message IDs and `deleted_at_epoch` so background sync never re-adds deleted messages.
    """
    try:
        if not CLOUDINARY_MESSAGES_STORE.get("loaded"):
            load_messages_store_from_cloudinary()

        convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
        global_del_list: List[str] = CLOUDINARY_MESSAGES_STORE.setdefault("deleted_message_ids", [])
        global_del_set = set(str(x) for x in global_del_list if x)
        now_ep = time.time()

        def _record_deleted_msg_id(conv_obj: Dict[str, Any], mid_val: str):
            clean_m = str(mid_val or "").strip()
            if not clean_m:
                return
            if clean_m not in global_del_set:
                global_del_set.add(clean_m)
                global_del_list.append(clean_m)
            conv_del = conv_obj.setdefault("deleted_message_ids", [])
            if clean_m not in conv_del:
                conv_del.append(clean_m)

        # CASE 1: DELETE ALL CONVERSATIONS (AT TOP OF MESSAGES MODAL)
        if payload.delete_all:
            plat_filter = str(payload.platform or "all").strip().lower()
            acc_filter = str(payload.account_id or "all").strip()
            deleted_conv_count = 0
            for ckey, c_obj in list(convs_store.items()):
                if not isinstance(c_obj, dict):
                    continue
                c_plat = str(c_obj.get("platform") or "").strip().lower()
                c_acc = str(c_obj.get("account_id") or "").strip()
                if plat_filter not in ("", "all") and c_plat != plat_filter:
                    continue
                if acc_filter not in ("", "all") and c_acc != acc_filter:
                    continue
                for m in (c_obj.get("messages") or []):
                    if isinstance(m, dict):
                        _record_deleted_msg_id(c_obj, m.get("id") or "")
                        _record_deleted_msg_id(c_obj, m.get("platform_message_id") or "")
                c_obj["messages"] = []
                c_obj["last_message_text"] = "No messages yet"
                c_obj["hidden"] = True
                c_obj["is_read"] = True
                c_obj["unread_count"] = 0
                c_obj["deleted_at_epoch"] = now_ep
                deleted_conv_count += 1

            save_messages_store_async()
            return {
                "status": "success",
                "mode": "delete_all",
                "deleted_conversations": deleted_conv_count,
                "message": f"Deleted {deleted_conv_count} conversation(s)."
            }

        # Find target conversation
        ckey_req = str(payload.conversation_key or "").strip()
        cid_req = str(payload.conversation_id or "").strip()
        aid_req = str(payload.account_id or "").strip()
        target_conv = None
        target_key = ""

        if ckey_req and ckey_req in convs_store:
            target_key = ckey_req
            target_conv = convs_store[ckey_req]
        elif aid_req and cid_req and f"{aid_req}_{cid_req}" in convs_store:
            target_key = f"{aid_req}_{cid_req}"
            target_conv = convs_store[target_key]
        else:
            for k, c_obj in convs_store.items():
                if not isinstance(c_obj, dict):
                    continue
                alt_ids = [str(x) for x in (c_obj.get("alternate_conversation_ids") or []) if x]
                if (
                    k == ckey_req
                    or k == cid_req
                    or str(c_obj.get("conversation_id") or "") == cid_req
                    or str(c_obj.get("platform_conversation_id") or "") == cid_req
                    or str(c_obj.get("zernio_conversation_id") or "") == cid_req
                    or (cid_req and cid_req in alt_ids)
                ):
                    if not aid_req or str(c_obj.get("account_id") or "") == aid_req:
                        target_key = k
                        target_conv = c_obj
                        break

        if not target_conv:
            return JSONResponse({"status": "error", "message": "Conversation not found."}, status_code=404)

        msg_id_req = str(payload.message_id or "").strip()

        # CASE 2: DELETE SINGLE MESSAGE BUBBLE INSIDE CONVERSATION
        if msg_id_req:
            _record_deleted_msg_id(target_conv, msg_id_req)
            old_msgs = list(target_conv.get("messages") or [])
            remaining_msgs = []
            for m in old_msgs:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or "").strip()
                pmid = str(m.get("platform_message_id") or "").strip()
                if mid == msg_id_req or pmid == msg_id_req:
                    _record_deleted_msg_id(target_conv, mid)
                    _record_deleted_msg_id(target_conv, pmid)
                    continue
                remaining_msgs.append(m)

            target_conv["messages"] = remaining_msgs
            if remaining_msgs:
                last_m = remaining_msgs[-1]
                target_conv["last_message_text"] = str(last_m.get("message") or "Attachment")
                target_conv["last_message_is_own"] = bool(last_m.get("is_own"))
                if last_m.get("created_iso"):
                    target_conv["updated_iso"] = last_m["created_iso"]
                if last_m.get("display_time"):
                    target_conv["display_time"] = last_m["display_time"]
            else:
                target_conv["last_message_text"] = "No messages yet"
                target_conv["last_message_is_own"] = False

            save_messages_store_async()
            return {
                "status": "success",
                "mode": "delete_message",
                "conversation_key": target_key,
                "message_id": msg_id_req,
                "remaining_count": len(remaining_msgs),
                "last_message_text": target_conv.get("last_message_text") or "No messages yet",
                "message": "Message deleted."
            }

        # CASE 3: DELETE ENTIRE CONVERSATION THREAD
        for m in (target_conv.get("messages") or []):
            if isinstance(m, dict):
                _record_deleted_msg_id(target_conv, m.get("id") or "")
                _record_deleted_msg_id(target_conv, m.get("platform_message_id") or "")

        target_conv["messages"] = []
        target_conv["last_message_text"] = "No messages yet"
        target_conv["hidden"] = True
        target_conv["is_read"] = True
        target_conv["unread_count"] = 0
        target_conv["deleted_at_epoch"] = now_ep

        save_messages_store_async()
        return {
            "status": "success",
            "mode": "delete_conversation",
            "conversation_key": target_key,
            "conversation_id": target_conv.get("conversation_id") or cid_req,
            "message": "Conversation deleted."
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


