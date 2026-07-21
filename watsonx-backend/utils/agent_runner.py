"""
agent_runner.py – Stateful conversational agent backed by ICA Agentic Studio.

This module sits one layer above ica_client.py.  It maintains a per-session
message history, injects the user's current activity context into the system
prompt, and provides a clean `chat()` API that the desktop client calls.

Agent persona: "Optimizer" – a productivity coach that is fully aware of the
user's detected activity patterns and can answer questions, suggest automations,
explain tools, and help plan implementation steps.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from utils.ica_client import get_ica_client

log = logging.getLogger(__name__)

# ── Database path (shared with db_helper.py) ─────────────────────────────────

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "local.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_chat_table() -> None:
    """Create the chat_sessions table if it does not exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          TEXT    PRIMARY KEY,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                title       TEXT,
                messages    TEXT    NOT NULL   -- JSON array of {role, content, ts}
            );
        """)
    log.debug("chat_sessions table ready.")


# ── System prompt factory ─────────────────────────────────────────────────────

_SYSTEM_BASE = """\
You are Optimizer, an AI productivity coach embedded in the AI Task Optimizer desktop app.
You have direct access to the user's recent Windows activity patterns detected on their machine.
Your job is to help the user:
  • Understand which of their workflows are good candidates for automation
  • Choose the right tool (IBM RPA, Power Automate, Python, ICA Agentic Studio, etc.)
  • Create step-by-step implementation plans they can follow today
  • Answer follow-up questions about any suggestion the app has already made

Always be concrete and actionable. When recommending a tool, mention the exact feature or
API to use. When giving steps, number them. Keep replies under 350 words unless the user
explicitly asks for detail.

Do NOT hallucinate pattern names or statistics. If you are unsure about a pattern detail,
say so and ask the user to check the "Today" tab for the latest data.
"""


def _build_system_prompt(context_snippets: List[str]) -> str:
    """Attach live activity context to the base system prompt."""
    if not context_snippets:
        return _SYSTEM_BASE
    ctx_block = "\n".join(f"  - {s}" for s in context_snippets)
    return (
        _SYSTEM_BASE
        + "\n\n## User's current activity context (from today's session)\n"
        + ctx_block
        + "\n\nUse the above context to personalise your answers.\n"
    )


# ── AgentRunner ───────────────────────────────────────────────────────────────

class AgentRunner:
    """
    Manages a single chat session.

    Usage:
        runner = AgentRunner.new_session(context_snippets=[...])
        reply  = runner.chat("How do I automate my Excel data entry?")
        reply2 = runner.chat("Can you show me a Python script for that?")
        runner.save()
    """

    MAX_HISTORY_MESSAGES = 20  # keep last N pairs to stay within context limits

    def __init__(self, session_id: str, messages: List[dict], context_snippets: List[str]):
        self._session_id = session_id
        self._messages: List[dict] = messages        # [{role, content, ts}]
        self._system_prompt = _build_system_prompt(context_snippets)
        self._client = get_ica_client()

    # ── Public API ────────────────────────────────────────────────────────────

    @classmethod
    def new_session(cls, context_snippets: List[str] | None = None) -> "AgentRunner":
        """Create a fresh session (not persisted until save() is called)."""
        init_chat_table()
        sid = str(uuid.uuid4())
        log.info("New agent session: %s", sid)
        return cls(sid, [], context_snippets or [])

    @classmethod
    def load_session(cls, session_id: str, context_snippets: List[str] | None = None) -> "AgentRunner":
        """Resume an existing session from the database."""
        init_chat_table()
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"Session {session_id} not found.")
        messages = json.loads(row["messages"])
        log.info("Resumed agent session: %s (%d messages)", session_id, len(messages))
        return cls(session_id, messages, context_snippets or [])

    def chat(self, user_message: str) -> str:
        """
        Send a user message, get the agent reply, update history.
        Returns the reply text.
        """
        ts = datetime.utcnow().isoformat()
        self._messages.append({"role": "user", "content": user_message, "ts": ts})

        try:
            # Flatten the trimmed conversation history into a readable transcript
            # so the ICA agent has full context.  The transcript is sent as the
            # `prompt` argument; the system prompt is prepended by ica_client.
            history = self._trimmed_history()
            transcript_lines = []
            for m in history:
                label = "User" if m["role"] == "user" else "Assistant"
                transcript_lines.append(f"{label}: {m['content']}")
            transcript = "\n".join(transcript_lines)

            reply = self._client.generate(
                prompt=transcript,
                system_prompt=self._system_prompt,
            )
        except Exception as exc:
            log.error("AgentRunner.chat failed: %s", exc, exc_info=True)
            reply = (
                "Sorry, I couldn't reach the AI agent right now. "
                "Please check your ICA credentials in config/api_keys.json and try again."
            )

        self._messages.append({"role": "assistant", "content": reply, "ts": datetime.utcnow().isoformat()})
        return reply

    def save(self) -> None:
        """Persist the session to SQLite."""
        init_chat_table()
        now = datetime.utcnow().isoformat()
        # Build a short title from the first user message
        title = next(
            (m["content"][:60] for m in self._messages if m["role"] == "user"),
            "New conversation",
        )
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, created_at, updated_at, title, messages)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    title      = excluded.title,
                    messages   = excluded.messages
                """,
                (
                    self._session_id,
                    now,
                    now,
                    title,
                    json.dumps(self._messages),
                ),
            )
        log.info("Session %s saved (%d messages).", self._session_id, len(self._messages))

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def history(self) -> List[dict]:
        """Return a copy of the full message history."""
        return list(self._messages)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _trimmed_history(self) -> List[dict]:
        """Return the last MAX_HISTORY_MESSAGES messages to avoid context overflow."""
        return self._messages[-self.MAX_HISTORY_MESSAGES:]


# ── Session list helper ───────────────────────────────────────────────────────

def list_sessions(limit: int = 20) -> List[dict]:
    """Return recent sessions ordered by last update, newest first."""
    init_chat_table()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, title FROM chat_sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
