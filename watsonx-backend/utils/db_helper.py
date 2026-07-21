"""
db_helper.py – Local SQLite backend store.

Replaces the IBM Cloudant helper.  Uses the same SQLite file as the
desktop client so the whole project runs with zero cloud database
dependencies.

Tables managed here (backend-side):
  activity_batches  – ingest endpoint writes here
  feedback          – feedback endpoint writes here

The desktop client's own tables (activity_records, suggestions, etc.)
live in the same file but are managed by client/database.py.
"""
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Resolve: watsonx-backend/utils/ → project-root/data/local.db
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "local.db"


# ── Connection factory ────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema bootstrap ──────────────────────────────────────────────

def init_backend_tables() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity_batches (
                id                 TEXT PRIMARY KEY,
                received_at        TEXT NOT NULL,
                user_id            TEXT,
                session_json       TEXT,
                metrics_json       TEXT,
                patterns_json      TEXT,
                opportunities_json TEXT,
                analyzed_at        TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_id  TEXT    NOT NULL,
                helpful        INTEGER NOT NULL,
                created_at     TEXT    NOT NULL
            );
        """)
    log.debug("Backend SQLite tables ready at %s", _DB_PATH)


# ── Public DB handle ──────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_db() -> "_LocalDB":
    """Return a lazily-initialised local DB handle (replaces get_cloudant_client)."""
    init_backend_tables()
    return _LocalDB()


class _LocalDB:
    """
    Drop-in replacement for the old _CloudantDB.
    Exposes the same method names so Cloud Function code changes are minimal.
    """

    # ── activity_batches ──────────────────────────────────────────

    def create_document(self, doc: dict) -> dict:
        doc_id = doc.get("_id") or str(uuid.uuid4())
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO activity_batches
                    (id, received_at, user_id, session_json,
                     metrics_json, patterns_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    doc.get("received_at", datetime.utcnow().isoformat()),
                    doc.get("session", {}).get("user_id", "unknown"),
                    json.dumps(doc.get("session", {})),
                    json.dumps(doc.get("metrics", {})),
                    json.dumps(doc.get("patterns", [])),
                ),
            )
        return {"id": doc_id}

    def get_document(self, doc_id: str) -> dict:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM activity_batches WHERE id = ?", (doc_id,)
            ).fetchone()
        if not row:
            return {}
        return self._row_to_doc(dict(row))

    def update_document(self, doc: dict) -> dict:
        with _connect() as conn:
            conn.execute(
                """
                UPDATE activity_batches
                SET opportunities_json = ?, analyzed_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(doc.get("opportunities", [])),
                    doc.get("analyzed_at", datetime.utcnow().isoformat()),
                    doc["_id"],
                ),
            )
        return {"id": doc["_id"]}

    def get_query_result(
        self, selector: dict, fields: list = None, limit: int = 25
    ) -> list:
        """
        Simplified selector support:
          'session.user_id'  → filters by user_id column
          'received_at': {'$gte': iso_string}  → date cutoff
        """
        user_id = selector.get("session.user_id", "")
        cutoff  = selector.get("received_at", {}).get("$gte", "")

        sql: str       = "SELECT * FROM activity_batches WHERE 1=1"
        params: list[Any] = []

        if user_id:
            sql += " AND user_id = ?"
            params.append(user_id)
        if cutoff:
            sql += " AND received_at >= ?"
            params.append(cutoff)

        sql += f" ORDER BY received_at DESC LIMIT {int(limit)}"

        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        docs = [self._row_to_doc(dict(r)) for r in rows]

        if fields:
            docs = [{k: d[k] for k in fields if k in d} for d in docs]

        return docs

    # ── feedback ──────────────────────────────────────────────────

    def create_feedback(self, suggestion_id: str, helpful: bool) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO feedback (suggestion_id, helpful, created_at) VALUES (?, ?, ?)",
                (str(suggestion_id), 1 if helpful else 0, datetime.utcnow().isoformat()),
            )

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _row_to_doc(row: dict) -> dict:
        return {
            "_id":           row.get("id", ""),
            "type":          "activity_batch",
            "received_at":   row.get("received_at", ""),
            "session":       json.loads(row.get("session_json") or "{}"),
            "metrics":       json.loads(row.get("metrics_json") or "{}"),
            "patterns":      json.loads(row.get("patterns_json") or "[]"),
            "opportunities": json.loads(row.get("opportunities_json") or "[]"),
            "analyzed_at":   row.get("analyzed_at", ""),
        }

    def __getitem__(self, doc_id: str) -> dict:
        return self.get_document(doc_id)
