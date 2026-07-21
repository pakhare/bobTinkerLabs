"""
activity_monitor.py – Windows activity tracking (windows, keyboard count, mouse count).

Privacy guarantees:
  • Actual keystroke content is NEVER recorded – only event counts.
  • Window titles are optionally anonymized via config.
  • Screenshots are never taken.
"""
import hashlib
import logging
import re
import threading
import time
from datetime import datetime
from typing import Optional

import psutil
import win32gui
import win32process
from pynput import keyboard as _kb, mouse as _mouse

from config import settings
from database import insert_activity

log = logging.getLogger(__name__)

# ── Application category map ──────────────────────────────────────

APP_CATEGORIES: dict[str, str] = {
    "EXCEL.EXE": "spreadsheet",
    "WINWORD.EXE": "document",
    "POWERPNT.EXE": "presentation",
    "OUTLOOK.EXE": "email",
    "THUNDERBIRD.EXE": "email",
    "CHROME.EXE": "browser",
    "MSEDGE.EXE": "browser",
    "FIREFOX.EXE": "browser",
    "CODE.EXE": "coding",
    "PYCHARM64.EXE": "coding",
    "DEVENV.EXE": "coding",
    "NOTEPAD.EXE": "text_editor",
    "NOTEPAD++.EXE": "text_editor",
    "EXPLORER.EXE": "file_management",
    "POWERSHELL.EXE": "terminal",
    "CMD.EXE": "terminal",
    "SLACK.EXE": "communication",
    "TEAMS.EXE": "communication",
    "ZOOM.EXE": "communication",
    "ACROBAT.EXE": "pdf",
    "ACRORD32.EXE": "pdf",
}

# Patterns that typically contain PII in window titles
_PII_PATTERNS = [
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),  # email
    re.compile(r"\b\d{10,}\b"),  # phone / account numbers
]


class ActivityMonitor:
    """Background monitor – runs in its own thread; writes records to local DB."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Current window state
        self._current_hwnd: Optional[int] = None
        self._current_app: str = ""
        self._current_title: str = ""
        self._window_start: float = time.monotonic()

        # Counters reset each polling cycle
        self._keyboard_count: int = 0
        self._mouse_count: int = 0
        self._idle_time: int = 0

        # pynput listeners (started lazily)
        self._kb_listener: Optional[_kb.Listener] = None
        self._mouse_listener: Optional[_mouse.Listener] = None

    # ── Public API ────────────────────────────────────────────────

    def start_monitoring(self) -> None:
        self._stop_event.clear()
        self._start_input_listeners()
        t = threading.Thread(target=self._poll_loop, daemon=True, name="ActivityMonitor")
        t.start()
        log.info("Activity monitoring started (poll every %ss)", settings.poll_interval)

    def stop_monitoring(self) -> None:
        self._stop_event.set()
        if self._kb_listener:
            self._kb_listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()
        log.info("Activity monitoring stopped.")

    # ── Window helpers ────────────────────────────────────────────

    def get_active_window(self) -> dict:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            app_name = proc.name().upper()
        except Exception:
            app_name = "UNKNOWN.EXE"
            pid = 0

        if settings.privacy.get("anonymize_window_titles", True):
            title = self._anonymize_title(title)

        return {
            "hwnd": hwnd,
            "window_title": title,
            "app_name": app_name,
            "process_id": pid,
            "category": self.categorize_application(app_name),
        }

    def categorize_application(self, app_name: str) -> str:
        return APP_CATEGORIES.get(app_name.upper(), "other")

    # ── Internal helpers ──────────────────────────────────────────

    def _anonymize_title(self, title: str) -> str:
        for pattern in _PII_PATTERNS:
            title = pattern.sub("[REDACTED]", title)
        return title

    def _start_input_listeners(self) -> None:
        def on_press(_key):
            with self._lock:
                self._keyboard_count += 1

        def on_click(_x, _y, _button, _pressed):
            if _pressed:
                with self._lock:
                    self._mouse_count += 1

        self._kb_listener = _kb.Listener(on_press=on_press)
        self._mouse_listener = _mouse.Listener(on_click=on_click)
        self._kb_listener.start()
        self._mouse_listener.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(settings.poll_interval)
            self._tick()

    def _tick(self) -> None:
        try:
            window = self.get_active_window()
        except Exception as exc:
            log.debug("get_active_window failed: %s", exc)
            return

        app_name = window["app_name"]
        if app_name in settings.excluded_apps:
            return

        hwnd = window["hwnd"]
        now = time.monotonic()

        with self._lock:
            kb = self._keyboard_count
            mc = self._mouse_count
            self._keyboard_count = 0
            self._mouse_count = 0

        # Detect idle: no keyboard/mouse in this interval
        idle = settings.poll_interval if (kb == 0 and mc == 0) else 0

        # If the foreground window changed, flush the previous record
        if hwnd != self._current_hwnd and self._current_hwnd is not None:
            duration = int(now - self._window_start)
            self._flush_record(duration, kb=0, mc=0, idle=idle)

        # Update current state
        self._current_hwnd = hwnd
        self._current_app = app_name
        self._current_title = window["window_title"]
        self._window_start = now

        # Write an interval record (one every poll_interval seconds)
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "app_name": app_name,
            "window_title": window["window_title"],
            "process_id": window["process_id"],
            "duration_seconds": settings.poll_interval,
            "keyboard_events": kb,
            "mouse_clicks": mc,
            "category": window["category"],
            "idle_time": idle,
        }
        try:
            insert_activity(record)
        except Exception as exc:
            log.error("Failed to save activity record: %s", exc)

    def _flush_record(self, duration: int, kb: int, mc: int, idle: int) -> None:
        if not self._current_app:
            return
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "app_name": self._current_app,
            "window_title": self._current_title,
            "process_id": 0,
            "duration_seconds": duration,
            "keyboard_events": kb,
            "mouse_clicks": mc,
            "category": self.categorize_application(self._current_app),
            "idle_time": idle,
        }
        try:
            insert_activity(record)
        except Exception as exc:
            log.error("Failed to flush record: %s", exc)
