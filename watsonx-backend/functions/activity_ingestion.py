"""
activity_ingestion.py – Cloud Function: receive and persist activity batches.

Storage backend: local SQLite (replaces IBM Cloudant).

Expected payload (POST body):
{
  "session": { ... },
  "metrics": { ... },
  "patterns": [ ... ]
}
"""
import json
import logging
import uuid
from datetime import datetime

from utils.db_helper import get_db
from utils.validators import validate_ingest_payload

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main(params: dict) -> dict:
    """Cloud Functions entry point."""
    try:
        body = _parse_body(params)
        errors = validate_ingest_payload(body)
        if errors:
            return _response(400, {"error": "Validation failed", "details": errors})

        doc_id = _persist(body)
        return _response(200, {"status": "ok", "doc_id": doc_id})

    except Exception as exc:
        log.exception("activity_ingestion failed")
        return _response(500, {"error": str(exc)})


# ── Helpers ───────────────────────────────────────────────────────

def _parse_body(params: dict) -> dict:
    if "body" in params and isinstance(params["body"], str):
        return json.loads(params["body"])
    return params


def _persist(payload: dict) -> str:
    db = get_db()
    doc = {
        "_id":         str(uuid.uuid4()),
        "type":        "activity_batch",
        "received_at": datetime.utcnow().isoformat(),
        "session":     payload.get("session", {}),
        "metrics":     payload.get("metrics", {}),
        "patterns":    payload.get("patterns", []),
    }
    result = db.create_document(doc)
    return result["id"]


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
