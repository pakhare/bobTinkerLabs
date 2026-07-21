"""
ica_client.py – Thin REST wrapper around ICA Agentic Studio.

Replaces watsonx_client.py.  No IBM SDK required – just plain HTTP.

Credentials (priority: env var → config/api_keys.json):
  ICA_API_URL   – base URL,  e.g. https://api.ica.ibm.com/v1
  ICA_API_KEY   – bearer token / API key
  ICA_AGENT_ID  – the agent to send messages to
"""
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# ── Credential resolution ─────────────────────────────────────────

def _load_api_keys() -> dict:
    keys_path = Path(__file__).parent.parent.parent / "config" / "api_keys.json"
    if keys_path.exists():
        with open(keys_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _get(env_var: str, json_key: str) -> str:
    value = os.environ.get(env_var) or _load_api_keys().get(json_key, "")
    if not value:
        raise EnvironmentError(
            f"Missing credential: set '{env_var}' env var "
            f"or '{json_key}' in config/api_keys.json"
        )
    return value


# ── Public factory ────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_ica_client() -> "_ICAClient":
    api_url  = _get("ICA_API_URL",  "ica_api_url")
    api_key  = _get("ICA_API_KEY",  "ica_api_key")
    agent_id = _get("ICA_AGENT_ID", "ica_agent_id")
    log.info("ICA client initialised (agent=%s)", agent_id)
    return _ICAClient(api_url.rstrip("/"), api_key, agent_id)


class _ICAClient:
    """
    Sends a prompt to an ICA Agentic Studio agent via the A2A protocol.

    Confirmed working request shape (IBM ICA, method=message/send):
      POST {base_url}/{agent_id}/a2a
      {
        "jsonrpc": "2.0",
        "id":      "<uuid>",
        "method":  "message/send",
        "params": {
          "message": {
            "messageId": "<uuid>",
            "role":      "user",
            "parts":     [{"kind": "text", "text": "<prompt>"}]
          }
        }
      }

    Response shape:
      {
        "jsonrpc": "2.0",
        "id": "<uuid>",
        "result": {
          "message": {
            "contextId": "...",
            "messageId": "...",
            "role":      "agent",
            "parts":     [{"kind": "text", "text": "<reply>"}]
          }
        }
      }
    """

    # base_url already contains /apis/v3/ica/agent-registry
    _CHAT_PATH = "/{agent_id}/a2a"

    def __init__(self, base_url: str, api_key: str, agent_id: str):
        self._base_url = base_url
        self._agent_id = agent_id
        self._session  = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        })

    def generate(self, prompt: str, system_prompt: str = "", timeout: int = 30) -> str:
        """Send a prompt via A2A message/send and return the agent's reply text."""
        import uuid

        # Combine system prompt + user prompt into a single user turn.
        # A2A message/send carries one message object; prepend system context
        # as plain text when provided.
        if system_prompt:
            full_text = f"{system_prompt}\n\n{prompt}"
        else:
            full_text = prompt

        payload = {
            "jsonrpc": "2.0",
            "id":      str(uuid.uuid4()),
            "method":  "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role":      "user",
                    "parts":     [{"kind": "text", "text": full_text}],
                }
            },
        }

        url = self._base_url + self._CHAT_PATH.format(agent_id=self._agent_id)
        log.info("ICA A2A request -> POST %s", url)
        resp = self._session.post(url, json=payload, timeout=timeout)
        log.info("ICA response status: %s", resp.status_code)
        if not resp.ok:
            log.error("ICA error body: %s", resp.text[:500])
        resp.raise_for_status()

        return self._parse_a2a_response(resp.json())

    @staticmethod
    def _parse_a2a_response(data: dict) -> str:
        """Extract the reply text from an A2A message/send response."""
        result = data.get("result", {})

        # IBM ICA shape: result.message.parts[0].text
        msg = result.get("message", {})
        parts = msg.get("parts", [])
        if parts and "text" in parts[0]:
            return str(parts[0]["text"])

        # Fallback: result.output (some variants)
        if "output" in result:
            return str(result["output"])

        # Last resort: return raw JSON so callers can still attempt to parse
        return json.dumps(data)
