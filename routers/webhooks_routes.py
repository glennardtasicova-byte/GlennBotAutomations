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
# --- INSTANT WEBHOOK RECEIVER (COMMENTS + DIRECT MESSAGES + TEXTBEE SMS -> CLOUDINARY) ---
# ==============================================================================

@router.get("/webhooks")
@router.get("/webhook")
@router.get("/api/webhook")
@router.get("/api/webhooks")
@router.get("/webhooks/composio")
@router.get("/api/webhooks/composio")
@router.get("/api/webhooks/email")
@router.get("/api/webhooks/zernio")
def verify_webhook_endpoint(request: Request):
    qp = request.query_params
    hub_challenge = qp.get("hub.challenge") or qp.get("challenge")
    if hub_challenge is not None:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    live_base = get_dynamic_base_url(request=request, prefer_public=True)
    return {
        "status": "active",
        "webhook_url": f"{live_base}/webhooks",
        "zernio_webhook_url": f"{live_base}/api/webhooks/zernio",
        "textbee_sms_webhook_url": f"{live_base}/api/webhooks/textbee/sms",
        "composio_webhook_url": f"{live_base}/webhooks",
        "composio_signing_secret_configured": True,
        "textbee_signing_secret_configured": bool(TEXTBEE_WEBHOOK_SECRET),
        "verify_token": WEBHOOK_VERIFY_TOKEN
    }

@router.post("/")
@router.post("/webhooks")
@router.post("/webhook")
@router.post("/api/webhook")
@router.post("/api/webhooks")
@router.post("/webhooks/composio")
@router.post("/api/webhooks/composio")
@router.post("/api/webhooks/email")
@router.post("/api/webhooks/zernio")
async def receive_webhook_event(request: Request):
    try:
        raw_bytes = await request.body()
        parsed_json = json.loads(raw_bytes.decode("utf-8")) if raw_bytes else {}
    except Exception:
        raw_bytes = b""
        parsed_json = {}

    # Support top-level batch arrays or multi-event lists so simultaneous webhook bursts never drop events
    if isinstance(parsed_json, list):
        batch_items = [item for item in parsed_json if isinstance(item, dict)]
        if not batch_items:
            return {"status": "received", "batch_count": 0}
        for item_dict in batch_items:
            N8N_WEBHOOK_EXECUTOR.submit(_receive_webhook_event_sync, request, item_dict, raw_bytes)
        return {"status": "received", "batch_count": len(batch_items), "queued": True}

    body = parsed_json if isinstance(parsed_json, dict) else {}
    if isinstance(body, dict) and "challenge" in body and len(body) <= 3:
        return {"challenge": body["challenge"]}

    # If payload contains a batch array under `events` or `records` (e.g. multiple simultaneous comments), fan out all items
    if isinstance(body.get("events"), list) and len(body["events"]) > 1:
        ev_list = [ev for ev in body["events"] if isinstance(ev, dict)]
        for ev_item in ev_list:
            N8N_WEBHOOK_EXECUTOR.submit(_receive_webhook_event_sync, request, ev_item, raw_bytes)
        return {"status": "received", "batch_count": len(ev_list), "queued": True}

    return await run_in_threadpool(lambda: _receive_webhook_event_sync(request, body, raw_bytes))


def _receive_webhook_event_sync(request: Request, body: Dict[str, Any], raw_bytes: bytes):

    if isinstance(body, dict) and "challenge" in body and len(body) <= 3:
        return {"challenge": body["challenge"]}

    req_path = str(request.url.path or "").lower()
    req_headers = {str(k).lower(): str(v) for k, v in request.headers.items()}

    # --- 0A. CHECK IF THIS IS A TEXTBEE.DEV INBOUND SMS WEBHOOK (MESSAGE_RECEIVED / X-Signature) ---
    if _is_textbee_sms_webhook_payload(body, req_headers, req_path, raw_bytes):
        return _handle_textbee_inbound_sms_webhook_event(body, raw_bytes, req_headers)

    # --- 0B. CHECK IF THIS IS A COMPOSIO REAL-TIME EMAIL WEBHOOK (GMAIL / OUTLOOK) ---
    if (
        "composio" in req_path
        or "/email" in req_path
        or ("_is_composio_email_webhook_payload" in globals() and _is_composio_email_webhook_payload(body, req_headers))
    ):
        if "_handle_composio_email_webhook_event" in globals():
            return _handle_composio_email_webhook_event(body, raw_bytes, req_headers)

    print(f"\n[⚡ EXTERNAL API WEBHOOK RECEIVED] Payload: {json.dumps(body)}")

    connected_items = refresh_connected_accounts_cache(force=False)
    if not connected_items or not get_all_zernio_keys():
        return {"status": "ignored", "reason": "no_connected_accounts"}

    event_name = str(body.get("event") or body.get("type") or "").strip().lower()
    root_obj = body.get("data") if isinstance(body.get("data"), dict) else body

    # --- 0.5 CHECK IF WEBHOOK IS A SCHEDULED POST STATUS EVENT (post.published, post.failed, post.partial) ---
    is_post_status_event = (
        event_name.startswith("post.")
        or (
            isinstance(body.get("post"), dict)
            and "comment" not in event_name
            and "message" not in event_name
            and not isinstance(root_obj.get("comment"), dict)
            and not isinstance(root_obj.get("message"), dict)
        )
    )
    if is_post_status_event:
        try:
            p_wh_obj = body.get("post") if isinstance(body.get("post"), dict) else (root_obj.get("post") if isinstance(root_obj.get("post"), dict) else root_obj)
            if isinstance(p_wh_obj, dict):
                z_wh_id = str(p_wh_obj.get("id") or p_wh_obj.get("_id") or "").strip()
                wh_caption = str(p_wh_obj.get("content") or p_wh_obj.get("caption") or "").strip()
                with db_engine.connect() as conn:
                    cand_rows = conn.execute(text("""
                        SELECT id, platform, page_id, account_name, post_type, caption,
                               media_preview_url, scheduled_time, status, status_message, external_post_id, permalink_url
                        FROM glennbot_scheduled_posts
                        ORDER BY scheduled_time DESC
                        LIMIT 60
                    """)).mappings().all()

                matched_sched_row = None
                for r_cand in cand_rows:
                    rc = dict(r_cand)
                    if str(rc.get("id") or "").startswith("post_ext_"):
                        continue
                    rc_ext = str(rc.get("external_post_id") or "").strip()
                    rc_msg = str(rc.get("status_message") or "")
                    if z_wh_id and (z_wh_id == rc_ext or z_wh_id in rc_msg):
                        matched_sched_row = rc
                        break
                if not matched_sched_row and wh_caption:
                    for r_cand in cand_rows:
                        rc = dict(r_cand)
                        if str(rc.get("id") or "").startswith("post_ext_"):
                            continue
                        if rc.get("status") in ("waiting", "processing") and (rc.get("caption") or "").strip() == wh_caption:
                            matched_sched_row = rc
                            break

                if matched_sched_row:
                    rec_id_wh = str(matched_sched_row["id"])
                    target_plat_wh = str(matched_sched_row.get("platform") or "")
                    outcome_wh = extract_zernio_post_outcome(p_wh_obj, target_platform=target_plat_wh)
                    if outcome_wh["state"] == "published" or "published" in event_name:
                        plat_pid = outcome_wh["platform_post_id"]
                        perm_url = outcome_wh["permalink"]
                        s_msg_wh = f"External API ID: {z_wh_id or matched_sched_row.get('external_post_id') or 'OK'}"
                        if plat_pid:
                            s_msg_wh += f" | Platform ID: {plat_pid}"
                        update_post_status(
                            rec_id_wh,
                            "published",
                            s_msg_wh,
                            external_post_id=plat_pid or z_wh_id or None,
                            permalink_url=perm_url or None
                        )
                        print(f"[✅ WEBHOOK POST PUBLISHED SYNCED TO SUPABASE] {rec_id_wh} ({target_plat_wh.upper()})")
                    elif outcome_wh["state"] == "failed" or "failed" in event_name:
                        err_wh = outcome_wh["error"] or "Failed to publish"
                        update_post_status(
                            rec_id_wh,
                            "failed",
                            f"External API Failed: {err_wh}",
                            external_post_id=z_wh_id or None
                        )
                        print(f"[❌ WEBHOOK POST FAILED SYNCED TO SUPABASE] {rec_id_wh}: {err_wh}")
                    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                    return {"status": "received", "type": "post_status", "record_id": rec_id_wh}
        except Exception as e:
            print(f"[⚠️ WEBHOOK POST STATUS PARSE WARNING]: {e}")
        return {"status": "received", "type": "post_status"}

    # --- A. CHECK IF WEBHOOK IS A DIRECT MESSAGE / CONVERSATION EVENT ---
    is_dm_event = (
        "message" in event_name
        or "conversation" in event_name
        or ("message" in root_obj and isinstance(root_obj.get("message"), dict) and "comment" not in root_obj)
        or ("conversation" in root_obj and isinstance(root_obj.get("conversation"), dict))
    )

    if is_dm_event:
        try:
            m_obj = root_obj.get("message") if isinstance(root_obj.get("message"), dict) else root_obj
            conv_obj = root_obj.get("conversation") if isinstance(root_obj.get("conversation"), dict) else (body.get("conversation") if isinstance(body.get("conversation"), dict) else {})
            acc_obj = root_obj.get("account") if isinstance(root_obj.get("account"), dict) else (body.get("account") if isinstance(body.get("account"), dict) else {})

            incoming_plat = str(
                m_obj.get("platform")
                or conv_obj.get("platform")
                or acc_obj.get("platform")
                or root_obj.get("platform")
                or ""
            ).strip().lower()
            incoming_acc_id = str(
                acc_obj.get("id")
                or acc_obj.get("_id")
                or acc_obj.get("accountId")
                or conv_obj.get("accountId")
                or m_obj.get("accountId")
                or ""
            ).strip()
            raw_incoming_uname = str(acc_obj.get("username") or acc_obj.get("displayName") or acc_obj.get("name") or "").strip()
            incoming_uname = raw_incoming_uname.lstrip("@").lower()

            matched_acc = None
            for acc in connected_items:
                if incoming_plat and (acc.get("platform") or "").strip().lower() != incoming_plat:
                    continue
                a_id = str(acc.get("account_id") or "").strip()
                a_uname = (acc.get("username") or "").strip().lstrip("@").lower()
                a_dname = (acc.get("account_name") or "").strip().lstrip("@").lower()
                if (
                    (incoming_acc_id and incoming_acc_id == a_id)
                    or (incoming_uname and incoming_uname in (a_uname, a_dname))
                    or (raw_incoming_uname and (_is_same_social_page_name(raw_incoming_uname, acc.get("account_name") or "") or _is_same_social_page_name(raw_incoming_uname, acc.get("username") or "")))
                ):
                    matched_acc = acc
                    break

            if not matched_acc and (incoming_acc_id or raw_incoming_uname):
                # Match via live Zernio accounts pool if incoming_acc_id is a Zernio _id and db has platformId or vice versa
                for force_flag in (False, True):
                    for za in fetch_zernio_connected_accounts(platform=incoming_plat or None, force=force_flag):
                        za_id = str(za.get("_id") or za.get("id") or "").strip()
                        za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
                        za_raw_name = str(za.get("displayName") or za.get("name") or za.get("username") or "").strip()
                        if _does_zernio_account_match_page(za, incoming_acc_id, "", raw_incoming_uname):
                            for acc in connected_items:
                                if incoming_plat and (acc.get("platform") or "").strip().lower() != incoming_plat:
                                    continue
                                a_id = str(acc.get("account_id") or "").strip()
                                if (
                                    a_id in (za_id, za_plat_id)
                                    or (za_raw_name and (_is_same_social_page_name(za_raw_name, acc.get("account_name") or "") or _is_same_social_page_name(za_raw_name, acc.get("username") or "")))
                                ):
                                    matched_acc = acc
                                    break
                        if matched_acc:
                            break
                    if matched_acc:
                        break

            if not matched_acc and incoming_plat:
                plat_conns = [acc for acc in connected_items if (acc.get("platform") or "").strip().lower() == incoming_plat]
                if len(plat_conns) == 1:
                    matched_acc = plat_conns[0]

            if matched_acc:
                db_acc_id = str(matched_acc.get("account_id") or "")
                acc_name = matched_acc.get("account_name") or incoming_plat.upper()
                plat = matched_acc.get("platform") or incoming_plat or "facebook"

                # Zernio webhook conversation has both `platformConversationId` (matches GET /inbox/conversations `id`) and `id` (Zernio internal id)
                plat_conv_id = str(
                    conv_obj.get("platformConversationId")
                    or m_obj.get("platformConversationId")
                    or m_obj.get("threadId")
                    or ""
                ).strip()
                z_conv_id = str(
                    conv_obj.get("id")
                    or conv_obj.get("_id")
                    or m_obj.get("conversationId")
                    or ""
                ).strip()
                sender_psid = str((m_obj.get("sender") or {}).get("id") or "").strip()
                conv_id = plat_conv_id or z_conv_id or sender_psid or f"conv_{uuid.uuid4().hex[:8]}"

                p_info = _extract_participant_from_conversation_obj(conv_obj or m_obj, db_acc_id, acc_name, plat)
                parsed_msg = _parse_single_message_item(
                    m_obj,
                    db_acc_id,
                    acc_name,
                    plat,
                    participant_fallback_name=p_info["participant_name"],
                    participant_fallback_avatar=p_info["participant_avatar"]
                )
                # If the webhook event itself is `message.sent` / `inbox.message.sent`, mark as own message
                if "sent" in event_name:
                    parsed_msg["is_own"] = True
                    parsed_msg["sender_name"] = acc_name

                has_valid_msg_content = bool((parsed_msg.get("message") or "").strip() or (parsed_msg.get("attachments") or []))

                part_id = str(
                    p_info["participant_id"]
                    or conv_obj.get("participantId")
                    or ("" if parsed_msg["is_own"] else parsed_msg.get("sender_id"))
                    or ""
                ).strip()
                part_name = (
                    p_info["participant_name"]
                    if parsed_msg["is_own"]
                    else (parsed_msg["sender_name"] if parsed_msg["sender_name"] not in ("User", "Facebook User", "Instagram User", "TikTok User") else p_info["participant_name"])
                )

                # If participant name is still generic (e.g. 'Facebook User' on a Private Reply webhook), resolve from commenter identity
                if not _normalize_participant_name_key(part_name):
                    resolved_wh_p = resolve_private_reply_participant(
                        platform=plat,
                        account_id=db_acc_id,
                        account_name=acc_name,
                        participant_id=part_id,
                        candidate_conv_ids=[conv_id, plat_conv_id, z_conv_id, sender_psid],
                        message_texts=[str(parsed_msg.get("message") or "")],
                        is_outbound_only_thread=bool(parsed_msg.get("is_own"))
                    )
                    if resolved_wh_p and _normalize_participant_name_key(resolved_wh_p.get("author_name") or ""):
                        part_name = resolved_wh_p["author_name"]
                        if resolved_wh_p.get("author_id") and not part_id:
                            part_id = resolved_wh_p["author_id"]
                        if resolved_wh_p.get("author_avatar") and not p_info.get("participant_avatar"):
                            p_info["participant_avatar"] = resolved_wh_p["author_avatar"]

                convs_store = CLOUDINARY_MESSAGES_STORE.setdefault("conversations", {})
                existing_conv = _find_existing_conversation_in_store(
                    convs_store,
                    db_acc_id=db_acc_id,
                    acc_name=acc_name,
                    platform=plat,
                    candidate_conv_ids=[conv_id, plat_conv_id, z_conv_id, sender_psid],
                    participant_id=part_id,
                    participant_name=part_name
                )

                alt_ids = []
                for cid_c in (conv_id, plat_conv_id, z_conv_id, part_id):
                    if cid_c and cid_c not in alt_ids:
                        alt_ids.append(cid_c)

                if existing_conv is None:
                    if has_valid_msg_content:
                        ckey = f"{db_acc_id}_{conv_id}"
                        convs_store[ckey] = {
                            "conv_key": ckey,
                            "conversation_id": conv_id,
                            "platform_conversation_id": plat_conv_id or conv_id,
                            "zernio_conversation_id": z_conv_id,
                            "alternate_conversation_ids": alt_ids,
                            "platform": plat,
                            "account_id": db_acc_id,
                            "zernio_account_id": incoming_acc_id or db_acc_id,
                            "zernio_api_key": get_zernio_key_for_account(incoming_acc_id or db_acc_id, account_name=acc_name, platform=plat),
                            "account_name": acc_name,
                            "account_avatar": matched_acc.get("avatar_url") or "",
                            "participant_id": part_id,
                            "participant_name": part_name,
                            "participant_handle": p_info["participant_handle"],
                            "participant_avatar": parsed_msg["sender_avatar"] if not parsed_msg["is_own"] else p_info["participant_avatar"],
                            "last_message_text": parsed_msg["message"],
                            "last_message_is_own": parsed_msg["is_own"],
                            "updated_iso": parsed_msg["created_iso"],
                            "display_time": parsed_msg["display_time"],
                            "unread_count": 0 if parsed_msg["is_own"] else 1,
                            "is_read": parsed_msg["is_own"],
                            "hidden": False,
                            "messages": [parsed_msg]
                        }
                else:
                    if incoming_acc_id:
                        existing_conv["zernio_account_id"] = incoming_acc_id
                    owner_k = get_zernio_key_for_account(incoming_acc_id or db_acc_id, account_name=acc_name, platform=plat)
                    if owner_k:
                        existing_conv["zernio_api_key"] = owner_k
                    if plat_conv_id:
                        existing_conv["platform_conversation_id"] = plat_conv_id
                    if z_conv_id:
                        existing_conv["zernio_conversation_id"] = z_conv_id
                    if conv_id:
                        existing_conv["conversation_id"] = conv_id

                    if _normalize_participant_name_key(part_name) and not _normalize_participant_name_key(existing_conv.get("participant_name") or ""):
                        existing_conv["participant_name"] = part_name

                    ex_alts = list(existing_conv.get("alternate_conversation_ids") or [])
                    for cid_c in alt_ids:
                        if cid_c not in ex_alts:
                            ex_alts.append(cid_c)
                    existing_conv["alternate_conversation_ids"] = ex_alts

                    if has_valid_msg_content:
                        msgs = list(existing_conv.get("messages") or [])
                        already_exists = any(_are_messages_duplicate(x, parsed_msg) for x in msgs)
                        existing_conv["messages"] = _deduplicate_messages_list(msgs + [parsed_msg])
                        existing_conv["last_message_text"] = parsed_msg["message"]
                        existing_conv["last_message_is_own"] = parsed_msg["is_own"]
                        existing_conv["updated_iso"] = parsed_msg["created_iso"]
                        existing_conv["display_time"] = parsed_msg["display_time"]
                        existing_conv["hidden"] = False
                        if not parsed_msg["is_own"] and not already_exists:
                            existing_conv["is_read"] = False
                            existing_conv["unread_count"] = int(existing_conv.get("unread_count") or 0) + 1
                            if parsed_msg["sender_name"] not in ("User", "Facebook User", "Instagram User", "TikTok User"):
                                existing_conv["participant_name"] = parsed_msg["sender_name"]
                            if parsed_msg["sender_avatar"] and not existing_conv.get("participant_avatar"):
                                existing_conv["participant_avatar"] = parsed_msg["sender_avatar"]

                deduplicate_and_merge_conversations_store(connected_items)
                save_messages_store_async()
                print(f"[💬 WEBHOOK DM SAVED TO CLOUDINARY] {parsed_msg['sender_name']} -> '{acc_name}': '{parsed_msg['message']}'")
                if "_notify_n8n_new_message" in globals() and not parsed_msg.get("is_own"):
                    _notify_n8n_new_message({
                        "platform": plat,
                        "account_id": db_acc_id,
                        "account_name": acc_name,
                        "conversation_id": conv_id,
                        "participant_id": part_id,
                        "participant_name": part_name
                    }, parsed_msg, is_background_sync=False)
                elif "_dispatch_outbound_n8n_webhook_async" in globals() and not parsed_msg.get("is_own"):
                    _dispatch_outbound_n8n_webhook_async("message.received", {
                        "platform": plat,
                        "account_id": db_acc_id,
                        "account_name": acc_name,
                        "conversation_id": conv_id,
                        "participant_id": part_id,
                        "participant_name": part_name,
                        "message": parsed_msg
                    })
        except Exception as e:
            print(f"[⚠️ WEBHOOK DM PARSE WARNING]: {e}")
        return {"status": "received", "type": "message"}

    # --- B. HANDLE COMMENT WEBHOOK EVENT ---
    matched_row = None
    try:
        c_obj = root_obj.get("comment") if isinstance(root_obj.get("comment"), dict) else root_obj
        p_obj = root_obj.get("post") if isinstance(root_obj.get("post"), dict) else (body.get("post") if isinstance(body.get("post"), dict) else {})
        acc_obj = root_obj.get("account") if isinstance(root_obj.get("account"), dict) else (body.get("account") if isinstance(body.get("account"), dict) else {})

        if isinstance(c_obj, dict):
            cid = str(c_obj.get("ID") or c_obj.get("id") or c_obj.get("commentId") or c_obj.get("_id") or c_obj.get("platform_id") or "").strip()
            msg_text = (c_obj.get("Text") or c_obj.get("text") or c_obj.get("message") or c_obj.get("content") or "").strip()

            plat_post_id = str(
                c_obj.get("platformPostId")
                or p_obj.get("platformPostId")
                or root_obj.get("platformPostId")
                or ""
            ).strip()
            z_post_id = str(
                c_obj.get("postId")
                or p_obj.get("id")
                or p_obj.get("_id")
                or root_obj.get("postId")
                or ""
            ).strip()
            incoming_post_id = plat_post_id or z_post_id
            plat_post_suffix = plat_post_id.split("_")[-1] if "_" in plat_post_id else plat_post_id
            native_page_prefix = plat_post_id.split("_")[0] if "_" in plat_post_id else ""

            raw_acc_candidates = [
                acc_obj.get("_id"),
                acc_obj.get("id"),
                acc_obj.get("accountId"),
                acc_obj.get("platformAccountId"),
                p_obj.get("accountId"),
                c_obj.get("accountId"),
                root_obj.get("accountId"),
                body.get("accountId"),
            ]
            incoming_acc_id = ""
            dict_acc_name_fallback = ""
            for cand_a in raw_acc_candidates:
                if isinstance(cand_a, dict):
                    extracted_aid = str(cand_a.get("_id") or cand_a.get("id") or cand_a.get("accountId") or cand_a.get("platformAccountId") or "").strip()
                    if extracted_aid and not incoming_acc_id:
                        incoming_acc_id = extracted_aid
                    if not dict_acc_name_fallback:
                        dict_acc_name_fallback = str(cand_a.get("displayName") or cand_a.get("name") or cand_a.get("username") or "").strip()
                elif cand_a is not None:
                    s_aid = str(cand_a).strip()
                    if s_aid and not s_aid.startswith("{") and not incoming_acc_id:
                        incoming_acc_id = s_aid

            raw_incoming_acc_name = str(
                acc_obj.get("displayName")
                or acc_obj.get("name")
                or acc_obj.get("username")
                or dict_acc_name_fallback
                or p_obj.get("accountName")
                or p_obj.get("pageName")
                or c_obj.get("accountName")
                or c_obj.get("pageName")
                or root_obj.get("accountName")
                or root_obj.get("pageName")
                or body.get("accountName")
                or body.get("pageName")
                or ""
            ).strip()
            incoming_acc_name = raw_incoming_acc_name.lstrip("@").lower()
            incoming_post_caption = str(
                p_obj.get("content")
                or p_obj.get("caption")
                or p_obj.get("text")
                or ""
            ).strip()
            incoming_plat = str(
                c_obj.get("platform")
                or p_obj.get("platform")
                or acc_obj.get("platform")
                or root_obj.get("platform")
                or body.get("platform")
                or ""
            ).strip().lower()

            parent_id = str(
                c_obj.get("parentCommentId")
                or c_obj.get("parentId")
                or c_obj.get("parent_id")
                or c_obj.get("inReplyToId")
                or c_obj.get("replyToCommentId")
                or c_obj.get("repliedToId")
                or (c_obj.get("parent") or {}).get("id")
                or root_obj.get("parentCommentId")
                or root_obj.get("parentId")
                or ""
            ).strip()
            # Ensure top-level comments where parentId == postId are NOT misclassified as replies
            wh_post_id_norms = {
                str(x).strip()
                for x in (plat_post_id, plat_post_suffix, z_post_id, incoming_post_id, cid)
                if x and str(x).strip()
            }
            if parent_id and (parent_id in wh_post_id_norms or _normalize_comment_key(parent_id) in wh_post_id_norms):
                parent_id = ""
            is_reply_flag = bool(c_obj.get("isReply") or c_obj.get("is_reply") or parent_id)

            if cid and msg_text:
                post_rows = _get_cached_published_posts(ttl_sec=3.5, force=False)

                connected_post_rows = [
                    dict(r) for r in post_rows
                    if is_post_account_connected(dict(r), connected_items)
                ]

                resolved_z_acc_id = ""
                resolved_api_key = ""
                cand_webhook_acc_ids = {x for x in (incoming_acc_id, native_page_prefix) if x}

                # Check cached Zernio accounts first (force=False) so webhook processing never hangs on external HTTP
                for za in fetch_zernio_connected_accounts(platform=incoming_plat or None, force=False):
                    if not isinstance(za, dict):
                        continue
                    za_id = str(za.get("_id") or za.get("id") or "").strip()
                    za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
                    za_uname = (za.get("username") or "").strip().lstrip("@").lower()
                    za_dname = (za.get("displayName") or za.get("name") or "").strip().lstrip("@").lower()
                    if (
                        (cand_webhook_acc_ids & {x for x in (za_id, za_plat_id) if x})
                        or (incoming_acc_name and incoming_acc_name in (za_uname, za_dname))
                        or _does_zernio_account_match_page(za, incoming_acc_id, native_page_prefix, raw_incoming_acc_name)
                    ):
                        resolved_z_acc_id = za_id or incoming_acc_id
                        resolved_api_key = str(za.get("_zernio_api_key") or "").strip()
                        if not raw_incoming_acc_name:
                            raw_incoming_acc_name = str(za.get("displayName") or za.get("name") or za.get("username") or "").strip()
                            incoming_acc_name = raw_incoming_acc_name.lstrip("@").lower()
                        break

                if not resolved_z_acc_id:
                    resolved_z_acc_id = incoming_acc_id

                # 1. Exact Match by Post ID
                for r_d in connected_post_rows:
                    row_known_ids = extract_all_known_ids_for_row(r_d)
                    s_msg = r_d.get("status_message") or ""
                    p_link = r_d.get("permalink_url") or ""
                    for cand_pid in (plat_post_id, plat_post_suffix, z_post_id):
                        if cand_pid and (cand_pid in row_known_ids or cand_pid in s_msg or (len(cand_pid) > 6 and cand_pid in p_link)):
                            matched_row = r_d
                            break
                    if matched_row:
                        break

                # 2. Match by Post Caption + Account
                if not matched_row and incoming_post_caption:
                    clean_inc_cap = _strip_invisible_guard_chars(incoming_post_caption).lower()
                    for r_d in connected_post_rows:
                        if incoming_plat and (r_d.get("platform") or "").strip().lower() != incoming_plat:
                            continue
                        if "Platform ID:" in (r_d.get("status_message") or ""):
                            continue
                        r_page_id = str(r_d.get("page_id") or "").strip()
                        r_acc_raw = str(r_d.get("account_name") or "").strip()
                        if resolved_z_acc_id or raw_incoming_acc_name:
                            valid_r_ids = _collect_valid_account_ids_for_page(incoming_plat, r_page_id, r_acc_raw)
                            page_ok = bool(
                                (resolved_z_acc_id and resolved_z_acc_id in valid_r_ids)
                                or (raw_incoming_acc_name and _is_same_social_page_name(raw_incoming_acc_name, r_acc_raw))
                            )
                            if not page_ok:
                                continue
                        if _strip_invisible_guard_chars(r_d.get("caption") or "").lower() == clean_inc_cap:
                            matched_row = r_d
                            break

                # 3. Facebook unlinked post fallback
                if not matched_row and incoming_plat == "facebook" and not z_post_id:
                    for r_d in connected_post_rows:
                        if (r_d.get("platform") or "").strip().lower() != "facebook":
                            continue
                        r_page_id = str(r_d.get("page_id") or "").strip()
                        r_acc_raw = str(r_d.get("account_name") or "").strip()
                        valid_r_ids = _collect_valid_account_ids_for_page("facebook", r_page_id, r_acc_raw)
                        if (resolved_z_acc_id and resolved_z_acc_id in valid_r_ids) or (raw_incoming_acc_name and _is_same_social_page_name(raw_incoming_acc_name, r_acc_raw)):
                            if "Platform ID:" not in (r_d.get("status_message") or ""):
                                matched_row = r_d
                                break

                # 4. Auto-import previous post if not scheduled via GlennBot, OR heal existing post_ext_ record if account was resolved
                synth_plat_post_id = plat_post_id or z_post_id or (f"wh_post_{resolved_z_acc_id or incoming_plat or 'social'}" if not matched_row else "")
                if synth_plat_post_id and (
                    not matched_row
                    or (str(matched_row.get("id") or "").startswith("post_ext_") and (resolved_z_acc_id or incoming_acc_name))
                ):
                    healed_or_created = ensure_external_post_record_in_db(
                        platform=incoming_plat or (matched_row.get("platform") if matched_row else "facebook"),
                        plat_post_id=plat_post_id or (extract_external_post_id(matched_row) if matched_row else synth_plat_post_id),
                        z_post_id=z_post_id,
                        account_id=resolved_z_acc_id,
                        account_name=raw_incoming_acc_name or incoming_acc_name,
                        caption=incoming_post_caption,
                        permalink=str(p_obj.get("permalink") or p_obj.get("platformPostUrl") or ""),
                        preview_url=str(p_obj.get("imageUrl") or ""),
                        connected_items=connected_items
                    )
                    if healed_or_created:
                        matched_row = healed_or_created
                        _invalidate_fast_db_cache(["published_posts"])

                # 5. Ultimate Zero-Drop Fallback: match by page account first before platform fallback, and persist virtual row in DB
                if not matched_row and (resolved_z_acc_id or raw_incoming_acc_name):
                    for r_d in connected_post_rows:
                        if incoming_plat and (r_d.get("platform") or "").strip().lower() != incoming_plat:
                            continue
                        r_page_id = str(r_d.get("page_id") or "").strip()
                        r_acc_raw = str(r_d.get("account_name") or "").strip()
                        valid_r_ids = _collect_valid_account_ids_for_page(incoming_plat or str(r_d.get("platform") or ""), r_page_id, r_acc_raw)
                        if (resolved_z_acc_id and resolved_z_acc_id in valid_r_ids) or (raw_incoming_acc_name and _is_same_social_page_name(raw_incoming_acc_name, r_acc_raw)):
                            matched_row = r_d
                            break
                if not matched_row:
                    fallback_acc = None
                    for a in connected_items:
                        if incoming_plat and (a.get("platform") or "").strip().lower() != incoming_plat:
                            continue
                        a_id = str(a.get("account_id") or "").strip()
                        a_name = str(a.get("account_name") or "").strip()
                        if (resolved_z_acc_id and a_id == resolved_z_acc_id) or (raw_incoming_acc_name and _is_same_social_page_name(raw_incoming_acc_name, a_name)):
                            fallback_acc = a
                            break
                    if not fallback_acc:
                        fallback_acc = next((a for a in connected_items if not incoming_plat or (a.get("platform") or "").strip().lower() == incoming_plat), connected_items[0])
                    fallback_ext_plat = incoming_plat or fallback_acc.get("platform") or "facebook"
                    fallback_ext_pid = synth_plat_post_id or "live"
                    fallback_ext_hash = hashlib.md5(f"{fallback_ext_plat}_{fallback_ext_pid}".encode("utf-8")).hexdigest()[:10]
                    matched_row = {
                        "id": f"post_ext_{fallback_ext_hash}",
                        "platform": fallback_ext_plat,
                        "page_id": str(fallback_acc.get("account_id") or resolved_z_acc_id or ""),
                        "account_name": raw_incoming_acc_name or fallback_acc.get("account_name") or fallback_ext_plat.upper(),
                        "post_type": "reels",
                        "caption": incoming_post_caption or "Social Media Post",
                        "scheduled_time": datetime.now(MANILA_TZ),
                        "status": "published",
                        "status_message": f"External Post | Platform ID: {synth_plat_post_id}",
                        "external_post_id": synth_plat_post_id,
                        "permalink_url": str(p_obj.get("permalink") or p_obj.get("platformPostUrl") or "")
                    }
                    try:
                        with db_engine.begin() as conn_fb:
                            conn_fb.execute(
                                text("""
                                    INSERT INTO glennbot_scheduled_posts
                                    (id, platform, page_id, account_name, post_type, caption, media_preview_url,
                                     scheduled_time, status, status_message, external_post_id, permalink_url)
                                    VALUES (:id, :plat, :pid, :aname, 'reels', :cap, '',
                                            :stime, 'published', :smsg, :extid, :plink)
                                    ON CONFLICT (id) DO UPDATE SET scheduled_time = EXCLUDED.scheduled_time
                                """),
                                {
                                    "id": matched_row["id"],
                                    "plat": matched_row["platform"],
                                    "pid": matched_row["page_id"],
                                    "aname": matched_row["account_name"],
                                    "cap": matched_row["caption"],
                                    "stime": matched_row["scheduled_time"],
                                    "smsg": matched_row["status_message"],
                                    "extid": matched_row["external_post_id"],
                                    "plink": matched_row["permalink_url"] or None
                                }
                            )
                        _invalidate_fast_db_cache(["published_posts"])
                    except Exception:
                        pass

                if matched_row:
                    rec_id = str(matched_row["id"])
                    w_permalink = str(p_obj.get("permalink") or p_obj.get("platformPostUrl") or matched_row.get("permalink_url") or "").strip()
                    if (plat_post_id and "Platform ID:" not in (matched_row.get("status_message") or "")) or (w_permalink and not matched_row.get("permalink_url")):
                        new_s_msg = matched_row.get("status_message") or ""
                        if plat_post_id and "Platform ID:" not in new_s_msg:
                            new_s_msg = f"{new_s_msg} | Platform ID: {plat_post_id}".strip(" |")
                        update_post_status(
                            rec_id,
                            matched_row["status"],
                            new_s_msg,
                            external_post_id=plat_post_id or extract_external_post_id(matched_row),
                            permalink_url=w_permalink or None
                        )
                        matched_row["status_message"] = new_s_msg
                        if plat_post_id:
                            matched_row["external_post_id"] = plat_post_id
                        if w_permalink:
                            matched_row["permalink_url"] = w_permalink
                        _invalidate_fast_db_cache(["published_posts"])

                    auth_obj = c_obj.get("Author") or c_obj.get("author") or c_obj.get("from") or c_obj.get("user") or {}
                    if not isinstance(auth_obj, dict):
                        auth_obj = {}
                    u_aid = str(auth_obj.get("ID") or auth_obj.get("id") or c_obj.get("author_id") or c_obj.get("authorId") or "").strip()
                    u_handle = (
                        c_obj.get("author_username")
                        or c_obj.get("username")
                        or auth_obj.get("Username")
                        or auth_obj.get("username")
                        or auth_obj.get("unique_id")
                        or ""
                    ).strip().lstrip("@")
                    u_name = (
                        c_obj.get("author_name")
                        or auth_obj.get("Name")
                        or auth_obj.get("name")
                        or auth_obj.get("displayName")
                        or auth_obj.get("nickname")
                        or ""
                    ).strip()
                    u_avatar = (
                        c_obj.get("author_picture")
                        or auth_obj.get("Picture")
                        or auth_obj.get("picture")
                        or auth_obj.get("avatarUrl")
                        or auth_obj.get("profilePictureUrl")
                        or auth_obj.get("avatar")
                        or ""
                    )
                    acc_name_clean = (matched_row.get("account_name") or "").strip().lstrip("@")
                    explicit_not_own_wh = (
                        c_obj.get("isOwnAccount") is False
                        or auth_obj.get("isOwnAccount") is False
                        or c_obj.get("isOwner") is False
                        or auth_obj.get("isOwner") is False
                    )
                    is_own = bool(
                        c_obj.get("IsOwner")
                        or c_obj.get("isOwner")
                        or c_obj.get("is_owner")
                        or c_obj.get("isOwnAccount")
                        or auth_obj.get("IsOwner")
                        or auth_obj.get("isOwner")
                        or auth_obj.get("is_owner")
                        or auth_obj.get("isOwnAccount")
                        or (not explicit_not_own_wh and acc_name_clean and u_handle and u_handle.lower() == acc_name_clean.lower())
                        or (is_reply_flag and not explicit_not_own_wh and acc_name_clean and u_name and u_name.lower() == acc_name_clean.lower())
                    )
                    commenter_name = (
                        f"{u_name} (@{u_handle})"
                        if (u_name and u_handle and u_name.lower() != u_handle.lower())
                        else (u_name or (f"@{u_handle}" if u_handle else "User"))
                    )

                    if commenter_name == "User" and not is_own:
                        known = lookup_known_author_identity(u_aid, rec_id)
                        if known and known.get("name"):
                            commenter_name = known["name"]
                            if not u_handle and known.get("handle"):
                                u_handle = known["handle"].lstrip("@")
                            if not u_avatar and known.get("avatar"):
                                u_avatar = known["avatar"]
                    elif commenter_name != "User" and u_aid and not is_own:
                        remember_author_identity(u_aid, commenter_name, f"@{u_handle}" if u_handle else "", u_avatar)

                    ts_info = parse_meta_timestamp(
                        c_obj.get("CreatedAt") or c_obj.get("createdAt") or c_obj.get("created_at") or c_obj.get("timestamp") or c_obj.get("createdTime") or "",
                        item_id=cid
                    )

                    if not is_own:
                        try:
                            with db_engine.begin() as conn:
                                conn.execute(text("DELETE FROM glennbot_seen_comments WHERE comment_id = :cid"), {"cid": cid})
                            _invalidate_fast_db_cache(["seen_comments"])
                        except Exception:
                            pass

                    eff_z_acc_id = resolved_z_acc_id or str(matched_row.get("page_id") or "")
                    eff_api_key = resolved_api_key or get_zernio_key_for_account(
                        eff_z_acc_id,
                        account_name=str(matched_row.get("account_name") or ""),
                        platform=str(matched_row.get("platform") or incoming_plat)
                    )

                    with COMMENTS_STORE_LOCK:
                        posts_store = CLOUDINARY_COMMENTS_STORE.setdefault("posts", {})
                        p_entry = posts_store.get(rec_id)
                        if p_entry and cid in (p_entry.get("deleted_comment_ids") or []):
                            p_entry["deleted_comment_ids"] = [x for x in p_entry["deleted_comment_ids"] if x != cid]

                        # Only treat cid_prefix as a parent comment ID if it is NOT the post ID / page ID prefix and matches an actual comment key
                        if not is_reply_flag and "_" in cid and p_entry and isinstance(p_entry.get("comments"), dict):
                            cid_prefix = cid.split("_")[0].strip()
                            post_and_page_prefixes = {
                                str(x).strip()
                                for x in (
                                    plat_post_id,
                                    plat_post_suffix,
                                    native_page_prefix,
                                    z_post_id,
                                    extract_external_post_id(matched_row),
                                    (extract_external_post_id(matched_row) or "").split("_")[0],
                                    (extract_external_post_id(matched_row) or "").split("_")[-1],
                                )
                                if x and str(x).strip()
                            }
                            if cid_prefix and cid_prefix not in post_and_page_prefixes and cid_prefix in p_entry["comments"]:
                                is_reply_flag = True
                                parent_id = cid_prefix

                        target_parent = None
                        if is_reply_flag:
                            c_map = (p_entry.get("comments") if (p_entry and isinstance(p_entry.get("comments"), dict)) else {}) or {}
                            target_parent = c_map.get(parent_id) if parent_id else None
                            if not target_parent and parent_id and c_map:
                                norm_p = _normalize_comment_key(parent_id)
                                for k_cid, p_comm in c_map.items():
                                    if _normalize_comment_key(k_cid) == norm_p:
                                        target_parent = p_comm
                                        break
                                    for ex_r in (p_comm.get("replies") or []):
                                        ex_rid = str(ex_r.get("id") or "").strip()
                                        if ex_rid and (ex_rid == parent_id or _normalize_comment_key(ex_rid) == norm_p):
                                            target_parent = p_comm
                                            break
                                    if target_parent:
                                        break
                            if not target_parent and c_map:
                                target_parent = next(iter(c_map.values()))

                            # CRITICAL: If a non-owner comment was flagged as a reply (e.g. parentId == postId) or no parent exists in store yet,
                            # do NOT drop it from GlennBot's Comments modal & live notification stack — fall through and save it as a comment!
                            if target_parent is None and not is_own:
                                is_reply_flag = False

                        if is_reply_flag:
                            resolved_parent_cid = str((target_parent or {}).get("comment_id") or parent_id or cid).strip()
                            parent_author_id_val = str((target_parent or {}).get("author_id") or "").strip()
                            parent_author_name_val = str((target_parent or {}).get("author_name") or "").strip()

                            if target_parent is not None:
                                if not is_own and commenter_name == "User":
                                    if parent_author_name_val and parent_author_name_val not in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"):
                                        commenter_name = parent_author_name_val
                                        if not u_avatar and target_parent.get("author_avatar"):
                                            u_avatar = target_parent["author_avatar"]
                                elif is_own and commenter_name in ("User", ""):
                                    commenter_name = matched_row.get("account_name") or matched_row["platform"].upper()

                                rep_item = {
                                    "id": cid,
                                    "parent_comment_id": resolved_parent_cid,
                                    "replied_to_id": parent_id or resolved_parent_cid,
                                    "author_id": u_aid or (eff_z_acc_id if is_own else ""),
                                    "author_name": commenter_name,
                                    "author_avatar": u_avatar,
                                    "is_own": is_own,
                                    "is_read": is_own,
                                    "can_reply": True,
                                    "message": msg_text,
                                    "created_iso": ts_info["iso"],
                                    "display_time": ts_info["display"]
                                }
                                target_parent["can_reply"] = False
                                reps = target_parent.setdefault("replies", [])
                                if not any(str(r.get("id")) == cid for r in reps):
                                    reps.append(rep_item)
                                if not is_own and p_entry:
                                    p_entry["notification_hidden"] = False
                                save_comments_store_async()
                                print(f"[🚀 WEBHOOK REPLY SAVED TO CLOUDINARY] Reply by {commenter_name} (is_own={is_own}): '{msg_text}'")

                            # Notify n8n for BOTH user replies AND Page replies to a comment (is_reply_flag=True)!
                            if "_notify_n8n_new_comment" in globals():
                                eff_author_name = (
                                    (matched_row.get("account_name") or matched_row["platform"].upper())
                                    if (is_own and commenter_name in ("User", ""))
                                    else commenter_name
                                )
                                eff_author_id = (
                                    u_aid
                                    or u_handle
                                    or (parent_author_id_val if is_own else "")
                                    or eff_z_acc_id
                                )
                                reply_notif_payload = {
                                    "comment_id": cid,
                                    "parent_comment_id": resolved_parent_cid,
                                    "replied_to_id": parent_id or resolved_parent_cid,
                                    "is_reply": True,
                                    "is_reply_to_comment": True,
                                    "zernio_post_id": incoming_post_id or extract_external_post_id(matched_row),
                                    "zernio_account_id": eff_z_acc_id,
                                    "zernio_api_key": eff_api_key,
                                    "record_id": rec_id,
                                    "external_post_id": extract_external_post_id(matched_row),
                                    "platform": matched_row["platform"],
                                    "page_id": str(matched_row.get("page_id") or ""),
                                    "account_name": matched_row.get("account_name") or matched_row["platform"].upper(),
                                    "author_name": eff_author_name,
                                    "author_handle": f"@{u_handle}" if u_handle else "",
                                    "author_id": eff_author_id,
                                    "parent_author_id": parent_author_id_val,
                                    "parent_author_name": parent_author_name_val,
                                    "author_avatar": u_avatar,
                                    "is_own_comment": is_own,
                                    "message": msg_text,
                                    "created_iso": ts_info["iso"],
                                    "display_time": ts_info["display"]
                                }
                                _notify_n8n_new_comment(matched_row, reply_notif_payload, is_background_sync=False)
                        elif not is_own:
                            instant_comment = {
                                "comment_id": cid,
                                "parent_comment_id": parent_id if is_reply_flag else "",
                                "is_reply": is_reply_flag,
                                "zernio_post_id": incoming_post_id or extract_external_post_id(matched_row),
                                "zernio_account_id": eff_z_acc_id,
                                "zernio_api_key": eff_api_key,
                                "auth_source": "external_api",
                                "record_id": rec_id,
                                "external_post_id": extract_external_post_id(matched_row),
                                "platform": matched_row["platform"],
                                "page_id": str(matched_row.get("page_id") or ""),
                                "account_name": matched_row.get("account_name") or matched_row["platform"].upper(),
                                "post_type": matched_row.get("post_type") or "reels",
                                "post_caption": matched_row.get("caption") or "",
                                "post_permalink": matched_row.get("permalink_url") or "",
                                "comment_permalink": c_obj.get("permalink") or matched_row.get("permalink_url") or "",
                                "author_name": commenter_name,
                                "author_handle": f"@{u_handle}" if u_handle else "",
                                "author_id": u_aid or u_handle,
                                "author_avatar": u_avatar,
                                "is_own_comment": False,
                                "message": msg_text,
                                "like_count": 0,
                                "created_iso": ts_info["iso"],
                                "display_time": ts_info["display"],
                                "is_read": False,
                                "replies": []
                            }
                            update_cloudinary_store_for_post(matched_row, [instant_comment], unhide_if_new=True, force_unhide=True)
                            save_comments_store_async()
                            print(f"[🚀 WEBHOOK COMMENT SAVED & UNHIDDEN IN CLOUDINARY] {commenter_name} on '{matched_row.get('account_name')}': '{msg_text}'")
                            if "_notify_n8n_new_comment" in globals():
                                _notify_n8n_new_comment(matched_row, instant_comment, is_background_sync=False)
    except Exception as e:
        print(f"[⚠️ WEBHOOK PARSE WARNING]: {e}")

    if matched_row:
        rec_sync_key = str(matched_row.get("id") or "")
        now_wh_ts = time.time()
        # Debounce background post sync per post (2.0s) so 10 simultaneous comments on the same post don't spawn 10 redundant Zernio syncs
        if (now_wh_ts - WEBHOOK_POST_SYNC_DEBOUNCE.get(rec_sync_key, 0.0)) >= 2.0:
            WEBHOOK_POST_SYNC_DEBOUNCE[rec_sync_key] = now_wh_ts
            try:
                BG_SYNC_EXECUTOR.submit(sync_single_post_to_cloudinary, matched_row, False)
            except Exception:
                threading.Thread(
                    target=sync_single_post_to_cloudinary,
                    kwargs={"r_dict": matched_row, "force_unhide": False},
                    daemon=True
                ).start()
    return {"status": "received", "synced": True}


YOUTUBE_AUTO_SYNC_STATE: Dict[str, Any] = {
    "running": False,
    "last_ts": 0.0,
    "last_inbox_discovery_ts": 0.0
}


def sync_youtube_and_active_posts_background(active_record_id: str = ""):
    if YOUTUBE_AUTO_SYNC_STATE.get("running"):
        return
    YOUTUBE_AUTO_SYNC_STATE["running"] = True
    try:
        now_ts = time.time()
        YOUTUBE_AUTO_SYNC_STATE["last_ts"] = now_ts

        # 0) Sync any due 'waiting' or 'processing' scheduled posts with Zernio & YouTube first
        # so newly published YouTube/Facebook videos are immediately marked 'published' in Supabase!
        sync_pending_scheduled_posts_with_zernio()

        # 1) Periodically query Zernio's /v1/inbox/comments list AND connected YouTube channels' recent videos/Shorts
        if (now_ts - YOUTUBE_AUTO_SYNC_STATE.get("last_inbox_discovery_ts", 0.0)) >= 6.0:
            YOUTUBE_AUTO_SYNC_STATE["last_inbox_discovery_ts"] = now_ts
            try:
                connected_items = refresh_connected_accounts_cache(force=False)
                get_zernio_posts_map(force=True)
                _ensure_recent_youtube_channel_videos_registered(connected_items, max_per_channel=6)
                for cp in get_zernio_commented_posts_list(force=True):
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
                _invalidate_fast_db_cache(["published_posts"])
            except Exception as disc_err:
                print(f"[⚠️ AUTO INBOX COMMENT DISCOVERY WARNING]: {disc_err}")

        # 2) Fetch published YouTube, Facebook, Instagram, and TikTok posts (plus active_record_id if any) and sync their comments/replies
        with db_engine.connect() as conn:
            if active_record_id:
                rows = conn.execute(
                    text("""
                        SELECT id, platform, page_id, account_name, post_type, caption,
                               scheduled_time, status, status_message, external_post_id, permalink_url
                        FROM glennbot_scheduled_posts
                        WHERE status = 'published'
                          AND (LOWER(platform) IN ('youtube', 'facebook', 'instagram', 'tiktok') OR id = :act_id)
                        ORDER BY scheduled_time DESC
                        LIMIT 45
                    """),
                    {"act_id": active_record_id}
                ).mappings().all()
            else:
                rows = conn.execute(
                    text("""
                        SELECT id, platform, page_id, account_name, post_type, caption,
                               scheduled_time, status, status_message, external_post_id, permalink_url
                        FROM glennbot_scheduled_posts
                        WHERE status = 'published'
                          AND LOWER(platform) IN ('youtube', 'facebook', 'instagram', 'tiktok')
                        ORDER BY scheduled_time DESC
                        LIMIT 45
                    """)
                ).mappings().all()

        if not rows:
            return

        connected_items = refresh_connected_accounts_cache(force=False)
        target_posts = [dict(r) for r in rows if is_post_account_connected(dict(r), connected_items)]
        if not target_posts:
            return

        max_workers = min(4, len(target_posts))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(sync_single_post_to_cloudinary, p_dict, False)
                for p_dict in target_posts
            ]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    pass
    except Exception as e:
        print(f"[⚠️ AUTO YOUTUBE SYNC WARNING]: {e}")
    finally:
        YOUTUBE_AUTO_SYNC_STATE["running"] = False


def trigger_auto_youtube_and_active_sync(active_record_id: str = "", min_interval: float = 6.0):
    now_ts = time.time()
    if YOUTUBE_AUTO_SYNC_STATE.get("running"):
        return
    if (now_ts - YOUTUBE_AUTO_SYNC_STATE.get("last_ts", 0.0)) < min_interval and not active_record_id:
        return
    threading.Thread(
        target=sync_youtube_and_active_posts_background,
        kwargs={"active_record_id": (active_record_id or "").strip()},
        daemon=True
    ).start()


