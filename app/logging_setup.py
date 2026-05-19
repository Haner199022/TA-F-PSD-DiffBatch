"""Centralized logging configuration for TA-F PSD DiffBatch.

Production builds run with ``console=False`` (PyInstaller windowed mode), so
``print(..., file=sys.stderr)`` is a black hole. This module wires a rotating
file handler to a stable per-user location so we can actually diagnose issues
on colleagues' machines.

Call :func:`setup_logging` once from ``launcher.main()`` before any other code
runs. Subsequent modules just do ``log = logging.getLogger(__name__)``.

Log location:
    Windows:  ``%LocalAppData%\\TA-F\\PS-BATCH\\logs\\app.log``
    Other:    ``~/.tafpsd/logs/app.log``  (Mac dev mode only)

If the preferred directory can't be created (rare, locked-down corp profile),
we fall back to the system temp dir rather than crash the launcher.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _default_log_dir() -> Path:
    """Return the per-user log directory for the current platform."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "TA-F" / "PS-BATCH" / "logs"
    return Path.home() / ".tafpsd" / "logs"


# Module-level state. Read by other modules (diagnostics, errors). Mutated
# only by setup_logging() — never assign these from outside.
LOG_DIR: Path = _default_log_dir()
LOG_FILE: Path = LOG_DIR / "app.log"

# Rotation policy: keep total disk usage bounded.
MAX_BYTES: int = 2_000_000   # 2 MB per file
BACKUP_COUNT: int = 3         # 3 rotated copies = 6 MB cap

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Singleton guard: setup_logging() is idempotent.
_configured = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO,
                  log_dir: Optional[Path] = None) -> Path:
    """Configure the root logger to write to a rotating file.

    Returns the log directory that was actually used (may differ from
    ``LOG_DIR`` if the default location was unwritable and we fell back to
    ``%TEMP%``). Safe to call multiple times — subsequent calls are no-ops.

    Args:
        level: minimum log level for the root logger.
        log_dir: override the default directory (mostly for tests).
    """
    global LOG_DIR, LOG_FILE, _configured

    if _configured:
        return LOG_DIR

    target = Path(log_dir) if log_dir is not None else _default_log_dir()
    target = _ensure_writable(target)

    LOG_DIR = target
    LOG_FILE = target / "app.log"

    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    # Don't duplicate handlers if a caller already attached one (e.g. tests).
    if not any(isinstance(h, logging.handlers.RotatingFileHandler)
               for h in root.handlers):
        root.addHandler(handler)

    _configured = True
    root.info("=" * 60)
    root.info("PS-BATCH starting · log dir: %s", LOG_DIR)
    root.info("Python: %s", sys.version.split()[0])
    return LOG_DIR


def _ensure_writable(preferred: Path) -> Path:
    """Try to create ``preferred``; fall back to TEMP if that fails.

    Returns whichever directory succeeded. As a last resort returns
    ``preferred`` even if mkdir failed — RotatingFileHandler will then raise
    on first write, which we'd rather surface as a real error than silently
    swallow.
    """
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        # Probe writability: mkdir succeeds even on read-only mounts.
        probe = preferred / ".write_probe"
        probe.touch()
        probe.unlink()
        return preferred
    except OSError:
        pass

    fallback = Path(tempfile.gettempdir()) / "tafpsd_logs"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    except OSError:
        return preferred


def reset_for_tests() -> None:
    """Tear down configuration so tests can call setup_logging again."""
    global _configured
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            try:
                h.close()
            except Exception:
                pass
            root.removeHandler(h)
    _configured = False
