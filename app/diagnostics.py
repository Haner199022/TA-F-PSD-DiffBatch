"""Diagnostic report builder.

When a colleague hits a bug, they hit ``Help → Copy diagnostic info`` and
paste the result into a chat message. This module assembles the report from
three log sources plus the current launcher state:

    1. The last 50 lines of the in-app output panel (what the user just saw).
    2. The last 200 lines of ``app.log`` (structured logging from all modules).
    3. The last 100 lines of the most-recent batch ``normalize_log.txt`` /
       ``script_run_log.txt`` (ExtendScript output — where most real failures
       show up).

If any source is missing it's labelled ``(not present)`` rather than omitted,
so the maintainer can tell the difference between "no log" and "user pasted
half the report".
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import logging_setup
from persistence import PRESETS_PATH


# Header template. Kept simple so the result reads well in plain text chat.
_HEADER = """\
TA-F PSD DiffBatch diagnostic
=============================
Version:   {version}
Python:    {python}
PS:        {ps_app}
Presets:   {presets}
Log file:  {log_file}
{paths}
"""


@dataclass(frozen=True)
class DiagnosticContext:
    """Snapshot of launcher state at the moment the user pressed Copy."""
    version: str
    ps_app: str
    after_path: str
    before_path: str
    folder_path: str
    output_path: str
    last_output_folder: Optional[str]


def build_report(ctx: DiagnosticContext,
                 gui_log_tail: Iterable[str]) -> str:
    """Compose the full diagnostic text. Pure function — safe to call from any
    thread; doesn't touch UI."""
    paths = (
        f"After:     {ctx.after_path or '(none)'}\n"
        f"Before:    {ctx.before_path or '(none)'}\n"
        f"Batch:     {ctx.folder_path or '(none)'}\n"
        f"Output:    {ctx.output_path or '(default)'}\n"
        f"Last out:  {ctx.last_output_folder or '(none)'}"
    )
    # Read LOG_FILE through the module so the path stays correct after
    # setup_logging() reassigns it (e.g. when the preferred dir is unwritable
    # and the launcher falls back to %TEMP%).
    log_file = logging_setup.LOG_FILE

    out: list[str] = [
        _HEADER.format(
            version=ctx.version,
            python=sys.version.split()[0],
            ps_app=ctx.ps_app,
            presets=PRESETS_PATH,
            log_file=log_file,
            paths=paths,
        )
    ]

    gui_lines = list(gui_log_tail)[-50:]
    out.append("\n--- GUI log (last 50) ---")
    out.append("\n".join(gui_lines) if gui_lines else "(empty)")

    out.append("\n\n--- app.log (last 200) ---")
    out.append(_tail(log_file, 200))

    if ctx.last_output_folder:
        normalize_log = Path(ctx.last_output_folder) / "normalize_log.txt"
        out.append(f"\n\n--- normalize_log.txt (last 100) [{normalize_log}] ---")
        out.append(_tail(normalize_log, 100))

        # Script Runner writes to a sibling _script_log folder, not _normalized.
        script_log = (Path(ctx.last_output_folder).parent
                      / "_script_log" / "script_run_log.txt")
        if script_log.exists():
            out.append(f"\n\n--- script_run_log.txt (last 100) ---")
            out.append(_tail(script_log, 100))

    return "\n".join(out)


def _tail(path: Path, n: int) -> str:
    """Return the last ``n`` lines of ``path`` as a string. Never raises —
    missing files and read errors get a labelled placeholder."""
    try:
        if not path.exists():
            return "(not present)"
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return "\n".join(lines[-n:]) if lines else "(empty)"
    except OSError as exc:
        return f"(read failed: {exc})"
