import io
import re
import json
import time
import hashlib
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any
import pytz
import cloudinary
import cloudinary.uploader
import cloudinary.api

from core.config import (
    HTTP_SESSION,
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    ENV_EXTERNAL_API_KEY,
    ZERNIO_CLOUDINARY_PUBLIC_ID,
    CLOUDINARY_COMMENTS_PUBLIC_ID,
    CLOUDINARY_MESSAGES_PUBLIC_ID,
)
from core.database import extract_all_known_ids_for_row
from services.gdrive_service import (
    extract_gdrive_file_id_from_url,
    delete_media_from_gdrive,
)

# --- 2. CLOUDINARY CONFIGURATION (RESERVED FOR THE 6 JSON CONFIG/STATE FILES & LEGACY QUEUE) ---
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)


# ==============================================================================
# --- EXTERNAL API KEY POOL & BUFFER MANAGER (CLOUDINARY + .ENV PROTECTED) ---
# ==============================================================================
def _make_key_id(raw_key: str) -> str:
    return "api_" + hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()[:12]


def _mask_api_key(raw_key: str) -> str:
    k = (raw_key or "").strip()
    if len(k) > 12:
        return f"{k[:8]}••••{k[-4:]}"
    return "••••••••" if k else "None"


EXTERNAL_KEYS_STATE: Dict[str, Any] = {
    "cloudinary_entries": [],
    "preferred_active_key": "",
    "loaded_from_cloudinary": False
}


def load_external_keys_from_cloudinary() -> Dict[str, Any]:
    try:
        res = cloudinary.api.resource(ZERNIO_CLOUDINARY_PUBLIC_ID, resource_type="raw")
        sec_url = res.get("secure_url")
        if sec_url:
            sep = "&" if "?" in sec_url else "?"
            r = HTTP_SESSION.get(f"{sec_url}{sep}_t={int(time.time())}", timeout=15)
            if r.status_code == 200:
                data = r.json()
                raw_entries = data.get("entries") or data.get("keys") or []
                normalized_entries = []
                seen = set()

                if ENV_EXTERNAL_API_KEY:
                    seen.add(ENV_EXTERNAL_API_KEY)

                for item in raw_entries:
                    if isinstance(item, str):
                        k_str = item.strip()
                        if k_str and k_str not in seen:
                            seen.add(k_str)
                            normalized_entries.append({
                                "id": _make_key_id(k_str),
                                "api_key": k_str,
                                "added_at": data.get("updated_at") or datetime.now(pytz.timezone("Asia/Manila")).strftime("%b %d, %Y • %I:%M %p"),
                                "forced_in_use": True
                            })
                    elif isinstance(item, dict):
                        k_str = str(item.get("api_key") or "").strip()
                        if k_str and k_str not in seen:
                            seen.add(k_str)
                            normalized_entries.append({
                                "id": item.get("id") or _make_key_id(k_str),
                                "api_key": k_str,
                                "added_at": item.get("added_at") or datetime.now(pytz.timezone("Asia/Manila")).strftime("%b %d, %Y • %I:%M %p"),
                                "forced_in_use": bool(item.get("forced_in_use", False))
                            })

                EXTERNAL_KEYS_STATE["cloudinary_entries"] = normalized_entries
                EXTERNAL_KEYS_STATE["preferred_active_key"] = (data.get("active_key") or "").strip()
                EXTERNAL_KEYS_STATE["loaded_from_cloudinary"] = True
                print(f"[☁️ CLOUDINARY API POOL] Loaded {len(normalized_entries)} additional External API key(s) from Cloudinary.")
                return data
    except Exception:
        EXTERNAL_KEYS_STATE["loaded_from_cloudinary"] = True
    return {}


def sync_external_keys_to_cloudinary() -> bool:
    try:
        payload_obj = {
            "active_key": EXTERNAL_KEYS_STATE.get("preferred_active_key") or "",
            "entries": EXTERNAL_KEYS_STATE.get("cloudinary_entries") or [],
            "keys": [e["api_key"] for e in (EXTERNAL_KEYS_STATE.get("cloudinary_entries") or []) if e.get("api_key")],
            "updated_at": datetime.now(pytz.timezone("Asia/Manila")).isoformat()
        }
        payload_bytes = json.dumps(payload_obj, indent=2).encode("utf-8")
        cloudinary.uploader.upload(
            io.BytesIO(payload_bytes),
            public_id=ZERNIO_CLOUDINARY_PUBLIC_ID,
            resource_type="raw",
            overwrite=True,
            invalidate=True
        )
        return True
    except Exception as e:
        print(f"[❌ CLOUDINARY SYNC KEYS ERROR]: {e}")
        return False


def get_all_external_key_records() -> List[Dict[str, Any]]:
    if not EXTERNAL_KEYS_STATE["loaded_from_cloudinary"]:
        load_external_keys_from_cloudinary()

    records = []
    seen = set()
    if ENV_EXTERNAL_API_KEY:
        seen.add(ENV_EXTERNAL_API_KEY)
        records.append({
            "id": "env_default",
            "api_key": ENV_EXTERNAL_API_KEY,
            "is_env": True,
            "added_at": "Default (.env)",
            "forced_in_use": True
        })

    for entry in (EXTERNAL_KEYS_STATE.get("cloudinary_entries") or []):
        k_str = (entry.get("api_key") or "").strip()
        if k_str and k_str not in seen:
            seen.add(k_str)
            records.append({
                "id": entry.get("id") or _make_key_id(k_str),
                "api_key": k_str,
                "is_env": False,
                "added_at": entry.get("added_at") or "Saved in Cloudinary",
                "forced_in_use": bool(entry.get("forced_in_use", False))
            })
    return records


def get_all_zernio_keys() -> List[str]:
    return [r["api_key"] for r in get_all_external_key_records() if r.get("api_key")]


threading.Thread(target=load_external_keys_from_cloudinary, daemon=True).start()


# ==============================================================================
# --- CLOUDINARY COMMENTS & NOTIFICATIONS STORAGE MANAGER ---
# ==============================================================================
CLOUDINARY_COMMENTS_STORE: Dict[str, Any] = {
    "posts": {},
    "authors": {},
    "loaded": False
}
CLOUDINARY_COMMENTS_LOCK = threading.Lock()


def remember_author_identity(author_id: str, author_name: str, author_handle: str = "", author_avatar: str = ""):
    aid = str(author_id or "").strip()
    nm = str(author_name or "").strip()
    if not aid or not nm or nm in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"):
        return
    authors_map = CLOUDINARY_COMMENTS_STORE.setdefault("authors", {})
    prev = authors_map.get(aid) or {}
    authors_map[aid] = {
        "name": nm,
        "handle": str(author_handle or prev.get("handle") or "").strip(),
        "avatar": str(author_avatar or prev.get("avatar") or "").strip()
    }


def lookup_known_author_identity(author_id: str, record_id: str = "") -> Optional[Dict[str, str]]:
    aid = str(author_id or "").strip()
    if not aid:
        return None
    authors_map = CLOUDINARY_COMMENTS_STORE.get("authors") or {}
    if aid in authors_map and authors_map[aid].get("name"):
        return authors_map[aid]

    posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
    for rid, p_entry in posts_store.items():
        for cid, c_obj in (p_entry.get("comments") or {}).items():
            c_aid = str(c_obj.get("author_id") or "").strip()
            c_nm = str(c_obj.get("author_name") or "").strip()
            if c_aid == aid and c_nm and c_nm not in ("User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"):
                res = {
                    "name": c_nm,
                    "handle": str(c_obj.get("author_handle") or "").strip(),
                    "avatar": str(c_obj.get("author_avatar") or "").strip()
                }
                remember_author_identity(aid, res["name"], res["handle"], res["avatar"])
                return res
    return None


def load_comments_store_from_cloudinary() -> Dict[str, Any]:
    with CLOUDINARY_COMMENTS_LOCK:
        try:
            res = cloudinary.api.resource(CLOUDINARY_COMMENTS_PUBLIC_ID, resource_type="raw")
            sec_url = res.get("secure_url")
            if sec_url:
                sep = "&" if "?" in sec_url else "?"
                r = HTTP_SESSION.get(f"{sec_url}{sep}_t={int(time.time())}", timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and isinstance(data.get("posts"), dict):
                        CLOUDINARY_COMMENTS_STORE["posts"] = data["posts"]
                        if isinstance(data.get("authors"), dict):
                            CLOUDINARY_COMMENTS_STORE["authors"] = data["authors"]
                        CLOUDINARY_COMMENTS_STORE["loaded"] = True
                        for p_entry in data["posts"].values():
                            for c_obj in (p_entry.get("comments") or {}).values():
                                remember_author_identity(
                                    c_obj.get("author_id", ""),
                                    c_obj.get("author_name", ""),
                                    c_obj.get("author_handle", ""),
                                    c_obj.get("author_avatar", "")
                                )
                        print(f"[☁️ CLOUDINARY COMMENTS] Loaded comment history for {len(data['posts'])} post(s) from Cloudinary.")
                        return CLOUDINARY_COMMENTS_STORE["posts"]
        except Exception:
            pass
        CLOUDINARY_COMMENTS_STORE["loaded"] = True
        return CLOUDINARY_COMMENTS_STORE["posts"]


_CLOUDINARY_COMMENTS_UPLOAD_LOCK = threading.Lock()


def save_comments_store_to_cloudinary() -> bool:
    try:
        with CLOUDINARY_COMMENTS_LOCK:
            payload_obj = {
                "updated_at": datetime.now(pytz.timezone("Asia/Manila")).isoformat(),
                "authors": dict(CLOUDINARY_COMMENTS_STORE.get("authors") or {}),
                "posts": dict(CLOUDINARY_COMMENTS_STORE.get("posts") or {})
            }
            payload_bytes = json.dumps(payload_obj, indent=2).encode("utf-8")
        with _CLOUDINARY_COMMENTS_UPLOAD_LOCK:
            cloudinary.uploader.upload(
                io.BytesIO(payload_bytes),
                public_id=CLOUDINARY_COMMENTS_PUBLIC_ID,
                resource_type="raw",
                overwrite=True,
                invalidate=True
            )
        return True
    except Exception as e:
        print(f"[⚠️ CLOUDINARY COMMENTS SAVE ERROR]: {e}")
        return False


def save_comments_store_async():
    threading.Thread(target=save_comments_store_to_cloudinary, daemon=True).start()


threading.Thread(target=load_comments_store_from_cloudinary, daemon=True).start()


# ==============================================================================
# --- CLOUDINARY MESSAGES & UNIFIED INBOX STORAGE MANAGER ---
# ==============================================================================
CLOUDINARY_MESSAGES_STORE: Dict[str, Any] = {
    "conversations": {},  # {conv_key: {conversation_id, account_id, account_name, platform, participant_name, ... messages: []}}
    "deleted_message_ids": [],
    "loaded": False,
    "last_synced": 0.0
}
CLOUDINARY_MESSAGES_LOCK = threading.Lock()


def load_messages_store_from_cloudinary() -> Dict[str, Any]:
    with CLOUDINARY_MESSAGES_LOCK:
        try:
            res = cloudinary.api.resource(CLOUDINARY_MESSAGES_PUBLIC_ID, resource_type="raw")
            sec_url = res.get("secure_url")
            if sec_url:
                sep = "&" if "?" in sec_url else "?"
                r = HTTP_SESSION.get(f"{sec_url}{sep}_t={int(time.time())}", timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and isinstance(data.get("conversations"), dict):
                        CLOUDINARY_MESSAGES_STORE["conversations"] = data["conversations"]
                        if isinstance(data.get("deleted_message_ids"), list):
                            CLOUDINARY_MESSAGES_STORE["deleted_message_ids"] = [str(x) for x in data["deleted_message_ids"] if x]
                        CLOUDINARY_MESSAGES_STORE["loaded"] = True
                        print(f"[☁️ CLOUDINARY MESSAGES] Loaded {len(data['conversations'])} conversation(s) from Cloudinary.")
                        return CLOUDINARY_MESSAGES_STORE["conversations"]
        except Exception:
            pass
        CLOUDINARY_MESSAGES_STORE["loaded"] = True
        return CLOUDINARY_MESSAGES_STORE["conversations"]


_CLOUDINARY_MESSAGES_UPLOAD_LOCK = threading.Lock()


def save_messages_store_to_cloudinary() -> bool:
    try:
        with CLOUDINARY_MESSAGES_LOCK:
            payload_obj = {
                "updated_at": datetime.now(pytz.timezone("Asia/Manila")).isoformat(),
                "deleted_message_ids": list(CLOUDINARY_MESSAGES_STORE.get("deleted_message_ids") or [])[-5000:],
                "conversations": dict(CLOUDINARY_MESSAGES_STORE.get("conversations") or {})
            }
            payload_bytes = json.dumps(payload_obj, indent=2).encode("utf-8")
        with _CLOUDINARY_MESSAGES_UPLOAD_LOCK:
            cloudinary.uploader.upload(
                io.BytesIO(payload_bytes),
                public_id=CLOUDINARY_MESSAGES_PUBLIC_ID,
                resource_type="raw",
                overwrite=True,
                invalidate=True
            )
        return True
    except Exception as e:
        print(f"[⚠️ CLOUDINARY MESSAGES SAVE ERROR]: {e}")
        return False


def save_messages_store_async():
    threading.Thread(target=save_messages_store_to_cloudinary, daemon=True).start()


def _is_message_deleted_for_conversation(conv_obj: Dict[str, Any], msg_obj: Dict[str, Any]) -> bool:
    if not isinstance(msg_obj, dict):
        return True
    global_del = set(str(x) for x in (CLOUDINARY_MESSAGES_STORE.get("deleted_message_ids") or []) if x)
    local_del = set(str(x) for x in ((conv_obj or {}).get("deleted_message_ids") or []) if x)
    mid = str(msg_obj.get("id") or "").strip()
    pmid = str(msg_obj.get("platform_message_id") or "").strip()
    if (mid and (mid in global_del or mid in local_del)) or (pmid and (pmid in global_del or pmid in local_del)):
        return True
    del_epoch = float((conv_obj or {}).get("deleted_at_epoch") or 0.0)
    if del_epoch > 0.0:
        m_iso = str(msg_obj.get("created_iso") or "").strip()
        if m_iso:
            try:
                cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", m_iso.replace("Z", "+00:00"))
                m_ep = datetime.fromisoformat(cleaned).timestamp()
                if m_ep <= del_epoch:
                    return True
            except Exception:
                pass
    return False


def _filter_out_deleted_messages(conv_obj: Dict[str, Any], messages_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        m for m in (messages_list or [])
        if isinstance(m, dict) and not _is_message_deleted_for_conversation(conv_obj, m)
    ]


threading.Thread(target=load_messages_store_from_cloudinary, daemon=True).start()


# ==============================================================================
# --- TIKTOK PUBLIC AUTHOR & VIDEO RESOLVER ---
# ==============================================================================
LAST_TIKWM_CALL_TS = 0.0
TIKWM_LOCK = threading.Lock()


def fetch_tikwm_video_metadata(video_id: str, username: str = "") -> Dict[str, str]:
    global LAST_TIKWM_CALL_TS
    vid = str(video_id or "").strip()
    if not vid or not vid.isdigit():
        return {}
    clean_u = (username or "tiktok").strip().lstrip("@")
    tk_url = f"https://www.tiktok.com/@{clean_u}/video/{vid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    with TIKWM_LOCK:
        elapsed = time.time() - LAST_TIKWM_CALL_TS
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        try:
            LAST_TIKWM_CALL_TS = time.time()
            res = HTTP_SESSION.get("https://www.tikwm.com/api/", params={"url": tk_url}, headers=headers, timeout=12).json()
            if res.get("code") == 0 and isinstance(res.get("data"), dict):
                d = res["data"]
                return {
                    "caption": str(d.get("title") or "").strip(),
                    "video_url": str(d.get("play") or d.get("wmplay") or "").strip(),
                    "cover_url": str(d.get("cover") or d.get("origin_cover") or "").strip(),
                    "permalink": tk_url
                }
        except Exception as e:
            print(f"[⚠️ TIKWM VIDEO META WARNING ({vid})]: {e}")
    return {"permalink": tk_url}


def fetch_tikwm_comments_lookup(video_id: str) -> Dict[str, Dict[str, str]]:
    global LAST_TIKWM_CALL_TS
    vid = str(video_id or "").strip()
    if not vid or not vid.isdigit():
        return {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    lookup: Dict[str, Dict[str, str]] = {}

    with TIKWM_LOCK:
        elapsed = time.time() - LAST_TIKWM_CALL_TS
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        try:
            LAST_TIKWM_CALL_TS = time.time()
            res = HTTP_SESSION.get(f"https://www.tikwm.com/api/comment/list?url={vid}&count=50", headers=headers, timeout=12).json()
            if res.get("code") == 0:
                comm_list = (res.get("data") or {}).get("comments") or []
                for c in comm_list:
                    if not isinstance(c, dict):
                        continue
                    cid = str(c.get("id") or "").strip()
                    txt = (c.get("text") or "").strip().lower()
                    u_obj = c.get("user") or {}
                    uid = (u_obj.get("unique_id") or "").strip().lstrip("@")
                    nick = (u_obj.get("nickname") or "").strip()
                    avatar = u_obj.get("avatar") or ""
                    if nick and uid and nick.lower() != uid.lower():
                        full_name = f"{nick} (@{uid})"
                    else:
                        full_name = nick or (f"@{uid}" if uid else "")

                    if full_name:
                        info = {"name": full_name, "handle": f"@{uid}" if uid else "", "avatar": avatar}
                        if cid:
                            lookup[f"id:{cid}"] = info
                        if txt:
                            lookup[f"txt:{txt}"] = info

                    for rep in (c.get("reply_comment") or []):
                        if not isinstance(rep, dict):
                            continue
                        rcid = str(rep.get("id") or "").strip()
                        rtxt = (rep.get("text") or "").strip().lower()
                        ru_obj = rep.get("user") or {}
                        ruid = (ru_obj.get("unique_id") or "").strip().lstrip("@")
                        rnick = (ru_obj.get("nickname") or "").strip()
                        ravatar = ru_obj.get("avatar") or ""
                        if rnick and ruid and rnick.lower() != ruid.lower():
                            rfull = f"{rnick} (@{ruid})"
                        else:
                            rfull = rnick or (f"@{ruid}" if ruid else "")
                        if rfull:
                            rinfo = {"name": rfull, "handle": f"@{ruid}" if ruid else "", "avatar": ravatar}
                            if rcid:
                                lookup[f"id:{rcid}"] = rinfo
                            if rtxt:
                                lookup[f"txt:{rtxt}"] = rinfo
        except Exception as e:
            print(f"[⚠️ TIKWM AUTHOR LOOKUP WARNING ({vid})]: {e}")

    return lookup


def repair_unknown_authors_in_post_entry(p_entry: Dict[str, Any], db_post: Optional[Dict[str, Any]] = None) -> bool:
    if not isinstance(p_entry, dict):
        return False
    c_map = p_entry.get("comments") or {}
    if not c_map:
        return False

    generic_names = {"", "User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"}
    needs_repair = False

    known_commenters_in_post: List[Dict[str, str]] = []
    for cid, c_obj in c_map.items():
        c_nm = str(c_obj.get("author_name") or "").strip()
        c_aid = str(c_obj.get("author_id") or "").strip()
        c_hdl = str(c_obj.get("author_handle") or "").strip()
        c_av = str(c_obj.get("author_avatar") or "").strip()
        if c_nm not in generic_names and not c_obj.get("is_own_comment"):
            remember_author_identity(c_aid, c_nm, c_hdl, c_av)
            known_commenters_in_post.append({"name": c_nm, "handle": c_hdl, "avatar": c_av, "id": c_aid})
        else:
            needs_repair = True

        for rep in (c_obj.get("replies") or []):
            r_nm = str(rep.get("author_name") or "").strip()
            if r_nm in generic_names and not rep.get("is_own"):
                needs_repair = True

    if not needs_repair:
        return False

    tikwm_lookup: Dict[str, Dict[str, str]] = {}
    platform = (p_entry.get("platform") or (db_post or {}).get("platform") or "").strip().lower()
    if platform == "tiktok":
        tk_vid_id = ""
        for cid, c_obj in c_map.items():
            cand = str(c_obj.get("zernio_post_id") or c_obj.get("external_post_id") or "").strip()
            if cand.isdigit() and len(cand) > 12:
                tk_vid_id = cand
                break
        if not tk_vid_id and db_post:
            for kid in extract_all_known_ids_for_row(db_post):
                if kid.isdigit() and len(kid) > 12:
                    tk_vid_id = kid
                    break
        if tk_vid_id:
            tikwm_lookup = fetch_tikwm_comments_lookup(tk_vid_id)

    repaired_any = False
    for cid, c_obj in c_map.items():
        c_nm = str(c_obj.get("author_name") or "").strip()
        c_aid = str(c_obj.get("author_id") or "").strip()
        c_txt = (c_obj.get("message") or "").strip().lower()

        if c_nm in generic_names and not c_obj.get("is_own_comment"):
            resolved = (
                lookup_known_author_identity(c_aid)
                or tikwm_lookup.get(f"id:{cid}")
                or (tikwm_lookup.get(f"txt:{c_txt}") if c_txt else None)
            )
            if not resolved and len(known_commenters_in_post) >= 1:
                resolved = known_commenters_in_post[0]
            if resolved and resolved.get("name"):
                c_obj["author_name"] = resolved["name"]
                if resolved.get("handle"):
                    c_obj["author_handle"] = resolved["handle"]
                if resolved.get("avatar") and not c_obj.get("author_avatar"):
                    c_obj["author_avatar"] = resolved["avatar"]
                remember_author_identity(c_aid, c_obj["author_name"], c_obj.get("author_handle", ""), c_obj.get("author_avatar", ""))
                repaired_any = True

        parent_author_name = str(c_obj.get("author_name") or "").strip()
        parent_author_avatar = str(c_obj.get("author_avatar") or "").strip()

        for rep in (c_obj.get("replies") or []):
            if rep.get("is_own"):
                continue
            r_nm = str(rep.get("author_name") or "").strip()
            if r_nm in generic_names:
                r_id = str(rep.get("id") or "").strip()
                r_aid = str(rep.get("author_id") or "").strip()
                r_txt = (rep.get("message") or "").strip().lower()

                r_resolved = (
                    lookup_known_author_identity(r_aid)
                    or tikwm_lookup.get(f"id:{r_id}")
                    or (tikwm_lookup.get(f"txt:{r_txt}") if r_txt else None)
                )
                if not r_resolved and parent_author_name not in generic_names:
                    r_resolved = {"name": parent_author_name, "avatar": parent_author_avatar}
                elif not r_resolved and len(known_commenters_in_post) >= 1:
                    r_resolved = known_commenters_in_post[0]

                if r_resolved and r_resolved.get("name"):
                    rep["author_name"] = r_resolved["name"]
                    if r_resolved.get("avatar") and not rep.get("author_avatar"):
                        rep["author_avatar"] = r_resolved["avatar"]
                    repaired_any = True

    return repaired_any


def cleanup_cloudinary(media_items):
    """
    Hybrid post-publish media cleanup (retains function name 'cleanup_cloudinary' so existing
    APScheduler jobs stored in Supabase SQLAlchemyJobStore continue to run seamlessly).
    - Skips Zernio temporary media ('media.zernio.com'), which Zernio auto-purges after 7 days.
    - Skips Reusable Files Vault items ('is_vault_file': True / 'files_vault') so files in the "Files" modal remain permanently available.
    - Deletes temporary Google Drive media files for new scheduled posts.
    - Deletes Cloudinary media files for legacy queued posts.
    - Keeps lightweight thumbnail/cover images ('is_thumb': True) so dashboard & calendar previews never 404.
    """
    for m in (media_items or []):
        try:
            if not isinstance(m, dict) or m.get("is_thumb"):
                continue
            if (
                m.get("is_vault_file")
                or m.get("vault_file_id")
                or "files_vault" in str(m.get("gdrive_file_name") or "")
                or "files_vault" in str(m.get("public_id") or "")
            ):
                continue
            storage_type = str(m.get("storage") or "").strip().lower()
            raw_url = str(m.get("url") or "").strip()
            if storage_type == "zernio" or "media.zernio.com" in raw_url:
                continue
            if storage_type == "google_drive" or m.get("gdrive_file_id") or "/api/gdrive-media/" in raw_url:
                gd_fid = str(m.get("gdrive_file_id") or extract_gdrive_file_id_from_url(raw_url) or "").strip()
                gd_fname = str(m.get("gdrive_file_name") or m.get("public_id") or "").strip()
                delete_media_from_gdrive(gd_fid, gd_fname)
            elif m.get("public_id"):
                cloudinary.uploader.destroy(m["public_id"], resource_type=m.get("type", "video"))
                print(f"[🧹 CLOUDINARY LEGACY CLEANUP] Deleted published media file: {m.get('public_id')}")
        except Exception:
            pass
