"""Single source of truth for the app version string.

All build artifacts derive their version from this module:

    - launcher.APP_VERSION       — imported directly
    - version_info.txt           — rendered from version_info.txt.tpl by
                                   tools/render_version.py
    - installer.iss AppVersion   — read at compile time via GetEnv("APP_VERSION");
                                   build.bat exports it from this module

To cut a release, edit this file only. Everything else (PyInstaller metadata,
Inno Setup wizard, About dialog) follows.
"""
from __future__ import annotations

__version__ = "1.5.0"


def version_tuple() -> tuple[int, int, int, int]:
    """Four-component tuple required by PyInstaller's VSVersionInfo.

    Pads to 4 with zeros so "1.5" → (1, 5, 0, 0); truncates anything beyond
    4 components defensively. Raises ValueError if any component isn't an
    integer — fail-fast at build time beats shipping malformed metadata.
    """
    parts = [int(p) for p in __version__.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])
