"""Unit tests for post_tool_use_ansible_lint hook."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _payload(path: str, tool: str = "Edit") -> str:
    return json.dumps({"tool_name": tool, "tool_input": {"file_path": path}})


def test_runs_ansible_lint_on_yaml_in_ansible_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    args, kwargs = fake_run.call_args
    assert args[0] == ["ansible-lint", str(target)]
    assert kwargs.get("check") is False
    assert kwargs.get("timeout") == 30

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "syntax-check failure" in out["hookSpecificOutput"]["additionalContext"]


def test_skips_non_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("/abs/foo.py")))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_skips_yaml_outside_ansible_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    target = tmp_path / "docker-compose.yml"
    target.write_text("services: {}\n")

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_emits_nothing_when_lint_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(return_value=subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_exits_zero_when_ansible_lint_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The binary being absent must degrade, not crash the hook chain."""
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError))
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0


def test_exits_zero_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    (tmp_path / "ansible.cfg").write_text("[defaults]\n")
    target = tmp_path / "site.yaml"
    target.write_text("- hosts: all\n")

    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="ansible-lint", timeout=30)),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload(str(target))))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0


def test_exits_zero_on_malformed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
