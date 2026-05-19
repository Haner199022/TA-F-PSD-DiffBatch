"""Tests for nas_config three-level fallback (env > .json > .example.json)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import nas_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Each test starts with no env override."""
    monkeypatch.delenv(nas_config.ENV_OVERRIDE, raising=False)


@pytest.fixture
def isolated_candidates(tmp_path, monkeypatch):
    """Redirect _candidate_dirs to a single tmp dir so tests don't pick up
    the real app/ folder's example/json."""
    monkeypatch.setattr(nas_config, "_candidate_dirs", lambda: [tmp_path])
    return tmp_path


class TestLoad:
    def test_no_config_returns_placeholder(self, isolated_candidates):
        cfg = nas_config.load()
        assert cfg.nas_root == r"\\nas\TA-F\PS-BATCH"
        assert cfg.manifest_name == "latest.json"

    def test_example_used_when_only_example_present(self, isolated_candidates):
        (isolated_candidates / "nas_config.example.json").write_text(
            json.dumps({"nas_root": r"\\nas\example\share",
                        "manifest_name": "manifest.json"}),
            encoding="utf-8",
        )
        cfg = nas_config.load()
        assert cfg.nas_root == r"\\nas\example\share"
        assert cfg.manifest_name == "manifest.json"

    def test_real_wins_over_example(self, isolated_candidates):
        # Both present; real .json wins
        (isolated_candidates / "nas_config.json").write_text(
            json.dumps({"nas_root": r"\\nas\real\share",
                        "manifest_name": "latest.json"}),
            encoding="utf-8",
        )
        (isolated_candidates / "nas_config.example.json").write_text(
            json.dumps({"nas_root": r"\\nas\placeholder",
                        "manifest_name": "latest.json"}),
            encoding="utf-8",
        )
        cfg = nas_config.load()
        assert cfg.nas_root == r"\\nas\real\share"

    def test_corrupt_json_falls_back_to_next(self, isolated_candidates):
        (isolated_candidates / "nas_config.json").write_text("{not json",
                                                              encoding="utf-8")
        (isolated_candidates / "nas_config.example.json").write_text(
            json.dumps({"nas_root": r"\\nas\fallback",
                        "manifest_name": "latest.json"}),
            encoding="utf-8",
        )
        cfg = nas_config.load()
        # Real is corrupt → next candidate (example) wins
        assert cfg.nas_root == r"\\nas\fallback"

    def test_non_dict_top_level_ignored(self, isolated_candidates):
        (isolated_candidates / "nas_config.json").write_text("[1, 2, 3]",
                                                              encoding="utf-8")
        cfg = nas_config.load()
        # Falls back to placeholder defaults
        assert cfg.nas_root == r"\\nas\TA-F\PS-BATCH"

    def test_partial_config_fills_defaults(self, isolated_candidates):
        # Only nas_root set; manifest_name defaults
        (isolated_candidates / "nas_config.json").write_text(
            json.dumps({"nas_root": r"\\share\only"}),
            encoding="utf-8",
        )
        cfg = nas_config.load()
        assert cfg.nas_root == r"\\share\only"
        assert cfg.manifest_name == "latest.json"


class TestManifestPath:
    def test_env_override_beats_everything(self, isolated_candidates, monkeypatch):
        (isolated_candidates / "nas_config.json").write_text(
            json.dumps({"nas_root": r"\\nas\should-not-be-used",
                        "manifest_name": "latest.json"}),
            encoding="utf-8",
        )
        monkeypatch.setenv(nas_config.ENV_OVERRIDE, r"\\override\path.json")
        assert nas_config.manifest_path() == r"\\override\path.json"

    def test_path_composed_when_no_override(self, isolated_candidates):
        (isolated_candidates / "nas_config.json").write_text(
            json.dumps({"nas_root": r"\\nas\team",
                        "manifest_name": "release.json"}),
            encoding="utf-8",
        )
        result = nas_config.manifest_path()
        # Path separator handling differs by OS; assert both pieces present
        assert r"\\nas\team" in result
        assert "release.json" in result


class TestNasConfigDataclass:
    def test_manifest_path_composes(self):
        cfg = nas_config.NasConfig(
            nas_root=r"\\srv\share", manifest_name="x.json",
        )
        assert "x.json" in cfg.manifest_path()
        assert r"\\srv\share" in cfg.manifest_path()
