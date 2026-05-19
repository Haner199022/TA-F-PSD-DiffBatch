"""Updater logic tests. Network is mocked — these run offline + fast."""
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import persistence
import updater


@pytest.fixture
def tmp_presets(tmp_path, monkeypatch):
    """Each test gets its own persistence file so muted_versions don't leak."""
    monkeypatch.setattr(persistence, "PRESETS_PATH", tmp_path / "presets.json")


class TestIsNewer:
    @pytest.mark.parametrize("remote,local,expected", [
        ("1.5.0", "1.4.1", True),
        ("1.4.1", "1.5.0", False),
        ("1.4.1", "1.4.1", False),
        ("1.5.0", "1.4", True),           # missing component defaults to 0
        ("1.10.0", "1.9.0", True),        # NOT lex compare — the classic semver bug
        ("2.0.0", "1.99.99", True),
        ("garbage", "1.4.1", False),      # malformed → false-safe
    ])
    def test_compare(self, remote, local, expected):
        assert updater.is_newer(remote, local) == expected


class TestCheckForUpdate:
    def _write_manifest(self, path: Path, manifest: dict):
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_returns_info_when_newer(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        self._write_manifest(manifest, {
            "version": "1.5.1",
            "exe_url": str(tmp_path / "setup.exe"),
            "exe_sha256": "abc123",
            "changelog": "fix: stuff",
            "mandatory": False,
        })
        info = updater.check_for_update("1.5.0", manifest_url=str(manifest))
        assert info is not None
        assert info.version == "1.5.1"
        assert info.exe_sha256 == "abc123"
        assert info.mandatory is False

    def test_returns_none_when_same(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        self._write_manifest(manifest, {
            "version": "1.5.0", "exe_url": "x", "exe_sha256": "y",
        })
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is None

    def test_returns_none_when_muted(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        self._write_manifest(manifest, {
            "version": "1.5.1", "exe_url": "x", "exe_sha256": "y",
        })
        persistence.add_muted_version("1.5.1")
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is None

    def test_returns_none_when_nas_down(self, tmp_path, tmp_presets):
        nonexistent = tmp_path / "no-such-file.json"
        assert updater.check_for_update("1.5.0", manifest_url=str(nonexistent)) is None

    def test_returns_none_when_manifest_malformed(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        manifest.write_text("{not json", encoding="utf-8")
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is None

    def test_returns_none_when_required_field_missing(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        # missing exe_sha256
        self._write_manifest(manifest, {"version": "1.5.1", "exe_url": "x"})
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is None


class TestDownloadUpdate:
    def test_succeeds_on_matching_sha(self, tmp_path, tmp_presets):
        src = tmp_path / "src.exe"
        payload = b"fake installer contents"
        src.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()

        info = updater.UpdateInfo(
            version="1.5.1", exe_url=str(src), exe_sha256=sha,
            changelog="", mandatory=False,
        )
        result = updater.download_update(info, dest_dir=tmp_path / "out")
        assert result.exists()
        assert result.read_bytes() == payload

    def test_raises_on_checksum_mismatch(self, tmp_path, tmp_presets):
        src = tmp_path / "src.exe"
        src.write_bytes(b"real contents")
        info = updater.UpdateInfo(
            version="1.5.1", exe_url=str(src),
            exe_sha256="deadbeef" * 8,  # wrong
            changelog="", mandatory=False,
        )
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            updater.download_update(info, dest_dir=tmp_path / "out")


class TestReadManifestTimeout:
    """v1.5.0 hardening: UNC reads run on a daemon thread with a hard
    deadline so an unreachable NAS share can't stall startup."""

    def test_normal_read_completes_under_budget(self, tmp_path):
        # Happy path — local file reads instantly
        manifest = tmp_path / "latest.json"
        manifest.write_text('{"version": "1.5.0", "exe_url": "x"}', encoding="utf-8")
        t0 = time.monotonic()
        result = updater._read_manifest(str(manifest), timeout=3.0)
        elapsed = time.monotonic() - t0
        assert result == {"version": "1.5.0", "exe_url": "x"}
        assert elapsed < 0.5  # generous; actual ~ms

    def test_slow_read_aborts_at_deadline(self, monkeypatch):
        """Simulate a blocked UNC read (worker never returns). Main thread
        must wake at the deadline, log, and return None."""
        # Patch Path.read_bytes so the worker hangs well past the deadline
        def slow_read(self, *args, **kwargs):
            time.sleep(5.0)
            return b"{}"
        monkeypatch.setattr(Path, "read_bytes", slow_read)

        t0 = time.monotonic()
        result = updater._read_manifest("/fake/path.json", timeout=0.5)
        elapsed = time.monotonic() - t0

        assert result is None
        # Allow a little slack for thread scheduling; must be far less than 5s
        assert elapsed < 1.5, f"deadline overrun: {elapsed:.2f}s"

    def test_missing_file_returns_none_promptly(self):
        # File-not-found is the common NAS-unreachable equivalent for tests
        t0 = time.monotonic()
        result = updater._read_manifest("/nonexistent/manifest.json", timeout=3.0)
        elapsed = time.monotonic() - t0
        assert result is None
        assert elapsed < 0.5

    def test_worker_exception_returns_none(self, monkeypatch):
        """Any exception in the worker — not just OSError — must be caught
        so check_for_update never propagates a crash on startup."""
        def boom(self, *args, **kwargs):
            raise ValueError("simulated weird failure")
        monkeypatch.setattr(Path, "read_bytes", boom)
        assert updater._read_manifest("/x.json", timeout=3.0) is None

    def test_malformed_json_returns_none(self, tmp_path):
        manifest = tmp_path / "latest.json"
        manifest.write_bytes(b"\xff\xfeNot valid JSON\xff")
        assert updater._read_manifest(str(manifest), timeout=3.0) is None


class TestCheckResult:
    """v1.5.0 CheckResult dataclass — distinguishes 'no update' from
    'NAS unreachable' so the launcher can show a one-time toast."""

    def _write(self, path, manifest):
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_nas_unreachable_when_manifest_missing(self, tmp_path, tmp_presets):
        result = updater._check_internal(
            "1.5.0",
            manifest_url=str(tmp_path / "absent.json"),
            timeout=2.0,
        )
        assert result.info is None
        assert result.nas_reachable is False

    def test_reachable_no_update_when_same_version(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        self._write(manifest, {
            "version": "1.5.0", "exe_url": "x", "exe_sha256": "y",
        })
        result = updater._check_internal("1.5.0", manifest_url=str(manifest),
                                          timeout=2.0)
        assert result.info is None
        assert result.nas_reachable is True

    def test_reachable_no_update_when_muted(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        self._write(manifest, {
            "version": "1.5.1", "exe_url": "x", "exe_sha256": "y",
        })
        persistence.add_muted_version("1.5.1")
        result = updater._check_internal("1.5.0", manifest_url=str(manifest),
                                          timeout=2.0)
        assert result.info is None
        assert result.nas_reachable is True  # NAS was fine; user muted

    def test_reachable_with_info_when_newer(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        self._write(manifest, {
            "version": "1.5.1", "exe_url": "x", "exe_sha256": "abc",
            "changelog": "fix things",
        })
        result = updater._check_internal("1.5.0", manifest_url=str(manifest),
                                          timeout=2.0)
        assert result.info is not None
        assert result.info.version == "1.5.1"
        assert result.nas_reachable is True

    def test_reachable_when_manifest_malformed_fields(self, tmp_path, tmp_presets):
        """Bad payload != bad network — NAS was fine, publisher screwed up."""
        manifest = tmp_path / "latest.json"
        # Missing exe_sha256
        self._write(manifest, {"version": "1.5.1", "exe_url": "x"})
        result = updater._check_internal("1.5.0", manifest_url=str(manifest),
                                          timeout=2.0)
        assert result.info is None
        assert result.nas_reachable is True

    def test_check_for_update_remains_backward_compatible(self, tmp_path, tmp_presets):
        """Existing callers (tests + the synchronous code path) still get
        Optional[UpdateInfo] from check_for_update — only check_async grew
        the new shape."""
        manifest = tmp_path / "latest.json"
        self._write(manifest, {
            "version": "1.5.1", "exe_url": "x", "exe_sha256": "y",
        })
        result = updater.check_for_update("1.5.0", manifest_url=str(manifest))
        assert isinstance(result, updater.UpdateInfo)


class TestCheckAsync:
    def test_callback_receives_check_result(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        manifest.write_text(json.dumps({
            "version": "1.5.1", "exe_url": "x", "exe_sha256": "y",
        }), encoding="utf-8")

        received = []
        done = __import__("threading").Event()

        def cb(result):
            received.append(result)
            done.set()

        updater.check_async("1.5.0", cb, manifest_url=str(manifest))
        assert done.wait(timeout=5.0), "callback never fired"
        assert len(received) == 1
        assert isinstance(received[0], updater.CheckResult)
        assert received[0].nas_reachable is True
        assert received[0].info is not None

    def test_callback_receives_nas_unreachable_signal(self, tmp_path, tmp_presets):
        received = []
        done = __import__("threading").Event()

        def cb(result):
            received.append(result)
            done.set()

        updater.check_async("1.5.0", cb,
                            manifest_url=str(tmp_path / "absent.json"))
        assert done.wait(timeout=5.0)
        assert received[0].info is None
        assert received[0].nas_reachable is False


class TestMute:
    def test_mute_then_filtered(self, tmp_path, tmp_presets):
        manifest = tmp_path / "latest.json"
        manifest.write_text(json.dumps({
            "version": "1.5.1", "exe_url": "x", "exe_sha256": "y",
        }), encoding="utf-8")

        # Before mute: returns info
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is not None
        # After mute: filtered out
        updater.mute_version("1.5.1")
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is None
        # But a newer one still shows
        manifest.write_text(json.dumps({
            "version": "1.5.2", "exe_url": "x", "exe_sha256": "y",
        }), encoding="utf-8")
        assert updater.check_for_update("1.5.0", manifest_url=str(manifest)) is not None
