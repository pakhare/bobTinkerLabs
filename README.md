# AI Task Optimizer

> A Windows desktop assistant that silently watches what you do, detects repetitive patterns in real time, and suggests exactly how to automate them — powered by **IBM ICA Agentic Studio** and **IBM watsonx Orchestrate**.

---

## What it does

| Feature | Description |
|---|---|
| **Activity monitoring** | Tracks foreground window, keystroke counts, and click counts every 5 seconds. No content is ever captured — counts only. |
| **Pattern detection** | Seven rule-based detectors identify automation candidates (data entry, copy-paste loops, email sorting, report generation, and more). |
| **AI suggestions** | Detected patterns are sent to an ICA Agentic Studio A2A agent which enriches them into actionable automation suggestions with tool recommendations and time-saving estimates. |
| **Ask AI chat** | A full conversational chat tab backed by the same ICA A2A agent. The agent receives your live activity context and helps you plan and implement automations. |
| **System tray** | Runs quietly in the background; a tray icon gives quick access to the dashboard or quit. |

---

## Architecture

```
Windows Client
──────────────────────────────────────────────────────────────
ActivityMonitor  →  SQLite DB  →  DataProcessor  →  CloudClient
   (5 s poll)                      (patterns)       (30 min sync)
                                                         │
                                        ┌────────────────┘
                                        ▼
                              watsonx-backend (in-process)
                              ┌──────────────────────────┐
                              │  suggestion_engine.py     │
                              │  task_classifier.py       │  ← ICA A2A agent
                              │  activity_ingestion.py    │
                              │  feedback_handler.py      │
                              └──────────────────────────┘

DashboardApp (CustomTkinter)
  ├── Today tab        ← live metrics + top apps + detected patterns
  ├── Suggestions tab  ← AI-generated automation cards with ICA enrichment
  ├── History tab      ← 7-day productivity overview
  ├── Settings tab     ← monitoring + privacy controls
  └── Ask AI tab       ← conversational ICA agent with live activity context
```

### Data flow

| Step | What happens |
|---|---|
| 1 | `ActivityMonitor` polls the foreground window every 5 s, records keystroke/click counts |
| 2 | Records are stored in a local SQLite database (`data/local.db`) |
| 3 | `DataProcessor` groups records and runs 7 pattern detectors |
| 4 | Every 30 min `CloudClient` calls `suggestion_engine` in-process |
| 5 | `task_classifier` sends detected patterns to ICA via the A2A `message/send` protocol |
| 6 | The ICA agent returns enriched suggestions (tool, description, time saving) |
| 7 | Suggestions are persisted to SQLite and shown in the Suggestions tab |
| 8 | The Ask AI tab opens a stateful chat session; every message includes a live activity context snippet |
| 9 | User feedback (Helpful / Dismiss) is recorded locally and submitted to `feedback_handler` |

---

## IBM services used

| Service | Role |
|---|---|
| **ICA Agentic Studio** (A2A protocol) | Powers both the Suggestions enrichment (`task_classifier`) and the Ask AI conversational agent (`agent_runner`) |

---

## Project layout

```
ai-task-optimizer/
├── client/
│   ├── main.py                  ← Entry point
│   ├── activity_monitor.py      ← Windows foreground + input tracker
│   ├── data_processor.py        ← Pattern detection + metrics aggregation
│   ├── cloud_client.py          ← Sync loop, suggestion fetch, ICA chat
│   ├── ui_dashboard.py          ← CustomTkinter 5-tab dashboard
│   ├── database.py              ← SQLite schema + queries
│   ├── config.py                ← Settings & API key singleton
│   └── app_utils.py             ← Logging setup, OS helpers
│
├── watsonx-backend/
│   ├── functions/
│   │   ├── activity_ingestion.py   ← Processes + stores activity batches
│   │   ├── suggestion_engine.py    ← Fetches patterns, calls task_classifier
│   │   ├── feedback_handler.py     ← Records helpful/dismiss votes
│   │   └── ml_analysis.py         ← Statistical pattern analysis helpers
│   ├── models/
│   │   └── task_classifier.py     ← Sends patterns to ICA A2A, rule fallback
│   └── utils/
│       ├── ica_client.py          ← ICA Agentic Studio REST/A2A wrapper
│       ├── agent_runner.py        ← Stateful chat sessions on top of ICA
│       ├── db_helper.py           ← SQLite helpers for backend functions
│       └── validators.py          ← Input validation helpers
│
├── config/
│   ├── settings.json             ← Tunable parameters (poll interval, privacy, UI)
│   ├── api_keys.example.json     ← Committed template — copy to api_keys.json and fill in
│   └── api_keys.json             ← Real secrets — git-ignored, never committed
│
├── data/                         ← local.db + app.log (auto-created at runtime)
├── debug_ica.py                  ← Standalone ICA A2A connectivity probe
├── setup_wxo_security.py         ← One-time RSA key generator for watsonx Orchestrate
├── requirements.txt              ← Client dependencies
└── watsonx-backend/
    └── requirements.txt          ← Backend dependencies
```

---

## Quick start

### Prerequisites

- Windows 10 or 11 (64-bit)
- Python 3.11 or 3.12
- An IBM Cloud account with ICA Agentic Studio access

### 1 — Clone and install

```powershell
git clone https://github.com/your-org/ai-task-optimizer.git
cd ai-task-optimizer
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2 — Configure credentials

A safe template is already committed at [`config/api_keys.example.json`](config/api_keys.example.json).
Copy it to `api_keys.json` (which is git-ignored) and fill in your real values:

```powershell
copy config\api_keys.example.json config\api_keys.json
notepad config\api_keys.json
```

Fill in the three ICA fields:

```json
{
  "ica_api_url":  "https://servicesessentials.ibm.com/apis/v3/ica/agent-registry",
  "ica_api_key":  "YOUR_ICA_API_KEY",
  "ica_agent_id": "YOUR_ICA_AGENT_ID"
}
```

> ⚠️ **`api_keys.json` is listed in `.gitignore` and will never be committed.**
> Only `api_keys.example.json` (with placeholder values) is tracked by git.

Optionally adjust [`config/settings.json`](config/settings.json) to change poll intervals, privacy settings, or the UI theme.

### 3 — Verify ICA connectivity (optional)

```powershell
python debug_ica.py
```

This probes the ICA A2A endpoint with four payload shapes and prints which one succeeds. Expected output: `>>> SUCCESS <<<` on the first attempt.

### 4 — Launch

```powershell
cd client
python main.py
```

The app starts in the system tray and opens the dashboard window. All five tabs are immediately available.

---

## Detected patterns

| Pattern | Trigger |
|---|---|
| `manual_data_entry` | Spreadsheet app active + ≥ 60 keystrokes/min |
| `repetitive_copy_paste` | Multi-app switching + ≥ 20 keystrokes/min |
| `email_sorting` | Email client active + ≥ 10 clicks/min |
| `document_formatting` | Word / PowerPoint + mixed keyboard + mouse activity |
| `file_organization` | File Explorer + ≥ 5 clicks/min |
| `browser_research` | Browser + ≥ 12 clicks/min across multiple sessions |
| `report_generation` | Spreadsheet + document + email in same session |

---

## Privacy

- **Keystroke content is never captured** — only counts per time window.
- **Screenshots are never taken.**
- Window titles are anonymised: email addresses and long number strings are automatically redacted.
- Any application can be excluded via `settings.json → monitoring.excluded_apps`.
- All data is keyed to a SHA-256 hash of `COMPUTERNAME:USERNAME` — no real identity is stored or transmitted.

---

## Configuration reference

### `config/settings.json`

| Key | Default | Description |
|---|---|---|
| `monitoring.poll_interval_seconds` | `5` | How often the foreground window is sampled |
| `monitoring.sync_interval_minutes` | `30` | How often the backend sync loop runs |
| `monitoring.idle_threshold_seconds` | `60` | Inactivity threshold before a session is considered idle |
| `monitoring.excluded_apps` | `["LockApp.exe", …]` | Apps never tracked |
| `privacy.anonymize_window_titles` | `true` | Redact sensitive strings from window titles |
| `ui.theme` | `"dark"` | `"dark"` or `"light"` |
| `ui.minimize_to_tray` | `true` | Minimise to system tray instead of taskbar |
| `database.max_local_days` | `30` | Days of activity kept in local SQLite |

---

## Building a standalone executable (optional)

```powershell
pip install pyinstaller
cd client
pyinstaller --onefile --windowed --name "AI Task Optimizer" main.py
# Output: dist/AI Task Optimizer.exe
```

---

## Uploading to GitHub

### 1 — Create the repository

1. Go to [github.com](https://github.com) → **New repository**
2. Name it `ai-task-optimizer`, set visibility to **Private**
3. Do **not** tick "Add README", "Add .gitignore", or "Choose a licence" — the repo already has all of these
4. Click **Create repository** and copy the URL shown (e.g. `https://github.com/YOUR_USERNAME/ai-task-optimizer.git`)

### 2 — Initialise git and push

Run these commands from the `ai-task-optimizer` folder:

```powershell
cd "C:\Users\PrasadKhare\Documents\WatsonX 2026\ai-task-optimizer"

git init
git add .

# Verify api_keys.json is NOT listed (it must be absent)
git status

git commit -m "Initial commit: AI Task Optimizer"
git remote add origin https://github.com/YOUR_USERNAME/ai-task-optimizer.git
git branch -M main
git push -u origin main
```

When prompted for a password, use a **Personal Access Token** (not your GitHub account password):
GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token → tick **repo** → copy and paste.

### 3 — Confirm secrets are not in the repo

After pushing, open the repo on GitHub and verify:

| File | Should it appear? |
|---|---|
| `config/api_keys.json` | ❌ No — gitignored |
| `config/wxo_private.pem` | ❌ No — gitignored |
| `config/api_keys.example.json` | ✅ Yes — placeholder only |
| `.gitignore` | ✅ Yes |
| `README.md` | ✅ Yes |

If `api_keys.json` appears by mistake, remove it immediately:

```powershell
git rm --cached config/api_keys.json
git commit -m "Remove accidentally committed secrets"
git push
```

---

## License

MIT
