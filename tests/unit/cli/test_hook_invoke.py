"""`lh hook <name>` — the stable entry point settings.json points at.

Its docstring has always said "Called from settings.json by Claude Code". Until
now nothing called it, and it crashed on the first line that used the registry:
`_BUILTIN_HOOKS` holds `BuiltinHookSpec` records, and the code passed one to
`importlib.import_module` as though it were a module path.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from lazy_harness.cli.main import cli


def test_invoking_a_builtin_hook_by_name_runs_it() -> None:
    result = CliRunner().invoke(cli, ["hook", "pre-compact"], input="{}")

    assert result.exit_code == 0, result.output
    assert "startswith" not in result.output, "the registry holds specs, not module paths"
    assert "Traceback" not in result.output


def test_an_unknown_hook_name_is_reported_and_exits_zero() -> None:
    """A hook that fails must never bubble up to the agent."""
    result = CliRunner().invoke(cli, ["hook", "no-such-hook"], input="{}")

    assert result.exit_code == 0
    assert "Unknown hook" in result.output


def test_an_unexpected_error_inside_a_hook_still_exits_zero(monkeypatch) -> None:
    """The guard covers anything, not one exception type it was written for.

    It used to be a bare `except ImportError` around `importlib.import_module`
    in this command, and the registry type confusion this file exists for
    escaped it as a traceback. The command no longer imports anything — every
    builtin goes through `run_hook` — so the guard is the runner's, and this
    breaks the module load it makes to prove the same property there.
    """
    from lazy_harness.hooks import runner

    def boom(_module_path: str):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(runner, "_load_main", boom)

    result = CliRunner().invoke(cli, ["hook", "pre-compact"], input="{}")

    assert result.exit_code == 0, result.output
    assert "kaboom" in result.output


def test_every_registered_builtin_can_be_invoked_by_name() -> None:
    """The names deploy writes into settings.json are exactly these."""
    from lazy_harness.hooks.loader import list_builtin_hooks

    for name in list_builtin_hooks():
        result = CliRunner().invoke(cli, ["hook", name], input="{}")
        assert result.exit_code == 0, f"{name}: {result.output}"
        assert "Traceback" not in result.output, f"{name}: {result.output}"


def test_a_codex_caller_with_no_codex_profile_is_refused_on_exit_2(tmp_path, monkeypatch) -> None:
    """The refusal the unknown-profile fallback gives a Codex caller, byte for byte.

    Exit 2, nothing on stdout, the reason on stderr is the shape `codex-cli
    0.155.1` was run against on 2026-09-24 (`specs/designs/codex-evidence.md`
    §8): with this `lh hook` invocation as its `PreToolUse` hook, Codex did not
    run `touch marker.txt` and its router logged `Command blocked by PreToolUse
    hook: <stderr>`. The command is benign on purpose, so only the fallback's
    refusal -- never the builtin's own deny -- can produce the exit 2.
    """
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[profiles]\ndefault = "claude-probe"\n\n'
        '[profiles.claude-probe]\nidentity = "probe"\n'
        f'config_dir = "{tmp_path / "claude-probe"}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    payload = {
        "session_id": "s1",
        "turn_id": "01a0d416-88f7-73d3-b568-24ba46008afd",
        "cwd": str(tmp_path),
        "hook_event_name": "PreToolUse",
        "model": "gpt-6-sol",
        "permission_mode": "bypassPermissions",
        "tool_name": "Bash",
        "tool_input": {"command": "touch marker.txt"},
        "tool_use_id": "u1",
    }

    result = CliRunner().invoke(
        cli,
        ["hook", "pre-tool-use-security", "--profile", "no-such-profile"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "pre-tool-use-security" in result.stderr
    assert "no-such-profile" in result.stderr
    assert "codex caller" in result.stderr
