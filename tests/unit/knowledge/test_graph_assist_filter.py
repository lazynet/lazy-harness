"""Which tool calls are code-symbol searches over the repository.

Spec §3.1 filter rules 3 and 4. A miss here is silence, which is cheap; a false
hit injects graph context into an unrelated grep, which is the noise that made
the upstream nudge ignorable. So every ambiguous case resolves to `None`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.knowledge.graph_assist import identifier, search_target

ROOT = Path("/repo")
CWD = ROOT


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("check_version", "check_version"),
        ("check_version()", "check_version()"),
        ("graphify.check_version", "graphify.check_version"),
        ("'check_version'", "check_version"),
        ('"def check_version"', "check_version"),
        ("class Engine", "Engine"),
        ("function render", "render"),
        ("a.*b", None),
        ("two words", None),
        ("foo|bar", None),
        ("^def x", None),
        ("", None),
        ("9lives", None),
    ],
)
def test_identifier(raw: str, expected: str | None) -> None:
    assert identifier(raw) == expected


def _bash(command: object) -> tuple[str, object]:
    return "Bash", {"command": command}


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        (*_bash("grep -rn check_version src"), "check_version"),
        (*_bash("rg check_version"), "check_version"),
        (*_bash("rg -n -e check_version src"), "check_version"),
        (*_bash("rg -t py check_version"), "check_version"),
        (*_bash("rg --type py check_version"), "check_version"),
        (*_bash("rg -n check_version -- src"), "check_version"),
        (*_bash("grep -rn 'def check_version' /repo/src"), "check_version"),
        (*_bash("cd /repo && grep -rn check_version src"), "check_version"),
        (*_bash("grep check_version src && grep other src"), "check_version"),
        (*_bash("/usr/bin/grep -r check_version ."), "check_version"),
        (*_bash("grep -r check_version src | head -5"), "check_version"),
        (*_bash("cat x | grep check_version"), None),
        (*_bash("grep foo /var/log/x"), None),
        (*_bash("grep -r foo ../other"), None),
        (*_bash("grep 'a.*b' src"), None),
        (*_bash('grep "two words" src'), None),
        (*_bash("git grep check_version"), None),
        (*_bash("ls src"), None),
        (*_bash("grep"), None),
        (*_bash("grep 'unterminated"), None),
        (*_bash(None), None),
        (*_bash(42), None),
        ("Grep", {"pattern": "check_version"}, "check_version"),
        ("Grep", {"pattern": "check_version", "path": "/repo/src"}, "check_version"),
        ("Grep", {"pattern": "check_version", "path": "src"}, "check_version"),
        ("Grep", {"pattern": "check_version", "path": "/elsewhere"}, None),
        ("Grep", {"pattern": "a.*b"}, None),
        ("Grep", {"pattern": 7}, None),
        ("Grep", None, None),
        ("Grep", ["pattern"], None),
        ("Read", {"file_path": "/repo/x"}, None),
    ],
)
def test_search_target(tool: str, tool_input: object, expected: str | None) -> None:
    assert search_target(tool, tool_input, ROOT, CWD) == expected


@pytest.mark.parametrize(
    ("tool", "tool_input", "expected"),
    [
        ("Grep", {"pattern": "x"}, True),
        ("Grep", None, True),
        ("Bash", {"command": "grep -r foo src"}, True),
        ("Bash", {"command": "cat x | rg foo"}, True),
        ("Bash", {"command": "ls src && git status"}, False),
        ("Bash", {"command": "echo grep"}, False),
        ("Bash", {"command": "'unterminated"}, False),
        ("Bash", None, False),
        ("Read", {"file_path": "x"}, False),
    ],
)
def test_is_search_call(tool: str, tool_input: object, expected: bool) -> None:
    from lazy_harness.knowledge.graph_assist import is_search_call

    assert is_search_call(tool, tool_input) is expected
