"""Tests for diagnostic report builder. No UI involved — pure string assembly."""
from __future__ import annotations

import pytest

import diagnostics
import logging_setup


@pytest.fixture(autouse=True)
def _setup_logging_to_tmp(tmp_path, monkeypatch):
    """Redirect LOG_FILE to a tmp file so each test starts with a known log.

    Only patches logging_setup.LOG_FILE — diagnostics reads through the module
    rather than via `from logging_setup import LOG_FILE`, so a single mutation
    is sufficient.
    """
    logging_setup.reset_for_tests()
    log_file = tmp_path / "app.log"
    monkeypatch.setattr(logging_setup, "LOG_FILE", log_file)
    yield log_file
    logging_setup.reset_for_tests()


@pytest.fixture
def ctx_minimal():
    return diagnostics.DiagnosticContext(
        version="1.5.0",
        ps_app="Photoshop.Application",
        after_path="",
        before_path="",
        folder_path="",
        output_path="",
        last_output_folder=None,
    )


class TestBuildReport:
    def test_minimal_report_contains_header(self, ctx_minimal):
        report = diagnostics.build_report(ctx_minimal, [])
        assert "TA-F PSD DiffBatch diagnostic" in report
        assert "1.5.0" in report
        assert "Photoshop.Application" in report

    def test_paths_show_none_when_empty(self, ctx_minimal):
        report = diagnostics.build_report(ctx_minimal, [])
        assert "After:     (none)" in report
        assert "Batch:     (none)" in report
        assert "Output:    (default)" in report

    def test_gui_log_tail_caps_at_50(self, ctx_minimal):
        lines = [f"line {i}" for i in range(100)]
        report = diagnostics.build_report(ctx_minimal, lines)
        # lines[-50:] of range(100) = "line 50" .. "line 99"
        assert "line 99" in report
        assert "line 50" in report
        assert "line 49" not in report

    def test_empty_gui_log_shows_empty_marker(self, ctx_minimal):
        report = diagnostics.build_report(ctx_minimal, [])
        assert "(empty)" in report

    def test_includes_app_log_section_when_present(self, ctx_minimal, _setup_logging_to_tmp):
        log_file = _setup_logging_to_tmp
        log_file.write_text("ERROR: kaboom\nINFO: recovered\n", encoding="utf-8")
        report = diagnostics.build_report(ctx_minimal, [])
        assert "--- app.log (last 200) ---" in report
        assert "kaboom" in report

    def test_app_log_missing_shows_not_present(self, ctx_minimal):
        # _setup_logging_to_tmp creates the file's parent but not the file itself
        report = diagnostics.build_report(ctx_minimal, [])
        assert "--- app.log" in report
        assert "(not present)" in report

    def test_includes_normalize_log_when_output_folder_set(self, ctx_minimal, tmp_path):
        out_folder = tmp_path / "_normalized"
        out_folder.mkdir()
        (out_folder / "normalize_log.txt").write_text(
            "--- (1/3) foo.psd ---\nOK foo\n", encoding="utf-8"
        )
        ctx = diagnostics.DiagnosticContext(
            version="1.5.0", ps_app="ps", after_path="", before_path="",
            folder_path="", output_path="",
            last_output_folder=str(out_folder),
        )
        report = diagnostics.build_report(ctx, [])
        assert "normalize_log.txt" in report
        assert "OK foo" in report

    def test_includes_script_log_when_present(self, ctx_minimal, tmp_path):
        out_folder = tmp_path / "batch" / "_normalized"
        out_folder.mkdir(parents=True)
        script_log = tmp_path / "batch" / "_script_log" / "script_run_log.txt"
        script_log.parent.mkdir(parents=True)
        script_log.write_text("script ran 5 files\n", encoding="utf-8")

        ctx = diagnostics.DiagnosticContext(
            version="1.5.0", ps_app="ps", after_path="", before_path="",
            folder_path="", output_path="",
            last_output_folder=str(out_folder),
        )
        report = diagnostics.build_report(ctx, [])
        assert "script_run_log.txt" in report
        assert "script ran 5 files" in report


class TestTail:
    def test_returns_last_n_lines(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("\n".join(str(i) for i in range(20)), encoding="utf-8")
        assert diagnostics._tail(f, 5) == "15\n16\n17\n18\n19"

    def test_missing_file_returns_placeholder(self, tmp_path):
        assert diagnostics._tail(tmp_path / "nope.txt", 10) == "(not present)"

    def test_empty_file_returns_placeholder(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.touch()
        assert diagnostics._tail(f, 10) == "(empty)"

    def test_replaces_invalid_utf8(self, tmp_path):
        f = tmp_path / "bad.txt"
        # Mid-byte of a UTF-8 sequence; would raise without errors="replace"
        f.write_bytes(b"hello \xff world\n")
        result = diagnostics._tail(f, 10)
        assert "hello" in result
        assert "world" in result
