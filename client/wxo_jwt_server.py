"""
wxo_jwt_server.py – Localhost HTTP server for the watsonx Orchestrate chat widget.

Endpoints
---------
  GET  /          Returns the widget HTML page
  GET  /token     Returns a signed RS256 JWT for the widget's onGetUserToken callback

Why a JWT is required
---------------------
IBM watsonx Orchestrate requires embedded chat pages to authenticate each user
via a signed RS256 JWT.  The widget calls window.wxOConfiguration.onGetUserToken()
before it initialises; if no valid JWT is returned the widget shows an
authentication error.

The JWT is signed with the private key in config/wxo_private.pem.
The matching public key must be registered once in watsonx Orchestrate:
  watsonx Orchestrate UI → Embed chat → Security → Add public key
  (paste the contents of config/wxo_public.pem)

Run standalone for testing:
    python wxo_jwt_server.py --port 8765
"""
import argparse
import datetime
import http.server
import json
import pathlib
import socket
import sys
import threading
import uuid

# ── credential paths ──────────────────────────────────────────────
_CONFIG = pathlib.Path(__file__).parent.parent / "config"
_PRIVATE_KEY_PATH = _CONFIG / "wxo_private.pem"
_KEYS_PATH        = _CONFIG / "api_keys.json"


def _load_keys() -> dict:
    if _KEYS_PATH.exists():
        return json.loads(_KEYS_PATH.read_text(encoding="utf-8"))
    return {}


def _make_jwt(user_id: str = "") -> str:
    """Sign an RS256 JWT acceptable to the watsonx Orchestrate widget."""
    import jwt  # PyJWT

    private_key = _PRIVATE_KEY_PATH.read_bytes()
    keys        = _load_keys()

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub":        user_id or "anonymous",
        "iat":        now,
        "exp":        now + datetime.timedelta(hours=1),
        "jti":        str(uuid.uuid4()),
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


def _build_html(host_url: str, orchestration_id: str, crn: str,
                agent_id: str, agent_env_id: str, token_url: str) -> bytes:
    """Return the widget HTML as UTF-8 bytes."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ask AI</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{
      width: 100%; height: 100%; overflow: hidden;
      background: #1e1e2e; font-family: system-ui, sans-serif;
    }}
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    // Fetch a fresh signed JWT from our local Python server before the
    // widget initialises.  IBM requires this for every session.
    async function getToken() {{
      try {{
        const resp = await fetch('{token_url}');
        if (!resp.ok) throw new Error('token fetch failed: ' + resp.status);
        const data = await resp.json();
        return data.token;
      }} catch (e) {{
        console.error('wxo token error', e);
        return '';
      }}
    }}

    window.wxOConfiguration = {{
      orchestrationID:    "{orchestration_id}",
      hostURL:            "{host_url}",
      rootElementID:      "root",
      deploymentPlatform: "ibmcloud",
      crn:                "{crn}",
      chatOptions: {{
        agentId:            "{agent_id}",
        agentEnvironmentId: "{agent_env_id}",
      }},
      // Called by the widget whenever it needs a fresh user token
      onGetUserToken: getToken,
    }};

    setTimeout(function () {{
      const script = document.createElement('script');
      script.src = window.wxOConfiguration.hostURL + '/wxochat/wxoLoader.js?embed=true';
      script.addEventListener('load', function () {{ wxoLoader.init(); }});
      document.head.appendChild(script);
    }}, 0);
  </script>
</body>
</html>""".encode("utf-8")


# ── HTTP request handler ──────────────────────────────────────────

def _make_handler(html_bytes: bytes):
    class _Handler(http.server.BaseHTTPRequestHandler):

        def do_GET(self):
            if self.path.startswith("/token"):
                self._handle_token()
            else:
                self._handle_html()

        def _handle_html(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)

        def _handle_token(self):
            try:
                token = _make_jwt()
                body  = json.dumps({"token": token}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                # Allow the IBM widget (same origin) to read the response
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                msg = json.dumps({"error": str(exc)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        def log_message(self, *_):
            pass  # silence access logs

    return _Handler


# ── public API ────────────────────────────────────────────────────

def start(port: int = 0) -> tuple[http.server.HTTPServer, int]:
    """
    Start the server on the given port (0 = pick a free port).
    Returns (server, actual_port).  The server runs on a daemon thread.
    """
    keys        = _load_keys()
    host_url    = keys.get("wxo_host_url",            "")
    orch_id     = keys.get("wxo_orchestration_id",    "")
    crn         = keys.get("wxo_crn",                 "")
    agent_id    = keys.get("wxo_agent_id",            "")
    agent_env   = keys.get("wxo_agent_environment_id","")

    if port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    token_url  = f"http://127.0.0.1:{port}/token"
    html_bytes = _build_html(host_url, orch_id, crn, agent_id, agent_env, token_url)

    handler = _make_handler(html_bytes)
    server  = http.server.HTTPServer(("127.0.0.1", port), handler)

    t = threading.Thread(target=server.serve_forever, daemon=True, name="WxOJWT")
    t.start()
    return server, port


# ── CLI entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="watsonx Orchestrate JWT server")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if not _PRIVATE_KEY_PATH.exists():
        sys.exit(f"Private key not found: {_PRIVATE_KEY_PATH}\n"
                 "Run setup_wxo_keys.py first.")

    server, port = start(args.port)
    print(f"wxo_jwt_server running on http://127.0.0.1:{port}/")
    print(f"Token endpoint: http://127.0.0.1:{port}/token")
    print("Press Ctrl+C to stop.")
    try:
        server._BaseServer__is_shut_down.wait()
    except KeyboardInterrupt:
        server.shutdown()
