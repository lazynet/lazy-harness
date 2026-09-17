"""The shipped guard, driven through the Codex adapter with Codex's own payload.

F9's preflight asserted that its two fixtures are denied, and it asserted it by
importing `pre_tool_use_security` and calling `rule.pattern.search(command)` and
`should_block_path(path)` directly. Those are the denylist primitives. No
payload was ever built, `parse_hook_input` never ran, `main(event)` was never
called and `format_hook_output` never emitted anything — so the check proved
that two strings match two regexes, and the gate then went on to assert that a
*Codex tool call* would be blocked.

That is the repo's own gate read backwards: an artifact is verified by the
system that consumes it, not by the test that wrote it. Everything between the
regex and the wire — the adapter's operation mapping, the patch-blob parser,
the verdict envelope Codex honours — was unverified by the check that licensed
the assertion.

This file is the missing half, and it runs in CI where the gate cannot. Both
fixtures go in as the payloads `codex-cli` 0.154.0 was measured sending
(`specs/designs/codex-evidence.md` §1-§2), through `run_hook` under a profile
declaring `agent = "codex"`, and the verdict is read off what the runner
returns — the same bytes Codex would receive on stdout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.hooks.runner import run_hook

PROFILE = "probe-codex"


@pytest.fixture
def codex_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An `LH_CONFIG_DIR` whose `probe-codex` profile runs the Codex adapter.

    Two profiles, not one: the runner resolves its adapter by profile name, and
    a config with a single profile cannot tell "read the name it was given"
    apart from "took the only one there was" — the resolution defect
    `_adapter_for`'s docstring was written after.
    """
    config_dir = tmp_path / "lh"
    config_dir.mkdir()
    agent_dir = tmp_path / "codex-home"
    (config_dir / "config.toml").write_text(
        "[harness]\n"
        'version = "1"\n\n'
        "[agent]\n"
        'type = "claude-code"\n\n'
        "[profiles]\n"
        'default = "cc"\n\n'
        "[profiles.cc]\n"
        f'config_dir = "{tmp_path / "cc"}"\n'
        "roots = []\n\n"
        f"[profiles.{PROFILE}]\n"
        f'config_dir = "{agent_dir}"\n'
        "roots = []\n"
        'agent = "codex"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))
    return agent_dir


def _decision(payload: dict) -> tuple[str | None, str]:
    """The `permissionDecision` and its reason, read off the runner's stdout.

    Parsed rather than pattern-matched: what Codex receives is a JSON document,
    and a substring check would pass on a document Codex cannot load — which is
    exactly how probe 4's hand-escaped envelope reached Codex invalid and let
    the edit through while looking like a deny.
    """
    output = run_hook("pre-tool-use-security", profile=PROFILE, stdin_text=json.dumps(payload))
    assert output.exit_code == 0, f"exit {output.exit_code}, stderr {output.stderr!r}"
    if not output.stdout:
        return None, ""
    spec = json.loads(output.stdout).get("hookSpecificOutput", {})
    return spec.get("permissionDecision"), spec.get("permissionDecisionReason", "")


def _bash_payload(command: str) -> dict:
    """The shape 0.154.0 sends for a shell call — `tool_name` is `Bash`."""
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "f9",
        "cwd": "/tmp",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _patch_payload(path: str) -> dict:
    """The shape 0.154.0 sends for a native edit: `tool_name` is `apply_patch`
    and `tool_input.command` is a raw patch blob — the *same key* a `Bash` call
    uses, which is why nothing downstream can shortcut on the key name."""
    blob = f"*** Begin Patch\n*** Update File: {path}\n@@\n-seed\n+touched\n*** End Patch"
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "f9",
        "cwd": "/tmp",
        "tool_name": "apply_patch",
        "tool_input": {"command": blob},
    }


def test_the_bash_fixture_is_denied_through_the_codex_adapter(codex_profile: Path) -> None:
    """F9's phase B asserts this exact call is blocked."""
    decision, reason = _decision(_bash_payload("rm -rf /tmp/f9-doomed"))

    assert decision == "deny"
    assert "Recursive delete" in reason


def test_the_native_edit_fixture_is_denied_through_the_codex_adapter(
    codex_profile: Path,
) -> None:
    """The arm that needs the patch blob parsed before the path can be judged —
    two fixes were needed here, not one (`codex-evidence.md` §2)."""
    decision, reason = _decision(_patch_payload("/tmp/f9-work/.env"))

    assert decision == "deny"
    assert ".env" in reason


def test_a_benign_call_is_not_denied(codex_profile: Path) -> None:
    """The negative that makes the two above evidence of the denylist rather
    than of a hook that denies everything it is handed."""
    decision, _ = _decision(_bash_payload("printf hello"))

    assert decision != "deny"


def test_the_deny_envelope_is_the_one_codex_honours(codex_profile: Path) -> None:
    """Probe 4b measured which envelope blocks and probe 4 measured what an
    invalid one does — Codex fails open on an unsupported `permissionDecision`.
    So the field names are the contract, and a renamed key would fail open in
    production while every denylist test stayed green."""
    output = run_hook(
        "pre-tool-use-security", profile=PROFILE, stdin_text=json.dumps(_bash_payload("rm -rf /x"))
    )

    assert output.exit_code == 0, "Codex reads the envelope on stdout; a non-zero exit is not it"
    document = json.loads(output.stdout or "{}")
    assert set(document) == {"hookSpecificOutput"}
    spec = document["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["permissionDecision"] == "deny"
    assert spec["permissionDecisionReason"]


def test_the_guard_writes_its_block_line_under_the_profiles_own_agent_dir(
    codex_profile: Path,
) -> None:
    """The line F9's phase B counts. Landing it under the global agent's dir
    would make every delta read zero and every turn read `never invoked`."""
    _decision(_bash_payload("rm -rf /tmp/f9-doomed"))

    log = (codex_profile / "logs" / "hooks.log").read_text(encoding="utf-8")
    assert "pre-tool-use-security: blocked " in log


# --- the gate must actually use this path ----------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"


def _gate_code() -> str:
    """The gate script with its comments stripped.

    Asserted against the code, not the file: the first spelling of the test
    below passed on the word `run_hook` appearing in a comment that merely
    *described* the runner, which is the same vacuity as a matcher test that
    supplies no matcher.
    """
    text = GATE_SH.read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_preflight_no_longer_reaches_past_the_runner() -> None:
    """The defect itself: a preflight that reads `BLOCK_RULES` proves two
    regexes match two strings and licenses an assertion about a tool call."""
    code = _gate_code()

    assert "BLOCK_RULES" not in code
    assert "should_block_path" not in code


def test_the_preflight_drives_the_shipped_runner() -> None:
    assert "run_hook" in _gate_code()


def test_the_preflight_builds_both_native_payload_shapes() -> None:
    """A preflight that fed only `Bash` would leave the native edit arm — the
    one needing the patch blob parsed — licensed by nothing."""
    code = _gate_code()

    assert "apply_patch" in code
    assert "Begin Patch" in code
