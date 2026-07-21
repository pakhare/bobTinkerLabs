"""
main.py – Entry point for AI Task Optimizer.

Responsibilities:
  1. Initialize logging and local DB
  2. Start activity monitor
  3. Start cloud sync loop
  4. Launch UI window with system-tray integration
"""
import logging
import sys
import threading
from pathlib import Path

# Ensure the client/ directory is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from app_utils import setup_logging, is_windows
setup_logging()

log = logging.getLogger(__name__)

from config import settings
from database import init_db, purge_old_records
from activity_monitor import ActivityMonitor
from cloud_client import CloudClient
from ui_dashboard import DashboardApp


def _build_tray_icon(app: DashboardApp, monitor: ActivityMonitor, cloud: CloudClient):
    """
    Create a system-tray icon (pystray).  Runs its own blocking loop in a
    background thread so the Tkinter mainloop is unaffected.
    """
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Draw a minimal 64×64 icon programmatically (no asset file required)
        img = Image.new("RGBA", (64, 64), (30, 30, 50, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill=(59, 130, 244, 255))
        draw.text((22, 20), "⚡", fill=(255, 255, 255, 255))

        def on_show(_icon, _item):
            app.after(0, app.deiconify)

        def on_quit(_icon, _item):
            _icon.stop()
            monitor.stop_monitoring()
            cloud.stop_sync_loop()
            app.after(0, app.destroy)

        menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", on_show, default=True),
            pystray.MenuItem("Quit", on_quit),
        )
        icon = pystray.Icon("ai_task_optimizer", img, "AI Task Optimizer", menu)
        threading.Thread(target=icon.run, daemon=True, name="SysTray").start()
    except ImportError:
        log.warning("pystray or Pillow not installed – system tray disabled.")


def main():
    if not is_windows():
        log.error("AI Task Optimizer requires Windows. Exiting.")
        sys.exit(1)

    log.info("Starting AI Task Optimizer …")

    # 1. Database
    init_db()
    purge_old_records()

    # 2. Activity monitoring
    monitor = ActivityMonitor()
    monitor.start_monitoring()

    # 3. Cloud sync
    cloud = CloudClient()
    cloud.start_sync_loop()
    # Immediately fetch any pending suggestions on startup
    threading.Thread(target=cloud.fetch_suggestions, daemon=True).start()

    # 4. UI
    app = DashboardApp()
    app.set_cloud_client(cloud)   # give the Ask-AI tab access to the agent

    # 5. System tray (requires pystray + Pillow)
    if settings.minimize_to_tray:
        _build_tray_icon(app, monitor, cloud)

    log.info("UI launched.")
    app.mainloop()

    # ── Teardown (reached after window.destroy()) ─────────────────
    log.info("Shutting down …")
    monitor.stop_monitoring()
    cloud.stop_sync_loop()
    log.info("Goodbye.")


if __name__ == "__main__":
    main()
