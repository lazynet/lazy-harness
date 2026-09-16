"""The snapshot surface, checked against the deploy that produces it.

`snapshot_targets` and `deploy/engine.py` answer one question — which paths does
a deploy own — from two places. An integration test invokes both and asserts
they agree, because a target list that drifts from the engine is a rollback that
silently misses an artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.cli.deploy_cmd import _run_deploy
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)
from lazy_harness.core.paths import config_dir
from lazy_harness.deploy.snapshot import snapshot_targets


def _artifacts(root: Path) -> set[Path]:
    """Every file and symlink under `root`, without following symlinked dirs."""
    found: set[Path] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        for item in current.iterdir():
            if item.is_symlink() or item.is_file():
                found.add(item)
            elif item.is_dir():
                stack.append(item)
    return found


@pytest.fixture
def two_profiles(home_dir: Path) -> Config:
    profiles_src = config_dir() / "profiles"
    for name in ("lazy", "flex"):
        src = profiles_src / name
        src.mkdir(parents=True)
        (src / "CLAUDE.md").write_text(f"# {name}\n")
        (src / "skills").mkdir()
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy")),
                "flex": ProfileEntry(config_dir=str(home_dir / ".claude-flex")),
            },
        ),
        hooks={},
    )


def test_every_path_the_deploy_writes_is_a_snapshot_target(
    home_dir: Path, two_profiles: Config
) -> None:
    before = _artifacts(home_dir)
    targets = set(snapshot_targets(two_profiles))

    _run_deploy(two_profiles)

    written = _artifacts(home_dir) - before
    assert written, "the deploy wrote nothing; the assertion below would be vacuous"
    assert written <= targets, (
        "the deploy writes artifacts the snapshot would not capture: "
        f"{sorted(str(p) for p in written - targets)}"
    )


def test_two_profiles_settings_are_distinct_targets(two_profiles: Config) -> None:
    """The basename collision, at the surface that produces it."""
    targets = snapshot_targets(two_profiles)
    settings = [p for p in targets if p.name == "settings.json"]

    assert len(settings) == 2
    assert len(set(settings)) == 2


def _write_config(home_dir: Path) -> None:
    """Two profiles on disk, so every basename in the surface collides."""
    from lazy_harness.core.config import save_config

    profiles_src = config_dir() / "profiles"
    for name in ("lazy", "flex"):
        src = profiles_src / name
        src.mkdir(parents=True, exist_ok=True)
        (src / "CLAUDE.md").write_text(f"# {name}\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy")),
                "flex": ProfileEntry(config_dir=str(home_dir / ".claude-flex")),
            },
        ),
    )
    save_config(cfg, config_dir() / "config.toml")


def _snapshots(home_dir: Path) -> list[Path]:
    deploy_ns = home_dir / ".config" / "lazy-harness" / "backups" / "deploy"
    if not deploy_ns.is_dir():
        return []
    return sorted(p for p in deploy_ns.iterdir() if p.is_dir())


def test_deploy_takes_a_snapshot_without_being_asked(home_dir: Path) -> None:
    """Unconditional on every deploy. A trigger that can be wrong fails in the
    direction of no snapshot when one was needed."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    assert CliRunner().invoke(cli, ["deploy"]).exit_code == 0

    taken = _snapshots(home_dir)
    assert len(taken) == 1
    assert (taken[0] / "rollback.json").is_file()


def test_snapshot_flag_takes_a_snapshot_and_does_not_deploy(home_dir: Path) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--snapshot"])

    assert result.exit_code == 0
    assert len(_snapshots(home_dir)) == 1
    assert not (home_dir / ".claude-lazy" / "CLAUDE.md").exists()
    assert not (home_dir / ".claude-lazy" / "settings.json").exists()


def test_rollback_restores_each_profile_its_own_settings(home_dir: Path) -> None:
    """The collision end to end, verified by reading the files back."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    assert runner.invoke(cli, ["deploy"]).exit_code == 0

    lazy_settings = home_dir / ".claude-lazy" / "settings.json"
    flex_settings = home_dir / ".claude-flex" / "settings.json"
    lazy_settings.write_bytes(b'{"who": "lazy"}')
    flex_settings.write_bytes(b'{"who": "flex"}')

    assert runner.invoke(cli, ["deploy"]).exit_code == 0
    assert lazy_settings.read_bytes() != b'{"who": "lazy"}'

    assert runner.invoke(cli, ["deploy", "--rollback"]).exit_code == 0

    assert lazy_settings.read_bytes() == b'{"who": "lazy"}'
    assert flex_settings.read_bytes() == b'{"who": "flex"}'


def test_rollback_repoints_a_profile_symlink(home_dir: Path) -> None:
    """Every profile artifact is an existing symlink under ADR-009, so this is
    the shape a deploy rollback is actually made of."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    assert runner.invoke(cli, ["deploy"]).exit_code == 0

    link = home_dir / ".claude-lazy" / "CLAUDE.md"
    original = link.readlink()

    assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0

    elsewhere = home_dir / "elsewhere.md"
    elsewhere.write_text("# not the profile\n")
    link.unlink()
    link.symlink_to(elsewhere)

    assert runner.invoke(cli, ["deploy", "--rollback"]).exit_code == 0

    assert link.readlink() == original


def test_snapshots_are_pruned_to_the_last_ten(home_dir: Path) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    for _ in range(12):
        assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0

    assert len(_snapshots(home_dir)) == 10


def test_snapshot_help_says_it_exits_without_deploying(home_dir: Path) -> None:
    """Read off the rendered help, not the docstring.

    Help that reads as 'enable the snapshot' would teach the opposite of the
    decision: without the flag there is still a snapshot.
    """
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    output = CliRunner().invoke(cli, ["deploy", "--help"]).output

    assert "without deploying" in output


def test_two_deploys_in_the_same_second_keep_separate_snapshots(home_dir: Path) -> None:
    """A second-resolution timestamp collapses them onto one directory, and the
    second snapshot then overwrites the first one's manifest with post-deploy
    state — losing the only record of what the machine looked like before."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0
    assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0

    assert len(_snapshots(home_dir)) == 2


@pytest.fixture
def detected_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin MCP discovery, which otherwise probes the machine running the test.

    Both adapters plan their MCP document only when a server is detected, so
    leaving the probe live makes "did the deploy write this target" a fact about
    the developer's `PATH`. Pinned to one server rather than none, because the
    interesting direction is the target being written: a blanked probe would
    make every MCP assertion vacuously true.
    """
    from lazy_harness.deploy import engine

    monkeypatch.setattr(
        engine, "_collect_mcp_servers", lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}}
    )


@pytest.fixture
def mixed_agents(home_dir: Path) -> Config:
    """The default profile overrides the agent; the second inherits the global.

    The override is the only shape under which the two readers can disagree —
    without one, `get_agent(cfg.agent.type)` and `agent_for_profile` return the
    same adapter and every assertion below holds for the wrong reason.
    """
    profiles_src = config_dir() / "profiles"
    for name in ("lazy", "flex"):
        src = profiles_src / name
        src.mkdir(parents=True)
        (src / "CLAUDE.md").write_text(f"# {name}\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy"), agent="codex"),
                "flex": ProfileEntry(config_dir=str(home_dir / ".claude-flex")),
            },
        ),
        hooks={},
    )
    cfg.agent.type = "claude-code"
    return cfg


def test_the_snapshot_reads_the_agent_per_profile_like_the_deploy(
    home_dir: Path, mixed_agents: Config
) -> None:
    """The override profile's MCP target comes from its own adapter.

    `CodexAdapter.mcp_config_file()` is `""`, so the profile that declares it
    owns no MCP document, while the profile that inherits `[agent].type` still
    owns `.claude.json`. Resolving the global agent once above the loop gives
    the overriding profile the other adapter's file — a rollback that restores
    or deletes an artifact the deploy never wrote.
    """
    from lazy_harness.agents.registry import get_agent

    global_mcp = get_agent("claude-code").mcp_config_file()
    targets = set(snapshot_targets(mixed_agents))

    assert home_dir / ".claude-flex" / global_mcp in targets
    assert home_dir / ".claude-lazy" / global_mcp not in targets


def test_the_global_link_follows_the_default_profiles_agent(
    home_dir: Path, mixed_agents: Config
) -> None:
    """`CodexAdapter.global_config_link()` is `None` — a refusal to own one.

    The link belongs to the default profile, so the adapter asked for it is that
    profile's. Asking `[agent].type` snapshots `~/.claude` on a machine whose
    default profile runs an agent that never touches it.
    """
    from lazy_harness.agents.registry import get_agent

    global_link = get_agent("claude-code").global_config_link()
    assert global_link is not None, "the global agent must own a link, or this proves nothing"

    assert global_link not in set(snapshot_targets(mixed_agents))


def test_an_overridden_agent_keeps_snapshot_and_deploy_in_agreement(
    home_dir: Path, mixed_agents: Config, detected_servers: None
) -> None:
    """Both readers invoked for real, under the override, and compared.

    The pre-existing agreement test runs a config with no override, so it passes
    with and without per-profile resolution. This one does not.

    The reverse direction is asserted over the overriding profile's directory
    alone: elsewhere a target may be legitimately absent, and the manifest
    records `kind: "absent"` precisely so a rollback deletes what a first deploy
    created.

    `detected_servers` is what makes that assertion mean the same thing on every
    machine. Both adapters plan their MCP document only when a server is
    detected, so on a developer's laptop with `qmd` installed the deploy writes
    it and on a bare runner it does not — and a target claimed but unwritten is
    indistinguishable from a target claimed by the wrong adapter, which is the
    defect this test exists to catch. An earlier revision carved out
    `.claude.json` in prose and relied on the Codex profile having no
    MCP-dependent target of its own; it acquired one, and the carve-out failed
    on CI while passing locally. Pinning the probe removes the divergence
    instead of describing it.
    """
    overridden = home_dir / ".claude-lazy"
    before = _artifacts(home_dir)
    targets = set(snapshot_targets(mixed_agents))

    _run_deploy(mixed_agents)

    written = _artifacts(home_dir) - before
    assert written, "the deploy wrote nothing; the assertion below would be vacuous"
    assert written <= targets, (
        "the deploy writes artifacts the snapshot would not capture: "
        f"{sorted(str(p) for p in written - targets)}"
    )

    claimed = {p for p in targets if p.parent == overridden}
    assert claimed, "no target under the overriding profile; the assertion below is vacuous"
    assert claimed <= written, (
        "the snapshot claims artifacts of the overriding profile that its own "
        f"agent never writes: {sorted(str(p) for p in claimed - written)}"
    )


def test_a_profile_whose_agent_cannot_plan_contributes_no_config_target(
    home_dir: Path,
) -> None:
    """`config_targets()` is `ConfigPlanner`'s, not every adapter's.

    `NullAdapter` is the shipped sentinel for an agent that plans nothing. Asking
    it for its targets is an `AttributeError` on a duck-typed collaborator, and
    inventing `settings.json` for it would snapshot a path no deploy can write.
    """
    profiles_src = config_dir() / "profiles"
    (profiles_src / "void").mkdir(parents=True)
    (profiles_src / "void" / "CLAUDE.md").write_text("# void\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="void",
            items={"void": ProfileEntry(config_dir=str(home_dir / ".void"), agent="null")},
        ),
        hooks={},
    )

    targets = snapshot_targets(cfg)

    assert targets == [home_dir / ".void" / "CLAUDE.md"]


def test_a_codex_profile_snapshots_the_config_toml_it_merges_into(home_dir: Path) -> None:
    """The widening audited where it matters most: rollback.

    `CodexAdapter` gained `config.toml` as a target, and the snapshot derives its
    manifest from `config_targets()` rather than listing paths of its own — so
    the file the deploy now merges into is the file `--rollback` can restore. A
    rollback that skipped it would leave a half-reverted deploy behind, and
    `config.toml` is the one file here carrying state the user cannot retype.
    """
    profiles_src = config_dir() / "profiles"
    (profiles_src / "cx").mkdir(parents=True)
    (profiles_src / "cx" / "AGENTS.md").write_text("# cx\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="cx",
            items={"cx": ProfileEntry(config_dir=str(home_dir / ".codex"), agent="codex")},
        ),
        hooks={},
    )

    targets = snapshot_targets(cfg)

    assert home_dir / ".codex" / "config.toml" in targets
    assert home_dir / ".codex" / "hooks.json" in targets
