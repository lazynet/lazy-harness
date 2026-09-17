"""The assembler and the deployer must agree on one layout (decision 5, ADR-052).

`sync_agent_md` reads segments at the profile root and writes the assembled
document there. Segments change what `deploy_profiles` links. If the two drift,
the document the assembler writes is never deployed — the failure this lane has
to rule out, through the real deploy engine rather than the registry.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.agents.base import FileEdit, HookEvent, Operation, ToolCall
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


def _flat_tree(home: Path) -> tuple[Config, Path]:
    """A profile in the pre-segment layout, with role-named doc segments."""
    profiles = config_dir() / "profiles"
    (profiles / "_common").mkdir(parents=True)
    (profiles / "_common" / "common.md").write_text("shared rules\n")
    (profiles / "_common" / "codex.md").write_text("codex rules\n")

    src = profiles / "gate"
    (src / "skills").mkdir(parents=True)
    (src / "skills" / "a.md").write_text("a")
    (src / "head.md").write_text("identity\n")
    (src / "tail.md").write_text("context\n")
    (src / "hooks.json").write_text("{}")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="gate",
            items={"gate": ProfileEntry(config_dir=str(home / "codex-home"), agent="codex")},
        ),
        hooks={},
    )
    # On disk, because the sync hook resolves the profile's agent by loading
    # `config.toml` itself. Without it the hook falls back to the default
    # adapter and writes `CLAUDE.md` into a Codex profile — the very defect the
    # per-profile resolution fixed, which a fixture holding `cfg` in memory
    # would hide.
    save_config(cfg, config_file())
    return cfg, src


def _codex_adapter():
    from lazy_harness.agents.registry import get_agent

    return get_agent("codex")


def test_the_assembled_doc_is_still_linked_after_migrate_and_deploy(home_dir: Path) -> None:
    cfg, src = _flat_tree(home_dir)

    apply_migration(plan_migration(src))
    sync_profiles(config_dir() / "profiles", _codex_adapter(), cfg=cfg)
    deploy_profiles(cfg, only="gate")

    deployed = home_dir / "codex-home" / "AGENTS.md"
    assert deployed.is_symlink(), "the assembled system doc stopped being deployed"
    assert deployed.resolve() == (src / "AGENTS.md").resolve()
    assert "identity" in deployed.read_text()
    assert "codex rules" in deployed.read_text()


def test_migration_moves_the_agent_config_but_leaves_the_doc_segments(home_dir: Path) -> None:
    cfg, src = _flat_tree(home_dir)

    apply_migration(plan_migration(src))

    assert (src / "head.md").is_file(), "a doc segment was moved out of the assembler's reach"
    assert (src / "tail.md").is_file()
    assert (src / "codex" / "hooks.json").is_file()
    assert (src / "shared" / "skills" / "a.md").is_file()


def test_the_assembler_still_finds_its_segments_on_a_migrated_tree(home_dir: Path) -> None:
    cfg, src = _flat_tree(home_dir)
    apply_migration(plan_migration(src))

    results = sync_profiles(config_dir() / "profiles", _codex_adapter(), cfg=cfg)

    written = [r for r in results if r.profile == "gate" and r.action == "written"]
    assert written, f"the assembler skipped a migrated profile: {results}"


def test_the_sync_hook_still_fires_for_a_segment_edit_on_a_migrated_tree(
    home_dir: Path,
) -> None:
    """`_trees_touched` walks up to the `profiles` dir and gates on the
    basename. A `shared/` directory between them must not hide the tree."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as hook

    cfg, src = _flat_tree(home_dir)
    apply_migration(plan_migration(src))
    sync_profiles(config_dir() / "profiles", _codex_adapter(), cfg=cfg)
    deploy_profiles(cfg, only="gate")

    deployed = home_dir / "codex-home" / "AGENTS.md"
    assert "identity, revised" not in deployed.read_text(), (
        "the assertion below would pass without the hook running"
    )

    (src / "head.md").write_text("identity, revised\n")
    hook.main(
        HookEvent(
            event="post_tool_use",
            profile="gate",
            session_id="s1",
            cwd=Path("/work"),
            transcript_path=None,
            tool=ToolCall(
                native_name="Edit",
                operation=Operation.MODIFY_FILE,
                edits=(FileEdit(path=src / "head.md"),),
            ),
        )
    )

    assert "identity, revised" in deployed.read_text(), (
        "the hook did not regenerate the doc the deploy links"
    )


def test_a_segment_dir_does_not_become_a_trigger_path(home_dir: Path) -> None:
    """A file under `shared/` named like a segment still resolves to its tree —
    the guard on the walk-up, so the fix above is not accidental."""
    from lazy_harness.hooks.builtins.post_tool_use_sync_system_doc import _trees_touched

    profiles = config_dir() / "profiles"
    trees = _trees_touched((profiles / "gate" / "shared" / "head.md",))

    assert trees == [profiles]


def _legacy_tree(home: Path) -> tuple[Config, Path]:
    """The deployed shape before ADR-055: stem-keyed segments, flat assets."""
    profiles = config_dir() / "profiles"
    (profiles / "_common").mkdir(parents=True)
    (profiles / "_common" / "CLAUDE.common.md").write_text("shared rules\n")
    (profiles / "_common" / "claude-code.md").write_text("claude rules\n")

    src = profiles / "gate"
    (src / "skills").mkdir(parents=True)
    (src / "skills" / "a.md").write_text("a")
    (src / "CLAUDE.head.md").write_text("identity\n")
    (src / "CLAUDE.tail.md").write_text("context\n")
    (src / "settings.json").write_text("{}")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="gate",
            items={"gate": ProfileEntry(config_dir=str(home / "claude-home"))},
        ),
        hooks={},
    )
    save_config(cfg, config_file())
    return cfg, src


def _claude_adapter():
    from lazy_harness.agents.registry import get_agent

    return get_agent("claude-code")


def test_the_assembler_stops_reporting_a_legacy_layout_once_migrate_has_run(
    home_dir: Path,
) -> None:
    """The two halves of ADR-043's migration window, closing together.

    `sync_profiles` reports `legacy segment layout` so the pending rename is
    visible; `migrate` performs it. If the names the rename writes were not the
    names the assembler reads, the report would survive the migration — which
    is the drift that would leave the fallback permanent.
    """
    cfg, src = _legacy_tree(home_dir)
    profiles = config_dir() / "profiles"

    before = sync_profiles(profiles, _claude_adapter(), cfg=cfg)
    apply_migration(plan_migration(src))
    after = sync_profiles(profiles, _claude_adapter(), cfg=cfg)

    assert [r.reason for r in before] == [
        "legacy segment layout — rename to head.md / common.md / tail.md"
    ]
    assert [r.reason for r in after] == [""], (
        f"the rename left the assembler on the fallback: {after}"
    )
    assembled = (src / "CLAUDE.md").read_text()
    assert "identity" in assembled
    assert "shared rules" in assembled
    assert "claude rules" in assembled


def test_the_renamed_header_names_the_files_that_now_exist(home_dir: Path) -> None:
    """The header tells the reader which files to edit. After the rename it
    must name the role-named ones — a header still pointing at
    `CLAUDE.head.md` sends them to a file that is not there."""
    cfg, src = _legacy_tree(home_dir)
    apply_migration(plan_migration(src))

    sync_profiles(config_dir() / "profiles", _claude_adapter(), cfg=cfg)

    header = (src / "CLAUDE.md").read_text().splitlines()[0]
    assert "head.md / _common/common.md" in header, header
    assert "CLAUDE.head.md" not in header
