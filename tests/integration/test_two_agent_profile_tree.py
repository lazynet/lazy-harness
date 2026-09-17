"""One profiles tree, two agents: what each config dir is allowed to receive.

ADR-052's promise is that a Codex profile stops receiving Claude Code's assets.
`test_deploy_profile_segments.py` asserts that on a hand-built segment layout;
what is asserted here is the same promise at the end of the real sequence a user
runs — `lh profile migrate` on each profile, then `lh deploy` — with both agents
sharing one `_common/` and one `profiles/` tree. The consumer is the deployer and
the artifact is the ledger, not the resolver's return value.
"""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)
from lazy_harness.core.paths import config_dir, config_file
from lazy_harness.core.profile_migrate import apply_migration, plan_migration
from lazy_harness.core.sync_agent_md import sync_profiles
from lazy_harness.deploy.engine import deploy_profiles
from lazy_harness.deploy.ledger import LEDGER_RELATIVE

CLAUDE_HOME = "claude-home"
CODEX_HOME = "codex-home"


def _two_agent_tree(home: Path) -> Config:
    """`lazy` on Claude Code with the deployed shape, `lazy-codex` on Codex.

    `lazy` carries the legacy segment names and a flat asset root, which is what
    the deployed machine has; `lazy-codex` is new, so it is born role-named.
    `commands/` sits under `claude-code/` by hand: the registry does not claim
    it, so `migrate` would call it shared — and Codex has its own `skills/`
    directory in `CODEX_HOME`, which a shared link would collide with.
    """
    profiles = config_dir() / "profiles"
    (profiles / "_common").mkdir(parents=True)
    (profiles / "_common" / "CLAUDE.common.md").write_text("shared rules\n")
    (profiles / "_common" / "claude-code.md").write_text("claude-only rules\n")
    (profiles / "_common" / "codex.md").write_text("codex-only rules\n")

    claude = profiles / "lazy"
    (claude / "claude-code" / "commands").mkdir(parents=True)
    (claude / "claude-code" / "commands" / "c.md").write_text("cmd")
    (claude / "shared" / "docs").mkdir(parents=True)
    (claude / "shared" / "docs" / "repos.md").write_text("docs")
    (claude / "CLAUDE.head.md").write_text("lazy identity\n")
    (claude / "CLAUDE.tail.md").write_text("lazy context\n")
    (claude / "settings.json").write_text("{}")

    codex = profiles / "lazy-codex"
    codex.mkdir()
    (codex / "head.md").write_text("codex identity\n")
    (codex / "tail.md").write_text("codex context\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home / CLAUDE_HOME)),
                "lazy-codex": ProfileEntry(
                    config_dir=str(home / CODEX_HOME), agent="codex", billing_model="flat_rate"
                ),
            },
        ),
        hooks={},
    )
    save_config(cfg, config_file())
    return cfg


def _migrate_and_deploy(cfg: Config) -> None:
    from lazy_harness.agents.registry import get_agent

    profiles = config_dir() / "profiles"
    for name in cfg.profiles.items:
        apply_migration(plan_migration(profiles / name))
    sync_profiles(profiles, get_agent("claude-code"), cfg=cfg)
    deploy_profiles(cfg)


def _ledger(target: Path) -> set[str]:
    return set(json.loads((target / LEDGER_RELATIVE).read_text())["links"])


def test_no_claude_code_asset_reaches_the_codex_config_dir(home_dir: Path) -> None:
    cfg = _two_agent_tree(home_dir)

    _migrate_and_deploy(cfg)

    codex_home = home_dir / CODEX_HOME
    for claude_only in ("settings.json", "commands", "skills", "CLAUDE.md"):
        assert not (codex_home / claude_only).exists(), (
            f"{claude_only} reached the Codex config dir; "
            f"it holds {sorted(p.name for p in codex_home.iterdir())}"
        )


def test_the_claude_profile_still_receives_everything_it_had(home_dir: Path) -> None:
    """The other half of the promise: isolation that costs the Claude profile
    its own assets is a regression, not a fix."""
    cfg = _two_agent_tree(home_dir)

    _migrate_and_deploy(cfg)

    claude_home = home_dir / CLAUDE_HOME
    assert (claude_home / "settings.json").is_symlink()
    assert (claude_home / "commands" / "c.md").read_text() == "cmd"
    assert (claude_home / "docs" / "repos.md").read_text() == "docs"
    assert (claude_home / "CLAUDE.md").is_symlink()
    assert not (claude_home / "AGENTS.md").exists()


def test_each_ledger_lists_exactly_the_links_that_profile_was_given(home_dir: Path) -> None:
    """The ledger is what a later deploy prunes against, so a name missing from
    it is a link nothing will ever clean up, and a name in it that was never
    linked is a deletion waiting for an unrelated file.

    `head.md` and `tail.md` are in both ledgers, and that is measured rather
    than chosen: the segments stay at the profile root (ADR-052), the root layer
    is deployed whole, so the build inputs are linked beside the document they
    build. It predates the rename — the deployed machine carries
    `~/.claude-lazy/CLAUDE.head.md` today — and excluding them is a change to
    `resolve_segments`, not to the rename. Asserted here so the next person to
    consider it sees the current answer instead of inferring one.
    """
    cfg = _two_agent_tree(home_dir)

    _migrate_and_deploy(cfg)

    assert _ledger(home_dir / CODEX_HOME) == {"AGENTS.md", "head.md", "tail.md"}
    assert _ledger(home_dir / CLAUDE_HOME) == {
        "CLAUDE.md",
        "head.md",
        "tail.md",
        "settings.json",
        "commands",
        "docs",
    }


def test_a_new_role_named_profile_blocks_sync_until_the_shared_segment_is_renamed(
    home_dir: Path,
) -> None:
    """The ordering constraint the migration plan has to respect.

    `_common/` is one directory for the tree, and the refusal is up front —
    every shared segment a profile needs is loaded before the first write. So
    adding a role-named profile beside legacy ones, without renaming the shared
    segment in the same step, stops `lh profile sync-system-doc` for *every*
    profile, not just the new one. The order is: rename the shared segment
    first, add the new profile second.
    """
    import pytest

    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.sync_agent_md import SyncError

    cfg = _two_agent_tree(home_dir)
    profiles = config_dir() / "profiles"

    with pytest.raises(SyncError, match="_common/common.md"):
        sync_profiles(profiles, get_agent("claude-code"), cfg=cfg)

    assert not (profiles / "lazy" / "CLAUDE.md").exists(), (
        "the refusal wrote a document for the profile it reached first"
    )


def test_the_renamed_segments_stale_links_are_pruned_on_the_next_deploy(home_dir: Path) -> None:
    """The rename changes what the root layer carries, so the links made under
    the old names have to stop existing. A stale `CLAUDE.head.md` symlink would
    dangle at the source the rename emptied."""
    from lazy_harness.agents.registry import get_agent

    profiles = config_dir() / "profiles"
    (profiles / "_common").mkdir(parents=True)
    (profiles / "_common" / "CLAUDE.common.md").write_text("shared rules\n")
    claude = profiles / "lazy"
    claude.mkdir()
    (claude / "CLAUDE.head.md").write_text("lazy identity\n")
    (claude / "CLAUDE.tail.md").write_text("lazy context\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={"lazy": ProfileEntry(config_dir=str(home_dir / CLAUDE_HOME))},
        ),
        hooks={},
    )
    save_config(cfg, config_file())

    sync_profiles(profiles, get_agent("claude-code"), cfg=cfg)
    deploy_profiles(cfg, only="lazy")
    claude_home = home_dir / CLAUDE_HOME
    assert (claude_home / "CLAUDE.head.md").is_symlink(), "fixture no longer reproduces the shape"

    apply_migration(plan_migration(claude))
    sync_profiles(profiles, get_agent("claude-code"), cfg=cfg)
    deploy_profiles(cfg, only="lazy")

    assert not (claude_home / "CLAUDE.head.md").is_symlink(), (
        "a dangling link to the pre-rename segment survived the redeploy"
    )
    assert (claude_home / "head.md").is_symlink()


def test_the_two_documents_are_assembled_from_the_same_shared_segment(home_dir: Path) -> None:
    cfg = _two_agent_tree(home_dir)

    _migrate_and_deploy(cfg)

    codex_doc = (home_dir / CODEX_HOME / "AGENTS.md").read_text()
    claude_doc = (home_dir / CLAUDE_HOME / "CLAUDE.md").read_text()

    for doc in (codex_doc, claude_doc):
        assert "shared rules" in doc
    assert "codex-only rules" in codex_doc
    assert "claude-only rules" not in codex_doc
    assert "claude-only rules" in claude_doc
    assert "codex-only rules" not in claude_doc
