"""Tests for the symlink ownership ledger (decision 3, ADR-052).

`ensure_symlink` reports an existing link and moves on, so a link the harness
wrote under the flat layout survives forever once the segmented deploy stops
generating it. The ledger is the record that lets deploy tell its own stale
links apart from everything else in the config dir — which it must not touch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.deploy.ledger import (
    LEDGER_RELATIVE,
    owned_links,
    prune_unowned,
    read_ledger,
    write_ledger,
)


def _codex_profile(home: Path) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "gate"
    cfg.profiles.items = {
        "gate": ProfileEntry(config_dir=str(home / "codex-home"), agent="codex"),
    }
    return cfg


def _seed(home: Path, spec: dict[str, object]) -> Path:
    from lazy_harness.core.paths import config_dir

    src = config_dir() / "profiles" / "gate"
    src.mkdir(parents=True, exist_ok=True)

    def build(root: Path, tree: dict[str, object]) -> None:
        for name, value in tree.items():
            path = root / name
            if isinstance(value, dict):
                path.mkdir(parents=True, exist_ok=True)
                build(path, value)
            else:
                path.write_text(str(value))

    build(src, spec)
    return src


# --- the ledger as a module -------------------------------------------------


def test_the_ledger_round_trips(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    config.mkdir()

    write_ledger(config, {Path("skills/a.md"), Path("docs")})

    assert read_ledger(config) == {Path("skills/a.md"), Path("docs")}


def test_an_absent_ledger_reads_as_none_not_as_empty(tmp_path: Path) -> None:
    """`None` means 'never written'; `set()` means 'owns nothing'. Adoption
    turns on that difference, so collapsing them would re-adopt on every run."""
    config = tmp_path / "cfg"
    config.mkdir()

    assert read_ledger(config) is None
    write_ledger(config, set())
    assert read_ledger(config) == set()


def test_with_no_ledger_existing_links_into_the_profile_are_adopted(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    config.mkdir()
    src = tmp_path / "profiles" / "gate"
    (src / "skills").mkdir(parents=True)
    (src / "skills" / "a.md").write_text("a")
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("e")

    (config / "skills").mkdir()
    (config / "skills" / "a.md").symlink_to(src / "skills" / "a.md")
    (config / "foreign.md").symlink_to(elsewhere)
    (config / "settings.json").write_text("{}")

    owned, adopted = owned_links(config, src)

    assert adopted is True
    assert owned == {Path("skills/a.md")}, (
        "adoption must take the harness's own links and nothing else"
    )


def test_a_written_ledger_is_believed_over_a_scan(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    config.mkdir()
    src = tmp_path / "profiles" / "gate"
    src.mkdir(parents=True)
    (src / "a.md").write_text("a")
    (config / "a.md").symlink_to(src / "a.md")

    write_ledger(config, set())
    owned, adopted = owned_links(config, src)

    assert adopted is False
    assert owned == set()


def test_a_stale_owned_link_is_removed(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    config.mkdir()
    src = tmp_path / "profiles" / "gate"
    src.mkdir(parents=True)
    (src / "gone.md").write_text("g")
    (config / "gone.md").symlink_to(src / "gone.md")

    removed = prune_unowned(config, src, owned={Path("gone.md")}, keep=set())

    assert removed == [Path("gone.md")]
    assert not (config / "gone.md").exists()
    assert not (config / "gone.md").is_symlink()


def test_a_hand_made_link_the_ledger_never_owned_is_kept(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    config.mkdir()
    src = tmp_path / "profiles" / "gate"
    src.mkdir(parents=True)
    (src / "mine.md").write_text("m")
    (config / "mine.md").symlink_to(src / "mine.md")

    removed = prune_unowned(config, src, owned=set(), keep=set())

    assert removed == []
    assert (config / "mine.md").is_symlink()


def test_an_owned_name_now_pointing_outside_the_profile_is_kept(tmp_path: Path) -> None:
    """The user repointed it. The ledger records a name, not a claim on it."""
    config = tmp_path / "cfg"
    config.mkdir()
    src = tmp_path / "profiles" / "gate"
    src.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("e")
    (config / "repointed.md").symlink_to(elsewhere)

    removed = prune_unowned(config, src, owned={Path("repointed.md")}, keep=set())

    assert removed == []
    assert (config / "repointed.md").is_symlink()


def test_an_owned_link_still_generated_is_kept(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    config.mkdir()
    src = tmp_path / "profiles" / "gate"
    src.mkdir(parents=True)
    (src / "still.md").write_text("s")
    (config / "still.md").symlink_to(src / "still.md")

    removed = prune_unowned(config, src, owned={Path("still.md")}, keep={Path("still.md")})

    assert removed == []
    assert (config / "still.md").is_symlink()


# --- the ledger through a real deploy ---------------------------------------


def test_deploy_removes_a_link_it_no_longer_generates(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    cfg = _codex_profile(home_dir)
    src = _seed(home_dir, {"old.md": "o", "kept.md": "k"})
    deploy_profiles(cfg, only="gate")
    assert (home_dir / "codex-home" / "old.md").is_symlink()

    (src / "old.md").unlink()
    deploy_profiles(cfg, only="gate")

    assert not (home_dir / "codex-home" / "old.md").is_symlink()
    assert (home_dir / "codex-home" / "kept.md").is_symlink()


def test_deploy_writes_a_ledger_naming_what_it_linked(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    _seed(home_dir, {"shared": {"skills": {"a.md": "a"}}, "codex": {"skills": {"b.md": "b"}}})
    deploy_profiles(_codex_profile(home_dir), only="gate")

    ledger = home_dir / "codex-home" / LEDGER_RELATIVE
    assert ledger.is_file()
    assert set(json.loads(ledger.read_text())["links"]) == {"skills/a.md", "skills/b.md"}


def test_deploy_with_the_ledger_deleted_by_hand_re_adopts_and_still_prunes(
    home_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The repo gate: delete the known rows, re-invoke, and it recovers them."""
    from lazy_harness.deploy.engine import deploy_profiles

    cfg = _codex_profile(home_dir)
    src = _seed(home_dir, {"old.md": "o", "kept.md": "k"})
    deploy_profiles(cfg, only="gate")

    (home_dir / "codex-home" / LEDGER_RELATIVE).unlink()
    (src / "old.md").unlink()
    capsys.readouterr()

    deploy_profiles(cfg, only="gate")

    assert not (home_dir / "codex-home" / "old.md").is_symlink(), (
        "a deploy that lost its ledger must re-adopt its links, not abandon them"
    )
    assert "adopt" in capsys.readouterr().out.lower()


def test_deploy_leaves_a_users_own_link_in_the_config_dir_alone(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    cfg = _codex_profile(home_dir)
    _seed(home_dir, {"kept.md": "k"})
    target = home_dir / "codex-home"
    target.mkdir(parents=True, exist_ok=True)
    elsewhere = home_dir / "notes.md"
    elsewhere.write_text("n")
    (target / "notes.md").symlink_to(elsewhere)

    deploy_profiles(cfg, only="gate")
    deploy_profiles(cfg, only="gate")

    assert (target / "notes.md").is_symlink()
    assert (target / "notes.md").resolve() == elsewhere.resolve()


@pytest.mark.parametrize(
    "payload",
    ["{not json", "null", "42", "[]", '{"links": "skills/a.md"}', '{"links": null}'],
    ids=["malformed", "null", "int", "list-for-dict", "str-for-list", "null-for-list"],
)
def test_an_unreadable_ledger_reads_as_absent_rather_than_as_empty(
    tmp_path: Path, payload: str
) -> None:
    """Re-adopting is recoverable; treating junk as 'owns nothing' strands every
    link the harness ever wrote."""
    config = tmp_path / "cfg"
    (config / LEDGER_RELATIVE.parent).mkdir(parents=True)
    (config / LEDGER_RELATIVE).write_text(payload)

    assert read_ledger(config) is None
