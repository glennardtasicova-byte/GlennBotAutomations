import os
import io
import re
import uuid
import json
import time
import threading
import mimetypes
import urllib.parse
from datetime import datetime
from typing import Dict, Any
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api

from core.config import (
    BASE_DIR,
    HTTP_SESSION,
    MANILA_TZ,
    manila_tz,
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    GOOGLE_DRIVE_CLIENT_ID,
    GOOGLE_DRIVE_CLIENT_SECRET,
    GOOGLE_DRIVE_PROJECT_ID,
    GOOGLE_DRIVE_FOLDER_NAME,
    GOOGLE_DRIVE_FOLDER_ID,
    GOOGLE_DRIVE_REFRESH_TOKEN,
    CLOUDINARY_GDRIVE_TOKEN_PUBLIC_ID,
    LOCAL_GDRIVE_TOKEN_CACHE_PATH,
)

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)

# ==============================================================================
# --- GOOGLE DRIVE API v3 MEDIA STORAGE ENGINE ---
# ==============================================================================
GDRIVE_AUTH_LOCK = threading.Lock()
GDRIVE_AUTH_CACHE: Dict[str, Any] = {
    "loaded": False,
    "refresh_token": GOOGLE_DRIVE_REFRESH_TOKEN,
    "access_token": "",
    "expires_at": 0.0,
    "folder_id": GOOGLE_DRIVE_FOLDER_ID,
    "folder_name": GOOGLE_DRIVE_FOLDER_NAME,
    "connected_email": ""
}


def _load_gdrive_auth_store(force_cloud: bool = False) -> Dict[str, Any]:
    with GDRIVE_AUTH_LOCK:
        if GDRIVE_AUTH_CACHE.get("loaded") and not force_cloud:
            return dict(GDRIVE_AUTH_CACHE)

    env_rt = (os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN") or GOOGLE_DRIVE_REFRESH_TOKEN or "").strip()
    loaded_data: Dict[str, Any] = {}

    if os.path.exists(LOCAL_GDRIVE_TOKEN_CACHE_PATH) and not force_cloud:
        try:
            with open(LOCAL_GDRIVE_TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    loaded_data.update(d)
        except Exception:
            pass

    if (force_cloud or not loaded_data.get("refresh_token")) and CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        try:
            res = cloudinary.api.resource(CLOUDINARY_GDRIVE_TOKEN_PUBLIC_ID, resource_type="raw")
            sec_url = res.get("secure_url")
            if sec_url:
                sep = "&" if "?" in sec_url else "?"
                r = HTTP_SESSION.get(f"{sec_url}{sep}_t={int(time.time())}", timeout=15)
                if r.status_code == 200:
                    d = r.json()
                    if isinstance(d, dict):
                        loaded_data.update(d)
        except Exception:
            pass

    with GDRIVE_AUTH_LOCK:
        if env_rt and not loaded_data.get("refresh_token"):
            loaded_data["refresh_token"] = env_rt
        if loaded_data.get("refresh_token"):
            GDRIVE_AUTH_CACHE["refresh_token"] = str(loaded_data["refresh_token"]).strip()
        if loaded_data.get("folder_id"):
            GDRIVE_AUTH_CACHE["folder_id"] = str(loaded_data["folder_id"]).strip()
        if loaded_data.get("connected_email"):
            GDRIVE_AUTH_CACHE["connected_email"] = str(loaded_data["connected_email"]).strip()
        GDRIVE_AUTH_CACHE["loaded"] = True
        return dict(GDRIVE_AUTH_CACHE)


def _save_gdrive_auth_store(refresh_token: str = "", folder_id: str = "", connected_email: str = "") -> None:
    with GDRIVE_AUTH_LOCK:
        if refresh_token:
            GDRIVE_AUTH_CACHE["refresh_token"] = refresh_token.strip()
        if folder_id:
            GDRIVE_AUTH_CACHE["folder_id"] = folder_id.strip()
        if connected_email:
            GDRIVE_AUTH_CACHE["connected_email"] = connected_email.strip()
        GDRIVE_AUTH_CACHE["loaded"] = True
        payload = {
            "refresh_token": GDRIVE_AUTH_CACHE.get("refresh_token") or "",
            "folder_id": GDRIVE_AUTH_CACHE.get("folder_id") or "",
            "folder_name": GDRIVE_AUTH_CACHE.get("folder_name") or GOOGLE_DRIVE_FOLDER_NAME,
            "connected_email": GDRIVE_AUTH_CACHE.get("connected_email") or "",
            "updated_at": datetime.now(manila_tz).isoformat()
        }

    try:
        with open(LOCAL_GDRIVE_TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    rt_val = payload.get("refresh_token") or ""
    if rt_val:
        env_path = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as ef:
                    env_text = ef.read()
                if "GOOGLE_DRIVE_REFRESH_TOKEN=" in env_text:
                    env_text = re.sub(
                        r"^GOOGLE_DRIVE_REFRESH_TOKEN=.*$",
                        f"GOOGLE_DRIVE_REFRESH_TOKEN={rt_val}",
                        env_text,
                        flags=re.MULTILINE
                    )
                else:
                    env_text = env_text.rstrip() + f"\nGOOGLE_DRIVE_REFRESH_TOKEN={rt_val}\n"
                with open(env_path, "w", encoding="utf-8") as ef:
                    ef.write(env_text)
            except Exception:
                pass

    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        try:
            raw_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            cloudinary.uploader.upload(
                io.BytesIO(raw_bytes),
                resource_type="raw",
                public_id=CLOUDINARY_GDRIVE_TOKEN_PUBLIC_ID,
                overwrite=True,
                invalidate=True
            )
        except Exception as e:
            print(f"[⚠️ GDRIVE TOKEN CLOUDINARY SAVE WARNING]: {e}")


def is_gdrive_media_configured() -> bool:
    return bool(GOOGLE_DRIVE_CLIENT_ID and GOOGLE_DRIVE_CLIENT_SECRET)


def is_gdrive_authorized() -> bool:
    state = _load_gdrive_auth_store(force_cloud=False)
    return bool(state.get("refresh_token"))


def gdrive_get_access_token(force_refresh: bool = False) -> str:
    state = _load_gdrive_auth_store(force_cloud=False)
    now_ts = time.time()
    with GDRIVE_AUTH_LOCK:
        cached_tok = str(GDRIVE_AUTH_CACHE.get("access_token") or "").strip()
        exp_at = float(GDRIVE_AUTH_CACHE.get("expires_at") or 0.0)
        if not force_refresh and cached_tok and (exp_at - now_ts) > 120:
            return cached_tok

    refresh_tok = str(state.get("refresh_token") or "").strip()
    if not refresh_tok:
        state = _load_gdrive_auth_store(force_cloud=True)
        refresh_tok = str(state.get("refresh_token") or "").strip()

    if not refresh_tok:
        raise RuntimeError("Google Drive OAuth is not connected yet. Click 'Connect Google Drive' in the Files modal to authorize once.")

    resp = HTTP_SESSION.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_DRIVE_CLIENT_ID,
            "client_secret": GOOGLE_DRIVE_CLIENT_SECRET,
            "refresh_token": refresh_tok,
            "grant_type": "refresh_token"
        },
        timeout=25
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Google Drive token refresh failed ({resp.status_code}): {resp.text[:250]}")

    data = resp.json() or {}
    acc_tok = str(data.get("access_token") or "").strip()
    expires_in = int(data.get("expires_in") or 3500)
    if not acc_tok:
        raise RuntimeError("Google Drive OAuth response did not include an access_token.")

    with GDRIVE_AUTH_LOCK:
        GDRIVE_AUTH_CACHE["access_token"] = acc_tok
        GDRIVE_AUTH_CACHE["expires_at"] = time.time() + expires_in
    return acc_tok


def gdrive_ensure_vault_folder() -> str:
    state = _load_gdrive_auth_store(force_cloud=False)
    cached_fid = str(state.get("folder_id") or "").strip()
    if cached_fid:
        return cached_fid

    acc_tok = gdrive_get_access_token(force_refresh=False)
    headers = {"Authorization": f"Bearer {acc_tok}"}
    q_str = f"mimeType='application/vnd.google-apps.folder' and name='{GOOGLE_DRIVE_FOLDER_NAME}' and trashed=false"
    search_resp = HTTP_SESSION.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=headers,
        params={"q": q_str, "fields": "files(id, name)", "pageSize": 5},
        timeout=20
    )
    if search_resp.status_code == 200:
        files = (search_resp.json() or {}).get("files") or []
        if files and files[0].get("id"):
            fid = str(files[0]["id"]).strip()
            _save_gdrive_auth_store(folder_id=fid)
            return fid

    create_resp = HTTP_SESSION.post(
        "https://www.googleapis.com/drive/v3/files",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "name": GOOGLE_DRIVE_FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder"
        },
        params={"fields": "id, name"},
        timeout=20
    )
    if create_resp.status_code in (200, 201):
        fid = str((create_resp.json() or {}).get("id") or "").strip()
        if fid:
            _save_gdrive_auth_store(folder_id=fid)
            return fid
    return ""


def gdrive_set_file_public_reader(gdrive_file_id: str) -> bool:
    fid = (gdrive_file_id or "").strip()
    if not fid:
        return False
    try:
        acc_tok = gdrive_get_access_token(force_refresh=False)
        resp = HTTP_SESSION.post(
            f"https://www.googleapis.com/drive/v3/files/{fid}/permissions",
            headers={
                "Authorization": f"Bearer {acc_tok}",
                "Content-Type": "application/json"
            },
            json={"role": "reader", "type": "anyone"},
            timeout=15
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        print(f"[⚠️ GDRIVE PERMISSION WARNING] ({fid}): {e}")
        return False


def gdrive_init_resumable_upload(
    filename: str,
    content_type: str = "application/octet-stream",
    total_size: int = 0,
    origin: str = "",
    vault_file_id: str = ""
) -> str:
    acc_tok = gdrive_get_access_token(force_refresh=False)
    folder_id = ""
    try:
        folder_id = gdrive_ensure_vault_folder()
    except Exception:
        folder_id = ""

    clean_name = os.path.basename(str(filename or "file").strip())
    clean_name = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", clean_name) or "file"

    meta: Dict[str, Any] = {"name": clean_name}
    if folder_id:
        meta["parents"] = [folder_id]
    if vault_file_id:
        meta["appProperties"] = {"glennbot_file_id": str(vault_file_id).strip()}

    headers: Dict[str, str] = {
        "Authorization": f"Bearer {acc_tok}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": content_type or "application/octet-stream"
    }
    if total_size > 0:
        headers["X-Upload-Content-Length"] = str(total_size)
    if origin:
        headers["Origin"] = origin

    init_resp = HTTP_SESSION.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,size,mimeType,webViewLink,webContentLink,appProperties",
        headers=headers,
        data=json.dumps(meta).encode("utf-8"),
        timeout=25
    )
    if init_resp.status_code not in (200, 201):
        raise RuntimeError(f"Google Drive resumable upload init failed ({init_resp.status_code}): {init_resp.text[:250]}")

    session_uri = str(init_resp.headers.get("Location") or "").strip()
    if not session_uri:
        raise RuntimeError("Google Drive did not return a Location header for resumable upload.")
    return session_uri


def build_gdrive_direct_stream_url(gdrive_file_id: str) -> str:
    clean_id = (gdrive_file_id or "").strip()
    if not clean_id:
        return ""
    return f"/api/gdrive-media/{urllib.parse.quote(clean_id, safe='')}"


def build_gdrive_file_url(gdrive_file_name: str, force_fresh_token: bool = False) -> str:
    clean_name = (gdrive_file_name or "").strip().lstrip("/")
    if not clean_name:
        return ""
    if clean_name.startswith("http://") or clean_name.startswith("https://") or clean_name.startswith("/api/"):
        return clean_name
    if "/" not in clean_name and len(clean_name) >= 15:
        return build_gdrive_direct_stream_url(clean_name)
    return f"/api/gdrive-media/{urllib.parse.quote(clean_name, safe='/')}"


def extract_gdrive_file_id_from_url(url_str: str) -> str:
    u = (url_str or "").strip()
    if not u:
        return ""
    if "/api/gdrive-media/" in u:
        return u.split("/api/gdrive-media/", 1)[1].split("?")[0].strip("/")
    if "id=" in u and "drive.google.com" in u:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
            if qs.get("id"):
                return str(qs["id"][0]).strip()
        except Exception:
            pass
    return ""


def upload_media_to_gdrive(
    file_bytes: bytes,
    original_filename: str,
    media_type: str = "video",
    is_thumb: bool = False,
    custom_subfolder: str = "",
    custom_file_prefix: str = ""
) -> Dict[str, Any]:
    if not file_bytes:
        raise ValueError("Cannot upload empty file bytes to Google Drive.")

    clean_orig = os.path.basename(str(original_filename or "media").strip())
    clean_orig = re.sub(r"^file_[a-fA-F0-9]{8,16}_+", "", clean_orig) or "media"
    if is_thumb and not clean_orig.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        clean_orig = f"{clean_orig}.jpg"

    # Keep exact clean filename in Google Drive (without file_id prefix); file_id is stored in Cloudinary
    if custom_subfolder in ("files_vault", "spreadsheets") or str(custom_file_prefix).startswith("file_"):
        gdrive_filename = clean_orig
    else:
        safe_orig = re.sub(r"[^a-zA-Z0-9._-]", "_", clean_orig)
        prefix_part = f"{custom_file_prefix}_" if custom_file_prefix else f"{int(time.time())}_{uuid.uuid4().hex[:8]}_"
        gdrive_filename = f"{prefix_part}{safe_orig}"

    guessed_mime, _ = mimetypes.guess_type(clean_orig)
    if is_thumb:
        content_type = guessed_mime if (guessed_mime and guessed_mime.startswith("image/")) else "image/jpeg"
    elif media_type == "video":
        content_type = guessed_mime if (guessed_mime and guessed_mime.startswith("video/")) else "video/mp4"
    else:
        content_type = guessed_mime or "application/octet-stream"

    total_size = len(file_bytes)
    vault_fid = custom_file_prefix if str(custom_file_prefix).startswith("file_") else ""
    session_uri = gdrive_init_resumable_upload(
        filename=gdrive_filename,
        content_type=content_type,
        total_size=total_size,
        vault_file_id=vault_fid
    )

    up_resp = HTTP_SESSION.put(
        session_uri,
        headers={
            "Content-Type": content_type,
            "Content-Length": str(total_size)
        },
        data=file_bytes,
        timeout=600
    )
    if up_resp.status_code not in (200, 201):
        raise RuntimeError(f"Google Drive upload PUT failed ({up_resp.status_code}): {up_resp.text[:250]}")

    res_json = up_resp.json() or {}
    gdrive_file_id = str(res_json.get("id") or "").strip()
    if not gdrive_file_id:
        raise RuntimeError("Google Drive upload succeeded but returned no file ID.")

    gdrive_set_file_public_reader(gdrive_file_id)
    stream_url = build_gdrive_direct_stream_url(gdrive_file_id)
    print(f"[✅ GOOGLE DRIVE UPLOADED] {gdrive_filename} ({round(total_size / 1024, 1)} KB) -> ID: {gdrive_file_id}")
    return {
        "url": stream_url,
        "public_id": gdrive_file_id,
        "gdrive_file_id": gdrive_file_id,
        "gdrive_file_name": gdrive_filename,
        "web_view_link": str(res_json.get("webViewLink") or f"https://drive.google.com/file/d/{gdrive_file_id}/view"),
        "storage": "google_drive",
        "type": "image" if is_thumb else media_type,
        "is_thumb": bool(is_thumb)
    }


def delete_media_from_gdrive(gdrive_file_id: str, gdrive_file_name: str = "") -> bool:
    clean_id = (gdrive_file_id or "").strip()
    if not clean_id or "/" in clean_id:
        return False
    if not is_gdrive_authorized():
        return False
    try:
        acc_tok = gdrive_get_access_token(force_refresh=False)
        del_resp = HTTP_SESSION.delete(
            f"https://www.googleapis.com/drive/v3/files/{clean_id}",
            headers={"Authorization": f"Bearer {acc_tok}"},
            timeout=20
        )
        if del_resp.status_code in (200, 204, 404):
            print(f"[🧹 GOOGLE DRIVE CLEANUP] Deleted file ID: {clean_id} ({gdrive_file_name})")
            return True
    except Exception as e:
        print(f"[⚠️ GOOGLE DRIVE DELETE WARNING] ({clean_id}): {e}")
    return False
