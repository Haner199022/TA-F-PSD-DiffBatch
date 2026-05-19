"""Tests for logging_setup. Covers idempotent setup, custom dir, and the
fallback path when the preferred directory is unwritable."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

import logging_setup


@pytest.fixture(autouse=True)
def _reset():
    """Each test starts with a clean root logger + module state."""
    logging_setup.reset_for_tests()
    yield
    logging_setup.reset_for_tests()


class TestSetupLogging:
    def test_creates_log_file_in_target(self, tmp_path):
        target = tmp_path / "logs"
        used = logging_setup.setup_logging(log_dir=target)
        assert used == target
        assert target.exists()
        assert logging_setup.LOG_FILE == target / "app.log"
        # First call writes a banner line
        assert logging_setup.LOG_FILE.exists()
        assert logging_setup.LOG_FILE.stat().st_size > 0

    def test_is_idempotent(self, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        logging_setup.setup_logging(log_dir=first)
        # Second call must NOT switch directories — caller may not expect it
        used = logging_setup.setup_logging(log_dir=second)
        assert used == first
        assert not second.exists()

    def test_writes_log_messages(self, tmp_path):
        logging_setup.setup_logging(log_dir=tmp_path)
        logging.getLogger("test").info("hello from test")
        content = logging_setup.LOG_FILE.read_text(encoding="utf-8")
        assert "hello from test" in content

    def test_handles_utf8_path_logging(self, tmp_path):
        """Chinese paths show up in logs without GBK encoding errors."""
        logging_setup.setup_logging(log_dir=tmp_path)
        logging.getLogger("test").info("path: %s", "C:\\Users\\李\\桌面.psd")
        content = logging_setup.LOG_FILE.read_text(encoding="utf-8")
        assert "李" in content


class TestFallback:
    def test_falls_back_to_temp_when_target_unwritable(self, tmp_path, monkeypatch):
        # Force mkdir to fail for the preferred dir to simulate locked profile
        original_mkdir = Path.mkdir
        preferred = tmp_path / "locked"

        def fake_mkdir(self, *args, **kwargs):
            if str(self) == str(preferred):
                raise OSError("simulated permission denied")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fake_mkdir)
        used = logging_setup.setup_logging(log_dir=preferred)
        # Should not equal the preferred path; should still be a real dir
        assert used != preferred
        assert used.exists()


class TestDefaultLogDir:
    @pytest.mark.skipif(
        __import__("os").name != "nt",
        reason="Windows-only branch; Path() can't build a WindowsPath on POSIX hosts.",
    )
    def test_uses_localappdata_on_windows(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
        result = logging_setup._default_log_dir()
        assert "TA-F" in str(result)
        assert "PS-BATCH" in str(result)
        assert "logs" in str(result)

    def test_falls_back_to_home_on_non_windows(self, monkeypatch):
        monkeypatch.setattr("os.name", "posix")
        result = logging_setup._default_log_dir()
        assert str(result).endswith(".tafpsd/logs")
