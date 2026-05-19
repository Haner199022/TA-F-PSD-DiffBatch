"""Persistence roundtrip tests. Each test isolates PRESETS_PATH to a tmp file."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import persistence


@pytest.fixture
def tmp_presets(tmp_path, monkeypatch):
    """Redirect persistence.PRESETS_PATH to a per-test temp file."""
    target = tmp_path / "presets.json"
    monkeypatch.setattr(persistence, "PRESETS_PATH", target)
    return target


class TestPresets:
    def test_empty_when_file_missing(self, tmp_presets):
        assert persistence.load_presets() == []

    def test_save_and_load(self, tmp_presets):
        entry = {"name": "set01", "after_path": "/x/a.psd", "before_path": ""}
        persistence.save_presets([entry])
        assert persistence.load_presets() == [entry]

    def test_corrupt_file_returns_empty(self, tmp_presets):
        tmp_presets.write_text("{not json", encoding="utf-8")
        # Should not raise — silently recover
        assert persistence.load_presets() == []

    def test_save_preserves_other_keys(self, tmp_presets):
        persistence.save_appearance_mode("Light")
        persistence.save_presets([{"name": "x"}])
        # appearance_mode must survive a preset save
        assert persistence.load_appearance_mode() == "Light"


class TestAppearanceMode:
    def test_default_is_system(self, tmp_presets):
        assert persistence.load_appearance_mode() == "System"

    def test_invalid_mode_falls_back(self, tmp_presets):
        persistence.save_appearance_mode("Hot Pink")  # rejected
        assert persistence.load_appearance_mode() == "System"

    def test_roundtrip_each(self, tmp_presets):
        for mode in ("Dark", "Light", "System"):
            persistence.save_appearance_mode(mode)
            assert persistence.load_appearance_mode() == mode


class TestMutedVersions:
    def test_starts_empty(self, tmp_presets):
        assert persistence.load_muted_versions() == []

    def test_add_and_check(self, tmp_presets):
        persistence.add_muted_version("1.5.1")
        assert persistence.is_muted("1.5.1") is True
        assert persistence.is_muted("1.5.2") is False

    def test_add_is_idempotent(self, tmp_presets):
        persistence.add_muted_version("1.5.1")
        persistence.add_muted_version("1.5.1")
        assert persistence.load_muted_versions() == ["1.5.1"]


class TestUserScriptsDirs:
    def test_starts_empty(self, tmp_presets):
        assert persistence.load_user_scripts_dirs() == []

    def test_roundtrip(self, tmp_presets):
        dirs = [r"C:\scripts\my", r"D:\jsx-utils"]
        persistence.save_user_scripts_dirs(dirs)
        assert persistence.load_user_scripts_dirs() == dirs


# ---------------------------------------------------------------------------
# v1.5.0 hardening tests
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    """The save path must never leave the file half-written. We can't truly
    kill the process mid-write in a unit test, but we can simulate every
    failure mode that would cause data loss in the old non-atomic code."""

    def test_save_creates_no_tmp_on_success(self, tmp_presets):
        persistence.save_presets([{"name": "a"}])
        # The .tmp sibling must be cleaned up after a successful os.replace
        assert not tmp_presets.with_suffix(".json.tmp").exists()
        assert tmp_presets.exists()

    def test_replace_failure_preserves_original(self, tmp_presets, monkeypatch):
        # Seed a known-good file we want to defend
        persistence.save_presets([{"name": "original"}])
        original_bytes = tmp_presets.read_bytes()

        # Force os.replace to fail (e.g. file locked by another process)
        def boom(*a, **kw):
            raise OSError("simulated lock")
        monkeypatch.setattr(persistence.os, "replace", boom)

        # The save attempt logs an error but doesn't raise
        persistence.save_presets([{"name": "would-overwrite"}])

        # Original bytes must still be on disk
        assert tmp_presets.read_bytes() == original_bytes

    def test_write_failure_cleans_up_tmp(self, tmp_presets, monkeypatch):
        # Simulate the tmp write itself failing (disk full mid-write).
        def boom(self, *a, **kw):
            raise OSError("simulated disk full")
        monkeypatch.setattr(Path, "write_text", boom)

        persistence.save_presets([{"name": "x"}])

        # No .tmp should linger; the original file should not exist
        # (we never had one in this test)
        assert not tmp_presets.with_suffix(".json.tmp").exists()

    def test_save_stamps_schema_version(self, tmp_presets):
        persistence.save_presets([{"name": "a"}])
        on_disk = json.loads(tmp_presets.read_text(encoding="utf-8"))
        assert on_disk["schema_version"] == persistence.SCHEMA_VERSION


class TestQuarantine:
    """Corrupt files must be moved aside, not silently overwritten."""

    def test_corrupt_file_gets_quarantined(self, tmp_presets):
        tmp_presets.write_text("{not json", encoding="utf-8")
        persistence.load_presets()  # triggers quarantine

        # Original file is gone
        assert not tmp_presets.exists()
        # A .broken.<ts>.json sibling exists with the corrupt bytes preserved
        siblings = list(tmp_presets.parent.glob("presets.broken.*.json"))
        assert len(siblings) == 1
        assert siblings[0].read_text(encoding="utf-8") == "{not json"

    def test_non_dict_top_level_gets_quarantined(self, tmp_presets):
        # A valid JSON array at top level shouldn't crash us, but it's not
        # the shape we expect — treat as corrupt
        tmp_presets.write_text("[1, 2, 3]", encoding="utf-8")
        persistence.load_presets()

        assert not tmp_presets.exists()
        assert list(tmp_presets.parent.glob("presets.broken.*.json"))

    def test_subsequent_save_after_quarantine_works(self, tmp_presets):
        tmp_presets.write_text("{not json", encoding="utf-8")
        persistence.load_presets()  # quarantines

        # After quarantine, app should be able to start fresh
        persistence.save_presets([{"name": "fresh"}])
        assert persistence.load_presets() == [{"name": "fresh"}]

    def test_quarantine_failure_does_not_raise(self, tmp_presets, monkeypatch):
        # If rename itself fails (corrupt file locked), we still return [] —
        # never crash the app on startup over a preset file
        tmp_presets.write_text("{not json", encoding="utf-8")

        def boom(self, *a, **kw):
            raise OSError("simulated lock on rename")
        monkeypatch.setattr(Path, "rename", boom)

        # Must not raise
        result = persistence.load_presets()
        assert result == []


class TestMutedWarnings:
    """v1.5.0 generic warning-mute mechanism, distinct from version mutes."""

    def test_starts_empty(self, tmp_presets):
        assert persistence.load_muted_warnings() == []
        assert persistence.is_warning_muted("anything") is False

    def test_add_and_check(self, tmp_presets):
        persistence.add_muted_warning("nas_unreachable")
        assert persistence.is_warning_muted("nas_unreachable") is True
        assert persistence.is_warning_muted("other_key") is False

    def test_add_is_idempotent(self, tmp_presets):
        persistence.add_muted_warning("nas_unreachable")
        persistence.add_muted_warning("nas_unreachable")
        assert persistence.load_muted_warnings() == ["nas_unreachable"]

    def test_does_not_collide_with_muted_versions(self, tmp_presets):
        persistence.add_muted_version("1.5.1")
        persistence.add_muted_warning("nas_unreachable")
        # Each key is checked against its own list
        assert persistence.is_muted("1.5.1") is True
        assert persistence.is_muted("nas_unreachable") is False
        assert persistence.is_warning_muted("nas_unreachable") is True
        assert persistence.is_warning_muted("1.5.1") is False

    def test_empty_key_is_no_op(self, tmp_presets):
        persistence.add_muted_warning("")
        assert persistence.load_muted_warnings() == []


class TestMigrate:
    """Schema migration is transparent on read; saved files stamp the latest."""

    def test_v1_file_without_schema_gets_migrated_on_read(self, tmp_presets):
        # Simulate a file written by an older build (no schema_version field)
        legacy = {
            "presets": [{"name": "old"}],
            "appearance_mode": "Dark",
        }
        tmp_presets.write_text(json.dumps(legacy), encoding="utf-8")

        # Read still works — content is preserved
        assert persistence.load_presets() == [{"name": "old"}]
        assert persistence.load_appearance_mode() == "Dark"

    def test_v1_file_gets_stamped_on_next_save(self, tmp_presets):
        legacy = {"presets": [{"name": "old"}]}
        tmp_presets.write_text(json.dumps(legacy), encoding="utf-8")

        # Any write triggers _save which stamps the version
        persistence.save_appearance_mode("Light")
        on_disk = json.loads(tmp_presets.read_text(encoding="utf-8"))
        assert on_disk["schema_version"] == persistence.SCHEMA_VERSION
        # Original keys still there
        assert on_disk["presets"] == [{"name": "old"}]
        assert on_disk["appearance_mode"] == "Light"

    def test_future_schema_version_left_alone(self, tmp_presets):
        # A file from a hypothetical newer build shouldn't be downgraded
        future = {"schema_version": 99, "presets": [{"name": "x"}]}
        tmp_presets.write_text(json.dumps(future), encoding="utf-8")

        result = persistence._load()
        assert result["schema_version"] == 99

    def test_migrate_idempotent(self, tmp_presets):
        # Calling _migrate twice produces same result
        raw1 = persistence._migrate({"presets": []})
        raw2 = persistence._migrate(dict(raw1))
        assert raw1 == raw2
