"""
cloud_client.py – Local backend client.

The "backend" functions run in-process (no HTTP server needed).
This module imports the watsonx-backend Python modules directly and
calls them as regular functions, writing results into the shared
local SQLite database.
"""
import json
import logging
import sys
import threading
from pathlib import Path
from typing import List

from config import settings
from database import (
    enqueue,
    get_pending_queue,
    remove_queue_item,
    increment_queue_attempts,
    upsert_suggestion,
    get_unuploaded_activities,
    mark_activities_uploaded,
)
from data_processor import DataProcessor

log = logging.getLogger(__name__)

_processor = DataProcessor()

# ── Make watsonx-backend importable ──────────────────────────────
# We need:
#   • watsonx-backend/functions/ on path  → `import suggestion_engine`
#   • watsonx-backend/            on path  → `from utils.db_helper import`
#   • watsonx-backend/models/     on path  → `from task_classifier import`
_BACKEND_ROOT = Path(__file__).parent.parent / "watsonx-backend"
for _subdir in (_BACKEND_ROOT, _BACKEND_ROOT / "functions",
                _BACKEND_ROOT / "models", _BACKEND_ROOT / "utils"):
    _ps = str(_subdir)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)


class CloudClient:
    """Calls backend functions in-process; no network required."""

    def __init__(self):
        self._stop_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────

    def start_sync_loop(self) -> None:
        self._stop_event.clear()
        t = threading.Thread(target=self._sync_loop, daemon=True, name="BackendSync")
        t.start()
        log.info("Backend sync loop started (interval: %ss)", settings.sync_interval)

    def stop_sync_loop(self) -> None:
        self._stop_event.set()

    def sync_now(self) -> None:
        self._do_sync()

    def fetch_suggestions(self) -> List[dict]:
        """Call the suggestion engine directly and persist results locally."""
        try:
            from suggestion_engine import main as _suggest

            # Build the user_id the same way data_processor does
            import hashlib, os
            raw = f"{os.getenv('COMPUTERNAME', 'PC')}:{os.getenv('USERNAME', 'user')}"
            user_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

            result = _suggest({"user_id": user_id})
            suggestions = json.loads(result.get("body", "{}")).get("suggestions", [])
            for s in suggestions:
                upsert_suggestion(s)
            log.info("Fetched %d suggestions from local backend.", len(suggestions))
            return suggestions
        except Exception as exc:
            log.warning("fetch_suggestions failed: %s", exc)
            return []

    def chat(
        self,
        user_message: str,
        session_id: str | None = None,
    ) -> tuple[str, str]:
        """
        Send a message to the ICA Agentic Studio conversational agent.

        Parameters
        ----------
        user_message : str
            The text the user typed.
        session_id : str | None
            Pass an existing session ID to continue a conversation,
            or None to start a fresh one.

        Returns
        -------
        (reply_text, session_id)
            The agent's reply and the session ID to pass on the next call.
        """
        try:
            from agent_runner import AgentRunner

            # Build live context snippets from today's activity data
            context = self._build_context_snippets()

            if session_id:
                try:
                    runner = AgentRunner.load_session(session_id, context)
                except ValueError:
                    runner = AgentRunner.new_session(context)
            else:
                runner = AgentRunner.new_session(context)

            reply = runner.chat(user_message)
            runner.save()
            return reply, runner.session_id

        except Exception as exc:
            log.error("CloudClient.chat failed: %s", exc, exc_info=True)
            return (
                "⚠ Could not reach the AI agent. "
                "Check your ICA credentials in config/api_keys.json.",
                session_id or "",
            )

    def _build_context_snippets(self) -> list:
        """Return a short list of strings describing today's activity patterns."""
        try:
            activities = get_unuploaded_activities()
            patterns = _processor.detect_patterns(activities)
            metrics = _processor.calculate_metrics(activities)

            snippets = []
            if metrics:
                snippets.append(
                    f"Active today: {metrics.get('active_minutes', 0):.0f} min, "
                    f"productivity score: {metrics.get('productivity_score', 0)*100:.0f}%"
                )
            for p in patterns[:5]:
                snippets.append(
                    f"Pattern '{p['pattern_name']}' detected "
                    f"(confidence {int(p['confidence']*100)}%): {p['description']}"
                )
            return snippets
        except Exception as exc:
            log.warning("_build_context_snippets failed: %s", exc)
            return []

    def submit_feedback(self, suggestion_id: int, helpful: bool) -> None:
        try:
            from feedback_handler import main as _feedback
            _feedback({"suggestion_id": suggestion_id, "helpful": helpful})
        except Exception as exc:
            log.warning("submit_feedback failed (queued): %s", exc)
            enqueue("feedback/submit", {"suggestion_id": suggestion_id, "helpful": helpful})

    # ── Sync internals ────────────────────────────────────────────

    def _sync_loop(self) -> None:
        while not self._stop_event.wait(timeout=settings.sync_interval):
            self._do_sync()

    def _do_sync(self) -> None:
        log.debug("Starting sync cycle …")
        self._process_activities()
        self._flush_offline_queue()

    def _process_activities(self) -> None:
        activities = get_unuploaded_activities()
        if not activities:
            log.debug("No new activities to process.")
            return

        batch = _processor.prepare_cloud_batch(activities)
        ids = [a["id"] for a in activities]
        try:
            from activity_ingestion import main as _ingest
            result = _ingest(batch)
            if result.get("statusCode", 500) == 200:
                mark_activities_uploaded(ids)
                log.info("Processed %d activity records.", len(activities))
            else:
                log.warning("Ingest returned status %s", result.get("statusCode"))
        except Exception as exc:
            log.warning("Activity processing failed: %s", exc)
            enqueue("activity/ingest", batch)

    def _flush_offline_queue(self) -> None:
        pending = get_pending_queue()
        if not pending:
            return
        log.info("Flushing %d queued items …", len(pending))
        for item in pending:
            try:
                payload = json.loads(item["payload"])
                endpoint = item["endpoint"]

                if endpoint == "activity/ingest":
                    from activity_ingestion import main as _fn
                elif endpoint == "feedback/submit":
                    from feedback_handler import main as _fn
                else:
                    log.warning("Unknown queued endpoint: %s", endpoint)
                    continue

                result = _fn(payload)
                if result.get("statusCode", 500) == 200:
                    remove_queue_item(item["id"])
                else:
                    increment_queue_attempts(item["id"])
            except Exception as exc:
                log.warning("Queue item %d still failing: %s", item["id"], exc)
                increment_queue_attempts(item["id"])
