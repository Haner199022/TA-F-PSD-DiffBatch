#!/usr/bin/env python3
"""Render app/version_info.txt from app/_version.py + the .tpl template.

Invoked by build.bat before PyInstaller runs. Also safe to run by hand
when bumping the version locally — verify by diffing app/version_info.txt.

Exit code:
    0 — wrote (or refreshed) version_info.txt
    1 — _version.py malformed or template missing
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
TEMPLATE = APP_DIR / "version_info.txt.tpl"
OUTPUT = APP_DIR / "version_info.txt"

# Make _version importable when run from anywhere
sys.path.insert(0, str(APP_DIR))


def main() -> int:
    try:
        from _version import __version__, version_tuple  # noqa: E402
    except (ImportError, ValueError) as exc:
        print(f"error: _version.py unusable: {exc}", file=sys.stderr)
        return 1

    if not TEMPLATE.exists():
        print(f"error: template missing: {TEMPLATE}", file=sys.stderr)
        return 1

    tpl = TEMPLATE.read_text(encoding="utf-8")
    rendered = tpl.replace("{VERSION_TUPLE}", str(version_tuple()))
    rendered = rendered.replace("{VERSION_STR}", __version__)

    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"rendered version_info.txt · v{__version__} · {version_tuple()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
