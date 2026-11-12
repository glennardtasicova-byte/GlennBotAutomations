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
        pool_size=8,
        max_overflow=12,
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS glennbot_comment_automation_queue (
                queue_id VARCHAR(128) PRIMARY KEY,
                comment_id VARCHAR(128) NOT NULL,
                thread_id VARCHAR(128) DEFAULT '',
                post_id VARCHAR(128) DEFAULT '',
                record_id VARCHAR(128) DEFAULT '',
                platform VARCHAR(64) DEFAULT '',
                account_name VARCHAR(255) DEFAULT '',
                author_name VARCHAR(255) DEFAULT '',
                message TEXT DEFAULT '',
                is_own_comment INTEGER DEFAULT 0,
                payload_json TEXT DEFAULT '{}',
                status VARCHAR(32) DEFAULT 'queued',
                ai_reply TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                queued_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
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


import json as _db_json
import uuid as _db_uuid
import threading as _queue_threading

SUPABASE_COMMENT_QUEUE_LOCK = _queue_threading.RLock()
SUPABASE_COMMENT_QUEUE_COND = _queue_threading.Condition(SUPABASE_COMMENT_QUEUE_LOCK)
_SUPABASE_QUEUE_TABLE_READY = False


def _ensure_supabase_comment_queue_table() -> None:
    global _SUPABASE_QUEUE_TABLE_READY
    if _SUPABASE_QUEUE_TABLE_READY:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS glennbot_comment_automation_queue (
                    queue_id VARCHAR(128) PRIMARY KEY,
                    comment_id VARCHAR(128) NOT NULL,
                    thread_id VARCHAR(128) DEFAULT '',
                    post_id VARCHAR(128) DEFAULT '',
                    record_id VARCHAR(128) DEFAULT '',
                    platform VARCHAR(64) DEFAULT '',
                    account_name VARCHAR(255) DEFAULT '',
                    author_name VARCHAR(255) DEFAULT '',
                    message TEXT DEFAULT '',
                    is_own_comment INTEGER DEFAULT 0,
                    payload_json TEXT DEFAULT '{}',
                    status VARCHAR(32) DEFAULT 'queued',
                    ai_reply TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    queued_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                );
            """))
        _SUPABASE_QUEUE_TABLE_READY = True
    except Exception as e:
        print(f"[SupabaseCommentQueue] Table init warning: {e}")


def enqueue_and_acquire_supabase_comment_queue_turn(
    wb_data: Dict[str, Any],
    is_test_run: bool = False,
    max_wait_seconds: float = 180.0
) -> Dict[str, Any]:
    """
    Stores an incoming post comment/reply webhook into the Supabase `glennbot_comment_automation_queue`
    table (via `DATABASE_URL` in `.env`) with `status = 'queued'`, and waits in strict FIFO order
    until all earlier comments in the queue have finished processing before marking this item
    `status = 'processing'` and returning control to the automation workflow.
    """
    _ensure_supabase_comment_queue_table()
    root_body = wb_data.get("body") if isinstance(wb_data.get("body"), dict) else wb_data
    wb = root_body.get("data") if isinstance(root_body.get("data"), dict) else root_body
    if not isinstance(wb, dict):
        wb = {}

    now_utc = datetime.now(pytz.utc)
    raw_cid = str(wb.get("comment_id") or root_body.get("comment_id") or f"cid_{int(time.time() * 1000)}").strip()
    raw_tid = str(wb.get("thread_id") or wb.get("root_comment_id") or wb.get("parent_comment_id") or raw_cid).strip()
    raw_pid = str(wb.get("post_id") or wb.get("zernio_post_id") or wb.get("external_post_id") or "").strip()
    raw_rid = str(wb.get("record_id") or "").strip()
    raw_plat = str(wb.get("platform") or "facebook").strip().lower()
    raw_acc = str(wb.get("account_name") or "GlennBot Automations").strip()
    raw_auth = str(wb.get("author_name") or "Commenter").strip()
    raw_msg = str(wb.get("message") or "").strip()
    is_own = 1 if bool(wb.get("is_own_comment") or wb.get("is_own")) else 0

    queue_id = str(wb.get("queue_id") or root_body.get("queue_id") or "").strip()
    if not queue_id:
        queue_id = f"sbq_{int(time.time() * 1000)}_{_db_uuid.uuid4().hex[:6]}"

    payload_str = _db_json.dumps(wb, ensure_ascii=False, default=str)
    queue_position = 1
    pending_count = 1
    waited_ms = 0
    enqueue_t0 = time.time()

    try:
        with db_engine.begin() as conn:
            # 1. Auto-expire stale 'processing' or 'queued' rows older than 90 seconds so the queue never blocks
            stale_cutoff = now_utc - timedelta(seconds=90)
            conn.execute(
                text("""
                    UPDATE glennbot_comment_automation_queue
                    SET status = 'expired_timeout',
                        error_message = 'Auto-expired stale processing lock (>90s)',
                        completed_at = :now_ts
                    WHERE status IN ('processing', 'queued')
                      AND queued_at < :cutoff
                """),
                {"now_ts": now_utc, "cutoff": stale_cutoff}
            )
            # 2. Insert incoming comment webhook into Supabase queue as 'queued'
            conn.execute(
                text("""
                    INSERT INTO glennbot_comment_automation_queue
                    (queue_id, comment_id, thread_id, post_id, record_id, platform,
                     account_name, author_name, message, is_own_comment, payload_json,
                     status, queued_at)
                    VALUES (:qid, :cid, :tid, :pid, :rid, :plat,
                            :aname, :auth, :msg, :is_own, :pjson,
                            'queued', :q_at)
                    ON CONFLICT (queue_id) DO UPDATE SET
                        status = 'queued',
                        queued_at = EXCLUDED.queued_at
                """),
                {
                    "qid": queue_id,
                    "cid": raw_cid,
                    "tid": raw_tid,
                    "pid": raw_pid,
                    "rid": raw_rid,
                    "plat": raw_plat,
                    "aname": raw_acc,
                    "auth": raw_auth,
                    "msg": raw_msg,
                    "is_own": is_own,
                    "pjson": payload_str,
                    "q_at": now_utc,
                }
            )
    except Exception as e:
        print(f"[SupabaseCommentQueue] Enqueue insert warning: {e}")

    # 3. Acquire FIFO turn so comments & replies are processed strictly one-by-one
    effective_timeout = 2.0 if is_test_run else max(5.0, min(max_wait_seconds, 240.0))
    deadline = time.time() + effective_timeout

    with SUPABASE_COMMENT_QUEUE_COND:
        while True:
            can_acquire = False
            try:
                with db_engine.begin() as conn:
                    now_check = datetime.now(pytz.utc)
                    conn.execute(
                        text("""
                            UPDATE glennbot_comment_automation_queue
                            SET status = 'expired_timeout',
                                completed_at = :now_ts
                            WHERE status = 'processing'
                              AND started_at IS NOT NULL
                              AND started_at < :cutoff
                        """),
                        {"now_ts": now_check, "cutoff": now_check - timedelta(seconds=75)}
                    )
                    active_rows = conn.execute(
                        text("""
                            SELECT queue_id, status
                            FROM glennbot_comment_automation_queue
                            WHERE status IN ('processing', 'queued')
                            ORDER BY queued_at ASC, queue_id ASC
                            LIMIT 100
                        """)
                    ).mappings().all()

                    pending_count = len(active_rows)
                    for idx_r, r_item in enumerate(active_rows):
                        if str(r_item["queue_id"]) == queue_id:
                            queue_position = idx_r + 1
                            break

                    any_other_processing = any(
                        str(r_item["status"]) == "processing" and str(r_item["queue_id"]) != queue_id
                        for r_item in active_rows
                    )
                    head_queued_id = next(
                        (str(r_item["queue_id"]) for r_item in active_rows if str(r_item["status"]) == "queued"),
                        queue_id
                    )

                    if (not any_other_processing and head_queued_id == queue_id) or time.time() >= deadline:
                        conn.execute(
                            text("""
                                UPDATE glennbot_comment_automation_queue
                                SET status = 'processing',
                                    started_at = :now_ts
                                WHERE queue_id = :qid
                            """),
                            {"now_ts": now_check, "qid": queue_id}
                        )
                        can_acquire = True
            except Exception as e:
                print(f"[SupabaseCommentQueue] FIFO check warning: {e}")
                can_acquire = True

            if can_acquire:
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            SUPABASE_COMMENT_QUEUE_COND.wait(timeout=min(0.4, remaining))

    waited_ms = int((time.time() - enqueue_t0) * 1000)
    db_engine_label = "sqlite_fallback" if DATABASE_URL.startswith("sqlite") else "supabase_postgresql"
    return {
        **wb_data,
        "queueId": queue_id,
        "queue_id": queue_id,
        "queueStatus": "processing",
        "queuePosition": queue_position,
        "pendingInSupabaseQueue": pending_count,
        "queueWaitMs": waited_ms,
        "supabaseTable": "glennbot_comment_automation_queue",
        "databaseEngine": db_engine_label,
        "databaseUrlConfigured": not DATABASE_URL.startswith("sqlite"),
        "comment_id": raw_cid,
        "thread_id": raw_tid,
        "post_id": raw_pid,
        "record_id": raw_rid,
        "platform": raw_plat,
        "account_name": raw_acc,
        "author_name": raw_auth,
        "message": raw_msg,
        "is_own_comment": bool(is_own),
    }


def complete_supabase_comment_queue_turn(
    queue_id: str = "",
    comment_id: str = "",
    ai_reply: str = "",
    status: str = "completed",
    error_message: str = ""
) -> Dict[str, Any]:
    """
    Marks the currently processing comment in `glennbot_comment_automation_queue` as `completed`
    (or `failed` / `skipped_own_comment`) and immediately notifies the next queued comment in Supabase!
    """
    _ensure_supabase_comment_queue_table()
    clean_qid = str(queue_id or "").strip()
    clean_cid = str(comment_id or "").strip()
    clean_status = str(status or "completed").strip() or "completed"
    now_utc = datetime.now(pytz.utc)
    remaining_queued = 0

    with SUPABASE_COMMENT_QUEUE_COND:
        try:
            with db_engine.begin() as conn:
                if clean_qid:
                    conn.execute(
                        text("""
                            UPDATE glennbot_comment_automation_queue
                            SET status = :st,
                                ai_reply = CASE WHEN :rep != '' THEN :rep ELSE ai_reply END,
                                error_message = CASE WHEN :err != '' THEN :err ELSE error_message END,
                                completed_at = :now_ts
                            WHERE queue_id = :qid
                        """),
                        {
                            "st": clean_status,
                            "rep": str(ai_reply or "")[:4000],
                            "err": str(error_message or "")[:1000],
                            "now_ts": now_utc,
                            "qid": clean_qid,
                        }
                    )
                elif clean_cid:
                    conn.execute(
                        text("""
                            UPDATE glennbot_comment_automation_queue
                            SET status = :st,
                                ai_reply = CASE WHEN :rep != '' THEN :rep ELSE ai_reply END,
                                error_message = CASE WHEN :err != '' THEN :err ELSE error_message END,
                                completed_at = :now_ts
                            WHERE comment_id = :cid AND status IN ('processing', 'queued')
                        """),
                        {
                            "st": clean_status,
                            "rep": str(ai_reply or "")[:4000],
                            "err": str(error_message or "")[:1000],
                            "now_ts": now_utc,
                            "cid": clean_cid,
                        }
                    )
                rem_row = conn.execute(
                    text("""
                        SELECT COUNT(*) AS cnt
                        FROM glennbot_comment_automation_queue
                        WHERE status = 'queued'
                    """)
                ).mappings().first()
                remaining_queued = int((rem_row or {}).get("cnt") or 0)
        except Exception as e:
            print(f"[SupabaseCommentQueue] Complete turn warning: {e}")
        finally:
            SUPABASE_COMMENT_QUEUE_COND.notify_all()

    return {
        "status": "success",
        "queueId": clean_qid,
        "commentId": clean_cid,
        "queueStatus": clean_status,
        "remainingInSupabaseQueue": remaining_queued,
        "supabaseTable": "glennbot_comment_automation_queue",
        "completedAt": now_utc.astimezone(MANILA_TZ).strftime("%Y-%m-%d %I:%M:%S %p"),
    }


def get_supabase_comment_queue_status(limit: int = 50) -> Dict[str, Any]:
    _ensure_supabase_comment_queue_table()
    items: List[Dict[str, Any]] = []
    counts = {"queued": 0, "processing": 0, "completed": 0}
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT queue_id, comment_id, thread_id, post_id, record_id, platform,
                           account_name, author_name, message, is_own_comment, status,
                           ai_reply, error_message, queued_at, started_at, completed_at
                    FROM glennbot_comment_automation_queue
                    ORDER BY queued_at DESC
                    LIMIT :lim
                """),
                {"lim": max(1, min(limit, 200))}
            ).mappings().all()
            for r in rows:
                d = dict(r)
                st = str(d.get("status") or "queued")
                if st in counts:
                    counts[st] += 1
                items.append({
                    "queue_id": d.get("queue_id"),
                    "comment_id": d.get("comment_id"),
                    "thread_id": d.get("thread_id"),
                    "post_id": d.get("post_id"),
                    "record_id": d.get("record_id"),
                    "platform": d.get("platform"),
                    "account_name": d.get("account_name"),
                    "author_name": d.get("author_name"),
                    "message": d.get("message"),
                    "is_own_comment": bool(d.get("is_own_comment")),
                    "status": st,
                    "ai_reply": d.get("ai_reply") or "",
                    "error_message": d.get("error_message") or "",
                    "queued_at": str(d.get("queued_at") or ""),
                    "started_at": str(d.get("started_at") or ""),
                    "completed_at": str(d.get("completed_at") or ""),
                })
    except Exception as e:
        print(f"[SupabaseCommentQueue] Status read warning: {e}")
    return {
        "status": "success",
        "supabase_table": "glennbot_comment_automation_queue",
        "database_url_configured": not DATABASE_URL.startswith("sqlite"),
        "counts": counts,
        "items": items,
    }


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
    executors={"default": {"type": "threadpool", "max_workers": 10}},
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
        m_link = re.search(r"(?:/videos/|/reel/|/posts/|/video/|/photo/|story_fbid=|fbid=)(\d+)", permalink)
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
    elif plat_clean == "facebook" and not final_permalink and target_pid:
        if "_" in target_pid:
            fb_page_part, fb_post_part = target_pid.split("_", 1)
            final_permalink = f"https://www.facebook.com/{fb_page_part}/posts/{fb_post_part}"
        else:
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

    cand_tokens = {
        str(t).strip()
        for t in (target_pid, target_pid_suffix, z_post_id)
        if t and len(str(t).strip()) >= 6 and str(t).strip() != "OK"
    }

    if (not final_caption or final_caption in ("Previous Post", "Social Media Post") or not final_preview or not final_permalink) and target_pid:
        try:
            from services import zernio_service as _zs_mod
            _cp_cache_dict = getattr(_zs_mod, "ZERNIO_COMMENTED_POSTS_CACHE", None)
        except Exception:
            _cp_cache_dict = None
        if not isinstance(_cp_cache_dict, dict):
            _main_mod = sys.modules.get("main")
            _cp_cache_dict = getattr(_main_mod, "ZERNIO_COMMENTED_POSTS_CACHE", None) if _main_mod else None
        _cp_list = list((_cp_cache_dict.get("items") if isinstance(_cp_cache_dict, dict) else None) or [])
        for _cp in _cp_list:
            if not isinstance(_cp, dict):
                continue
            _cp_id = str(_cp.get("platformPostId") or _cp.get("id") or _cp.get("_id") or "").strip()
            _cp_suf = _cp_id.split("_")[-1].strip() if "_" in _cp_id else _cp_id
            if _cp_id and (_cp_id in cand_tokens or (_cp_suf and _cp_suf in cand_tokens)):
                _cp_cap = str(_cp.get("content") or _cp.get("caption") or "").strip()
                _cp_plink = str(_cp.get("permalink") or _cp.get("platformPostUrl") or "").strip()
                _cp_pic = str(_cp.get("picture") or _cp.get("imageUrl") or _cp.get("thumbnailUrl") or "").strip()
                if (not final_caption or final_caption in ("Previous Post", "Social Media Post")) and _cp_cap:
                    final_caption = _cp_cap
                if not final_preview and _cp_pic:
                    final_preview = _cp_pic
                if (not final_permalink or ("_" in final_permalink and "/posts/" not in final_permalink)) and _cp_plink:
                    final_permalink = _cp_plink
                break

    if plat_clean == "tiktok" and target_pid.isdigit() and (not final_caption or final_caption == "Previous Post" or not final_preview):
        try:
            _tikwm_fn = _resolve_service_callable("fetch_tikwm_video_metadata")
            tk_meta = _tikwm_fn(target_pid, final_uname) if _tikwm_fn else {}
            if (not final_caption or final_caption == "Previous Post") and tk_meta.get("caption"):
                final_caption = tk_meta["caption"]
            if not final_preview and (tk_meta.get("video_url") or tk_meta.get("cover_url")):
                final_preview = tk_meta.get("video_url") or tk_meta.get("cover_url") or ""
        except Exception:
            pass

    manila_tz = pytz.timezone("Asia/Manila")
    now_m = datetime.now(manila_tz)
    status_msg = f"External Post | Platform ID: {target_pid}"
    if z_post_id and z_post_id != target_pid:
        status_msg = f"External Post | External API ID: {z_post_id} | Platform ID: {target_pid}"

    try:
        with db_engine.begin() as conn:
            # First check if a canonical (non-post_ext_) or existing row ALREADY matches this post so we never split a post across two record_ids
            existing_plat_rows = conn.execute(
                text("""
                    SELECT id, platform, page_id, account_name, post_type, caption,
                           media_preview_url, scheduled_time, status, status_message, external_post_id, permalink_url
                    FROM glennbot_scheduled_posts
                    WHERE LOWER(platform) = :plat AND status = 'published'
                    ORDER BY CASE WHEN id NOT LIKE 'post_ext_%' THEN 0 ELSE 1 END, scheduled_time DESC
                    LIMIT 80
                """),
                {"plat": plat_clean}
            ).mappings().all()

            clean_target_cap = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", final_caption).strip().lower() if final_caption and final_caption != "Previous Post" else ""
            canonical_matched_id = ""
            matched_er_dict: Optional[Dict[str, Any]] = None
            duplicate_ext_ids_to_remove: List[str] = []

            for er in existing_plat_rows:
                er_dict = dict(er)
                er_id = str(er_dict.get("id") or "").strip()
                if not er_id:
                    continue
                er_known = set(str(k).strip() for k in extract_all_known_ids_for_row(er_dict) if k)
                er_known_suffixes = {k.split("_")[-1].strip() for k in er_known if "_" in k}
                er_smsg = str(er_dict.get("status_message") or "")
                er_plink = str(er_dict.get("permalink_url") or "")
                id_match = bool(
                    (cand_tokens & (er_known | er_known_suffixes))
                    or any(tok in er_smsg or tok in er_plink for tok in cand_tokens)
                )
                cap_match = False
                if not id_match and clean_target_cap and not er_id.startswith("post_ext_"):
                    er_cap_clean = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", str(er_dict.get("caption") or "")).strip().lower()
                    if er_cap_clean and er_cap_clean == clean_target_cap:
                        er_pid = str(er_dict.get("page_id") or "").strip()
                        er_aname = str(er_dict.get("account_name") or "").strip()
                        if (er_pid and er_pid in (candidate_acc_ids | {final_page_id})) or _is_same_social_page_name(er_aname, final_acc_name):
                            cap_match = True

                if id_match or cap_match:
                    if not canonical_matched_id:
                        canonical_matched_id = er_id
                        matched_er_dict = er_dict
                    elif er_id != canonical_matched_id and er_id.startswith("post_ext_"):
                        duplicate_ext_ids_to_remove.append(er_id)

            if matched_er_dict:
                existing_cap = str(matched_er_dict.get("caption") or "").strip()
                existing_prev = str(matched_er_dict.get("media_preview_url") or "").strip()
                if (not final_caption or final_caption in ("Previous Post", "Social Media Post")) and existing_cap and existing_cap not in ("Previous Post", "Social Media Post"):
                    final_caption = existing_cap
                if not final_preview and existing_prev:
                    final_preview = existing_prev

            if canonical_matched_id:
                rec_id = canonical_matched_id
                if duplicate_ext_ids_to_remove:
                    for dup_ext_id in duplicate_ext_ids_to_remove:
                        conn.execute(
                            text("DELETE FROM glennbot_scheduled_posts WHERE id = :dup_id"),
                            {"dup_id": dup_ext_id}
                        )

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
                        scheduled_time = CASE WHEN glennbot_scheduled_posts.id LIKE 'post_ext_%' THEN EXCLUDED.scheduled_time ELSE glennbot_scheduled_posts.scheduled_time END,
                        status_message = CASE WHEN EXCLUDED.status_message != '' THEN EXCLUDED.status_message ELSE glennbot_scheduled_posts.status_message END,
                        external_post_id = COALESCE(NULLIF(EXCLUDED.external_post_id, ''), glennbot_scheduled_posts.external_post_id),
                        caption = CASE WHEN glennbot_scheduled_posts.caption = '' OR glennbot_scheduled_posts.caption IS NULL OR glennbot_scheduled_posts.caption IN ('Previous Post', 'Social Media Post') THEN EXCLUDED.caption ELSE glennbot_scheduled_posts.caption END,
                        media_preview_url = CASE WHEN glennbot_scheduled_posts.media_preview_url = '' OR glennbot_scheduled_posts.media_preview_url IS NULL THEN EXCLUDED.media_preview_url ELSE glennbot_scheduled_posts.media_preview_url END,
                        permalink_url = CASE WHEN EXCLUDED.permalink_url IS NOT NULL AND EXCLUDED.permalink_url != '' AND (glennbot_scheduled_posts.permalink_url IS NULL OR glennbot_scheduled_posts.permalink_url = '' OR (glennbot_scheduled_posts.permalink_url LIKE 'https://www.facebook.com/%_%' AND EXCLUDED.permalink_url LIKE '%/posts/%')) THEN EXCLUDED.permalink_url ELSE COALESCE(glennbot_scheduled_posts.permalink_url, EXCLUDED.permalink_url) END
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
                ORDER BY CASE
                    WHEN id IN ('post_ext_dc6a96869a', 'post_ext_b10078462e', 'post_ext_19fdfb7f26') THEN 0
                    WHEN LOWER(COALESCE(account_name, '')) IN ('glennbot automations', '@glennbot.automation', 'glennbot.automation') THEN 1
                    ELSE 2
                END, scheduled_time DESC
                LIMIT 150
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
