"""
ml_analysis.py – Cloud Function: trigger ICA analysis on a stored batch.

Storage backend: local SQLite (replaces IBM Cloudant).

POST /activity/analyze  { "batch_id": "..." }
"""
import json
import logging
from datetime import datetime

from utils.db_helper import get_db
from models.task_classifier import analyze_patterns

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main(params: dict) -> dict:
    try:
        body = _parse_body(params)
        batch_id = body.get("batch_id")
        if not batch_id:
            return _response(400, {"error": "batch_id is required"})

        db = get_db()
        doc = db[batch_id]
        if not doc:
            return _response(404, {"error": "batch not found"})

        patterns = doc.get("patterns", [])
        opportunities = analyze_patterns(patterns)

        # Persist analysis results back into the same row
        doc["opportunities"] = opportunities
        doc["analyzed_at"]   = datetime.utcnow().isoformat()
        db.update_document(doc)

        return _response(200, {"opportunities": opportunities})

    except Exception as exc:
        log.exception("ml_analysis failed")
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
