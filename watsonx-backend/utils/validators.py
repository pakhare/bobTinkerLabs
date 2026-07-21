"""
validators.py – Input validation helpers for Cloud Functions.
"""
from typing import List


def validate_ingest_payload(payload: dict) -> List[str]:
    """Return a list of error messages; empty list means the payload is valid."""
    errors = []
    if not isinstance(payload, dict):
        return ["Payload must be a JSON object."]
    if "session" not in payload:
        errors.append("Missing required field: session")
    if "metrics" not in payload:
        errors.append("Missing required field: metrics")
    if "patterns" in payload and not isinstance(payload["patterns"], list):
        errors.append("Field 'patterns' must be an array.")
    return errors
