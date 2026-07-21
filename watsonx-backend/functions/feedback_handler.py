"""
feedback_handler.py – Cloud Function: record user feedback on suggestions.

Storage backend: local SQLite (replaces IBM Cloudant).

POST /feedback/submit  { "suggestion_id": "...", "helpful": true|false }
"""
import json
import logging
from datetime import datetime

from utils.db_helper import get_db

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main(params: dict) -> dict:
    try:
        body = _parse_body(params)
        suggestion_id = body.get("suggestion_id")
        helpful       = body.get("helpful")

        if suggestion_id is None or helpful is None:
            return _response(400, {"error": "suggestion_id and helpful are required"})

        db = get_db()
        db.create_feedback(
            suggestion_id=str(suggestion_id),
            helpful=bool(helpful),
        )
        log.info(
            "Feedback recorded: suggestion_id=%s helpful=%s", suggestion_id, helpful
        )
        return _response(200, {"status": "ok"})

    except Exception as exc:
        log.exception("feedback_handler failed")
        return _response(500, {"error": str(exc)})


def _parse_body(params: dict) -> dict:
    if "body" in params and isinstance(params["body"], str):
        return json.loads(params["body"])
    return params


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
