"""
suggestion_engine.py – Cloud Function: generate and return personalised suggestions.

Storage backend: local SQLite (replaces IBM Cloudant).

GET /suggestions/get?user_id=<hashed_user_id>
"""
import json
import logging
from datetime import datetime, timedelta

from utils.db_helper import get_db
from models.task_classifier import analyze_patterns

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main(params: dict) -> dict:
    """Cloud Functions entry point."""
    try:
        user_id = (
            params.get("user_id")
            or params.get("__ow_query", {}).get("user_id", "unknown")
        )
        suggestions = _generate_suggestions(user_id)
        return _response(200, {"suggestions": suggestions})
    except Exception as exc:
        log.exception("suggestion_engine failed")
        return _response(500, {"error": str(exc)})


# ── Core logic ────────────────────────────────────────────────────

def _generate_suggestions(user_id: str) -> list:
    db = get_db()

    # Fetch recent batches for this user (last 7 days) from local SQLite
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    docs = db.get_query_result(
        {"session.user_id": user_id, "received_at": {"$gte": cutoff}},
        fields=["patterns", "metrics"],
        limit=50,
    )

    # Aggregate all patterns across recent batches
    all_patterns: list = []
    for doc in docs:
        all_patterns.extend(doc.get("patterns", []))

    if not all_patterns:
        log.info("No patterns found for user %s – returning empty suggestions.", user_id)
        return []

    # De-duplicate by pattern_name, keep highest confidence
    best: dict = {}
    for p in all_patterns:
        name = p.get("pattern_name", "")
        if name not in best or p.get("confidence", 0) > best[name].get("confidence", 0):
            best[name] = p

    top_patterns = sorted(
        best.values(), key=lambda x: x.get("confidence", 0), reverse=True
    )[:5]

    # Enrich with ICA agent analysis
    opportunities = analyze_patterns(top_patterns)

    return [
        {
            "received_at":         datetime.utcnow().isoformat(),
            "title":               opp.get("opportunity_title", "Automation Opportunity"),
            "description":         opp.get("opportunity_description", ""),
            "tool_name":           opp.get("recommended_tool", ""),
            "tutorial_url":        opp.get("tutorial_link", ""),
            "time_saving_minutes": opp.get("estimated_time_saving_minutes", 0),
        }
        for opp in opportunities
    ]


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
