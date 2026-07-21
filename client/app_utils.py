"""
utils.py – Shared utility helpers.
"""
import hashlib
import logging
import os
import platform
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a consistent format."""
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                Path(__file__).parent.parent / "data" / "app.log",
                encoding="utf-8",
            ),
        ],
    )


def is_windows() -> bool:
    return platform.system() == "Windows"


def resource_path(relative: str) -> Path:
    """Return absolute path – works both in dev and in PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent.parent
    return base / relative
