"""Tests for the unified error entry point. Tk dialogs are mocked so these
tests run headless and fast."""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

import errors
import logging_setup


@pytest.fixture(autouse=True)
def _setup_logging_to_tmp(tmp_path, monkeypatch):
    """Patch only logging_setup.LOG_FILE; errors.py reads via module reference."""
    logging_setup.reset_for_tests()
    log_file = tmp_path / "app.log"
    monkeypatch.setattr(logging_setup, "LOG_FILE", log_file)
    yield log_file
    logging_setup.reset_for_tests()


def _raise(exc_type=RuntimeError, msg="boom") -> Exception:
    """Return an exception with a real __traceback__ attached, the way it
    arrives in an `except` block."""
    try:
        raise exc_type(msg)
    except exc_type as e:
        return e


class TestShowError:
    def test_logs_full_traceback(self, caplog, _setup_logging_to_tmp):
        exc = _raise(RuntimeError, "kaboom")
        with patch("errors.messagebox.showerror") as mock_dialog:
            with caplog.at_level(logging.ERROR, logger="errors"):
                errors.show_error(None, "Update failed", exc)
        assert mock_dialog.called
        # caplog catches the log call
        assert any("kaboom" in r.message for r in caplog.records)
        # And the traceback string is in the log message
        assert any("RuntimeError" in r.message for r in caplog.records)

    def test_includes_log_path_in_dialog_body(self, _setup_logging_to_tmp):
        exc = _raise()
        with patch("errors.messagebox.showerror") as mock_dialog:
            errors.show_error(None, "Update failed", exc)
        _, kwargs = mock_dialog.call_args
        title = mock_dialog.call_args[0][0]
        body = mock_dialog.call_args[0][1]
        assert title == "Update failed"
        assert "boom" in body
        assert str(_setup_logging_to_tmp) in body
        assert "Copy diagnostic info" in body

    def test_includes_hint_when_provided(self, _setup_logging_to_tmp):
        exc = _raise()
        with patch("errors.messagebox.showerror") as mock_dialog:
            errors.show_error(None, "PS timeout", exc,
                              hint="请手动关闭 Photoshop 后重试。")
        body = mock_dialog.call_args[0][1]
        assert "请手动关闭 Photoshop" in body

    def test_falls_back_to_class_name_when_str_empty(self, _setup_logging_to_tmp):
        class WeirdError(Exception):
            pass
        exc = _raise(WeirdError, "")
        with patch("errors.messagebox.showerror") as mock_dialog:
            errors.show_error(None, "Oops", exc)
        body = mock_dialog.call_args[0][1]
        assert "WeirdError" in body


class TestRetry:
    def test_retry_invoked_when_user_clicks_retry(self, _setup_logging_to_tmp):
        exc = _raise()
        retry_calls = []
        with patch("errors.messagebox.askretrycancel", return_value=True):
            errors.show_error(None, "NAS hiccup", exc,
                              retry=lambda: retry_calls.append(1))
        assert retry_calls == [1]

    def test_retry_skipped_when_user_clicks_cancel(self, _setup_logging_to_tmp):
        exc = _raise()
        retry_calls = []
        with patch("errors.messagebox.askretrycancel", return_value=False):
            errors.show_error(None, "NAS hiccup", exc,
                              retry=lambda: retry_calls.append(1))
        assert retry_calls == []

    def test_retry_callback_exception_does_not_recurse(self, _setup_logging_to_tmp):
        exc = _raise()
        def bad_retry():
            raise ValueError("retry crashed")
        with patch("errors.messagebox.askretrycancel", return_value=True):
            with patch("errors.messagebox.showerror") as mock_err:
                errors.show_error(None, "NAS hiccup", exc, retry=bad_retry)
        # The retry crash surfaces as a fresh error dialog, not a recursion
        assert mock_err.called
        body = mock_err.call_args[0][1]
        assert "retry crashed" in body


class TestShowWarning:
    def test_logs_and_displays(self, caplog, _setup_logging_to_tmp):
        with patch("errors.messagebox.showwarning") as mock_dialog:
            with caplog.at_level(logging.WARNING, logger="errors"):
                errors.show_warning(None, "Missing input", "Pick a folder first.")
        assert mock_dialog.called
        assert any("Pick a folder first" in r.message for r in caplog.records)
