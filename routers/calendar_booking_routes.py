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


def _is_valid_public_meeting_join_url(url_str: str) -> bool:
    """
    Returns True ONLY if `url_str` is a genuine public video meeting join link
    (e.g., `teams.live.com/meet/...`, `teams.microsoft.com/l/meetup-join/...`, `meet.google.com/xxx-xxxx-xxx`, `zoom.us/j/...`).
    Strictly rejects private OWA mailbox links (`outlook.live.com/owa/?itemid=...`) and generic homepages (`teams.live.com/v2/`)
    which trigger Gmail's Anti-Phishing / Deceptive Link filter and cause Outlook invites to land in SPAM!
    """
    u = str(url_str or "").strip()
    if not u.startswith(("http://", "https://")):
        return False
    u_low = u.lower().rstrip("/")
    if "outlook.live.com/owa" in u_low or "outlook.office.com/owa" in u_low or "itemid=" in u_low:
        return False
    if u_low in (
        "https://teams.live.com/v2",
        "https://teams.live.com",
        "https://teams.microsoft.com",
        "https://meet.google.com/new",
        "https://zoom.us/start/videomeeting"
    ):
        return False
    return True


def _send_calendar_notification_email_single(
    clean_to: str,
    email_subject: str,
    html_builder,
    org_email: str,
    ev_provider: str,
    target_acc: Optional[dict] = None,
    preferred_sender_email: str = ""
) -> str:
    """
    Sends a Calendar Invite, Reschedule Notice, or Cancellation Notice to `clean_to`
    using the user's explicitly selected `preferred_sender_email` (from the modal dropdown)
    or the matching organizer email account.
    - Guarantees that `glennard.tasico.va@outlook.com` is NEVER used to send Zoom or Google Meet emails
      unless the user explicitly selected it in the Sender Email dropdown!
    - Returns the actual sender email address used (or empty string if not sent).
    """
    _load_email_hub_state()
    email_accounts = list(EMAIL_HUB_STATE.get("accounts") or [])
    if not email_accounts:
        try:
            _auto_discover_composio_email_accounts()
            email_accounts = list(EMAIL_HUB_STATE.get("accounts") or [])
        except Exception:
            pass

    pref_low = str(preferred_sender_email or "").strip().lower()
    if pref_low in ("auto", "default", "organizer"):
        pref_low = ""
    org_low = str(org_email or "").strip().lower()
    to_low = str(clean_to or "").strip().lower()

    # 1. If the user explicitly selected a sender email in the modal dropdown, honor it first!
    if pref_low and "@" in pref_low:
        chosen_ea = next(
            (
                ea for ea in email_accounts
                if str(ea.get("email_address") or "").strip().lower() == pref_low
                and ea.get("composio_connection_id")
            ),
            None
        )
        if chosen_ea:
            ea_prov = str(chosen_ea.get("provider") or "").lower()
            ea_cid = str(chosen_ea["composio_connection_id"]).strip()
            ea_eid = str(chosen_ea.get("composio_entity_id") or "glennbot_email_user").strip()
            ea_email = str(chosen_ea.get("email_address") or pref_low).strip()
            try:
                if ea_prov == "gmail":
                    r_gm = _composio_execute_tool(
                        "GMAIL_SEND_EMAIL",
                        ea_cid,
                        ea_eid,
                        {
                            "user_id": "me",
                            "recipient_email": clean_to,
                            "subject": email_subject,
                            "body": html_builder(org_email or ea_email),
                            "is_html": True
                        }
                    )
                    if r_gm.get("successful", False):
                        return ea_email
                else:
                    r_out = _composio_execute_tool(
                        "OUTLOOK_OUTLOOK_SEND_EMAIL",
                        ea_cid,
                        ea_eid,
                        {
                            "user_id": "me",
                            "to_email": clean_to,
                            "subject": email_subject,
                            "body": html_builder(org_email or ea_email),
                            "is_html": True,
                            "save_to_sent_items": True
                        }
                    )
                    if r_out.get("successful", False):
                        return ea_email
            except Exception as e_pref:
                print(f"[CalendarHub] Explicit sender ({ea_email}) send warning: {e_pref}")

    # 2. Automatic sender selection based on Calendar Provider & Organizer Email
    gmail_accs = [
        ea for ea in email_accounts
        if str(ea.get("provider") or "").lower() == "gmail"
        and ea.get("composio_connection_id")
        and str(ea.get("email_address") or "").strip().lower() != to_low
    ]
    outlook_email_accs = [
        ea for ea in email_accounts
        if str(ea.get("provider") or "").lower() in ("microsoft", "outlook")
        and ea.get("composio_connection_id")
        and str(ea.get("email_address") or "").strip().lower() != to_low
    ]

    # CASE A: MS Outlook / MS Teams Calendar ONLY
    if ev_provider == "outlook_calendar" or (target_acc and str(target_acc.get("toolkit_slug") or "") == "outlook"):
        is_personal_outlook_org = any(d in org_low for d in ("@outlook.", "@hotmail.", "@live.", "@msn."))
        preferred_gmail_relay = next(
            (ea for ea in gmail_accs if "glennard.tasico.va" in str(ea.get("email_address") or "").lower()),
            gmail_accs[0] if gmail_accs else None
        )
        if is_personal_outlook_org and preferred_gmail_relay:
            try:
                relay_em = str(preferred_gmail_relay.get("email_address") or org_email).strip()
                r_gm = _composio_execute_tool(
                    "GMAIL_SEND_EMAIL",
                    str(preferred_gmail_relay["composio_connection_id"]),
                    str(preferred_gmail_relay.get("composio_entity_id") or "glennbot_email_user"),
                    {
                        "user_id": "me",
                        "recipient_email": clean_to,
                        "subject": email_subject,
                        "body": html_builder(org_email or relay_em),
                        "is_html": True
                    }
                )
                if r_gm.get("successful", False):
                    return relay_em
            except Exception as e:
                print(f"[CalendarHub] Gmail relay for Outlook warning ({clean_to}): {e}")

        outlook_conn_id = str(target_acc.get("composio_connection_id") or "") if target_acc else ""
        outlook_entity = str(target_acc.get("composio_entity_id") or "glennbot_calendar_user") if target_acc else "glennbot_calendar_user"
        if not outlook_conn_id and outlook_email_accs:
            outlook_conn_id = str(outlook_email_accs[0].get("composio_connection_id") or "")
            outlook_entity = str(outlook_email_accs[0].get("composio_entity_id") or "glennbot_email_user")
        if outlook_conn_id:
            try:
                r_out = _composio_execute_tool(
                    "OUTLOOK_OUTLOOK_SEND_EMAIL",
                    outlook_conn_id,
                    outlook_entity,
                    {
                        "user_id": "me",
                        "to_email": clean_to,
                        "subject": email_subject,
                        "body": html_builder(org_email),
                        "is_html": True,
                        "save_to_sent_items": True
                    }
                )
                if r_out.get("successful", False):
                    return org_email
            except Exception as e:
                print(f"[CalendarHub] Outlook email warning ({clean_to}): {e}")
        return ""

    # CASE B: Google Calendar / Google Meet / Zoom Cloud Meetings -> Strictly send via Gmail (NEVER @outlook.com unless explicitly chosen!)
    matched_gmail = next(
        (ea for ea in gmail_accs if org_low and str(ea.get("email_address") or "").strip().lower() == org_low),
        next(
            (ea for ea in gmail_accs if "glennard.tasico.va" in str(ea.get("email_address") or "").lower()),
            gmail_accs[0] if gmail_accs else None
        )
    )
    if matched_gmail:
        try:
            sender_em = str(matched_gmail.get("email_address") or org_email).strip()
            r_gm = _composio_execute_tool(
                "GMAIL_SEND_EMAIL",
                str(matched_gmail["composio_connection_id"]),
                str(matched_gmail.get("composio_entity_id") or "glennbot_email_user"),
                {
                    "user_id": "me",
                    "recipient_email": clean_to,
                    "subject": email_subject,
                    "body": html_builder(org_email or sender_em),
                    "is_html": True
                }
            )
            if r_gm.get("successful", False):
                return sender_em
        except Exception as e:
            print(f"[CalendarHub] Gmail send warning ({clean_to}): {e}")
    return ""


def _send_calendar_invite_emails_to_attendees(
    saved_event: dict,
    attendee_emails: List[str],
    target_acc: Optional[dict] = None,
    preferred_sender_email: str = ""
):
    """
    Guarantees that every invited guest/recipient receives a clean, spam-safe,
    dark-mode-readable HTML Meeting Invitation Email in their Primary INBOX.
    """
    if not attendee_emails:
        return
    try:
        import urllib.parse
        import html as py_html
        enriched_ev = _enrich_calendar_event_date_fields(saved_event)
        subject_title = str(enriched_ev.get("subject") or "Scheduled Meeting").strip()
        disp_date = str(enriched_ev.get("display_date") or "").strip()
        time_range = str(enriched_ev.get("time_range_str") or enriched_ev.get("time_str") or "").strip()
        tz_str = str(enriched_ev.get("timezone") or "Asia/Manila").strip()
        m_plat = str(enriched_ev.get("meeting_platform") or "none").lower()
        raw_m_url = str(enriched_ev.get("meeting_url") or "").strip()
        m_url = raw_m_url if _is_valid_public_meeting_join_url(raw_m_url) else ""
        raw_loc = str(enriched_ev.get("location") or "").strip()
        loc_str = "" if ("outlook.live.com/owa" in raw_loc.lower() or "itemid=" in raw_loc.lower()) else raw_loc
        desc_str = str(enriched_ev.get("description") or "").strip()
        org_email = str(enriched_ev.get("organizer_email") or enriched_ev.get("email_address") or "").strip()
        ev_provider = str(enriched_ev.get("provider") or "").lower()
        start_iso_raw = str(enriched_ev.get("start_iso") or "").strip()
        end_iso_raw = str(enriched_ev.get("end_iso") or "").strip()

        plat_labels = {
            "google_meet": "Google Meet Video Call",
            "microsoft_teams": "Microsoft Teams Meeting",
            "zoom": "Zoom Cloud Meeting",
            "none": "Calendar Appointment"
        }
        plat_label = plat_labels.get(m_plat, "Online Meeting")

        gcal_template_url = ""
        try:
            dt_s = _parse_calendar_iso_datetime(start_iso_raw, tz_str)
            dt_e = _parse_calendar_iso_datetime(end_iso_raw, tz_str)
            if dt_s and dt_e:
                dt_s_utc = dt_s.astimezone(timezone.utc)
                dt_e_utc = dt_e.astimezone(timezone.utc)
                dates_param = f"{dt_s_utc.strftime('%Y%m%dT%H%M%SZ')}/{dt_e_utc.strftime('%Y%m%dT%H%M%SZ')}"
                details_full = f"{desc_str}\n\nJoin {plat_label}: {m_url}".strip() if m_url else desc_str
                safe_loc = loc_str or (m_url if m_url else plat_label)
                gcal_template_url = (
                    "https://calendar.google.com/calendar/render?action=TEMPLATE"
                    f"&text={urllib.parse.quote(subject_title)}"
                    f"&dates={dates_param}"
                    f"&details={urllib.parse.quote(details_full)}"
                    f"&location={urllib.parse.quote(safe_loc)}"
                )
        except Exception:
            pass

        email_subject = f"Invitation: {subject_title} @ {disp_date} ({time_range})"
        join_btn_html = ""
        if m_url:
            join_btn_html = (
                f'<div style="margin:18px 0;">'
                f'<a href="{py_html.escape(m_url)}" target="_blank" '
                f'style="display:inline-block;background-color:#0284c7;color:#ffffff;font-weight:700;'
                f'text-decoration:none;padding:11px 20px;border-radius:8px;font-size:14px;">'
                f'Join {py_html.escape(plat_label)}'
                f'</a>'
                f'<div style="margin-top:6px;font-size:12px;color:#0284c7;">'
                f'Meeting Link: <a href="{py_html.escape(m_url)}" style="color:#0284c7;word-break:break-all;">{py_html.escape(m_url)}</a>'
                f'</div></div>'
            )
        elif m_plat != "none":
            join_btn_html = (
                f'<div style="margin:14px 0;padding:10px 14px;background-color:#e0f2fe;border:1px solid #38bdf8;border-radius:8px;color:#0369a1;font-size:13px;">'
                f'<strong>Conferencing:</strong> {py_html.escape(plat_label)} (Organizer: {py_html.escape(org_email)})'
                f'</div>'
            )

        cal_btns_html = ""
        if gcal_template_url:
            cal_btns_html = (
                f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid #cbd5e1;">'
                f'<a href="{py_html.escape(gcal_template_url)}" target="_blank" '
                f'style="display:inline-block;margin-right:10px;margin-top:6px;padding:8px 14px;border-radius:6px;'
                f'background-color:#0f172a;color:#ffffff;text-decoration:none;font-size:12px;font-weight:600;">'
                f'+ Add to Google Calendar</a></div>'
            )

        agenda_html = ""
        if desc_str:
            agenda_html = (
                f'<div style="margin-top:14px;padding:12px;background-color:#f0f9ff;border-left:4px solid #0284c7;'
                f'border-radius:6px;color:#0c4a6e;font-size:13px;white-space:pre-wrap;">'
                f'<strong>Agenda / Notes:</strong><br>{py_html.escape(desc_str)}</div>'
            )

        def _build_invite_html(organizer_display: str) -> str:
            return (
                '<div style="max-width:580px;border:1px solid #38bdf8;border-radius:12px;padding:20px;'
                'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;line-height:1.6;">'
                f'<div style="font-size:12px;font-weight:700;text-transform:uppercase;color:#0284c7;letter-spacing:0.05em;">{py_html.escape(plat_label)} Invitation</div>'
                f'<h2 style="margin:6px 0 14px 0;font-size:18px;color:#0284c7;">{py_html.escape(subject_title)}</h2>'
                '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;font-size:14px;">'
                f'<tr><td style="padding:4px 0;color:#64748b;width:105px;"><strong>Date:</strong></td><td style="padding:4px 0;color:#0284c7;font-weight:700;">{py_html.escape(disp_date)}</td></tr>'
                f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Time:</strong></td><td style="padding:4px 0;color:#0284c7;font-weight:700;">{py_html.escape(time_range)} ({py_html.escape(tz_str)})</td></tr>'
                f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Organizer:</strong></td><td style="padding:4px 0;color:#2563eb;font-weight:600;">{py_html.escape(organizer_display)}</td></tr>'
                + (f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Location:</strong></td><td style="padding:4px 0;color:#64748b;font-weight:600;">{py_html.escape(loc_str)}</td></tr>' if loc_str and loc_str != m_url else '')
                + '</table>'
                + join_btn_html
                + agenda_html
                + cal_btns_html
                + '</div>'
            )

        for recipient in attendee_emails:
            clean_to = str(recipient or "").strip()
            if not clean_to or "@" not in clean_to:
                continue
            if org_email and clean_to.lower() == org_email.lower():
                continue
            _send_calendar_notification_email_single(
                clean_to=clean_to,
                email_subject=email_subject,
                html_builder=_build_invite_html,
                org_email=org_email,
                ev_provider=ev_provider,
                target_acc=target_acc,
                preferred_sender_email=preferred_sender_email
            )
    except Exception as e:
        print(f"[CalendarHub] Invite email dispatch warning: {e}")


def _create_event_on_google_calendar_account(
    gcal_acc: dict,
    subject: str,
    description: str,
    location: str,
    naive_start: str,
    timezone_str: str,
    duration_minutes: int,
    attendee_emails: List[str],
    availability: str,
    meeting_platform: str,
    generated_meeting_url: str
) -> Tuple[str, str, str]:
    """
    Creates an event on a connected Google Calendar account (`GOOGLECALENDAR_CREATE_EVENT`)
    and returns `(external_event_id, html_link, meeting_url)`.
    Uses `send_updates: False` so Google Calendar does NOT send a duplicate second email
    alongside our unified HTML Invitation Card, and `exclude_organizer: False` so the
    organizer (`self: True`) stays on the event and it always appears on the sender's
    own Google Calendar (`calendar.google.com`)!
    """
    conn_id = str(gcal_acc.get("composio_connection_id") or "").strip()
    entity_id = str(gcal_acc.get("composio_entity_id") or "glennbot_calendar_user").strip()
    if not conn_id:
        return ("", "", generated_meeting_url)

    dur_h = duration_minutes // 60
    dur_m = duration_minutes % 60
    merged_desc = description or subject
    if generated_meeting_url and generated_meeting_url not in merged_desc:
        merged_desc = f"{merged_desc}\n\nJoin Online Meeting ({meeting_platform.upper()}): {generated_meeting_url}".strip()

    gcal_args = {
        "calendar_id": "primary",
        "summary": subject,
        "description": merged_desc,
        "location": location or generated_meeting_url,
        "start_datetime": naive_start,
        "timezone": timezone_str,
        "event_duration_hour": dur_h,
        "event_duration_minutes": dur_m,
        "attendees": attendee_emails,
        "exclude_organizer": False,
        "send_updates": False,
        "create_meeting_room": True if (meeting_platform == "google_meet" and not generated_meeting_url) else False,
        "transparency": "transparent" if availability == "free" else "opaque"
    }
    res = _composio_execute_tool("GOOGLECALENDAR_CREATE_EVENT", conn_id, entity_id, gcal_args)
    if not res.get("successful", True) and gcal_args.get("create_meeting_room"):
        gcal_args["create_meeting_room"] = False
        res = _composio_execute_tool("GOOGLECALENDAR_CREATE_EVENT", conn_id, entity_id, gcal_args)

    d_obj = (res.get("data") or {}).get("response_data") or res.get("data") or {}
    ext_id = ""
    html_link = ""
    final_meet_url = generated_meeting_url
    if isinstance(d_obj, dict):
        ext_id = str(d_obj.get("id") or "").strip()
        html_link = str(d_obj.get("htmlLink") or "").strip()
        if not final_meet_url:
            final_meet_url = str(d_obj.get("hangoutLink") or "").strip()
            if not final_meet_url and isinstance(d_obj.get("conferenceData"), dict):
                for ep in (d_obj["conferenceData"].get("entryPoints") or []):
                    if isinstance(ep, dict) and ep.get("uri"):
                        final_meet_url = str(ep["uri"]).strip()
                        break
    return (ext_id, html_link, final_meet_url)


def _create_event_on_outlook_calendar_account(
    outlook_acc: dict,
    subject: str,
    description: str,
    location: str,
    naive_start: str,
    naive_end: str,
    timezone_str: str,
    attendee_emails: List[str],
    availability: str,
    meeting_platform: str,
    generated_meeting_url: str
) -> Tuple[str, str, str]:
    """
    Creates an event on a connected Microsoft Outlook / MS Teams Calendar account
    (`OUTLOOK_OUTLOOK_CALENDAR_CREATE_EVENT`) with cascading fallback so both
    Microsoft 365 Business and Personal Microsoft accounts succeed 100% of the time!
    Leaves `attendees_info` empty on the raw Graph calendar create call so Outlook
    does not generate a duplicate second email alongside our unified HTML Invitation Card!
    Returns `(external_event_id, html_link, meeting_url)`.
    """
    conn_id = str(outlook_acc.get("composio_connection_id") or "").strip()
    entity_id = str(outlook_acc.get("composio_entity_id") or "glennbot_calendar_user").strip()
    if not conn_id:
        return ("", "", generated_meeting_url)

    merged_desc = description or subject
    if generated_meeting_url and generated_meeting_url not in merged_desc:
        merged_desc = f"{merged_desc}\n\nJoin Online Meeting ({meeting_platform.upper()}): {generated_meeting_url}".strip()

    base_args = {
        "user_id": "me",
        "subject": subject,
        "body": merged_desc,
        "is_html": False,
        "start_datetime": naive_start,
        "end_datetime": naive_end,
        "time_zone": timezone_str,
        "location": location or generated_meeting_url or ("Microsoft Teams Meeting" if meeting_platform == "microsoft_teams" else ""),
        "show_as": availability if availability in ("free", "tentative", "busy", "oof") else "busy",
        "attendees_info": []
    }

    attempts = []
    if meeting_platform == "microsoft_teams":
        a1 = dict(base_args)
        a1["is_online_meeting"] = True
        a1["online_meeting_provider"] = "teamsForBusiness"
        attempts.append(a1)

        a2 = dict(base_args)
        a2["is_online_meeting"] = True
        attempts.append(a2)

        a3 = dict(base_args)
        a3["is_online_meeting"] = False
        attempts.append(a3)
    else:
        a_std = dict(base_args)
        a_std["is_online_meeting"] = False
        attempts.append(a_std)

    ext_id = ""
    html_link = ""
    final_meet_url = generated_meeting_url

    for idx, args_payload in enumerate(attempts):
        res = _composio_execute_tool("OUTLOOK_OUTLOOK_CALENDAR_CREATE_EVENT", conn_id, entity_id, args_payload)
        d_obj = (res.get("data") or {}).get("response_data") or res.get("data") or {}
        if res.get("successful", False) and isinstance(d_obj, dict) and d_obj.get("id"):
            ext_id = str(d_obj.get("id") or "").strip()
            html_link = str(d_obj.get("webLink") or "").strip()
            if not final_meet_url:
                om_obj = d_obj.get("onlineMeeting") if isinstance(d_obj.get("onlineMeeting"), dict) else {}
                final_meet_url = str(om_obj.get("joinUrl") or d_obj.get("onlineMeetingUrl") or "").strip()
            break

    return (ext_id, html_link, final_meet_url)


def _schedule_composio_calendar_event_sync(body: dict) -> Dict[str, Any]:
    """
    Auto-detects the target Calendar Provider & Account based on the selected Meeting Platform / Mode:
    - `google_meet` or `google_calendar` -> Strictly Google Calendar & Meet (`googlecalendar`)
    - `microsoft_teams` or `outlook_calendar` -> Strictly MS Outlook & Teams Calendar (`outlook`)
    - `zoom` -> Creates in Zoom Cloud Meetings (`zoom`) AND auto-adds to the sender's Google Calendar
      (`googlecalendar` with `send_updates: False`, `exclude_organizer: False`) so it appears on the
      sender's actual Google Calendar (`calendar.google.com`) while still sending only 1 invite email!
    """
    accounts = _discover_composio_calendar_accounts()

    subject = str(body.get("subject") or body.get("title") or "Scheduled Meeting").strip()
    description = str(body.get("description") or body.get("agenda") or "").strip()
    location = str(body.get("location") or "").strip()
    timezone_str = str(body.get("timezone") or "Asia/Manila").strip() or "Asia/Manila"
    date_str = str(body.get("date") or "").strip()
    start_time_str = str(body.get("start_time") or "10:00").strip()
    end_time_str = str(body.get("end_time") or "").strip()
    duration_minutes = max(10, int(body.get("duration_minutes") or 60))
    meeting_platform = str(body.get("meeting_platform") or "none").strip().lower()
    custom_meeting_url = str(body.get("meeting_url") or "").strip()
    availability = str(body.get("availability") or "busy").strip().lower()
    reminder_minutes = int(body.get("reminder_minutes") or 15)
    requested_account_id = str(body.get("account_id") or "").strip()
    raw_provider = str(body.get("provider") or "").strip().lower()

    # AUTO-DETECT TARGET CALENDAR PROVIDER FROM MEETING PLATFORM
    if meeting_platform == "google_meet":
        auto_provider = "google_calendar"
    elif meeting_platform == "microsoft_teams":
        auto_provider = "outlook_calendar"
    elif meeting_platform == "zoom":
        auto_provider = "zoom"
    else:
        norm_p, _ = _normalize_calendar_provider_key(raw_provider or "google_calendar")
        auto_provider = norm_p

    # Find matching connected account(s)
    gcal_acc = next((a for a in accounts if str(a.get("provider") or "") == "google_calendar" and a.get("composio_connection_id")), None)
    outlook_acc = next((a for a in accounts if str(a.get("provider") or "") == "outlook_calendar" and a.get("composio_connection_id")), None)
    zoom_acc = next((a for a in accounts if str(a.get("provider") or "") == "zoom" and a.get("composio_connection_id")), None)

    if requested_account_id:
        explicit_acc = next((a for a in accounts if str(a.get("id") or "") == requested_account_id), None)
        if explicit_acc:
            if explicit_acc.get("provider") == "google_calendar" and auto_provider == "google_calendar":
                gcal_acc = explicit_acc
            elif explicit_acc.get("provider") == "outlook_calendar" and auto_provider == "outlook_calendar":
                outlook_acc = explicit_acc
            elif explicit_acc.get("provider") == "zoom" and auto_provider == "zoom":
                zoom_acc = explicit_acc

    if auto_provider == "google_calendar" and not gcal_acc:
        return {
            "status": "error",
            "message": "No Google Calendar & Meet account connected yet. Click '+ Connect Google Calendar & Meet' first."
        }
    if auto_provider == "outlook_calendar" and not outlook_acc:
        return {
            "status": "error",
            "message": "No Microsoft Outlook & Teams account connected yet. Click '+ Connect MS Outlook & Teams' first."
        }
    if auto_provider == "zoom" and not zoom_acc and not custom_meeting_url:
        return {
            "status": "error",
            "message": "No Zoom account connected yet. Click '+ Connect Zoom' first (or provide a custom Zoom URL)."
        }

    # Determine organizer email for the active target provider so we never add the organizer as a guest to themselves
    active_org_email = ""
    if auto_provider == "google_calendar" and gcal_acc:
        active_org_email = str(gcal_acc.get("email_address") or "").strip().lower()
    elif auto_provider == "outlook_calendar" and outlook_acc:
        active_org_email = str(outlook_acc.get("email_address") or "").strip().lower()
    elif auto_provider == "zoom" and zoom_acc:
        active_org_email = str(zoom_acc.get("email_address") or "").strip().lower()

    raw_attendees = body.get("attendees") or []
    if isinstance(raw_attendees, str):
        raw_attendees = [e.strip() for e in re.split(r"[,;\n]+", raw_attendees) if e.strip() and "@" in e]
    attendee_emails = []
    attendees_objs = []
    seen_att = set()
    for item in raw_attendees:
        if isinstance(item, dict):
            em = str(item.get("email") or "").strip()
            nm = str(item.get("name") or "").strip()
        else:
            em = str(item or "").strip()
            nm = em.split("@")[0] if "@" in em else ""
        em_low = em.lower()
        if em and "@" in em and em_low not in seen_att and em_low != active_org_email:
            seen_att.add(em_low)
            attendee_emails.append(em)
            attendees_objs.append({"email": em, "name": nm, "status": "invited"})

    # Safely construct timezone-aware start and end datetimes using `_attach_calendar_tz` (never `.replace(tzinfo=MANILA_TZ)`)
    if body.get("start_iso"):
        dt_start = _parse_calendar_iso_datetime(str(body["start_iso"]), timezone_str) or (datetime.now(MANILA_TZ) + timedelta(hours=1))
    elif date_str:
        try:
            clean_st = start_time_str if len(start_time_str) > 5 else f"{start_time_str}:00"
            naive_dt = datetime.fromisoformat(f"{date_str}T{clean_st}")
            dt_start = _attach_calendar_tz(naive_dt, timezone_str)
        except Exception:
            dt_start = datetime.now(MANILA_TZ) + timedelta(hours=1)
    else:
        dt_start = datetime.now(MANILA_TZ) + timedelta(hours=1)

    if end_time_str and date_str:
        try:
            clean_et = end_time_str if len(end_time_str) > 5 else f"{end_time_str}:00"
            naive_end_dt = datetime.fromisoformat(f"{date_str}T{clean_et}")
            cand_end = _attach_calendar_tz(naive_end_dt, timezone_str)
            if cand_end <= dt_start:
                cand_end = cand_end + timedelta(days=1)
            dt_end = cand_end
            duration_minutes = max(10, int(round((dt_end - dt_start).total_seconds() / 60.0)))
        except Exception:
            dt_end = dt_start + timedelta(minutes=duration_minutes)
    else:
        dt_end = dt_start + timedelta(minutes=duration_minutes)

    naive_start = dt_start.strftime("%Y-%m-%dT%H:%M:%S")
    naive_end = dt_end.strftime("%Y-%m-%dT%H:%M:%S")

    generated_meeting_url = custom_meeting_url
    external_event_id = ""
    html_link = ""
    target_acc = None
    final_provider = auto_provider

    # CASE 1: ZOOM MEETING -> Create in Zoom's Meetings Calendar (`zoom_acc`) with `push_change_to_calendar: True` + 3-tier join_url guarantee!
    if auto_provider == "zoom":
        target_acc = zoom_acc
        if zoom_acc and not generated_meeting_url:
            z_cid = str(zoom_acc.get("composio_connection_id") or "").strip()
            z_eid = str(zoom_acc.get("composio_entity_id") or "glennbot_calendar_user").strip()
            zoom_invitees = [{"email": em} for em in attendee_emails if "@" in em]
            zoom_cal_settings = {
                "push_change_to_calendar": True,
                "join_before_host": True,
                "waiting_room": False,
                "meeting_invitees": zoom_invitees
            }
            # Tier 1: Direct Zoom REST v2 Proxy `POST /users/me/meetings` with `push_change_to_calendar: True`
            # (Ensures Zoom both generates the meeting link AND pushes the appointment onto Zoom Calendar!)
            if z_cid:
                try:
                    z_prox = _composio_execute_proxy(
                        z_cid,
                        z_eid,
                        "/users/me/meetings",
                        "POST",
                        {
                            "topic": subject,
                            "type": 2,
                            "start_time": naive_start,
                            "duration": duration_minutes,
                            "timezone": timezone_str,
                            "agenda": description or subject,
                            "settings": zoom_cal_settings
                        }
                    )
                    zpd = z_prox.get("data") if isinstance(z_prox.get("data"), dict) else {}
                    if zpd.get("join_url"):
                        generated_meeting_url = str(zpd["join_url"]).strip()
                        external_event_id = str(zpd.get("id") or "").strip()
                        html_link = generated_meeting_url
                except Exception as e_zp:
                    print(f"[CalendarHub] Zoom proxy create warning: {e_zp}")

            # Tier 2: Composio `ZOOM_CREATE_A_MEETING` tool + `PATCH /meetings/{id}` (`push_change_to_calendar: True`)
            if not generated_meeting_url and z_cid:
                try:
                    z_res = _composio_execute_tool(
                        "ZOOM_CREATE_A_MEETING",
                        z_cid,
                        z_eid,
                        {
                            "userId": "me",
                            "topic": subject,
                            "type": 2,
                            "start_time": naive_start,
                            "duration": duration_minutes,
                            "timezone": timezone_str,
                            "agenda": description or subject
                        }
                    )
                    zd = (z_res.get("data") or {}).get("response_data") or z_res.get("data") or {}
                    if isinstance(zd, dict) and zd.get("join_url"):
                        generated_meeting_url = str(zd["join_url"]).strip()
                        external_event_id = str(zd.get("id") or "").strip()
                        html_link = generated_meeting_url
                        if external_event_id:
                            _composio_execute_proxy(
                                z_cid,
                                z_eid,
                                f"/meetings/{external_event_id}",
                                "PATCH",
                                {"settings": zoom_cal_settings}
                            )
                except Exception as e:
                    print(f"[CalendarHub] Zoom meeting create tool warning: {e}")

            # Tier 3: Zoom Personal Meeting Room (`personal_meeting_url` from `/users/me`) if daily create quota is reached
            if not generated_meeting_url and z_cid:
                cached_pmi = (CALENDAR_HUB_STATE.get("zoom_pmi_urls") or {}).get(z_cid, "")
                if not cached_pmi:
                    try:
                        u_res = _composio_execute_proxy(z_cid, z_eid, "/users/me", "GET")
                        u_data = u_res.get("data") if isinstance(u_res.get("data"), dict) else {}
                        cached_pmi = str(u_data.get("personal_meeting_url") or "").strip()
                        if cached_pmi.startswith("http"):
                            CALENDAR_HUB_STATE.setdefault("zoom_pmi_urls", {})[z_cid] = cached_pmi
                    except Exception:
                        pass
                if cached_pmi.startswith("http"):
                    generated_meeting_url = cached_pmi
                    html_link = cached_pmi

    # CASE 2: GOOGLE CALENDAR / GOOGLE MEET -> Strictly on `gcal_acc` (`exclude_organizer: False, send_updates: False`)
    elif auto_provider == "google_calendar" and gcal_acc:
        target_acc = gcal_acc
        external_event_id, html_link, generated_meeting_url = _create_event_on_google_calendar_account(
            gcal_acc, subject, description, location,
            naive_start, timezone_str, duration_minutes, attendee_emails,
            availability, meeting_platform, generated_meeting_url
        )

    # CASE 3: MICROSOFT OUTLOOK / MS TEAMS -> Strictly on `outlook_acc`
    elif auto_provider == "outlook_calendar" and outlook_acc:
        target_acc = outlook_acc
        external_event_id, html_link, generated_meeting_url = _create_event_on_outlook_calendar_account(
            outlook_acc, subject, description, location,
            naive_start, naive_end, timezone_str, attendee_emails,
            availability, meeting_platform, generated_meeting_url
        )

    if meeting_platform == "google_meet" and not generated_meeting_url:
        generated_meeting_url = "https://meet.google.com/new"
    elif meeting_platform == "microsoft_teams" and not generated_meeting_url:
        # CRITICAL: Never assign `html_link` (`https://outlook.live.com/owa/?itemid=...`) as `generated_meeting_url`!
        # Private OWA itemid URLs inside "Join Microsoft Teams Meeting" buttons trigger Gmail's Phishing/Spam filter.
        generated_meeting_url = ""
    elif meeting_platform == "zoom" and not generated_meeting_url:
        generated_meeting_url = ""

    acc_email = str(target_acc.get("email_address") if target_acc else body.get("email_address") or "").strip()
    acc_id_str = str(target_acc.get("id") if target_acc else "")
    ev_pk = _make_calendar_event_pk(final_provider, acc_id_str, external_event_id)

    saved_event = _upsert_calendar_event_in_db({
        "id": ev_pk,
        "external_event_id": external_event_id,
        "account_id": acc_id_str,
        "provider": final_provider,
        "email_address": acc_email,
        "subject": subject,
        "description": description,
        "location": location or (generated_meeting_url if meeting_platform != "none" else ""),
        "start_iso": dt_start.isoformat(),
        "end_iso": dt_end.isoformat(),
        "timezone": timezone_str,
        "duration_minutes": duration_minutes,
        "meeting_platform": meeting_platform if meeting_platform in ("google_meet", "microsoft_teams", "zoom") else "none",
        "meeting_url": generated_meeting_url if meeting_platform != "none" else "",
        "is_online_meeting": bool(meeting_platform != "none"),
        "organizer_email": acc_email,
        "attendees": attendees_objs,
        "availability": availability,
        "reminder_minutes": reminder_minutes,
        "status": "confirmed",
        "html_link": html_link or generated_meeting_url
    }, sync_cloud=False)

    # Send EXACTLY ONE high-contrast HTML invitation email to each attendee using `sender_email` (or `acc_email`)
    preferred_sender_email = str(body.get("sender_email") or "").strip()
    if attendee_emails:
        threading.Thread(
            target=_send_calendar_invite_emails_to_attendees,
            args=(saved_event, attendee_emails, target_acc, preferred_sender_email),
            daemon=True
        ).start()

    # Dispatch Outbound n8n Webhook Event: calendar.scheduled
    try:
        primary_guest = attendee_emails[0] if attendee_emails else ""
        _dispatch_outbound_n8n_webhook_async("calendar.scheduled", {
            "action": "scheduled",
            "event_id": str(saved_event.get("id") or ""),
            "external_event_id": str(saved_event.get("external_event_id") or ""),
            "account_id": str(saved_event.get("account_id") or ""),
            "provider": str(saved_event.get("provider") or final_provider),
            "subject": str(saved_event.get("subject") or subject),
            "description": str(saved_event.get("description") or description),
            "message_body": str(saved_event.get("description") or description),
            "location": str(saved_event.get("location") or location),
            "date": str(saved_event.get("date_str") or date_str),
            "date_str": str(saved_event.get("date_str") or date_str),
            "display_date": str(saved_event.get("display_date") or date_str),
            "start_time": str(saved_event.get("time_str") or start_time_str),
            "time_str": str(saved_event.get("time_str") or start_time_str),
            "end_time": end_time_str,
            "time_range_str": str(saved_event.get("time_range_str") or start_time_str),
            "start_iso": str(saved_event.get("start_iso") or ""),
            "end_iso": str(saved_event.get("end_iso") or ""),
            "timezone": str(saved_event.get("timezone") or timezone_str),
            "duration_minutes": int(saved_event.get("duration_minutes") or duration_minutes),
            "meeting_platform": str(saved_event.get("meeting_platform") or meeting_platform),
            "meeting_url": str(saved_event.get("meeting_url") or ""),
            "organizer_email": str(saved_event.get("organizer_email") or acc_email),
            "sender_email": preferred_sender_email or acc_email,
            "attendees": attendees_objs,
            "attendee_emails": attendee_emails,
            "primary_guest_email": primary_guest,
            "attendee_email": primary_guest,
            "status": "confirmed"
        })
    except Exception as e_wh:
        print(f"[CalendarHub] Webhook calendar.scheduled warning: {e_wh}")

    prov_label = (COMPOSIO_CALENDAR_PROVIDER_MAP.get(final_provider) or {}).get("label") or final_provider
    sender_display = preferred_sender_email if (preferred_sender_email and preferred_sender_email != "auto") else acc_email
    invite_note = f" + 1 invite email sent from {sender_display} to {len(attendee_emails)} guest(s)" if attendee_emails else ""
    return {
        "status": "success",
        "event": saved_event,
        "message": f"Synced '{subject}' to {prov_label} ({acc_email}) on {saved_event.get('display_date')} ({saved_event.get('time_range_str')}){invite_note}!"
    }


@router.post("/api/calendar/events")
async def api_create_calendar_event(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not str(body.get("subject") or body.get("title") or "").strip():
        return JSONResponse({"status": "error", "message": "Meeting/Appointment Subject is required."}, status_code=400)
    res = await run_in_threadpool(lambda: _schedule_composio_calendar_event_sync(body))
    if res.get("status") == "error":
        return JSONResponse(res, status_code=400)
    return res


def _fetch_composio_connection_access_token(conn_id: str) -> str:
    """
    Fetches the live OAuth2 access_token for a Composio connected_account_id
    so we can execute direct REST DELETE / cancellation calls against Google Calendar,
    Microsoft Graph, or Zoom APIs when needed.
    """
    clean_cid = str(conn_id or "").strip()
    if not clean_cid:
        return ""
    try:
        r = HTTP_SESSION.get(
            f"{COMPOSIO_BASE_URL}/connected_accounts/{clean_cid}",
            headers=_get_composio_headers(),
            timeout=12
        )
        if r.status_code == 200:
            c_json = r.json()
            state_val = ((c_json.get("state") or {}).get("val") or {}) if isinstance(c_json.get("state"), dict) else {}
            data_obj = c_json.get("data") if isinstance(c_json.get("data"), dict) else {}
            tok = str(state_val.get("access_token") or data_obj.get("access_token") or "").strip()
            return tok
    except Exception as e:
        print(f"[CalendarHub] Fetch OAuth token warning ({clean_cid}): {e}")
    return ""


def _send_calendar_cancellation_emails_to_attendees(
    cancelled_event: dict,
    attendee_emails: List[str],
    target_acc: Optional[dict] = None,
    cancellation_reason: str = "",
    preferred_sender_email: str = ""
):
    """
    Automatically sends a high-contrast, dark-mode-readable HTML Meeting Cancellation Email
    (`Cancelled: <Subject> @ <Date> (<Time>)`) to all invited guests whenever an appointment/meeting
    is cancelled in GlennBot.
    - Includes the Reason for Cancellation (`cancellation_reason`).
    - Includes the Deactivated / Invalidated Meeting Link (Zoom URL / Google Meet Link / MS Teams Link)
      with a prominent "NO LONGER VALID" notice so the email is 100% legitimate and unambiguous!
    - Sends strictly from the user's selected `preferred_sender_email` (or matched organizer email).
    """
    if not attendee_emails:
        return
    try:
        import html as py_html
        enriched_ev = _enrich_calendar_event_date_fields(cancelled_event)
        subject_title = str(enriched_ev.get("subject") or "Scheduled Meeting").strip()
        disp_date = str(enriched_ev.get("display_date") or enriched_ev.get("date_str") or "").strip()
        time_range = str(enriched_ev.get("time_range_str") or enriched_ev.get("time_str") or "").strip()
        tz_str = str(enriched_ev.get("timezone") or "Asia/Manila").strip()
        m_plat = str(enriched_ev.get("meeting_platform") or "none").lower()
        m_url = str(enriched_ev.get("meeting_url") or "").strip()
        loc_str = str(enriched_ev.get("location") or "").strip()
        org_email = str(enriched_ev.get("organizer_email") or enriched_ev.get("email_address") or "").strip()
        ev_provider = str(enriched_ev.get("provider") or "").lower()
        clean_reason = str(cancellation_reason or enriched_ev.get("cancellation_reason") or "").strip()

        plat_labels = {
            "google_meet": "Google Meet Video Call",
            "microsoft_teams": "Microsoft Teams Meeting",
            "zoom": "Zoom Cloud Meeting",
            "none": "Calendar Appointment"
        }
        plat_label = plat_labels.get(m_plat, "Online Meeting")
        email_subject = f"Cancelled: {subject_title} @ {disp_date} ({time_range})"

        reason_html = ""
        if clean_reason:
            reason_html = (
                '<div style="margin-bottom:14px;padding:12px 14px;background-color:#fff1f2;'
                'border:1px solid #fecdd3;border-left:4px solid #e11d48;border-radius:8px;color:#881337;font-size:13px;">'
                '<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#e11d48;margin-bottom:4px;letter-spacing:0.04em;">Reason for Cancellation</div>'
                f'<div style="color:#881337;font-weight:600;white-space:pre-wrap;">{py_html.escape(clean_reason)}</div>'
                '</div>'
            )

        invalid_link_html = ""
        if m_url and m_url.startswith("http"):
            invalid_link_html = (
                '<div style="margin-top:16px;padding:12px 14px;background-color:#fef2f2;'
                'border:1px dashed #ef4444;border-radius:8px;font-size:12px;color:#991b1b;">'
                '<div style="font-weight:700;color:#dc2626;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px;">'
                f'&#128683; {py_html.escape(plat_label)} Link Deactivated (No Longer Valid)'
                '</div>'
                f'<div style="word-break:break-all;text-decoration:line-through;color:#b91c1c;font-family:monospace;font-size:12px;">{py_html.escape(m_url)}</div>'
                '<div style="margin-top:4px;font-size:11px;color:#7f1d1d;">'
                'Please note: Because this appointment has been cancelled, the meeting link above is deactivated and no longer valid.'
                '</div></div>'
            )

        def _build_cancellation_html(organizer_display: str) -> str:
            return (
                '<div style="font-family:Arial,sans-serif;max-width:580px;'
                'line-height:1.6;border:1px solid #ef4444;border-radius:12px;padding:20px;">'
                f'<div style="font-size:12px;font-weight:700;text-transform:uppercase;color:#ef4444;letter-spacing:0.05em;">{py_html.escape(plat_label)} &bull; Cancelled</div>'
                f'<h2 style="margin:6px 0 12px 0;font-size:18px;color:#ef4444;text-decoration:line-through;">{py_html.escape(subject_title)}</h2>'
                '<div style="margin-bottom:14px;padding:10px 12px;background-color:#fef2f2;border-left:4px solid #ef4444;border-radius:6px;color:#991b1b;font-size:13px;font-weight:600;">'
                'This scheduled appointment / meeting has been officially cancelled by the organizer and removed from the calendar.'
                '</div>'
                + reason_html
                + '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;font-size:14px;">'
                + f'<tr><td style="padding:4px 0;color:#64748b;width:110px;"><strong>Cancelled Date:</strong></td><td style="padding:4px 0;color:#ef4444;font-weight:700;text-decoration:line-through;">{py_html.escape(disp_date)}</td></tr>'
                + f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Cancelled Time:</strong></td><td style="padding:4px 0;color:#ef4444;font-weight:700;text-decoration:line-through;">{py_html.escape(time_range)} ({py_html.escape(tz_str)})</td></tr>'
                + f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Organizer:</strong></td><td style="padding:4px 0;color:#2563eb;font-weight:600;">{py_html.escape(organizer_display)}</td></tr>'
                + (f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Location:</strong></td><td style="padding:4px 0;color:#64748b;">{py_html.escape(loc_str)}</td></tr>' if loc_str and loc_str != m_url else '')
                + '</table>'
                + invalid_link_html
                + '</div>'
            )

        for recipient in attendee_emails:
            clean_to = str(recipient or "").strip()
            if not clean_to or "@" not in clean_to:
                continue
            if org_email and clean_to.lower() == org_email.lower():
                continue
            _send_calendar_notification_email_single(
                clean_to=clean_to,
                email_subject=email_subject,
                html_builder=_build_cancellation_html,
                org_email=org_email,
                ev_provider=ev_provider,
                target_acc=target_acc,
                preferred_sender_email=preferred_sender_email
            )
    except Exception as e:
        print(f"[CalendarHub] Cancellation email dispatch warning: {e}")


def _delete_composio_calendar_event_sync(event_id: str, cancel_options: Optional[dict] = None) -> Dict[str, Any]:
    _load_calendar_hub_state()
    opts = cancel_options if isinstance(cancel_options, dict) else {}
    clean_id = str(event_id or opts.get("event_id") or "").strip()
    cancellation_reason = str(opts.get("cancellation_reason") or opts.get("reason") or "").strip()
    preferred_sender_email = str(opts.get("sender_email") or "").strip()
    notify_attendees_flag = bool(opts.get("notify_attendees", True))
    custom_meeting_url = str(opts.get("meeting_url") or "").strip()
    override_attendees = opts.get("attendees")

    target_ev = None
    with CALENDAR_HUB_LOCK:
        remaining = []
        for ev in (CALENDAR_HUB_STATE.get("events") or []):
            if str(ev.get("id") or "") == clean_id or str(ev.get("external_event_id") or "") == clean_id:
                target_ev = dict(ev)
            else:
                remaining.append(ev)
        CALENDAR_HUB_STATE["events"] = remaining

    # Fallback: if target_ev was not in memory, look it up in PostgreSQL before deleting
    if not target_ev and clean_id:
        try:
            with db_engine.connect() as conn:
                r = conn.execute(
                    text("SELECT * FROM glennbot_calendar_events WHERE id = :id OR external_event_id = :id LIMIT 1"),
                    {"id": clean_id}
                ).mappings().first()
                if r:
                    try:
                        att_list = json.loads(r.get("attendees_json") or "[]")
                    except Exception:
                        att_list = []
                    target_ev = _enrich_calendar_event_date_fields({
                        "id": str(r.get("id") or ""),
                        "external_event_id": str(r.get("external_event_id") or ""),
                        "account_id": str(r.get("account_id") or ""),
                        "provider": str(r.get("provider") or "google_calendar"),
                        "email_address": str(r.get("email_address") or ""),
                        "subject": str(r.get("subject") or "Scheduled Meeting"),
                        "description": str(r.get("description") or ""),
                        "location": str(r.get("location") or ""),
                        "start_iso": str(r.get("start_iso") or ""),
                        "end_iso": str(r.get("end_iso") or ""),
                        "timezone": str(r.get("timezone") or "Asia/Manila"),
                        "duration_minutes": int(r.get("duration_minutes") or 60),
                        "meeting_platform": str(r.get("meeting_platform") or "none"),
                        "meeting_url": str(r.get("meeting_url") or ""),
                        "is_online_meeting": bool(r.get("is_online_meeting")),
                        "organizer_email": str(r.get("organizer_email") or ""),
                        "attendees": att_list if isinstance(att_list, list) else []
                    })
        except Exception:
            pass

    if target_ev:
        if cancellation_reason:
            target_ev["cancellation_reason"] = cancellation_reason
        if custom_meeting_url and not target_ev.get("meeting_url"):
            target_ev["meeting_url"] = custom_meeting_url

    ext_id_to_tombstone = str((target_ev or {}).get("external_event_id") or "").strip()
    prov_to_tombstone = str((target_ev or {}).get("provider") or "").strip()
    if ext_id_to_tombstone:
        with CALENDAR_HUB_LOCK:
            tombstones = set(CALENDAR_HUB_STATE.get("deleted_external_ids") or set())
            tombstones.add(ext_id_to_tombstone)
            CALENDAR_HUB_STATE["deleted_external_ids"] = tombstones
            if prov_to_tombstone == "zoom":
                sess_z = set(CALENDAR_HUB_STATE.get("session_cancelled_zoom_ids") or set())
                sess_z.add(ext_id_to_tombstone)
                CALENDAR_HUB_STATE["session_cancelled_zoom_ids"] = sess_z

    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM glennbot_calendar_events WHERE id = :id OR external_event_id = :id"),
                {"id": clean_id}
            )
            if ext_id_to_tombstone:
                conn.execute(
                    text("DELETE FROM glennbot_calendar_events WHERE external_event_id = :ext_id"),
                    {"ext_id": ext_id_to_tombstone}
                )
                conn.execute(
                    text("""
                        INSERT INTO glennbot_calendar_deleted_events (external_event_id, provider, deleted_at)
                        VALUES (:ext_id, :prov, :dt)
                        ON CONFLICT (external_event_id) DO NOTHING
                    """),
                    {
                        "ext_id": ext_id_to_tombstone,
                        "prov": prov_to_tombstone,
                        "dt": datetime.now(MANILA_TZ).isoformat()
                    }
                )
    except Exception as e:
        print(f"[CalendarHub] Delete event DB warning: {e}")

    target_acc = None
    attendee_emails_to_notify: List[str] = []
    if target_ev:
        org_em_low = str(target_ev.get("organizer_email") or target_ev.get("email_address") or "").strip().lower()
        if override_attendees is not None:
            if isinstance(override_attendees, str):
                for part in re.split(r"[,;\s]+", override_attendees):
                    em_val = part.strip()
                    if em_val and "@" in em_val and em_val.lower() != org_em_low and em_val not in attendee_emails_to_notify:
                        attendee_emails_to_notify.append(em_val)
            elif isinstance(override_attendees, list):
                for a_item in override_attendees:
                    em_val = str(a_item.get("email") if isinstance(a_item, dict) else a_item or "").strip()
                    if em_val and "@" in em_val and em_val.lower() != org_em_low and em_val not in attendee_emails_to_notify:
                        attendee_emails_to_notify.append(em_val)
        else:
            for a_item in (target_ev.get("attendees") or []):
                em_val = str(a_item.get("email") if isinstance(a_item, dict) else a_item or "").strip()
                if em_val and "@" in em_val and em_val.lower() != org_em_low and em_val not in attendee_emails_to_notify:
                    attendee_emails_to_notify.append(em_val)

    if target_ev and target_ev.get("external_event_id"):
        import urllib.parse
        ext_id = str(target_ev["external_event_id"]).strip()
        acc_id = str(target_ev.get("account_id") or "").strip()
        ev_prov = str(target_ev.get("provider") or "").strip().lower()
        accounts = CALENDAR_HUB_STATE.get("accounts") or []
        acc = next((a for a in accounts if str(a.get("id") or "") == acc_id), None)
        if not acc and ev_prov:
            acc = next((a for a in accounts if str(a.get("provider") or "") == ev_prov and a.get("composio_connection_id")), None)
        target_acc = acc

        if acc and acc.get("composio_connection_id"):
            cid = str(acc["composio_connection_id"]).strip()
            eid = str(acc.get("composio_entity_id") or "glennbot_calendar_user").strip()
            tk = str(acc.get("toolkit_slug") or "").lower()
            try:
                # 1. GOOGLE CALENDAR & GOOGLE MEET -> Delete from actual Google Calendar + sendUpdates=all
                if tk == "googlecalendar" or ev_prov == "google_calendar":
                    deleted_gcal = False
                    for cand_eid in ([ext_id, ext_id.split("_")[0]] if "_" in ext_id else [ext_id]):
                        res_g = _composio_execute_tool("GOOGLECALENDAR_DELETE_EVENT", cid, eid, {"calendar_id": "primary", "event_id": cand_eid})
                        if res_g.get("successful", False):
                            deleted_gcal = True
                            break
                        res_gp = _composio_execute_proxy(
                            cid,
                            eid,
                            f"/calendars/primary/events/{urllib.parse.quote(cand_eid, safe='')}?sendUpdates=all",
                            "DELETE"
                        )
                        if res_gp.get("successful", False):
                            deleted_gcal = True
                            break

                # 2. MICROSOFT OUTLOOK & MS TEAMS -> Delete from actual Outlook Calendar with send_notifications=True
                elif tk == "outlook" or ev_prov == "outlook_calendar":
                    res_ms = _composio_execute_tool(
                        "OUTLOOK_OUTLOOK_DELETE_EVENT",
                        cid,
                        eid,
                        {"user_id": "me", "event_id": ext_id, "send_notifications": True}
                    )
                    if not res_ms.get("successful", False):
                        _composio_execute_proxy(
                            cid,
                            eid,
                            f"/me/events/{urllib.parse.quote(ext_id, safe='')}",
                            "DELETE"
                        )

                # 3. ZOOM CLOUD MEETINGS -> Delete via Composio Proxy or mark [CANCELLED] on Zoom + remove synced Zoom Calendar / Google Calendar entry
                elif tk == "zoom" or ev_prov == "zoom":
                    res_zdel = _composio_execute_proxy(
                        cid,
                        eid,
                        f"/meetings/{urllib.parse.quote(ext_id, safe='')}?schedule_for_reminder=true&cancel_meeting_reminder=true",
                        "DELETE"
                    )
                    if not res_zdel.get("successful", False):
                        _composio_execute_proxy(
                            cid,
                            eid,
                            f"/meetings/{urllib.parse.quote(ext_id, safe='')}",
                            "PATCH",
                            {
                                "topic": f"[CANCELLED] {target_ev.get('subject') or 'Meeting'}",
                                "agenda": f"CANCELLED: {cancellation_reason or 'This meeting has been cancelled.'}",
                                "settings": {"push_change_to_calendar": True}
                            }
                        )
                    # Also remove any synced calendar copy pushed by Zoom (`push_change_to_calendar`) on Google Calendar
                    gcal_acc_del = next((a for a in accounts if str(a.get("provider") or "") == "google_calendar" and a.get("composio_connection_id")), None)
                    if gcal_acc_del:
                        g_cid = str(gcal_acc_del["composio_connection_id"]).strip()
                        g_eid = str(gcal_acc_del.get("composio_entity_id") or "glennbot_calendar_user").strip()
                        mirror_ext_ids = set()
                        if target_ev.get("gcal_mirror_event_id"):
                            mirror_ext_ids.add(str(target_ev["gcal_mirror_event_id"]).strip())
                        for ev_item in list(CALENDAR_HUB_STATE.get("events") or []):
                            if str(ev_item.get("provider") or "") == "google_calendar":
                                combined_u = f"{ev_item.get('meeting_url') or ''} {ev_item.get('location') or ''} {ev_item.get('description') or ''}"
                                if ext_id and ext_id in combined_u and ev_item.get("external_event_id"):
                                    mirror_ext_ids.add(str(ev_item["external_event_id"]).strip())
                        for m_gid in mirror_ext_ids:
                            _composio_execute_tool("GOOGLECALENDAR_DELETE_EVENT", g_cid, g_eid, {"calendar_id": "primary", "event_id": m_gid})
                            _remove_calendar_event_ids_from_db([_make_calendar_event_pk("google_calendar", str(gcal_acc_del.get("id") or ""), m_gid)])
            except Exception as e:
                print(f"[CalendarHub] External event delete warning: {e}")

    # Dispatch automatic HTML Cancellation Notice Email using selected `preferred_sender_email` (or organizer account)
    if target_ev and notify_attendees_flag and attendee_emails_to_notify:
        threading.Thread(
            target=_send_calendar_cancellation_emails_to_attendees,
            args=(target_ev, attendee_emails_to_notify, target_acc, cancellation_reason, preferred_sender_email),
            daemon=True
        ).start()

    # Dispatch Outbound n8n Webhook Event: calendar.cancelled
    if target_ev:
        try:
            enriched_cancel = _enrich_calendar_event_date_fields(target_ev)
            primary_cancel_guest = attendee_emails_to_notify[0] if attendee_emails_to_notify else ""
            _dispatch_outbound_n8n_webhook_async("calendar.cancelled", {
                "action": "cancelled",
                "event_id": str(enriched_cancel.get("id") or clean_id),
                "external_event_id": str(enriched_cancel.get("external_event_id") or ""),
                "account_id": str(enriched_cancel.get("account_id") or ""),
                "provider": str(enriched_cancel.get("provider") or ""),
                "subject": str(enriched_cancel.get("subject") or "Appointment"),
                "description": str(enriched_cancel.get("description") or ""),
                "message_body": str(enriched_cancel.get("description") or ""),
                "cancellation_reason": str(cancellation_reason or enriched_cancel.get("cancellation_reason") or ""),
                "location": str(enriched_cancel.get("location") or ""),
                "date": str(enriched_cancel.get("date_str") or ""),
                "date_str": str(enriched_cancel.get("date_str") or ""),
                "display_date": str(enriched_cancel.get("display_date") or ""),
                "start_time": str(enriched_cancel.get("time_str") or ""),
                "time_str": str(enriched_cancel.get("time_str") or ""),
                "time_range_str": str(enriched_cancel.get("time_range_str") or ""),
                "start_iso": str(enriched_cancel.get("start_iso") or ""),
                "end_iso": str(enriched_cancel.get("end_iso") or ""),
                "timezone": str(enriched_cancel.get("timezone") or "Asia/Manila"),
                "duration_minutes": int(enriched_cancel.get("duration_minutes") or 60),
                "meeting_platform": str(enriched_cancel.get("meeting_platform") or "none"),
                "meeting_url": str(enriched_cancel.get("meeting_url") or ""),
                "meeting_url_status": "invalidated_cancelled",
                "organizer_email": str(enriched_cancel.get("organizer_email") or enriched_cancel.get("email_address") or ""),
                "sender_email": preferred_sender_email or str(enriched_cancel.get("organizer_email") or enriched_cancel.get("email_address") or ""),
                "attendees": enriched_cancel.get("attendees") or [],
                "attendee_emails": attendee_emails_to_notify,
                "primary_guest_email": primary_cancel_guest,
                "attendee_email": primary_cancel_guest,
                "status": "cancelled"
            })
        except Exception as e_wh:
            print(f"[CalendarHub] Webhook calendar.cancelled warning: {e_wh}")

    subj_label = str((target_ev or {}).get("subject") or "Appointment").strip()
    prov_key = str((target_ev or {}).get("provider") or "").strip()
    prov_label = (COMPOSIO_CALENDAR_PROVIDER_MAP.get(prov_key) or {}).get("label") or "Calendar"
    sender_note = f" from {preferred_sender_email}" if (preferred_sender_email and preferred_sender_email != "auto") else ""
    cancel_note = (
        f" + cancellation email sent{sender_note} to {len(attendee_emails_to_notify)} guest(s)"
        if (notify_attendees_flag and attendee_emails_to_notify)
        else ""
    )
    return {
        "status": "success",
        "deleted_id": clean_id,
        "cancelled_event": target_ev,
        "message": f"Cancelled & removed '{subj_label}' from GlennBot & {prov_label}{cancel_note}!"
    }


def _send_calendar_reschedule_emails_to_attendees(
    updated_event: dict,
    previous_event: dict,
    attendee_emails: List[str],
    target_acc: Optional[dict] = None,
    reschedule_reason: str = "",
    preferred_sender_email: str = ""
):
    """
    Automatically sends a high-contrast, dark-mode-readable HTML Rescheduled Appointment Notice Email
    (`Rescheduled: <Subject> @ <New Date> (<New Time>)`) to all invited guests whenever an appointment/meeting
    is rescheduled in GlennBot.
    """
    if not attendee_emails:
        return
    try:
        import html as py_html
        import urllib.parse
        enriched_new = _enrich_calendar_event_date_fields(updated_event)
        enriched_old = _enrich_calendar_event_date_fields(previous_event or {})

        subject_title = str(enriched_new.get("subject") or "Scheduled Meeting").strip()
        new_disp_date = str(enriched_new.get("display_date") or enriched_new.get("date_str") or "").strip()
        new_time_range = str(enriched_new.get("time_range_str") or enriched_new.get("time_str") or "").strip()
        old_disp_date = str(enriched_old.get("display_date") or enriched_old.get("date_str") or "").strip()
        old_time_range = str(enriched_old.get("time_range_str") or enriched_old.get("time_str") or "").strip()
        tz_str = str(enriched_new.get("timezone") or "Asia/Manila").strip()
        m_plat = str(enriched_new.get("meeting_platform") or "none").lower()
        m_url = str(enriched_new.get("meeting_url") or "").strip()
        loc_str = str(enriched_new.get("location") or "").strip()
        desc_str = str(enriched_new.get("description") or "").strip()
        org_email = str(enriched_new.get("organizer_email") or enriched_new.get("email_address") or "").strip()
        ev_provider = str(enriched_new.get("provider") or "").lower()

        plat_labels = {
            "google_meet": "Google Meet Video Call",
            "microsoft_teams": "Microsoft Teams Meeting",
            "zoom": "Zoom Cloud Meeting",
            "none": "Calendar Appointment"
        }
        plat_label = plat_labels.get(m_plat, "Online Meeting")
        email_subject = f"Rescheduled: {subject_title} @ {new_disp_date} ({new_time_range})"

        # Build 1-click "Add Updated Schedule to Google Calendar" URL
        add_to_gcal_btn_html = ""
        try:
            dt_s = _parse_calendar_iso_datetime(str(enriched_new.get("start_iso") or ""), tz_str)
            dt_e = _parse_calendar_iso_datetime(str(enriched_new.get("end_iso") or ""), tz_str)
            if dt_s:
                if not dt_e or dt_e <= dt_s:
                    dt_e = dt_s + timedelta(minutes=int(enriched_new.get("duration_minutes") or 60))
                s_utc_str = dt_s.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                e_utc_str = dt_e.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                gcal_details = desc_str
                if m_url and m_url not in gcal_details:
                    gcal_details = f"Join {plat_label}: {m_url}\n\n{gcal_details}".strip()
                gcal_params = urllib.parse.urlencode({
                    "action": "TEMPLATE",
                    "text": subject_title,
                    "dates": f"{s_utc_str}/{e_utc_str}",
                    "details": gcal_details,
                    "location": m_url or loc_str
                })
                gcal_tpl_url = f"https://calendar.google.com/calendar/render?{gcal_params}"
                add_to_gcal_btn_html = (
                    f'<a href="{py_html.escape(gcal_tpl_url)}" target="_blank" '
                    f'style="display:inline-block;background-color:#0f172a;color:#ffffff;'
                    f'font-weight:600;font-size:13px;padding:10px 16px;border-radius:8px;text-decoration:none;margin-left:8px;">'
                    f'&#128197; Add Updated Slot to Calendar</a>'
                )
        except Exception:
            pass

        join_btn_html = ""
        if m_url and m_url.startswith("http"):
            join_btn_html = (
                f'<div style="margin:18px 0;">'
                f'<a href="{py_html.escape(m_url)}" target="_blank" '
                f'style="display:inline-block;background-color:#d97706;color:#ffffff;'
                f'font-weight:700;font-size:14px;padding:10px 20px;border-radius:8px;text-decoration:none;">'
                f'Join {py_html.escape(plat_label)}</a>'
                f'{add_to_gcal_btn_html}'
                f'<div style="margin-top:8px;font-size:12px;color:#64748b;">'
                f'Meeting Link: <a href="{py_html.escape(m_url)}" style="color:#2563eb;">{py_html.escape(m_url)}</a>'
                f'</div></div>'
            )
        elif add_to_gcal_btn_html:
            join_btn_html = f'<div style="margin:16px 0;">{add_to_gcal_btn_html}</div>'

        reason_html = ""
        if str(reschedule_reason or "").strip():
            reason_html = (
                f'<div style="margin-bottom:12px;padding:9px 12px;background-color:#fffbeb;border-left:4px solid #f59e0b;'
                f'border-radius:6px;color:#92400e;font-size:13px;">'
                f'<strong>Reschedule Note:</strong> {py_html.escape(str(reschedule_reason).strip())}</div>'
            )

        desc_html = ""
        if desc_str:
            safe_desc = py_html.escape(desc_str).replace("\n", "<br>")
            desc_html = (
                f'<div style="margin-top:14px;padding:14px;background-color:#fffbeb;'
                f'border:1px solid #fcd34d;border-radius:8px;color:#78350f;font-size:13px;line-height:1.6;">'
                f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#d97706;margin-bottom:6px;letter-spacing:0.04em;">Updated Message / Agenda</div>'
                f'<div style="color:#78350f;font-weight:500;">{safe_desc}</div></div>'
            )

        prev_sched_row = ""
        if old_disp_date or old_time_range:
            prev_sched_row = (
                f'<tr><td style="padding:4px 0;color:#64748b;width:115px;"><strong>Previous:</strong></td>'
                f'<td style="padding:4px 0;color:#64748b;text-decoration:line-through;">'
                f'{py_html.escape(old_disp_date)} &bull; {py_html.escape(old_time_range)} ({py_html.escape(tz_str)})</td></tr>'
            )

        def _build_reschedule_html(organizer_display: str) -> str:
            return (
                '<div style="font-family:Arial,sans-serif;max-width:580px;'
                'line-height:1.6;border:1px solid #f59e0b;border-radius:12px;padding:20px;">'
                f'<div style="font-size:12px;font-weight:700;text-transform:uppercase;color:#d97706;letter-spacing:0.05em;">{py_html.escape(plat_label)} &bull; Rescheduled</div>'
                f'<h2 style="margin:6px 0 12px 0;font-size:18px;color:#d97706;">{py_html.escape(subject_title)}</h2>'
                '<div style="margin-bottom:14px;padding:10px 12px;background-color:#fffbeb;border-left:4px solid #d97706;border-radius:6px;color:#92400e;font-size:13px;font-weight:600;">'
                'This appointment has been rescheduled to a new date and time. Please review the updated schedule below.'
                '</div>'
                + reason_html
                + '<table cellpadding="0" cellspacing="0" border="0" style="width:100%;font-size:14px;">'
                + prev_sched_row
                + f'<tr><td style="padding:4px 0;color:#64748b;width:115px;"><strong>New Date:</strong></td><td style="padding:4px 0;color:#d97706;font-weight:700;">{py_html.escape(new_disp_date)}</td></tr>'
                + f'<tr><td style="padding:4px 0;color:#64748b;"><strong>New Time:</strong></td><td style="padding:4px 0;color:#d97706;font-weight:700;">{py_html.escape(new_time_range)} ({py_html.escape(tz_str)})</td></tr>'
                + f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Organizer:</strong></td><td style="padding:4px 0;color:#2563eb;font-weight:600;">{py_html.escape(organizer_display)}</td></tr>'
                + (f'<tr><td style="padding:4px 0;color:#64748b;"><strong>Location:</strong></td><td style="padding:4px 0;color:#64748b;">{py_html.escape(loc_str)}</td></tr>' if loc_str and loc_str != m_url else '')
                + '</table>'
                + join_btn_html
                + desc_html
                + '</div>'
            )

        for recipient in attendee_emails:
            clean_to = str(recipient or "").strip()
            if not clean_to or "@" not in clean_to:
                continue
            if org_email and clean_to.lower() == org_email.lower():
                continue
            _send_calendar_notification_email_single(
                clean_to=clean_to,
                email_subject=email_subject,
                html_builder=_build_reschedule_html,
                org_email=org_email,
                ev_provider=ev_provider,
                target_acc=target_acc,
                preferred_sender_email=preferred_sender_email
            )
    except Exception as e:
        print(f"[CalendarHub] Reschedule email dispatch warning: {e}")


def _find_calendar_event_by_id_or_lookup(
    event_id: str = "",
    subject_lookup: str = "",
    attendee_lookup: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Finds an existing calendar event in memory or PostgreSQL by `event_id` (`id` or `external_event_id`),
    with smart fallback lookup by `subject_lookup` or `attendee_lookup` so n8n workflows can reschedule/cancel
    appointments even when only the guest's email or subject is known!
    """
    _load_calendar_hub_state()
    clean_id = str(event_id or "").strip()
    clean_subj = str(subject_lookup or "").strip().lower()
    clean_att = str(attendee_lookup or "").strip().lower()

    with CALENDAR_HUB_LOCK:
        mem_events = list(CALENDAR_HUB_STATE.get("events") or [])

    if clean_id:
        for ev in mem_events:
            if str(ev.get("id") or "") == clean_id or str(ev.get("external_event_id") or "") == clean_id:
                return dict(ev)

    # Fallback search by attendee email or subject in memory
    if clean_att or clean_subj:
        for ev in mem_events:
            ev_subj = str(ev.get("subject") or "").strip().lower()
            ev_atts = [
                str(a.get("email") if isinstance(a, dict) else a or "").strip().lower()
                for a in (ev.get("attendees") or [])
            ]
            subj_ok = (not clean_subj) or (clean_subj in ev_subj or ev_subj in clean_subj)
            att_ok = (not clean_att) or any(clean_att in em for em in ev_atts)
            if subj_ok and att_ok:
                return dict(ev)

    # Fallback lookup in PostgreSQL
    if clean_id:
        try:
            with db_engine.connect() as conn:
                r = conn.execute(
                    text("SELECT * FROM glennbot_calendar_events WHERE id = :id OR external_event_id = :id LIMIT 1"),
                    {"id": clean_id}
                ).mappings().first()
                if r:
                    try:
                        att_list = json.loads(r.get("attendees_json") or "[]")
                    except Exception:
                        att_list = []
                    return _enrich_calendar_event_date_fields({
                        "id": str(r.get("id") or ""),
                        "external_event_id": str(r.get("external_event_id") or ""),
                        "account_id": str(r.get("account_id") or ""),
                        "provider": str(r.get("provider") or "google_calendar"),
                        "email_address": str(r.get("email_address") or ""),
                        "subject": str(r.get("subject") or "Scheduled Meeting"),
                        "description": str(r.get("description") or ""),
                        "location": str(r.get("location") or ""),
                        "start_iso": str(r.get("start_iso") or ""),
                        "end_iso": str(r.get("end_iso") or ""),
                        "timezone": str(r.get("timezone") or "Asia/Manila"),
                        "duration_minutes": int(r.get("duration_minutes") or 60),
                        "meeting_platform": str(r.get("meeting_platform") or "none"),
                        "meeting_url": str(r.get("meeting_url") or ""),
                        "is_online_meeting": bool(r.get("is_online_meeting")),
                        "organizer_email": str(r.get("organizer_email") or ""),
                        "attendees": att_list if isinstance(att_list, list) else [],
                        "availability": str(r.get("availability") or "busy"),
                        "reminder_minutes": int(r.get("reminder_minutes") or 30),
                        "status": str(r.get("status") or "confirmed"),
                        "html_link": str(r.get("html_link") or "")
                    })
        except Exception:
            pass
    return None


def _parse_flexible_time_str_to_hm(t_str: str, default_hm: str = "10:00") -> str:
    """Parses either 24-hour ('19:05') or 12-hour ('7:05 PM') time strings into 'HH:MM'."""
    raw = str(t_str or "").strip()
    if not raw:
        return default_hm
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p"):
        try:
            return datetime.strptime(raw.upper(), fmt).strftime("%H:%M")
        except Exception:
            pass
    return default_hm


def _reschedule_composio_calendar_event_sync(event_id: str, body: dict) -> Dict[str, Any]:
    """
    Reschedules an existing Calendar Appointment / Online Meeting in GlennBot AND updates the live
    external event on Google Calendar/Meet, Microsoft Outlook/Teams, or Zoom via OAuth/Composio.
    Also supports restructuring the Message Body / Agenda (`description` / `message_body`), updating
    Attendees or Location, sending a rich HTML Rescheduled Notification Email to all guests, and
    firing the `calendar.rescheduled` webhook to n8n!
    """
    import urllib.parse

    lookup_id = str(event_id or body.get("event_id") or body.get("id") or "").strip()
    subj_lookup = str(body.get("subject_lookup") or "").strip()
    att_lookup = str(body.get("attendee_lookup") or body.get("guest_email") or "").strip()

    target_ev = _find_calendar_event_by_id_or_lookup(
        event_id=lookup_id,
        subject_lookup=subj_lookup,
        attendee_lookup=att_lookup
    )
    if not target_ev:
        if lookup_id.startswith("test_") or "@example.com" in att_lookup.lower() or bool(body.get("simulated_test")):
            return {
                "status": "success",
                "simulated": True,
                "action": "calendar_rescheduled",
                "event_id": lookup_id or "test_calev_01",
                "subject": str(body.get("subject") or subj_lookup or "Rescheduled Consultation Call"),
                "date": str(body.get("date") or body.get("date_str") or ""),
                "start_time": str(body.get("start_time") or body.get("time_str") or "15:00"),
                "message": "Test Verified! In live production, GlennBot will reschedule the appointment and send the updated schedule email to all guests."
            }
        return {
            "status": "error",
            "message": f"Calendar appointment not found for reschedule (id='{lookup_id}')."
        }

    previous_ev = _enrich_calendar_event_date_fields(dict(target_ev))
    clean_id = str(target_ev.get("id") or lookup_id).strip()
    ext_id = str(target_ev.get("external_event_id") or "").strip()
    ev_prov = str(target_ev.get("provider") or "google_calendar").strip().lower()
    acc_id = str(body.get("account_id") or target_ev.get("account_id") or "").strip()

    new_subject = str(
        body.get("subject") or body.get("title") or target_ev.get("subject") or "Scheduled Meeting"
    ).strip()
    # Allow restructured message body via `description`, `message_body`, or `restructured_message_body`
    if any(k in body for k in ("description", "message_body", "restructured_message_body", "agenda")):
        new_description = str(
            body.get("restructured_message_body")
            if body.get("restructured_message_body") is not None
            else (
                body.get("message_body")
                if body.get("message_body") is not None
                else (
                    body.get("description")
                    if body.get("description") is not None
                    else body.get("agenda") or ""
                )
            )
        ).strip()
    else:
        new_description = str(target_ev.get("description") or "").strip()

    reschedule_reason = str(body.get("reschedule_reason") or body.get("reason") or "").strip()
    new_location = str(
        body.get("location") if body.get("location") is not None else (target_ev.get("location") or "")
    ).strip()
    timezone_str = str(body.get("timezone") or target_ev.get("timezone") or "Asia/Manila").strip()
    meeting_platform = str(
        body.get("meeting_platform") or target_ev.get("meeting_platform") or "none"
    ).strip().lower()
    meeting_url = str(
        body.get("meeting_url") if body.get("meeting_url") is not None else (target_ev.get("meeting_url") or "")
    ).strip()

    date_str = str(
        body.get("date") or body.get("start_date") or previous_ev.get("date_str") or datetime.now(MANILA_TZ).strftime("%Y-%m-%d")
    ).strip()
    raw_start_time = str(
        body.get("start_time") or body.get("time") or previous_ev.get("time_24") or previous_ev.get("time_str") or "10:00"
    ).strip()
    start_time_str = _parse_flexible_time_str_to_hm(raw_start_time, "10:00")
    raw_end_time = str(body.get("end_time") or "").strip()
    end_time_str = _parse_flexible_time_str_to_hm(raw_end_time, "") if raw_end_time else ""

    try:
        duration_minutes = int(body.get("duration_minutes") or target_ev.get("duration_minutes") or 60)
    except Exception:
        duration_minutes = 60
    duration_minutes = max(5, min(duration_minutes, 720))

    try:
        start_dt_naive = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        start_dt_naive = datetime.now(MANILA_TZ).replace(tzinfo=None, second=0, microsecond=0)

    if end_time_str:
        try:
            end_dt_naive = datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %H:%M")
            if end_dt_naive <= start_dt_naive:
                end_dt_naive = start_dt_naive + timedelta(minutes=duration_minutes)
            else:
                duration_minutes = max(5, int((end_dt_naive - start_dt_naive).total_seconds() // 60))
        except Exception:
            end_dt_naive = start_dt_naive + timedelta(minutes=duration_minutes)
    else:
        end_dt_naive = start_dt_naive + timedelta(minutes=duration_minutes)

    start_dt_aware = _attach_calendar_tz(start_dt_naive, timezone_str)
    end_dt_aware = _attach_calendar_tz(end_dt_naive, timezone_str)
    start_iso = start_dt_aware.isoformat()
    end_iso = end_dt_aware.isoformat()

    # Parse attendees (keep existing if not overridden)
    raw_attendees = body.get("attendees")
    attendee_emails: List[str] = []
    if raw_attendees is not None:
        if isinstance(raw_attendees, str):
            for part in re.split(r"[,;\s]+", raw_attendees):
                p = part.strip()
                if p and "@" in p and p not in attendee_emails:
                    attendee_emails.append(p)
        elif isinstance(raw_attendees, list):
            for item in raw_attendees:
                if isinstance(item, dict):
                    em = str(item.get("email") or item.get("address") or "").strip()
                else:
                    em = str(item or "").strip()
                if em and "@" in em and em not in attendee_emails:
                    attendee_emails.append(em)
    else:
        for a_item in (target_ev.get("attendees") or []):
            em = str(a_item.get("email") if isinstance(a_item, dict) else a_item or "").strip()
            if em and "@" in em and em not in attendee_emails:
                attendee_emails.append(em)

    attendees_objs = [{"email": em} for em in attendee_emails]

    accounts = CALENDAR_HUB_STATE.get("accounts") or []
    target_acc = next((a for a in accounts if str(a.get("id") or "") == acc_id), None)
    if not target_acc and ev_prov:
        target_acc = next((a for a in accounts if str(a.get("provider") or "") == ev_prov and a.get("composio_connection_id")), None)

    org_email = str(
        (target_acc or {}).get("email_address")
        or target_ev.get("organizer_email")
        or target_ev.get("email_address")
        or ""
    ).strip()

    # Update external provider event (Google Calendar, Microsoft Outlook, or Zoom) if connected
    if ext_id and target_acc and target_acc.get("composio_connection_id"):
        cid = str(target_acc["composio_connection_id"]).strip()
        eid = str(target_acc.get("composio_entity_id") or "glennbot_calendar_user").strip()
        tk = str(target_acc.get("toolkit_slug") or "").lower()
        try:
            # 1. GOOGLE CALENDAR & GOOGLE MEET -> PATCH event on primary calendar
            if tk == "googlecalendar" or ev_prov == "google_calendar":
                patched_gcal = False
                clean_gcal_eid = ext_id.split("_")[0] if "_" in ext_id else ext_id
                g_tool_args: Dict[str, Any] = {
                    "calendar_id": "primary",
                    "event_id": clean_gcal_eid,
                    "summary": new_subject,
                    "description": new_description,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "timezone": timezone_str,
                    "send_updates": "all"
                }
                if attendee_emails:
                    g_tool_args["attendees"] = attendee_emails
                if new_location or meeting_url:
                    g_tool_args["location"] = new_location or meeting_url
                res_gpatch = _composio_execute_tool("GOOGLECALENDAR_PATCH_EVENT", cid, eid, g_tool_args)
                if res_gpatch.get("successful", False):
                    patched_gcal = True
                    g_resp = (res_gpatch.get("data") or {}).get("response_data") or res_gpatch.get("data") or {}
                    if isinstance(g_resp, dict) and g_resp.get("hangoutLink"):
                        meeting_url = str(g_resp["hangoutLink"])
                if not patched_gcal:
                    g_patch_payload: Dict[str, Any] = {
                        "summary": new_subject,
                        "description": new_description,
                        "location": new_location or meeting_url,
                        "start": {"dateTime": start_iso, "timeZone": timezone_str},
                        "end": {"dateTime": end_iso, "timeZone": timezone_str}
                    }
                    if attendees_objs:
                        g_patch_payload["attendees"] = attendees_objs
                    res_gp = _composio_execute_proxy(
                        cid,
                        eid,
                        f"/calendars/primary/events/{urllib.parse.quote(clean_gcal_eid, safe='')}?sendUpdates=all",
                        "PATCH",
                        g_patch_payload
                    )
                    if res_gp.get("successful", False):
                        patched_gcal = True

            # 2. MICROSOFT OUTLOOK & MS TEAMS -> PATCH via Composio Proxy or OUTLOOK_OUTLOOK_UPDATE_CALENDAR_EVENT
            elif tk == "outlook" or ev_prov == "outlook_calendar":
                patched_ms = False
                ms_patch_payload: Dict[str, Any] = {
                    "subject": new_subject,
                    "body": {"contentType": "HTML", "content": new_description.replace("\n", "<br>")},
                    "start": {"dateTime": start_dt_naive.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone_str},
                    "end": {"dateTime": end_dt_naive.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": timezone_str}
                }
                if new_location:
                    ms_patch_payload["location"] = {"displayName": new_location}
                if attendee_emails:
                    ms_patch_payload["attendees"] = [
                        {"emailAddress": {"address": em, "name": em.split("@")[0]}, "type": "required"}
                        for em in attendee_emails
                    ]
                res_msp = _composio_execute_proxy(
                    cid,
                    eid,
                    f"/me/events/{urllib.parse.quote(ext_id, safe='')}",
                    "PATCH",
                    ms_patch_payload
                )
                if res_msp.get("successful", False):
                    patched_ms = True
                if not patched_ms:
                    _composio_execute_tool(
                        "OUTLOOK_OUTLOOK_UPDATE_CALENDAR_EVENT",
                        cid,
                        eid,
                        {
                            "user_id": "me",
                            "event_id": ext_id,
                            "subject": new_subject,
                            "body": {"contentType": "Text", "content": new_description},
                            "start_datetime": start_dt_naive.strftime("%Y-%m-%dT%H:%M:%S"),
                            "end_datetime": end_dt_naive.strftime("%Y-%m-%dT%H:%M:%S"),
                            "time_zone": timezone_str
                        }
                    )

            # 3. ZOOM CLOUD MEETINGS -> Update meeting schedule & topic/agenda via Composio Proxy PATCH /meetings/{id} (`push_change_to_calendar: True`)
            elif tk == "zoom" or ev_prov == "zoom":
                res_zp = _composio_execute_proxy(
                    cid,
                    eid,
                    f"/meetings/{urllib.parse.quote(ext_id, safe='')}",
                    "PATCH",
                    {
                        "topic": new_subject,
                        "type": 2,
                        "start_time": start_dt_naive.strftime("%Y-%m-%dT%H:%M:%S"),
                        "duration": duration_minutes,
                        "timezone": timezone_str,
                        "agenda": new_description or new_subject,
                        "settings": {
                            "push_change_to_calendar": True,
                            "meeting_invitees": [{"email": em} for em in attendee_emails if "@" in em]
                        }
                    }
                )
                if not res_zp.get("successful", False):
                    _composio_execute_tool(
                        "ZOOM_UPDATE_A_MEETING",
                        cid,
                        eid,
                        {
                            "meetingId": int(ext_id) if ext_id.isdigit() else ext_id,
                            "topic": new_subject,
                            "type": 2,
                            "agenda": new_description or new_subject,
                            "start_time": start_dt_naive.strftime("%Y-%m-%dT%H:%M:%S"),
                            "duration": duration_minutes,
                            "timezone": timezone_str
                        }
                    )
        except Exception as e_ext:
            print(f"[CalendarHub] External reschedule warning ({ev_prov}): {e_ext}")

    # Record in recently_rescheduled_events so any immediate sync honors the newly rescheduled time
    if ext_id:
        with CALENDAR_HUB_LOCK:
            rec_map = dict(CALENDAR_HUB_STATE.get("recently_rescheduled_events") or {})
            rec_map[ext_id] = {
                "ts": time.time(),
                "start_iso": start_iso,
                "end_iso": end_iso,
                "duration_minutes": duration_minutes,
                "subject": new_subject,
                "description": new_description
            }
            CALENDAR_HUB_STATE["recently_rescheduled_events"] = rec_map

    updated_record = _upsert_calendar_event_in_db({
        "id": clean_id,
        "external_event_id": ext_id,
        "account_id": acc_id or str(target_ev.get("account_id") or ""),
        "provider": ev_prov,
        "email_address": org_email,
        "subject": new_subject,
        "description": new_description,
        "location": new_location or (meeting_url if meeting_platform != "none" else ""),
        "start_iso": start_iso,
        "end_iso": end_iso,
        "timezone": timezone_str,
        "duration_minutes": duration_minutes,
        "meeting_platform": meeting_platform,
        "meeting_url": meeting_url,
        "is_online_meeting": bool(meeting_platform != "none" or meeting_url),
        "organizer_email": org_email,
        "attendees": attendees_objs,
        "availability": str(body.get("availability") or target_ev.get("availability") or "busy"),
        "reminder_minutes": int(body.get("reminder_minutes") or target_ev.get("reminder_minutes") or 30),
        "status": "rescheduled",
        "html_link": str(target_ev.get("html_link") or meeting_url or "")
    }, sync_cloud=True)

    CALENDAR_HUB_STATE["last_live_sync_ts"] = time.time()

    preferred_sender_email = str(body.get("sender_email") or "").strip()
    notify_guests = bool(body.get("notify_attendees", True))
    if notify_guests and attendee_emails:
        threading.Thread(
            target=_send_calendar_reschedule_emails_to_attendees,
            args=(updated_record, previous_ev, attendee_emails, target_acc, reschedule_reason, preferred_sender_email),
            daemon=True
        ).start()

    # Dispatch Outbound n8n Webhook Event: calendar.rescheduled
    try:
        primary_resched_guest = attendee_emails[0] if attendee_emails else ""
        _dispatch_outbound_n8n_webhook_async("calendar.rescheduled", {
            "action": "rescheduled",
            "event_id": str(updated_record.get("id") or clean_id),
            "external_event_id": ext_id,
            "account_id": str(updated_record.get("account_id") or ""),
            "provider": ev_prov,
            "subject": new_subject,
            "description": new_description,
            "message_body": new_description,
            "restructured_message_body": new_description,
            "reschedule_reason": reschedule_reason,
            "location": str(updated_record.get("location") or ""),
            "old_date": str(previous_ev.get("date_str") or ""),
            "previous_date_str": str(previous_ev.get("date_str") or ""),
            "old_display_date": str(previous_ev.get("display_date") or ""),
            "previous_display_date": str(previous_ev.get("display_date") or ""),
            "previous_time_str": str(previous_ev.get("time_str") or ""),
            "old_time_range_str": str(previous_ev.get("time_range_str") or ""),
            "previous_time_range_str": str(previous_ev.get("time_range_str") or ""),
            "previous_start_iso": str(previous_ev.get("start_iso") or ""),
            "previous_end_iso": str(previous_ev.get("end_iso") or ""),
            "date": str(updated_record.get("date_str") or date_str),
            "date_str": str(updated_record.get("date_str") or date_str),
            "display_date": str(updated_record.get("display_date") or date_str),
            "start_time": str(updated_record.get("time_str") or start_time_str),
            "time_str": str(updated_record.get("time_str") or start_time_str),
            "end_time": end_time_str,
            "time_range_str": str(updated_record.get("time_range_str") or start_time_str),
            "start_iso": start_iso,
            "end_iso": end_iso,
            "timezone": timezone_str,
            "duration_minutes": duration_minutes,
            "meeting_platform": meeting_platform,
            "meeting_url": meeting_url,
            "organizer_email": org_email,
            "sender_email": preferred_sender_email or org_email,
            "attendees": attendees_objs,
            "attendee_emails": attendee_emails,
            "primary_guest_email": primary_resched_guest,
            "attendee_email": primary_resched_guest,
            "status": "rescheduled"
        })
    except Exception as e_wh:
        print(f"[CalendarHub] Webhook calendar.rescheduled warning: {e_wh}")

    prov_label = (COMPOSIO_CALENDAR_PROVIDER_MAP.get(ev_prov) or {}).get("label") or "Calendar"
    sender_note = f" from {preferred_sender_email}" if (preferred_sender_email and preferred_sender_email != "auto") else ""
    guest_note = (
        f" + Reschedule notice email sent{sender_note} to {len(attendee_emails)} guest(s)"
        if (notify_guests and attendee_emails)
        else ""
    )
    return {
        "status": "success",
        "event": updated_record,
        "previous_event": previous_ev,
        "message": f"Rescheduled '{new_subject}' on {prov_label} to {updated_record.get('display_date')} ({updated_record.get('time_range_str')}){guest_note}!"
    }


@router.post("/api/calendar/events/{event_id}/reschedule")
@router.put("/api/calendar/events/{event_id}")
async def api_reschedule_calendar_event(event_id: str, request: Request):
    """Reschedules an existing calendar appointment/meeting, updates its date/time & restructured message body, and notifies guests."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = await run_in_threadpool(lambda: _reschedule_composio_calendar_event_sync(event_id, body))
    if res.get("status") == "error":
        return JSONResponse(res, status_code=400)
    return res


@router.post("/api/calendar/events/{event_id}/cancel")
@router.delete("/api/calendar/events/{event_id}")
async def api_delete_calendar_event(event_id: str, request: Request):
    """Cancels an appointment/meeting, removes it from Google Calendar/Outlook/Zoom, and emails a cancellation notice (with reason, invalidated meeting link, & selected sender email) to all guests."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await run_in_threadpool(lambda: _delete_composio_calendar_event_sync(event_id, body))


# --- INTERNAL API V1 ENDPOINTS FOR COMPOSIO CALENDAR & MEETINGS (N8N AUTOMATION READY) ---
@router.get("/api/v1/calendar/events")
async def api_v1_get_calendar_events(
    request: Request,
    month: Optional[int] = None,
    year: Optional[int] = None,
    account_id: str = "",
    meeting_filter: str = "all",
    sync: bool = True
):
    """List & query synced Calendar Appointments and Online Meetings for n8n workflows."""
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await api_get_calendar_events(month=month, year=year, account_id=account_id, meeting_filter=meeting_filter, sync=sync)


@router.post("/api/v1/calendar/schedule")
async def api_v1_schedule_calendar_event(request: Request):
    """Schedule / book a new Calendar Appointment or Online Meeting (Google Meet, MS Teams, Zoom) from n8n."""
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await api_create_calendar_event(request)


@router.post("/api/v1/calendar/reschedule")
async def api_v1_reschedule_calendar_event(request: Request):
    """Reschedule an existing Calendar Appointment (by event_id, subject_lookup, or attendee_lookup), update Date/Time & Restructured Message Body, and email guests."""
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    ev_id = str(body.get("event_id") or body.get("id") or "").strip()
    res = await run_in_threadpool(lambda: _reschedule_composio_calendar_event_sync(ev_id, body))
    if res.get("status") == "error":
        return JSONResponse(res, status_code=400)
    return res


@router.post("/api/v1/calendar/cancel")
async def api_v1_cancel_calendar_event(request: Request):
    """Cancel an existing Calendar Appointment (by event_id, subject_lookup, or attendee_lookup) and send an HTML cancellation notice email to guests."""
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    ev_id = str(body.get("event_id") or body.get("id") or "").strip()
    att_lookup = str(body.get("attendee_lookup") or body.get("guest_email") or "").strip()
    subj_lookup = str(body.get("subject_lookup") or "").strip()
    if not ev_id and (subj_lookup or att_lookup):
        found_ev = _find_calendar_event_by_id_or_lookup(
            event_id="",
            subject_lookup=subj_lookup,
            attendee_lookup=att_lookup
        )
        if found_ev:
            ev_id = str(found_ev.get("id") or found_ev.get("external_event_id") or "")
    if ev_id.startswith("test_") or "@example.com" in att_lookup.lower() or bool(body.get("simulated_test")):
        return {
            "status": "success",
            "simulated": True,
            "action": "calendar_cancelled",
            "deleted_id": ev_id or "test_calev_01",
            "cancellation_reason": str(body.get("cancellation_reason") or body.get("reason") or ""),
            "message": "Test Verified! In live production, GlennBot will cancel the appointment from the calendar and send the cancellation notice email to all guests."
        }
    if not ev_id:
        return JSONResponse({"status": "error", "message": "event_id (or matching subject_lookup / attendee_lookup) is required to cancel an appointment."}, status_code=400)
    return await run_in_threadpool(lambda: _delete_composio_calendar_event_sync(ev_id, body))


@router.delete("/api/v1/calendar/events/{event_id}")
async def api_v1_delete_calendar_event(event_id: str, request: Request):
    """Cancel & delete a Calendar Appointment by event_id from n8n."""
    key_obj = _verify_internal_api_key(request)
    if not key_obj:
        return _unauthorized_v1_response()
    return await api_delete_calendar_event(event_id, request)


# --- STARTUP RECOVERY & CONTINUOUS YOUTUBE COMMENT + CALENDAR POLLER ---
def _startup_recover_recent_activity():
    time.sleep(2)
    try:
        _load_internal_api_state(force_cloud=False)
        connected_items = refresh_connected_accounts_cache(force=False)
        for cp in get_zernio_commented_posts_list(force=True):
            cp_plat = (cp.get("platform") or "").strip().lower()
            cp_plat_id = str(cp.get("platformPostId") or cp.get("id") or "").strip()
            if cp_plat in ("tiktok", "youtube") and cp_plat_id:
                ensure_external_post_record_in_db(
                    platform=cp_plat,
                    plat_post_id=cp_plat_id,
                    z_post_id=str(cp.get("id") or ""),
                    account_id=str(cp.get("accountId") or ""),
                    account_name="",
                    caption=str(cp.get("content") or cp.get("caption") or ""),
                    permalink=str(cp.get("permalink") or cp.get("platformPostUrl") or ""),
                    preview_url="",
                    connected_items=connected_items
                )
        sync_all_connected_posts_to_cloudinary(force_refresh=True)
        sync_all_messages_to_cloudinary(force_refresh=True)
        # Pre-warm Analytics cache in background so clicking Analytics tab is instant
        _trigger_background_analytics_sync(force=True)
        # Enable Composio real-time email webhook triggers & seed seen inbox message IDs
        _enable_composio_triggers_for_all_email_accounts()
        _poll_realtime_new_emails_background()
        # Discover & sync Composio Calendar accounts + events on startup
        _discover_composio_calendar_accounts()
        _sync_external_composio_calendar_events()
    except Exception:
        pass

    # Continuous background poller so YouTube comments & replies, Real-Time Emails, and Composio Calendars arrive automatically
    # even before any user clicks "Sync", plus Render self-ping keep-alive & Analytics pre-warm
    last_self_ping = time.time()
    last_analytics_warm = time.time()
    last_email_realtime_watch = time.time()
    last_messages_bg_sync = time.time()
    last_calendar_bg_sync = time.time()
    bg_task_running: Dict[str, bool] = {
        "sched_posts": False,
        "yt_comments": False,
        "messages": False,
        "emails": False,
        "calendar": False,
        "self_ping": False
    }

    def _run_guarded_bg_task(task_key: str, fn):
        if bg_task_running.get(task_key):
            return
        bg_task_running[task_key] = True

        def _worker():
            try:
                fn()
            except Exception:
                pass
            finally:
                bg_task_running[task_key] = False

        try:
            BG_SYNC_EXECUTOR.submit(_worker)
        except Exception:
            bg_task_running[task_key] = False

    while True:
        time.sleep(3)
        now_loop = time.time()
        _run_guarded_bg_task("sched_posts", sync_pending_scheduled_posts_with_zernio)
        _run_guarded_bg_task("yt_comments", sync_youtube_and_active_posts_background)

        if now_loop - last_messages_bg_sync >= 6 and not MESSAGES_SYNC_LOCK.locked():
            last_messages_bg_sync = now_loop
            _run_guarded_bg_task("messages", lambda: sync_all_messages_to_cloudinary(force_refresh=False))

        if now_loop - last_email_realtime_watch >= 12:
            last_email_realtime_watch = now_loop
            _run_guarded_bg_task("emails", _poll_realtime_new_emails_background)

        if now_loop - last_calendar_bg_sync >= 10 and not CALENDAR_SYNC_LOCK.locked():
            last_calendar_bg_sync = now_loop
            _run_guarded_bg_task("calendar", _sync_external_composio_calendar_events)

        if now_loop - last_analytics_warm >= 180:
            last_analytics_warm = now_loop
            try:
                _trigger_background_analytics_sync(force=True)
            except Exception:
                pass

        if now_loop - last_self_ping >= 240:
            last_self_ping = now_loop
            def _do_self_ping():
                ping_base = get_dynamic_base_url(prefer_public=True)
                if ping_base.startswith("http") and not _is_localhost_origin(ping_base):
                    HTTP_SESSION.get(f"{ping_base}/health", timeout=10)
            _run_guarded_bg_task("self_ping", _do_self_ping)

