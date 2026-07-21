"""
ui_dashboard.py – CustomTkinter main window for AI Task Optimizer.

Tabs:
  Today     – live activity summary + top apps chart
  Suggestions – AI-generated automation suggestions
  History   – 7-day productivity chart
  Settings  – monitoring and privacy controls
  Ask AI    – ICA Agentic Studio chat (watsonx Orchestrate trial limitation)
"""
import logging
import threading
from datetime import date, datetime, timedelta
from typing import List

import customtkinter as ctk
from tkinter import messagebox
import sqlite3

from config import settings
from database import (
    get_active_suggestions,
    dismiss_suggestion,
    rate_suggestion,
    get_unuploaded_activities,
)
from data_processor import DataProcessor

log = logging.getLogger(__name__)
ctk.set_appearance_mode(settings.theme)
ctk.set_default_color_theme("blue")

_processor = DataProcessor()

# ── Colour constants (matches system palette) ─────────────────────
C_BG = "#1e1e2e"
C_SURFACE = "#2a2a3c"
C_ACCENT = "#3b82f4"
C_TEXT = "#e0e0e0"
C_MUTED = "#7a7a9a"
C_GREEN = "#22c55e"
C_ORANGE = "#f97316"
C_RED = "#ef4444"


class DashboardApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("AI Task Optimizer")
        self.geometry("900x640")
        self.minsize(800, 560)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Shared state updated by background refresh
        self._activities: List[dict] = []
        self._suggestions: List[dict] = []

        # Ask-AI chat state
        self._chat_session_id    = None
        self._chat_cloud_client  = None   # injected by main.py via set_cloud_client()

        self._build_ui()
        self._start_refresh_loop()

    def set_cloud_client(self, cloud_client) -> None:
        """Inject the CloudClient instance (sync, suggestions, and Ask AI chat)."""
        self._chat_cloud_client = cloud_client

    # ── UI construction ───────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        header = ctk.CTkFrame(self, height=56, corner_radius=0)
        header.pack(fill="x", side="top")
        ctk.CTkLabel(
            header,
            text="⚡ AI Task Optimizer",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left", padx=20, pady=12)
        ctk.CTkLabel(
            header,
            text="Powered by IBM watsonx",
            font=ctk.CTkFont(size=12),
            text_color=C_MUTED,
        ).pack(side="right", padx=20, pady=12)

        # Tab view
        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="both", expand=True, padx=12, pady=8)

        for tab_name in ("Today", "Suggestions", "History", "Settings", "Ask AI"):
            self._tabs.add(tab_name)

        self._build_today_tab()
        self._build_suggestions_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self._build_ask_ai_tab()

    # ── Today tab ─────────────────────────────────────────────────

    def _build_today_tab(self):
        tab = self._tabs.tab("Today")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # ── Metric cards row ──
        cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        cards_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        cards_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._card_active = self._metric_card(cards_frame, "Active Time", "–", 0)
        self._card_idle = self._metric_card(cards_frame, "Idle Time", "–", 1)
        self._card_apps = self._metric_card(cards_frame, "Apps Used", "–", 2)
        self._card_score = self._metric_card(cards_frame, "Productivity", "–", 3)

        # ── Top apps list ──
        apps_frame = ctk.CTkFrame(tab)
        apps_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(
            apps_frame,
            text="Top Applications",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self._apps_list_frame = ctk.CTkScrollableFrame(apps_frame)
        self._apps_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ── Patterns detected ──
        patterns_frame = ctk.CTkFrame(tab)
        patterns_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(
            patterns_frame,
            text="Detected Patterns",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self._patterns_list_frame = ctk.CTkScrollableFrame(patterns_frame)
        self._patterns_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _metric_card(self, parent, label: str, value: str, col: int) -> ctk.CTkLabel:
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.grid(row=0, column=col, padx=6, pady=4, sticky="ew")
        ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=11), text_color=C_MUTED).pack(
            pady=(10, 2)
        )
        lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold"))
        lbl.pack(pady=(0, 10))
        return lbl

    # ── Suggestions tab ───────────────────────────────────────────

    def _build_suggestions_tab(self):
        tab = self._tabs.tab("Suggestions")

        header_row = ctk.CTkFrame(tab, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            header_row,
            text="AI Automation Suggestions",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header_row,
            text="↻ Refresh",
            width=90,
            command=self._refresh_suggestions,
        ).pack(side="right")
        ctk.CTkButton(
            header_row,
            text="🧪 Test ICA",
            width=100,
            fg_color="#7c5cd8",
            hover_color="#6d4fc7",
            command=self._test_ica_pipeline,
        ).pack(side="right", padx=(0, 6))

        self._suggestions_scroll = ctk.CTkScrollableFrame(tab)
        self._suggestions_scroll.pack(fill="both", expand=True)

    def _render_suggestions(self, suggestions: List[dict]):
        for widget in self._suggestions_scroll.winfo_children():
            widget.destroy()

        if not suggestions:
            ctk.CTkLabel(
                self._suggestions_scroll,
                text="No suggestions yet. Keep working – patterns are being analyzed!",
                text_color=C_MUTED,
            ).pack(pady=40)
            return

        for s in suggestions:
            self._suggestion_card(self._suggestions_scroll, s)

    def _suggestion_card(self, parent, s: dict):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(fill="x", padx=4, pady=6)

        # Title row
        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            title_row,
            text=s.get("title", "Suggestion"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")
        save_label = f"⏱ saves ~{s.get('time_saving_minutes', '?')} min/day"
        ctk.CTkLabel(
            title_row,
            text=save_label,
            font=ctk.CTkFont(size=11),
            text_color=C_GREEN,
        ).pack(side="right")

        # Description
        ctk.CTkLabel(
            card,
            text=s.get("description", ""),
            font=ctk.CTkFont(size=12),
            text_color=C_MUTED,
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=12, pady=4)

        # Tool badge + actions
        action_row = ctk.CTkFrame(card, fg_color="transparent")
        action_row.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(
            action_row,
            text=f"🛠 {s.get('tool_name', '')}",
            font=ctk.CTkFont(size=11),
            text_color=C_ACCENT,
        ).pack(side="left")

        sid = s.get("id")
        ctk.CTkButton(
            action_row,
            text="✓ Helpful",
            width=80,
            fg_color=C_GREEN,
            hover_color="#16a34a",
            command=lambda _id=sid: self._on_helpful(_id),
        ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(
            action_row,
            text="✗ Dismiss",
            width=80,
            fg_color=C_RED,
            hover_color="#dc2626",
            command=lambda _id=sid: self._on_dismiss(_id),
        ).pack(side="right", padx=(4, 0))

    # ── History tab ───────────────────────────────────────────────

    def _build_history_tab(self):
        tab = self._tabs.tab("History")
        ctk.CTkLabel(
            tab,
            text="7-Day Productivity Overview",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self._history_frame = ctk.CTkScrollableFrame(tab)
        self._history_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self._render_history_placeholder()

    def _render_history_placeholder(self):
        for widget in self._history_frame.winfo_children():
            widget.destroy()
        ctk.CTkLabel(
            self._history_frame,
            text="History data will appear after the first full day of tracking.",
            text_color=C_MUTED,
        ).pack(pady=40)

    # ── Settings tab ──────────────────────────────────────────────

    def _build_settings_tab(self):
        tab = self._tabs.tab("Settings")
        tab.grid_columnconfigure(0, weight=1)

        # Monitoring section
        self._settings_section(tab, "Monitoring", row=0)
        self._poll_var = ctk.StringVar(value=str(settings.poll_interval))
        self._labeled_entry(tab, "Poll interval (seconds)", self._poll_var, row=1)

        self._sync_var = ctk.StringVar(value=str(settings.sync_interval // 60))
        self._labeled_entry(tab, "Cloud sync interval (minutes)", self._sync_var, row=2)

        # Privacy section
        self._settings_section(tab, "Privacy", row=3)
        self._anon_var = ctk.BooleanVar(value=settings.privacy.get("anonymize_window_titles", True))
        ctk.CTkCheckBox(tab, text="Anonymize window titles", variable=self._anon_var).grid(
            row=4, column=0, sticky="w", padx=24, pady=4
        )

        # Notifications
        self._settings_section(tab, "Notifications", row=5)
        self._notif_var = ctk.BooleanVar(value=settings.show_notifications)
        ctk.CTkCheckBox(tab, text="Show desktop notifications", variable=self._notif_var).grid(
            row=6, column=0, sticky="w", padx=24, pady=4
        )

        ctk.CTkButton(
            tab,
            text="Save Settings",
            command=self._save_settings,
        ).grid(row=7, column=0, padx=24, pady=20, sticky="w")

    def _settings_section(self, parent, title: str, row: int):
        ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=16, pady=(16, 4))

    def _labeled_entry(self, parent, label: str, var: ctk.StringVar, row: int):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=24, pady=3)
        ctk.CTkLabel(frame, text=label, width=260, anchor="w").pack(side="left")
        ctk.CTkEntry(frame, textvariable=var, width=80).pack(side="left")

    def _save_settings(self):
        import json
        from pathlib import Path

        new_settings = settings._settings.copy()
        try:
            new_settings["monitoring"]["poll_interval_seconds"] = int(self._poll_var.get())
            new_settings["monitoring"]["sync_interval_minutes"] = int(self._sync_var.get())
            new_settings["privacy"]["anonymize_window_titles"] = self._anon_var.get()
            new_settings["ui"]["show_notifications"] = self._notif_var.get()
        except ValueError:
            messagebox.showerror("Validation", "Interval values must be integers.")
            return

        path = Path(__file__).parent.parent / "config" / "settings.json"
        with open(path, "w") as fh:
            json.dump(new_settings, fh, indent=2)
        settings.reload()
        messagebox.showinfo("Settings", "Settings saved. Some changes take effect on next launch.")

    # ── Test helper ───────────────────────────────────────────────

    def _test_ica_pipeline(self):
        """Inject synthetic patterns and call the full ICA pipeline in a thread."""
        import threading
        self._render_suggestions([])  # clear panel and show spinner text

        # Show "working…" label immediately
        for w in self._suggestions_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._suggestions_scroll,
            text="⏳ Calling ICA Agentic Studio…",
            font=ctk.CTkFont(size=13),
            text_color=C_MUTED,
        ).pack(pady=40)

        def _run():
            import sys
            from pathlib import Path
            _BACKEND_ROOT = Path(__file__).parent.parent / "watsonx-backend"
            for _subdir in (_BACKEND_ROOT, _BACKEND_ROOT / "functions",
                            _BACKEND_ROOT / "models", _BACKEND_ROOT / "utils"):
                _ps = str(_subdir)
                if _ps not in sys.path:
                    sys.path.insert(0, _ps)

            # Synthetic patterns covering the most common automation scenarios
            fake_patterns = [
                {"pattern_name": "manual_data_entry",    "confidence": 0.91, "description": "High-volume typing in spreadsheet", "context": "EXCEL.EXE(42)"},
                {"pattern_name": "repetitive_copy_paste","confidence": 0.87, "description": "Switching apps with clipboard activity", "context": "EXCEL.EXE(20), CHROME.EXE(18)"},
                {"pattern_name": "email_sorting",        "confidence": 0.83, "description": "Repetitive clicks in email client", "context": "OUTLOOK.EXE(35)"},
                {"pattern_name": "report_generation",    "confidence": 0.79, "description": "Spreadsheet + doc + email session", "context": "EXCEL.EXE(15), WINWORD.EXE(12)"},
                {"pattern_name": "file_organization",    "confidence": 0.74, "description": "Repeated file explorer operations", "context": "EXPLORER.EXE(28)"},
            ]

            try:
                from task_classifier import analyze_patterns
                opportunities = analyze_patterns(fake_patterns)

                suggestions = [
                    {
                        "received_at":         __import__("datetime").datetime.utcnow().isoformat(),
                        "title":               opp.get("opportunity_title", "Automation Opportunity"),
                        "description":         opp.get("opportunity_description", ""),
                        "tool_name":           opp.get("recommended_tool", ""),
                        "tutorial_url":        opp.get("tutorial_link", ""),
                        "time_saving_minutes": opp.get("estimated_time_saving_minutes", 0),
                        "id":                  None,
                    }
                    for opp in opportunities
                ]
                self.after(0, lambda s=suggestions: self._render_suggestions(s))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error("Test ICA pipeline failed: %s", exc, exc_info=True)
                self.after(0, lambda: self._render_suggestions([]))

        threading.Thread(target=_run, daemon=True, name="TestICA").start()

    # ── Ask AI tab ────────────────────────────────────────────────

    def _build_ask_ai_tab(self):
        tab = self._tabs.tab("Ask AI")
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        # ── Header ──
        hdr = ctk.CTkFrame(tab, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(
            hdr,
            text="Ask AI Optimizer",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            hdr,
            text="＋ New Chat",
            width=100,
            fg_color=C_ACCENT,
            hover_color="#2563eb",
            command=self._new_chat,
        ).pack(side="right")
        ctk.CTkLabel(
            hdr,
            text="Powered by ICA Agentic Studio",
            font=ctk.CTkFont(size=11),
            text_color=C_MUTED,
        ).pack(side="right", padx=10)

        # ── Trial notice banner ──
        notice = ctk.CTkFrame(tab, fg_color="#2a1f3d", corner_radius=8)
        notice.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 4))
        ctk.CTkLabel(
            notice,
            text=(
                "ℹ  watsonx Orchestrate web chat requires a paid plan to enable "
                "the security configuration API.  For this hackathon submission the "
                "chat is powered by the ICA Agentic Studio A2A agent instead — the "
                "same engine that drives the Suggestions tab."
            ),
            font=ctk.CTkFont(size=11),
            text_color="#a78bfa",
            wraplength=760,
            justify="left",
        ).pack(padx=12, pady=8, anchor="w")

        # ── Scrollable chat history ──
        self._chat_scroll = ctk.CTkScrollableFrame(tab, fg_color=C_BG)
        self._chat_scroll.grid(row=2, column=0, sticky="nsew")
        self._chat_scroll.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # ── Welcome message ──
        self._append_chat_bubble(
            "👋 Hi! I'm Optimizer, your AI productivity coach.\n"
            "I can see your activity patterns from today and help you automate repetitive work.\n\n"
            "Try asking:\n"
            "• What's my biggest automation opportunity today?\n"
            "• Write a Python script to automate my Excel data entry\n"
            "• How do I set up Power Automate for email sorting?",
            role="assistant",
        )

        # ── Input area ──
        input_frame = ctk.CTkFrame(tab, fg_color="transparent")
        input_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        input_frame.grid_columnconfigure(0, weight=1)

        self._chat_input = ctk.CTkTextbox(
            input_frame,
            height=60,
            corner_radius=8,
            font=ctk.CTkFont(size=13),
            wrap="word",
        )
        self._chat_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._chat_input.bind("<Return>", self._on_chat_enter)
        self._chat_input.bind("<Shift-Return>", lambda e: None)

        self._chat_send_btn = ctk.CTkButton(
            input_frame,
            text="Send",
            width=90,
            command=self._send_chat_message,
            fg_color=C_ACCENT,
            hover_color="#2563eb",
        )
        self._chat_send_btn.grid(row=0, column=1, sticky="ns")

    def _append_chat_bubble(self, text: str, role: str) -> None:
        is_user      = role == "user"
        bubble_color = "#3b4a6b" if is_user else C_SURFACE
        anchor       = "e" if is_user else "w"
        padx_sides   = (60, 8) if is_user else (8, 60)

        outer = ctk.CTkFrame(self._chat_scroll, fg_color="transparent")
        outer.pack(fill="x", pady=3, padx=4)
        bubble = ctk.CTkFrame(outer, fg_color=bubble_color, corner_radius=12)
        bubble.pack(anchor=anchor, padx=padx_sides)
        ctk.CTkLabel(
            bubble,
            text=text,
            font=ctk.CTkFont(size=12),
            text_color=C_TEXT,
            wraplength=480,
            justify="left",
            anchor="w",
        ).pack(padx=12, pady=8)

    def _on_chat_enter(self, event):
        self._send_chat_message()
        return "break"

    def _send_chat_message(self) -> None:
        msg = self._chat_input.get("1.0", "end").strip()
        if not msg:
            return
        self._chat_input.delete("1.0", "end")
        self._append_chat_bubble(msg, role="user")

        # Typing indicator
        typing_outer = ctk.CTkFrame(self._chat_scroll, fg_color="transparent")
        typing_outer.pack(fill="x", pady=3, padx=4)
        ctk.CTkLabel(
            typing_outer,
            text="⏳ Optimizer is thinking…",
            font=ctk.CTkFont(size=12, slant="italic"),
            text_color=C_MUTED,
        ).pack(anchor="w", padx=12)
        self._chat_send_btn.configure(state="disabled")

        def _run():
            if self._chat_cloud_client is None:
                reply = "⚠ AI agent not ready yet — please wait a moment and try again."
            else:
                reply, new_sid = self._chat_cloud_client.chat(msg, self._chat_session_id)
                self._chat_session_id = new_sid
            self.after(0, lambda: self._on_chat_reply(reply, typing_outer))

        threading.Thread(target=_run, daemon=True, name="ChatAgent").start()

    def _on_chat_reply(self, reply: str, typing_outer) -> None:
        try:
            typing_outer.destroy()
        except Exception:
            pass
        self._append_chat_bubble(reply, role="assistant")
        self._chat_send_btn.configure(state="normal")
        self._chat_scroll._parent_canvas.yview_moveto(1.0)

    def _new_chat(self) -> None:
        self._chat_session_id = None
        for w in self._chat_scroll.winfo_children():
            w.destroy()
        self._append_chat_bubble(
            "New conversation started. How can I help you today?",
            role="assistant",
        )

    # ── Event handlers ────────────────────────────────────────────

    def _on_helpful(self, suggestion_id: int):
        if suggestion_id is not None:
            rate_suggestion(suggestion_id, helpful=True)
        self._refresh_suggestions()

    def _on_dismiss(self, suggestion_id: int):
        if suggestion_id is not None:
            dismiss_suggestion(suggestion_id)
        self._refresh_suggestions()

    def _on_close(self):
        if settings.minimize_to_tray:
            self.withdraw()
        else:
            self.destroy()

    # ── Data refresh ──────────────────────────────────────────────

    def _start_refresh_loop(self):
        self._refresh_today()
        self._refresh_suggestions()
        self.after(60_000, self._start_refresh_loop)  # every 60 s

    def _refresh_today(self):
        def _load():
            try:
                records = get_unuploaded_activities()
                metrics = _processor.calculate_metrics(records)
                patterns = _processor.detect_patterns(records)
                self.after(0, lambda: self._update_today_ui(metrics, records, patterns))
            except Exception as exc:
                log.error("Today refresh failed: %s", exc)

        threading.Thread(target=_load, daemon=True).start()

    def _update_today_ui(self, metrics: dict, records: List[dict], patterns: List[dict]):
        self._card_active.configure(
            text=f"{metrics.get('active_minutes', 0):.0f}m"
        )
        self._card_idle.configure(
            text=f"{metrics.get('idle_minutes', 0):.0f}m"
        )
        apps = set(r.get("app_name", "") for r in records)
        self._card_apps.configure(text=str(len(apps)))
        score = metrics.get("productivity_score", 0)
        self._card_score.configure(text=f"{score * 100:.0f}%")

        # App breakdown
        from collections import Counter
        app_durations: Counter = Counter()
        for r in records:
            app_durations[r.get("app_name", "?")] += r.get("duration_seconds", 0)

        for widget in self._apps_list_frame.winfo_children():
            widget.destroy()

        for app, dur in app_durations.most_common(8):
            minutes = dur // 60
            row = ctk.CTkFrame(self._apps_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=app, font=ctk.CTkFont(size=12), width=200, anchor="w").pack(
                side="left"
            )
            ctk.CTkLabel(
                row,
                text=f"{minutes}m",
                font=ctk.CTkFont(size=12),
                text_color=C_MUTED,
            ).pack(side="right")

        # Patterns
        for widget in self._patterns_list_frame.winfo_children():
            widget.destroy()

        if not patterns:
            ctk.CTkLabel(
                self._patterns_list_frame,
                text="No patterns detected yet.",
                text_color=C_MUTED,
            ).pack(pady=20)
        else:
            for p in patterns:
                pcard = ctk.CTkFrame(self._patterns_list_frame, corner_radius=8)
                pcard.pack(fill="x", pady=4)
                ctk.CTkLabel(
                    pcard,
                    text=p["pattern_name"].replace("_", " ").title(),
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).pack(anchor="w", padx=10, pady=(8, 2))
                ctk.CTkLabel(
                    pcard,
                    text=f"{p['description']}  ({int(p['confidence']*100)}% confidence)",
                    font=ctk.CTkFont(size=11),
                    text_color=C_MUTED,
                    wraplength=380,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 8))

    def _refresh_suggestions(self):
        def _load():
            try:
                s = get_active_suggestions()
                self.after(0, lambda: self._render_suggestions(s))
            except Exception as exc:
                log.error("Suggestions refresh failed: %s", exc)

        threading.Thread(target=_load, daemon=True).start()
