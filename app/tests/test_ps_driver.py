"""Pure-Python tests for ps_driver — no Photoshop required."""
import re
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ps_driver
from ps_driver import _to_jsx_string


# ---------------------------------------------------------------------------
# PROGRESS_RE is defined in launcher.py; we re-declare here to avoid pulling
# in customtkinter (which would require a display). The format is owned by
# normalize_psd.jsx → "--- (3/8) somefile.psd ---".
# ---------------------------------------------------------------------------

PROGRESS_RE = re.compile(r"^---\s*\((\d+)/(\d+)\)\s+(.+?)\s*---\s*$")


class TestToJsxString:
    def test_ascii_passthrough(self):
        assert _to_jsx_string("hello world") == "hello world"

    def test_escapes_quotes_and_backslash(self):
        assert _to_jsx_string('a"b\\c') == 'a\\"b\\\\c'

    def test_escapes_newlines(self):
        assert _to_jsx_string("line1\nline2\r\n") == "line1\\nline2\\r\\n"

    def test_non_ascii_becomes_uXXXX(self):
        # Chinese filename — the bug we hit early in this project. Each char
        # should become \uXXXX so the produced .jsx file stays pure-ASCII and
        # ExtendScript reads it correctly regardless of file encoding.
        # Built from codepoints so the test is editor-encoding-immune.
        src = chr(0x4EA7) + chr(0x54C1) + chr(0x56FE)  # 产品图
        result = _to_jsx_string(src)
        assert result == "\\u4EA7\\u54C1\\u56FE"
        for ch in result:
            assert ord(ch) < 128

    def test_path_with_chinese_dir(self):
        # Realistic case: a Windows path with a Chinese username segment.
        src = "C:\\Users\\" + chr(0x674E) + "\\Desktop\\test.psd"
        result = _to_jsx_string(src)
        assert "\\\\" in result        # backslashes escaped
        assert "\\u674E" in result     # 李 → 李
        for ch in result:
            assert ord(ch) < 128


class TestProgressRe:
    @pytest.mark.parametrize("line,expected", [
        ("--- (1/8) foo.psd ---", ("1", "8", "foo.psd")),
        ("--- (10/100) some name with spaces.psd ---", ("10", "100", "some name with spaces.psd")),
        ("---  (3/3)  trailing-ws.psd  ---", ("3", "3", "trailing-ws.psd")),
    ])
    def test_matches(self, line, expected):
        m = PROGRESS_RE.match(line)
        assert m is not None
        assert m.groups() == expected

    @pytest.mark.parametrize("line", [
        "(1/8) missing-dashes.psd",
        "--- 1/8 foo.psd ---",       # no parens
        "regular log line",
        "",
    ])
    def test_no_match(self, line):
        assert PROGRESS_RE.match(line) is None


# ---------------------------------------------------------------------------
# _drive_ps watchdog — mock pywin32 since it's Windows-only.
#
# We install fake `win32com.client` + `pythoncom` modules in sys.modules so
# the function's `import` statements succeed on Mac/Linux CI. The fake objects
# let us drive the success / exception / timeout paths deterministically.
# ---------------------------------------------------------------------------

def _install_fake_pywin32(monkeypatch, *, do_js, expect_init=True):
    """Wire fake win32com.client + pythoncom into sys.modules.

    Args:
        do_js: callable invoked when ps_com.DoJavaScript(js) is called.
               Use this to raise, sleep, or record the JS argument.
        expect_init: whether the test wants to assert CoInitialize/Uninitialize
                     bookkeeping (returns the fake pythoncom for inspection).
    """
    fake_pythoncom = types.ModuleType("pythoncom")
    fake_pythoncom.CoInitialize = MagicMock()
    fake_pythoncom.CoUninitialize = MagicMock()

    ps_com = MagicMock()
    ps_com.DoJavaScript = MagicMock(side_effect=do_js)

    fake_client = types.SimpleNamespace(Dispatch=MagicMock(return_value=ps_com))
    fake_win32com = types.ModuleType("win32com")
    fake_win32com.client = fake_client

    monkeypatch.setitem(sys.modules, "win32com", fake_win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", fake_client)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)

    return fake_pythoncom, fake_client, ps_com


class TestDrivePsWatchdog:
    """Three paths: success / exception / timeout."""

    def test_success_returns_empty_string(self, tmp_path, monkeypatch):
        recorded = {}
        def do_js(js):
            recorded["js"] = js
            return None  # PS DoJavaScript normally returns None

        pyc, _client, ps_com = _install_fake_pywin32(monkeypatch, do_js=do_js)

        jsx = tmp_path / "wrapper.jsx"
        jsx.write_text("/* fake */", encoding="utf-8")

        result = ps_driver._drive_ps(jsx, timeout_secs=2)

        assert result == ""
        # JS payload was constructed and passed through
        assert "$.evalFile(new File" in recorded["js"]
        assert str(jsx) in recorded["js"].replace("\\\\", "\\")
        # COM apartment bookkeeping happened exactly once
        assert pyc.CoInitialize.call_count == 1
        assert pyc.CoUninitialize.call_count == 1
        ps_com.DoJavaScript.assert_called_once()

    def test_exception_in_dojavascript_raises_runtimeerror(self, tmp_path, monkeypatch):
        def do_js(js):
            raise OSError("simulated COM error 0x80020009")

        pyc, _client, _ps_com = _install_fake_pywin32(monkeypatch, do_js=do_js)
        jsx = tmp_path / "wrapper.jsx"
        jsx.write_text("/* fake */", encoding="utf-8")

        with pytest.raises(RuntimeError, match="COM DoJavaScript failed"):
            ps_driver._drive_ps(jsx, timeout_secs=2)

        # CoUninitialize must still fire even on exception — apartment cleanup
        # is in a try/finally inside the worker
        assert pyc.CoInitialize.call_count == 1
        assert pyc.CoUninitialize.call_count == 1

    def test_timeout_when_call_hangs_past_deadline(self, tmp_path, monkeypatch):
        """Worker sleeps 10s; main thread must abort at 0.5s with TimeoutError."""
        def do_js(js):
            time.sleep(10.0)

        _install_fake_pywin32(monkeypatch, do_js=do_js)
        jsx = tmp_path / "wrapper.jsx"
        jsx.write_text("/* fake */", encoding="utf-8")

        t0 = time.monotonic()
        with pytest.raises(TimeoutError) as excinfo:
            ps_driver._drive_ps(jsx, timeout_secs=1)  # int min is 1s
        elapsed = time.monotonic() - t0

        # Error message must give the user the one actionable hint
        msg = str(excinfo.value)
        assert "close Photoshop manually" in msg
        assert "Copy diagnostic info" in msg
        assert "1s" in msg

        # Deadline honored — daemon thread leaks, that's the design
        assert elapsed < 2.0, f"deadline overrun: {elapsed:.2f}s"

    def test_pywin32_missing_raises_clear_message(self, monkeypatch, tmp_path):
        """If pywin32 isn't installed (dev mode without it), the error must
        tell the user what to install."""
        # Remove both fake modules so the import fails inside _drive_ps
        monkeypatch.setitem(sys.modules, "win32com", None)
        monkeypatch.setitem(sys.modules, "pythoncom", None)
        jsx = tmp_path / "wrapper.jsx"
        jsx.write_text("/* fake */", encoding="utf-8")

        with pytest.raises(RuntimeError, match="pywin32 is required"):
            ps_driver._drive_ps(jsx, timeout_secs=1)
