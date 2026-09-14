"""What a builtin is allowed to read off the event it is handed.

`HookEvent` carries every field a payload can name precisely so that no hook
has to reach into `raw` -- and `specs/designs/2026-09-13-multi-agent-harness-design.md`
makes that a gate rather than a convention:

> `raw` exists for adapters, not for hooks, and a test asserts no builtin reads
> it.

The moment one does, the normalisation is a fiction: the hook is back to
reading one agent's field names, it keeps passing every test on Claude Code,
and it finds nothing on the next agent while reporting success.

Read through the AST rather than by substring so that prose about the rule --
including the comments explaining it -- is not mistaken for a violation of it,
and so that an alias (`e = event; e.raw`) is caught rather than missed.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BUILTINS_DIR = Path(__file__).resolve().parents[3] / "src" / "lazy_harness" / "hooks" / "builtins"

#: Adapter-only fields. `ToolCall.raw_input` is the same escape hatch one level
#: down: a builtin reading it has skipped the operation normalisation entirely.
_ADAPTER_ONLY = {"raw", "raw_input"}


def _attribute_reads(source: str) -> set[str]:
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr in _ADAPTER_ONLY
    }


def test_no_builtin_reads_an_adapter_only_field() -> None:
    offenders = {
        path.name: sorted(found)
        for path in sorted(_BUILTINS_DIR.glob("*.py"))
        if (found := _attribute_reads(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"adapter-only fields read by a builtin: {offenders}"


def test_the_gate_sees_an_adapter_only_read() -> None:
    """The check itself, against a module that does the thing it forbids.

    Without this the test above passes just as happily on a walker that never
    matches anything, which is the failure mode a prohibition test has.
    """
    assert _attribute_reads("def main(event):\n    return event.raw\n") == {"raw"}
    assert _attribute_reads("def main(e):\n    return e.tool.raw_input\n") == {"raw_input"}
    assert _attribute_reads("# event.raw is for adapters\nx = 1\n") == set()
