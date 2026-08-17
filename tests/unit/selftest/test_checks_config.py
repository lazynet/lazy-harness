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
