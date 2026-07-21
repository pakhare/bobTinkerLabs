"""
debug_ica.py  - final probe: message/send with messageId, vary contextId.
Run from the ai-task-optimizer directory:
    python debug_ica.py
"""
import json, sys, uuid
from pathlib import Path
import requests

keys_path = Path(__file__).parent / "config" / "api_keys.json"
keys = json.loads(keys_path.read_text())

BASE_URL  = keys["ica_api_url"].rstrip("/")
API_KEY   = keys["ica_api_key"]
AGENT_ID  = keys["ica_agent_id"]
URL       = f"{BASE_URL}/{AGENT_ID}/a2a"

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type":  "application/json",
    "Accept":        "application/json",
})

PROMPT = "Hello, confirm you are working. Reply in one sentence."

candidates = [
    # 1. messageId only, no contextId, kind:text
    {
        "label": "messageId only  kind:text",
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": PROMPT}],
            },
        },
    },
    # 2. messageId only, no contextId, no kind
    {
        "label": "messageId only  no kind",
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"text": PROMPT}],
            },
        },
    },
    # 3. messageId + contextId matching (same UUID reused as both IDs)
    {
        "label": "messageId + contextId same value",
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "contextId": AGENT_ID,   # use agent_id as context
                "role": "user",
                "parts": [{"kind": "text", "text": PROMPT}],
            },
        },
    },
    # 4. Wrap params in a "configuration" key (some IBM variants)
    {
        "label": "message/send  with configuration wrapper",
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": PROMPT}],
            },
            "configuration": {},
        },
    },
]

print(f"\nTarget URL: {URL}")
print("=" * 60)

for candidate in candidates:
    label = candidate.pop("label")
    print(f"\n[{label}]")
    print(f"  Payload : {json.dumps(candidate)[:350]}")
    try:
        resp = session.post(URL, json=candidate, timeout=30)
        print(f"  Status  : {resp.status_code}")
        try:
            body = json.dumps(resp.json(), indent=2)
        except Exception:
            body = resp.text
        print(f"  Body    : {body[:1200]}")
        if resp.ok:
            print("  >>> SUCCESS <<<")
            sys.exit(0)
    except Exception as exc:
        print(f"  ERROR   : {exc}")

print("\nAll shapes failed.")
