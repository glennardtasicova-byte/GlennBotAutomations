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
    ZERNIO_BASE_URL,
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


def _extract_meta_oe_score(url: str) -> int:
    u = str(url or "").strip()
    if not u or not u.startswith(("http://", "https://")):
        return 0
    m = re.search(r"[?&]oe=([0-9A-Fa-f]{6,12})", u)
    if m:
        try:
            return int(m.group(1), 16)
        except Exception:
            return 1
    if "cdninstagram.com" in u or "fbcdn.net" in u:
        return 1
    return 0xFFFFFFFF


def _pick_freshest_avatar_url(*urls: str) -> str:
    best_url = ""
    best_score = 0
    for raw in urls:
        u = str(raw or "").strip()
        if not u:
            continue
        sc = _extract_meta_oe_score(u)
        if sc > best_score:
            best_score = sc
            best_url = u
    return best_url


def _normalize_social_handle_token(val: str) -> str:
    s = str(val or "").strip()
    if not s:
        return ""
    m_paren = re.search(r"\(@([A-Za-z0-9._-]+)\)", s)
    if m_paren:
        return m_paren.group(1).strip().lower()
    return s.lstrip("@").strip().lower()


IG_PARTICIPANT_AVATAR_CACHE: Dict[str, Any] = {
    "last_fetched": 0.0,
    "refreshing": False,
    "by_id": {},
    "by_handle": {},
}
_IG_AVATAR_CACHE_LOCK = threading.Lock()


def remember_author_identity(author_id: str, author_name: str, author_handle: str = "", author_avatar: str = ""):
    aid = str(author_id or "").strip()
    nm = str(author_name or "").strip()
    generic_set = {"", "User", "TikTok User", "Facebook User", "Instagram User", "YouTube User", "Portfolio Client", "Visitor", "Website Visitor"}
    clean_hdl = _normalize_social_handle_token(author_handle or (nm if nm and not nm.startswith("User") and " " not in nm else ""))
    av = str(author_avatar or "").strip()

    if aid and nm and nm not in generic_set:
        authors_map = CLOUDINARY_COMMENTS_STORE.setdefault("authors", {})
        prev = authors_map.get(aid) or {}
        best_av = _pick_freshest_avatar_url(av, prev.get("avatar", ""))
        best_hdl = str(author_handle or prev.get("handle") or (f"@{clean_hdl}" if clean_hdl else "")).strip()
        authors_map[aid] = {
            "name": nm,
            "handle": best_hdl,
            "avatar": best_av
        }
        if best_av:
            prev_id_entry = IG_PARTICIPANT_AVATAR_CACHE["by_id"].get(aid) or {}
            IG_PARTICIPANT_AVATAR_CACHE["by_id"][aid] = {
                "id": aid,
                "name": nm,
                "handle": best_hdl,
                "avatar": _pick_freshest_avatar_url(best_av, prev_id_entry.get("avatar", ""))
            }

    if clean_hdl and clean_hdl not in {g.lower() for g in generic_set} and av:
        prev_h = IG_PARTICIPANT_AVATAR_CACHE["by_handle"].get(clean_hdl) or {}
        IG_PARTICIPANT_AVATAR_CACHE["by_handle"][clean_hdl] = {
            "id": aid or prev_h.get("id", ""),
            "name": (nm if nm not in generic_set else "") or prev_h.get("name") or clean_hdl,
            "handle": f"@{clean_hdl}",
            "avatar": _pick_freshest_avatar_url(av, prev_h.get("avatar", ""))
        }


def _do_refresh_social_participant_avatars():
    try:
        all_keys = get_all_zernio_keys()
        if not all_keys:
            return
        updated_store = False
        for k in all_keys:
            headers = {"Authorization": f"Bearer {k.strip()}", "Content-Type": "application/json"}
            try:
                acc_resp = HTTP_SESSION.get(f"{ZERNIO_BASE_URL}/accounts", headers=headers, timeout=12)
                if acc_resp.status_code == 200:
                    acc_data = acc_resp.json()
                    acc_list = acc_data.get("accounts") if isinstance(acc_data, dict) else (acc_data if isinstance(acc_data, list) else [])
                    for a in (acc_list or []):
                        if not isinstance(a, dict):
                            continue
                        a_id = str(a.get("platformAccountId") or a.get("platformId") or a.get("_id") or a.get("id") or "").strip()
                        a_uname = _normalize_social_handle_token(a.get("username") or a.get("handle") or "")
                        a_name = str(a.get("displayName") or a.get("name") or a_uname or "").strip()
                        a_pic = str(a.get("profilePicture") or a.get("avatar") or a.get("picture") or "").strip()
                        if a_pic and (a_id or a_uname):
                            remember_author_identity(a_id or a_uname, a_name or a_uname, f"@{a_uname}" if a_uname else "", a_pic)
                        a_z_id = str(a.get("_id") or a.get("id") or "").strip()
                        a_plat = str(a.get("platform") or "").strip().lower()
                        if a_z_id and a_plat in ("instagram", "facebook"):
                            try:
                                conv_resp = HTTP_SESSION.get(
                                    f"{ZERNIO_BASE_URL}/inbox/conversations",
                                    params={"accountId": a_z_id},
                                    headers=headers,
                                    timeout=12
                                )
                                if conv_resp.status_code == 200:
                                    c_json = conv_resp.json()
                                    c_list = c_json.get("data") if isinstance(c_json, dict) else (c_json if isinstance(c_json, list) else [])
                                    if isinstance(c_list, dict):
                                        c_list = c_list.get("conversations") or c_list.get("items") or []
                                    convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
                                    for cv in (c_list or []):
                                        if not isinstance(cv, dict):
                                            continue
                                        p_id = str(cv.get("participantId") or cv.get("senderId") or "").strip()
                                        p_uname = _normalize_social_handle_token(cv.get("participantUsername") or cv.get("participantHandle") or cv.get("username") or "")
                                        p_name = str(cv.get("participantName") or p_uname or "").strip()
                                        p_pic = str(cv.get("participantPicture") or cv.get("participantAvatar") or "").strip()
                                        if p_pic and (p_id or p_uname):
                                            remember_author_identity(p_id or p_uname, p_name or p_uname, f"@{p_uname}" if p_uname else "", p_pic)
                                            for st_conv in convs_store.values():
                                                if not isinstance(st_conv, dict):
                                                    continue
                                                st_pid = str(st_conv.get("participant_id") or "").strip()
                                                st_phdl = _normalize_social_handle_token(st_conv.get("participant_handle") or "")
                                                if (p_id and st_pid == p_id) or (p_uname and st_phdl == p_uname):
                                                    best_conv_av = _pick_freshest_avatar_url(p_pic, st_conv.get("participant_avatar", ""))
                                                    if best_conv_av and st_conv.get("participant_avatar") != best_conv_av:
                                                        st_conv["participant_avatar"] = best_conv_av
                            except Exception:
                                pass
            except Exception:
                pass

        # Also heal any active comments in CLOUDINARY_COMMENTS_STORE whose avatar was missing or expired
        posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
        for p_entry in posts_store.values():
            if not isinstance(p_entry, dict):
                continue
            for c_obj in (p_entry.get("comments") or {}).values():
                if not isinstance(c_obj, dict):
                    continue
                c_aid = str(c_obj.get("author_id") or "").strip()
                c_hdl = str(c_obj.get("author_handle") or "").strip()
                c_nm = str(c_obj.get("author_name") or "").strip()
                known = lookup_known_author_identity(c_aid, author_handle=c_hdl, author_name=c_nm, _skip_bg_trigger=True)
                if known and known.get("avatar"):
                    best_c_av = _pick_freshest_avatar_url(known["avatar"], c_obj.get("author_avatar", ""))
                    if best_c_av and c_obj.get("author_avatar") != best_c_av:
                        c_obj["author_avatar"] = best_c_av
                        updated_store = True
                for rep in (c_obj.get("replies") or []):
                    if not isinstance(rep, dict) or rep.get("is_own"):
                        continue
                    r_aid = str(rep.get("author_id") or "").strip()
                    r_nm = str(rep.get("author_name") or "").strip()
                    r_known = lookup_known_author_identity(r_aid, author_name=r_nm, _skip_bg_trigger=True)
                    if r_known and r_known.get("avatar"):
                        best_r_av = _pick_freshest_avatar_url(r_known["avatar"], rep.get("author_avatar", ""))
                        if best_r_av and rep.get("author_avatar") != best_r_av:
                            rep["author_avatar"] = best_r_av
                            updated_store = True
        if updated_store:
            save_comments_store_async()
        IG_PARTICIPANT_AVATAR_CACHE["last_fetched"] = time.time()
    except Exception as e:
        print(f"[⚠️ IG PARTICIPANT AVATAR REFRESH WARNING]: {e}")
    finally:
        IG_PARTICIPANT_AVATAR_CACHE["refreshing"] = False


def refresh_social_participant_avatars_cache(force: bool = False, background: bool = True):
    now_ts = time.time()
    with _IG_AVATAR_CACHE_LOCK:
        if IG_PARTICIPANT_AVATAR_CACHE.get("refreshing"):
            return
        min_ttl = 20.0 if force else 600.0
        if (now_ts - float(IG_PARTICIPANT_AVATAR_CACHE.get("last_fetched") or 0.0)) < min_ttl:
            return
        IG_PARTICIPANT_AVATAR_CACHE["refreshing"] = True

    if background:
        threading.Thread(target=_do_refresh_social_participant_avatars, daemon=True).start()
    else:
        _do_refresh_social_participant_avatars()


def lookup_known_author_identity(
    author_id: str,
    record_id: str = "",
    author_handle: str = "",
    author_name: str = "",
    _skip_bg_trigger: bool = False
) -> Optional[Dict[str, str]]:
    if not _skip_bg_trigger:
        refresh_social_participant_avatars_cache(force=False, background=True)

    aid = str(author_id or "").strip()
    generic_names = {"", "User", "TikTok User", "Facebook User", "Instagram User", "YouTube User", "Portfolio Client", "Visitor", "Website Visitor"}
    generic_lower = {g.lower() for g in generic_names}

    clean_handle = _normalize_social_handle_token(author_handle)
    clean_name_token = _normalize_social_handle_token(author_name) if author_name and author_name not in generic_names else ""
    handle_candidates = {h for h in (clean_handle, clean_name_token, _normalize_social_handle_token(aid) if aid and not aid.isdigit() else "") if h and h not in generic_lower}

    if not aid and not handle_candidates:
        return None

    best_name = str(author_name or "").strip() if str(author_name or "").strip() not in generic_names else ""
    best_handle = str(author_handle or "").strip()
    best_avatar = ""

    # 1. Check live IG_PARTICIPANT_AVATAR_CACHE
    if aid and aid in IG_PARTICIPANT_AVATAR_CACHE["by_id"]:
        hit = IG_PARTICIPANT_AVATAR_CACHE["by_id"][aid]
        if not best_name and hit.get("name") not in generic_names:
            best_name = hit.get("name", "")
        if not best_handle and hit.get("handle"):
            best_handle = hit.get("handle", "")
        best_avatar = _pick_freshest_avatar_url(best_avatar, hit.get("avatar", ""))

    for h_cand in handle_candidates:
        if h_cand in IG_PARTICIPANT_AVATAR_CACHE["by_handle"]:
            hit_h = IG_PARTICIPANT_AVATAR_CACHE["by_handle"][h_cand]
            if not best_name and hit_h.get("name") not in generic_names:
                best_name = hit_h.get("name", "")
            if not best_handle and hit_h.get("handle"):
                best_handle = hit_h.get("handle", "")
            best_avatar = _pick_freshest_avatar_url(best_avatar, hit_h.get("avatar", ""))

    # 2. Check CLOUDINARY_COMMENTS_STORE["authors"]
    authors_map = CLOUDINARY_COMMENTS_STORE.get("authors") or {}
    if aid and aid in authors_map:
        a_hit = authors_map[aid] or {}
        if not best_name and a_hit.get("name") not in generic_names:
            best_name = str(a_hit.get("name") or "")
        if not best_handle and a_hit.get("handle"):
            best_handle = str(a_hit.get("handle") or "")
        best_avatar = _pick_freshest_avatar_url(best_avatar, a_hit.get("avatar", ""))

    if handle_candidates:
        for a_k, a_val in authors_map.items():
            if not isinstance(a_val, dict):
                continue
            av_hdl = _normalize_social_handle_token(a_val.get("handle") or "")
            av_nm = _normalize_social_handle_token(a_val.get("name") or "")
            if (av_hdl and av_hdl in handle_candidates) or (av_nm and av_nm in handle_candidates):
                if not best_name and a_val.get("name") not in generic_names:
                    best_name = str(a_val.get("name") or "")
                if not best_handle and a_val.get("handle"):
                    best_handle = str(a_val.get("handle") or "")
                best_avatar = _pick_freshest_avatar_url(best_avatar, a_val.get("avatar", ""))

    # 3. Check CLOUDINARY_MESSAGES_STORE["conversations"] (where Instagram/Facebook DM participant avatars are stored!)
    convs_store = CLOUDINARY_MESSAGES_STORE.get("conversations") or {}
    for conv in convs_store.values():
        if not isinstance(conv, dict):
            continue
        c_pid = str(conv.get("participant_id") or "").strip()
        c_pname = str(conv.get("participant_name") or "").strip()
        c_phdl = _normalize_social_handle_token(conv.get("participant_handle") or "")
        c_pname_tok = _normalize_social_handle_token(c_pname)
        c_pav = str(conv.get("participant_avatar") or "").strip()
        if not c_pav and not (c_pname and c_pname not in generic_names):
            continue
        id_match = bool(aid and c_pid and c_pid == aid)
        hdl_match = bool(handle_candidates and ((c_phdl and c_phdl in handle_candidates) or (c_pname_tok and c_pname_tok in handle_candidates)))
        if id_match or hdl_match:
            if not best_name and c_pname and c_pname not in generic_names:
                best_name = c_pname
            if not best_handle and c_phdl:
                best_handle = f"@{c_phdl}"
            best_avatar = _pick_freshest_avatar_url(best_avatar, c_pav)

    # 4. Check connected accounts cache (in case commenter is one of the user's connected accounts e.g. @glenntasico)
    try:
        import sys as _sys
        z_mod = _sys.modules.get("services.zernio_service")
        if z_mod is not None:
            z_accs = (getattr(z_mod, "ZERNIO_ACCOUNTS_CACHE", {}) or {}).get("accounts") or []
            for za in z_accs:
                if not isinstance(za, dict):
                    continue
                za_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("_id") or za.get("id") or "").strip()
                za_uname = _normalize_social_handle_token(za.get("username") or za.get("handle") or "")
                za_name = str(za.get("displayName") or za.get("name") or "").strip()
                za_pic = str(za.get("profilePicture") or za.get("avatar") or za.get("picture") or "").strip()
                if (aid and za_id == aid) or (za_uname and za_uname in handle_candidates):
                    if not best_name and za_name not in generic_names:
                        best_name = za_name
                    if not best_handle and za_uname:
                        best_handle = f"@{za_uname}"
                    best_avatar = _pick_freshest_avatar_url(best_avatar, za_pic)
            conn_items = (getattr(z_mod, "CONNECTED_ACCOUNTS_CACHE", {}) or {}).get("items") or []
            for ci in conn_items:
                if not isinstance(ci, dict):
                    continue
                ci_id = str(ci.get("account_id") or "").strip()
                ci_uname = _normalize_social_handle_token(ci.get("username") or "")
                ci_pic = str(ci.get("avatar_url") or ci.get("profile_picture") or "").strip()
                if (aid and ci_id == aid) or (ci_uname and ci_uname in handle_candidates):
                    best_avatar = _pick_freshest_avatar_url(best_avatar, ci_pic)
    except Exception:
        pass

    # 5. Check CLOUDINARY_COMMENTS_STORE["posts"]
    posts_store = CLOUDINARY_COMMENTS_STORE.get("posts") or {}
    for rid, p_entry in posts_store.items():
        if not isinstance(p_entry, dict):
            continue
        for cid, c_obj in (p_entry.get("comments") or {}).items():
            if not isinstance(c_obj, dict):
                continue
            c_aid = str(c_obj.get("author_id") or "").strip()
            c_nm = str(c_obj.get("author_name") or "").strip()
            c_hdl = _normalize_social_handle_token(c_obj.get("author_handle") or "")
            c_nm_tok = _normalize_social_handle_token(c_nm)
            c_av = str(c_obj.get("author_avatar") or "").strip()
            if (aid and c_aid == aid) or (handle_candidates and ((c_hdl and c_hdl in handle_candidates) or (c_nm_tok and c_nm_tok in handle_candidates))):
                if not best_name and c_nm and c_nm not in generic_names:
                    best_name = c_nm
                if not best_handle and c_hdl:
                    best_handle = f"@{c_hdl}"
                best_avatar = _pick_freshest_avatar_url(best_avatar, c_av)

    if best_name or best_avatar:
        res = {
            "name": best_name or (f"@{clean_handle}" if clean_handle else "User"),
            "handle": best_handle or (f"@{clean_handle}" if clean_handle else ""),
            "avatar": best_avatar
        }
        if aid and res["name"] not in generic_names:
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
TIKWM_META_CACHE: Dict[str, Dict[str, Any]] = {}
TIKWM_COMMENTS_CACHE: Dict[str, Dict[str, Any]] = {}
TIKWM_BACKOFF_UNTIL_TS = 0.0
TIKWM_LAST_WARN_TS = 0.0


def fetch_tikwm_video_metadata(video_id: str, username: str = "") -> Dict[str, str]:
    global LAST_TIKWM_CALL_TS, TIKWM_BACKOFF_UNTIL_TS, TIKWM_LAST_WARN_TS
    vid = str(video_id or "").strip()
    if not vid or not vid.isdigit():
        return {}
    clean_u = (username or "tiktok").strip().lstrip("@")
    tk_url = f"https://www.tiktok.com/@{clean_u}/video/{vid}"

    now_ts = time.time()
    cached_entry = TIKWM_META_CACHE.get(vid)
    if cached_entry and now_ts < float(cached_entry.get("exp") or 0.0):
        res_copy = dict(cached_entry.get("data") or {})
        if not res_copy.get("permalink"):
            res_copy["permalink"] = tk_url
        return res_copy

    if now_ts < TIKWM_BACKOFF_UNTIL_TS:
        TIKWM_META_CACHE[vid] = {"exp": now_ts + 3600.0, "data": {"permalink": tk_url}}
        return {"permalink": tk_url}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    with TIKWM_LOCK:
        now_locked = time.time()
        cached_locked = TIKWM_META_CACHE.get(vid)
        if cached_locked and now_locked < float(cached_locked.get("exp") or 0.0):
            res_copy = dict(cached_locked.get("data") or {})
            if not res_copy.get("permalink"):
                res_copy["permalink"] = tk_url
            return res_copy

        if now_locked < TIKWM_BACKOFF_UNTIL_TS:
            TIKWM_META_CACHE[vid] = {"exp": now_locked + 3600.0, "data": {"permalink": tk_url}}
            return {"permalink": tk_url}

        elapsed = now_locked - LAST_TIKWM_CALL_TS
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        try:
            LAST_TIKWM_CALL_TS = time.time()
            raw_resp = HTTP_SESSION.get("https://www.tikwm.com/api/", params={"url": tk_url}, headers=headers, timeout=10)
            raw_text = (raw_resp.text or "").strip()
            if raw_resp.status_code != 200 or not raw_text.startswith("{"):
                TIKWM_BACKOFF_UNTIL_TS = time.time() + 1800.0
                TIKWM_META_CACHE[vid] = {"exp": time.time() + 3600.0, "data": {"permalink": tk_url}}
                if (time.time() - TIKWM_LAST_WARN_TS) > 1800.0:
                    TIKWM_LAST_WARN_TS = time.time()
                    print(f"[ℹ️ TIKWM COOLDOWN]: TikWM returned non-JSON/rate-limit (HTTP {raw_resp.status_code}); pausing TikWM lookups for 30m.")
                return {"permalink": tk_url}

            res = raw_resp.json()
            if res.get("code") == 0 and isinstance(res.get("data"), dict):
                d = res["data"]
                meta_out = {
                    "caption": str(d.get("title") or "").strip(),
                    "video_url": str(d.get("play") or d.get("wmplay") or "").strip(),
                    "cover_url": str(d.get("cover") or d.get("origin_cover") or "").strip(),
                    "permalink": tk_url
                }
                TIKWM_META_CACHE[vid] = {"exp": time.time() + 21600.0, "data": meta_out}
                return dict(meta_out)
        except Exception as e:
            TIKWM_BACKOFF_UNTIL_TS = time.time() + 1800.0
            if (time.time() - TIKWM_LAST_WARN_TS) > 1800.0:
                TIKWM_LAST_WARN_TS = time.time()
                print(f"[⚠️ TIKWM VIDEO META WARNING ({vid})]: {e} (cooldown 30m)")
        TIKWM_META_CACHE[vid] = {"exp": time.time() + 3600.0, "data": {"permalink": tk_url}}
    return {"permalink": tk_url}


def fetch_tikwm_comments_lookup(video_id: str) -> Dict[str, Dict[str, str]]:
    global LAST_TIKWM_CALL_TS, TIKWM_BACKOFF_UNTIL_TS, TIKWM_LAST_WARN_TS
    vid = str(video_id or "").strip()
    if not vid or not vid.isdigit():
        return {}

    now_ts = time.time()
    cached_c = TIKWM_COMMENTS_CACHE.get(vid)
    if cached_c and now_ts < float(cached_c.get("exp") or 0.0):
        return dict(cached_c.get("data") or {})

    if now_ts < TIKWM_BACKOFF_UNTIL_TS:
        TIKWM_COMMENTS_CACHE[vid] = {"exp": now_ts + 1800.0, "data": {}}
        return {}

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    lookup: Dict[str, Dict[str, str]] = {}

    with TIKWM_LOCK:
        now_locked = time.time()
        if now_locked < TIKWM_BACKOFF_UNTIL_TS:
            TIKWM_COMMENTS_CACHE[vid] = {"exp": now_locked + 1800.0, "data": {}}
            return {}

        elapsed = now_locked - LAST_TIKWM_CALL_TS
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        try:
            LAST_TIKWM_CALL_TS = time.time()
            raw_resp = HTTP_SESSION.get(f"https://www.tikwm.com/api/comment/list?url={vid}&count=50", headers=headers, timeout=10)
            raw_text = (raw_resp.text or "").strip()
            if raw_resp.status_code != 200 or not raw_text.startswith("{"):
                TIKWM_BACKOFF_UNTIL_TS = time.time() + 1800.0
                TIKWM_COMMENTS_CACHE[vid] = {"exp": time.time() + 1800.0, "data": {}}
                return {}

            res = raw_resp.json()
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
            TIKWM_COMMENTS_CACHE[vid] = {"exp": time.time() + 3600.0, "data": lookup}
        except Exception as e:
            TIKWM_BACKOFF_UNTIL_TS = time.time() + 1800.0
            TIKWM_COMMENTS_CACHE[vid] = {"exp": time.time() + 1800.0, "data": {}}
            if (time.time() - TIKWM_LAST_WARN_TS) > 1800.0:
                TIKWM_LAST_WARN_TS = time.time()
                print(f"[⚠️ TIKWM AUTHOR LOOKUP WARNING ({vid})]: {e} (cooldown 30m)")

    return lookup


def repair_unknown_authors_in_post_entry(p_entry: Dict[str, Any], db_post: Optional[Dict[str, Any]] = None) -> bool:
    if not isinstance(p_entry, dict):
        return False
    c_map = p_entry.get("comments") or {}
    if not c_map:
        return False

    generic_names = {"", "User", "TikTok User", "Facebook User", "Instagram User", "YouTube User"}
    needs_name_repair = False
    repaired_any = False

    known_commenters_in_post: List[Dict[str, str]] = []
    for cid, c_obj in c_map.items():
        c_nm = str(c_obj.get("author_name") or "").strip()
        c_aid = str(c_obj.get("author_id") or "").strip()
        c_hdl = str(c_obj.get("author_handle") or "").strip()
        c_av = str(c_obj.get("author_avatar") or "").strip()
        if c_nm not in generic_names and not c_obj.get("is_own_comment"):
            known_id = lookup_known_author_identity(c_aid, author_handle=c_hdl, author_name=c_nm)
            if known_id and known_id.get("avatar"):
                best_av = _pick_freshest_avatar_url(known_id["avatar"], c_av)
                if best_av and best_av != c_av:
                    c_obj["author_avatar"] = best_av
                    c_av = best_av
                    repaired_any = True
            remember_author_identity(c_aid, c_nm, c_hdl, c_av)
            known_commenters_in_post.append({"name": c_nm, "handle": c_hdl, "avatar": c_av, "id": c_aid})
        elif not c_obj.get("is_own_comment"):
            needs_name_repair = True

        for rep in (c_obj.get("replies") or []):
            if rep.get("is_own"):
                continue
            r_nm = str(rep.get("author_name") or "").strip()
            r_aid = str(rep.get("author_id") or "").strip()
            r_av = str(rep.get("author_avatar") or "").strip()
            if r_nm in generic_names:
                needs_name_repair = True
            else:
                r_known = lookup_known_author_identity(r_aid, author_name=r_nm)
                if r_known and r_known.get("avatar"):
                    best_r_av = _pick_freshest_avatar_url(r_known["avatar"], r_av)
                    if best_r_av and best_r_av != r_av:
                        rep["author_avatar"] = best_r_av
                        repaired_any = True

    if not needs_name_repair:
        return repaired_any

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

    for cid, c_obj in c_map.items():
        c_nm = str(c_obj.get("author_name") or "").strip()
        c_aid = str(c_obj.get("author_id") or "").strip()
        c_hdl = str(c_obj.get("author_handle") or "").strip()
        c_txt = (c_obj.get("message") or "").strip().lower()

        if c_nm in generic_names and not c_obj.get("is_own_comment"):
            resolved = (
                lookup_known_author_identity(c_aid, author_handle=c_hdl, author_name=c_nm)
                or tikwm_lookup.get(f"id:{cid}")
                or (tikwm_lookup.get(f"txt:{c_txt}") if c_txt else None)
            )
            if not resolved and len(known_commenters_in_post) >= 1:
                resolved = known_commenters_in_post[0]
            if resolved and resolved.get("name"):
                c_obj["author_name"] = resolved["name"]
                if resolved.get("handle"):
                    c_obj["author_handle"] = resolved["handle"]
                if resolved.get("avatar"):
                    c_obj["author_avatar"] = _pick_freshest_avatar_url(resolved["avatar"], c_obj.get("author_avatar", ""))
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
                    lookup_known_author_identity(r_aid, author_name=r_nm)
                    or tikwm_lookup.get(f"id:{r_id}")
                    or (tikwm_lookup.get(f"txt:{r_txt}") if r_txt else None)
                )
                if not r_resolved and parent_author_name not in generic_names:
                    r_resolved = {"name": parent_author_name, "avatar": parent_author_avatar}
                elif not r_resolved and len(known_commenters_in_post) >= 1:
                    r_resolved = known_commenters_in_post[0]

                if r_resolved and r_resolved.get("name"):
                    rep["author_name"] = r_resolved["name"]
                    if r_resolved.get("avatar"):
                        rep["author_avatar"] = _pick_freshest_avatar_url(r_resolved["avatar"], rep.get("author_avatar", ""))
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
