import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
import pytz
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from core.config import (
    ENV_EXTERNAL_API_KEY,
    ZERNIO_BASE_URL,
    MAX_ACCOUNTS_PER_EXTERNAL_API,
    HTTP_SESSION,
)
from core.database import db_engine
from services.cloudinary_service import (
    EXTERNAL_KEYS_STATE,
    CLOUDINARY_COMMENTS_STORE,
    CLOUDINARY_MESSAGES_STORE,
    _mask_api_key,
    _make_key_id,
    load_external_keys_from_cloudinary,
    sync_external_keys_to_cloudinary,
    get_all_zernio_keys,
    save_comments_store_async,
    save_messages_store_async,
)
from services.zernio_service import (
    CONNECTED_ACCOUNTS_CACHE,
    ZERNIO_ACCOUNTS_CACHE,
    ZERNIO_POSTS_CACHE,
    ZERNIO_COMMENTED_POSTS_CACHE,
    get_active_zernio_key,
    get_zernio_headers,
    extract_list_from_api_payload,
    fetch_zernio_connected_accounts,
    evaluate_external_api_pool_status,
    get_zernio_default_profile_id,
    refresh_connected_accounts_cache,
    get_zernio_key_for_account,
    _is_same_social_page_name,
)

router = APIRouter()

ANALYTICS_CACHE: Dict[str, Any] = {
    "by_period": {},
    "yt_video_stats": {},
    "ext_snapshot": {
        "ts": 0.0,
        "analytics_posts": [],
        "follower_stats": {},
        "permissions_notes": [],
        "is_syncing": False
    }
}
ANALYTICS_SYNC_LOCK = threading.Lock()


# ==============================================================================
# --- MANAGE EXTERNAL API KEYS ENDPOINTS ---
# ==============================================================================

class ExternalApiKeyPayload(BaseModel):
    api_key: str

@router.get("/api/external_api/keys")
@router.get("/api/zernio/api_key")
def get_external_api_keys_history(refresh: bool = True):
    pool = evaluate_external_api_pool_status(force_refresh=refresh)
    active_key = get_active_zernio_key()
    return {
        "status": "success",
        "masked_active_key": _mask_api_key(active_key),
        "total_saved_keys": len(pool),
        "keys": [
            {
                "id": item["id"],
                "masked_key": item["masked_key"],
                "is_env": item["is_env"],
                "added_at": item["added_at"],
                "connected_count": item["connected_count"],
                "max_limit": item["max_limit"],
                "is_full": item["is_full"],
                "is_current_slot": item["is_current_slot"],
                "status": item["status"],
                "account_names": item["account_names"],
                "order_index": item["order_index"]
            }
            for item in pool
        ]
    }

@router.post("/api/external_api/keys")
@router.post("/api/zernio/api_key")
def add_external_api_key_to_pool(payload: ExternalApiKeyPayload):
    new_key = (payload.api_key or "").strip()
    if not new_key:
        return {"status": "error", "message": "Please paste your External API Key."}

    existing_keys = get_all_zernio_keys()
    if new_key in existing_keys:
        return {"status": "error", "message": "This External API Key is already listed in your Manage API history."}

    prof_check = get_zernio_default_profile_id(api_key=new_key)
    if not prof_check.get("profile_id"):
        return {
            "status": "error",
            "message": f"Invalid External API Key: {prof_check.get('error')}"
        }

    current_pool = evaluate_external_api_pool_status(force_refresh=True)
    all_previous_full = all(item["is_full"] for item in current_pool) if current_pool else True

    now_label = datetime.now(pytz.timezone("Asia/Manila")).strftime("%b %d, %Y • %I:%M %p")
    new_entry = {
        "id": _make_key_id(new_key),
        "api_key": new_key,
        "added_at": now_label,
        "forced_in_use": all_previous_full
    }

    EXTERNAL_KEYS_STATE["cloudinary_entries"].append(new_entry)
    if all_previous_full:
        EXTERNAL_KEYS_STATE["preferred_active_key"] = new_key

    saved_ok = sync_external_keys_to_cloudinary()
    if not saved_ok:
        return {"status": "error", "message": "Failed to save External API Key to Cloudinary."}

    ZERNIO_ACCOUNTS_CACHE["last_fetched"] = 0.0
    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
    ZERNIO_COMMENTED_POSTS_CACHE["last_fetched"] = 0.0

    updated_pool = evaluate_external_api_pool_status(force_refresh=True)
    added_info = next((x for x in updated_pool if x["id"] == new_entry["id"]), None)
    assigned_status = added_info["status"] if added_info else ("In use" if all_previous_full else "Buffer")

    return {
        "status": "success",
        "message": f"External API Key saved to Cloudinary as '{assigned_status}'!",
        "masked_key": _mask_api_key(new_key),
        "assigned_status": assigned_status,
        "total_keys": len(updated_pool),
        "keys": [
            {
                "id": item["id"],
                "masked_key": item["masked_key"],
                "is_env": item["is_env"],
                "added_at": item["added_at"],
                "connected_count": item["connected_count"],
                "max_limit": item["max_limit"],
                "is_full": item["is_full"],
                "is_current_slot": item["is_current_slot"],
                "status": item["status"],
                "account_names": item["account_names"],
                "order_index": item["order_index"]
            }
            for item in updated_pool
        ]
    }

@router.post("/api/external_api/keys/{key_id}/activate")
def set_external_api_key_in_use(key_id: str):
    if not EXTERNAL_KEYS_STATE["loaded_from_cloudinary"]:
        load_external_keys_from_cloudinary()

    if key_id == "env_default" and ENV_EXTERNAL_API_KEY:
        EXTERNAL_KEYS_STATE["preferred_active_key"] = ENV_EXTERNAL_API_KEY
        sync_external_keys_to_cloudinary()
        return get_external_api_keys_history(refresh=True)

    found = False
    for entry in EXTERNAL_KEYS_STATE.get("cloudinary_entries", []):
        if entry.get("id") == key_id:
            entry["forced_in_use"] = True
            EXTERNAL_KEYS_STATE["preferred_active_key"] = entry["api_key"]
            found = True
            break

    if not found:
        return {"status": "error", "message": "API Key not found."}

    sync_external_keys_to_cloudinary()
    return get_external_api_keys_history(refresh=True)

@router.delete("/api/external_api/keys/{key_id}")
def delete_external_api_key_from_cloudinary(key_id: str):
    if key_id == "env_default":
        return {
            "status": "error",
            "message": "The default .env API key is protected and cannot be deleted."
        }

    if not EXTERNAL_KEYS_STATE["loaded_from_cloudinary"]:
        load_external_keys_from_cloudinary()

    before_list = EXTERNAL_KEYS_STATE.get("cloudinary_entries") or []
    target_entry = next((e for e in before_list if e.get("id") == key_id), None)
    if not target_entry:
        return {"status": "error", "message": "API key not found in Cloudinary."}

    deleted_api_key = (target_entry.get("api_key") or "").strip()

    owned_account_ids = set()
    owned_usernames = set()

    cached_by_key = (ZERNIO_ACCOUNTS_CACHE.get("accounts_by_key") or {}).get(deleted_api_key) or []
    if not cached_by_key and deleted_api_key:
        try:
            res = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/accounts", headers=get_zernio_headers(deleted_api_key), timeout=12).json()
            cached_by_key = extract_list_from_api_payload(res) or []
        except Exception:
            cached_by_key = []

    for a in cached_by_key:
        if not isinstance(a, dict):
            continue
        for id_field in ("_id", "id", "platformAccountId", "platformId", "pageId"):
            val = str(a.get(id_field) or "").strip()
            if val:
                owned_account_ids.add(val)
        for name_field in ("username", "displayName", "name"):
            nval = (a.get(name_field) or "").strip().lstrip("@").lower()
            if nval:
                owned_usernames.add(nval)

    EXTERNAL_KEYS_STATE["cloudinary_entries"] = [e for e in before_list if e.get("id") != key_id]
    if EXTERNAL_KEYS_STATE.get("preferred_active_key") == deleted_api_key:
        EXTERNAL_KEYS_STATE["preferred_active_key"] = ""

    sync_external_keys_to_cloudinary()

    ZERNIO_ACCOUNTS_CACHE["last_fetched"] = 0.0
    remaining_accs = fetch_zernio_connected_accounts(force=True)
    still_active_acc_ids = {
        str(a.get("_id") or a.get("id") or "").strip()
        for a in remaining_accs if isinstance(a, dict)
    }

    removed_accounts_count = 0
    removed_account_ids = set()
    removed_account_names = set()

    try:
        with db_engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT id, platform, account_id, account_name, username, access_token
                FROM glennbot_connected_accounts
            """)).mappings().all()

            for r in rows:
                r_id = str(r["id"])
                acc_id = str(r.get("account_id") or "").strip()
                acc_name = (r.get("account_name") or "").strip().lstrip("@").lower()
                uname = (r.get("username") or "").strip().lstrip("@").lower()
                raw_tok = (r.get("access_token") or "").strip()

                tok_matches_deleted = (
                    deleted_api_key != ""
                    and raw_tok in (f"EXTERNAL_API_MANAGED:{deleted_api_key}", f"ZERNIO_MANAGED:{deleted_api_key}")
                )
                id_matches_deleted = (
                    (acc_id in owned_account_ids or (acc_name and acc_name in owned_usernames) or (uname and uname in owned_usernames))
                    and acc_id not in still_active_acc_ids
                )

                if tok_matches_deleted or id_matches_deleted:
                    conn.execute(
                        text("DELETE FROM glennbot_connected_accounts WHERE id = :id"),
                        {"id": r_id}
                    )
                    removed_accounts_count += 1
                    if acc_id:
                        removed_account_ids.add(acc_id)
                        CONNECTED_ACCOUNTS_CACHE["zernio_key_by_account"].pop(acc_id, None)
                    if acc_name:
                        removed_account_names.add(acc_name)
                    if uname:
                        removed_account_names.add(uname)
    except Exception as e:
        print(f"[⚠️ CASCADE DELETE ACCOUNTS WARNING]: {e}")

    # Clean up Cloudinary Comments Store
    posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
    removed_from_store = False
    for rec_id, p_entry in list(posts_store.items()):
        p_page_id = str(p_entry.get("page_id") or "").strip()
        p_acc_name = (p_entry.get("account_name") or "").strip().lstrip("@").lower()
        if (p_page_id and p_page_id in (removed_account_ids | owned_account_ids)) or (p_acc_name and p_acc_name in (removed_account_names | owned_usernames)):
            posts_store.pop(rec_id, None)
            removed_from_store = True
    if removed_from_store:
        save_comments_store_async()

    # Clean up Cloudinary Messages Store
    convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
    removed_msgs = False
    for c_key, c_entry in list(convs_store.items()):
        c_acc_id = str(c_entry.get("account_id") or "").strip()
        c_acc_name = (c_entry.get("account_name") or "").strip().lstrip("@").lower()
        if (c_acc_id and c_acc_id in (removed_account_ids | owned_account_ids)) or (c_acc_name and c_acc_name in (removed_account_names | owned_usernames)):
            convs_store.pop(c_key, None)
            removed_msgs = True
    if removed_msgs:
        save_messages_store_async()

    refresh_connected_accounts_cache(force=True)
    ZERNIO_POSTS_CACHE["last_fetched"] = 0.0
    ZERNIO_COMMENTED_POSTS_CACHE["last_fetched"] = 0.0
    ANALYTICS_CACHE["by_period"].clear()

    history_res = get_external_api_keys_history(refresh=True)
    history_res["removed_accounts_count"] = removed_accounts_count
    return history_res


@router.get("/api/social/accounts")
def get_social_accounts():
    connected = refresh_connected_accounts_cache(force=True)
    fb_pages = []
    ig_accounts = []
    tiktok_accounts = []
    youtube_accounts = []
    whatsapp_accounts = []
    telegram_accounts = []

    for item in connected:
        plat = item.get("platform")
        acc_id = str(item.get("account_id") or "")
        acc_name = item.get("account_name") or ""
        uname = item.get("username") or ""
        avatar = item.get("avatar_url") or ""
        db_id = item.get("id") or f"{plat}_{acc_id}"

        if plat == "facebook":
            fb_pages.append({
                "id": acc_id,
                "name": acc_name,
                "avatar": avatar,
                "connected_by": "External API",
                "db_id": db_id
            })
        elif plat == "instagram":
            ig_accounts.append({
                "id": acc_id,
                "name": acc_name,
                "username": uname or acc_name,
                "avatar": avatar,
                "connected_by": "External API",
                "db_id": db_id
            })
        elif plat == "tiktok":
            tiktok_accounts.append({
                "id": acc_id,
                "name": acc_name or uname,
                "username": uname or acc_name,
                "avatar": avatar,
                "connected_by": "External API",
                "db_id": db_id
            })
        elif plat == "youtube":
            youtube_accounts.append({
                "id": acc_id,
                "name": acc_name or uname,
                "username": uname or acc_name,
                "avatar": avatar,
                "connected_by": "External API",
                "db_id": db_id
            })
        elif plat == "whatsapp":
            whatsapp_accounts.append({
                "id": acc_id,
                "name": acc_name or uname,
                "username": uname or acc_name,
                "avatar": avatar,
                "connected_by": "External API",
                "db_id": db_id
            })
        elif plat == "telegram":
            telegram_accounts.append({
                "id": acc_id,
                "name": acc_name or uname,
                "username": uname or acc_name,
                "avatar": avatar,
                "connected_by": "External API",
                "db_id": db_id
            })

    return {
        "facebook": fb_pages,
        "instagram": ig_accounts,
        "tiktok": tiktok_accounts,
        "youtube": youtube_accounts,
        "whatsapp": whatsapp_accounts,
        "telegram": telegram_accounts,
        "total_connected": len(connected)
    }


# ==============================================================================
# --- DYNAMIC SOCIAL ACCOUNT CONNECTION HUB ---
# ==============================================================================

class ConnectedAccountItem(BaseModel):
    platform: str
    account_id: str
    account_name: str
    username: Optional[str] = ""
    avatar_url: Optional[str] = ""
    access_token: Optional[str] = ""
    connected_by: Optional[str] = ""

class SaveConnectedAccountsPayload(BaseModel):
    accounts: List[ConnectedAccountItem]

class MetaDiscoverPayload(BaseModel):
    access_token: Optional[str] = ""
    code: Optional[str] = ""
    redirect_uri: Optional[str] = ""
    use_env_fallback: Optional[bool] = True

@router.get("/api/connected_accounts")
def list_connected_accounts():
    items = refresh_connected_accounts_cache(force=True)
    safe_items = []
    for r in items:
        plat = str(r.get("platform") or "").strip().lower()
        safe_items.append({
            "id": r.get("id"),
            "platform": plat,
            "account_id": r.get("account_id"),
            "account_name": r.get("account_name"),
            "username": r.get("username") or "",
            "avatar_url": r.get("avatar_url") or "",
            "connected_by": "TextBee.dev API" if plat == "sms" else (r.get("connected_by") or "External API"),
            "has_token": True
        })
    return {"status": "success", "accounts": safe_items}

@router.post("/api/connected_accounts/save")
def save_connected_accounts(payload: SaveConnectedAccountsPayload):
    if not payload.accounts:
        return {"status": "error", "message": "No accounts selected."}
    try:
        with db_engine.begin() as conn:
            for acc in payload.accounts:
                plat = acc.platform.strip().lower()
                aid = acc.account_id.strip()
                if not plat or not aid:
                    continue
                row_id = f"{plat}_{aid}"
                tok_val = (acc.access_token or "").strip()
                if not tok_val.startswith("EXTERNAL_API_MANAGED:"):
                    owner_k = get_zernio_key_for_account(aid, account_name=acc.account_name, platform=plat)
                    tok_val = f"EXTERNAL_API_MANAGED:{owner_k}" if owner_k else "EXTERNAL_API_MANAGED"

                conn.execute(
                    text("""
                        INSERT INTO glennbot_connected_accounts
                        (id, platform, account_id, account_name, username, avatar_url, access_token, connected_by)
                        VALUES (:id, :plat, :aid, :aname, :uname, :avatar, :tok, :cby)
                        ON CONFLICT (id) DO UPDATE SET
                            account_name = EXCLUDED.account_name,
                            username = EXCLUDED.username,
                            avatar_url = CASE WHEN EXCLUDED.avatar_url != '' THEN EXCLUDED.avatar_url ELSE glennbot_connected_accounts.avatar_url END,
                            access_token = EXCLUDED.access_token,
                            connected_by = 'External API'
                    """),
                    {
                        "id": row_id,
                        "plat": plat,
                        "aid": aid,
                        "aname": acc.account_name.strip() or aid,
                        "uname": (acc.username or "").strip(),
                        "avatar": (acc.avatar_url or "").strip(),
                        "tok": tok_val,
                        "cby": "External API"
                    }
                )
        refresh_connected_accounts_cache(force=True)
        ANALYTICS_CACHE["by_period"].clear()
        return {"status": "success", "saved_count": len(payload.accounts)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.delete("/api/connected_accounts/{item_id}")
def delete_connected_account(item_id: str, disconnect_remote: bool = False):
    try:
        with db_engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, platform, account_id FROM glennbot_connected_accounts WHERE id = :id"),
                {"id": item_id}
            ).mappings().first()
            conn.execute(
                text("DELETE FROM glennbot_connected_accounts WHERE id = :id"),
                {"id": item_id}
            )

        if disconnect_remote and row:
            acc_key = get_zernio_key_for_account(row["account_id"], platform=row.get("platform") or "")
            if acc_key:
                try:
                    HTTP_SESSION.delete(
                        f"{ZERNIO_BASE_URL}/accounts/{row['account_id']}",
                        headers=get_zernio_headers(acc_key),
                        timeout=15
                    )
                except Exception:
                    pass

        refresh_connected_accounts_cache(force=True)
        ANALYTICS_CACHE["by_period"].clear()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/oauth/connect_popup/{platform}")
def start_verified_oauth_popup(platform: str, request: Request):
    plat = platform.strip().lower()
    if plat not in ("facebook", "instagram", "tiktok", "youtube", "whatsapp", "telegram"):
        return {"status": "error", "message": f"Unsupported platform: {plat}"}

    pool = evaluate_external_api_pool_status(force_refresh=True)
    if not pool:
        return {
            "status": "error",
            "api_limit_reached": True,
            "message": "No External API Key configured. Click 'Manage API' to add one."
        }

    candidate_items = [item for item in pool if not item["is_full"]]
    if not candidate_items:
        return {
            "status": "error",
            "api_limit_reached": True,
            "message": f"All {len(pool)} External API key(s) have reached the {MAX_ACCOUNTS_PER_EXTERNAL_API}-account limit. Click 'Manage API' to add a new API key to the buffer."
        }

    last_error = "Could not retrieve or create an External API profile."
    for cand in candidate_items:
        cand_key = cand["api_key"]
        try:
            prof_res = get_zernio_default_profile_id(api_key=cand_key)
            profile_id = prof_res.get("profile_id")
            if not profile_id:
                last_error = prof_res.get("error") or last_error
                continue

            conn_resp = HTTP_SESSION.get(
                f"{ZERNIO_BASE_URL}/connect/{plat}",
                params={"profileId": profile_id},
                headers=get_zernio_headers(cand_key),
                timeout=20
            )
            conn_res = conn_resp.json() if conn_resp.text else {}
            data_sub = conn_res.get("data") if isinstance(conn_res.get("data"), dict) else {}
            auth_url = conn_res.get("authUrl") or conn_res.get("url") or data_sub.get("authUrl") or data_sub.get("url")
            verif_code = str(conn_res.get("code") or data_sub.get("code") or "").strip()
            bot_uname = str(conn_res.get("botUsername") or data_sub.get("botUsername") or "").strip().lstrip("@")
            instructions = conn_res.get("instructions") or data_sub.get("instructions") or []

            # Telegram in Zernio uses a Bot Verification Code flow (@LateScheduleBot + ZRN-XXXXXX code)
            if not auth_url and (verif_code or bot_uname):
                bot_uname = bot_uname or "LateScheduleBot"
                bot_url = f"https://t.me/{bot_uname}"
                promoted = False
                for entry in EXTERNAL_KEYS_STATE.get("cloudinary_entries", []):
                    if entry.get("api_key") == cand_key and not entry.get("forced_in_use"):
                        entry["forced_in_use"] = True
                        promoted = True
                EXTERNAL_KEYS_STATE["preferred_active_key"] = cand_key
                if promoted:
                    sync_external_keys_to_cloudinary()

                return {
                    "status": "success",
                    "connection_type": "telegram_bot_code",
                    "auth_url": bot_url,
                    "bot_url": bot_url,
                    "bot_username": bot_uname,
                    "verification_code": verif_code,
                    "instructions": instructions if isinstance(instructions, list) else [],
                    "expires_at": str(conn_res.get("expiresAt") or data_sub.get("expiresAt") or ""),
                    "expires_in": int(conn_res.get("expiresIn") or data_sub.get("expiresIn") or 900),
                    "mode": "external_api_oauth",
                    "platform": plat,
                    "active_key_masked": cand["masked_key"]
                }

            if not auth_url:
                last_error = conn_res.get("message") or conn_res.get("error") or str(conn_res)
                continue

            promoted = False
            for entry in EXTERNAL_KEYS_STATE.get("cloudinary_entries", []):
                if entry.get("api_key") == cand_key and not entry.get("forced_in_use"):
                    entry["forced_in_use"] = True
                    promoted = True
            EXTERNAL_KEYS_STATE["preferred_active_key"] = cand_key
            if promoted:
                sync_external_keys_to_cloudinary()

            return {
                "status": "success",
                "connection_type": "oauth_popup",
                "auth_url": auth_url,
                "mode": "external_api_oauth",
                "platform": plat,
                "active_key_masked": cand["masked_key"]
            }
        except Exception as e:
            last_error = str(e)
            continue

    return {
        "status": "error",
        "api_limit_reached": False,
        "message": f"Could not generate {plat.capitalize()} connection: {last_error}"
    }

@router.post("/api/oauth/meta/discover")
def discover_meta_accounts(payload: MetaDiscoverPayload):
    existing = refresh_connected_accounts_cache(force=True)
    existing_ids = {f"{r['platform']}_{r['account_id']}" for r in existing}

    fb_pages = []
    ig_accounts = []
    seen_fb_ids = set()
    seen_ig_ids = set()

    if not get_all_zernio_keys():
        return {
            "status": "error",
            "message": "No External API Key found in Manage API."
        }

    try:
        z_accounts = fetch_zernio_connected_accounts(force=True)
        for acc in z_accounts:
            plat = (acc.get("platform") or "").strip().lower()
            aid = str(acc.get("_id") or acc.get("id") or "")
            if not aid:
                continue
            uname = (acc.get("username") or acc.get("displayName") or "").strip().lstrip("@")
            dname = (acc.get("displayName") or acc.get("name") or uname or aid).strip()
            avatar = acc.get("avatarUrl") or acc.get("profilePictureUrl") or ""
            owner_key = acc.get("_zernio_api_key") or get_active_zernio_key()
            tok_marker = f"EXTERNAL_API_MANAGED:{owner_key}" if owner_key else "EXTERNAL_API_MANAGED"

            if plat == "facebook" and aid not in seen_fb_ids:
                seen_fb_ids.add(aid)
                fb_pages.append({
                    "platform": "facebook",
                    "account_id": aid,
                    "account_name": dname,
                    "username": uname or "Facebook Page",
                    "avatar_url": avatar,
                    "access_token": tok_marker,
                    "connected_by": "External API",
                    "already_connected": f"facebook_{aid}" in existing_ids
                })
            elif plat == "instagram" and aid not in seen_ig_ids:
                seen_ig_ids.add(aid)
                ig_accounts.append({
                    "platform": "instagram",
                    "account_id": aid,
                    "account_name": dname,
                    "username": uname or dname,
                    "avatar_url": avatar,
                    "access_token": tok_marker,
                    "connected_by": "External API",
                    "linked_fb_page": "External API Connected",
                    "already_connected": f"instagram_{aid}" in existing_ids
                })
    except Exception as e:
        print(f"[⚠️ EXTERNAL API META DISCOVER ERROR]: {e}")

    return {
        "status": "success",
        "connected_by": "External API",
        "facebook_pages": fb_pages,
        "instagram_accounts": ig_accounts
    }

@router.post("/api/oauth/tiktok/start")
def start_tiktok_oauth(provider: str = "external_api", request: Request = None):
    res = start_verified_oauth_popup("tiktok", request)
    if res.get("status") == "success":
        return {
            "status": "success",
            "provider": "external_api",
            "auth_url": res["auth_url"],
            "active_key_masked": res.get("active_key_masked", "")
        }
    return res

def is_post_account_connected(r_dict: Dict[str, Any], connected_items: Optional[List[Dict[str, Any]]] = None) -> bool:
    active_valid_keys = set(get_all_zernio_keys())
    if not active_valid_keys:
        return False

    items = connected_items if connected_items is not None else refresh_connected_accounts_cache(force=False)
    if not items:
        return False

    platform = (r_dict.get("platform") or "").strip().lower()
    page_id = str(r_dict.get("page_id") or r_dict.get("account_id") or "").strip()
    raw_acc_name = str(r_dict.get("account_name") or "").strip()
    acc_name = raw_acc_name.lstrip("@").lower()

    # Also include any cross-mapped Zernio _id <-> platformAccountId from ZERNIO_ACCOUNTS_CACHE
    equiv_ids = {page_id} if page_id else set()
    for za in (ZERNIO_ACCOUNTS_CACHE.get("accounts") or []):
        if not isinstance(za, dict):
            continue
        za_id = str(za.get("_id") or za.get("id") or "").strip()
        za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
        if page_id and page_id in (za_id, za_plat_id):
            if za_id:
                equiv_ids.add(za_id)
            if za_plat_id:
                equiv_ids.add(za_plat_id)

    for acc in items:
        acc_plat = (acc.get("platform") or "").strip().lower()
        if acc_plat != platform:
            continue

        raw_tok = (acc.get("access_token") or "").strip()
        bound_key = ""
        for prefix in ("EXTERNAL_API_MANAGED:", "ZERNIO_MANAGED:"):
            if raw_tok.startswith(prefix):
                bound_key = raw_tok.split(prefix, 1)[1].strip()
                break
        if bound_key and bound_key not in active_valid_keys:
            continue

        acc_id = str(acc.get("account_id") or "").strip()
        acc_uname = (acc.get("username") or "").strip().lstrip("@").lower()
        acc_dname = (acc.get("account_name") or "").strip().lstrip("@").lower()

        if acc_id and acc_id in equiv_ids:
            return True
        if acc_name and (
            (acc_dname and (acc_dname == acc_name or acc_dname in acc_name or acc_name in acc_dname))
            or (acc_uname and (acc_uname == acc_name or f"@{acc_uname}" in acc_name))
            or _is_same_social_page_name(raw_acc_name, acc.get("account_name") or "")
            or _is_same_social_page_name(raw_acc_name, acc.get("username") or "")
        ):
            return True
    return False

@router.get("/api/oauth/tiktok/discover")
def discover_tiktok_accounts(refresh: bool = True):
    try:
        existing = refresh_connected_accounts_cache(force=refresh)
        existing_ids = {f"{r['platform']}_{r['account_id']}" for r in existing}
        existing_by_uname = {
            (r.get("username") or "").strip().lstrip("@").lower(): r
            for r in existing if r.get("platform") == "tiktok"
        }

        z_tiktok_accounts = fetch_zernio_connected_accounts(platform="tiktok", force=refresh)
        results = []

        for acc in z_tiktok_accounts:
            aid = str(acc.get("_id") or acc.get("id") or "")
            if not aid:
                continue
            uname = (acc.get("username") or acc.get("displayName") or "tiktok_user").strip().lstrip("@")
            key = uname.lower()
            dname = acc.get("displayName") or acc.get("name") or f"@{uname}"
            avatar = acc.get("avatarUrl") or acc.get("profilePictureUrl") or ""
            owner_key = acc.get("_zernio_api_key") or get_active_zernio_key()
            tok_marker = f"EXTERNAL_API_MANAGED:{owner_key}" if owner_key else "EXTERNAL_API_MANAGED"

            results.append({
                "platform": "tiktok",
                "account_id": aid,
                "account_name": dname,
                "username": uname,
                "avatar_url": avatar,
                "access_token": tok_marker,
                "connected_by": f"@{uname} (External API)",
                "external_api_connected": True,
                "already_connected": (f"tiktok_{aid}" in existing_ids) or (key in existing_by_uname)
            })

        return {"status": "success", "tiktok_accounts": results}
    except Exception as e:
        return {"status": "error", "tiktok_accounts": [], "message": str(e)}

@router.post("/api/oauth/youtube/start")
def start_youtube_oauth(provider: str = "external_api", request: Request = None):
    res = start_verified_oauth_popup("youtube", request)
    if res.get("status") == "success":
        return {
            "status": "success",
            "provider": "external_api",
            "auth_url": res["auth_url"],
            "active_key_masked": res.get("active_key_masked", "")
        }
    return res

@router.get("/api/oauth/youtube/discover")
def discover_youtube_accounts(refresh: bool = True):
    try:
        existing = refresh_connected_accounts_cache(force=refresh)
        existing_ids = {f"{r['platform']}_{r['account_id']}" for r in existing}
        existing_by_uname = {
            (r.get("username") or "").strip().lstrip("@").lower(): r
            for r in existing if r.get("platform") == "youtube"
        }

        z_youtube_accounts = fetch_zernio_connected_accounts(platform="youtube", force=refresh)
        results = []

        for acc in z_youtube_accounts:
            aid = str(acc.get("_id") or acc.get("id") or "")
            if not aid:
                continue
            uname = (acc.get("username") or acc.get("displayName") or acc.get("name") or "youtube_channel").strip().lstrip("@")
            key = uname.lower()
            dname = acc.get("displayName") or acc.get("name") or f"@{uname}"
            avatar = acc.get("avatarUrl") or acc.get("profilePictureUrl") or ""
            owner_key = acc.get("_zernio_api_key") or get_active_zernio_key()
            tok_marker = f"EXTERNAL_API_MANAGED:{owner_key}" if owner_key else "EXTERNAL_API_MANAGED"

            results.append({
                "platform": "youtube",
                "account_id": aid,
                "account_name": dname,
                "username": uname,
                "avatar_url": avatar,
                "access_token": tok_marker,
                "connected_by": f"{dname} (External API)",
                "external_api_connected": True,
                "already_connected": (f"youtube_{aid}" in existing_ids) or (key in existing_by_uname)
            })

        return {"status": "success", "youtube_accounts": results}
    except Exception as e:
        return {"status": "error", "youtube_accounts": [], "message": str(e)}


@router.post("/api/oauth/whatsapp/start")
def start_whatsapp_oauth(provider: str = "external_api", request: Request = None):
    res = start_verified_oauth_popup("whatsapp", request)
    if res.get("status") == "success":
        return {
            **res,
            "status": "success",
            "provider": "external_api",
        }
    return res


@router.get("/api/oauth/whatsapp/discover")
def discover_whatsapp_accounts(refresh: bool = True):
    try:
        existing = refresh_connected_accounts_cache(force=refresh)
        existing_ids = {f"{r['platform']}_{r['account_id']}" for r in existing}
        z_wa_accounts = fetch_zernio_connected_accounts(platform="whatsapp", force=refresh)
        results = []
        for acc in z_wa_accounts:
            aid = str(acc.get("_id") or acc.get("id") or "")
            if not aid:
                continue
            uname = (acc.get("phoneNumber") or acc.get("phone") or acc.get("username") or acc.get("displayName") or "whatsapp_account").strip().lstrip("@")
            dname = acc.get("displayName") or acc.get("name") or uname
            avatar = acc.get("avatarUrl") or acc.get("profilePictureUrl") or ""
            owner_key = acc.get("_zernio_api_key") or get_active_zernio_key()
            tok_marker = f"EXTERNAL_API_MANAGED:{owner_key}" if owner_key else "EXTERNAL_API_MANAGED"
            results.append({
                "platform": "whatsapp",
                "account_id": aid,
                "account_name": dname,
                "username": uname,
                "avatar_url": avatar,
                "access_token": tok_marker,
                "connected_by": f"{dname} (External API)",
                "external_api_connected": True,
                "already_connected": f"whatsapp_{aid}" in existing_ids
            })
        return {"status": "success", "whatsapp_accounts": results}
    except Exception as e:
        return {"status": "error", "whatsapp_accounts": [], "message": str(e)}


@router.post("/api/oauth/telegram/start")
def start_telegram_oauth(provider: str = "external_api", request: Request = None):
    res = start_verified_oauth_popup("telegram", request)
    if res.get("status") == "success":
        return {
            **res,
            "status": "success",
            "provider": "external_api",
        }
    return res


@router.get("/api/oauth/telegram/discover")
def discover_telegram_accounts(refresh: bool = True):
    try:
        existing = refresh_connected_accounts_cache(force=refresh)
        existing_ids = {f"{r['platform']}_{r['account_id']}" for r in existing}
        z_tg_accounts = fetch_zernio_connected_accounts(platform="telegram", force=refresh)
        results = []
        for acc in z_tg_accounts:
            aid = str(acc.get("_id") or acc.get("id") or "")
            if not aid:
                continue
            uname = (acc.get("username") or acc.get("displayName") or acc.get("name") or "telegram_bot").strip().lstrip("@")
            dname = acc.get("displayName") or acc.get("name") or f"@{uname}"
            avatar = acc.get("avatarUrl") or acc.get("profilePictureUrl") or ""
            owner_key = acc.get("_zernio_api_key") or get_active_zernio_key()
            tok_marker = f"EXTERNAL_API_MANAGED:{owner_key}" if owner_key else "EXTERNAL_API_MANAGED"
            results.append({
                "platform": "telegram",
                "account_id": aid,
                "account_name": dname,
                "username": uname,
                "avatar_url": avatar,
                "access_token": tok_marker,
                "connected_by": f"{dname} (External API)",
                "external_api_connected": True,
                "already_connected": f"telegram_{aid}" in existing_ids
            })
        return {"status": "success", "telegram_accounts": results}
    except Exception as e:
        return {"status": "error", "telegram_accounts": [], "message": str(e)}
