"""Photoshop driver: generates wrapper .jsx, invokes PS via COM (pywin32), parses result.

Windows-only as of v1.5.0 — Mac codepath was removed per the team-tool pivot
(see plan/2026-05-14-roadmap-6months-design.md).
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locate the bundled normalize_psd.jsx
# ---------------------------------------------------------------------------

def find_normalize_jsx() -> Path:
    """Resolve normalize_psd.jsx in PyInstaller bundle (_MEIPASS) or alongside
    this script in dev mode."""
    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "normalize_psd.jsx")
    here = Path(__file__).resolve().parent
    candidates.append(here / "normalize_psd.jsx")
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
# PS driver — Windows COM (pywin32)
# ---------------------------------------------------------------------------

def _drive_ps(jsx_path: Path, ps_app: str = "Photoshop.Application",
              timeout_secs: int = 1800) -> str:
    """Tell Photoshop to $.evalFile(jsx_path) via COM, with a hard watchdog.

    The synchronous COM call (`DoJavaScript`) blocks the calling thread for
    the entire duration of the script — minutes to hours for a real batch.
    If PS itself hangs (unresponsive, model dialog stuck, plugin crash) the
    call never returns, which used to take the launcher GUI down with it.

    We move the COM call onto a dedicated daemon thread and apply a hard
    deadline on this thread. On timeout we raise ``TimeoutError`` with a
    message that tells the user the one thing they can actually do —
    close Photoshop manually. The worker thread is leaked (still blocked
    on the COM call); it'll die with the process. Per-thread COM apartment
    init via ``pythoncom.CoInitialize`` is mandatory: any thread that
    dispatches a COM object must own an apartment.

    ``ps_app`` is informational only — COM dispatch picks the registered
    Photoshop install.
    """
    try:
        import win32com.client  # type: ignore
        import pythoncom         # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required. Install with: pip install pywin32"
        ) from exc

    js = '$.evalFile(new File("' + _to_jsx_string(str(jsx_path)) + '"));'

    box: dict = {"exc": None}
    done = threading.Event()

    def worker():
        try:
            # Each thread that touches COM must initialize its own apartment.
            # Without this, Dispatch raises CoInitialize-not-called.
            pythoncom.CoInitialize()
            try:
                ps_com = win32com.client.Dispatch("Photoshop.Application")
                ps_com.DoJavaScript(js)
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:  # noqa: BLE001 — never let worker crash silently
            box["exc"] = exc
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True, name="ps-com-call").start()

    if not done.wait(timeout=timeout_secs):
        raise TimeoutError(
            f"Photoshop did not respond within {timeout_secs}s. "
            f"Please close Photoshop manually and retry. "
            f"If this keeps happening, use Help → Copy diagnostic info and "
            f"send it to the maintainer."
        )

    if box["exc"] is not None:
        raise RuntimeError(
            f"Photoshop COM DoJavaScript failed: {box['exc']}"
        ) from box["exc"]
    return ""


# ---------------------------------------------------------------------------
# Public API: analyze
# ---------------------------------------------------------------------------

def analyze(after_path: str, before_path: Optional[str] = None,
            ps_app: str = "Photoshop.Application") -> dict:
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
              ps_app: str = "Photoshop.Application",
              on_log_line: Optional[Callable[[str], None]] = None,
              output_folder: Optional[str] = None,
              cancel_event: Optional[threading.Event] = None) -> dict:
    """Run the full batch. Streams log lines to `on_log_line` (called from a
    background thread). Returns the final result dict.

    `output_folder` overrides the default of `<batch_folder>/../_normalized/`.
    `cancel_event`: if set during the run, a marker file is dropped in the output
    folder and the .jsx breaks the loop on the next PSD boundary.
    """
    prod_jsx = find_normalize_jsx()
    out_folder = output_folder or str(Path(batch_folder).parent / "_normalized")
    log_path = Path(out_folder) / "normalize_log.txt"
    cancel_marker = Path(out_folder) / ".cancel"

    Path(out_folder).mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()
    # Clean any stale marker from a prior aborted run
    if cancel_marker.exists():
        cancel_marker.unlink()

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

        # Helper threads: log tailer + cancel watcher
        stop_event = threading.Event()
        if on_log_line:
            tailer = threading.Thread(
                target=_tail_log, args=(log_path, on_log_line, stop_event), daemon=True
            )
            tailer.start()
        if cancel_event is not None:
            watcher = threading.Thread(
                target=_watch_cancel, args=(cancel_event, cancel_marker, stop_event), daemon=True
            )
            watcher.start()

        try:
            stderr = _drive_ps(wrapper_path, ps_app, timeout_secs=1800)
        finally:
            stop_event.set()
            # Always clean up the marker so the next run starts fresh
            if cancel_marker.exists():
                try:
                    cancel_marker.unlink()
                except Exception as exc:
                    log.warning("cancel: failed to remove marker: %s", exc)

        if not out_json.exists():
            raise RuntimeError(
                f"PS produced no batch result.\nstderr:\n{stderr}"
            )
        return json.loads(out_json.read_text(encoding="utf-8"))


def _watch_cancel(cancel_event: threading.Event, marker: Path,
                  stop_event: threading.Event, poll_interval: float = 0.2) -> None:
    """Drop the cancel marker when the user clicks CANCEL. Exits when the batch
    finishes (stop_event set) regardless of whether cancel fired."""
    while not stop_event.is_set():
        if cancel_event.is_set():
            try:
                marker.touch()
            except Exception as exc:
                log.warning("cancel: failed to create marker: %s", exc)
            return
        time.sleep(poll_interval)


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
# Public API: run_custom_script
# ---------------------------------------------------------------------------

# Generated wrapper body for run_custom_script(). All placeholders are
# %(NAME)s tokens — we use percent-formatting because the JSX body contains
# many literal { and } that would clash with f-string / str.format.
_CUSTOM_SCRIPT_WRAPPER = r"""
(function () {
    var BATCH_FOLDER  = "%(batch_folder)s";
    var SCRIPT_PATH   = "%(script_path)s";
    var OUTPUT_FOLDER = "%(output_folder)s";
    var OUTPUT_MODE   = "%(output_mode)s";
    var LOG_PATH      = "%(log_path)s";
    var CANCEL_MARKER = "%(cancel_marker)s";
    var RESULT_JSON   = "%(result_json)s";

    function writeLog(msg) {
        var f = new File(LOG_PATH);
        f.encoding = "UTF-8";
        if (f.open("a")) { f.writeln(msg); f.close(); }
    }
    function isCancelled() { return (new File(CANCEL_MARKER)).exists; }
    function jsonEscape(s) {
        s = String(s);
        s = s.replace(/\\/g, "\\\\");
        s = s.replace(/"/g, "\\\"");
        s = s.replace(/\n/g, "\\n");
        s = s.replace(/\r/g, "");
        s = s.replace(/\t/g, "\\t");
        return s;
    }

    var folder = new Folder(BATCH_FOLDER);
    var raw = folder.exists ? folder.getFiles(function (f) {
        return (f instanceof File) && /\.psd$/i.test(f.name);
    }) : [];
    raw.sort(function (a, b) { return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0); });

    var total = raw.length;
    var processed = 0;
    var failed = 0;
    var errors = [];
    var userScript = new File(SCRIPT_PATH);

    writeLog("Custom script run: " + total + " PSD file(s)");
    writeLog("Script: " + SCRIPT_PATH);
    writeLog("Output mode: " + OUTPUT_MODE);

    for (var i = 0; i < raw.length; i++) {
        if (isCancelled()) { writeLog("--- cancelled by user ---"); break; }
        var psd = raw[i];
        writeLog("--- (" + (i + 1) + "/" + total + ") " + psd.name + " ---");

        var doc = null;
        try {
            doc = app.open(psd);
        } catch (eOpen) {
            failed++;
            errors.push({ file: psd.name, message: "open failed: " + eOpen });
            writeLog("ERROR open: " + eOpen);
            continue;
        }

        var scriptOk = true;
        try {
            $.evalFile(userScript);
        } catch (eScript) {
            scriptOk = false;
            failed++;
            errors.push({ file: psd.name, message: "script error: " + eScript });
            writeLog("ERROR script: " + eScript);
        }

        try {
            if (!scriptOk) {
                if (app.documents.length) app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
            } else if (OUTPUT_MODE === "save_to_output") {
                var outFile = new File(OUTPUT_FOLDER + "/" + psd.name);
                var opts = new PhotoshopSaveOptions();
                opts.alphaChannels = true;
                opts.layers = true;
                opts.embedColorProfile = true;
                opts.annotations = false;
                opts.spotColors = true;
                app.activeDocument.saveAs(outFile, opts, true);
                app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
                processed++;
            } else if (OUTPUT_MODE === "overwrite") {
                app.activeDocument.save();
                app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
                processed++;
            } else {
                // no_save
                if (app.documents.length) app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);
                processed++;
            }
        } catch (eSave) {
            failed++;
            errors.push({ file: psd.name, message: "save failed: " + eSave });
            writeLog("ERROR save: " + eSave);
            try { if (app.documents.length) app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (eClose) {}
        }
    }

    writeLog("Done. processed=" + processed + " failed=" + failed);

    var errParts = [];
    for (var j = 0; j < errors.length; j++) {
        errParts.push('{"file":"' + jsonEscape(errors[j].file) + '","message":"' + jsonEscape(errors[j].message) + '"}');
    }
    var json =
        '{"ok":true,' +
        '"total":' + total + ',' +
        '"processed":' + processed + ',' +
        '"failed":' + failed + ',' +
        '"errors":[' + errParts.join(",") + ']}';

    var rf = new File(RESULT_JSON);
    rf.encoding = "UTF-8";
    if (rf.open("w")) { rf.write(json); rf.close(); }
})();
"""


def run_custom_script(script_path: str, batch_folder: str,
                      output_mode: str = "save_to_output",
                      output_folder: Optional[str] = None,
                      ps_app: str = "Photoshop.Application",
                      on_log_line: Optional[Callable[[str], None]] = None,
                      cancel_event: Optional[threading.Event] = None) -> dict:
    """Run a user-supplied .jsx against every PSD in `batch_folder`.

    The wrapper opens each PSD, evals the user's script (which should operate
    on `app.activeDocument`), then handles save/close per `output_mode`.

    output_mode:
      "save_to_output" — saveAs into `output_folder` (default = <batch>/../_script_out/)
      "overwrite"      — save() over the source PSD
      "no_save"        — close without saving (script is responsible for any output)

    Errors in a single PSD are recorded and the batch continues.
    """
    if output_mode not in ("save_to_output", "overwrite", "no_save"):
        raise ValueError(f"unknown output_mode: {output_mode}")
    if not Path(script_path).exists():
        raise FileNotFoundError(f"script not found: {script_path}")
    if not Path(batch_folder).exists():
        raise FileNotFoundError(f"batch folder not found: {batch_folder}")

    # Resolve output folder for both save_to_output and the log/result files.
    # When the user picked overwrite/no_save we still need somewhere to drop
    # the log + cancel marker — put it next to the source folder.
    if output_mode == "save_to_output":
        out_folder = output_folder or str(Path(batch_folder).parent / "_script_out")
    else:
        out_folder = output_folder or str(Path(batch_folder).parent / "_script_log")
    Path(out_folder).mkdir(parents=True, exist_ok=True)

    log_path = Path(out_folder) / "script_run_log.txt"
    cancel_marker = Path(out_folder) / ".cancel"
    if log_path.exists():
        log_path.unlink()
    if cancel_marker.exists():
        cancel_marker.unlink()

    with tempfile.TemporaryDirectory(prefix="ps_custom_") as tmp:
        tmp = Path(tmp)
        out_json = tmp / "custom_result.json"
        wrapper_src = _CUSTOM_SCRIPT_WRAPPER % {
            "batch_folder":  _to_jsx_string(batch_folder),
            "script_path":   _to_jsx_string(script_path),
            "output_folder": _to_jsx_string(out_folder),
            "output_mode":   _to_jsx_string(output_mode),
            "log_path":      _to_jsx_string(str(log_path)),
            "cancel_marker": _to_jsx_string(str(cancel_marker)),
            "result_json":   _to_jsx_string(str(out_json)),
        }
        wrapper_path = tmp / "wrapper.jsx"
        wrapper_path.write_text(wrapper_src, encoding="utf-8")

        stop_event = threading.Event()
        if on_log_line:
            tailer = threading.Thread(
                target=_tail_log, args=(log_path, on_log_line, stop_event), daemon=True
            )
            tailer.start()
        if cancel_event is not None:
            watcher = threading.Thread(
                target=_watch_cancel, args=(cancel_event, cancel_marker, stop_event), daemon=True
            )
            watcher.start()

        try:
            stderr = _drive_ps(wrapper_path, ps_app, timeout_secs=1800)
        finally:
            stop_event.set()
            if cancel_marker.exists():
                try:
                    cancel_marker.unlink()
                except Exception as exc:
                    log.warning("cancel: failed to remove marker: %s", exc)

        if not out_json.exists():
            raise RuntimeError(
                f"PS produced no script-run result.\nstderr:\n{stderr}"
            )
        result = json.loads(out_json.read_text(encoding="utf-8"))
        result["outputFolder"] = out_folder
        return result


# ---------------------------------------------------------------------------
# Detect Photoshop installation (informational only on Windows)
# ---------------------------------------------------------------------------

def find_photoshop_app_name() -> Optional[str]:
    """Return the COM ProgID 'Photoshop.Application'. The actual PS install
    is discovered by COM at dispatch time, so this is informational only —
    we never probe COM here (slow, would open PS)."""
    return "Photoshop.Application"
