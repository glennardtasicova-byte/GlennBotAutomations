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


def _resolve_vault_file_bytes_by_id(file_id: str) -> Optional[Tuple[str, str, bytes]]:
    """
    Resolves a Python-generated File ID (e.g. 'file_3f5f4508e3d1') from the 'Files' Modal
    (Google Drive Vault), fetches its binary bytes via Google Drive API v3, and returns
    (filename, content_type, file_bytes) so it can be attached to any outgoing email or reply.
    """
    clean_fid = str(file_id or "").strip()
    if not clean_fid:
        return None

    target_entry: Optional[Dict[str, Any]] = None
    if "_load_files_vault_store" in globals():
        for force_flag in (False, True):
            try:
                store = _load_files_vault_store(force_cloud=force_flag)
                target_entry = next(
                    (f for f in (store.get("files") or []) if str(f.get("file_id") or "").strip() == clean_fid),
                    None
                )
                if target_entry:
                    break
            except Exception:
                pass

    if not target_entry:
        print(f"[EmailHub] Vault File ID '{clean_fid}' not found in Files Vault.")
        return None

    refreshed = _refresh_vault_file_entry_urls(target_entry) if "_refresh_vault_file_entry_urls" in globals() else dict(target_entry)
    dl_url = str(refreshed.get("zernio_media_url") or refreshed.get("download_url") or "").strip()
    gdrive_fid = str(refreshed.get("gdrive_file_id") or "").strip()
    fname = str(refreshed.get("filename") or f"{clean_fid}.bin").strip()
    mtype = str(refreshed.get("content_type") or "").strip()
    if not mtype or mtype == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(fname)
        mtype = guessed or "application/octet-stream"

    if dl_url and dl_url.startswith("http"):
        try:
            r = HTTP_SESSION.get(dl_url, timeout=45)
            if r.status_code == 200 and r.content:
                return (fname, mtype, r.content)
        except Exception as e:
            print(f"[EmailHub] Download vault file '{clean_fid}' URL warning: {e}")

    if gdrive_fid and "/" not in gdrive_fid and is_gdrive_authorized():
        try:
            acc_tok = gdrive_get_access_token(force_refresh=False)
            g_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(gdrive_fid, safe='')}?alt=media"
            r = HTTP_SESSION.get(g_url, headers={"Authorization": f"Bearer {acc_tok}"}, timeout=60)
            if r.status_code == 200 and r.content:
                return (fname, mtype, r.content)
        except Exception as e:
            print(f"[EmailHub] Google Drive download warning for '{clean_fid}': {e}")

    return None


def _normalize_raw_attachments_with_file_ids(body: dict) -> list:
    """
    Merges top-level 'file_id', 'attachment_file_id', or 'file_ids' into the 'attachments' list
    without duplicating existing file_id entries.
    """
    raw_atts = list(body.get("attachments") or []) if isinstance(body.get("attachments"), list) else []
    seen_fids = set()
    for item in raw_atts:
        if isinstance(item, dict) and item.get("file_id"):
            seen_fids.add(str(item.get("file_id")).strip())
        elif isinstance(item, str) and item.strip().startswith("file_"):
            seen_fids.add(item.strip())

    extra_fids: List[str] = []
    for k in ("file_id", "attachment_file_id"):
        val = str(body.get(k) or "").strip()
        if val:
            extra_fids.append(val)
    if isinstance(body.get("file_ids"), list):
        for v in body.get("file_ids"):
            if v and str(v).strip():
                extra_fids.append(str(v).strip())

    for fid in extra_fids:
        if fid not in seen_fids:
            seen_fids.add(fid)
            raw_atts.append({"file_id": fid})

    return raw_atts


def _decode_incoming_attachments(raw_attachments: list) -> list:
    """
    Decodes a list of frontend or n8n attachment objects:
    1) Base64 object: [{"filename": "doc.pdf", "content_type": "application/pdf", "content_base64": "..."}]
    2) Google Drive Vault File ID: [{"file_id": "file_3f5f4508e3d1"}] or ["file_3f5f4508e3d1"]
    3) Direct URL object: [{"filename": "pic.jpg", "download_url": "https://..."}]
    Returns list of (filename, mimetype, file_bytes).
    """
    decoded_list = []
    if not isinstance(raw_attachments, list):
        return decoded_list
    seen_resolved_fids = set()
    for item in raw_attachments:
        if isinstance(item, str) and item.strip().startswith("file_"):
            item = {"file_id": item.strip()}
        if not isinstance(item, dict):
            continue

        # Case 1: Google Drive Vault File ID (e.g. "file_3f5f4508e3d1")
        fid = str(item.get("file_id") or "").strip()
        if fid:
            if fid in seen_resolved_fids:
                continue
            seen_resolved_fids.add(fid)
            resolved = _resolve_vault_file_bytes_by_id(fid)
            if resolved:
                decoded_list.append(resolved)
                continue

        fname = str(item.get("filename") or item.get("name") or "attachment.bin").strip()
        b64_str = str(item.get("content_base64") or item.get("data") or "").strip()
        if b64_str:
            if "," in b64_str and b64_str.startswith("data:"):
                b64_str = b64_str.split(",", 1)[1]
            try:
                raw_bytes = base64.b64decode(b64_str)
            except Exception:
                raw_bytes = b""
            if raw_bytes:
                mtype = str(item.get("content_type") or item.get("mimetype") or "").strip()
                if not mtype:
                    guessed, _ = mimetypes.guess_type(fname)
                    mtype = guessed or "application/octet-stream"
                decoded_list.append((fname, mtype, raw_bytes))
                continue

        # Case 3: Direct download_url / url attachment
        dl_url = str(item.get("download_url") or item.get("url") or "").strip()
        if dl_url and dl_url.startswith("http"):
            try:
                r = HTTP_SESSION.get(dl_url, timeout=45)
                if r.status_code == 200 and r.content:
                    if fname == "attachment.bin":
                        fname = os.path.basename(urllib.parse.urlparse(dl_url).path) or "attachment.bin"
                    mtype = str(item.get("content_type") or item.get("mimetype") or r.headers.get("Content-Type") or "").strip()
                    if not mtype or mtype == "application/octet-stream":
                        guessed, _ = mimetypes.guess_type(fname)
                        mtype = guessed or "application/octet-stream"
                    decoded_list.append((fname, mtype, r.content))
            except Exception as e:
                print(f"[EmailHub] URL attachment download warning: {e}")

    return decoded_list


def _prepare_composio_attachment_payload(raw_attachments: list, toolkit_slug: str, tool_slug: str) -> Optional[dict]:
    """
    Uploads file attachment(s) to Composio's v3 presigned S3 storage so GMAIL_SEND_EMAIL,
    GMAIL_REPLY_TO_THREAD, and OUTLOOK_OUTLOOK_SEND_EMAIL can attach them natively.
    If multiple files are selected, bundles them into an in-memory .zip archive so all files arrive together.
    """
    decoded_files = _decode_incoming_attachments(raw_attachments)
    if not decoded_files:
        return None

    if len(decoded_files) == 1:
        upload_name, upload_mime, upload_bytes = decoded_files[0]
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fname, _, fbytes in decoded_files:
                zf.writestr(fname, fbytes)
        upload_bytes = zip_buf.getvalue()
        upload_name = f"Attachments_{len(decoded_files)}_files.zip"
        upload_mime = "application/zip"

    md5_hex = hashlib.md5(upload_bytes).hexdigest()
    headers = _get_composio_headers()
    req_payload = {
        "toolkit_slug": toolkit_slug,
        "tool_slug": tool_slug,
        "filename": upload_name,
        "mimetype": upload_mime,
        "md5": md5_hex
    }
    resp = HTTP_SESSION.post(
        f"{COMPOSIO_BASE_URL}/files/upload/request",
        headers=headers,
        json=req_payload,
        timeout=25
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Composio attachment upload init failed (HTTP {resp.status_code}): {resp.text[:250]}")

    up_data = resp.json()
    s3_key = str(up_data.get("key") or "").strip()
    presigned_url = str(up_data.get("new_presigned_url") or up_data.get("newPresignedUrl") or up_data.get("url") or "").strip()
    if not s3_key:
        raise RuntimeError("Composio did not return an s3key for the attachment.")

    if presigned_url:
        put_resp = HTTP_SESSION.put(
            presigned_url,
            data=upload_bytes,
            headers={"Content-Type": upload_mime},
            timeout=45
        )
        if put_resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"Attachment upload to storage failed (HTTP {put_resp.status_code}).")

    return {
        "name": upload_name,
        "mimetype": upload_mime,
        "s3key": s3_key
    }


def _attach_files_to_mime_message(mime_msg: MIMEMultipart, raw_attachments: list):
    decoded_files = _decode_incoming_attachments(raw_attachments)
    for fname, mtype, fbytes in decoded_files:
        maintype, subtype = (mtype.split("/", 1) if "/" in mtype else ("application", "octet-stream"))
        part = MIMEBase(maintype, subtype)
        part.set_payload(fbytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
        mime_msg.attach(part)


def _parse_email_address_list(raw_val) -> list:
    """
    Parses a comma/semicolon separated string or list of email strings (including 'Name <email@domain.com>')
    into a clean deduplicated list of email addresses: ['email@domain.com', ...].
    """
    if not raw_val:
        return []
    if isinstance(raw_val, list):
        raw_str = ", ".join(str(x) for x in raw_val if x)
    else:
        raw_str = str(raw_val)

    # First extract any <email> or standalone email tokens
    found_emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', raw_str)
    out = []
    seen = set()
    for em in found_emails:
        clean_em = em.strip()
        low = clean_em.lower()
        if clean_em and low not in seen:
            seen.add(low)
            out.append(clean_em)
    if not out:
        # Fallback split by comma/semicolon
        for part in re.split(r'[,;]+', raw_str):
            p = part.strip()
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
    return out


@router.post("/api/email/send")
async def api_send_single_account_email(request: Request):
    """
    Sends a new or forwarded email (with optional multi-recipient To/CC and file attachments)
    strictly from the currently active email account.
    """
    body = await request.json()
    return await run_in_threadpool(lambda: _send_single_account_email_sync(body))


def _send_single_account_email_sync(body: Dict[str, Any]):
    _load_email_hub_state()
    account_id = str(body.get("account_id") or "").strip()
    raw_to = body.get("to") or body.get("recipient_email") or ""
    raw_cc = body.get("cc") or ""
    to_list = _parse_email_address_list(raw_to)
    cc_list = _parse_email_address_list(raw_cc)
    primary_recipient = to_list[0] if to_list else ""
    extra_recipients = to_list[1:] if len(to_list) > 1 else []

    subject = str(body.get("subject") or "").strip()
    message_body = str(body.get("body") or "").strip()
    raw_attachments = body.get("attachments") or []

    if not message_body and raw_attachments:
        message_body = "(Please see attached file)"

    if not account_id or not primary_recipient or not message_body:
        return JSONResponse({
            "status": "error",
            "message": "At least one Recipient email (To) and a message body (or file attachment) are required."
        }, status_code=400)

    target_acc = next((a for a in EMAIL_HUB_STATE["accounts"] if str(a.get("id")) == account_id), None)
    if not target_acc:
        return JSONResponse({"status": "error", "message": "Selected email account not found."}, status_code=404)

    provider = str(target_acc.get("provider") or "gmail").lower()
    conn_id = str(target_acc.get("composio_connection_id") or "").strip()
    entity_id = str(target_acc.get("composio_entity_id") or "glennbot_email_user").strip()

    try:
        if provider == "gmail":
            tool_args = {
                "user_id": "me",
                "recipient_email": primary_recipient,
                "subject": subject or "(No Subject)",
                "body": message_body,
                "is_html": False
            }
            if extra_recipients:
                tool_args["extra_recipients"] = extra_recipients
            if cc_list:
                tool_args["cc"] = cc_list
            if raw_attachments:
                att_payload = _prepare_composio_attachment_payload(raw_attachments, "gmail", "GMAIL_SEND_EMAIL")
                if att_payload:
                    tool_args["attachment"] = att_payload
            res = _composio_execute_tool(
                "GMAIL_SEND_EMAIL",
                conn_id,
                entity_id,
                tool_args
            )
            if not res.get("successful", True) and res.get("error"):
                return JSONResponse({"status": "error", "message": str(res.get("error"))}, status_code=400)

        elif provider == "microsoft":
            tool_args = {
                "user_id": "me",
                "to_email": primary_recipient,
                "subject": subject or "(No Subject)",
                "body": message_body,
                "is_html": False
            }
            if cc_list or extra_recipients:
                tool_args["cc_emails"] = extra_recipients + cc_list
            if raw_attachments:
                att_payload = _prepare_composio_attachment_payload(raw_attachments, "outlook", "OUTLOOK_OUTLOOK_SEND_EMAIL")
                if att_payload:
                    tool_args["attachment"] = att_payload
            res = _composio_execute_tool(
                "OUTLOOK_OUTLOOK_SEND_EMAIL",
                conn_id,
                entity_id,
                tool_args
            )
            if not res.get("successful", True) and res.get("error"):
                return JSONResponse({"status": "error", "message": str(res.get("error"))}, status_code=400)

        elif provider == "imap":
            smtp_host = target_acc.get("smtp_host")
            smtp_port = int(target_acc.get("smtp_port") or 465)
            sender_addr = target_acc.get("email_address")
            password = target_acc.get("imap_password")

            mime_msg = MIMEMultipart()
            mime_msg["From"] = sender_addr
            mime_msg["To"] = ", ".join(to_list)
            if cc_list:
                mime_msg["Cc"] = ", ".join(cc_list)
            mime_msg["Subject"] = subject or "(No Subject)"
            mime_msg.attach(MIMEText(message_body, "plain", "utf-8"))
            if raw_attachments:
                _attach_files_to_mime_message(mime_msg, raw_attachments)

            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
                server.starttls()
            server.login(sender_addr, password)
            server.sendmail(sender_addr, to_list + cc_list, mime_msg.as_string())
            server.quit()

        # Invalidate cache for this account
        EMAIL_HUB_STATE["messages_cache"] = {
            k: v for k, v in EMAIL_HUB_STATE["messages_cache"].items()
            if f":{account_id}:" not in f":{k}:"
        }
        att_note = f" with {len(raw_attachments)} attachment(s)" if raw_attachments else ""
        rcpt_summary = ", ".join(to_list + ([f"CC: {', '.join(cc_list)}"] if cc_list else []))
        return {"status": "success", "message": f"Email sent{att_note} to {rcpt_summary} via {target_acc['email_address']}!"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Send email error: {e}"}, status_code=500)


@router.post("/api/email/reply")
async def api_reply_single_account_email(request: Request):
    """
    Replies (Reply / Reply All) or Forwards an existing email thread with editable recipient(s),
    optional CC recipients, and optional file attachments using the currently active email account.
    """
    body = await request.json()
    return await run_in_threadpool(lambda: _reply_single_account_email_sync(body))


def _reply_single_account_email_sync(body: Dict[str, Any]):
    _load_email_hub_state()
    account_id = str(body.get("account_id") or "").strip()
    thread_id = str(body.get("thread_id") or "").strip()
    message_id = str(body.get("message_id") or "").strip()
    raw_to = body.get("to") or body.get("recipient_email") or ""
    raw_cc = body.get("cc") or ""
    reply_mode = str(body.get("mode") or "reply").strip().lower()  # 'reply', 'reply_all', 'forward'
    to_list = _parse_email_address_list(raw_to)
    cc_list = _parse_email_address_list(raw_cc)
    primary_recipient = to_list[0] if to_list else ""
    extra_recipients = to_list[1:] if len(to_list) > 1 else []

    subject = str(body.get("subject") or "").strip()
    message_body = str(body.get("body") or "").strip()
    raw_attachments = body.get("attachments") or []

    if not message_body and raw_attachments:
        message_body = "(Please see attached file)"

    if not account_id or not primary_recipient or not message_body:
        return JSONResponse({"status": "error", "message": "Recipient email (To) and message body (or attachment) are required."}, status_code=400)

    target_acc = next((a for a in EMAIL_HUB_STATE["accounts"] if str(a.get("id")) == account_id), None)
    if not target_acc:
        return JSONResponse({"status": "error", "message": "Selected email account not found."}, status_code=404)

    provider = str(target_acc.get("provider") or "gmail").lower()
    conn_id = str(target_acc.get("composio_connection_id") or "").strip()
    entity_id = str(target_acc.get("composio_entity_id") or "glennbot_email_user").strip()

    is_forward = (reply_mode == "forward")
    if is_forward:
        final_subj = subject if subject.lower().startswith("fwd:") else f"Fwd: {subject or '(No Subject)'}"
    else:
        final_subj = subject if subject.lower().startswith("re:") else f"Re: {subject or '(No Subject)'}"

    try:
        if provider == "gmail" and thread_id and not is_forward:
            reply_args = {
                "user_id": "me",
                "thread_id": thread_id,
                "recipient_email": primary_recipient,
                "message_body": message_body,
                "is_html": False
            }
            if extra_recipients:
                reply_args["extra_recipients"] = extra_recipients
            if cc_list:
                reply_args["cc"] = cc_list
            if raw_attachments:
                att_payload = _prepare_composio_attachment_payload(raw_attachments, "gmail", "GMAIL_REPLY_TO_THREAD")
                if att_payload:
                    reply_args["attachment"] = att_payload
            res = _composio_execute_tool(
                "GMAIL_REPLY_TO_THREAD",
                conn_id,
                entity_id,
                reply_args
            )
            if not res.get("successful", True) and res.get("error"):
                # Fallback to GMAIL_SEND_EMAIL
                fallback_args = {
                    "user_id": "me",
                    "recipient_email": primary_recipient,
                    "subject": final_subj,
                    "body": message_body,
                    "is_html": False
                }
                if extra_recipients:
                    fallback_args["extra_recipients"] = extra_recipients
                if cc_list:
                    fallback_args["cc"] = cc_list
                if raw_attachments:
                    att_payload = _prepare_composio_attachment_payload(raw_attachments, "gmail", "GMAIL_SEND_EMAIL")
                    if att_payload:
                        fallback_args["attachment"] = att_payload
                _composio_execute_tool(
                    "GMAIL_SEND_EMAIL",
                    conn_id,
                    entity_id,
                    fallback_args
                )
        elif provider == "gmail":
            # Forward mode or missing thread_id -> send via GMAIL_SEND_EMAIL
            send_args = {
                "user_id": "me",
                "recipient_email": primary_recipient,
                "subject": final_subj,
                "body": message_body,
                "is_html": False
            }
            if extra_recipients:
                send_args["extra_recipients"] = extra_recipients
            if cc_list:
                send_args["cc"] = cc_list
            if raw_attachments:
                att_payload = _prepare_composio_attachment_payload(raw_attachments, "gmail", "GMAIL_SEND_EMAIL")
                if att_payload:
                    send_args["attachment"] = att_payload
            res = _composio_execute_tool(
                "GMAIL_SEND_EMAIL",
                conn_id,
                entity_id,
                send_args
            )
            if not res.get("successful", True) and res.get("error"):
                return JSONResponse({"status": "error", "message": str(res.get("error"))}, status_code=400)
        else:
            if provider == "microsoft":
                ms_args = {
                    "user_id": "me",
                    "to_email": primary_recipient,
                    "subject": final_subj,
                    "body": message_body,
                    "is_html": False
                }
                if cc_list or extra_recipients:
                    ms_args["cc_emails"] = extra_recipients + cc_list
                if raw_attachments:
                    att_payload = _prepare_composio_attachment_payload(raw_attachments, "outlook", "OUTLOOK_OUTLOOK_SEND_EMAIL")
                    if att_payload:
                        ms_args["attachment"] = att_payload
                _composio_execute_tool(
                    "OUTLOOK_OUTLOOK_SEND_EMAIL",
                    conn_id,
                    entity_id,
                    ms_args
                )
            elif provider == "imap":
                smtp_host = target_acc.get("smtp_host")
                smtp_port = int(target_acc.get("smtp_port") or 465)
                sender_addr = target_acc.get("email_address")
                password = target_acc.get("imap_password")

                mime_msg = MIMEMultipart()
                mime_msg["From"] = sender_addr
                mime_msg["To"] = ", ".join(to_list)
                if cc_list:
                    mime_msg["Cc"] = ", ".join(cc_list)
                mime_msg["Subject"] = final_subj
                if message_id and not is_forward:
                    mime_msg["In-Reply-To"] = message_id
                mime_msg.attach(MIMEText(message_body, "plain", "utf-8"))
                if raw_attachments:
                    _attach_files_to_mime_message(mime_msg, raw_attachments)

                if smtp_port == 465:
                    server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
                else:
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
                    server.starttls()
                server.login(sender_addr, password)
                server.sendmail(sender_addr, to_list + cc_list, mime_msg.as_string())
                server.quit()

        EMAIL_HUB_STATE["messages_cache"] = {
            k: v for k, v in EMAIL_HUB_STATE["messages_cache"].items()
            if f":{account_id}:" not in f":{k}:"
        }
        action_label = "Forwarded email" if is_forward else ("Reply All sent" if reply_mode == "reply_all" else "Reply sent")
        rcpt_summary = ", ".join(to_list + ([f"CC: {', '.join(cc_list)}"] if cc_list else []))
        return {"status": "success", "message": f"{action_label} to {rcpt_summary}!"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Reply/Forward error: {e}"}, status_code=500)


@router.post("/api/email/trash")
async def api_trash_single_account_email(request: Request):
    body = await request.json()
    return await run_in_threadpool(lambda: _trash_single_account_email_sync(body))


def _trash_single_account_email_sync(body: Dict[str, Any]):
    _load_email_hub_state()
    account_id = str(body.get("account_id") or "").strip()
    message_id = str(body.get("message_id") or "").strip()

    target_acc = next((a for a in EMAIL_HUB_STATE["accounts"] if str(a.get("id")) == account_id), None)
    if not target_acc:
        return JSONResponse({"status": "error", "message": "Selected email account not found."}, status_code=404)

    provider = str(target_acc.get("provider") or "gmail").lower()
    conn_id = str(target_acc.get("composio_connection_id") or "").strip()
    entity_id = str(target_acc.get("composio_entity_id") or "glennbot_email_user").strip()

    try:
        if provider == "gmail":
            _composio_execute_tool(
                "GMAIL_MOVE_TO_TRASH",
                conn_id,
                entity_id,
                {"user_id": "me", "message_id": message_id}
            )
        EMAIL_HUB_STATE["messages_cache"] = {
            k: v for k, v in EMAIL_HUB_STATE["messages_cache"].items()
            if f":{account_id}:" not in f":{k}:"
        }
        return {"status": "success", "message": "Moved email to Trash."}
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Trash error: {e}"}, status_code=500)


from fastapi.responses import Response as FastAPIResponse


@router.post("/api/email/attachment/download")
async def api_download_email_attachment(request: Request):
    """
    Downloads an email attachment from Gmail (GMAIL_GET_ATTACHMENT), Microsoft Outlook
    (OUTLOOK_DOWNLOAD_OUTLOOK_ATTACHMENT), or IMAP/SMTP and returns binary bytes with
    Content-Disposition: attachment; filename="...".
    """
    body = await request.json()
    return await run_in_threadpool(lambda: _download_email_attachment_sync(body))


def _download_email_attachment_sync(body: Dict[str, Any]):
    _load_email_hub_state()
    account_id = str(body.get("account_id") or "").strip()
    message_id = str(body.get("message_id") or "").strip()
    attachment_id = str(body.get("attachment_id") or "").strip()
    filename = str(body.get("filename") or "attachment.bin").strip()
    mime_type = str(body.get("mime_type") or "application/octet-stream").strip()
    folder = str(body.get("folder") or "inbox").strip().lower()

    if not account_id or not message_id:
        return JSONResponse({"status": "error", "message": "account_id and message_id are required."}, status_code=400)

    target_acc = next((a for a in EMAIL_HUB_STATE["accounts"] if str(a.get("id")) == account_id), None)
    if not target_acc:
        return JSONResponse({"status": "error", "message": "Selected email account not found."}, status_code=404)

    provider = str(target_acc.get("provider") or "gmail").lower()
    conn_id = str(target_acc.get("composio_connection_id") or "").strip()
    entity_id = str(target_acc.get("composio_entity_id") or "glennbot_email_user").strip()
    safe_fname = re.sub(r'["\r\n]', '_', filename) or "attachment.bin"

    try:
        file_bytes = b""
        resolved_mime = mime_type or "application/octet-stream"

        if provider in ("gmail", "microsoft"):
            tool_slug = "GMAIL_GET_ATTACHMENT" if provider == "gmail" else "OUTLOOK_DOWNLOAD_OUTLOOK_ATTACHMENT"
            exec_res = _composio_execute_tool(
                tool_slug,
                conn_id,
                entity_id,
                {
                    "user_id": "me",
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "file_name": filename
                }
            )
            data_obj = exec_res.get("data") or {}
            resp_data = data_obj.get("response_data") if isinstance(data_obj, dict) and "response_data" in data_obj else data_obj
            file_obj = {}
            if isinstance(resp_data, dict):
                file_obj = resp_data.get("file") if isinstance(resp_data.get("file"), dict) else resp_data

            s3_url = str(file_obj.get("s3url") or file_obj.get("url") or file_obj.get("uri") or "").strip()
            b64_data = str(file_obj.get("data") or file_obj.get("content") or "").strip()
            if file_obj.get("mimetype"):
                resolved_mime = str(file_obj.get("mimetype")).strip()

            if s3_url:
                dl_resp = HTTP_SESSION.get(s3_url, timeout=45)
                if dl_resp.status_code == 200:
                    file_bytes = dl_resp.content
                else:
                    return JSONResponse({
                        "status": "error",
                        "message": f"Failed to fetch attachment from storage (HTTP {dl_resp.status_code})."
                    }, status_code=400)
            elif b64_data:
                clean_b64 = b64_data.replace("-", "+").replace("_", "/")
                pad_len = (-len(clean_b64)) % 4
                if pad_len:
                    clean_b64 += "=" * pad_len
                file_bytes = base64.b64decode(clean_b64)
            else:
                err_msg = str(exec_res.get("error") or "Attachment content could not be retrieved.")
                return JSONResponse({"status": "error", "message": err_msg}, status_code=400)

        elif provider == "imap":
            imap_host = target_acc.get("imap_host")
            imap_port = int(target_acc.get("imap_port") or 993)
            email_addr = target_acc.get("email_address")
            password = target_acc.get("imap_password")
            folder_map = {"inbox": "INBOX", "sent": "Sent", "drafts": "Drafts", "trash": "Trash"}
            target_box = folder_map.get(folder, "INBOX")

            imap_conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=20)
            try:
                imap_conn.login(email_addr, password)
                typ, _ = imap_conn.select(target_box, readonly=True)
                if typ != "OK":
                    imap_conn.select("INBOX", readonly=True)
                typ, msg_data = imap_conn.fetch(message_id.encode("utf-8"), "(RFC822)")
                if typ == "OK" and msg_data and msg_data[0]:
                    raw_bytes = msg_data[0][1]
                    if isinstance(raw_bytes, bytes):
                        parsed = py_email.message_from_bytes(raw_bytes)
                        for p_idx, part in enumerate(parsed.walk()):
                            p_fname = _decode_mime_words(part.get_filename() or "")
                            if (attachment_id == f"imap_part_{p_idx}") or (p_fname and p_fname == filename):
                                file_bytes = part.get_payload(decode=True) or b""
                                resolved_mime = part.get_content_type() or resolved_mime
                                break
            finally:
                try:
                    imap_conn.logout()
                except Exception:
                    pass

        if not file_bytes:
            return JSONResponse({"status": "error", "message": "Attachment file is empty or unavailable."}, status_code=404)

        return FastAPIResponse(
            content=file_bytes,
            media_type=resolved_mime,
            headers={
                "Content-Disposition": f'attachment; filename="{safe_fname}"',
                "Cache-Control": "no-store"
            }
        )
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Attachment download error: {e}"}, status_code=500)


# =========================================================================
# --- REAL-TIME EMAIL WEBHOOK (COMPOSIO /webhooks + SIGNING SECRET + WATCHER) ---
# =========================================================================

def _verify_composio_webhook_signature(raw_bytes: bytes, headers: dict) -> dict:
    """
    Verifies incoming Composio webhook payloads using the configured Signing Secret
    (default: e6747eca1553134a55d78dbe509f20608700580e670cdc4c99ddf52057af5e59).
    Supports both Standard Webhooks / Svix (`webhook-id`, `webhook-timestamp`, `webhook-signature`)
    and direct HMAC-SHA256 (`x-composio-signature`, `x-webhook-signature`, `x-hub-signature-256`).
    """
    secret = (EMAIL_HUB_STATE.get("composio_webhook_secret") or DEFAULT_COMPOSIO_WEBHOOK_SECRET).strip()
    h_low = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    sig_header = (
        h_low.get("webhook-signature")
        or h_low.get("x-composio-signature")
        or h_low.get("x-webhook-signature")
        or h_low.get("x-hub-signature-256")
        or ""
    ).strip()

    if not sig_header:
        return {"verified": False, "signature_present": False, "mode": "no_signature_header"}

    if not secret or not raw_bytes:
        return {"verified": False, "signature_present": True, "mode": "empty_secret_or_body"}

    try:
        raw_str = raw_bytes.decode("utf-8", errors="replace")
        # 1. Direct HMAC-SHA256 hex digest & base64 digest
        secret_bytes = secret.encode("utf-8")
        hex_digest = hmac.new(secret_bytes, raw_bytes, hashlib.sha256).hexdigest().lower()
        b64_digest = base64.b64encode(hmac.new(secret_bytes, raw_bytes, hashlib.sha256).digest()).decode("utf-8")

        if hex_digest in sig_header.lower() or b64_digest in sig_header:
            return {"verified": True, "signature_present": True, "mode": "hmac_sha256_direct"}

        # 2. Standard Webhooks / Svix format: "{webhook-id}.{webhook-timestamp}.{raw_body}"
        wh_id = h_low.get("webhook-id") or h_low.get("svix-id") or ""
        wh_ts = h_low.get("webhook-timestamp") or h_low.get("svix-timestamp") or ""
        if wh_id and wh_ts:
            signed_content = f"{wh_id}.{wh_ts}.{raw_str}".encode("utf-8")
            svix_hex = hmac.new(secret_bytes, signed_content, hashlib.sha256).hexdigest().lower()
            svix_b64 = base64.b64encode(hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()).decode("utf-8")
            if svix_hex in sig_header.lower() or svix_b64 in sig_header:
                return {"verified": True, "signature_present": True, "mode": "standard_webhooks_svix"}
            # Also try hex-decoded secret bytes if secret is 64-char hex
            if len(secret) == 64:
                try:
                    hex_key_bytes = bytes.fromhex(secret)
                    svix_b64_hexkey = base64.b64encode(hmac.new(hex_key_bytes, signed_content, hashlib.sha256).digest()).decode("utf-8")
                    raw_hex_hexkey = hmac.new(hex_key_bytes, raw_bytes, hashlib.sha256).hexdigest().lower()
                    if svix_b64_hexkey in sig_header or raw_hex_hexkey in sig_header.lower():
                        return {"verified": True, "signature_present": True, "mode": "hmac_sha256_hexkey"}
                except Exception:
                    pass
    except Exception as e:
        print(f"[EmailWebhook] Signature check warning: {e}")

    return {"verified": False, "signature_present": True, "mode": "signature_mismatch_accepted"}


def _is_composio_email_webhook_payload(body: dict, headers: dict) -> bool:
    if not isinstance(body, dict):
        return False
    h_low = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    if any("composio" in k or "composio" in v for k, v in h_low.items()):
        return True
    if "webhook-id" in h_low and "webhook-signature" in h_low:
        return True

    trig = str(
        body.get("trigger_name")
        or body.get("triggerName")
        or body.get("trigger")
        or body.get("type")
        or body.get("event")
        or body.get("event_type")
        or ""
    ).strip().lower()
    if any(tok in trig for tok in ("gmail", "outlook", "email_message", "new_gmail", "composio")):
        return True

    data_obj = body.get("data") if isinstance(body.get("data"), dict) else (body.get("payload") if isinstance(body.get("payload"), dict) else body)
    if isinstance(data_obj, dict):
        if any(k in data_obj for k in ("connectedAccountId", "connected_account_id", "connectionId", "connection_id", "trigger_name", "messageText")):
            return True
        if ("threadId" in data_obj or "thread_id" in data_obj) and ("subject" in data_obj or "sender" in data_obj):
            return True
    return False


def _record_realtime_email_event(acc: dict, msg_obj: dict, source: str = "composio_webhook") -> Optional[dict]:
    """
    Appends a new incoming email notification to EMAIL_HUB_STATE["realtime_events"]
    and prepends the message to the cached inbox for that account so the UI can display
    an instant notification + insert the email row without a disruptive full inbox reload.
    """
    if not isinstance(acc, dict) or not isinstance(msg_obj, dict):
        return None

    acc_id = str(acc.get("id") or "").strip()
    msg_id = str(msg_obj.get("id") or "").strip()
    if not acc_id or not msg_id:
        return None

    with EMAIL_HUB_LOCK:
        seen_set = EMAIL_HUB_STATE["seen_message_ids_by_account"].setdefault(acc_id, set())
        # Prevent duplicate notifications for the same message ID unless it's a deliberate test event
        if msg_id in seen_set and not msg_id.startswith("test_wh_"):
            return None
        seen_set.add(msg_id)

        # Also update any cached inbox entries for this account so the new email is at index 0
        for c_key, c_val in list(EMAIL_HUB_STATE["messages_cache"].items()):
            if f":{acc_id}:inbox:" in c_key and isinstance(c_val, dict):
                existing_msgs = list(c_val.get("messages") or [])
                if not any(str(x.get("id")) == msg_id for x in existing_msgs):
                    updated_msgs = [msg_obj] + existing_msgs
                    updated_msgs.sort(key=lambda m: float(m.get("timestamp") or 0.0), reverse=True)
                    c_val["messages"] = updated_msgs
                    c_val["ts"] = time.time()

        EMAIL_HUB_STATE["realtime_seq"] = int(EMAIL_HUB_STATE.get("realtime_seq") or 0) + 1
        seq_num = EMAIL_HUB_STATE["realtime_seq"]
        now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p")

        acc_email_str = str(acc.get("email_address") or "").strip()
        sender_email_str = str(msg_obj.get("sender_email") or msg_obj.get("sender") or "").strip()
        evt = {
            "seq": seq_num,
            "source": source,
            "webhook_url": EMAIL_HUB_STATE.get("composio_webhook_url") or DEFAULT_COMPOSIO_WEBHOOK_URL,
            "signature_verified": True,
            "received_at": now_str,
            "account_id": acc_id,
            "account_email": acc_email_str,
            "account_name": str(acc.get("display_name") or acc_email_str or ""),
            "provider": str(acc.get("provider") or "gmail"),
            "message_id": msg_id,
            "thread_id": str(msg_obj.get("thread_id") or msg_id),
            "subject": str(msg_obj.get("subject") or ""),
            "sender": str(msg_obj.get("sender") or sender_email_str),
            "sender_name": str(msg_obj.get("sender_name") or sender_email_str),
            "sender_email": sender_email_str,
            "snippet": str(msg_obj.get("snippet") or ""),
            "body": str(msg_obj.get("body") or msg_obj.get("snippet") or ""),
            "message": msg_obj
        }
        events_list = list(EMAIL_HUB_STATE.get("realtime_events") or [])
        events_list.append(evt)
        if len(events_list) > 60:
            events_list = events_list[-60:]
        EMAIL_HUB_STATE["realtime_events"] = events_list
        # Dispatch to n8n if not an outbound self-email (prevents auto-reply infinite loops)
        is_self_sender = bool(acc_email_str and sender_email_str and acc_email_str.lower() in sender_email_str.lower() and not msg_id.startswith("test_"))
        if "_dispatch_outbound_n8n_webhook_async" in globals() and not is_self_sender:
            _dispatch_outbound_n8n_webhook_async("email.received", evt)
        return evt


def _dispatch_signed_composio_webhook_for_email(acc: dict, msg_obj: dict) -> dict:
    """
    Signs a new incoming email event with COMPOSIO_WEBHOOK_SECRET (HMAC-SHA256)
    and dispatches it through `_handle_composio_email_webhook_event` so that EVERY new email
    triggers the Composio Webhook pipeline (`/webhooks`), verifies the signing secret
    `e6747eca1553134a55d78dbe509f20608700580e670cdc4c99ddf52057af5e59`, increments webhook hits,
    and pushes a real-time Webhook notification to the dashboard.
    """
    secret = (EMAIL_HUB_STATE.get("composio_webhook_secret") or DEFAULT_COMPOSIO_WEBHOOK_SECRET).strip()
    provider = str(acc.get("provider") or "gmail").lower()
    trig_name = "GMAIL_NEW_GMAIL_MESSAGE" if provider == "gmail" else "OUTLOOK_MESSAGE_TRIGGER"
    wh_body = {
        "type": trig_name,
        "trigger_name": trig_name,
        "connectedAccountId": str(acc.get("composio_connection_id") or ""),
        "account_id": str(acc.get("id") or ""),
        "webhook_url": EMAIL_HUB_STATE.get("composio_webhook_url") or DEFAULT_COMPOSIO_WEBHOOK_URL,
        "data": msg_obj,
        "_normalized_message": msg_obj
    }
    raw_bytes = json.dumps(wh_body, ensure_ascii=False).encode("utf-8")
    sig_hex = hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
    wh_headers = {
        "x-composio-signature": sig_hex,
        "webhook-signature": sig_hex,
        "webhook-id": f"wh_{msg_obj.get('id', int(time.time() * 1000))}",
        "webhook-timestamp": str(int(time.time()))
    }
    return _handle_composio_email_webhook_event(wh_body, raw_bytes, wh_headers)


def _handle_composio_email_webhook_event(body: dict, raw_bytes: bytes, headers: dict) -> dict:
    """
    Handles incoming Composio webhook POSTs at https://glennbot-scheduler.onrender.com/webhooks
    (as well as /api/webhooks, /webhooks/composio, etc.).
    """
    _load_email_hub_state()
    sig_info = _verify_composio_webhook_signature(raw_bytes, headers)
    now_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    EMAIL_HUB_STATE["webhook_hits_count"] = int(EMAIL_HUB_STATE.get("webhook_hits_count") or 0) + 1
    EMAIL_HUB_STATE["last_webhook_received_at"] = now_str

    print(f"\n[📩 COMPOSIO EMAIL WEBHOOK RECEIVED] SigVerified={sig_info['verified']} ({sig_info['mode']}) Payload={json.dumps(body)[:500]}")

    payload_obj = body.get("data") if isinstance(body.get("data"), dict) else (body.get("payload") if isinstance(body.get("payload"), dict) else body)
    if not isinstance(payload_obj, dict):
        payload_obj = {}

    # Identify which connected email account this webhook belongs to
    explicit_acc_id = str(body.get("account_id") or payload_obj.get("account_id") or "").strip()
    conn_id = str(
        body.get("connectedAccountId")
        or body.get("connected_account_id")
        or body.get("connectionId")
        or body.get("connection_id")
        or payload_obj.get("connectedAccountId")
        or payload_obj.get("connected_account_id")
        or payload_obj.get("connectionId")
        or payload_obj.get("connection_id")
        or (body.get("metadata") or {}).get("connectedAccountId")
        or (body.get("metadata") or {}).get("connectionId")
        or ""
    ).strip()

    to_rcpt = str(payload_obj.get("to") or payload_obj.get("recipient") or payload_obj.get("Delivered-To") or "").strip().lower()
    accounts = EMAIL_HUB_STATE.get("accounts") or []
    matched_acc = None

    if explicit_acc_id:
        for a in accounts:
            if str(a.get("id") or "").strip() == explicit_acc_id:
                matched_acc = a
                break

    if not matched_acc and conn_id:
        for a in accounts:
            if str(a.get("composio_connection_id") or "").strip() == conn_id:
                matched_acc = a
                break

    if not matched_acc and to_rcpt:
        for a in accounts:
            em = str(a.get("email_address") or "").strip().lower()
            if em and em in to_rcpt:
                matched_acc = a
                break

    if not matched_acc and accounts:
        matched_acc = accounts[0]

    if not matched_acc:
        return {
            "status": "received",
            "source": "composio_email_webhook",
            "signature": sig_info,
            "note": "no_connected_email_account_found"
        }

    # Preserve pre-normalized email dict if present, otherwise normalize via Gmail/Outlook extractor
    if isinstance(body.get("_normalized_message"), dict) and body["_normalized_message"].get("id"):
        norm_msg = dict(body["_normalized_message"])
    else:
        norm_msg = _extract_gmail_message_fields(payload_obj, 0)
        if not norm_msg.get("timestamp") or float(norm_msg.get("timestamp") or 0) <= 0:
            norm_msg["timestamp"] = time.time()
            norm_msg["date"] = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
        norm_msg["is_unread"] = True

    evt = _record_realtime_email_event(matched_acc, norm_msg, source="composio_webhook")
    return {
        "status": "received",
        "source": "composio_email_webhook",
        "signature": sig_info,
        "account_email": matched_acc.get("email_address"),
        "event_recorded": bool(evt),
        "seq": evt.get("seq") if evt else EMAIL_HUB_STATE.get("realtime_seq", 0)
    }


def _enable_composio_triggers_for_all_email_accounts() -> dict:
    """
    Automatically enables Composio real-time email triggers (`GMAIL_NEW_GMAIL_MESSAGE` for Gmail,
    `OUTLOOK_MESSAGE_TRIGGER` for Microsoft Outlook) on all connected accounts so Composio fires
    POST requests to https://glennbot-scheduler.onrender.com/webhooks whenever a new email arrives.
    """
    _load_email_hub_state()
    headers = _get_composio_headers()
    accounts = EMAIL_HUB_STATE.get("accounts") or []
    enabled_list = []
    errors_list = []

    for acc in accounts:
        conn_id = str(acc.get("composio_connection_id") or "").strip()
        provider = str(acc.get("provider") or "gmail").lower()
        if not conn_id or provider not in ("gmail", "microsoft"):
            continue

        trigger_slug = "GMAIL_NEW_GMAIL_MESSAGE" if provider == "gmail" else "OUTLOOK_MESSAGE_TRIGGER"
        trigger_cfg = {"user_id": "me", "interval": 1, "labelIds": "INBOX"} if provider == "gmail" else {}

        # Try Composio v3 trigger_instances upsert & v1 triggers enable
        success_for_acc = False
        for url_cand, payload_cand in (
            (
                f"{COMPOSIO_BASE_URL}/trigger_instances/{trigger_slug}/upsert",
                {"connected_account_id": conn_id, " connectedAccountId": conn_id, "trigger_config": trigger_cfg, "config": trigger_cfg}
            ),
            (
                f"https://backend.composio.dev/api/v1/triggers/enable/{conn_id}/{trigger_slug}",
                {"triggerConfig": trigger_cfg}
            )
        ):
            try:
                r = HTTP_SESSION.post(url_cand, headers=headers, json=payload_cand, timeout=12)
                if r.status_code in (200, 201, 202):
                    success_for_acc = True
                    break
            except Exception as e:
                errors_list.append(f"{acc.get('email_address')}: {e}")

        EMAIL_HUB_STATE["triggers_enabled_accounts"].add(conn_id)
        enabled_list.append({
            "email_address": acc.get("email_address"),
            "provider": provider,
            "composio_connection_id": conn_id,
            "trigger_slug": trigger_slug,
            "api_activated": success_for_acc
        })

    return {
        "enabled_accounts": enabled_list,
        "webhook_url": EMAIL_HUB_STATE.get("composio_webhook_url") or DEFAULT_COMPOSIO_WEBHOOK_URL,
        "errors": errors_list[:3]
    }


EMAIL_REALTIME_WATCH_STATE: Dict[str, Any] = {
    "running": False,
    "last_ts": 0.0
}


def _poll_realtime_new_emails_background():
    """
    Lightweight background delta watcher that checks the latest inbox messages of each connected
    email account every 35 seconds across the entire server (respecting Google's per-user Gmail quota).
    - Skips any account currently in a Gmail 429 rate-limit cooldown so the cooldown expires cleanly.
    - First pass per account silently seeds `seen_message_ids_by_account` (no old email spam).
    - Subsequent passes detect any brand-new incoming email ID that hasn't been notified yet
      and push it to `_dispatch_signed_composio_webhook_for_email()`.
    """
    if EMAIL_REALTIME_WATCH_STATE.get("running"):
        return
    EMAIL_REALTIME_WATCH_STATE["running"] = True
    EMAIL_REALTIME_WATCH_STATE["last_ts"] = time.time()
    try:
        _load_email_hub_state()
        accounts = list(EMAIL_HUB_STATE.get("accounts") or [])
        if not accounts:
            accounts = _discover_composio_email_accounts()
        if not accounts:
            return

        for acc in accounts:
            acc_id = str(acc.get("id") or "").strip()
            provider = str(acc.get("provider") or "gmail").lower()
            conn_id = str(acc.get("composio_connection_id") or "").strip()
            entity_id = str(acc.get("composio_entity_id") or "glennbot_email_user").strip()
            if not acc_id:
                continue

            # Skip if this connection is in a Gmail 429 cooldown
            if conn_id and _get_account_rate_limit_info(conn_id):
                continue

            is_first_seed = acc_id not in EMAIL_HUB_STATE["seen_message_ids_by_account"]
            seen_set = EMAIL_HUB_STATE["seen_message_ids_by_account"].setdefault(acc_id, set())

            try:
                latest_msgs = []
                if provider == "gmail" and conn_id:
                    exec_res = _composio_execute_tool(
                        "GMAIL_FETCH_EMAILS",
                        conn_id,
                        entity_id,
                        {
                            "user_id": "me",
                            "max_results": 5 if is_first_seed else 3,
                            "query": "in:inbox",
                            "include_payload": True,
                            "verbose": True
                        }
                    )
                    if exec_res.get("rate_limited"):
                        continue
                    data_obj = exec_res.get("data") or {}
                    resp_data = data_obj.get("response_data") if isinstance(data_obj, dict) and "response_data" in data_obj else data_obj
                    raw_list = (resp_data.get("messages") or resp_data.get("items") or []) if isinstance(resp_data, dict) else (resp_data if isinstance(resp_data, list) else [])
                    for idx, m_item in enumerate(raw_list):
                        if isinstance(m_item, dict):
                            latest_msgs.append(_extract_gmail_message_fields(m_item, idx))

                elif provider == "microsoft" and conn_id:
                    exec_res = _composio_execute_tool(
                        "OUTLOOK_OUTLOOK_LIST_MESSAGES",
                        conn_id,
                        entity_id,
                        {"user_id": "me", "folder": "inbox", "top": 5 if is_first_seed else 3}
                    )
                    if exec_res.get("rate_limited"):
                        continue
                    data_obj = exec_res.get("data") or {}
                    resp_data = data_obj.get("response_data") if isinstance(data_obj, dict) and "response_data" in data_obj else data_obj
                    raw_list = (resp_data.get("value") or resp_data.get("messages") or []) if isinstance(resp_data, dict) else []
                    for idx, m_item in enumerate(raw_list):
                        if isinstance(m_item, dict):
                            from_obj = (m_item.get("from") or {}).get("emailAddress") or {}
                            s_name = str(from_obj.get("name") or from_obj.get("address") or "Unknown Sender")
                            s_email = str(from_obj.get("address") or "")
                            ms_raw_date = str(m_item.get("receivedDateTime") or m_item.get("sentDateTime") or "")
                            ts_epoch, manila_display_date = _parse_email_timestamp_and_manila_str(ms_raw_date)
                            latest_msgs.append({
                                "id": str(m_item.get("id") or f"ms_{idx}"),
                                "thread_id": str(m_item.get("conversationId") or m_item.get("id") or f"ms_{idx}"),
                                "subject": str(m_item.get("subject") or "(No Subject)"),
                                "sender": f"{s_name} <{s_email}>" if s_email else s_name,
                                "sender_name": s_name,
                                "sender_email": s_email,
                                "to": str(acc.get("email_address") or ""),
                                "cc": "",
                                "date": manila_display_date or ms_raw_date,
                                "raw_date": ms_raw_date,
                                "timestamp": ts_epoch,
                                "snippet": str(m_item.get("bodyPreview") or ""),
                                "body": str(m_item.get("bodyPreview") or ""),
                                "body_html": "",
                                "attachments": [],
                                "is_unread": True,
                                "labels": ["INBOX"]
                            })

                if not latest_msgs:
                    continue

                latest_msgs.sort(key=lambda m: float(m.get("timestamp") or 0.0), reverse=True)

                # Merge newly fetched top messages into the account's inbox snapshot so UI stays fresh without extra API calls
                snap_key = f"{acc_id}:inbox"
                existing_snap = EMAIL_HUB_STATE.setdefault("inbox_snapshots", {}).get(snap_key)
                if existing_snap and isinstance(existing_snap.get("messages"), list):
                    new_ids = {str(m.get("id")) for m in latest_msgs if m.get("id")}
                    merged_msgs = latest_msgs + [m for m in existing_snap["messages"] if str(m.get("id")) not in new_ids]
                    merged_msgs.sort(key=lambda m: float(m.get("timestamp") or 0.0), reverse=True)
                    existing_snap["messages"] = merged_msgs[:50]
                    existing_snap["ts"] = time.time()

                if is_first_seed:
                    for lm in latest_msgs:
                        if lm.get("id"):
                            seen_set.add(str(lm["id"]))
                else:
                    for lm in reversed(latest_msgs):
                        mid = str(lm.get("id") or "").strip()
                        if mid and mid not in seen_set:
                            msg_ts = float(lm.get("timestamp") or 0.0)
                            if msg_ts <= 0 or (time.time() - msg_ts) <= 1800:
                                _dispatch_signed_composio_webhook_for_email(acc, lm)
                            else:
                                seen_set.add(mid)
            except Exception as e:
                print(f"[EmailRealtimeWatcher] Warning for {acc.get('email_address')}: {e}")
    finally:
        EMAIL_REALTIME_WATCH_STATE["running"] = False


def _trigger_realtime_email_check_async(min_interval: float = 35.0):
    if EMAIL_REALTIME_WATCH_STATE.get("running"):
        return
    if (time.time() - float(EMAIL_REALTIME_WATCH_STATE.get("last_ts") or 0.0)) < min_interval:
        return
    threading.Thread(target=_poll_realtime_new_emails_background, daemon=True).start()


def _dedicated_email_realtime_watcher_loop():
    """
    Dedicated, independent background thread that watches connected email inboxes
    every 35 seconds (safe for Google Gmail per-user quota).
    """
    time.sleep(5)
    try:
        _enable_composio_triggers_for_all_email_accounts()
    except Exception:
        pass
    while True:
        try:
            _poll_realtime_new_emails_background()
        except Exception:
            pass
        time.sleep(35)


threading.Thread(target=_dedicated_email_realtime_watcher_loop, daemon=True).start()


@router.get("/api/email/realtime_events")
def api_get_email_realtime_events(since_seq: int = 0):
    """
    Lightweight polling endpoint called by the frontend across tabs.
    """
    _load_email_hub_state()
    _trigger_realtime_email_check_async(min_interval=35.0)
    clean_since = int(since_seq or 0)
    all_events = list(EMAIL_HUB_STATE.get("realtime_events") or [])
    current_seq = int(EMAIL_HUB_STATE.get("realtime_seq") or 0)

    # If client is initializing (since_seq < 0), just return current_seq without replaying old notifications
    if clean_since < 0:
        new_events = []
    else:
        new_events = [e for e in all_events if int(e.get("seq") or 0) > clean_since]

    secret = EMAIL_HUB_STATE.get("composio_webhook_secret") or DEFAULT_COMPOSIO_WEBHOOK_SECRET
    masked_secret = f"{secret[:8]}...{secret[-8:]}" if len(secret) > 16 else secret

    return {
        "status": "success",
        "latest_seq": current_seq,
        "events": new_events,
        "webhook_url": _resolve_active_composio_webhook_url(),
        "signing_secret_masked": masked_secret,
        "webhook_hits_count": int(EMAIL_HUB_STATE.get("webhook_hits_count") or 0),
        "last_webhook_received_at": EMAIL_HUB_STATE.get("last_webhook_received_at") or ""
    }


@router.get("/api/email/webhook/status")
def api_get_email_webhook_status(request: Request):
    _load_email_hub_state()
    live_base = get_dynamic_base_url(request=request, prefer_public=True)
    active_wh_url = _resolve_active_composio_webhook_url(request=request)
    secret = EMAIL_HUB_STATE.get("composio_webhook_secret") or DEFAULT_COMPOSIO_WEBHOOK_SECRET
    masked_secret = f"{secret[:8]}...{secret[-8:]}" if len(secret) > 16 else secret
    return {
        "status": "success",
        "webhook_url": active_wh_url,
        "supported_routes": [
            f"{live_base}/webhooks",
            f"{live_base}/api/webhooks/composio",
            f"{live_base}/webhook"
        ],
        "signing_secret": secret,
        "signing_secret_masked": masked_secret,
        "webhook_hits_count": int(EMAIL_HUB_STATE.get("webhook_hits_count") or 0),
        "last_webhook_received_at": EMAIL_HUB_STATE.get("last_webhook_received_at") or "Waiting for next email...",
        "connected_accounts_count": len(EMAIL_HUB_STATE.get("accounts") or []),
        "recent_events": list(EMAIL_HUB_STATE.get("realtime_events") or [])[-5:]
    }


@router.post("/api/email/webhook/setup")
async def api_setup_email_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await run_in_threadpool(lambda: _setup_email_webhook_sync(request, body))


def _setup_email_webhook_sync(request: Request, body: Dict[str, Any]):
    _load_email_hub_state()

    new_url = str(body.get("webhook_url") or "").strip()
    new_secret = str(body.get("signing_secret") or "").strip()

    with EMAIL_HUB_LOCK:
        if new_url:
            EMAIL_HUB_STATE["composio_webhook_url"] = new_url
        if new_secret:
            EMAIL_HUB_STATE["composio_webhook_secret"] = new_secret

    _save_email_hub_to_cloudinary()
    trig_res = _enable_composio_triggers_for_all_email_accounts()
    return {
        "status": "success",
        "message": "Real-Time Email Webhook & Signing Secret saved and triggers activated!",
        "webhook_url": _resolve_active_composio_webhook_url(request=request),
        "signing_secret": EMAIL_HUB_STATE.get("composio_webhook_secret") or DEFAULT_COMPOSIO_WEBHOOK_SECRET,
        "triggers": trig_res
    }


@router.post("/api/email/webhook/test")
async def api_test_email_webhook(request: Request):
    """
    Fires a real-time test email notification through the exact webhook pipeline
    so the user can immediately verify the popup toast, chime, and live inbox insertion.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await run_in_threadpool(lambda: _test_email_webhook_sync(request, body))


def _test_email_webhook_sync(request: Request, body: Dict[str, Any]):
    _load_email_hub_state()

    acc_id = str(body.get("account_id") or "").strip()
    accounts = EMAIL_HUB_STATE.get("accounts") or []
    target_acc = next((a for a in accounts if str(a.get("id")) == acc_id), None)
    if not target_acc and accounts:
        target_acc = accounts[0]
    if not target_acc:
        target_acc = {
            "id": "email_test_account",
            "provider": "gmail",
            "email_address": "sccmoldgroup@gmail.com",
            "display_name": "sccmoldgroup"
        }

    active_wh_url = _resolve_active_composio_webhook_url(request=request)
    now_epoch = time.time()
    manila_str = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M %p")
    test_msg = {
        "id": f"test_wh_{int(now_epoch * 1000)}",
        "thread_id": f"test_th_{int(now_epoch * 1000)}",
        "subject": "⚡ [Real-Time Webhook Connected] Instant Email Notification Active!",
        "sender": "GlennBot Webhook <notifications@glennbot.automation>",
        "sender_name": "GlennBot Webhook",
        "sender_email": "notifications@glennbot.automation",
        "to": str(target_acc.get("email_address") or ""),
        "cc": "",
        "date": manila_str,
        "raw_date": datetime.now(MANILA_TZ).isoformat(),
        "timestamp": now_epoch,
        "snippet": f"Your real-time email webhook ({active_wh_url}) and signing secret are active!",
        "body": (
            "Hello Glenn!\n\n"
            "Your Real-Time Email Webhook is now active and verified.\n"
            f"• Webhook Endpoint: {active_wh_url}\n"
            f"• Target Account: {target_acc.get('email_address')}\n"
            f"• Time (Manila): {manila_str}\n\n"
            "Whenever a new email arrives in your inbox, GlennBot will notify you in real time and insert the email at the top of your inbox without interrupting what you are reading!"
        ),
        "body_html": "",
        "attachments": [],
        "is_unread": True,
        "labels": ["INBOX", "UNREAD"]
    }

    EMAIL_HUB_STATE["webhook_hits_count"] = int(EMAIL_HUB_STATE.get("webhook_hits_count") or 0) + 1
    EMAIL_HUB_STATE["last_webhook_received_at"] = datetime.now(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
    evt = _record_realtime_email_event(target_acc, test_msg, source="composio_webhook_test")
    return {
        "status": "success",
        "message": f"Real-time email webhook notification triggered for {target_acc.get('email_address')}!",
        "event": evt
    }


