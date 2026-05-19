"""User-data persistence for TA-F PSD DiffBatch.

All user state lives in a single JSON file at ``~/.tafpsd_presets.json``:

    {
      "schema_version":     2,             # added in v1.5.0 for forward-compat
      "presets":            [ ... ],       # named After/Before recipes
      "user_scripts_dirs":  [ ... ],       # extra .jsx dirs added via "+ Dir"
      "appearance_mode":    "Dark"|"Light"|"System",
      "muted_versions":     [ ... ]        # auto-update mute list (v1.5.0+)
    }

Each entry has a typed getter/setter pair; callers never touch the file
directly.

v1.5.0 hardening:
    - ``_save`` writes to ``.tmp`` then ``os.replace`` so a crash/power loss
      mid-write can never leave a half-written file.
    - ``_load`` moves a corrupt file aside to ``.broken.<timestamp>.json``
      instead of silently losing the user's history. The app continues with
      empty state, but the original bytes are preserved on disk for recovery.
    - Schema version is stamped at 2 on every write; older blobs are migrated
      transparently on read.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

PRESETS_PATH = Path.home() / ".tafpsd_presets.json"

# Bump whenever the on-disk shape changes. _migrate() handles upgrades.
SCHEMA_VERSION = 2

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level: read/write the whole blob. All public getters/setters go through these.
# ---------------------------------------------------------------------------

def _load() -> dict:
    """Return the full user-data dict.

    Returns an empty dict if the file is missing. If the file exists but is
    unreadable / not valid JSON / not a dict, the original is renamed to
    ``<path>.broken.<timestamp>.json`` so it isn't overwritten on the next
    save, and we return ``{}`` (the app starts with empty state). The
    rename failure (rare: locked file) is logged but never raised — losing
    presets is bad, but crashing on startup is worse.
    """
    if not PRESETS_PATH.exists():
        return {}
    try:
        raw = PRESETS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return _migrate(data)
        log.error("load corrupt: top-level is %s, not dict", type(data).__name__)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.error("load corrupt: %s", exc)

    # Reached only when the file exists but failed to parse or wasn't a dict.
    _quarantine_corrupt_file()
    return {}


def _quarantine_corrupt_file() -> None:
    """Move the corrupt preset file aside so the next save() doesn't clobber
    it. Best-effort — if the rename fails (locked, EACCES), log and move on."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = PRESETS_PATH.with_suffix(f".broken.{ts}.json")
    try:
        PRESETS_PATH.rename(backup)
        log.info("corrupt presets quarantined: %s", backup)
    except OSError as exc:
        log.error("could not quarantine corrupt presets: %s", exc)


def _save(data: dict) -> None:
    """Atomic write: serialize to a sibling ``.tmp`` file, then ``os.replace``.

    ``os.replace`` is atomic on both POSIX and Windows (NTFS), so a process
    crash or power loss either leaves the original intact (write failed
    before replace) or fully written (replace succeeded). The ``.tmp`` file
    is cleaned up on failure.
    """
    # Always stamp the current schema so old installs that get downgraded
    # don't get fooled by a future-shaped blob.
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION

    tmp = PRESETS_PATH.with_suffix(PRESETS_PATH.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, PRESETS_PATH)
    except OSError as exc:
        log.error("save failed: %s", exc)
        # Clean up the half-written tmp so future saves don't see it linger.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError as cleanup_exc:
                log.warning("could not unlink stale tmp: %s", cleanup_exc)


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

def _migrate(raw: dict) -> dict:
    """Upgrade an on-disk blob to the current schema.

    v1 → v2: no field renames, just stamp the version. Pre-existing files
    have no ``schema_version`` key; we treat anything without it as v1 and
    add the stamp on read so future saves are well-formed.

    Any future migration steps should:
      - check ``raw.get("schema_version", 1)``
      - apply transforms in order
      - end with ``raw["schema_version"] = SCHEMA_VERSION``
    """
    version = raw.get("schema_version", 1)
    if version >= SCHEMA_VERSION:
        return raw

    if version < 2:
        # v1 → v2 — no field changes; future migrations slot here.
        log.info("migrating presets v%s → v%s", version, SCHEMA_VERSION)

    raw["schema_version"] = SCHEMA_VERSION
    return raw


# ---------------------------------------------------------------------------
# Presets — named After/Before recipes
# ---------------------------------------------------------------------------

def load_presets() -> list:
    presets = _load().get("presets")
    return presets if isinstance(presets, list) else []


def save_presets(presets: list) -> None:
    data = _load()
    data["presets"] = presets
    _save(data)


# ---------------------------------------------------------------------------
# Script Runner — user-added .jsx directories
# ---------------------------------------------------------------------------

def load_user_scripts_dirs() -> list:
    dirs = _load().get("user_scripts_dirs")
    return dirs if isinstance(dirs, list) else []


def save_user_scripts_dirs(dirs: list) -> None:
    data = _load()
    data["user_scripts_dirs"] = dirs
    _save(data)


# ---------------------------------------------------------------------------
# Appearance mode — Dark / Light / System
# ---------------------------------------------------------------------------

def load_appearance_mode() -> str:
    """Defaults to 'System' (follow OS) for fresh installs."""
    mode = _load().get("appearance_mode")
    return mode if mode in ("Dark", "Light", "System") else "System"


def save_appearance_mode(mode: str) -> None:
    if mode not in ("Dark", "Light", "System"):
        return
    data = _load()
    data["appearance_mode"] = mode
    _save(data)


# ---------------------------------------------------------------------------
# Auto-update — muted versions (v1.5.0+)
# ---------------------------------------------------------------------------

def load_muted_versions() -> list:
    """Return list of version strings the user said 'don't ask me again' for."""
    muted = _load().get("muted_versions")
    return muted if isinstance(muted, list) else []


def add_muted_version(version: str) -> None:
    if not version:
        return
    muted = load_muted_versions()
    if version in muted:
        return
    muted.append(version)
    data = _load()
    data["muted_versions"] = muted
    _save(data)


def is_muted(version: str) -> bool:
    return version in load_muted_versions()


# ---------------------------------------------------------------------------
# Generic warning mute — for non-version-specific dismissible warnings
# (e.g. "NAS unreachable on first launch") added in v1.5.0+
# ---------------------------------------------------------------------------

def load_muted_warnings() -> list:
    """Warning keys the user said 'don't show me again' for. Free-form
    strings; the launcher picks the keys (e.g. 'nas_unreachable')."""
    muted = _load().get("muted_warnings")
    return muted if isinstance(muted, list) else []


def add_muted_warning(key: str) -> None:
    if not key:
        return
    muted = load_muted_warnings()
    if key in muted:
        return
    muted.append(key)
    data = _load()
    data["muted_warnings"] = muted
    _save(data)


def is_warning_muted(key: str) -> bool:
    return key in load_muted_warnings()
