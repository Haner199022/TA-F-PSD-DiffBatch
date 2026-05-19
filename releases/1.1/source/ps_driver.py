"""Photoshop driver: generates wrapper .jsx, invokes PS via osascript, parses result.

Cross-platform stubs — the Mac path uses `osascript`. The Windows path (added
later in Step 4) uses pywin32 + COM but exposes the same functions.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Locate the bundled normalize_psd.jsx
# ---------------------------------------------------------------------------

def find_normalize_jsx() -> Path:
    """Resolve normalize_psd.jsx in: PyInstaller bundle (_MEIPASS), py2app
    Resources dir, or alongside this script in dev mode."""
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "normalize_psd.jsx")
    here = Path(__file__).resolve().parent
    candidates += [
        here / "normalize_psd.jsx",
        here.parent / "Resources" / "normalize_psd.jsx",  # py2app .app layout
        here.parent / "normalize_psd.jsx",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Could not locate normalize_psd.jsx (looked in: "
        + ", ".join(str(c) for c in candidates) + ")"
    )


# ---------------------------------------------------------------------------
# JSX path-string sanitization
# ---------------------------------------------------------------------------

def _to_jsx_string(s: str) -> str:
    """Encode a Python string as a JSX string literal contents.

    Non-ASCII chars become \\uXXXX escapes so the JSX file is portable across
    encodings — same trick we use elsewhere in this project.
    """
    out = []
    for ch in s:
        cp = ord(ch)
        if ch in ('"', '\\'):
            out.append('\\' + ch)
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif cp > 127:
            out.append(f"\\u{cp:04X}")
        else:
            out.append(ch)
    return ''.join(out)


# ---------------------------------------------------------------------------
# Wrapper JSX generator
# ---------------------------------------------------------------------------

def _make_wrapper(mode: str, cfg: dict, prod_jsx: Path, output_path: Path) -> str:
    """Generate the JS that sets the automation hook globals and evals the
    production JSX. Returns the JS source as a string.
    """
    cfg_with_output = dict(cfg, outputPath=str(output_path))
    fields = ", ".join(
        f'"{k}": "{_to_jsx_string(str(v))}"' for k, v in cfg_with_output.items()
    )

    if mode == "analyze":
        flag = "__ANALYZE_AUTO__"
        cfg_var = "__ANALYZE_CONFIG__"
    elif mode == "batch":
        flag = "__NORMALIZE_AUTO__"
        cfg_var = "__NORMALIZE_CONFIG__"
    else:
        raise ValueError(f"unknown mode: {mode}")

    return (
        f'$.global.{flag} = true;\n'
        f'$.global.{cfg_var} = {{ {fields} }};\n'
        f'$.evalFile(new File("{_to_jsx_string(str(prod_jsx))}"));\n'
    )


# ---------------------------------------------------------------------------
# Platform-specific PS drivers
# ---------------------------------------------------------------------------

def _drive_ps_mac(jsx_path: Path, ps_app: str, timeout_secs: int) -> str:
    """Tell macOS Photoshop to $.evalFile(jsx_path). Raises on failure."""
    applescript = (
        f'with timeout of {timeout_secs} seconds\n'
        f'  tell application "{ps_app}" to do javascript "$.evalFile(\\"{jsx_path}\\")"\n'
        f'end timeout\n'
    )
    p = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True, text=True, timeout=timeout_secs + 60,
    )
    # AppleEvent timeout (-1712) often fires *after* PS finished; the result
    # file existence check (in callers) is the source of truth. We don't raise
    # on rc != 0 here unless we have nothing else to go on.
    return p.stderr or ""


def _drive_ps_windows(jsx_path: Path, ps_app: str, timeout_secs: int) -> str:
    """Tell Windows Photoshop to $.evalFile(jsx_path) via COM (pywin32).
    PS app name is ignored on Windows — COM dispatch picks the latest install.
    """
    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required on Windows. Install with: pip install pywin32"
        ) from exc

    # COM Dispatch resolves to whatever Photoshop is registered for the
    # "Photoshop.Application" ProgID. Works for any reasonably modern PS.
    ps_com = win32com.client.Dispatch("Photoshop.Application")
    js = '$.evalFile(new File("' + _to_jsx_string(str(jsx_path)) + '"));'
    # DoJavaScript is synchronous and returns when the script finishes. No
    # AppleEvent-style timeout issue on Windows.
    try:
        ps_com.DoJavaScript(js)
    except Exception as exc:
        raise RuntimeError(f"Photoshop COM DoJavaScript failed: {exc}") from exc
    return ""


def _drive_ps(jsx_path: Path, ps_app: str, timeout_secs: int = 1800) -> str:
    """Cross-platform: have Photoshop $.evalFile(jsx_path)."""
    system = platform.system()
    if system == "Darwin":
        return _drive_ps_mac(jsx_path, ps_app, timeout_secs)
    if system == "Windows":
        return _drive_ps_windows(jsx_path, ps_app, timeout_secs)
    raise RuntimeError(f"Unsupported platform: {system}")


# ---------------------------------------------------------------------------
# Public API: analyze
# ---------------------------------------------------------------------------

def analyze(after_path: str, before_path: Optional[str] = None,
            ps_app: str = "Adobe Photoshop 2026") -> dict:
    """Read recipe from `after_path` and (optionally) diff against `before_path`.
    Returns a dict like {ok, recipeSummary, diff}.
    """
    prod_jsx = find_normalize_jsx()
    with tempfile.TemporaryDirectory(prefix="psd_normalizer_") as tmp:
        tmp = Path(tmp)
        out_json = tmp / "analyze_result.json"
        cfg = {"referencePath": after_path}
        if before_path:
            cfg["beforePath"] = before_path
        wrapper_src = _make_wrapper("analyze", cfg, prod_jsx, out_json)
        wrapper_path = tmp / "wrapper.jsx"
        wrapper_path.write_text(wrapper_src, encoding="utf-8")

        stderr = _drive_ps(wrapper_path, ps_app, timeout_secs=900)

        if not out_json.exists():
            raise RuntimeError(
                f"PS produced no analyze result.\nstderr:\n{stderr}"
            )
        return json.loads(out_json.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Public API: run_batch
# ---------------------------------------------------------------------------

def run_batch(after_path: str, batch_folder: str,
              ps_app: str = "Adobe Photoshop 2026",
              on_log_line: Optional[Callable[[str], None]] = None,
              output_folder: Optional[str] = None) -> dict:
    """Run the full batch. Streams log lines to `on_log_line` (called from a
    background thread). Returns the final result dict.

    `output_folder` overrides the default of `<batch_folder>/../_normalized/`.
    """
    prod_jsx = find_normalize_jsx()
    out_folder = output_folder or str(Path(batch_folder).parent / "_normalized")
    log_path = Path(out_folder) / "normalize_log.txt"

    # Pre-clear the log so we can tail it cleanly
    Path(out_folder).mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    with tempfile.TemporaryDirectory(prefix="psd_normalizer_") as tmp:
        tmp = Path(tmp)
        out_json = tmp / "batch_result.json"
        cfg = {
            "referencePath": after_path,
            "batchFolderPath": batch_folder,
        }
        if output_folder:
            cfg["outFolderPath"] = output_folder
        wrapper_src = _make_wrapper("batch", cfg, prod_jsx, out_json)
        wrapper_path = tmp / "wrapper.jsx"
        wrapper_path.write_text(wrapper_src, encoding="utf-8")

        # Start log-tailing thread (writes complete on each newline)
        stop_event = threading.Event()
        if on_log_line:
            tailer = threading.Thread(
                target=_tail_log, args=(log_path, on_log_line, stop_event), daemon=True
            )
            tailer.start()

        try:
            stderr = _drive_ps(wrapper_path, ps_app, timeout_secs=1800)
        finally:
            stop_event.set()

        if not out_json.exists():
            raise RuntimeError(
                f"PS produced no batch result.\nstderr:\n{stderr}"
            )
        return json.loads(out_json.read_text(encoding="utf-8"))


def _tail_log(path: Path, on_line: Callable[[str], None], stop_event: threading.Event,
              poll_interval: float = 0.5) -> None:
    """Tail-f a log file that may not exist yet; emit each new line. ExtendScript
    writes \r line endings on macOS, so we split on either \n or \r."""
    last_size = 0
    pending = ""
    while not stop_event.is_set():
        try:
            if path.exists():
                with path.open("rb") as f:
                    f.seek(last_size)
                    chunk = f.read()
                    last_size = f.tell()
                if chunk:
                    text = pending + chunk.decode("utf-8", errors="replace")
                    # ExtendScript may use \r — normalize
                    text = text.replace("\r", "\n")
                    *complete, pending = text.split("\n")
                    for line in complete:
                        if line:
                            on_line(line)
        except Exception:
            pass
        time.sleep(poll_interval)
    # Flush any remaining
    if pending and on_line:
        on_line(pending)


# ---------------------------------------------------------------------------
# Detect Photoshop installation (best effort, Mac only here)
# ---------------------------------------------------------------------------

def find_photoshop_app_name() -> Optional[str]:
    """Return a display name for the installed Photoshop, or None if not found.

    Mac: scans /Applications for 'Adobe Photoshop *' and returns the latest
    (used as the AppleScript target).

    Windows: returns the COM ProgID 'Photoshop.Application' if reachable. The
    actual PS path is discovered by COM at dispatch time, so the returned name
    is informational only.
    """
    system = platform.system()
    if system == "Darwin":
        apps_dir = Path("/Applications")
        if not apps_dir.exists():
            return None
        candidates = sorted(apps_dir.glob("Adobe Photoshop*"))
        if not candidates:
            return None
        return candidates[-1].stem  # "Adobe Photoshop 2026"
    if system == "Windows":
        # We don't probe COM here (slow, opens PS). Just return the ProgID.
        return "Photoshop.Application"
    return None
