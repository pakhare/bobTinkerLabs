"""
wxo_chat_launcher.py – pywebview child-process launcher for the Ask AI tab.

Must be run as a subprocess (pywebview requires the main thread).

Arguments
---------
  --url          http://127.0.0.1:<port>/   (localhost server in parent process)
  --parent-hwnd  Win32 HWND of the CTkFrame to embed into
  --width        initial pixel width
  --height       initial pixel height

The window is created frameless/borderless, then Win32 SetParent + SetWindowPos
rearrange it so it fills the parent CTkFrame like a true embedded control.
A background thread polls a temp file written by the parent whenever the frame
is resized, and calls window.resize() accordingly.
"""
import argparse
import json
import os
import pathlib
import tempfile
import threading
import time

import webview


# ── argument parsing ──────────────────────────────────────────────

def _parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",          required=True)
    ap.add_argument("--parent-hwnd",  type=int, default=0)
    ap.add_argument("--width",        type=int, default=480)
    ap.add_argument("--height",       type=int, default=640)
    return ap.parse_args()


# ── Win32 helpers ─────────────────────────────────────────────────

def _embed_into_parent(child_hwnd: int, parent_hwnd: int,
                       width: int, height: int) -> None:
    """Reparent the pywebview native window into the Tkinter frame."""
    try:
        import ctypes
        GWL_STYLE     = -16
        WS_CHILD      = 0x40000000
        WS_VISIBLE    = 0x10000000
        WS_POPUP      = 0x80000000
        SWP_SHOWWINDOW = 0x0040

        user32 = ctypes.windll.user32

        # Strip popup/caption styles, add WS_CHILD so it behaves as a child
        style = user32.GetWindowLongW(child_hwnd, GWL_STYLE)
        style = (style & ~WS_POPUP) | WS_CHILD | WS_VISIBLE
        user32.SetWindowLongW(child_hwnd, GWL_STYLE, style)

        # Reparent
        user32.SetParent(child_hwnd, parent_hwnd)

        # Fill the parent frame exactly
        user32.SetWindowPos(
            child_hwnd, 0,
            0, 0, width, height,
            SWP_SHOWWINDOW,
        )
    except Exception as exc:
        print(f"[wxo_launcher] embed failed: {exc}")


# ── resize poller ─────────────────────────────────────────────────

def _poll_resize(window: webview.Window,
                 child_hwnd_ref: list,
                 parent_hwnd: int) -> None:
    """
    Poll the shared size file written by ui_dashboard._on_wxo_frame_resize()
    and resize + reposition the webview to match.
    """
    size_file = pathlib.Path(tempfile.gettempdir()) / "wxo_size.json"
    last_mtime = 0.0

    try:
        import ctypes
        user32 = ctypes.windll.user32
    except Exception:
        return  # non-Windows, skip

    while True:
        time.sleep(0.25)
        try:
            mtime = size_file.stat().st_mtime
            if mtime <= last_mtime:
                continue
            last_mtime = mtime
            data = json.loads(size_file.read_text())
            w, h = int(data["w"]), int(data["h"])
            if w < 10 or h < 10:
                continue
            hwnd = child_hwnd_ref[0]
            if hwnd:
                user32.SetWindowPos(hwnd, 0, 0, 0, w, h, 0x0040)
        except Exception:
            pass


# ── main ──────────────────────────────────────────────────────────

def main():
    args = _parse()

    window = webview.create_window(
        "Ask AI – watsonx Orchestrate",
        args.url,
        width=args.width,
        height=args.height,
        resizable=True,
        frameless=True,          # no title bar – it will live inside the CTk frame
        easy_drag=False,
    )

    child_hwnd_ref = [0]  # mutable container so the thread can read it

    def _on_shown():
        """Called by pywebview on the GUI thread once the native window exists."""
        import ctypes
        # Find the child HWND: pywebview doesn't expose it directly,
        # so we enumerate top-level windows to find ours by title.
        title_target = "Ask AI – watsonx Orchestrate"
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def _enum_cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title_target:
                found.append(hwnd)
            return True

        ctypes.windll.user32.EnumWindows(_enum_cb, 0)

        if found and args.parent_hwnd:
            child_hwnd = found[0]
            child_hwnd_ref[0] = child_hwnd
            _embed_into_parent(child_hwnd, args.parent_hwnd,
                               args.width, args.height)
            # Start resize polling thread
            t = threading.Thread(
                target=_poll_resize,
                args=(window, child_hwnd_ref, args.parent_hwnd),
                daemon=True,
            )
            t.start()

    window.events.shown += _on_shown
    webview.start()


if __name__ == "__main__":
    main()
