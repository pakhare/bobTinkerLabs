"""
data_processor.py – Aggregate raw activity records and detect automation patterns.
"""
import hashlib
import json
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, date
from typing import List, Dict, Any, Tuple

log = logging.getLogger(__name__)

# ── Pattern detection rules ───────────────────────────────────────

class PatternRule:
    """Declarative definition of a detectable pattern."""

    def __init__(
        self,
        name: str,
        description: str,
        category_weights: Dict[str, float],
        min_kb_rate: float = 0,
        min_mc_rate: float = 0,
        min_occurrences: int = 3,
        confidence_base: float = 0.70,
    ):
        self.name = name
        self.description = description
        self.category_weights = category_weights   # {category: weight}
        self.min_kb_rate = min_kb_rate             # keystrokes/minute threshold
        self.min_mc_rate = min_mc_rate             # clicks/minute threshold
        self.min_occurrences = min_occurrences
        self.confidence_base = confidence_base


PATTERN_RULES: List[PatternRule] = [
    PatternRule(
        name="manual_data_entry",
        description="Repeated high-volume typing in a spreadsheet or form",
        category_weights={"spreadsheet": 1.0, "document": 0.6, "browser": 0.4},
        min_kb_rate=60,
        confidence_base=0.78,
    ),
    PatternRule(
        name="repetitive_copy_paste",
        description="Switching between two apps with frequent keyboard activity",
        category_weights={"spreadsheet": 0.8, "document": 0.8, "browser": 0.6, "other": 0.4},
        min_kb_rate=20,
        min_occurrences=5,
        confidence_base=0.85,
    ),
    PatternRule(
        name="email_sorting",
        description="Prolonged email client usage with repetitive mouse clicks",
        category_weights={"email": 1.0},
        min_mc_rate=10,
        confidence_base=0.82,
    ),
    PatternRule(
        name="document_formatting",
        description="Repeated short actions in a word processor",
        category_weights={"document": 1.0, "presentation": 0.7},
        min_kb_rate=15,
        min_mc_rate=8,
        confidence_base=0.75,
    ),
    PatternRule(
        name="file_organization",
        description="Extensive file explorer operations",
        category_weights={"file_management": 1.0},
        min_mc_rate=5,
        min_occurrences=4,
        confidence_base=0.80,
    ),
    PatternRule(
        name="browser_research",
        description="Long repeated browser sessions with frequent navigation",
        category_weights={"browser": 1.0},
        min_mc_rate=12,
        min_occurrences=5,
        confidence_base=0.68,
    ),
    PatternRule(
        name="report_generation",
        description="Cycling between spreadsheet, document, and email",
        category_weights={"spreadsheet": 0.7, "document": 0.7, "email": 0.5},
        min_kb_rate=30,
        min_occurrences=3,
        confidence_base=0.72,
    ),
]


# ── DataProcessor ─────────────────────────────────────────────────

class DataProcessor:
    """Stateless processor – operates on lists of activity dicts from the DB."""

    # ── Aggregation ───────────────────────────────────────────────

    def aggregate_activities(self, raw_data: List[dict]) -> Dict[str, Any]:
        """Group raw per-interval records into a daily session summary."""
        if not raw_data:
            return {}

        total_duration = sum(r.get("duration_seconds", 0) for r in raw_data)
        total_idle = sum(r.get("idle_time", 0) for r in raw_data)
        active_time = max(total_duration - total_idle, 0)

        category_time: Counter = Counter()
        app_time: Counter = Counter()
        for r in raw_data:
            dur = r.get("duration_seconds", 0)
            category_time[r.get("category", "other")] += dur
            app_time[r.get("app_name", "UNKNOWN")] += dur

        timestamps = [r["timestamp"] for r in raw_data if r.get("timestamp")]
        timestamps.sort()

        return {
            "session_date": date.today().isoformat(),
            "user_id": self._hashed_user_id(),
            "start_time": timestamps[0] if timestamps else "",
            "end_time": timestamps[-1] if timestamps else "",
            "total_active_time": active_time,
            "total_idle_time": total_idle,
            "top_categories": dict(category_time.most_common(5)),
            "top_apps": dict(app_time.most_common(5)),
            "record_count": len(raw_data),
        }

    # ── Pattern detection ─────────────────────────────────────────

    def detect_patterns(self, activities: List[dict]) -> List[dict]:
        """Return a list of detected pattern dicts, sorted by confidence desc."""
        if not activities:
            return []

        detected = []
        for rule in PATTERN_RULES:
            result = self._evaluate_rule(rule, activities)
            if result:
                detected.append(result)

        detected.sort(key=lambda p: p["confidence"], reverse=True)
        return detected

    def _evaluate_rule(self, rule: PatternRule, activities: List[dict]) -> Dict | None:
        matching = [
            a for a in activities
            if a.get("category", "other") in rule.category_weights
        ]
        if len(matching) < rule.min_occurrences:
            return None

        # Weighted category score
        weight_sum = sum(
            rule.category_weights.get(a.get("category", "other"), 0)
            for a in matching
        )

        # Keyboard rate: total keystrokes / total minutes active
        total_minutes = max(sum(a.get("duration_seconds", 0) for a in matching) / 60, 0.1)
        kb_rate = sum(a.get("keyboard_events", 0) for a in matching) / total_minutes
        mc_rate = sum(a.get("mouse_clicks", 0) for a in matching) / total_minutes

        if kb_rate < rule.min_kb_rate and rule.min_kb_rate > 0:
            return None
        if mc_rate < rule.min_mc_rate and rule.min_mc_rate > 0:
            return None

        # Scale confidence by category match density
        density = len(matching) / max(len(activities), 1)
        confidence = min(rule.confidence_base * (1 + density * 0.2), 0.99)

        return {
            "session_date": date.today().isoformat(),
            "pattern_name": rule.name,
            "description": rule.description,
            "confidence": round(confidence, 3),
            "context": self._summarize_context(matching),
            "raw_json": json.dumps(
                {"kb_rate": round(kb_rate, 1), "mc_rate": round(mc_rate, 1), "matches": len(matching)}
            ),
        }

    def _summarize_context(self, activities: List[dict]) -> str:
        apps = Counter(a.get("app_name", "?") for a in activities)
        top = ", ".join(f"{app}({cnt})" for app, cnt in apps.most_common(3))
        return f"Detected in: {top}"

    # ── Anonymization ─────────────────────────────────────────────

    def anonymize_data(self, data: dict) -> dict:
        """Strip any remaining PII before sending to the cloud."""
        safe = json.loads(json.dumps(data))  # deep copy
        if "user_id" not in safe:
            safe["user_id"] = self._hashed_user_id()
        # Remove raw window titles from cloud payload
        for record in safe.get("activities", []):
            record.pop("window_title", None)
            record.pop("process_id", None)
        return safe

    # ── Metrics ───────────────────────────────────────────────────

    def calculate_metrics(self, activities: List[dict]) -> dict:
        if not activities:
            return {}
        total_dur = sum(a.get("duration_seconds", 0) for a in activities)
        total_idle = sum(a.get("idle_time", 0) for a in activities)
        active = max(total_dur - total_idle, 0)
        productivity_score = round(active / max(total_dur, 1), 3)

        kb_total = sum(a.get("keyboard_events", 0) for a in activities)
        mc_total = sum(a.get("mouse_clicks", 0) for a in activities)

        return {
            "total_duration_minutes": round(total_dur / 60, 1),
            "active_minutes": round(active / 60, 1),
            "idle_minutes": round(total_idle / 60, 1),
            "productivity_score": productivity_score,
            "total_keystrokes": kb_total,
            "total_mouse_clicks": mc_total,
        }

    # ── Cloud batch preparation ───────────────────────────────────

    def prepare_cloud_batch(self, activities: List[dict]) -> dict:
        aggregated = self.aggregate_activities(activities)
        patterns = self.detect_patterns(activities)
        metrics = self.calculate_metrics(activities)

        batch = {
            "session": aggregated,
            "metrics": metrics,
            "patterns": patterns,
        }
        return self.anonymize_data(batch)

    # ── Utility ───────────────────────────────────────────────────

    @staticmethod
    def _hashed_user_id() -> str:
        """Deterministic, non-reversible user identifier (machine+user)."""
        raw = f"{os.getenv('COMPUTERNAME', 'PC')}:{os.getenv('USERNAME', 'user')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
