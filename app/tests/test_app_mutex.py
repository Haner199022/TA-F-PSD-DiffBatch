"""Cross-file consistency: launcher.py and installer.iss must agree on the
Windows named-mutex used by Inno Setup's AppMutex directive.

If these drift, Inno Setup won't detect the running launcher during an
update install — CloseApplications becomes a no-op and the user sees a
"file in use" error mid-replace. We can't simulate Inno on Mac, but we
can pin the names to a single value at the test layer.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import launcher


APP_DIR = Path(__file__).resolve().parent.parent
INSTALLER_ISS = APP_DIR / "installer.iss"


def _read_define(name: str) -> str:
    """Parse ``#define <name> "value"`` from installer.iss."""
    text = INSTALLER_ISS.read_text(encoding="utf-8")
    m = re.search(rf'^#define\s+{re.escape(name)}\s+"([^"]+)"', text, re.MULTILINE)
    if not m:
        pytest.fail(f"installer.iss does not define {name!r}")
    return m.group(1)


class TestMutexNameConsistency:
    def test_launcher_constant_matches_iss_define(self):
        iss_value = _read_define("MutexName")
        assert launcher.APP_MUTEX_NAME == iss_value, (
            f"launcher.APP_MUTEX_NAME={launcher.APP_MUTEX_NAME!r} but "
            f"installer.iss MutexName={iss_value!r} — these MUST match for "
            f"Inno Setup's AppMutex to detect the running instance."
        )

    def test_mutex_name_has_no_spaces(self):
        """Spaces survive most Win32 APIs but are an avoidable parsing
        hazard in some command-line invocations."""
        assert " " not in launcher.APP_MUTEX_NAME
        assert " " not in _read_define("MutexName")

    def test_iss_appmutex_references_mutexname_define(self):
        """The AppMutex directive must use the {#MutexName} macro, not
        a hardcoded literal — otherwise this consistency test can't
        protect against drift."""
        text = INSTALLER_ISS.read_text(encoding="utf-8")
        assert re.search(r"^AppMutex=\{#MutexName\}", text, re.MULTILINE), (
            "installer.iss AppMutex must reference {#MutexName} so the "
            "name stays single-sourced."
        )

class TestVersionPipeline:
    """W2 D4 architecture: _version.py is the single source of truth.

    Chain:
        app/_version.py  →  launcher.APP_VERSION (import)
                         →  version_info.txt   (via tools/render_version.py)
                         →  installer.iss      (via GetEnv at compile time)

    We can't run ISCC on Mac, but everything upstream of it is testable."""

    def test_launcher_version_matches_version_module(self):
        from _version import __version__
        assert launcher.APP_VERSION == __version__, (
            f"launcher.APP_VERSION={launcher.APP_VERSION!r} but "
            f"_version.__version__={__version__!r} — launcher must "
            f"import from _version, not redeclare the literal."
        )

    def test_iss_uses_getenv_for_version(self):
        """iss must not hardcode version anymore — that's the whole point
        of W2 D4. If a future commit accidentally re-pins it as a literal,
        the test below catches it."""
        text = INSTALLER_ISS.read_text(encoding="utf-8")
        assert re.search(
            r'^#define\s+AppVersion\s+GetEnv\("APP_VERSION"\)',
            text, re.MULTILINE,
        ), (
            "installer.iss AppVersion must be `GetEnv(\"APP_VERSION\")` so "
            "build.bat is the single injection point. A hardcoded literal "
            "reintroduces drift."
        )

    def test_iss_has_fail_fast_when_env_missing(self):
        """If someone hits F9 in the Inno IDE without setting APP_VERSION,
        ISCC should #error rather than silently produce a 0.0.0 installer."""
        text = INSTALLER_ISS.read_text(encoding="utf-8")
        assert '#if AppVersion == ""' in text and "#error" in text, (
            "installer.iss should refuse to compile when APP_VERSION env "
            "var is unset."
        )

    def test_render_version_produces_consistent_output(self, tmp_path):
        """tools/render_version.py must read _version.py and produce a
        version_info.txt whose embedded strings exactly match."""
        import subprocess
        from _version import __version__, version_tuple

        repo_root = APP_DIR.parent
        script = repo_root / "tools" / "render_version.py"
        result = subprocess.run(
            ["python3", str(script)], capture_output=True, text=True, check=True,
        )
        assert __version__ in result.stdout

        rendered = (APP_DIR / "version_info.txt").read_text(encoding="utf-8")
        # The 4-tuple must appear twice (filevers + prodvers)
        assert rendered.count(str(version_tuple())) == 2
        # FileVersion + ProductVersion both carry the string form
        assert rendered.count(f"u'{__version__}'") >= 2

    def test_render_version_fails_loudly_when_template_missing(self, monkeypatch):
        """If the template file is gone, render_version must exit 1 (so
        build.bat aborts) rather than silently writing nothing."""
        import importlib.util
        from pathlib import Path
        repo_root = APP_DIR.parent
        script = repo_root / "tools" / "render_version.py"

        spec = importlib.util.spec_from_file_location("render_version", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Point TEMPLATE at a path that doesn't exist
        monkeypatch.setattr(mod, "TEMPLATE", Path("/nonexistent/template.tpl"))
        assert mod.main() == 1

    def test_version_tuple_pads_to_four(self):
        """PyInstaller requires a 4-tuple; short version strings must pad."""
        from _version import version_tuple
        # The actual version
        result = version_tuple()
        assert len(result) == 4
        assert all(isinstance(p, int) for p in result)
