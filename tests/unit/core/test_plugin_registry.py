"""Plugin registry paths that dangle outside the profile.

Claude Code records absolute paths in `plugins/known_marketplaces.json` and
`plugins/installed_plugins.json`. Paths written through the old `~/.claude ->
<profile>` link stop resolving when the link goes, and every plugin of that
marketplace then fails to load with `cache-miss` — silently, in a session.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.core.plugin_registry import find_plugin_path_drift, repair_plugin_paths


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / ".claude-lazy"
    (profile / "plugins" / "marketplaces" / "official").mkdir(parents=True)
    (profile / "plugins" / "cache" / "official" / "tool" / "1.0.0").mkdir(parents=True)
    return profile


def _write_registries(profile: Path, legacy: Path) -> None:
    (profile / "plugins" / "known_marketplaces.json").write_text(
        json.dumps(
            {
                "official": {
                    "source": {"source": "github", "repo": "org/official"},
                    "installLocation": str(legacy / "plugins" / "marketplaces" / "official"),
                    "lastUpdated": "2026-09-23T12:00:00.000Z",
                }
            },
            indent=2,
        )
    )
    (profile / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "tool@official": [
                        {
                            "scope": "user",
                            "installPath": str(
                                legacy / "plugins" / "cache" / "official" / "tool" / "1.0.0"
                            ),
                            "version": "1.0.0",
                        }
                    ],
                    "gone@official": [
                        {
                            "scope": "user",
                            "installPath": str(
                                legacy / "plugins" / "cache" / "official" / "gone" / "2.0.0"
                            ),
                            "version": "2.0.0",
                        }
                    ],
                },
            },
            indent=2,
        )
    )


def test_dangling_paths_are_reported_with_the_in_profile_repair(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    _write_registries(profile, tmp_path / ".claude")

    drift = {d.entry: d for d in find_plugin_path_drift(profile)}

    assert set(drift) == {"official", "tool@official", "gone@official"}
    assert drift["official"].repair == profile / "plugins" / "marketplaces" / "official"
    assert drift["official"].registry == profile / "plugins" / "known_marketplaces.json"
    assert drift["tool@official"].repair == (
        profile / "plugins" / "cache" / "official" / "tool" / "1.0.0"
    )
    assert drift["gone@official"].repair is None
    assert drift["gone@official"].stale == (
        tmp_path / ".claude" / "plugins" / "cache" / "official" / "gone" / "2.0.0"
    )


def test_paths_that_resolve_are_not_drift(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    _write_registries(profile, profile)
    (profile / "plugins" / "cache" / "official" / "gone" / "2.0.0").mkdir(parents=True)

    assert find_plugin_path_drift(profile) == []


def test_a_profile_without_registries_has_no_drift(tmp_path: Path) -> None:
    assert find_plugin_path_drift(tmp_path) == []


@pytest.mark.parametrize("body", ["{not json", "null", "42", "[]", '{"x": null}'])
def test_malformed_or_wrong_type_registries_are_skipped(tmp_path: Path, body: str) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "known_marketplaces.json").write_text(body)
    (plugins / "installed_plugins.json").write_text(body)

    assert find_plugin_path_drift(tmp_path) == []


def test_wrong_type_plugin_entries_are_skipped(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"a": None, "b": [None, 3, {"installPath": 7}], "c": {}}})
    )

    assert find_plugin_path_drift(tmp_path) == []


def test_repair_rewrites_only_what_resolves_and_keeps_every_other_field(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    legacy = tmp_path / ".claude"
    _write_registries(profile, legacy)

    repaired = repair_plugin_paths(profile)

    assert {d.entry for d in repaired} == {"official", "tool@official"}
    remaining = find_plugin_path_drift(profile)
    assert [(d.entry, d.repair) for d in remaining] == [("gone@official", None)]

    marketplaces = json.loads((profile / "plugins" / "known_marketplaces.json").read_text())
    assert marketplaces["official"]["installLocation"] == str(
        profile / "plugins" / "marketplaces" / "official"
    )
    assert marketplaces["official"]["source"] == {"source": "github", "repo": "org/official"}
    assert marketplaces["official"]["lastUpdated"] == "2026-09-23T12:00:00.000Z"

    installed = json.loads((profile / "plugins" / "installed_plugins.json").read_text())
    assert installed["version"] == 2
    assert installed["plugins"]["tool@official"][0]["version"] == "1.0.0"
    assert installed["plugins"]["gone@official"][0]["installPath"] == str(
        legacy / "plugins" / "cache" / "official" / "gone" / "2.0.0"
    )


def test_repair_without_drift_leaves_the_files_untouched(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    _write_registries(profile, profile)
    (profile / "plugins" / "cache" / "official" / "gone" / "2.0.0").mkdir(parents=True)
    registry = profile / "plugins" / "installed_plugins.json"
    before = registry.read_bytes()
    mtime = registry.stat().st_mtime_ns

    assert repair_plugin_paths(profile) == []
    assert registry.read_bytes() == before
    assert registry.stat().st_mtime_ns == mtime
