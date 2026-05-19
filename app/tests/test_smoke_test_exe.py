"""Tests for tools/smoke_test_exe.py.

We can't exercise the real Windows .exe on Mac/Linux CI, but the smoke
runner is just a process supervisor — its logic (missing / alive / crash
detection) is platform-agnostic and validates against any standin process.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "tools" / "smoke_test_exe.py"


@pytest.fixture
def smoke_mod():
    """Load tools/smoke_test_exe.py as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location("smoke_test_exe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSmokeRunner:
    def test_missing_exe_returns_1(self, smoke_mod, monkeypatch, tmp_path):
        monkeypatch.setenv("PSBATCH_SMOKE_EXE_PATH",
                           str(tmp_path / "not-there.exe"))
        monkeypatch.setenv("PSBATCH_SMOKE_DWELL_SECS", "1")
        assert smoke_mod.main() == 1

    def test_long_lived_process_returns_0(self, smoke_mod, monkeypatch):
        """Use a sleep loop as the standin 'exe' — it stays alive longer
        than the dwell, so the smoke must report OK."""
        monkeypatch.setenv("PSBATCH_SMOKE_EXE_PATH", sys.executable)
        # We need a real subprocess that lives > dwell. Patch _resolve_exe
        # to inject argv that makes the python interpreter sleep.
        original_popen = smoke_mod.subprocess.Popen
        recorded = {}

        def fake_popen(cmd, **kwargs):
            # Replace the [exe] command with [python, -c, "sleep 5"]
            new_cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
            recorded["cmd"] = new_cmd
            return original_popen(new_cmd, **kwargs)

        monkeypatch.setattr(smoke_mod.subprocess, "Popen", fake_popen)
        monkeypatch.setenv("PSBATCH_SMOKE_EXE_PATH", sys.executable)
        monkeypatch.setenv("PSBATCH_SMOKE_DWELL_SECS", "1")
        # The path passed by env must exist or main() exits early
        assert smoke_mod.main() == 0
        assert "cmd" in recorded

    def test_short_lived_process_returns_1(self, smoke_mod, monkeypatch):
        """An exe that exits before the dwell elapses must be flagged."""
        original_popen = smoke_mod.subprocess.Popen

        def fake_popen(cmd, **kwargs):
            return original_popen(
                [sys.executable, "-c", "import sys; sys.exit(0)"], **kwargs,
            )

        monkeypatch.setattr(smoke_mod.subprocess, "Popen", fake_popen)
        monkeypatch.setenv("PSBATCH_SMOKE_EXE_PATH", sys.executable)
        monkeypatch.setenv("PSBATCH_SMOKE_DWELL_SECS", "2")
        assert smoke_mod.main() == 1

    def test_dwell_secs_env_var_respected(self, smoke_mod, monkeypatch):
        monkeypatch.setenv("PSBATCH_SMOKE_DWELL_SECS", "7")
        assert smoke_mod._dwell_secs() == 7

    def test_dwell_secs_falls_back_on_garbage(self, smoke_mod, monkeypatch):
        monkeypatch.setenv("PSBATCH_SMOKE_DWELL_SECS", "not-a-number")
        assert smoke_mod._dwell_secs() == smoke_mod.DEFAULT_DWELL

    def test_resolve_exe_honors_env_override(self, smoke_mod, monkeypatch, tmp_path):
        target = tmp_path / "custom.exe"
        monkeypatch.setenv("PSBATCH_SMOKE_EXE_PATH", str(target))
        assert smoke_mod._resolve_exe() == target

    def test_resolve_exe_falls_back_to_default(self, smoke_mod, monkeypatch):
        monkeypatch.delenv("PSBATCH_SMOKE_EXE_PATH", raising=False)
        result = smoke_mod._resolve_exe()
        assert result == smoke_mod.DEFAULT_EXE
