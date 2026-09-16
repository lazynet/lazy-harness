"""Unit tests for post_tool_use_ansible_lint hook.

In-process, over `main(event) -> HookDecision`. `subprocess.run` is patched
here, which the goldens next door cannot do: they cross a process boundary and
plant a `/bin/sh` stand-in on the pinned PATH instead. Neither requires the real
`ansible-lint`, deliberately — the repo's gate on that is "a bare command name
resolves from ambient `PATH`", so a suite that ran the installed binary would
assert against whatever rule set the machine happened to carry, and one that
skipped when it was missing would cover nothing on CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lazy_harness.agents.base import FileEdit, HookEvent, Operation, ToolCall


def _event(*paths: str, tool: str = "Edit", cwd: Path | None = None) -> HookEvent:
    return HookEvent(
        event="post_tool_use",
        profile="p",
        session_id="s",
        cwd=cwd or Path("/nonexistent"),
        transcript_path=None,
        tool=ToolCall(
            native_name=tool,
            operation=Operation.MODIFY_FILE,
            edits=tuple(FileEdit(path=Path(p)) for p in paths),
        ),
    )


def test_runs_ansible_lint_on_yaml_in_ansible_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    role = tmp_path / "roles" / "web" / "tasks"
    role.mkdir(parents=True)
    target = role / "main.yml"
    target.write_text("- name: noop\n")

    fake_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            [], returncode=2, stdout="syntax-check failure", stderr=""
        )
    )
    monkeypatch.setattr("subprocess.run", fake_run)

    decision = mod.main(_event(str(target)))

    args, kwargs = fake_run.call_args
    assert args[0] == ["ansible-lint", str(target)]
    assert kwargs.get("check") is False
    assert kwargs.get("timeout") == 30
    assert kwargs.get("cwd") == tmp_path

    assert decision.verdict is None
    assert "syntax-check failure" in decision.additional_context


def test_skips_non_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event("/abs/foo.py")).additional_context == ""
    fake_run.assert_not_called()


def test_skips_yaml_outside_ansible_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    target = tmp_path / "docker-compose.yml"
    target.write_text("services: {}\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(str(target))).additional_context == ""
    fake_run.assert_not_called()


def test_emits_nothing_when_lint_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    fake_run = MagicMock(
        return_value=subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    )
    monkeypatch.setattr("subprocess.run", fake_run)

    decision = mod.main(_event(str(target)))

    fake_run.assert_called_once()
    assert decision.additional_context == ""
    assert decision.verdict is None


def test_reports_a_missing_ansible_lint_to_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The binary being absent must degrade, not crash the hook chain — and must be
    visible to the agent, not just to the log, since the log doesn't change behaviour."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError))

    decision = mod.main(_event(str(target)))

    assert "unavailable" in decision.additional_context.lower()
    assert "site.yaml" in decision.additional_context


def test_abstains_on_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-executable ansible-lint on PATH must degrade, not crash the hook chain."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    role = tmp_path / "roles" / "web" / "tasks"
    role.mkdir(parents=True)
    target = role / "main.yml"
    target.write_text("- name: noop\n")

    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=PermissionError))

    decision = mod.main(_event(str(target)))

    assert decision.verdict is None
    assert "PermissionError" in decision.additional_context


def test_reports_a_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="ansible-lint", timeout=30)),
    )

    decision = mod.main(_event(str(target)))

    assert "TimeoutExpired" in decision.additional_context


def test_skips_files_outside_roles_or_playbooks_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-Ansible YAML that merely happens to live under an ansible.cfg (e.g. a
    Traefik or Homepage config committed alongside a playbooks repo) must not lint."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "docker" / "traefik" / "foo.yml"
    target.parent.mkdir(parents=True)
    target.write_text("http: {}\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(str(target))).additional_context == ""
    fake_run.assert_not_called()


def test_skips_vault_encrypted_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ansible-vault-encrypted files are unlintable ciphertext; feeding them to
    ansible-lint produces load-failure noise, not a real finding. The target sits
    inside roles/, so it is in lint scope — only the vault guard can skip it here,
    proving the guard itself works rather than riding on the scope predicate."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "roles" / "web" / "vars" / "vault.yml"
    target.parent.mkdir(parents=True)
    target.write_text("$ANSIBLE_VAULT;1.1;AES256\n66386439653236336462626566\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(str(target))).additional_context == ""
    fake_run.assert_not_called()


def test_skips_group_vars_outside_lint_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """group_vars/ sits outside roles/, playbooks/, and the Ansible root, so it is
    excluded by the scope predicate even for ordinary, unencrypted content."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "group_vars" / "all" / "vars.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("some_var: 1\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(str(target))).additional_context == ""
    fake_run.assert_not_called()


def test_abstains_when_the_event_carries_no_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ToolCall` is `None` for a payload naming no tool, which is every
    non-tool event — and `lh hooks run post_tool_use` hands over `{}`."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    event = HookEvent(
        event="post_tool_use",
        profile="p",
        session_id="s",
        cwd=Path("/nonexistent"),
        transcript_path=None,
    )

    assert mod.main(event).additional_context == ""
    fake_run.assert_not_called()


def test_abstains_when_the_tool_call_names_no_edited_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """`edits` is empty for a `tool_input` carrying no path at all."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event()).additional_context == ""
    fake_run.assert_not_called()


# --- trap 3: the operation is wider than the tool set -----------------------


def test_a_notebook_edit_naming_a_yaml_path_is_not_linted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The widening this migration refuses to let ride in as a normalisation.

    `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE` beside `Edit` and
    `Write` (`claude_code.py:97`), and `_FILE_PATH_KEYS` reads `notebook_path`
    into the same `FileEdit.path` (`:99`). So replacing the tool-name gate with
    `operation is Operation.MODIFY_FILE` would make this hook act on notebooks
    for the first time. The suffix re-check does not save it: nothing in
    `ToolCall` makes a notebook path end `.ipynb`, and this one does not.

    The narrowing chosen is the native name against `INSPECTED_TOOLS` — the
    pre-migration gate, unchanged — rather than an `.ipynb` exclusion, which
    would not cover this case at all. Deleting it turns this red.
    """
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    role = tmp_path / "roles" / "web" / "tasks"
    role.mkdir(parents=True)
    target = role / "main.yml"
    target.write_text("- name: noop\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    decision = mod.main(_event(str(target), tool="NotebookEdit"))

    assert decision.additional_context == ""
    fake_run.assert_not_called()


def test_the_inspected_tools_are_a_strict_subset_of_the_declared_operation() -> None:
    """The gap trap 3 lives in, asserted rather than described in a comment.

    If `_TOOL_OPERATIONS` ever stopped mapping a tool outside `INSPECTED_TOOLS`
    to `MODIFY_FILE`, the narrowing above would become redundant and this test
    is where that is noticed — rather than the narrowing quietly outliving its
    reason.
    """
    from lazy_harness.agents.claude_code import _TOOL_OPERATIONS
    from lazy_harness.hooks.builtins.post_tool_use_ansible_lint import INSPECTED_TOOLS

    modify = {t for t, op in _TOOL_OPERATIONS.items() if op is Operation.MODIFY_FILE}

    assert INSPECTED_TOOLS < modify, (
        f"INSPECTED_TOOLS={sorted(INSPECTED_TOOLS)} no longer narrows MODIFY_FILE={sorted(modify)}"
    )


def test_every_edit_in_one_tool_call_is_linted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`edits` is plural because other agents' patch tools are.

    Claude Code yields at most one, so this changes no byte of the goldens; it
    is what stops `edits[0]` from becoming the singular `file_path` assumption
    the `ToolCall` docstring exists to warn about.
    """
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    role = tmp_path / "roles" / "web" / "tasks"
    role.mkdir(parents=True)
    first = role / "main.yml"
    second = role / "install.yml"
    first.write_text("- name: noop\n")
    second.write_text("- name: noop\n")

    fake_run = MagicMock(
        return_value=subprocess.CompletedProcess(
            [], returncode=2, stdout="fqcn[action-core] violation", stderr=""
        )
    )
    monkeypatch.setattr("subprocess.run", fake_run)

    decision = mod.main(_event(str(first), str(second)))

    linted = [call.args[0][1] for call in fake_run.call_args_list]
    assert linted == [str(first), str(second)]
    assert decision.additional_context.count("fqcn[action-core] violation") == 2


# --- the registry declaration ----------------------------------------------


def test_the_registry_declares_what_this_hook_acts_on() -> None:
    """Declared, not inferred from the `Edit|Write` matcher, which names Claude
    Code's own tool names. Another agent's translated matcher still has to be
    asked whether the operation exists there."""
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    spec = _BUILTIN_HOOKS["post-tool-use-ansible-lint"]

    assert spec.event == "post_tool_use"
    assert spec.operations == frozenset({Operation.MODIFY_FILE})
    assert spec.blocking is False


def test_this_hook_declares_no_transcript_signal() -> None:
    """It reads an edited file and a linter's output, never the transcript.

    Declaring one would make `deploy` refuse to install it on an agent whose
    reader cannot supply a signal the hook never touches.
    """
    from lazy_harness.hooks.loader import builtin_signals

    assert builtin_signals("post-tool-use-ansible-lint") == frozenset()
