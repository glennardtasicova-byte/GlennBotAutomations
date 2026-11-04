import os
import re
import sys
import json
import time
import hashlib
import threading
import mimetypes
import urllib.parse
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
import pytz
import requests
from sqlalchemy import text

from core.config import (
    HTTP_SESSION,
    ENV_EXTERNAL_API_KEY,
    ZERNIO_BASE_URL,
    MAX_ACCOUNTS_PER_EXTERNAL_API,
    TEXTBEE_API_KEY,
    TEXTBEE_SIM_SUBSCRIPTION_ID,
    TEXTBEE_ACCOUNT_ID,
)
from core.database import (
    db_engine,
    update_post_status,
    _normalize_social_page_name,
    _strip_social_page_punctuation,
    _extract_social_page_segments,
    _is_same_social_page_name,
    _does_zernio_account_match_page,
)
from services.gdrive_service import (
    is_gdrive_authorized,
    gdrive_get_access_token,
    extract_gdrive_file_id_from_url,
)
from services.cloudinary_service import (
    _mask_api_key,
    EXTERNAL_KEYS_STATE,
    get_all_external_key_records,
    get_all_zernio_keys,
    fetch_tikwm_video_metadata,
)

# --- IN-MEMORY CACHING ---
CONNECTED_ACCOUNTS_CACHE: Dict[str, Any] = {
    "last_fetched": 0.0,
    "items": [],
    "raw_tokens": {},
    "zernio_key_by_account": {}
}
ZERNIO_ACCOUNTS_CACHE: Dict[str, Any] = {
    "last_fetched": 0.0,
    "accounts": [],
    "accounts_by_key": {},
    "had_fetch_error": False
}
ZERNIO_POSTS_CACHE: Dict[str, Any] = {
    "last_fetched": 0.0,
    "posts_map": {},
    "posts_list": []
}
ZERNIO_COMMENTED_POSTS_CACHE: Dict[str, Any] = {
    "last_fetched": 0.0,
    "items": []
}
LIVE_DETAILS_CACHE: Dict[str, Any] = {}
LAST_UPLOAD_HEARTBEAT_TS: Dict[str, float] = {}


def _format_bytes_label(num_bytes: int) -> str:
    b = max(0, int(num_bytes or 0))
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024.0 ** 3):.2f} GB"
    if b >= 1024 * 1024:
        return f"{b / (1024.0 ** 2):.1f} MB"
    if b >= 1024:
        return f"{b / 1024.0:.1f} KB"
    return f"{b} B"


def _resolve_runtime_helper(func_name: str):
    for mod_name in ("main", "routers.scheduler_routes"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            fn = getattr(mod, func_name, None)
            if callable(fn):
                return fn
    return None


def extract_list_from_api_payload(payload: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("conversations", "messages", "threads", "chats", "comments", "posts", "accounts", "profiles", "data", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return val
            elif isinstance(val, dict):
                for subkey in ("conversations", "messages", "threads", "chats", "comments", "posts", "accounts", "profiles", "data", "items", "results"):
                    subval = val.get(subkey)
                    if isinstance(subval, list):
                        return subval
    return None


def get_zernio_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    key_to_use = (api_key or get_active_zernio_key()).strip()
    return {
        "Authorization": f"Bearer {key_to_use}",
        "Content-Type": "application/json"
    }


def fetch_zernio_connected_accounts(platform: Optional[str] = None, force: bool = False) -> List[Dict[str, Any]]:
    all_keys = get_all_zernio_keys()
    if not all_keys:
        ZERNIO_ACCOUNTS_CACHE["accounts"] = []
        ZERNIO_ACCOUNTS_CACHE["accounts_by_key"] = {}
        ZERNIO_ACCOUNTS_CACHE["had_fetch_error"] = False
        return []
    now_ts = time.time()
    if not force and ZERNIO_ACCOUNTS_CACHE["accounts"] and (now_ts - ZERNIO_ACCOUNTS_CACHE["last_fetched"] < 45):
        all_accs = ZERNIO_ACCOUNTS_CACHE["accounts"]
    else:
        merged_accs = []
        prev_by_key: Dict[str, List[Dict[str, Any]]] = ZERNIO_ACCOUNTS_CACHE.get("accounts_by_key") or {}
        by_key: Dict[str, List[Dict[str, Any]]] = {}
        seen_acc_keys = set()
        any_error = False

        def _fetch_accs_for_key(k: str):
            try:
                res = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/accounts", headers=get_zernio_headers(k), timeout=25).json()
                return k, extract_list_from_api_payload(res) or [], False
            except Exception as e:
                print(f"[⚠️ EXTERNAL API ACCOUNTS TIMEOUT/RETRY ({_mask_api_key(k)})]: Using cached accounts ({e})")
                return k, prev_by_key.get(k, []), True

        with ThreadPoolExecutor(max_workers=max(1, len(all_keys))) as ex:
            futures = [ex.submit(_fetch_accs_for_key, k) for k in all_keys]
            for fut in as_completed(futures):
                k, k_accs, had_err = fut.result()
                if had_err:
                    any_error = True
                by_key[k] = []
                for a in k_accs:
                    if not isinstance(a, dict) or a.get("enabled", True) is False:
                        continue
                    aid = str(a.get("_id") or a.get("id") or "")
                    plat_aid = str(a.get("platformAccountId") or a.get("platformId") or a.get("pageId") or "")
                    a_copy = dict(a)
                    a_copy["_zernio_api_key"] = k
                    by_key[k].append(a_copy)
                    if aid:
                        CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][aid] = k
                    if plat_aid:
                        CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][plat_aid] = k
                    dedup_pair = f"{aid}_{k}"
                    if aid and dedup_pair not in seen_acc_keys:
                        seen_acc_keys.add(dedup_pair)
                        merged_accs.append(a_copy)

        ZERNIO_ACCOUNTS_CACHE["accounts"] = merged_accs
        ZERNIO_ACCOUNTS_CACHE["accounts_by_key"] = by_key
        ZERNIO_ACCOUNTS_CACHE["had_fetch_error"] = any_error
        ZERNIO_ACCOUNTS_CACHE["last_fetched"] = now_ts
        all_accs = merged_accs

    if platform:
        plat_lower = platform.strip().lower()
        return [a for a in all_accs if (a.get("platform") or "").strip().lower() == plat_lower and a.get("enabled", True) is not False]
    return [a for a in all_accs if a.get("enabled", True) is not False]


def evaluate_external_api_pool_status(force_refresh: bool = False) -> List[Dict[str, Any]]:
    fetch_zernio_connected_accounts(force=force_refresh)
    by_key = ZERNIO_ACCOUNTS_CACHE.get("accounts_by_key") or {}
    records = get_all_external_key_records()
    preferred = (EXTERNAL_KEYS_STATE.get("preferred_active_key") or "").strip()

    evaluated = []
    active_slot_assigned = False

    for idx, rec in enumerate(records):
        k = rec["api_key"]
        k_accs = by_key.get(k) or []
        count = len(k_accs)
        acc_names = []
        for a in k_accs:
            nm = a.get("displayName") or a.get("name") or a.get("username") or a.get("platform") or "Account"
            plat = (a.get("platform") or "").upper()
            acc_names.append(f"{plat}: {nm}" if plat else str(nm))

        is_full = count >= MAX_ACCOUNTS_PER_EXTERNAL_API
        is_current_slot = False

        if not is_full and not active_slot_assigned:
            is_current_slot = True
            active_slot_assigned = True

        if preferred and k == preferred and not is_full:
            is_current_slot = True

        if count > 0 or is_current_slot or rec.get("is_env") or rec.get("forced_in_use"):
            status_tag = "In use"
        else:
            status_tag = "Buffer"

        evaluated.append({
            "id": rec["id"],
            "api_key": k,
            "masked_key": _mask_api_key(k),
            "is_env": rec["is_env"],
            "added_at": rec["added_at"],
            "connected_count": count,
            "max_limit": MAX_ACCOUNTS_PER_EXTERNAL_API,
            "is_full": is_full,
            "is_current_slot": is_current_slot,
            "status": status_tag,
            "account_names": acc_names,
            "order_index": idx + 1
        })

    return evaluated


def get_active_zernio_key() -> str:
    records = get_all_external_key_records()
    if not records:
        return ""
    by_key = ZERNIO_ACCOUNTS_CACHE.get("accounts_by_key") or {}
    preferred = (EXTERNAL_KEYS_STATE.get("preferred_active_key") or "").strip()

    if preferred:
        pref_accs = by_key.get(preferred)
        if pref_accs is not None and len(pref_accs) < MAX_ACCOUNTS_PER_EXTERNAL_API:
            return preferred

    for r in records:
        k = r["api_key"]
        if k in by_key and len(by_key[k]) < MAX_ACCOUNTS_PER_EXTERNAL_API:
            return k

    return records[0]["api_key"]


def get_zernio_default_profile_id(api_key: Optional[str] = None) -> Dict[str, Any]:
    key_to_use = (api_key or get_active_zernio_key()).strip()
    if not key_to_use:
        return {"profile_id": None, "error": "No External API Key configured. Click 'Manage API' to add one."}
    try:
        headers = get_zernio_headers(key_to_use)
        resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/profiles", headers=headers, timeout=20)
        res = resp.json() if resp.text else {}

        if resp.status_code in (401, 403):
            err_msg = (res.get("error") if isinstance(res.get("error"), str) else (res.get("error") or {}).get("message")) or res.get("message") or "Invalid or exhausted External API Key."
            return {"profile_id": None, "error": f"Could not retrieve or create an External API profile ({err_msg})."}

        profiles = extract_list_from_api_payload(res) or []
        if profiles:
            for p in profiles:
                if isinstance(p, dict) and p.get("isDefault") and (p.get("_id") or p.get("id")):
                    return {"profile_id": str(p.get("_id") or p.get("id")), "error": ""}
            first_id = profiles[0].get("_id") or profiles[0].get("id") if isinstance(profiles[0], dict) else None
            if first_id:
                return {"profile_id": str(first_id), "error": ""}

        create_resp = HTTP_SESSION.post(
            f"{ZERNIO_BASE_URL}/profiles",
            headers=headers,
            json={"name": "GlennBot Default"},
            timeout=20
        )
        create_res = create_resp.json() if create_resp.text else {}
        prof_obj = create_res.get("profile") or create_res.get("data") or create_res
        if isinstance(prof_obj, dict) and (prof_obj.get("_id") or prof_obj.get("id")):
            return {"profile_id": str(prof_obj.get("_id") or prof_obj.get("id")), "error": ""}

        err_detail = create_res.get("message") or create_res.get("error") or res.get("message") or "Maximum account/profile limit reached on this External API key."
        return {"profile_id": None, "error": f"Could not retrieve or create an External API profile: {err_detail}"}
    except Exception as e:
        return {"profile_id": None, "error": f"Could not retrieve or create an External API profile ({e})."}


def _collect_valid_account_ids_for_page(
    platform: str,
    page_id: str = "",
    account_name: str = "",
    stored_z_acc_id: str = ""
) -> set:
    plat_clean = (platform or "").strip().lower()
    valid_ids = {str(x or "").strip() for x in (page_id, stored_z_acc_id) if str(x or "").strip()}
    try:
        for acc in refresh_connected_accounts_cache(force=False):
            if not isinstance(acc, dict):
                continue
            if plat_clean and (acc.get("platform") or "").strip().lower() != plat_clean:
                continue
            a_id = str(acc.get("account_id") or "").strip()
            a_name = str(acc.get("account_name") or "").strip()
            a_uname = str(acc.get("username") or "").strip()
            if (a_id and a_id in valid_ids) or (account_name and (_is_same_social_page_name(account_name, a_name) or _is_same_social_page_name(account_name, a_uname))):
                if a_id:
                    valid_ids.add(a_id)
    except Exception:
        pass
    try:
        for za in fetch_zernio_connected_accounts(platform=plat_clean or None, force=False):
            if _does_zernio_account_match_page(za, page_id, stored_z_acc_id, account_name):
                for id_f in ("_id", "id", "platformAccountId", "platformId", "pageId"):
                    v = str(za.get(id_f) or "").strip()
                    if v:
                        valid_ids.add(v)
    except Exception:
        pass
    return valid_ids


def get_zernio_key_for_account(account_id: str, account_name: str = "", platform: str = "") -> str:
    aid = str(account_id or "").strip()
    plat_clean = (platform or "").strip().lower()
    valid_keys = set(get_all_zernio_keys())

    refresh_connected_accounts_cache(force=False)
    if aid:
        mapped_key = CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"].get(aid)
        if mapped_key and mapped_key in valid_keys:
            return mapped_key

        raw_tok = CONNECTED_ACCOUNTS_CACHE["raw_tokens"].get(aid, "")
        for prefix in ("EXTERNAL_API_MANAGED:", "ZERNIO_MANAGED:"):
            if raw_tok.startswith(prefix):
                extracted = raw_tok.split(prefix, 1)[1].strip()
                if extracted and extracted in valid_keys:
                    return extracted

    # Check Supabase connected accounts cache by ID or Unicode-normalized Page Name
    for acc in (CONNECTED_ACCOUNTS_CACHE.get("items") or []):
        if not isinstance(acc, dict):
            continue
        if plat_clean and (acc.get("platform") or "").strip().lower() != plat_clean:
            continue
        c_aid = str(acc.get("account_id") or "").strip()
        c_aname = str(acc.get("account_name") or "").strip()
        c_uname = str(acc.get("username") or "").strip()
        if (aid and c_aid == aid) or (account_name and (_is_same_social_page_name(account_name, c_aname) or _is_same_social_page_name(account_name, c_uname))):
            if c_aid:
                mapped_k = CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"].get(c_aid)
                if mapped_k and mapped_k in valid_keys:
                    return mapped_k
            raw_t = str(acc.get("access_token") or "").strip()
            for prefix in ("EXTERNAL_API_MANAGED:", "ZERNIO_MANAGED:"):
                if raw_t.startswith(prefix):
                    ext_k = raw_t.split(prefix, 1)[1].strip()
                    if ext_k and ext_k in valid_keys:
                        if c_aid:
                            CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][c_aid] = ext_k
                        if aid:
                            CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][aid] = ext_k
                        return ext_k

    # Check live Zernio accounts (first cached, then force=True if not found in cache)
    for force_flag in (False, True):
        z_accs = fetch_zernio_connected_accounts(platform=plat_clean or None, force=force_flag)
        # Pass A: Exact ID match
        if aid:
            for a in z_accs:
                a_id = str(a.get("_id") or a.get("id") or "").strip()
                a_plat_id = str(a.get("platformAccountId") or a.get("platformId") or a.get("pageId") or "").strip()
                k_cand = (a.get("_zernio_api_key") or "").strip()
                if k_cand and k_cand in valid_keys and aid in (a_id, a_plat_id):
                    return k_cand
        # Pass B: Unicode-safe Page Name / Username match
        if account_name:
            for a in z_accs:
                k_cand = (a.get("_zernio_api_key") or "").strip()
                if k_cand and k_cand in valid_keys and _does_zernio_account_match_page(a, "", "", account_name):
                    return k_cand

    return get_active_zernio_key()


def get_candidate_zernio_keys_for_account(account_id: str, preferred_key: str = "", account_name: str = "", platform: str = "") -> List[str]:
    valid_keys = set(get_all_zernio_keys())
    ordered = []
    owner_key = get_zernio_key_for_account(account_id, account_name=account_name, platform=platform)
    if owner_key and owner_key in valid_keys:
        ordered.append(owner_key)

    if preferred_key and preferred_key.strip() in valid_keys and preferred_key.strip() not in ordered:
        ordered.append(preferred_key.strip())

    for k in get_all_zernio_keys():
        if k and k not in ordered:
            ordered.append(k)
    return ordered


def resolve_zernio_account_id(platform: str, page_id: str, account_name: str = "") -> str:
    pid = str(page_id or "").strip()
    plat_clean = (platform or "").strip().lower()

    for force_flag in (False, True):
        z_accs = fetch_zernio_connected_accounts(platform=plat_clean or None, force=force_flag)
        if pid:
            for a in z_accs:
                aid = str(a.get("_id") or a.get("id") or "").strip()
                plat_aid = str(a.get("platformAccountId") or a.get("platformId") or a.get("pageId") or "").strip()
                if pid == aid or (plat_aid and pid == plat_aid):
                    return aid

        if account_name:
            for a in z_accs:
                aid = str(a.get("_id") or a.get("id") or "").strip()
                if aid and _does_zernio_account_match_page(a, "", "", account_name):
                    return aid

    return pid


def resolve_live_zernio_account_and_key_pairs(
    platform: str,
    account_id: str,
    account_name: str = "",
    stored_z_acc_id: str = "",
    preferred_key: str = ""
) -> List[Dict[str, str]]:
    """
    Finds the exact (api_key, zernio_account_id) pair(s) from the multi-key Cloudinary pool
    that actually own the target social media page. Prevents sending a page's accountId
    with another page's API key or sending from a different Facebook Page.
    """
    plat_clean = (platform or "").strip().lower()
    aid_clean = str(account_id or "").strip()
    stored_clean = str(stored_z_acc_id or "").strip()
    valid_keys = set(get_all_zernio_keys())

    matched_pairs: List[Dict[str, str]] = []
    seen_pairs = set()

    def _add_pair(k: str, z_id: str):
        k_s = (k or "").strip()
        z_s = (z_id or "").strip()
        if k_s and z_s and k_s in valid_keys:
            pair_key = f"{k_s}::{z_s}"
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                matched_pairs.append({"api_key": k_s, "account_id": z_s})

    # Collect all known IDs for this specific page from Supabase glennbot_connected_accounts
    known_page_ids = {x for x in (aid_clean, stored_clean) if x}
    bound_supabase_key = ""
    try:
        for acc in refresh_connected_accounts_cache(force=False):
            if not isinstance(acc, dict):
                continue
            if plat_clean and (acc.get("platform") or "").strip().lower() != plat_clean:
                continue
            c_aid = str(acc.get("account_id") or "").strip()
            c_aname = str(acc.get("account_name") or "").strip()
            c_uname = str(acc.get("username") or "").strip()
            if (c_aid and c_aid in known_page_ids) or (account_name and (_is_same_social_page_name(account_name, c_aname) or _is_same_social_page_name(account_name, c_uname))):
                if c_aid:
                    known_page_ids.add(c_aid)
                raw_t = str(acc.get("access_token") or "").strip()
                for prefix in ("EXTERNAL_API_MANAGED:", "ZERNIO_MANAGED:"):
                    if raw_t.startswith(prefix):
                        k_ext = raw_t.split(prefix, 1)[1].strip()
                        if k_ext in valid_keys:
                            bound_supabase_key = k_ext
    except Exception:
        pass

    for force_flag in (False, True):
        z_accs = fetch_zernio_connected_accounts(platform=plat_clean or None, force=force_flag)
        # 1. Exact ID match (_id, id, platformAccountId, pageId)
        for a in z_accs:
            z_id = str(a.get("_id") or a.get("id") or "").strip()
            plat_aid = str(a.get("platformAccountId") or a.get("platformId") or a.get("pageId") or "").strip()
            k_cand = str(a.get("_zernio_api_key") or "").strip()
            if not z_id or not k_cand:
                continue
            if known_page_ids & {x for x in (z_id, plat_aid) if x}:
                _add_pair(k_cand, z_id)

        # 2. Match by Unicode-normalized Social Media Page Name / Username
        if account_name:
            for a in z_accs:
                z_id = str(a.get("_id") or a.get("id") or "").strip()
                k_cand = str(a.get("_zernio_api_key") or "").strip()
                if not z_id or not k_cand:
                    continue
                if _does_zernio_account_match_page(a, "", "", account_name):
                    _add_pair(k_cand, z_id)

        if matched_pairs:
            break

    # Fallback if live accounts check had a network hiccup: use ONLY this page's bound key (never all keys from other pages)
    if not matched_pairs:
        fallback_z_id = resolve_zernio_account_id(plat_clean, aid_clean or stored_clean, account_name)
        owner_key = bound_supabase_key or get_zernio_key_for_account(fallback_z_id, account_name=account_name, platform=plat_clean)
        cand_keys = [k for k in (owner_key, preferred_key) if k and k.strip() in valid_keys]
        if not cand_keys:
            cand_keys = get_candidate_zernio_keys_for_account(fallback_z_id, preferred_key=preferred_key, account_name=account_name, platform=plat_clean)
        for ck in cand_keys:
            for cid in (fallback_z_id, stored_clean, aid_clean):
                if cid:
                    _add_pair(ck, cid)

    return matched_pairs


def refresh_connected_accounts_cache(force: bool = False) -> List[Dict[str, Any]]:
    now_ts = time.time()
    if not force and (now_ts - CONNECTED_ACCOUNTS_CACHE["last_fetched"] < 15):
        return CONNECTED_ACCOUNTS_CACHE["items"]
    try:
        active_valid_keys = set(get_all_zernio_keys())
        live_zernio_accs = fetch_zernio_connected_accounts(force=force)
        had_fetch_error = ZERNIO_ACCOUNTS_CACHE.get("had_fetch_error", False)

        valid_live_acc_ids = set()
        live_key_map = {}
        for za in live_zernio_accs:
            if not isinstance(za, dict):
                continue
            z_k = za.get("_zernio_api_key") or ""
            for id_field in ("_id", "id", "platformAccountId", "platformId", "pageId"):
                val = str(za.get(id_field) or "").strip()
                if val:
                    valid_live_acc_ids.add(val)
                    if z_k:
                        live_key_map[val] = z_k

        stale_row_ids = []
        items = []
        raw_toks = {}

        with db_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, platform, account_id, account_name, username, avatar_url, access_token, connected_by, created_at
                FROM glennbot_connected_accounts
                ORDER BY created_at ASC
            """)).mappings().all()

            for r in rows:
                d = dict(r)
                row_id = str(d.get("id") or "")
                acc_id = str(d.get("account_id") or "").strip()
                raw_tok = (d.get("access_token") or "").strip()

                bound_key = ""
                for prefix in ("EXTERNAL_API_MANAGED:", "ZERNIO_MANAGED:"):
                    if raw_tok.startswith(prefix):
                        bound_key = raw_tok.split(prefix, 1)[1].strip()
                        break

                is_textbee_sms_row = (
                    str(d.get("platform") or "").strip().lower() == "sms"
                    or acc_id == TEXTBEE_ACCOUNT_ID
                    or raw_tok.startswith("TEXTBEE_API_MANAGED")
                )
                if is_textbee_sms_row:
                    if TEXTBEE_API_KEY:
                        items.append(d)
                        raw_toks[acc_id] = raw_tok
                    elif row_id:
                        stale_row_ids.append(row_id)
                    continue

                is_old_meta_row = not (raw_tok.startswith("EXTERNAL_API_MANAGED") or raw_tok.startswith("ZERNIO_MANAGED"))
                is_deleted_key = bool(bound_key and bound_key not in active_valid_keys)
                is_not_in_live_pool = bool(not had_fetch_error and valid_live_acc_ids and acc_id not in valid_live_acc_ids)

                if not active_valid_keys or is_old_meta_row or is_deleted_key or is_not_in_live_pool:
                    if row_id:
                        stale_row_ids.append(row_id)
                    continue

                items.append(d)
                if acc_id:
                    raw_toks[acc_id] = raw_tok
                    resolved_k = bound_key or live_key_map.get(acc_id, "")
                    if resolved_k:
                        CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][acc_id] = resolved_k

        # Auto-enroll any live WhatsApp or Telegram accounts linked on active Zernio API keys
        # so they are immediately available in Messages and Contacts without extra manual steps
        existing_acc_ids = {str(it.get("account_id") or "").strip() for it in items}
        new_auto_enrolled = []
        for za in live_zernio_accs:
            if not isinstance(za, dict) or za.get("enabled", True) is False:
                continue
            z_plat = (za.get("platform") or "").strip().lower()
            if z_plat not in ("whatsapp", "telegram"):
                continue
            z_aid = str(za.get("_id") or za.get("id") or "").strip()
            if not z_aid or z_aid in existing_acc_ids:
                continue
            z_uname = (za.get("username") or za.get("phoneNumber") or za.get("phone") or za.get("displayName") or z_plat).strip().lstrip("@")
            z_dname = (za.get("displayName") or za.get("name") or z_uname or z_aid).strip()
            z_avatar = (za.get("avatarUrl") or za.get("profilePictureUrl") or "").strip()
            z_key = (za.get("_zernio_api_key") or get_active_zernio_key()).strip()
            tok_val = f"EXTERNAL_API_MANAGED:{z_key}" if z_key else "EXTERNAL_API_MANAGED"
            row_id = f"{z_plat}_{z_aid}"
            new_row = {
                "id": row_id,
                "platform": z_plat,
                "account_id": z_aid,
                "account_name": z_dname,
                "username": z_uname,
                "avatar_url": z_avatar,
                "access_token": tok_val,
                "connected_by": "External API"
            }
            new_auto_enrolled.append(new_row)
            existing_acc_ids.add(z_aid)
            items.append(new_row)
            raw_toks[z_aid] = tok_val
            if z_key:
                CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"][z_aid] = z_key

        # Auto-enroll TextBee.dev SMS Gateway (SIM 2) when TEXTBEE_API_KEY is configured
        if TEXTBEE_API_KEY and TEXTBEE_ACCOUNT_ID not in existing_acc_ids:
            tb_sim = str(TEXTBEE_SIM_SUBSCRIPTION_ID or "2").strip()
            tb_tok = f"TEXTBEE_API_MANAGED:{TEXTBEE_API_KEY}"
            tb_row = {
                "id": f"sms_{TEXTBEE_ACCOUNT_ID}",
                "platform": "sms",
                "account_id": TEXTBEE_ACCOUNT_ID,
                "account_name": f"TextBee SMS (SIM {tb_sim})",
                "username": f"SIM {tb_sim} • TextBee.dev",
                "avatar_url": "",
                "access_token": tb_tok,
                "connected_by": "TextBee.dev API"
            }
            new_auto_enrolled.append(tb_row)
            existing_acc_ids.add(TEXTBEE_ACCOUNT_ID)
            items.append(tb_row)
            raw_toks[TEXTBEE_ACCOUNT_ID] = tb_tok

        if new_auto_enrolled:
            try:
                with db_engine.begin() as conn:
                    for nr in new_auto_enrolled:
                        conn.execute(
                            text("""
                                INSERT INTO glennbot_connected_accounts
                                (id, platform, account_id, account_name, username, avatar_url, access_token, connected_by)
                                VALUES (:id, :plat, :aid, :aname, :uname, :avatar, :tok, :cby)
                                ON CONFLICT (id) DO UPDATE SET
                                    account_name = EXCLUDED.account_name,
                                    username = EXCLUDED.username,
                                    access_token = EXCLUDED.access_token
                            """),
                            {
                                "id": nr["id"],
                                "plat": nr["platform"],
                                "aid": nr["account_id"],
                                "aname": nr["account_name"],
                                "uname": nr["username"],
                                "avatar": nr["avatar_url"],
                                "tok": nr["access_token"],
                                "cby": nr["connected_by"]
                            }
                        )
            except Exception as e:
                print(f"[⚠️ AUTO-ENROLL WHATSAPP/TELEGRAM WARNING]: {e}")

        if stale_row_ids:
            with db_engine.begin() as conn:
                for s_id in stale_row_ids:
                    conn.execute(
                        text("DELETE FROM glennbot_connected_accounts WHERE id = :id"),
                        {"id": s_id}
                    )
            print(f"[🧹 STRICT AUTO-CLEANUP] Automatically removed {len(stale_row_ids)} stale/disconnected account(s) from Supabase.")

        CONNECTED_ACCOUNTS_CACHE["items"] = items
        CONNECTED_ACCOUNTS_CACHE["raw_tokens"] = raw_toks
        CONNECTED_ACCOUNTS_CACHE["last_fetched"] = now_ts
        return items
    except Exception as e:
        print(f"[⚠️ CONNECTED ACCOUNTS CACHE ERROR]: {e}")
        return CONNECTED_ACCOUNTS_CACHE["items"]


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


# ==============================================================================
# --- ZERNIO NATIVE PRESIGNED MEDIA CLOUD ENGINE (UP TO 5GB / 4GB FACEBOOK) ---
# ==============================================================================
def _detect_attachment_media_category(filename: str = "", raw_content_type: str = "", fallback_type: str = "file") -> str:
    ct = (raw_content_type or "").strip().lower()
    ext = os.path.splitext(filename or "")[1].lower()
    if ct.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        return "image"
    if ct.startswith("video/") or ext in (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg"):
        return "video"
    if ct.startswith("audio/") or ext in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"):
        return "audio"
    if fallback_type in ("image", "video", "audio", "file"):
        return fallback_type
    return "file"


def _normalize_zernio_content_type(filename: str, raw_content_type: str = "", media_type: str = "video") -> str:
    ct = (raw_content_type or "").strip().lower()
    ext = os.path.splitext(filename or "")[1].lower()
    accepted_video = {"video/mp4", "video/quicktime", "video/webm", "video/mpeg", "video/avi", "video/x-msvideo"}
    accepted_image = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
    accepted_audio = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/mp4", "audio/aac", "audio/webm"}

    if media_type == "image" or ct.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if ct == "image/jpg":
            return "image/jpeg"
        if ct in accepted_image:
            return ct
        if ext == ".png":
            return "image/png"
        if ext == ".webp":
            return "image/webp"
        if ext == ".gif":
            return "image/gif"
        return "image/jpeg"

    if media_type == "audio" or ct.startswith("audio/") or ext in (".mp3", ".wav", ".ogg", ".m4a", ".aac"):
        if ct in accepted_audio:
            return "audio/mpeg" if ct == "audio/mp3" else ct
        if ext == ".wav":
            return "audio/wav"
        if ext == ".ogg":
            return "audio/ogg"
        if ext in (".m4a", ".aac"):
            return "audio/mp4"
        return "audio/mpeg"

    if media_type == "file" or (
        media_type not in ("video", "image", "audio")
        and not ct.startswith("video/")
        and ext not in ("", ".mp4", ".mov", ".webm", ".mpg", ".mpeg", ".avi", ".mkv", ".m4v")
    ):
        if ct and "/" in ct and not ct.startswith("video/"):
            return ct
        guessed_ct, _ = mimetypes.guess_type(filename or "")
        if guessed_ct:
            return guessed_ct
        if ext == ".json":
            return "application/json"
        if ext == ".pdf":
            return "application/pdf"
        if ext == ".txt":
            return "text/plain"
        if ext == ".csv":
            return "text/csv"
        if ext == ".zip":
            return "application/zip"
        return "application/octet-stream"

    if ct in accepted_video:
        return ct
    if ext == ".mov":
        return "video/quicktime"
    if ext == ".webm":
        return "video/webm"
    if ext in (".mpg", ".mpeg"):
        return "video/mpeg"
    if ext == ".avi":
        return "video/avi"
    return "video/mp4"


def get_zernio_presigned_upload_target(
    filename: str,
    content_type: str = "video/mp4",
    file_size: int = 0,
    platform: str = "",
    account_id: str = "",
    explicit_api_key: str = "",
    media_type: str = ""
) -> Dict[str, str]:
    """
    Calls Zernio's official POST /v1/media/presign endpoint to obtain a direct-to-cloud
    presigned PUT uploadUrl (supports up to 5GB) and a publicUrl (https://media.zernio.com/temp/...).
    Using Zernio's native media cloud enables Zernio's resumable upload pipeline for >1GB Facebook videos (up to 4GB).
    """
    api_key = (explicit_api_key or "").strip()
    if not api_key and (platform or account_id):
        try:
            resolved_acc = resolve_zernio_account_id(platform, account_id)
            api_key = get_zernio_key_for_account(resolved_acc, platform=platform)
        except Exception:
            api_key = ""
    if not api_key:
        all_keys = get_all_zernio_keys()
        api_key = all_keys[0] if all_keys else ENV_EXTERNAL_API_KEY
    if not api_key:
        return {"upload_url": "", "public_url": "", "key": "", "content_type": content_type}

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", os.path.basename(filename or "video.mp4"))
    inferred_mtype = (media_type or "").strip().lower() or _detect_attachment_media_category(safe_name, content_type, fallback_type="video")
    if "." not in safe_name:
        if inferred_mtype == "image":
            safe_name = f"{safe_name}.jpg"
        elif inferred_mtype == "video":
            safe_name = f"{safe_name}.mp4"
    norm_ct = _normalize_zernio_content_type(safe_name, content_type, inferred_mtype)

    payload: Dict[str, Any] = {
        "filename": safe_name,
        "contentType": norm_ct
    }
    if file_size and int(file_size) > 0:
        payload["size"] = int(file_size)

    try:
        resp = HTTP_SESSION.post(
            f"{ZERNIO_BASE_URL}/media/presign",
            headers=get_zernio_headers(api_key),
            json=payload,
            timeout=25
        )
        if resp.status_code not in (200, 201) and "size" in payload:
            # Retry without optional size parameter in case a specific Zernio endpoint version only expects filename + contentType
            payload.pop("size", None)
            resp = HTTP_SESSION.post(
                f"{ZERNIO_BASE_URL}/media/presign",
                headers=get_zernio_headers(api_key),
                json=payload,
                timeout=25
            )
        if resp.status_code in (200, 201):
            data = resp.json() or {}
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            upload_url = str(inner.get("uploadUrl") or data.get("uploadUrl") or "").strip()
            public_url = str(inner.get("publicUrl") or data.get("publicUrl") or inner.get("url") or "").strip()
            key_str = str(inner.get("key") or data.get("key") or "").strip()
            if upload_url and public_url:
                return {
                    "upload_url": upload_url,
                    "public_url": public_url,
                    "key": key_str,
                    "content_type": norm_ct
                }
        else:
            print(f"[ℹ️ ZERNIO PRESIGN NOTE] /media/presign returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[⚠️ ZERNIO PRESIGN WARNING]: {e}")

    return {"upload_url": "", "public_url": "", "key": "", "content_type": norm_ct}


def upload_bytes_to_zernio_presign(
    file_bytes: bytes,
    original_filename: str,
    media_type: str = "video",
    is_thumb: bool = False,
    platform: str = "",
    account_id: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Uploads an in-memory buffer (e.g. custom thumbnail image, photo, document, or small clip) directly
    to Zernio's presigned media storage (https://media.zernio.com/temp/...).
    """
    if not file_bytes:
        return None
    safe_orig = re.sub(r"[^a-zA-Z0-9._-]", "_", os.path.basename(original_filename or ("thumb.jpg" if is_thumb else "media.mp4")))
    if is_thumb and not safe_orig.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        safe_orig = f"{safe_orig}.jpg"
    guessed_mime, _ = mimetypes.guess_type(safe_orig)
    eff_mtype = "image" if is_thumb else _detect_attachment_media_category(safe_orig, guessed_mime or "", fallback_type=(media_type or "video"))
    norm_ct = _normalize_zernio_content_type(safe_orig, guessed_mime or "", eff_mtype)

    target = get_zernio_presigned_upload_target(
        filename=safe_orig,
        content_type=norm_ct,
        file_size=len(file_bytes),
        platform=platform,
        account_id=account_id,
        media_type=eff_mtype
    )
    up_url = target.get("upload_url") or ""
    pub_url = target.get("public_url") or ""
    eff_ct = target.get("content_type") or norm_ct
    if not up_url or not pub_url:
        return None

    try:
        put_resp = requests.put(
            up_url,
            data=file_bytes,
            headers={
                "Content-Type": eff_ct,
                "Content-Length": str(len(file_bytes))
            },
            timeout=300
        )
        if put_resp.status_code in (200, 201, 204):
            print(f"[✅ ZERNIO MEDIA CLOUD UPLOADED] {safe_orig} ({round(len(file_bytes) / 1024, 1)} KB) -> {pub_url}")
            return {
                "url": pub_url,
                "public_id": target.get("key") or pub_url,
                "storage": "zernio",
                "type": eff_mtype,
                "is_thumb": bool(is_thumb)
            }
    except Exception as e:
        print(f"[⚠️ ZERNIO DIRECT PUT UPLOAD WARNING]: {e}")
    return None


def bridge_gdrive_media_to_zernio_presign(
    source_media_url: str = "",
    gdrive_file_name: str = "",
    media_type: str = "video",
    api_key: str = "",
    record_id: str = "",
    vault_file_id: str = "",
    expected_file_size: int = 0,
    platform: str = "",
    account_id: str = "",
    gdrive_file_id: str = "",
    source_url: str = "",
    filename: str = "",
    **kwargs: Any
) -> Tuple[str, str]:
    """
    Zero-RAM Streaming Bridge: Streams media stored in Google Drive ('GlennBot_Media_Vault')
    in 1 MB chunks directly into Zernio's native presigned storage (https://media.zernio.com/temp/...)
    before publishing to Facebook/Instagram/TikTok/YouTube.
    Includes a 3-attempt automatic retry loop so Render.com Free Tier socket resets never abort the transfer.
    Returns (zernio_public_url, error_hint).
    """
    u = (source_url or source_media_url or "").strip()
    eff_file_name = (filename or gdrive_file_name or "").strip()
    if u and "media.zernio.com" in u:
        return u, ""

    resolved_gdrive_id = (gdrive_file_id or "").strip()
    if "/" in resolved_gdrive_id:
        resolved_gdrive_id = ""
    if not resolved_gdrive_id and u:
        resolved_gdrive_id = extract_gdrive_file_id_from_url(u)
    if (
        not resolved_gdrive_id
        and eff_file_name
        and "/" not in eff_file_name
        and "." not in eff_file_name
        and not eff_file_name.startswith("file_")
        and len(eff_file_name) >= 15
    ):
        resolved_gdrive_id = eff_file_name.strip()

    # Fallback 1: Look up vault_file_id in FILES_VAULT_STORE if gdrive_file_id wasn't passed directly
    if not resolved_gdrive_id and vault_file_id:
        try:
            _load_vault_fn = _resolve_runtime_helper("_load_files_vault_store")
            v_store = _load_vault_fn(force_cloud=False) if _load_vault_fn else {}
            v_match = next((f for f in (v_store.get("files") or []) if str(f.get("file_id") or "") == str(vault_file_id).strip()), None)
            if v_match:
                cand_gid = str(v_match.get("gdrive_file_id") or "").strip()
                if cand_gid and "/" not in cand_gid:
                    resolved_gdrive_id = cand_gid
                if not expected_file_size and v_match.get("size_bytes"):
                    expected_file_size = int(v_match.get("size_bytes") or 0)
        except Exception:
            pass

    # Fallback 2: Search Google Drive folder by vault_file_id prefix if gdrive_file_id was not saved in an older entry
    if not resolved_gdrive_id and vault_file_id and is_gdrive_authorized():
        try:
            acc_tok_search = gdrive_get_access_token(force_refresh=False)
            safe_q_fid = str(vault_file_id).strip().replace("'", "")
            q_str = f"(appProperties has {{ key='glennbot_file_id' and value='{safe_q_fid}' }} or name contains '{safe_q_fid}') and trashed=false"
            s_resp = HTTP_SESSION.get(
                "https://www.googleapis.com/drive/v3/files",
                params={"q": q_str, "fields": "files(id,name,size)", "pageSize": 5},
                headers={"Authorization": f"Bearer {acc_tok_search}"},
                timeout=15
            )
            if s_resp.status_code == 200:
                found_files = (s_resp.json() or {}).get("files") or []
                if found_files:
                    resolved_gdrive_id = str(found_files[0].get("id") or "").strip()
                    if not expected_file_size and found_files[0].get("size"):
                        expected_file_size = int(found_files[0].get("size") or 0)
        except Exception:
            pass

    if not resolved_gdrive_id and not u.startswith("http") and not vault_file_id:
        return u, ""

    fname = os.path.basename(eff_file_name or ("video.mp4" if media_type == "video" else ("image.jpg" if media_type == "image" else "attachment.bin")))
    norm_ct = _normalize_zernio_content_type(fname, "", media_type)

    if record_id:
        LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()

    last_err = ""
    for attempt in range(3):
        req_headers: Dict[str, str] = {}
        if resolved_gdrive_id and is_gdrive_authorized():
            try:
                acc_tok = gdrive_get_access_token(force_refresh=(attempt > 0))
                stream_source_url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(resolved_gdrive_id, safe='')}?alt=media"
                req_headers["Authorization"] = f"Bearer {acc_tok}"
            except Exception as auth_err:
                last_err = str(auth_err)
                stream_source_url = u
        elif resolved_gdrive_id:
            stream_source_url = f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(resolved_gdrive_id, safe='')}"
        else:
            stream_source_url = u

        if not stream_source_url or not stream_source_url.startswith("http"):
            return "", last_err or "No valid Google Drive or HTTP source URL to stream to Zernio."

        try:
            with requests.get(stream_source_url, headers=req_headers, stream=True, timeout=90) as src_resp:
                if src_resp.status_code != 200:
                    err_body = ""
                    try:
                        err_body = src_resp.text[:250]
                    except Exception:
                        pass
                    last_err = f"Media source returned HTTP {src_resp.status_code}: {err_body}"
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue
                    return "", last_err

                content_len = int(src_resp.headers.get("Content-Length") or expected_file_size or 0)
                target = get_zernio_presigned_upload_target(
                    filename=fname,
                    content_type=norm_ct,
                    file_size=content_len,
                    platform=platform,
                    account_id=account_id,
                    explicit_api_key=api_key,
                    media_type=media_type
                )
                up_url = target.get("upload_url") or ""
                pub_url = target.get("public_url") or ""
                eff_ct = target.get("content_type") or norm_ct
                if not up_url or not pub_url or content_len <= 0:
                    last_err = "Could not obtain Zernio presigned upload target."
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    return "", last_err

                parsed_u = urllib.parse.urlparse(up_url)
                z_conn = http.client.HTTPSConnection(parsed_u.netloc, timeout=600)
                try:
                    z_path = parsed_u.path + (f"?{parsed_u.query}" if parsed_u.query else "")
                    z_conn.putrequest("PUT", z_path)
                    z_conn.putheader("Content-Type", eff_ct)
                    z_conn.putheader("Content-Length", str(content_len))
                    z_conn.endheaders()

                    bytes_streamed = 0
                    last_pct_logged = 0
                    size_human = _format_bytes_label(content_len)
                    vault_tag = f" [{vault_file_id}]" if vault_file_id else ""
                    retry_tag = f" (Retry {attempt + 1}/3)" if attempt > 0 else ""

                    for chunk in src_resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            z_conn.send(chunk)
                            bytes_streamed += len(chunk)
                            if record_id:
                                LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
                            if record_id and content_len > 0:
                                pct = min(99, max(1, int(round((bytes_streamed / float(content_len)) * 100))))
                                if pct - last_pct_logged >= 6 or pct == 99:
                                    last_pct_logged = pct
                                    update_post_status(
                                        record_id,
                                        "processing_payload",
                                        f"Processing Payload • Transferring {fname}{vault_tag} ({size_human}) from Google Drive to Zernio Cloud ({pct}%){retry_tag}..."
                                    )

                    z_put_resp = z_conn.getresponse()
                    z_put_resp.read()
                    if z_put_resp.status in (200, 201, 204):
                        print(f"[🌉 GOOGLE DRIVE -> ZERNIO CLOUD BRIDGE SUCCESS] Streamed {fname}{vault_tag} ({size_human}) -> {pub_url}")
                        return pub_url, ""
                    last_err = f"Zernio R2 PUT returned HTTP {z_put_resp.status}"
                finally:
                    try:
                        z_conn.close()
                    except Exception:
                        pass
        except Exception as e:
            last_err = str(e)
            print(f"[⚠️ GDRIVE -> ZERNIO BRIDGE WARNING (Attempt {attempt + 1}/3)]: {e}")
            if record_id:
                LAST_UPLOAD_HEARTBEAT_TS[record_id] = time.time()
            if attempt < 2:
                time.sleep(2 * (attempt + 1))

    return "", last_err


# ==============================================================================
# --- EXTERNAL API POSTING ENGINE (WITH TRUE PUBLISH & FAILURE CHECK) ---
# ==============================================================================
def _is_valid_final_permalink(permalink: str, platform: str = "") -> bool:
    u = (permalink or "").strip()
    if not u or not u.startswith(("http://", "https://")):
        return False
    plat_low = (platform or "").strip().lower()
    u_low = u.lower().rstrip("/")
    if plat_low == "facebook":
        # Reject generic Facebook URLs that do not contain a specific post/video/reel ID
        if u_low in ("https://www.facebook.com", "https://facebook.com", "https://fb.watch") or u_low.endswith(("/videos", "/reel", "/reels", "/posts", "/watch")):
            return False
        # Reject if the URL path is just a 24-char Zernio internal ObjectId instead of a Facebook ID
        m_fb_path = re.search(r"facebook\.com/([0-9a-f]{24})$", u_low)
        if m_fb_path:
            return False
    elif plat_low == "youtube":
        if not re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", u):
            return False
    return True


def extract_zernio_post_outcome(post_obj: Dict[str, Any], target_platform: str = "") -> Dict[str, str]:
    if not isinstance(post_obj, dict):
        return {"state": "processing", "zernio_id": "", "platform_post_id": "", "permalink": "", "error": ""}

    t_plat = (target_platform or str(post_obj.get("platform") or "")).strip().lower()
    zernio_id = str(post_obj.get("_id") or post_obj.get("id") or post_obj.get("postId") or "").strip()
    platform_post_id = str(
        post_obj.get("platformPostId")
        or post_obj.get("videoId")
        or post_obj.get("externalPostId")
        or ""
    ).strip()
    permalink = str(
        post_obj.get("platformPostUrl")
        or post_obj.get("permalink")
        or post_obj.get("url")
        or post_obj.get("videoUrl")
        or ""
    ).strip()
    top_status = str(post_obj.get("status") or post_obj.get("state") or "").strip().lower()
    err_msg = str(post_obj.get("error") or post_obj.get("errorMessage") or post_obj.get("failureReason") or "").strip()

    plat_statuses = []
    for p_res in (post_obj.get("platforms") or []):
        if not isinstance(p_res, dict):
            continue
        p_plat = str(p_res.get("platform") or "").strip().lower()
        if t_plat and p_plat and p_plat != t_plat:
            continue
        if not t_plat and p_plat:
            t_plat = p_plat
        cand_link = str(
            p_res.get("platformPostUrl")
            or p_res.get("permalink")
            or p_res.get("url")
            or p_res.get("videoUrl")
            or ""
        ).strip()
        if cand_link and (not permalink or not _is_valid_final_permalink(permalink, t_plat)):
            permalink = cand_link
        cand_pid = str(
            p_res.get("platformPostId")
            or p_res.get("videoId")
            or p_res.get("externalPostId")
            or ""
        ).strip()
        if cand_pid and (not platform_post_id or platform_post_id == zernio_id):
            platform_post_id = cand_pid
        p_st = str(p_res.get("status") or p_res.get("state") or "").strip().lower()
        if p_st:
            plat_statuses.append(p_st)
        p_err = p_res.get("error") or p_res.get("errorMessage") or p_res.get("failureReason") or p_res.get("message")
        if isinstance(p_err, dict):
            p_err = p_err.get("message") or json.dumps(p_err)
        if p_err and not err_msg:
            err_msg = str(p_err).strip()

    # Extract YouTube 11-char video ID from permalink if platform_post_id is missing or is still a 24-char Zernio ID
    if t_plat == "youtube":
        if permalink:
            m_yt = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", permalink)
            if m_yt and (not platform_post_id or len(platform_post_id) == 24):
                platform_post_id = m_yt.group(1).strip()
        if platform_post_id and re.match(r"^[A-Za-z0-9_-]{11}$", platform_post_id) and not _is_valid_final_permalink(permalink, "youtube"):
            permalink = f"https://www.youtube.com/watch?v={platform_post_id}"
    elif t_plat == "facebook":
        if platform_post_id and len(platform_post_id) == 24 and re.match(r"^[0-9a-f]{24}$", platform_post_id.lower()):
            # Do not treat a 24-char Zernio Mongo ID as a native Facebook Post ID
            if platform_post_id == zernio_id:
                platform_post_id = ""
        if permalink and not _is_valid_final_permalink(permalink, "facebook"):
            permalink = ""
        if not permalink and platform_post_id:
            if "_" in platform_post_id:
                page_part, post_part = platform_post_id.split("_", 1)
                permalink = f"https://www.facebook.com/{page_part}/posts/{post_part}"
            else:
                permalink = f"https://www.facebook.com/{platform_post_id}"

    failed_tokens = ("failed", "error", "rejected", "cancelled", "aborted")
    published_tokens = ("published", "completed", "posted", "success", "live", "uploaded", "done")
    active_processing_tokens = ("scheduled", "pending", "queued", "processing", "publishing", "uploading", "in_progress", "rendering", "encoding")

    if any(s in failed_tokens for s in plat_statuses) or top_status in failed_tokens:
        return {
            "state": "failed",
            "zernio_id": zernio_id,
            "platform_post_id": platform_post_id,
            "permalink": permalink,
            "error": err_msg or "Failed to publish to the social media platform."
        }

    is_explicitly_published = (
        any(s in published_tokens for s in plat_statuses)
        or top_status in published_tokens
    )
    is_explicitly_in_flight = (
        any(s in active_processing_tokens for s in plat_statuses)
        or top_status in active_processing_tokens
    )

    if is_explicitly_published:
        return {
            "state": "published",
            "zernio_id": zernio_id,
            "platform_post_id": platform_post_id,
            "permalink": permalink,
            "error": ""
        }

    if not is_explicitly_in_flight and (platform_post_id or _is_valid_final_permalink(permalink, t_plat)):
        return {
            "state": "published",
            "zernio_id": zernio_id,
            "platform_post_id": platform_post_id,
            "permalink": permalink,
            "error": ""
        }

    return {
        "state": "processing",
        "zernio_id": zernio_id,
        "platform_post_id": platform_post_id,
        "permalink": permalink,
        "error": err_msg
    }


def _strip_internal_ids_from_status_message(msg: str, status: str = "") -> str:
    """
    Removes internal External API ID / Platform ID / Zernio ID / existingPostId / accountId tokens
    and raw Python dict wrappers from status_message before sending to the frontend GUI
    (Calendar, Queue, Modals) while keeping them in the DB for internal comment/analytics matching.
    """
    st_low = (status or "").strip().lower()
    if st_low == "published":
        return ""
    raw = str(msg or "").replace("Zernio", "External API").replace("PostZen", "External API").strip()
    if not raw:
        return ""
    # Unwrap raw Python dict strings like: External API Failed: {'error': '...', 'details': {...}}
    m_dict_err = re.search(r"['\"]error['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw)
    if m_dict_err and ("{" in raw and "}" in raw):
        prefix = "External API Failed: " if raw.lower().startswith("external api failed") else ""
        raw = f"{prefix}{m_dict_err.group(1).strip()}"
    cleaned = re.sub(
        r"(?:External API ID|Platform ID|Zernio ID|PostZen ID|FB Post ID|FB Video ID|FB Album ID|IG Post ID|existingPostId|accountId)\s*[:=]\s*[^\s,|)}'\"\]>]+",
        "",
        raw,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\(\s*ID\s*:\s*[^)]+\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"•\s*ID\s*:\s*[^\s,|)]+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bExternal Post\b", "", cleaned, flags=re.IGNORECASE)
    parts = [p.strip(" •|-") for p in re.split(r"\s*\|\s*", cleaned) if p.strip(" •|-")]
    result = " • ".join(parts).strip(" •|-")
    if st_low == "waiting" and not result:
        return "Waiting for schedule..."
    return result


def _format_zernio_error_text(data: Any, fallback_text: str = "") -> str:
    if isinstance(data, dict):
        err_val = data.get("error") or data.get("message") or data.get("detail")
        if isinstance(err_val, str) and err_val.strip():
            return err_val.strip()
        if isinstance(err_val, dict):
            sub_msg = err_val.get("message") or err_val.get("error")
            if isinstance(sub_msg, str) and sub_msg.strip():
                return sub_msg.strip()
    raw_txt = str(fallback_text or data or "Unknown error").strip()
    m_err = re.search(r"['\"]error['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw_txt)
    if m_err:
        return m_err.group(1).strip()
    return raw_txt


def _differentiate_caption_for_zernio_24h_guard(caption: str, record_id: str, variant_step: int = 1) -> str:
    """
    Ensures caption content is treated as unique by Zernio's 24-hour anti-duplicate filter
    when a user schedules/posts multiple videos or episodes to the same account within 24 hours
    using the same caption text.
    """
    base = (caption or "").rstrip()
    seed_str = f"{record_id}_{variant_step}_{int(time.time())}"
    digest = hashlib.sha1(seed_str.encode("utf-8")).hexdigest()[:6]
    # Build an invisible Unicode signature using Braille Pattern Blank (\u2800, category So - never stripped by .trim())
    # combined with Word Joiner (\u2060) and Zero-Width Non-Joiner (\u200c)
    palette = ["\u2800", "\u2060", "\u200c", "\u200b"]
    invisible_sig = "".join(palette[int(ch, 16) % len(palette)] for ch in digest) + "\u2800"
    if variant_step <= 1:
        if len(base) >= 2:
            return base[:-1] + invisible_sig + base[-1] + invisible_sig
        return base + invisible_sig
    # Fallback if external API ever normalizes all invisible symbols on a subsequent retry:
    short_tag = digest[:3].upper()
    return f"{base}{invisible_sig} · #{short_tag}" if base else f"#{short_tag}"


_ZERNIO_PUBLISH_LOCK = threading.Lock()
_ZERNIO_ACTIVE_PUBLISH_RECORDS: set = set()


def _should_proactively_differentiate_caption(record_id: str, account_id: str, resolved_acc_id: str, caption: str) -> bool:
    """
    Checks if another scheduled/published/processing post in `glennbot_scheduled_posts` for the same social account
    already uses this exact same caption within a 48-hour window so we can proactively make the caption unique.
    """
    clean_cap = (caption or "").strip()
    if not clean_cap:
        return False
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, caption, page_id
                    FROM glennbot_scheduled_posts
                    WHERE id != :rid
                      AND status IN ('waiting', 'processing', 'processing_payload', 'published')
                    ORDER BY scheduled_time DESC
                    LIMIT 80
                """),
                {"rid": record_id}
            ).fetchall()
        for r in rows:
            r_acc = str(r[2] or "").strip()
            if r_acc in (account_id, resolved_acc_id):
                if str(r[1] or "").strip() == clean_cap:
                    return True
    except Exception:
        pass
    return False


def _handle_zernio_duplicate_content_response(
    record_id: str,
    resp_data: Any,
    resp_text: str,
    media_items: list,
    headers: dict
) -> Dict[str, Any]:
    """
    Inspects Zernio's 'This exact content is already scheduled, publishing, or was posted to this account within the last 24 hours'
    response. Determines whether `existingPostId` is:
      1. 'adopt': Created by an earlier attempt/timeout or pre-registration of THIS post -> adopt `existingPostId` and succeed without re-uploading!
      2. 'retry_unique_caption': Explicitly owned by a DIFFERENT row in `glennbot_scheduled_posts` -> differentiate caption.
    """
    raw_combined = f"{resp_data} {resp_text}"
    if "already scheduled, publishing, or was posted" not in raw_combined.lower() and "existingpostid" not in raw_combined.lower():
        return {"action": "none"}

    existing_post_id = ""
    if isinstance(resp_data, dict):
        details = resp_data.get("details")
        if isinstance(details, dict):
            existing_post_id = str(details.get("existingPostId") or details.get("postId") or "").strip()
    if not existing_post_id:
        m_ext = re.search(r"existingPostId['\"]?\s*:\s*['\"]([^'\"]+)['\"]", raw_combined)
        if m_ext:
            existing_post_id = m_ext.group(1).strip()

    if not existing_post_id:
        return {"action": "none", "existing_post_id": ""}

    # 1. Check if another record in our DB already owns `existing_post_id`
    owned_by_other_record = False
    owned_by_this_record = False
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id FROM glennbot_scheduled_posts
                    WHERE external_post_id = :eid
                       OR status_message LIKE :elike
                """),
                {"eid": existing_post_id, "elike": f"%{existing_post_id}%"}
            ).fetchall()
        for r in rows:
            rid = str(r[0] or "").strip()
            if rid == str(record_id).strip():
                owned_by_this_record = True
            elif rid and not rid.startswith("post_ext_"):
                owned_by_other_record = True
    except Exception:
        pass

    # Fetch the existing post object from Zernio if available
    fetched_post_obj: Dict[str, Any] = {}
    try:
        chk_resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/posts/{existing_post_id}", headers=headers, timeout=20)
        if chk_resp.status_code == 200 and chk_resp.text:
            chk_json = chk_resp.json()
            cand_obj = chk_json.get("post") or chk_json.get("data") or chk_json
            if isinstance(cand_obj, dict):
                fetched_post_obj = cand_obj
    except Exception as e:
        print(f"[⚠️ ZERNIO EXISTING POST CHECK WARNING] {existing_post_id}: {e}")

    # CRITICAL FIX: If `existing_post_id` is NOT owned by another scheduled row in our DB,
    # it was created by THIS record (e.g. Attempt 1 that timed out while uploading a 1.4GB video, or pre-registration).
    # Always ADOPT it so we NEVER re-upload the same video 2x or 3x!
    if owned_by_this_record or not owned_by_other_record:
        print(f"[✅ ZERNIO EXISTING POST ADOPTED] {record_id} adopted existingPostId {existing_post_id} (prevented duplicate upload)!")
        return {"action": "adopt", "existing_post_id": existing_post_id, "post_obj": fetched_post_obj}

    print(f"[🔄 ZERNIO 24H DUPLICATE GUARD] existingPostId {existing_post_id} belongs to another post in DB. Differentiating caption for {record_id}...")
    return {"action": "retry_unique_caption", "existing_post_id": existing_post_id}


def _recover_zernio_post_after_timeout(
    record_id: str,
    plat_lower: str,
    resolved_acc_id: str,
    caption: str,
    title: str,
    headers: dict
) -> Optional[Dict[str, Any]]:
    """
    When a large video (e.g. 1.4GB / 48 mins) `POST /v1/posts` times out waiting for Zernio's HTTP response,
    Zernio is usually still uploading/publishing the video in the background.
    This helper polls `GET /v1/posts` on Zernio to find and adopt that in-flight post so we NEVER send a second or third upload!
    """
    clean_cap = (caption or "").strip()
    clean_title = (title or "").strip()
    print(f"[🔍 TIMEOUT RECOVERY] Checking Zernio for in-flight {plat_lower.upper()} post for {record_id}...")

    for wait_step in range(3):
        time.sleep(6 if wait_step == 0 else 8)
        try:
            resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/posts", headers=headers, timeout=25)
            if resp.status_code == 200 and resp.text:
                posts_list = extract_list_from_api_payload(resp.json()) or []
                for p in posts_list:
                    if not isinstance(p, dict):
                        continue
                    p_id = str(p.get("_id") or p.get("id") or "").strip()
                    if not p_id:
                        continue
                    p_content = str(p.get("content") or p.get("caption") or "").strip()
                    # Check if platform/account matches
                    plat_matched = False
                    for pl in (p.get("platforms") or []):
                        if not isinstance(pl, dict):
                            continue
                        pl_plat = str(pl.get("platform") or "").strip().lower()
                        pl_acc = pl.get("accountId")
                        if isinstance(pl_acc, dict):
                            pl_acc = pl_acc.get("_id") or pl_acc.get("id")
                        pl_spec = pl.get("platformSpecificData") if isinstance(pl.get("platformSpecificData"), dict) else {}
                        pl_title = str(pl_spec.get("title") or "").strip()
                        if pl_plat == plat_lower and (not resolved_acc_id or str(pl_acc or "") == resolved_acc_id):
                            if (clean_cap and p_content == clean_cap) or (clean_title and pl_title == clean_title):
                                plat_matched = True
                                break
                    if plat_matched:
                        # Ensure this Zernio post isn't already owned by a different GlennBot row
                        other_owner = False
                        try:
                            with db_engine.connect() as conn:
                                rows = conn.execute(
                                    text("SELECT id FROM glennbot_scheduled_posts WHERE external_post_id = :eid OR status_message LIKE :elike"),
                                    {"eid": p_id, "elike": f"%{p_id}%"}
                                ).fetchall()
                            for r in rows:
                                rid = str(r[0] or "").strip()
                                if rid and rid != record_id and not rid.startswith("post_ext_"):
                                    other_owner = True
                        except Exception:
                            pass
                        if not other_owner:
                            print(f"[✅ TIMEOUT RECOVERY SUCCESS] Found in-flight Zernio post {p_id} for {record_id}!")
                            return p
        except Exception as e:
            print(f"[⚠️ TIMEOUT RECOVERY CHECK WARNING] {record_id}: {e}")
    return None


def _cancel_zernio_scheduled_post(z_post_id: str, platform: str = "", account_id: str = "") -> None:
    clean_zid = (z_post_id or "").strip()
    if not clean_zid or clean_zid == "OK":
        return
    keys_to_try: List[str] = []
    if account_id or platform:
        resolved_acc = resolve_zernio_account_id(platform, account_id) if account_id else ""
        k_acc = get_zernio_key_for_account(resolved_acc or account_id, platform=platform)
        if k_acc:
            keys_to_try.append(k_acc)
    for k in get_all_zernio_keys():
        if k and k not in keys_to_try:
            keys_to_try.append(k)
    for api_k in keys_to_try:
        try:
            resp = HTTP_SESSION.delete(
                f"{ZERNIO_BASE_URL}/posts/{clean_zid}",
                headers=get_zernio_headers(api_k),
                timeout=20
            )
            if resp.status_code in (200, 204, 404):
                print(f"[🗑️ ZERNIO SCHEDULED POST DELETED] ID: {clean_zid} (HTTP {resp.status_code})")
                ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                return
        except Exception as e:
            print(f"[⚠️ ZERNIO DELETE POST WARNING] {clean_zid}: {e}")


def register_scheduled_post_on_zernio(
    record_id: str,
    platform: str,
    account_id: str,
    post_type: str,
    caption: str,
    media_items: list,
    title: str = "",
    scheduled_time: Optional[datetime] = None
) -> str:
    """
    Pre-registers a future scheduled post on Zernio (`POST /v1/posts` with `scheduledFor` in UTC ISO-8601)
    so Zernio locks the uploaded media on `media.zernio.com` (never expiring after 7 days even for >7 day schedules)
    and publishes automatically at the exact scheduled time.
    Returns the Zernio Post ID if registered, or "" if registration should be deferred to runtime.
    """
    if not scheduled_time:
        return ""
    manila_tz = pytz.timezone("Asia/Manila")
    now_manila = datetime.now(manila_tz)
    sched_local = scheduled_time.astimezone(manila_tz) if getattr(scheduled_time, "tzinfo", None) else manila_tz.localize(scheduled_time)
    seconds_ahead = (sched_local - now_manila).total_seconds()
    if seconds_ahead <= 90:
        return ""
    # Zernio temporary media storage (media.zernio.com/temp/...) expires after 7 days.
    # For posts scheduled more than 6 days in advance, keep the media safely in Google Drive
    # and let APScheduler bridge it from Google Drive -> Zernio on the scheduled day!
    if seconds_ahead > 6 * 86400:
        print(f"[📅 >6 DAYS SCHEDULE GUARD] Deferring Zernio media transfer for {record_id} ({round(seconds_ahead / 86400, 1)} days ahead) to prevent 7-day Zernio storage expiration.")
        return ""

    resolved_acc_id = resolve_zernio_account_id(platform, account_id)
    api_key_for_acc = get_zernio_key_for_account(resolved_acc_id, platform=platform)
    if not api_key_for_acc:
        return ""

    headers = get_zernio_headers(api_key_for_acc)
    plat_lower = (platform or "").strip().lower()
    ptype_lower = (post_type or "").strip().lower()
    scheduled_utc_iso = sched_local.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    effective_caption = caption or ""
    if _should_proactively_differentiate_caption(record_id, account_id, resolved_acc_id, effective_caption):
        effective_caption = _differentiate_caption_for_zernio_24h_guard(effective_caption, record_id, variant_step=1)

    thumb_url = ""
    for m in (media_items or []):
        if isinstance(m, dict) and m.get("is_thumb") and m.get("url"):
            if m.get("vault_file_id") and "media.zernio.com" not in str(m.get("url") or ""):
                _transfer_fn = _resolve_runtime_helper("_transfer_vault_file_to_zernio_media_item")
                if _transfer_fn:
                    vt_bridged = _transfer_fn(
                        file_id=str(m["vault_file_id"]),
                        platform=platform,
                        account_id=account_id,
                        is_thumb=True,
                        record_id=record_id,
                        defer_to_runtime=False
                    )
                    if vt_bridged and vt_bridged.get("url"):
                        m["url"] = vt_bridged["url"]
            thumb_url = str(m["url"]).strip()
            break

    for m in (media_items or []):
        if not isinstance(m, dict) or m.get("is_thumb") or not m.get("url"):
            continue
        raw_m_url = str(m.get("url") or "").strip()
        m_storage = str(m.get("storage") or "").lower()
        if (
            m.get("vault_file_id")
            or m.get("gdrive_file_id")
            or m_storage == "google_drive"
        ) and "media.zernio.com" not in raw_m_url:
            m_type_check = str(m.get("type") or ("video" if ptype_lower in ("reels", "video169") else "image")).strip().lower()
            bridged_url, _ = bridge_gdrive_media_to_zernio_presign(
                source_url=raw_m_url,
                filename=str(m.get("filename") or m.get("gdrive_file_name") or ""),
                media_type=m_type_check,
                api_key=api_key_for_acc,
                vault_file_id=str(m.get("vault_file_id") or ""),
                gdrive_file_id=str(m.get("gdrive_file_id") or "")
            )
            if bridged_url and "media.zernio.com" in bridged_url:
                m["url"] = bridged_url
                m["storage"] = "zernio"

    def _build_sched_payload(include_thumb: bool = True, minimal_platform_data: bool = False, custom_caption: Optional[str] = None) -> Dict[str, Any]:
        z_media: List[Dict[str, Any]] = []
        for m in (media_items or []):
            if not isinstance(m, dict) or m.get("is_thumb") or not m.get("url"):
                continue
            m_type = str(m.get("type") or ("video" if ptype_lower in ("reels", "video169") else "image")).strip().lower()
            live_media_url = str(m["url"]).strip()
            item_obj: Dict[str, Any] = {"type": m_type, "url": live_media_url}
            if include_thumb and thumb_url and m_type == "video":
                item_obj["thumbnail"] = thumb_url
                if plat_lower == "instagram" and not minimal_platform_data:
                    item_obj["instagramThumbnail"] = thumb_url
            z_media.append(item_obj)

        plat_entry: Dict[str, Any] = {"platform": plat_lower, "accountId": resolved_acc_id}
        plat_specific: Dict[str, Any] = {}
        if plat_lower == "facebook":
            if ptype_lower == "reels":
                plat_specific["contentType"] = "reel"
            if title and title.strip() and not minimal_platform_data:
                plat_specific["title"] = title.strip()
        elif plat_lower == "instagram":
            if ptype_lower == "reels":
                plat_specific["contentType"] = "reel"
                plat_specific["shareToFeed"] = True
            if include_thumb and thumb_url:
                plat_specific["instagramThumbnail"] = thumb_url
                if not minimal_platform_data:
                    plat_specific["reelCover"] = thumb_url
        elif plat_lower == "tiktok":
            tiktok_settings: Dict[str, Any] = {
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "allow_comment": True,
                "allow_duet": True,
                "allow_stitch": True,
                "content_preview_confirmed": True,
                "express_consent_given": True
            }
            if include_thumb and thumb_url:
                tiktok_settings["video_cover_image_url"] = thumb_url
            plat_specific.update(tiktok_settings)
            if not minimal_platform_data:
                plat_specific["tiktokSettings"] = tiktok_settings
        elif plat_lower == "youtube":
            yt_title = (title or "").strip() or (caption or "").split("\n")[0].strip() or "New Video"
            plat_specific["title"] = yt_title[:100]
            plat_specific["visibility"] = "public"
            if include_thumb and thumb_url and not minimal_platform_data:
                plat_specific["thumbnail"] = thumb_url
                plat_specific["thumbnailUrl"] = thumb_url

        if plat_specific:
            plat_entry["platformSpecificData"] = plat_specific

        return {
            "content": effective_caption if custom_caption is None else custom_caption,
            "mediaItems": z_media,
            "scheduledFor": scheduled_utc_iso,
            "platforms": [plat_entry]
        }

    dup_variant_step = 0
    for attempt in range(2):
        payload = _build_sched_payload(
            include_thumb=True,
            minimal_platform_data=(attempt >= 1 and dup_variant_step == 0),
            custom_caption=effective_caption
        )
        try:
            res = HTTP_SESSION.post(f"{ZERNIO_BASE_URL}/posts", headers=headers, json=payload, timeout=120)
            data = res.json() if res.text else {}
            if res.status_code in (200, 201, 207):
                post_obj = (
                    data.get("post")
                    or data.get("data")
                    or (data.get("posts")[0] if isinstance(data.get("posts"), list) and data.get("posts") else data)
                )
                if isinstance(post_obj, dict):
                    ext_api_id = str(post_obj.get("_id") or post_obj.get("id") or "").strip()
                    if ext_api_id:
                        print(f"[📅 ZERNIO NATIVE SCHEDULE REGISTERED] {record_id} -> Zernio ID: {ext_api_id} for {scheduled_utc_iso}")
                        update_post_status(
                            record_id,
                            "waiting",
                            f"Waiting for schedule... | External API ID: {ext_api_id}",
                            external_post_id=ext_api_id
                        )
                        ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                        return ext_api_id
            else:
                dup_info = _handle_zernio_duplicate_content_response(record_id, data, res.text, media_items, headers)
                if dup_info.get("action") == "adopt" and dup_info.get("existing_post_id"):
                    ext_api_id = str(dup_info["existing_post_id"]).strip()
                    update_post_status(
                        record_id,
                        "waiting",
                        f"Waiting for schedule... | External API ID: {ext_api_id}",
                        external_post_id=ext_api_id
                    )
                    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                    return ext_api_id
                elif dup_info.get("action") == "retry_unique_caption":
                    dup_variant_step += 1
                    effective_caption = _differentiate_caption_for_zernio_24h_guard(caption or "", record_id, variant_step=dup_variant_step)
                    continue
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as te:
            print(f"[⚠️ ZERNIO SCHEDULE REGISTER TIMEOUT] {record_id}: {te}")
            recovered = _recover_zernio_post_after_timeout(record_id, plat_lower, resolved_acc_id, effective_caption, title, headers)
            if isinstance(recovered, dict):
                ext_api_id = str(recovered.get("_id") or recovered.get("id") or "").strip()
                if ext_api_id:
                    update_post_status(
                        record_id,
                        "waiting",
                        f"Waiting for schedule... | External API ID: {ext_api_id}",
                        external_post_id=ext_api_id
                    )
                    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                    return ext_api_id
            break
        except Exception as e:
            print(f"[⚠️ ZERNIO SCHEDULE REGISTER WARNING] {record_id} (attempt {attempt + 1}): {e}")
    return ""


def post_via_zernio(record_id: str, platform: str, account_id: str, post_type: str, caption: str, media_items: list, title: str = "") -> bool:
    # Prevent concurrent duplicate executions of the same record_id
    with _ZERNIO_PUBLISH_LOCK:
        if record_id in _ZERNIO_ACTIVE_PUBLISH_RECORDS:
            print(f"[🛡️ DUPLICATE EXECUTION BLOCKED] {record_id} is already being published by another worker.")
            return True
        _ZERNIO_ACTIVE_PUBLISH_RECORDS.add(record_id)

    try:
        resolved_acc_id = resolve_zernio_account_id(platform, account_id)
        api_key_for_acc = get_zernio_key_for_account(resolved_acc_id, platform=platform)
        if not api_key_for_acc:
            update_post_status(record_id, "failed", "Missing External API Key.")
            return False

        headers = get_zernio_headers(api_key_for_acc)
        plat_lower = (platform or "").strip().lower()
        ptype_lower = (post_type or "").strip().lower()

        # Check if this post was already pre-registered on Zernio with `scheduledFor` (or cancelled/published)
        pre_scheduled_zernio_id = ""
        try:
            with db_engine.connect() as conn:
                row_chk = conn.execute(
                    text("SELECT status, external_post_id, status_message FROM glennbot_scheduled_posts WHERE id = :id"),
                    {"id": record_id}
                ).fetchone()
            if not row_chk:
                print(f"[ℹ️ SCHEDULE SKIPPED] {record_id} was deleted before publish time.")
                return False
            cur_db_status = str(row_chk[0] or "").strip().lower()
            if cur_db_status == "published":
                return True
            cand_ext = str(row_chk[1] or "").strip()
            cur_s_msg = str(row_chk[2] or "").strip()
            m_z_pre = re.search(r"(?:External API ID|Zernio ID):\s*([^\s,|]+)", cur_s_msg)
            if m_z_pre:
                pre_scheduled_zernio_id = m_z_pre.group(1).strip()
            elif cand_ext and cand_ext != "OK":
                pre_scheduled_zernio_id = cand_ext
        except Exception:
            pass

        if pre_scheduled_zernio_id:
            update_post_status(
                record_id,
                "processing",
                f"Publishing to {platform.capitalize()} via External API... | External API ID: {pre_scheduled_zernio_id}",
                external_post_id=pre_scheduled_zernio_id
            )
        else:
            update_post_status(record_id, "processing", f"Publishing to {platform.capitalize()} via External API...")

        # Extract custom thumbnail / cover image URL if user uploaded one ("Add Thumbnail" / "Cover/Thumb")
        thumb_url = ""
        for m in (media_items or []):
            if isinstance(m, dict) and m.get("is_thumb") and m.get("url"):
                if (m.get("vault_file_id") or m.get("gdrive_file_id")) and "media.zernio.com" not in str(m.get("url") or ""):
                    bridged_t, _ = bridge_gdrive_media_to_zernio_presign(
                        source_url=str(m.get("url") or ""),
                        filename=str(m.get("filename") or m.get("gdrive_file_name") or ""),
                        media_type="image",
                        api_key=api_key_for_acc,
                        vault_file_id=str(m.get("vault_file_id") or ""),
                        gdrive_file_id=str(m.get("gdrive_file_id") or "")
                    )
                    if bridged_t and "media.zernio.com" in bridged_t:
                        m["url"] = bridged_t
                        m["storage"] = "zernio"
                thumb_url = str(m["url"]).strip()
                break

        _discover_yt_fn = _resolve_runtime_helper("discover_youtube_video_id_direct")

        # If already registered on Zernio via `scheduledFor`, monitor Zernio's native execution and sync status to Supabase!
        if pre_scheduled_zernio_id:
            print(f"[⏳ MONITORING PRE-SCHEDULED ZERNIO POST] {record_id} -> Zernio ID: {pre_scheduled_zernio_id}")
            for poll_idx in range(60):
                try:
                    chk_resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/posts/{pre_scheduled_zernio_id}", headers=headers, timeout=20)
                    if chk_resp.status_code == 200:
                        chk = chk_resp.json() if chk_resp.text else {}
                        chk_obj = chk.get("post") or chk.get("data") or chk
                        if isinstance(chk_obj, dict):
                            outcome = extract_zernio_post_outcome(chk_obj, target_platform=platform)
                            if outcome["state"] != "published" and plat_lower == "youtube" and poll_idx >= 2 and _discover_yt_fn:
                                yt_vid_live = _discover_yt_fn({
                                    "id": record_id,
                                    "platform": "youtube",
                                    "page_id": account_id,
                                    "account_name": "",
                                    "caption": f"{title}\n{caption}".strip() if title else caption,
                                    "external_post_id": outcome.get("platform_post_id") or pre_scheduled_zernio_id,
                                    "permalink_url": outcome.get("permalink") or "",
                                    "status_message": f"External API ID: {pre_scheduled_zernio_id}"
                                })
                                if yt_vid_live:
                                    outcome["state"] = "published"
                                    outcome["platform_post_id"] = yt_vid_live
                                    outcome["permalink"] = f"https://www.youtube.com/watch?v={yt_vid_live}"
                            if outcome["state"] == "published":
                                if plat_lower == "youtube" and thumb_url:
                                    try:
                                        HTTP_SESSION.post(
                                            f"{ZERNIO_BASE_URL}/posts/{pre_scheduled_zernio_id}/update-metadata",
                                            headers=headers,
                                            json={"platform": "youtube", "accountId": resolved_acc_id, "thumbnailUrl": thumb_url},
                                            timeout=20
                                        )
                                    except Exception:
                                        pass
                                platform_post_id = outcome["platform_post_id"]
                                permalink = outcome["permalink"]
                                saved_ext_id = platform_post_id or pre_scheduled_zernio_id
                                status_msg = f"External API ID: {pre_scheduled_zernio_id}"
                                if platform_post_id:
                                    status_msg += f" | Platform ID: {platform_post_id}"
                                update_post_status(
                                    record_id,
                                    "published",
                                    status_msg,
                                    external_post_id=saved_ext_id,
                                    permalink_url=permalink or None
                                )
                                ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                                ZERNIO_COMMENTED_POSTS_CACHE["last_fetched"] = 0.0
                                return True
                            elif outcome["state"] == "failed":
                                err_detail = outcome["error"] or "Failed to publish"
                                fail_msg = f"External API Failed: {err_detail}"
                                update_post_status(record_id, "failed", fail_msg, external_post_id=pre_scheduled_zernio_id)
                                ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                                return False
                    elif chk_resp.status_code == 404:
                        pre_scheduled_zernio_id = ""
                        break
                except Exception:
                    pass
                update_post_status(
                    record_id,
                    "processing",
                    f"Publishing & rendering on {platform.capitalize()}... | External API ID: {pre_scheduled_zernio_id}",
                    external_post_id=pre_scheduled_zernio_id
                )
                time.sleep(5)

            if pre_scheduled_zernio_id:
                ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                return True

        # Stage any Google Drive / Vault media into Zernio's native presigned media cloud (media.zernio.com) at publish runtime
        gdrive_bridge_error_hint = ""
        for m in (media_items or []):
            if not isinstance(m, dict) or m.get("is_thumb") or not m.get("url"):
                continue
            raw_m_url = str(m.get("url") or "").strip()
            m_storage = str(m.get("storage") or "").lower()
            if (
                m.get("vault_file_id")
                or m.get("gdrive_file_id")
                or m_storage == "google_drive"
            ) and "media.zernio.com" not in raw_m_url:
                m_type_check = str(m.get("type") or ("video" if ptype_lower in ("reels", "video169") else "image")).strip().lower()
                update_post_status(record_id, "processing", f"Transferring media from Google Drive to Zernio Cloud for {plat_lower.upper()}...")
                bridged_url, bridge_err = bridge_gdrive_media_to_zernio_presign(
                    source_url=raw_m_url,
                    filename=str(m.get("filename") or m.get("gdrive_file_name") or ""),
                    media_type=m_type_check,
                    api_key=api_key_for_acc,
                    record_id=record_id,
                    vault_file_id=str(m.get("vault_file_id") or ""),
                    gdrive_file_id=str(m.get("gdrive_file_id") or "")
                )
                if bridged_url and "media.zernio.com" in bridged_url:
                    m["url"] = bridged_url
                    m["storage"] = "zernio"
                elif bridge_err:
                    gdrive_bridge_error_hint = bridge_err

        effective_caption = caption or ""
        if _should_proactively_differentiate_caption(record_id, account_id, resolved_acc_id, effective_caption):
            effective_caption = _differentiate_caption_for_zernio_24h_guard(effective_caption, record_id, variant_step=1)

        def _build_zernio_post_payload(include_thumb: bool = True, minimal_platform_data: bool = False, custom_caption: Optional[str] = None) -> Dict[str, Any]:
            z_media: List[Dict[str, Any]] = []
            for m in (media_items or []):
                if not isinstance(m, dict) or m.get("is_thumb") or not m.get("url"):
                    continue
                m_type = str(m.get("type") or ("video" if ptype_lower in ("reels", "video169") else "image")).strip().lower()
                live_media_url = str(m["url"]).strip()
                item_obj: Dict[str, Any] = {
                    "type": m_type,
                    "url": live_media_url
                }
                if include_thumb and thumb_url and m_type == "video":
                    item_obj["thumbnail"] = thumb_url
                    if plat_lower == "instagram" and not minimal_platform_data:
                        item_obj["instagramThumbnail"] = thumb_url
                z_media.append(item_obj)

            plat_entry: Dict[str, Any] = {
                "platform": plat_lower,
                "accountId": resolved_acc_id
            }
            plat_specific: Dict[str, Any] = {}

            if plat_lower == "facebook":
                if ptype_lower == "reels":
                    plat_specific["contentType"] = "reel"
                if title and title.strip() and not minimal_platform_data:
                    plat_specific["title"] = title.strip()

            elif plat_lower == "instagram":
                if ptype_lower == "reels":
                    plat_specific["contentType"] = "reel"
                    plat_specific["shareToFeed"] = True
                if include_thumb and thumb_url:
                    plat_specific["instagramThumbnail"] = thumb_url
                    if not minimal_platform_data:
                        plat_specific["reelCover"] = thumb_url

            elif plat_lower == "tiktok":
                tiktok_settings: Dict[str, Any] = {
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "allow_comment": True,
                    "allow_duet": True,
                    "allow_stitch": True,
                    "content_preview_confirmed": True,
                    "express_consent_given": True
                }
                if include_thumb and thumb_url:
                    tiktok_settings["video_cover_image_url"] = thumb_url

                plat_specific["privacy_level"] = "PUBLIC_TO_EVERYONE"
                plat_specific["allow_comment"] = True
                plat_specific["allow_duet"] = True
                plat_specific["allow_stitch"] = True
                plat_specific["content_preview_confirmed"] = True
                plat_specific["express_consent_given"] = True
                if include_thumb and thumb_url:
                    plat_specific["video_cover_image_url"] = thumb_url
                if not minimal_platform_data:
                    plat_specific["tiktokSettings"] = tiktok_settings

            elif plat_lower == "youtube":
                yt_title = (title or "").strip() or (caption or "").split("\n")[0].strip() or "New Video"
                plat_specific["title"] = yt_title[:100]
                plat_specific["visibility"] = "public"
                if include_thumb and thumb_url and not minimal_platform_data:
                    plat_specific["thumbnail"] = thumb_url
                    plat_specific["thumbnailUrl"] = thumb_url

            if plat_specific:
                plat_entry["platformSpecificData"] = plat_specific

            body_payload: Dict[str, Any] = {
                "content": effective_caption if custom_caption is None else custom_caption,
                "mediaItems": z_media,
                "publishNow": True,
                "platforms": [plat_entry]
            }
            if include_thumb and thumb_url:
                print(f"[🖼️ THUMBNAIL ATTACHED] Platform: {plat_lower.upper()} (attempt_minimal={minimal_platform_data}) | Thumbnail URL: {thumb_url}")
            return body_payload

        url = f"{ZERNIO_BASE_URL}/posts"
        # Allow up to 2 attempts only for explicit HTTP 400 validation errors (never retry timeouts on large videos!)
        max_retries = 2
        last_error = ""
        dup_variant_step = 0

        for attempt in range(max_retries):
            err_low = last_error.lower()
            thumb_rejected = any(w in err_low for w in ("video_cover_image_url", "reelcover", "instagramthumbnail", "custom_thumbnail", "invalid thumbnail", "thumbnail image", "cover image"))
            if attempt == 0 and dup_variant_step == 0:
                payload = _build_zernio_post_payload(include_thumb=True, minimal_platform_data=False, custom_caption=effective_caption)
            else:
                payload = _build_zernio_post_payload(include_thumb=(not thumb_rejected), minimal_platform_data=True, custom_caption=effective_caption)

            adopted_post_obj: Optional[Dict[str, Any]] = None
            res = None
            data: Dict[str, Any] = {}

            try:
                # 300-second timeout so 1.4GB+ (48-min) videos finish transferring from Zernio to YouTube/Facebook without cutting off
                res = HTTP_SESSION.post(url, headers=headers, json=payload, timeout=300)
                data = res.json() if res.text else {}
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as req_timeout_err:
                last_error = f"External API request timed out while transferring video: {req_timeout_err}"
                print(f"[⏳ EXTERNAL API TIMEOUT] {record_id} ({platform.upper()}): {last_error}")
                # CRITICAL: Do NOT re-POST the video! Recover the in-flight post from Zernio instead!
                recovered_obj = _recover_zernio_post_after_timeout(record_id, plat_lower, resolved_acc_id, effective_caption, title, headers)
                if isinstance(recovered_obj, dict):
                    adopted_post_obj = recovered_obj
                else:
                    # Even if Zernio hasn't listed it yet, do NOT re-submit a 1.4GB video a second time
                    break
            except Exception as e:
                last_error = str(e)
                break

            if res is not None and res.status_code not in [200, 201, 207] and adopted_post_obj is None:
                dup_info = _handle_zernio_duplicate_content_response(record_id, data, res.text, media_items, headers)
                if dup_info.get("action") == "adopt" and dup_info.get("existing_post_id"):
                    adopted_post_obj = dup_info.get("post_obj") if isinstance(dup_info.get("post_obj"), dict) else {}
                    if not adopted_post_obj.get("_id") and not adopted_post_obj.get("id"):
                        adopted_post_obj["_id"] = str(dup_info["existing_post_id"]).strip()
                elif dup_info.get("action") == "retry_unique_caption" and attempt < max_retries - 1:
                    dup_variant_step += 1
                    effective_caption = _differentiate_caption_for_zernio_24h_guard(caption or "", record_id, variant_step=dup_variant_step)
                    time.sleep(1)
                    continue
                elif res.status_code >= 500:
                    # On HTTP 500/502/503/504 gateway timeout, check if Zernio actually created the post before retrying
                    recovered_obj = _recover_zernio_post_after_timeout(record_id, plat_lower, resolved_acc_id, effective_caption, title, headers)
                    if isinstance(recovered_obj, dict):
                        adopted_post_obj = recovered_obj
                    else:
                        last_error = _format_zernio_error_text(data, res.text)
                        break

            if (res is not None and res.status_code in [200, 201, 207]) or adopted_post_obj is not None:
                post_obj = adopted_post_obj if adopted_post_obj is not None else (
                    data.get("post")
                    or data.get("data")
                    or (data.get("posts")[0] if isinstance(data.get("posts"), list) and data.get("posts") else data)
                )
                if not isinstance(post_obj, dict):
                    post_obj = {}

                outcome = extract_zernio_post_outcome(post_obj, target_platform=platform)
                ext_api_id = outcome["zernio_id"]

                if ext_api_id and outcome["state"] == "processing":
                    for poll_idx in range(60):
                        update_post_status(
                            record_id,
                            "processing",
                            f"Publishing & rendering on {platform.capitalize()}... | External API ID: {ext_api_id}",
                            external_post_id=ext_api_id
                        )
                        time.sleep(5)
                        try:
                            chk_resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/posts/{ext_api_id}", headers=headers, timeout=20)
                            if chk_resp.status_code == 200:
                                chk = chk_resp.json()
                                chk_obj = chk.get("post") or chk.get("data") or chk
                                if isinstance(chk_obj, dict):
                                    outcome = extract_zernio_post_outcome(chk_obj, target_platform=platform)
                                    if outcome["state"] != "published" and plat_lower == "youtube" and poll_idx >= 2 and _discover_yt_fn:
                                        yt_vid_live = _discover_yt_fn({
                                            "id": record_id,
                                            "platform": "youtube",
                                            "page_id": account_id,
                                            "account_name": "",
                                            "caption": f"{title}\n{caption}".strip() if title else caption,
                                            "external_post_id": outcome.get("platform_post_id") or ext_api_id,
                                            "permalink_url": outcome.get("permalink") or "",
                                            "status_message": f"External API ID: {ext_api_id}"
                                        })
                                        if yt_vid_live:
                                            outcome["state"] = "published"
                                            outcome["platform_post_id"] = yt_vid_live
                                            outcome["permalink"] = f"https://www.youtube.com/watch?v={yt_vid_live}"
                                    if outcome["state"] in ("published", "failed"):
                                        break
                        except Exception:
                            pass

                if outcome["state"] == "failed":
                    err_detail = _format_zernio_error_text(outcome["error"], "Failed to publish")
                    if gdrive_bridge_error_hint and "unable to fetch video" in err_detail.lower():
                        err_detail = f"{err_detail} ({gdrive_bridge_error_hint})"
                    fail_msg = f"External API Failed: {err_detail}"
                    print(f"[❌ EXTERNAL API {platform.upper()} FAILED] {fail_msg}")
                    last_error = err_detail or fail_msg
                    if attempt < max_retries - 1 and thumb_url and any(w in last_error.lower() for w in ("thumbnail", "cover", "image", "parameter", "invalid")):
                        print(f"[🔄 THUMBNAIL FALLBACK RETRY] Retrying {platform.upper()} post with fallback payload...")
                        time.sleep(3)
                        continue
                    update_post_status(record_id, "failed", fail_msg, external_post_id=ext_api_id or None)
                    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                    return False

                if outcome["state"] == "processing" and ext_api_id:
                    update_post_status(
                        record_id,
                        "processing",
                        f"Rendering video on {platform.capitalize()}... | External API ID: {ext_api_id}",
                        external_post_id=ext_api_id
                    )
                    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                    return True

                if plat_lower == "youtube" and thumb_url and ext_api_id:
                    try:
                        HTTP_SESSION.post(
                            f"{ZERNIO_BASE_URL}/posts/{ext_api_id}/update-metadata",
                            headers=headers,
                            json={"platform": "youtube", "accountId": resolved_acc_id, "thumbnailUrl": thumb_url},
                            timeout=20
                        )
                    except Exception:
                        pass

                platform_post_id = outcome["platform_post_id"]
                permalink = outcome["permalink"]
                saved_ext_id = platform_post_id or ext_api_id or "OK"
                status_msg = f"External API ID: {ext_api_id or saved_ext_id}"
                if platform_post_id:
                    status_msg += f" | Platform ID: {platform_post_id}"

                print(f"[✅ EXTERNAL API {platform.upper()} FINISH] Success! {status_msg}")
                update_post_status(
                    record_id,
                    "published",
                    status_msg,
                    external_post_id=saved_ext_id,
                    permalink_url=permalink or None
                )
                ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
                ZERNIO_COMMENTED_POSTS_CACHE["last_fetched"] = 0.0
                return True
            else:
                if res is not None:
                    last_error = _format_zernio_error_text(data, res.text)
                print(f"[⚠️ EXTERNAL API WARNING] Attempt {attempt + 1}/{max_retries} ({platform}): {last_error}")
                # Only retry if Zernio explicitly rejected a thumbnail/cover parameter before creating a post
                if not (thumb_url and any(w in last_error.lower() for w in ("thumbnail", "cover", "image", "parameter", "invalid"))):
                    break

            if attempt < max_retries - 1:
                update_post_status(record_id, "processing", f"External API Retry {attempt + 1}/{max_retries} in 5s...")
                time.sleep(5)

        update_post_status(record_id, "failed", f"External API Failed: {last_error}")
        return False
    finally:
        with _ZERNIO_PUBLISH_LOCK:
            _ZERNIO_ACTIVE_PUBLISH_RECORDS.discard(record_id)


def post_to_facebook(record_id, page_id, post_type, caption, media_items):
    print(f"\n[🚀 FB POST VIA EXTERNAL API] Publishing to FB Page: {page_id}")
    post_via_zernio(record_id, "facebook", page_id, post_type, caption, media_items)


def post_to_instagram(record_id, ig_user_id, post_type, caption, media_items):
    print(f"\n[🚀 IG POST VIA EXTERNAL API] Publishing to IG Account: {ig_user_id}")
    post_via_zernio(record_id, "instagram", ig_user_id, post_type, caption, media_items)


def post_to_tiktok(record_id, account_id, caption, media_items):
    print(f"\n[🚀 TIKTOK POST VIA EXTERNAL API] Publishing to TikTok Account: {account_id}")
    post_via_zernio(record_id, "tiktok", account_id, "reels", caption, media_items)


def post_to_youtube(record_id, account_id, post_type, caption, media_items, title=""):
    print(f"\n[🚀 YOUTUBE POST VIA EXTERNAL API] Publishing to YouTube Channel: {account_id}")
    post_via_zernio(record_id, "youtube", account_id, post_type, caption, media_items, title=title)
