"""NAS-based auto-update for TA-F PSD DiffBatch (v1.5.0+).

Design (per plan/2026-05-14-roadmap-6months-design.md):

  Startup
    └─ background thread: read NAS latest.json  (3s timeout, silent fallback)
       └─ if remote_version > local_version and not muted:
            ├─ download installer to %TEMP% (SHA256 verified)
            └─ post UpdateInfo to the GUI queue → user sees [Update][Later][Mute]

  On [Update]:
    └─ apply_update():  Popen installer  →  sys.exit(0)
       The installer waits for the running .exe to terminate, then replaces
       and relaunches. Inno Setup handles this via /SILENT + AppMutex.

  On [Later]:  do nothing (re-prompt next startup)
  On [Mute]:   add version to muted_versions[], skip until a newer version ships

All NAS access is best-effort; an unreachable NAS never blocks the GUI.
"""
from __future__ import annotations

import hashlib
import json
import logging
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import nas_config
from persistence import add_muted_version, is_muted

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — single source of truth for the NAS layout
# ---------------------------------------------------------------------------

# Default NAS root (kept for backwards-compat / Help → Onboarding). The
# canonical source is nas_config.py; this constant is now derived from it,
# so any per-machine `nas_config.json` automatically flows through.
DEFAULT_NAS_ROOT = nas_config.load().nas_root
DEFAULT_MANIFEST_NAME = nas_config.load().manifest_name

# Probe timeout: the launcher should never wait more than this for the NAS.
PROBE_TIMEOUT_SECS = 3.0


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------

@dataclass
class UpdateInfo:
    """Result of a successful NAS check. Always trustworthy: the SHA256 in
    `exe_sha256` is what download_update() will verify against."""
    version: str          # semver string from manifest, e.g. "1.5.1"
    exe_url: str          # absolute path or http(s) URL
    exe_sha256: str       # lowercase hex
    changelog: str        # human-readable summary (may be multi-line)
    mandatory: bool       # if true, GUI suppresses the "Later" button


@dataclass(frozen=True)
class CheckResult:
    """What check_async tells the launcher.

    Distinguishes the three relevant outcomes:
        - newer version available             → info is UpdateInfo, nas_reachable=True
        - up-to-date / muted / malformed JSON → info is None,       nas_reachable=True
        - NAS share unreachable / timed out   → info is None,       nas_reachable=False

    The third case is the one the launcher uses to decide whether to show
    the "auto-update source unreachable" toast on first encounter.
    """
    info: Optional[UpdateInfo]
    nas_reachable: bool


# ---------------------------------------------------------------------------
# Manifest discovery
# ---------------------------------------------------------------------------

def _manifest_path() -> str:
    """Resolve the manifest location. Delegates to nas_config which honors
    the PSBATCH_UPDATE_URL env override, then nas_config.json (real), then
    nas_config.example.json (placeholder)."""
    return nas_config.manifest_path()


def _read_manifest(url_or_path: str, timeout: float) -> Optional[dict]:
    """Fetch + parse the manifest. Returns None on any failure (network down,
    UNC unreachable, timeout, malformed JSON). Never raises.

    UNC paths on Windows ignore the urllib socket timeout — an unreachable
    SMB share can take 5-10s before the OS gives up. We run the read on a
    daemon thread and apply a hard deadline on the calling side, so the
    startup path never waits longer than ``timeout`` seconds regardless of
    what the OS does with the share.

    The daemon thread is leaked on timeout; it'll finish (or die with the
    process) on its own. This is fine because:
      - the thread holds no shared mutable state past ``box``;
      - Python guarantees the GIL releases during blocking IO so the main
        thread really does wake up at the deadline;
      - the launcher exits cleanly via sys.exit even with live daemons.
    """
    box: dict = {"raw": None, "exc": None}
    done = threading.Event()

    def worker():
        try:
            if url_or_path.lower().startswith(("http://", "https://")):
                with urllib.request.urlopen(url_or_path, timeout=timeout) as resp:
                    box["raw"] = resp.read()
            else:
                box["raw"] = Path(url_or_path).read_bytes()
        except (OSError, urllib.error.URLError, socket.timeout) as exc:
            box["exc"] = exc
        except Exception as exc:  # noqa: BLE001 — never let worker crash silently
            box["exc"] = exc
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True, name="manifest-probe").start()

    if not done.wait(timeout=timeout):
        log.info("manifest probe timed out after %.1fs (path: %s)",
                 timeout, url_or_path)
        return None

    if box["exc"] is not None:
        log.warning("manifest unreachable: %s", box["exc"])
        return None

    raw = box["raw"]
    if raw is None:
        # Worker finished without setting raw or exc — defensive only.
        return None

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("manifest malformed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Version comparison — simple semver tuple compare
# ---------------------------------------------------------------------------

_VERSION_HEAD_RE = __import__("re").compile(r"^\d+(?:\.\d+)*")


def _parse_version(v: str) -> Optional[tuple]:
    """Parse '1.4.1' → (1, 4, 1). Returns None if the string doesn't start with
    digits — that catches garbage manifests so they never appear newer."""
    m = _VERSION_HEAD_RE.match(v.strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(0).split("."))


def is_newer(remote: str, local: str) -> bool:
    """True if `remote` is strictly greater than `local`. Returns False for
    any unparseable input — better to skip a real update than to apply junk."""
    r, l = _parse_version(remote), _parse_version(local)
    if r is None or l is None:
        return False
    return r > l


# ---------------------------------------------------------------------------
# Public API — check (cheap, called on startup)
# ---------------------------------------------------------------------------

def _check_internal(local_version: str,
                    manifest_url: Optional[str],
                    timeout: float) -> CheckResult:
    """Do the actual manifest read + parse + version compare.

    Always returns a CheckResult. ``nas_reachable`` is False iff the
    manifest read itself failed (network down, share unmounted, JSON
    malformed). It's True for "manifest fine, no newer version" and
    "manifest fine, muted version" — both indistinguishable from the
    user's point of view, and equally not a NAS problem.
    """
    raw = _read_manifest(manifest_url or _manifest_path(), timeout=timeout)
    if raw is None:
        return CheckResult(info=None, nas_reachable=False)

    try:
        version = str(raw["version"]).strip()
        exe_url = str(raw["exe_url"]).strip()
        sha = str(raw["exe_sha256"]).strip().lower()
    except (KeyError, TypeError) as exc:
        log.warning("manifest missing fields: %s", exc)
        # We DID reach the NAS — bad payload is a publisher problem, not
        # a network problem. Don't show the NAS-unreachable toast.
        return CheckResult(info=None, nas_reachable=True)

    if not is_newer(version, local_version) or is_muted(version):
        return CheckResult(info=None, nas_reachable=True)

    return CheckResult(
        info=UpdateInfo(
            version=version,
            exe_url=exe_url,
            exe_sha256=sha,
            changelog=str(raw.get("changelog", "")).strip(),
            mandatory=bool(raw.get("mandatory", False)),
        ),
        nas_reachable=True,
    )


def check_for_update(local_version: str,
                     manifest_url: Optional[str] = None,
                     timeout: float = PROBE_TIMEOUT_SECS) -> Optional[UpdateInfo]:
    """Synchronous variant retained for tests and any future caller that
    doesn't care about the nas_reachable signal. Returns just the
    UpdateInfo (or None if up-to-date / muted / NAS down)."""
    return _check_internal(local_version, manifest_url, timeout).info


def check_async(local_version: str,
                callback: Callable[[CheckResult], None],
                manifest_url: Optional[str] = None) -> None:
    """Run the check in a daemon thread; invoke ``callback(CheckResult)``
    when done. Never blocks the caller. The callback receives the new
    CheckResult shape (v1.5.0+) so the GUI can distinguish "no update"
    from "NAS unreachable"."""
    def run():
        result = _check_internal(local_version, manifest_url, PROBE_TIMEOUT_SECS)
        try:
            callback(result)
        except Exception as exc:
            log.error("callback failed: %s", exc, exc_info=True)
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# Public API — download (called after user accepts)
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_update(info: UpdateInfo,
                    dest_dir: Optional[Path] = None,
                    on_progress: Optional[Callable[[float], None]] = None) -> Path:
    """Download the installer, verify SHA256, return the local path. Raises
    RuntimeError if checksum mismatch or download fails."""
    import tempfile
    target_dir = dest_dir or Path(tempfile.gettempdir()) / "tafpsd_updater"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"PSDNormalizer-{info.version}-setup.exe"

    src = info.exe_url
    if src.lower().startswith(("http://", "https://")):
        # HTTP download with progress callback
        with urllib.request.urlopen(src, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            written = 0
            with target.open("wb") as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if on_progress and total:
                        on_progress(min(1.0, written / total))
    else:
        # UNC / local file copy
        import shutil
        shutil.copy2(src, target)
        if on_progress:
            on_progress(1.0)

    got = _sha256_file(target)
    if got.lower() != info.exe_sha256.lower():
        try:
            target.unlink()
        except OSError:
            pass
        raise RuntimeError(
            f"checksum mismatch: expected {info.exe_sha256}, got {got}"
        )
    return target


# ---------------------------------------------------------------------------
# Public API — apply (called after download succeeds)
# ---------------------------------------------------------------------------

def apply_update(installer: Path) -> None:
    """Launch the installer detached and exit the current process. The
    installer is responsible for waiting on the running .exe to close
    (Inno Setup AppMutex), replacing it, and relaunching.

    Does not return on success — calls sys.exit(0).
    """
    if not installer.exists():
        raise RuntimeError(f"installer missing: {installer}")
    # DETACHED_PROCESS=0x00000008 + CREATE_NEW_PROCESS_GROUP=0x00000200
    creation_flags = 0x00000008 | 0x00000200
    subprocess.Popen(
        [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
        creationflags=creation_flags,
        close_fds=True,
    )
    # Tiny grace period so the installer's first kernel32 call happens before
    # we tear down. Not strictly required — Popen returned, so the child exists.
    time.sleep(0.2)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Public API — mute (called when user picks "Mute this version")
# ---------------------------------------------------------------------------

def mute_version(version: str) -> None:
    """Mark this exact version string as 'don't ask me again'. A later, newer
    release will still prompt (since is_newer comparisons go by parsed semver)."""
    add_muted_version(version)
