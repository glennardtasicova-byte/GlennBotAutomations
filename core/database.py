import re
import sys
import time
import hashlib
import unicodedata
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import pytz
from sqlalchemy import create_engine, text
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from core.config import (
    DATABASE_URL,
    _DB_CONNECT_ARGS,
    MANILA_TZ,
    FAST_DB_READ_CACHE_LOCK,
    FAST_DB_READ_CACHE,
    _invalidate_fast_db_cache,
)

# --- 3. DATABASE ENGINE & SCHEDULER CONFIGURATION (SUPABASE / SQLITE) ---
if DATABASE_URL.startswith("sqlite"):
    db_engine = create_engine(
        DATABASE_URL,
        connect_args=_DB_CONNECT_ARGS,
        pool_pre_ping=True,
    )
else:
    db_engine = create_engine(
        DATABASE_URL,
        connect_args=_DB_CONNECT_ARGS,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=20,
        max_overflow=40,
        pool_timeout=30
    )


def _coerce_db_datetime(val: Any, default_tz=MANILA_TZ) -> Optional[datetime]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone(default_tz)
        return pytz.utc.localize(val).astimezone(default_tz)
    try:
        s = str(val).strip()
        if not s:
            return None
        cleaned = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            return dt.astimezone(default_tz)
        return pytz.utc.localize(dt).astimezone(default_tz)
    except Exception:
        return None


def init_records_db():
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_scheduled_posts (
                id VARCHAR(64) PRIMARY KEY,
                platform VARCHAR(32) NOT NULL,
                page_id VARCHAR(128),
                account_name VARCHAR(255),
                post_type VARCHAR(32) NOT NULL,
                caption TEXT,
                media_preview_url TEXT,
                scheduled_time TIMESTAMPTZ NOT NULL,
                status VARCHAR(32) DEFAULT 'waiting',
                status_message TEXT,
                external_post_id VARCHAR(128),
                permalink_url TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_presets (
                id VARCHAR(64) PRIMARY KEY,
                preset_name VARCHAR(255) NOT NULL,
                selection_json TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_seen_comments (
                comment_id VARCHAR(128) PRIMARY KEY,
                record_id VARCHAR(64),
                platform VARCHAR(32),
                seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_dismissed_comments (
                comment_id VARCHAR(128) PRIMARY KEY,
                record_id VARCHAR(64),
                dismissed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_seen_messages (
                conversation_id VARCHAR(128) PRIMARY KEY,
                account_id VARCHAR(128),
                last_seen_iso VARCHAR(128) DEFAULT '',
                seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_connected_accounts (
                id VARCHAR(128) PRIMARY KEY,
                platform VARCHAR(32) NOT NULL,
                account_id VARCHAR(128) NOT NULL,
                account_name VARCHAR(255) NOT NULL,
                username VARCHAR(255) DEFAULT '',
                avatar_url TEXT DEFAULT '',
                access_token TEXT DEFAULT '',
                connected_by VARCHAR(255) DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_crm_contacts (
                id TEXT PRIMARY KEY,
                first_name TEXT,
                middle_name TEXT,
                last_name TEXT,
                contact_number TEXT,
                email_address TEXT,
                platform TEXT,
                social_username TEXT,
                account_name TEXT,
                category TEXT DEFAULT 'lead',
                company TEXT,
                notes TEXT,
                source_type TEXT DEFAULT 'manual',
                source_ref_id TEXT,
                avatar_url TEXT,
                created_at TEXT,
                updated_at TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_email_accounts (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                email_address TEXT NOT NULL,
                display_name TEXT,
                composio_connection_id TEXT,
                composio_entity_id TEXT,
                imap_host TEXT,
                imap_port INTEGER DEFAULT 993,
                smtp_host TEXT,
                smtp_port INTEGER DEFAULT 465,
                imap_password TEXT,
                avatar_url TEXT,
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_internal_api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL,
                scopes TEXT DEFAULT 'all',
                status TEXT DEFAULT 'ACTIVE',
                requests_count INTEGER DEFAULT 0,
                last_used_at TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_n8n_workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                webhook_url TEXT DEFAULT '',
                webhook_path TEXT DEFAULT '',
                webhook_secret TEXT DEFAULT '',
                events_json TEXT DEFAULT '{}',
                detected_conditions_json TEXT DEFAULT '[]',
                workflow_json TEXT DEFAULT '{}',
                updated_at TEXT DEFAULT ''
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_calendar_accounts (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                toolkit_slug TEXT NOT NULL,
                email_address TEXT NOT NULL,
                display_name TEXT,
                composio_connection_id TEXT,
                composio_entity_id TEXT,
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_calendar_events (
                id TEXT PRIMARY KEY,
                external_event_id TEXT,
                account_id TEXT,
                provider TEXT NOT NULL,
                email_address TEXT,
                subject TEXT NOT NULL,
                description TEXT,
                location TEXT,
                start_iso TEXT NOT NULL,
                end_iso TEXT NOT NULL,
                timezone TEXT DEFAULT 'Asia/Manila',
                duration_minutes INTEGER DEFAULT 60,
                meeting_platform TEXT DEFAULT 'none',
                meeting_url TEXT,
                is_online_meeting INTEGER DEFAULT 0,
                organizer_email TEXT,
                attendees_json TEXT,
                availability TEXT DEFAULT 'busy',
                reminder_minutes INTEGER DEFAULT 15,
                status TEXT DEFAULT 'confirmed',
                html_link TEXT,
                created_at TEXT,
                updated_at TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_calendar_deleted_events (
                external_event_id TEXT PRIMARY KEY,
                provider TEXT,
                deleted_at TEXT
            );
        """))

    if not DATABASE_URL.startswith("sqlite"):
        for col_sql in (
            "ALTER TABLE glennbot_scheduled_posts ADD COLUMN IF NOT EXISTS external_post_id VARCHAR(128);",
            "ALTER TABLE glennbot_scheduled_posts ADD COLUMN IF NOT EXISTS permalink_url TEXT;",
        ):
            try:
                with db_engine.begin() as conn:
                    conn.execute(text(col_sql))
            except Exception:
                pass


# Initialize SQLite tables synchronously (< 2ms) so background threads never see 'no such table'
if DATABASE_URL.startswith("sqlite"):
    try:
        init_records_db()
    except Exception as _sqlite_init_err:
        print(f"[⚠️ SQLITE DB INIT WARNING]: {_sqlite_init_err}")


jobstores = {
    'default': SQLAlchemyJobStore(
        url=DATABASE_URL,
        engine_options={
            'connect_args': _DB_CONNECT_ARGS,
            'pool_pre_ping': True,
            'pool_recycle': 300
        }
    )
}
scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors={"default": {"type": "threadpool", "max_workers": 30}},
    job_defaults={"coalesce": True, "max_instances": 4, "misfire_grace_time": 120},
    timezone="Asia/Manila"
)


# --- SOCIAL PAGE NAME & ACCOUNT MATCHING HELPERS ---
def _normalize_social_page_name(name: str) -> str:
    raw = unicodedata.normalize("NFKC", str(name or "")).strip().lstrip("@")
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).casefold()


def _strip_social_page_punctuation(name: str) -> str:
    norm = _normalize_social_page_name(name)
    if not norm:
        return ""
    # Preserve all Unicode letters/numbers (including Japanese Kanji, Hiragana, Katakana, Latin, digits)
    return "".join(ch for ch in norm if ch.isalnum())


def _extract_social_page_segments(name: str) -> List[str]:
    norm = _normalize_social_page_name(name)
    if not norm:
        return []
    segments: List[str] = [norm]
    alnum_full = _strip_social_page_punctuation(norm)
    if alnum_full and len(alnum_full) >= 3 and alnum_full not in segments:
        segments.append(alnum_full)
    # Split bilingual / compound page titles like "Sket Dance /スケット・ダンス (Suketto Dansu)"
    for part in re.split(r"[/／|｜()（）\[\]【】\-–—]+", norm):
        p_clean = re.sub(r"\s+", " ", part).strip()
        if len(p_clean) >= 3 and p_clean not in ("facebook", "instagram", "tiktok", "youtube", "user", "page"):
            if p_clean not in segments:
                segments.append(p_clean)
            p_alnum = _strip_social_page_punctuation(p_clean)
            if len(p_alnum) >= 3 and p_alnum not in segments:
                segments.append(p_alnum)
    return segments


def _is_same_social_page_name(name_a: str, name_b: str) -> bool:
    na = _normalize_social_page_name(name_a)
    nb = _normalize_social_page_name(name_b)
    if not na or not nb:
        return False
    generic_Set = {"facebook", "instagram", "tiktok", "youtube", "user", "facebook user", "instagram user", "meta user"}
    if na in generic_Set or nb in generic_Set:
        return False
    if na == nb:
        return True
    sa = _strip_social_page_punctuation(na)
    sb = _strip_social_page_punctuation(nb)
    if sa and sb and sa == sb:
        return True
    segs_a = set(_extract_social_page_segments(na))
    segs_b = set(_extract_social_page_segments(nb))
    if segs_a and segs_b and (segs_a & segs_b):
        return True
    return False


def _does_zernio_account_match_page(
    za: Dict[str, Any],
    target_account_id: str = "",
    stored_z_acc_id: str = "",
    target_account_name: str = ""
) -> bool:
    if not isinstance(za, dict):
        return False
    za_ids = {
        str(za.get("_id") or "").strip(),
        str(za.get("id") or "").strip(),
        str(za.get("platformAccountId") or "").strip(),
        str(za.get("platformId") or "").strip(),
        str(za.get("pageId") or "").strip()
    }
    za_ids.discard("")
    target_ids = {str(target_account_id or "").strip(), str(stored_z_acc_id or "").strip()}
    target_ids.discard("")
    if target_ids and (za_ids & target_ids):
        return True
    if target_account_name:
        for field in ("displayName", "name", "username"):
            cand_nm = str(za.get(field) or "").strip()
            if cand_nm and _is_same_social_page_name(target_account_name, cand_nm):
                return True
    return False


def _resolve_service_callable(func_name: str):
    try:
        from services import zernio_service
        fn = getattr(zernio_service, func_name, None)
        if callable(fn):
            return fn
    except Exception:
        pass
    main_mod = sys.modules.get("main")
    if main_mod is not None:
        fn = getattr(main_mod, func_name, None)
        if callable(fn):
            return fn
    return None


# --- HELPER FUNCTIONS FOR DATABASE RECORDS ---
def update_post_status(
    record_id: str,
    status: str,
    message: str = "",
    external_post_id: Optional[str] = None,
    permalink_url: Optional[str] = None
):
    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE glennbot_scheduled_posts 
                    SET status = :status,
                        status_message = :msg,
                        external_post_id = COALESCE(:ext_id, external_post_id),
                        permalink_url = COALESCE(:permalink, permalink_url)
                    WHERE id = :id
                """),
                {
                    "status": status,
                    "msg": message,
                    "ext_id": external_post_id,
                    "permalink": permalink_url,
                    "id": record_id
                }
            )
    except Exception as e:
        print(f"[⚠️ DB STATUS UPDATE ERROR]: {e}")


def extract_external_post_id(row_dict: Dict[str, Any]) -> str:
    ext_id = (row_dict.get("external_post_id") or "").strip()
    if ext_id and ext_id != "OK":
        return ext_id
    msg = (row_dict.get("status_message") or "").strip()
    match = re.search(r"(?:Platform ID|External API ID|Zernio ID|PostZen ID|FB Post ID|FB Video ID|FB Album ID|IG Post ID):\s*([^\s,|]+)", msg)
    if match:
        return match.group(1).strip()
    return ext_id


def extract_all_known_ids_for_row(row_dict: Dict[str, Any]) -> List[str]:
    ids = []
    ext_id = (row_dict.get("external_post_id") or "").strip()
    if ext_id and ext_id != "OK":
        ids.append(ext_id)
    msg = (row_dict.get("status_message") or "").strip()
    for m in re.finditer(r"(?:Platform ID|External API ID|Zernio ID|PostZen ID|FB Post ID|FB Video ID|FB Album ID|IG Post ID):\s*([^\s,|]+)", msg):
        val = m.group(1).strip()
        if val and val != "OK" and val not in ids:
            ids.append(val)
    permalink = (row_dict.get("permalink_url") or "").strip()
    if permalink:
        m_link = re.search(r"(?:/videos/|/reel/|/posts/|/video/|story_fbid=|fbid=)(\d+)", permalink)
        if m_link and m_link.group(1) not in ids:
            ids.append(m_link.group(1))
        m_yt = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", permalink)
        if m_yt and m_yt.group(1) not in ids:
            ids.append(m_yt.group(1))
    return ids


def ensure_external_post_record_in_db(
    platform: str,
    plat_post_id: str,
    z_post_id: str,
    account_id: str,
    account_name: str,
    caption: str,
    permalink: str,
    preview_url: str,
    connected_items: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    target_pid = (plat_post_id or z_post_id or "").strip()
    if not target_pid:
        return None

    plat_clean = (platform or "").strip().lower()
    rec_id = f"post_ext_{hashlib.md5(f'{plat_clean}_{target_pid}'.encode('utf-8')).hexdigest()[:10]}"

    if isinstance(account_id, dict):
        acc_id_clean = str(account_id.get("_id") or account_id.get("id") or account_id.get("accountId") or account_id.get("platformAccountId") or "").strip()
        if not account_name:
            account_name = str(account_id.get("displayName") or account_id.get("name") or account_id.get("username") or "").strip()
    else:
        acc_id_clean = str(account_id or "").strip()
        if acc_id_clean.startswith("{") and acc_id_clean.endswith("}"):
            m_dict_id = re.search(r"['\"](?:_id|id|accountId)['\"]\s*:\s*['\"]([^'\"]+)['\"]", acc_id_clean)
            if m_dict_id:
                acc_id_clean = m_dict_id.group(1).strip()
            else:
                acc_id_clean = ""
    acc_name_clean = (account_name or "").strip().lstrip("@").lower()
    native_page_prefix = target_pid.split("_")[0].strip() if ("_" in target_pid and plat_clean == "facebook") else ""
    target_pid_suffix = target_pid.split("_")[-1].strip() if "_" in target_pid else target_pid

    # 1. Cross-reference Zernio's live commented posts list and posts map if account_id or account_name is missing
    if not acc_id_clean or not acc_name_clean:
        try:
            _get_commented_fn = _resolve_service_callable("get_zernio_commented_posts_list")
            commented_list = _get_commented_fn(force=False) if _get_commented_fn else []
            for cp in commented_list:
                if not isinstance(cp, dict):
                    continue
                cp_plat = (cp.get("platform") or "").strip().lower()
                if cp_plat and cp_plat != plat_clean:
                    continue
                cp_id = str(cp.get("id") or cp.get("_id") or cp.get("postId") or "").strip()
                cp_plat_id = str(cp.get("platformPostId") or "").strip()
                cp_plat_suffix = cp_plat_id.split("_")[-1].strip() if "_" in cp_plat_id else cp_plat_id
                if (
                    target_pid in (cp_id, cp_plat_id, cp_plat_suffix)
                    or (target_pid_suffix and target_pid_suffix in (cp_id, cp_plat_id, cp_plat_suffix))
                    or (z_post_id and z_post_id in (cp_id, cp_plat_id))
                ):
                    cp_acc = cp.get("accountId") or cp.get("account")
                    if isinstance(cp_acc, dict):
                        if not acc_name_clean:
                            extracted_name = str(cp_acc.get("displayName") or cp_acc.get("name") or cp_acc.get("username") or "").strip()
                            if extracted_name:
                                account_name = extracted_name
                                acc_name_clean = extracted_name.lstrip("@").lower()
                        cp_acc = cp_acc.get("_id") or cp_acc.get("id") or cp_acc.get("accountId")
                    if cp_acc and not acc_id_clean:
                        acc_id_clean = str(cp_acc).strip()
                    if not acc_name_clean:
                        cp_aname = str(cp.get("accountName") or cp.get("pageName") or "").strip()
                        if cp_aname:
                            account_name = cp_aname
                            acc_name_clean = cp_aname.lstrip("@").lower()
                    if acc_id_clean:
                        break
        except Exception:
            pass

    # 2. Cross-reference live Zernio connected accounts to collect all matching IDs & names for this page
    candidate_acc_ids = {x for x in (acc_id_clean, native_page_prefix) if x}
    candidate_acc_names = {acc_name_clean} if acc_name_clean else set()
    live_matched_za: Optional[Dict[str, Any]] = None

    try:
        _fetch_za_fn = _resolve_service_callable("fetch_zernio_connected_accounts")
        if _fetch_za_fn:
            for force_flag in (False, True):
                for za in _fetch_za_fn(platform=plat_clean or None, force=force_flag):
                    if not isinstance(za, dict):
                        continue
                    za_id = str(za.get("_id") or za.get("id") or "").strip()
                    za_plat_id = str(za.get("platformAccountId") or za.get("platformId") or za.get("pageId") or "").strip()
                    za_uname = (za.get("username") or "").strip().lstrip("@").lower()
                    za_dname = (za.get("displayName") or za.get("name") or "").strip().lstrip("@").lower()
                    za_ids = {x for x in (za_id, za_plat_id) if x}
                    za_names = {x for x in (za_uname, za_dname) if x}

                    if (candidate_acc_ids & za_ids) or (candidate_acc_names & za_names) or _does_zernio_account_match_page(za, acc_id_clean, native_page_prefix, account_name):
                        live_matched_za = za
                        candidate_acc_ids.update(za_ids)
                        candidate_acc_names.update(za_names)
                        break
                if live_matched_za:
                    break
    except Exception:
        pass

    # 3. Match against connected_items in Supabase
    matched_acc = None
    has_verified_account_match = False
    for acc in connected_items:
        if (acc.get("platform") or "").strip().lower() != plat_clean:
            continue
        a_id = str(acc.get("account_id") or "").strip()
        a_uname = (acc.get("username") or "").strip().lstrip("@").lower()
        a_dname = (acc.get("account_name") or "").strip().lstrip("@").lower()
        name_matched = bool(
            (a_uname and a_uname in candidate_acc_names)
            or (a_dname and a_dname in candidate_acc_names)
            or (account_name and (_is_same_social_page_name(account_name, acc.get("account_name") or "") or _is_same_social_page_name(account_name, acc.get("username") or "")))
        )
        if (a_id and a_id in candidate_acc_ids) or name_matched:
            matched_acc = acc
            has_verified_account_match = True
            break

    if not matched_acc and live_matched_za:
        has_verified_account_match = True
        matched_acc = {
            "platform": plat_clean,
            "account_id": str(live_matched_za.get("_id") or live_matched_za.get("id") or acc_id_clean),
            "account_name": str(live_matched_za.get("displayName") or live_matched_za.get("name") or live_matched_za.get("username") or account_name or plat_clean.upper()),
            "username": str(live_matched_za.get("username") or "")
        }

    if not matched_acc:
        plat_conns = [acc for acc in connected_items if (acc.get("platform") or "").strip().lower() == plat_clean]
        if len(plat_conns) == 1:
            matched_acc = plat_conns[0]
        elif len(plat_conns) > 1 and (acc_id_clean or account_name):
            matched_acc = {
                "platform": plat_clean,
                "account_id": acc_id_clean or str(plat_conns[0].get("account_id") or ""),
                "account_name": account_name or str(plat_conns[0].get("account_name") or plat_clean.upper()),
                "username": ""
            }

    if not matched_acc:
        return None

    final_page_id = str(
        matched_acc.get("account_id")
        or (live_matched_za.get("_id") or live_matched_za.get("id") if live_matched_za else "")
        or acc_id_clean
        or ""
    ).strip()
    final_uname = (matched_acc.get("username") or (live_matched_za.get("username") if live_matched_za else "") or account_name or "").strip().lstrip("@")
    final_acc_name = (
        matched_acc.get("account_name")
        or (live_matched_za.get("displayName") or live_matched_za.get("name") if live_matched_za else "")
        or (f"@{final_uname}" if final_uname else plat_clean.upper())
    )
    if plat_clean == "tiktok" and final_uname and not final_acc_name.startswith("@"):
        final_acc_name = f"@{final_uname}"

    final_caption = (caption or "").strip()
    final_permalink = (permalink or "").strip()
    final_preview = (preview_url or "").strip()

    if plat_clean == "tiktok" and target_pid.isdigit():
        if not final_permalink:
            final_permalink = f"https://www.tiktok.com/@{final_uname or 'tiktok'}/video/{target_pid}"
        if not final_caption or not final_preview:
            _tikwm_fn = _resolve_service_callable("fetch_tikwm_video_metadata")
            tk_meta = _tikwm_fn(target_pid, final_uname) if _tikwm_fn else {}
            if not final_caption and tk_meta.get("caption"):
                final_caption = tk_meta["caption"]
            if not final_preview and (tk_meta.get("video_url") or tk_meta.get("cover_url")):
                final_preview = tk_meta.get("video_url") or tk_meta.get("cover_url") or ""
    elif plat_clean == "facebook" and not final_permalink and target_pid:
        final_permalink = f"https://www.facebook.com/{target_pid}"
    elif plat_clean == "youtube" and target_pid:
        m_yt_pid = re.search(r"(?:watch\?v=|youtu\.be/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", final_permalink or target_pid)
        yt_vid_clean = m_yt_pid.group(1) if m_yt_pid else (target_pid if re.match(r"^[A-Za-z0-9_-]{11}$", target_pid) else "")
        if yt_vid_clean:
            target_pid = yt_vid_clean
            if not final_permalink:
                final_permalink = f"https://www.youtube.com/watch?v={yt_vid_clean}"
            if not final_preview:
                final_preview = f"https://i.ytimg.com/vi/{yt_vid_clean}/hqdefault.jpg"

    manila_tz = pytz.timezone("Asia/Manila")
    now_m = datetime.now(manila_tz)
    status_msg = f"External Post | Platform ID: {target_pid}"
    if z_post_id and z_post_id != target_pid:
        status_msg = f"External Post | External API ID: {z_post_id} | Platform ID: {target_pid}"

    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO glennbot_scheduled_posts
                    (id, platform, page_id, account_name, post_type, caption, media_preview_url,
                     scheduled_time, status, status_message, external_post_id, permalink_url)
                    VALUES (:id, :plat, :pid, :aname, 'reels', :cap, :prev,
                            :stime, 'published', :smsg, :extid, :plink)
                    ON CONFLICT (id) DO UPDATE SET
                        page_id = CASE WHEN :verified_match = 1 AND EXCLUDED.page_id != '' THEN EXCLUDED.page_id ELSE glennbot_scheduled_posts.page_id END,
                        account_name = CASE WHEN :verified_match = 1 AND EXCLUDED.account_name != '' THEN EXCLUDED.account_name ELSE glennbot_scheduled_posts.account_name END,
                        scheduled_time = EXCLUDED.scheduled_time,
                        status_message = CASE WHEN EXCLUDED.status_message != '' THEN EXCLUDED.status_message ELSE glennbot_scheduled_posts.status_message END,
                        external_post_id = COALESCE(NULLIF(EXCLUDED.external_post_id, ''), glennbot_scheduled_posts.external_post_id),
                        caption = CASE WHEN glennbot_scheduled_posts.caption = '' OR glennbot_scheduled_posts.caption IS NULL OR glennbot_scheduled_posts.caption = 'Previous Post' THEN EXCLUDED.caption ELSE glennbot_scheduled_posts.caption END,
                        media_preview_url = CASE WHEN glennbot_scheduled_posts.media_preview_url = '' OR glennbot_scheduled_posts.media_preview_url IS NULL THEN EXCLUDED.media_preview_url ELSE glennbot_scheduled_posts.media_preview_url END,
                        permalink_url = COALESCE(EXCLUDED.permalink_url, glennbot_scheduled_posts.permalink_url)
                """),
                {
                    "id": rec_id,
                    "plat": plat_clean,
                    "pid": final_page_id,
                    "aname": final_acc_name,
                    "cap": final_caption or "Previous Post",
                    "prev": final_preview,
                    "stime": now_m,
                    "smsg": status_msg,
                    "extid": target_pid,
                    "plink": final_permalink or None,
                    "verified_match": 1 if has_verified_account_match else 0
                }
            )
            row_after = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, post_type, caption,
                           media_preview_url, scheduled_time, status, status_message, external_post_id, permalink_url
                    FROM glennbot_scheduled_posts
                    WHERE id = :id
                """),
                {"id": rec_id}
            ).mappings().first()

        if row_after:
            return dict(row_after)

        return {
            "id": rec_id,
            "platform": plat_clean,
            "page_id": final_page_id,
            "account_name": final_acc_name,
            "post_type": "reels",
            "caption": final_caption or "Previous Post",
            "media_preview_url": final_preview,
            "scheduled_time": now_m,
            "status": "published",
            "status_message": status_msg,
            "external_post_id": target_pid,
            "permalink_url": final_permalink
        }
    except Exception as e:
        print(f"[⚠️ AUTO-IMPORT EXTERNAL POST ERROR]: {e}")
        return None


def cleanup_old_records():
    try:
        cutoff_dt = datetime.now(pytz.utc) - timedelta(days=30)
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    DELETE FROM glennbot_scheduled_posts 
                    WHERE scheduled_time < :cutoff
                    AND status IN ('published', 'failed');
                """),
                {"cutoff": cutoff_dt}
            )
    except Exception as e:
        print(f"[❌ DB RETENTION ERROR]: {e}")


def _init_db_and_cron_job_bg():
    try:
        init_records_db()
    except Exception as e:
        print(f"[⚠️ DB INIT WARNING]: {e}")
    try:
        scheduler.add_job(
            cleanup_old_records,
            'cron',
            hour=3,
            minute=0,
            id='daily_db_retention_cleanup',
            replace_existing=True
        )
    except Exception as e:
        print(f"[⚠️ SCHEDULER JOB INIT WARNING]: {e}")


import threading as _db_threading
_db_threading.Thread(target=_init_db_and_cron_job_bg, daemon=True).start()


def _get_cached_seen_comment_ids(ttl_sec: float = 3.0) -> set:
    now_ts = time.time()
    with FAST_DB_READ_CACHE_LOCK:
        if (now_ts - FAST_DB_READ_CACHE.get("seen_comments_ts", 0.0)) < ttl_sec and isinstance(FAST_DB_READ_CACHE.get("seen_comments"), set):
            return set(FAST_DB_READ_CACHE["seen_comments"])
    try:
        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT comment_id FROM glennbot_seen_comments")).mappings().all()
            seen_ids = {str(r["comment_id"]) for r in seen_rows}
        with FAST_DB_READ_CACHE_LOCK:
            FAST_DB_READ_CACHE["seen_comments"] = seen_ids
            FAST_DB_READ_CACHE["seen_comments_ts"] = now_ts
        return set(seen_ids)
    except Exception:
        with FAST_DB_READ_CACHE_LOCK:
            return set(FAST_DB_READ_CACHE.get("seen_comments") or set())


def _get_cached_published_posts(ttl_sec: float = 3.5, force: bool = False) -> List[Dict[str, Any]]:
    now_ts = time.time()
    if not force:
        with FAST_DB_READ_CACHE_LOCK:
            if (now_ts - FAST_DB_READ_CACHE.get("published_posts_ts", 0.0)) < ttl_sec and FAST_DB_READ_CACHE.get("published_posts"):
                return [dict(x) for x in FAST_DB_READ_CACHE["published_posts"]]
    try:
        with db_engine.connect() as conn:
            post_rows = conn.execute(text("""
                SELECT id, platform, page_id, account_name, post_type, caption,
                       media_preview_url, scheduled_time, status, status_message, external_post_id, permalink_url
                FROM glennbot_scheduled_posts
                WHERE status = 'published'
                ORDER BY scheduled_time DESC
                LIMIT 120
            """)).mappings().all()
        rows_list = [dict(r) for r in post_rows]
        with FAST_DB_READ_CACHE_LOCK:
            FAST_DB_READ_CACHE["published_posts"] = rows_list
            FAST_DB_READ_CACHE["published_posts_ts"] = now_ts
        return [dict(x) for x in rows_list]
    except Exception:
        with FAST_DB_READ_CACHE_LOCK:
            return [dict(x) for x in (FAST_DB_READ_CACHE.get("published_posts") or [])]


def _get_cached_seen_messages_map(ttl_sec: float = 3.0) -> Dict[str, str]:
    now_ts = time.time()
    with FAST_DB_READ_CACHE_LOCK:
        if (now_ts - FAST_DB_READ_CACHE.get("seen_messages_ts", 0.0)) < ttl_sec and isinstance(FAST_DB_READ_CACHE.get("seen_messages"), dict):
            return dict(FAST_DB_READ_CACHE["seen_messages"])
    try:
        with db_engine.connect() as conn:
            seen_rows = conn.execute(text("SELECT conversation_id, last_seen_iso FROM glennbot_seen_messages")).mappings().all()
            seen_map = {str(r["conversation_id"]): str(r["last_seen_iso"] or "") for r in seen_rows}
        with FAST_DB_READ_CACHE_LOCK:
            FAST_DB_READ_CACHE["seen_messages"] = seen_map
            FAST_DB_READ_CACHE["seen_messages_ts"] = now_ts
        return dict(seen_map)
    except Exception:
        with FAST_DB_READ_CACHE_LOCK:
            return dict(FAST_DB_READ_CACHE.get("seen_messages") or {})
