#!/usr/bin/env python3
"""Post-build smoke test: launch the produced .exe, ensure it stays alive
for N seconds, then terminate it cleanly.

This catches the class of bug where PyInstaller produces a syntactically
valid .exe that crashes on import (missing module, busted spec datas,
malformed version metadata). Without this gate, the failure shows up only
when a colleague double-clicks the installer.

Exit codes:
    0  exe launched and remained alive for the dwell period
    1  exe missing, exited early, or refused to terminate

Tunables:
    PSBATCH_SMOKE_DWELL_SECS   default 3
    PSBATCH_SMOKE_EXE_PATH     override the default dist path
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = (REPO_ROOT / "app" / "dist" / "TA-F PSD DiffBatch"
               / "TA-F PSD DiffBatch.exe")
DEFAULT_DWELL = 3


def _resolve_exe() -> Path:
    override = os.environ.get("PSBATCH_SMOKE_EXE_PATH")
    return Path(override) if override else DEFAULT_EXE


def _dwell_secs() -> int:
    try:
        return int(os.environ.get("PSBATCH_SMOKE_DWELL_SECS", DEFAULT_DWELL))
    except ValueError:
        return DEFAULT_DWELL


def main() -> int:
    exe = _resolve_exe()
    dwell = _dwell_secs()

    if not exe.exists():
        print(f"FAIL: exe not produced at {exe}", file=sys.stderr)
        return 1

    print(f"smoke: launching {exe}")
    try:
        proc = subprocess.Popen(
            [str(exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        print(f"FAIL: could not launch: {exc}", file=sys.stderr)
        return 1

    try:
        # Wait the dwell period; if it dies sooner, that's the failure we
        # care about (crash-on-startup, missing DLL, busted entrypoint).
        time.sleep(dwell)
        rc = proc.poll()
        if rc is not None:
            print(f"FAIL: exe exited within {dwell}s (rc={rc})", file=sys.stderr)
            return 1
        print(f"smoke: exe alive after {dwell}s — terminating")
    finally:
        # Be polite first, hammer if it doesn't comply.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("smoke: terminate ignored, killing", file=sys.stderr)
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("FAIL: process did not die after kill",
                          file=sys.stderr)
                    return 1

    print("OK: smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
