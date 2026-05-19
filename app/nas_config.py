"""NAS configuration with three-level fallback.

Resolution priority (highest first):
    1. ``PSBATCH_UPDATE_URL`` env var — single-file override; overrides the
       full manifest path. Useful for emergency cutovers without rebuilding.
    2. ``app/nas_config.json`` — real config, gitignored. Build machine
       fills this in with the actual NAS share before running build.bat.
    3. ``app/nas_config.example.json`` — placeholder, committed. Lets dev
       checkouts boot without a NAS, ships the placeholder if no real
       config exists at build time.

Returns a NasConfig dataclass with ``nas_root`` and ``manifest_name``.
``manifest_path()`` is the convenience that the updater calls.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ENV_OVERRIDE = "PSBATCH_UPDATE_URL"


@dataclass(frozen=True)
class NasConfig:
    nas_root: str
    manifest_name: str

    def manifest_path(self) -> str:
        return str(Path(self.nas_root) / self.manifest_name)


def _candidate_dirs() -> list[Path]:
    """Where to look for nas_config*.json. PyInstaller frozen exe puts
    bundled data in _MEIPASS; dev mode reads alongside the script."""
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS))  # type: ignore[attr-defined]
    candidates.append(Path(__file__).resolve().parent)
    return candidates


def _read_json_config(path: Path) -> Optional[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            log.warning("nas_config %s: top-level not dict, ignoring", path)
            return None
        return raw
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("nas_config %s unreadable: %s", path, exc)
        return None


def _find_config_file() -> Optional[dict]:
    """Find the first usable .json (real wins over .example) in any candidate
    dir. Returns parsed dict or None if nothing exists / nothing parseable."""
    for d in _candidate_dirs():
        for name in ("nas_config.json", "nas_config.example.json"):
            p = d / name
            if p.exists():
                raw = _read_json_config(p)
                if raw is not None:
                    log.info("nas_config loaded from %s", p)
                    return raw
    return None


def load() -> NasConfig:
    """Resolve the effective NAS configuration. Never raises; falls back
    to a useless-but-non-crashing placeholder if nothing is configured."""
    raw = _find_config_file() or {}
    nas_root = str(raw.get("nas_root") or r"\\nas\TA-F\PS-BATCH").strip()
    manifest_name = str(raw.get("manifest_name") or "latest.json").strip()
    return NasConfig(nas_root=nas_root, manifest_name=manifest_name)


def manifest_path() -> str:
    """The manifest URL/UNC path. Honors ``PSBATCH_UPDATE_URL`` env override
    above all else; otherwise composes from :func:`load`."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return override
    return load().manifest_path()
