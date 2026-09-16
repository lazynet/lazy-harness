"""Tests for parsing/comparing the lh_version stamped on deployed artifacts.

Decision 9 (2026-09-13 multi-agent blast radius design): every managed block
or generated file carries the lazy-harness version that wrote it. This module
is the single place that reads it back out of each artifact kind and compares
it against the running binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_parse_version_splits_release_please_form() -> None:
    from lazy_harness.core.artifact_version import parse_version

    assert parse_version("0.59.0") == (0, 59, 0)


def test_parse_version_returns_none_for_unparsable_input() -> None:
    from lazy_harness.core.artifact_version import parse_version

    assert parse_version("not-a-version") is None
    assert parse_version("") is None


def test_is_newer_true_when_artifact_postdates_installed() -> None:
    from lazy_harness.core.artifact_version import is_newer

    assert is_newer("0.60.0", "0.59.0") is True


def test_is_newer_false_when_artifact_is_older_or_equal() -> None:
    from lazy_harness.core.artifact_version import is_newer

    assert is_newer("0.58.0", "0.59.0") is False
    assert is_newer("0.59.0", "0.59.0") is False


def test_is_newer_false_when_either_side_is_unparsable() -> None:
    """A doctor check that cannot prove a mismatch must not manufacture one."""
    from lazy_harness.core.artifact_version import is_newer

    assert is_newer("garbage", "0.59.0") is False
    assert is_newer("0.59.0", "garbage") is False


def test_extract_from_text_reads_the_envrc_notice() -> None:
    from lazy_harness.core.artifact_version import extract_from_text
    from lazy_harness.core.envrc import render_envrc

    content = render_envrc("CLAUDE_CONFIG_DIR", Path("/p"))
    from lazy_harness import __version__

    assert extract_from_text(content) == __version__


def test_extract_from_text_reads_the_generated_header() -> None:
    from lazy_harness import __version__
    from lazy_harness.core.artifact_version import extract_from_text
    from lazy_harness.core.sync_agent_md import render_agent_md

    content = render_agent_md("head", "common", "tail")
    assert extract_from_text(content) == __version__


def test_extract_from_text_returns_none_when_absent() -> None:
    from lazy_harness.core.artifact_version import extract_from_text

    assert extract_from_text("no marker here") is None


def test_extract_from_settings_reads_the_key() -> None:
    """lh_version lives at the document's top level, not inside
    `settings["hooks"]`: that block is a `{event: [entry, ...]}` contract,
    and the version of the document is not a hook entry."""
    from lazy_harness.core.artifact_version import extract_from_settings

    assert extract_from_settings({"lh_version": "0.59.0", "hooks": {}}) == "0.59.0"


def test_extract_from_settings_returns_none_when_absent_or_wrong_type() -> None:
    from lazy_harness.core.artifact_version import extract_from_settings

    assert extract_from_settings({"hooks": {}}) is None
    assert extract_from_settings({}) is None
    assert extract_from_settings({"lh_version": 59}) is None


def _cfg_with_profile(config_dir: Path, roots: list[str] | None = None):
    from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig

    return Config(
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(config_dir), roots=roots or []),
            },
        ),
    )


def test_collect_reports_reads_a_newer_settings_json(tmp_path: Path) -> None:
    from lazy_harness.core.artifact_version import collect_artifact_version_reports

    config_dir = tmp_path / "agentcfg"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({"lh_version": "99.0.0", "hooks": {}}))
    cfg = _cfg_with_profile(config_dir)
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    reports = collect_artifact_version_reports(cfg, profiles_dir)

    settings_reports = [r for r in reports if r.kind == "settings.json"]
    assert len(settings_reports) == 1
    assert settings_reports[0].profile == "personal"
    assert settings_reports[0].lh_version == "99.0.0"


def test_collect_reports_reads_envrc_per_root(tmp_path: Path) -> None:
    from lazy_harness.core.artifact_version import collect_artifact_version_reports
    from lazy_harness.core.envrc import write_envrc

    config_dir = tmp_path / "agentcfg"
    root = tmp_path / "repo"
    write_envrc(root, "CLAUDE_CONFIG_DIR", config_dir)
    cfg = _cfg_with_profile(config_dir, roots=[str(root)])
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    reports = collect_artifact_version_reports(cfg, profiles_dir)

    envrc_reports = [r for r in reports if r.kind == ".envrc"]
    assert len(envrc_reports) == 1
    from lazy_harness import __version__

    assert envrc_reports[0].lh_version == __version__


def test_collect_reports_skips_missing_artifacts(tmp_path: Path) -> None:
    from lazy_harness.core.artifact_version import collect_artifact_version_reports

    cfg = _cfg_with_profile(tmp_path / "nowhere")
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    reports = collect_artifact_version_reports(cfg, profiles_dir)

    assert reports == []


def test_collect_reports_resolves_the_doc_name_per_profile_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each profile can declare its own `[profiles.<name>].agent`. Resolving
    the doc name off one global adapter above the loop is the same defect
    `agent_for_profile` fixed for deploy — the wrong profile gets probed."""
    from lazy_harness.agents import registry
    from lazy_harness.core.artifact_version import collect_artifact_version_reports
    from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig

    class _OtherAdapter(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "other"

        def system_docs(self) -> list[Path]:
            return [Path("OTHER.md")]

    monkeypatch.setitem(registry._AGENTS, "other", _OtherAdapter)

    claude_dir = tmp_path / "claude-x"
    other_dir = tmp_path / "other-x"
    claude_dir.mkdir()
    other_dir.mkdir()
    cfg = Config(
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(claude_dir)),
                "experiment": ProfileEntry(config_dir=str(other_dir), agent="other"),
            },
        ),
    )
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "personal").mkdir(parents=True)
    (profiles_dir / "experiment").mkdir(parents=True)
    (profiles_dir / "personal" / "CLAUDE.md").write_text("head\n")
    (profiles_dir / "experiment" / "OTHER.md").write_text("head\n")

    reports = collect_artifact_version_reports(cfg, profiles_dir)

    by_profile = {r.profile: r.kind for r in reports if r.kind.endswith(".md")}
    assert by_profile["personal"] == "CLAUDE.md"
    assert by_profile["experiment"] == "OTHER.md", (
        f"experiment declares agent='other' but was probed for: {by_profile}"
    )


def test_a_multi_destination_agent_is_reported_once_per_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-043 — `system_docs()` returns every path the agent loads, and each
    is a separately deployed artifact carrying its own version stamp.

    With a single name, the second destination could not be probed at all: an
    out-of-date `instructions/*.instructions.md` beside a current
    `copilot-instructions.md` reported clean.
    """
    from lazy_harness.agents import registry
    from lazy_harness.core.artifact_version import collect_artifact_version_reports
    from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig

    class _TwoDocs(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "two-docs"

        def system_docs(self) -> list[Path]:
            return [Path("copilot-instructions.md"), Path("instructions/lh.instructions.md")]

    monkeypatch.setitem(registry._AGENTS, "two-docs", _TwoDocs)

    cfg_dir = tmp_path / "multi"
    cfg_dir.mkdir()
    cfg = Config(
        profiles=ProfilesConfig(
            default="multi",
            items={"multi": ProfileEntry(config_dir=str(cfg_dir), agent="two-docs")},
        ),
    )
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "multi" / "instructions").mkdir(parents=True)
    (profiles_dir / "multi" / "copilot-instructions.md").write_text("one\n")
    (profiles_dir / "multi" / "instructions" / "lh.instructions.md").write_text("two\n")

    reports = collect_artifact_version_reports(cfg, profiles_dir)

    assert {r.kind for r in reports} == {
        "copilot-instructions.md",
        "instructions/lh.instructions.md",
    }
