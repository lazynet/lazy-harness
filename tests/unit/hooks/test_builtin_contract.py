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


def _get_agent_calls(source: str) -> list[int]:
    """Line numbers of every `get_agent(...)` call in one module.

    Matched on the *call* rather than on its argument. A grep for
    `get_agent("claude-code")` missed the sites spelled
    `get_agent(cfg.agent.type if cfg is not None else "claude-code")` --
    `engram_persist.py` and `pre_compact.py` -- so the count would have depended
    on how the next one was written. Both call shapes are matched, bare and
    attribute-qualified, because `registry.get_agent(...)` is the same global
    resolution one import away.

    No total is quoted here on purpose. The plan this came from says "seven of
    the ten", which does not add up with the two it then names, and the sites
    were removed across PRs #314-#327 rather than in one diff, so the figure is
    not auditable from any one tree. What is auditable is the answer this test
    gives today, and it is zero.
    """
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", None) == "get_agent"
            or getattr(node.func, "attr", None) == "get_agent"
        )
    )


def test_no_builtin_resolves_its_agent_globally() -> None:
    """A hook's agent comes from the profile it was invoked with, or from nowhere.

    `get_agent(<literal>)` answers the machine's global `[agent].type`, which is
    a different question from "which agent does this profile run". A hook that
    asks it writes its log, its cursor and its session export under whichever
    agent the global key happens to name -- another profile's directory, live.
    `_shared.agent_dir_for(cfg, profile)` is the one importable answer, and
    `_shared.py` is excluded here because it *is* that helper. The exclusion is
    the whole file and covers **two** call sites, not one: `agent_dir_for`'s
    documented no-config degradation, and `profile_name`'s read of
    `cfg.agent.type` to learn which environment variable names the config dir —
    that one resolves globally by construction, because answering "which profile
    is this" is what it is for, and it has no profile to be given.
    """
    offenders = {
        path.name: lines
        for path in sorted(_BUILTINS_DIR.glob("*.py"))
        if path.name != "_shared.py"
        and (lines := _get_agent_calls(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"builtins resolving an agent without a profile: {offenders}"


def test_the_gate_sees_a_global_resolution_in_either_spelling() -> None:
    """The gate above passes on a clean tree, so its mechanism is proved here.

    Both spellings, because the bare-name check alone is what an earlier draft
    shipped and it is blind to the attribute form -- a builtin importing the
    module instead of the name would slip past a gate that still reported green.
    """
    assert _get_agent_calls('get_agent("claude-code")\n') == [1]
    assert _get_agent_calls("registry.get_agent(cfg.agent.type)\n") == [1]
    assert _get_agent_calls("# get_agent('claude-code') in a comment\n") == []
    assert _get_agent_calls('"""get_agent(\'claude-code\') in prose."""\n') == []
