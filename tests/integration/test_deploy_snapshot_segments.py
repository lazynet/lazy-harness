"""The snapshot surface must follow the segmented deploy, not the flat one.

`snapshot_targets` mirrors what the deploy writes by listing the profile source
directory. Once segments decide that, a mirror that still lists the root names
targets `shared` and `codex` — directories the deploy never links — and misses
every file link it does. Two readers of one answer, asserted against each other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry, ProfilesConfig
from lazy_harness.core.paths import config_dir
from lazy_harness.deploy.engine import deploy_profiles
from lazy_harness.deploy.snapshot import snapshot_targets


def _segmented(home: Path) -> Config:
    src = config_dir() / "profiles" / "gate"
    (src / "shared" / "skills" / "a").mkdir(parents=True)
    (src / "shared" / "skills" / "a" / "SKILL.md").write_text("a")
    (src / "codex" / "skills" / "b").mkdir(parents=True)
    (src / "codex" / "skills" / "b" / "SKILL.md").write_text("b")
    (src / "claude-code").mkdir(parents=True)
    (src / "claude-code" / "settings.json").write_text("{}")
    (src / "AGENTS.md").write_text("doc")
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="gate",
            items={"gate": ProfileEntry(config_dir=str(home / "codex-home"), agent="codex")},
        ),
        hooks={},
    )


def _links_under(root: Path) -> set[Path]:
    found: set[Path] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        for item in current.iterdir():
            if item.is_symlink():
                found.add(item)
            elif item.is_dir():
                stack.append(item)
    return found


def test_the_snapshot_covers_every_link_the_segmented_deploy_writes(home_dir: Path) -> None:
    cfg = _segmented(home_dir)

    deploy_profiles(cfg, only="gate")

    written = _links_under(home_dir / "codex-home")
    assert written, "the deploy linked nothing; the assertion below would be vacuous"
    missing = written - set(snapshot_targets(cfg))
    assert not missing, f"links a rollback would miss: {sorted(str(p) for p in missing)}"


def test_the_snapshot_covers_the_ownership_ledger(home_dir: Path) -> None:
    """The ledger is a file the deploy writes, so a rollback has to carry it —
    restoring links without the record of them leaves the next deploy unable to
    retract any of them."""
    from lazy_harness.deploy.ledger import LEDGER_RELATIVE

    cfg = _segmented(home_dir)

    assert home_dir / "codex-home" / LEDGER_RELATIVE in set(snapshot_targets(cfg))


def test_the_snapshot_covers_native_skill_links_and_their_ledger(home_dir: Path) -> None:
    from lazy_harness.deploy.skills import SKILL_LEDGER_RELATIVE

    cfg = _segmented(home_dir)
    root = home_dir / ".agents" / "skills"
    targets = set(snapshot_targets(cfg))

    assert {root / "a", root / "b", root.parent / SKILL_LEDGER_RELATIVE} <= targets


def test_the_snapshot_does_not_target_segment_directories(home_dir: Path) -> None:
    """`shared` and `codex` are source layout, never deploy destinations."""
    cfg = _segmented(home_dir)
    targets = {p.name for p in snapshot_targets(cfg)}

    assert "shared" not in targets
    assert "codex" not in targets


@pytest.mark.parametrize("check", ["manifest", "rollback"])
def test_legacy_skill_migration_snapshot_restores_the_root_without_copying_sources(
    home_dir: Path, tmp_path: Path, check: str
) -> None:
    from lazy_harness.deploy.ledger import LEDGER_RELATIVE, write_ledger
    from lazy_harness.deploy.skills import SKILL_LEDGER_RELATIVE
    from lazy_harness.deploy.snapshot import take_snapshot
    from lazy_harness.migrate.rollback import apply_rollback_log

    cfg = _segmented(home_dir)
    cfg.profiles.items["gate"].agent = "claude-code"
    target = home_dir / "codex-home"
    target.mkdir()
    source = config_dir() / "profiles" / "gate" / "skills"
    (source / "legacy").mkdir(parents=True)
    (source / "legacy" / "SKILL.md").write_text("original")
    root = target / "skills"
    root.symlink_to(source, target_is_directory=True)
    write_ledger(target, {Path("skills")})
    previous_ledger = (target / LEDGER_RELATIVE).read_bytes()
    snapshot = tmp_path / "snapshot"
    manifest = take_snapshot(snapshot_targets(cfg, only="gate"), snapshot)

    if check == "manifest":
        entries = json.loads(manifest.read_text())["entries"]
        roots = [entry for entry in entries if entry["path"] == str(root)]
        assert len(roots) == 1
        assert roots[0]["kind"] == "symlink"
        assert not any(
            Path(entry["path"]).is_relative_to(root) for entry in entries if entry not in roots
        )
        assert not list(snapshot.rglob("SKILL.md"))
        return

    deploy_profiles(cfg, only="gate")
    assert not root.is_symlink()
    assert (root / "legacy").is_symlink()
    messages = apply_rollback_log(snapshot)

    assert not any("failed" in message for message in messages)
    assert root.is_symlink()
    assert root.readlink() == source
    assert (source / "legacy" / "SKILL.md").read_text() == "original"
    assert not (source / "a").exists()
    assert (target / LEDGER_RELATIVE).read_bytes() == previous_ledger
    assert not (target / SKILL_LEDGER_RELATIVE).exists()
