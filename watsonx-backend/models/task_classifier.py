"""
task_classifier.py – Enrich detected patterns using ICA Agentic Studio.

Replaces the Granite / watsonx.ai call with an ICA agent chat call.
The prompt contract is identical; only the transport layer changes.
"""
import json
import logging

from utils.ica_client import get_ica_client

log = logging.getLogger(__name__)

# ── Prompt templates ──────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an AI productivity assistant. "
    "Given a list of detected user activity patterns on Windows, "
    "identify the top automation opportunities and recommend specific AI tools. "
    "Return ONLY a valid JSON array – no markdown fences, no prose, no explanation."
)

_USER_TEMPLATE = """Detected patterns (JSON):
{patterns_json}

For each pattern return a JSON object with EXACTLY these keys:
  pattern_name, opportunity_title, opportunity_description,
  recommended_tool, estimated_time_saving_minutes (integer), tutorial_link

Return a JSON array of those objects and nothing else."""


# ── Public API ────────────────────────────────────────────────────

def analyze_patterns(patterns: list) -> list:
    """
    Send patterns to the ICA agent for enrichment.
    Falls back to deterministic rules if the agent is unavailable
    or returns malformed JSON.
    """
    if not patterns:
        return []

    client = get_ica_client()
    prompt = _USER_TEMPLATE.format(patterns_json=json.dumps(patterns, indent=2))

    try:
        raw_text = client.generate(prompt=prompt, system_prompt=_SYSTEM_PROMPT)
        log.info("ICA raw response: %s", raw_text[:500])

        # Strip accidental markdown fences if the agent adds them anyway
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        opportunities = json.loads(cleaned)
        if not isinstance(opportunities, list):
            raise ValueError("Expected a JSON array, got: " + type(opportunities).__name__)

        log.info(
            "ICA agent analyzed %d patterns → %d opportunities",
            len(patterns), len(opportunities),
        )
        return opportunities

    except json.JSONDecodeError as exc:
        log.error("ICA agent returned non-JSON response: %s | raw text was: %s", exc, raw_text[:300])
        return _rule_based_fallback(patterns)
    except Exception as exc:
        log.error("ICA call failed: %s", exc, exc_info=True)
        return _rule_based_fallback(patterns)


# ── Fallback: deterministic rule-based mapping ────────────────────

_FALLBACK_MAP = {
    "manual_data_entry": {
        "opportunity_title": "Automate Data Entry with AI",
        "opportunity_description": (
            "You spend significant time typing data into spreadsheets. "
            "Use IBM RPA or a Python script with pandas/openpyxl to automate this."
        ),
        "recommended_tool": "IBM RPA / Python openpyxl",
        "estimated_time_saving_minutes": 45,
        "tutorial_link": "https://www.ibm.com/products/robotic-process-automation",
    },
    "repetitive_copy_paste": {
        "opportunity_title": "Replace Copy-Paste with Automation",
        "opportunity_description": (
            "Frequent copy-paste between apps can be eliminated with Power Automate "
            "or a Python script using pyperclip and win32com."
        ),
        "recommended_tool": "Microsoft Power Automate",
        "estimated_time_saving_minutes": 30,
        "tutorial_link": "https://powerautomate.microsoft.com",
    },
    "email_sorting": {
        "opportunity_title": "AI Email Triage via ICA",
        "opportunity_description": (
            "Use ICA Agentic Studio to classify and auto-route emails, "
            "saving hours of manual sorting each week."
        ),
        "recommended_tool": "ICA Agentic Studio + Outlook Rules",
        "estimated_time_saving_minutes": 25,
        "tutorial_link": "https://www.ibm.com/consulting/ica",
    },
    "document_formatting": {
        "opportunity_title": "Automate Document Styling",
        "opportunity_description": (
            "Python-docx templates or Word macros can apply consistent formatting "
            "in seconds instead of minutes."
        ),
        "recommended_tool": "python-docx / Word VBA",
        "estimated_time_saving_minutes": 20,
        "tutorial_link": "https://python-docx.readthedocs.io",
    },
    "file_organization": {
        "opportunity_title": "Smart File Organization Script",
        "opportunity_description": (
            "A Python watchdog script can automatically move files "
            "into the correct folders based on name, date, or content."
        ),
        "recommended_tool": "Python watchdog",
        "estimated_time_saving_minutes": 15,
        "tutorial_link": "https://python-watchdog.readthedocs.io",
    },
    "browser_research": {
        "opportunity_title": "AI Research Summarization via ICA",
        "opportunity_description": (
            "Ask your ICA agent to summarize web content in bulk, "
            "cutting research time dramatically."
        ),
        "recommended_tool": "ICA Agentic Studio",
        "estimated_time_saving_minutes": 35,
        "tutorial_link": "https://www.ibm.com/consulting/ica",
    },
    "report_generation": {
        "opportunity_title": "Automated Report Generation Pipeline",
        "opportunity_description": (
            "Combine Python pandas + python-docx with an ICA agent for the "
            "executive-summary section, then schedule with Windows Task Scheduler."
        ),
        "recommended_tool": "pandas + python-docx + ICA Agentic Studio",
        "estimated_time_saving_minutes": 60,
        "tutorial_link": "https://pandas.pydata.org",
    },
}


def _rule_based_fallback(patterns: list) -> list:
    results = []
    for p in patterns:
        name = p.get("pattern_name", "")
        if name in _FALLBACK_MAP:
            results.append({"pattern_name": name, **_FALLBACK_MAP[name]})
    return results
