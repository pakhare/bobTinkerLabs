"""
database.py – Local SQLite persistence layer.
"""
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from config import settings

log = logging.getLogger(__name__)


def _get_connection() -> sqlite3.Connection:
    db_path: Path = settings.local_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they do not already exist."""
    with _get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activity_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                app_name    TEXT    NOT NULL,
                window_title TEXT   NOT NULL,
                process_id  INTEGER,
                duration_seconds INTEGER DEFAULT 0,
                keyboard_events  INTEGER DEFAULT 0,
                mouse_clicks     INTEGER DEFAULT 0,
                category    TEXT,
                idle_time   INTEGER DEFAULT 0,
                uploaded    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS detected_patterns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT   NOT NULL,
                pattern_name TEXT   NOT NULL,
                confidence  REAL,
                context     TEXT,
                raw_json    TEXT
            );

            CREATE TABLE IF NOT EXISTS suggestions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT    NOT NULL,
                title       TEXT    NOT NULL,
                description TEXT,
                tool_name   TEXT,
                tutorial_url TEXT,
                time_saving_minutes INTEGER,
                dismissed   INTEGER DEFAULT 0,
                helpful     INTEGER
            );

            CREATE TABLE IF NOT EXISTS sync_queue (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT    NOT NULL,
                endpoint    TEXT    NOT NULL,
                payload     TEXT    NOT NULL,
                attempts    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          TEXT    PRIMARY KEY,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                title       TEXT,
                messages    TEXT    NOT NULL
            );
            """
        )
    log.info("Local database initialized at %s", settings.local_db_path)


# ── Activity records ──────────────────────────────────────────────

def insert_activity(record: dict) -> None:
    sql = """
        INSERT INTO activity_records
            (timestamp, app_name, window_title, process_id,
             duration_seconds, keyboard_events, mouse_clicks,
             category, idle_time)
        VALUES
            (:timestamp, :app_name, :window_title, :process_id,
             :duration_seconds, :keyboard_events, :mouse_clicks,
             :category, :idle_time)
    """
    with _get_connection() as conn:
        conn.execute(sql, record)


def get_unuploaded_activities() -> List[dict]:
    sql = "SELECT * FROM activity_records WHERE uploaded = 0 ORDER BY timestamp"
    with _get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def mark_activities_uploaded(ids: List[int]) -> None:
    placeholders = ",".join("?" * len(ids))
    sql = f"UPDATE activity_records SET uploaded = 1 WHERE id IN ({placeholders})"
    with _get_connection() as conn:
        conn.execute(sql, ids)


# ── Patterns ──────────────────────────────────────────────────────

def insert_pattern(pattern: dict) -> None:
    sql = """
        INSERT INTO detected_patterns (session_date, pattern_name, confidence, context, raw_json)
        VALUES (:session_date, :pattern_name, :confidence, :context, :raw_json)
    """
    with _get_connection() as conn:
        conn.execute(sql, pattern)


# ── Suggestions ───────────────────────────────────────────────────

def upsert_suggestion(s: dict) -> None:
    sql = """
        INSERT OR REPLACE INTO suggestions
            (received_at, title, description, tool_name, tutorial_url, time_saving_minutes)
        VALUES
            (:received_at, :title, :description, :tool_name, :tutorial_url, :time_saving_minutes)
    """
    with _get_connection() as conn:
        conn.execute(sql, s)


def get_active_suggestions() -> List[dict]:
    sql = "SELECT * FROM suggestions WHERE dismissed = 0 ORDER BY time_saving_minutes DESC"
    with _get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def dismiss_suggestion(suggestion_id: int) -> None:
    with _get_connection() as conn:
        conn.execute("UPDATE suggestions SET dismissed = 1 WHERE id = ?", (suggestion_id,))


def rate_suggestion(suggestion_id: int, helpful: bool) -> None:
    with _get_connection() as conn:
        conn.execute(
            "UPDATE suggestions SET helpful = ? WHERE id = ?",
            (1 if helpful else 0, suggestion_id),
        )


# ── Sync queue ────────────────────────────────────────────────────

def enqueue(endpoint: str, payload: dict) -> None:
    sql = """
        INSERT INTO sync_queue (created_at, endpoint, payload, attempts)
        VALUES (?, ?, ?, 0)
    """
    with _get_connection() as conn:
        conn.execute(sql, (datetime.utcnow().isoformat(), endpoint, json.dumps(payload)))


def get_pending_queue() -> List[dict]:
    sql = "SELECT * FROM sync_queue WHERE attempts < 5 ORDER BY created_at"
    with _get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def remove_queue_item(item_id: int) -> None:
    with _get_connection() as conn:
        conn.execute("DELETE FROM sync_queue WHERE id = ?", (item_id,))


def increment_queue_attempts(item_id: int) -> None:
    with _get_connection() as conn:
        conn.execute("UPDATE sync_queue SET attempts = attempts + 1 WHERE id = ?", (item_id,))


# ── Housekeeping ──────────────────────────────────────────────────

def purge_old_records() -> None:
    """Delete records older than max_local_days to keep DB size bounded."""
    cutoff = (datetime.utcnow() - timedelta(days=settings.max_local_days)).isoformat()
    with _get_connection() as conn:
        conn.execute("DELETE FROM activity_records WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM detected_patterns WHERE session_date < ?", (cutoff[:10],))
    log.info("Purged records older than %s days", settings.max_local_days)
