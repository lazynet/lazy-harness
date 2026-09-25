"""Operation-scoped security policy; command strings are never executed."""

import tomllib
from pathlib import Path

import pytest

from lazy_harness.agents.base import Verdict
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.hooks.builtins import pre_tool_use_security as security


@pytest.mark.parametrize(
    "command",
    [
        "git -C .worktrees/demo reset --hard",
        "rm -rf /tmp/lh-safe /example/valuable",
        "git push origin main --force",
        "git push origin -f main",
        "git -C 'repo with spaces' push origin main --force",
        "git reset HEAD --hard",
        "git push origin --force-with-lease main --force",
        "git push origin main -vf",
        "git push origin +main",
        "git\\\n push origin main --force",
        "rm /example/valuable -rf",
        "rm '-rf' /example/valuable",
        "'rm' -rf /example/valuable",
        "rm -rf /tmp/lh-safe | git reset --hard",
    ],
)
def test_legacy_regexes_cannot_rescue_operations(command: str) -> None:
    assert security.should_block(command, [r"\.worktrees/", "rm -rf /tmp/", ".*"]) is not None


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf scratch/a",
        "rm -f -R scratch/a scratch/b",
        "rm --force --recursive -- scratch/a",
        "rm\t-rf\t'scratch/with spaces'",
        "rm -rf './scratch/a'",
        "/bin/rm -rf scratch/a",
        "rm scratch/a -rf",
        "rm '-rf' scratch/a",
    ],
)
def test_explicit_cleanup_preserves_supported_paths(tmp_path: Path, command: str) -> None:
    assert (
        security.should_block(
            command, [], recursive_delete_roots=[tmp_path / "scratch"], cwd=tmp_path
        )
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf scratch/a outside",
        "rm -rf scratch",
        "rm -rf scratch/../outside",
        "rm -rf scratch-other/a",
        "rm -rf scratch/a; git reset --hard",
        "rm -rf scratch/a | cat .env",
        "rm -rf scratch/a && rm -rf outside",
        "rm -rf scratch/a\nrm -rf outside",
        "rm -rf scratch/a & rm -rf outside",
        "cd elsewhere && rm -rf scratch/a",
        "rm -rf scratch/*",
        "rm -rf scratch/$name",
        'rm -rf "scratch/$(echo outside)"',
        "rm -rf scratch/`echo outside`",
        "rm -rf scratch/{a,b}",
        "rm -rf scratch/a > outside",
        "echo scratch/a | xargs rm -rf",
        "sudo rm -rf scratch/a",
        "sh -c 'rm -rf scratch/a'",
        "rm -rf scratch/a --unknown",
        "rm -rf 'scratch/a",
        "rm -rf",
        "git -C scratch/a reset --hard",
    ],
)
def test_cleanup_refuses_ambiguous_or_out_of_scope_commands(tmp_path: Path, command: str) -> None:
    assert (
        security.should_block(
            command, [], recursive_delete_roots=[tmp_path / "scratch"], cwd=tmp_path
        )
        is not None
    )


def test_cleanup_resolves_symlinks_at_both_ends(tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    for operand in ("scratch/escape/outside", "scratch/escape/../outside"):
        assert (
            security.should_block(
                f"rm -rf {operand}", [], recursive_delete_roots=[alias], cwd=tmp_path
            )
            is not None
        )
    assert (
        security.should_block("rm -rf alias/child", [], recursive_delete_roots=[root], cwd=tmp_path)
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "example-cli list",
        "/opt/bin/example-cli list",
        "'example-cli' list",
        "env MODE=demo example-cli list",
        "MODE=demo example-cli list",
        "sudo -u nobody example-cli list",
        "command example-cli list",
        "echo ok | example-cli list",
        "echo ok; example-cli list",
        "sh -lc 'example-cli list'",
        "eval 'example-cli list'",
        "eval example-cli list",
        "exam\\\nple-cli list",
        "xargs -n 1 example-cli list",
    ],
)
def test_environment_policy_denies_commands(command: str) -> None:
    decision = security.should_block(command, [".*"], denied_commands=["example-cli"])
    assert decision is not None
    assert decision.rule.category == "policy"


@pytest.mark.parametrize("command", ["echo example-cli", "example-cli-helper list", "ls -la"])
def test_environment_policy_is_opt_in_and_checks_command_position(command: str) -> None:
    assert security.should_block(command, [], denied_commands=["example-cli"]) is None
    assert security.should_block("example-cli list", []) is None


def _event(command: str, cwd: Path):
    return ClaudeCodeAdapter().parse_hook_input(
        "pre_tool_use",
        {"cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": command}},
        profile="",
    )


def test_hook_loads_policy_and_uses_event_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    root = tmp_path / "scratch"
    (tmp_path / "config.toml").write_text(
        f'[hooks.pre_tool_use]\nrecursive_delete_roots = ["{root}"]\n'
        'denied_commands = ["example-cli"]\n'
    )
    assert security.main(_event("rm -rf scratch/a", tmp_path)).verdict is None
    assert security.main(_event("rm -rf scratch/a", tmp_path / "elsewhere")).verdict is Verdict.DENY
    assert security.main(_event("example-cli list", tmp_path)).verdict is Verdict.DENY


def test_existing_size_options_do_not_disable_security_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n[hooks.pre_tool_use]\n'
        "claude_md_max_lines = 200\nclaude_md_max_bytes = 12288\n"
        'denied_commands = ["example-cli"]\n'
    )
    assert security.main(_event("ls", tmp_path)).verdict is None
    decision = security.main(_event("example-cli list", tmp_path))
    assert decision.verdict is Verdict.DENY
    assert "Denied command: example-cli" in decision.reason


def test_hook_honors_shared_parser_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.core.config import ConfigError

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text("[hooks.pre_tool_use]\n")

    def refuse_policy(raw: object) -> dict[str, list[str]]:
        raise ConfigError("denied_commands rejected by shared validator")

    monkeypatch.setattr("lazy_harness.core.config.parse_security_policy", refuse_policy)
    decision = security.main(_event("ls", tmp_path))
    assert decision.verdict is Verdict.DENY
    assert "denied_commands rejected by shared validator" in decision.reason


def test_policy_does_not_load_unrelated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        "[profiles.demo]\nunknown_profile_option = true\n"
        '[hooks.pre_tool_use]\nclaude_md_max_lines = "invalid but unrelated"\n'
        'denied_commands = ["example-cli"]\n'
    )
    assert security.main(_event("ls", tmp_path)).verdict is None
    decision = security.main(_event("example-cli list", tmp_path))
    assert decision.verdict is Verdict.DENY
    assert "Denied command: example-cli" in decision.reason


@pytest.mark.parametrize(
    "config,key",
    [
        ("hooks = 1", "hooks"),
        ("[hooks]\npre_tool_use = []", "pre_tool_use"),
        ('[hooks.pre_tool_use]\ndenied_commands = "x"', "denied_commands"),
        ("[hooks.pre_tool_use]\ndenied_commands = [1]", "denied_commands"),
        ('[hooks.pre_tool_use]\ndenied_commands = [".*"]', "denied_commands"),
        (
            '[hooks.pre_tool_use]\nrecursive_delete_roots = ["relative"]',
            "recursive_delete_roots",
        ),
        ('[hooks.pre_tool_use]\nrecursive_delete_roots = ["/"]', "recursive_delete_roots"),
        ('[hooks.pre_tool_use]\nrecursive_delete_roots = ["//"]', "recursive_delete_roots"),
        ('[hooks.pre_tool_use]\nrecursive_delete_roots = ["/tmp/../.."]', "recursive_delete_roots"),
        ('[hooks.pre_tool_use]\ndenied_comands = ["x"]', "denied_comands"),
    ],
)
def test_invalid_policy_fails_closed_with_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str, key: str
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(config)
    decision = security.main(_event("ls", tmp_path))
    assert decision.verdict is Verdict.DENY
    assert key in decision.reason


def test_block_survives_broken_auditing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("lazy_harness.core.config.load_config", lambda *_: 1 / 0)
    assert security.main(_event("rm -rf outside", tmp_path)).verdict is Verdict.DENY


@pytest.mark.parametrize("new_destination", [False, True])
@pytest.mark.parametrize("scripts", ["", 'scripts = ["pre-tool-use-security"]\n', "scripts = []\n"])
def test_policy_survives_full_config_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_destination: bool, scripts: str
) -> None:
    from lazy_harness.core.config import load_config, save_config
    from lazy_harness.deploy.defaults import merge_with_defaults

    source = tmp_path / "source.toml"
    root = tmp_path / "scratch"
    source.write_text(
        f'[harness]\nversion = "1"\n[hooks.pre_tool_use]\n{scripts}'
        "claude_md_max_lines = 200\nclaude_md_max_bytes = 12288\n"
        f'recursive_delete_roots = ["{root}"]\ndenied_commands = ["example-cli"]\n'
    )
    destination = tmp_path / "config.toml" if new_destination else source
    cfg = load_config(source)
    for _ in range(2):
        save_config(cfg, destination)
        cfg = load_config(destination)
        monkeypatch.setattr(security, "config_file", lambda: destination)
        assert security.main(_event("example-cli list", tmp_path)).verdict is Verdict.DENY
        assert security.main(_event("rm -rf scratch/a", tmp_path)).verdict is None
        assert security.main(_event("rm -rf scratch/a outside", tmp_path)).verdict is Verdict.DENY
        saved = tomllib.loads(destination.read_text())["hooks"]["pre_tool_use"]
        assert saved["claude_md_max_lines"] == 200
        assert saved["claude_md_max_bytes"] == 12288
        assert ("scripts" in saved) == bool(scripts)
        effective = merge_with_defaults(cfg.hooks, ClaudeCodeAdapter())["pre_tool_use"]
        assert ("pre-tool-use-security" in effective) == (scripts != "scripts = []\n")
