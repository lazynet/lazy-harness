"""Tests for the config round-trip selftest check."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.selftest.result import CheckStatus


def test_round_trip_check_warns_when_there_is_no_config(tmp_path: Path) -> None:
    """CheckStatus has no SKIPPED member; absence warns rather than failing."""
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    results = check_config_round_trip(config_path=tmp_path / "absent.toml")
    assert [r.status for r in results] == [CheckStatus.WARNING]


def test_round_trip_check_passes_on_a_full_config(tmp_path: Path) -> None:
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[compound_loop]\nenabled = true\n\n"
        '[scheduler.jobs.qmd-sync]\nschedule = "0 */6 * * *"\ncommand = "qmd sync"\n'
    )

    results = check_config_round_trip(config_path=cfg_path)
    assert [r.status for r in results] == [CheckStatus.PASSED]


def test_an_incomplete_serializer_no_longer_loses_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read-modify-write makes serializer completeness a non-data-loss concern.

    With the old serialize-from-scratch writer, a `_config_to_dict` that
    omitted a section destroyed it. Under read-modify-write the overlay only
    overwrites what it carries, so an incomplete serializer degrades from
    "data loss" to "this field cannot be changed programmatically". The check
    passes here on purpose.
    """
    from lazy_harness.core import config as config_mod
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n\n[compound_loop]\nenabled = true\n')

    def lossy(cfg: config_mod.Config) -> dict:
        return {"harness": {"version": cfg.harness.version}}

    monkeypatch.setattr(config_mod, "_config_to_dict", lossy)

    results = check_config_round_trip(config_path=cfg_path)
    assert results[0].status == CheckStatus.PASSED


def test_round_trip_check_names_the_lost_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A destructive write path must fail the check and name what it dropped.

    This is what the check actually guards: the writer, not the serializer.
    The patched writer below reproduces the pre-fix serialize-from-scratch
    behaviour.
    """
    import tomli_w

    from lazy_harness.core import config as config_mod
    from lazy_harness.selftest.checks import config_check as check_mod

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n\n[compound_loop]\nenabled = true\n')

    def destructive(cfg: config_mod.Config, path: Path) -> None:
        path.write_bytes(tomli_w.dumps({"harness": {"version": cfg.harness.version}}).encode())

    monkeypatch.setattr(check_mod, "save_config", destructive)

    results = check_mod.check_config_round_trip(config_path=cfg_path)
    assert results[0].status == CheckStatus.FAILED
    assert "compound_loop" in results[0].message


def test_round_trip_check_never_writes_to_the_real_config(tmp_path: Path) -> None:
    """A health check that mutates what it checks is not a health check."""
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    cfg_path = tmp_path / "config.toml"
    original = '[harness]\nversion = "1"\n# a comment the probe must not touch\n'
    cfg_path.write_text(original)

    check_config_round_trip(config_path=cfg_path)

    assert cfg_path.read_text() == original


def _reg_with(config_path: str):
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    reg = CapabilityRegistry()
    reg.register(
        Capability(
            name="bogus",
            kind="tool",
            cardinality=Cardinality.MANY,
            config_path=config_path,
            summary="points at nothing",
        )
    )
    return reg


def test_capability_paths_check_fails_when_a_path_does_not_resolve(tmp_path: Path) -> None:
    """A capability pointing at a config key that does not exist is a broken
    contract, and nothing else in the framework would notice it."""
    from lazy_harness.selftest.checks.config_check import check_capability_paths
    from lazy_harness.selftest.result import CheckStatus

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')

    results = check_capability_paths(
        config_path=cfg_path, registry=_reg_with("memory.engram.no_such_field")
    )

    assert results[0].status == CheckStatus.FAILED
    assert "memory.engram.no_such_field" in results[0].message
    assert "bogus" in results[0].message


def test_capability_paths_check_passes_and_names_a_count(tmp_path: Path) -> None:
    from lazy_harness.selftest.checks.config_check import check_capability_paths
    from lazy_harness.selftest.result import CheckStatus

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')

    results = check_capability_paths(
        config_path=cfg_path, registry=_reg_with("memory.engram.enabled")
    )

    assert results[0].status == CheckStatus.PASSED
    assert "1" in results[0].message


def test_capability_paths_check_runs_against_the_real_registry(tmp_path: Path) -> None:
    """Paired smoke test: always injecting the registry would leave the default
    — the one that actually ships — unexercised."""
    from lazy_harness.selftest.checks.config_check import check_capability_paths
    from lazy_harness.selftest.result import CheckStatus

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')

    results = check_capability_paths(config_path=cfg_path)

    assert results[0].status == CheckStatus.PASSED, results[0].message


def test_capability_paths_check_reports_a_missing_config_rather_than_crashing(
    tmp_path: Path,
) -> None:
    from lazy_harness.selftest.checks.config_check import check_capability_paths
    from lazy_harness.selftest.result import CheckStatus

    results = check_capability_paths(config_path=tmp_path / "nope.toml")

    assert results[0].status == CheckStatus.WARNING


def _agent_result(results):
    return next(r for r in results if r.name == "agent-valid")


def test_config_check_refuses_a_misspelled_profile_agent(tmp_path: Path) -> None:
    """A config schema accepting user-supplied identifiers validates them and
    names what it ignored.

    `[profiles.<name>].agent` is such an identifier, and only `[agent].type` was
    ever checked. A typo there is not inert: `agent_for_profile` raises
    `AgentNotFoundError` at deploy and hook time, and `lh selftest` — the
    command whose job is to find that before it fires — reported the config
    valid.
    """
    from lazy_harness.selftest.checks.config_check import check_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "work"\n\n'
        '[profiles.work]\nconfig_dir = "~/.codex-work"\nagent = "codx"\n'
    )

    result = _agent_result(check_config(config_path=cfg_path))

    assert result.status == CheckStatus.FAILED
    assert "codx" in result.message
    assert "work" in result.message


def test_config_check_accepts_a_registered_profile_agent(tmp_path: Path) -> None:
    from lazy_harness.selftest.checks.config_check import check_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "work"\n\n'
        '[profiles.work]\nconfig_dir = "~/.codex-work"\nagent = "codex"\n'
    )

    assert _agent_result(check_config(config_path=cfg_path)).status == CheckStatus.PASSED


def test_the_supported_agent_set_is_the_registry(tmp_path: Path) -> None:
    """One answer in one importable place.

    A hand-maintained set beside the registry answers "is this agent usable"
    twice. It had drifted: `codex` resolves, deploys and runs — the step 4
    contract gate is built on it — and this check failed any config naming it.
    """
    from lazy_harness.agents.registry import list_agents
    from lazy_harness.selftest.checks.config_check import SUPPORTED_AGENTS

    assert SUPPORTED_AGENTS == set(list_agents())
