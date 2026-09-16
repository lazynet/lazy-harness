"""One side of the F8 gate's measurement: a payload in, a rendered `ToolCall` out.

The gate itself is `translation-gate.sh`; this file is the thing it points at, and
the reason the pointing is indirect. `translation-gate.sh $1` takes a TRANSLATOR
COMMAND exactly the way `isolation-gate.sh $1` takes an `lh` binary, so the
control fixtures can substitute a different adapter pair without editing a line
of shipped code. `--codex-map` is what those fixtures vary.

PROTOCOL. One record per line on stdin, tab-separated:

    <hook>\t<operation>\t<agent>\t<payload json>

`<agent>` is `claude-code`, `codex`, or `codex-blobless` — the last being the
shipped Codex side fed a patch blob with no file section, which is the case the
parser must abstain on.

One record per line on stdout, tab-separated, in the order received:

    <hook>\t<operation>\t<agent>\t<native_name>\t<operation|NONE>\t<n edits>\t<n reads>

The four rendered fields are the four the gate compares. They are rendered rather
than pickled because the gate is a shell script and because a count is the whole
question for `edits` and `reads`: a builtin iterating `tool.edits` does not care
which paths came back, it cares whether the loop body runs at all.

WHAT THIS MEASURES, AND WHAT IT DOES NOT. Both sides are Python objects — the
shipped `ClaudeCodeAdapter` and the shipped `CodexAdapter`. The `codex` binary is
never invoked. That is a real limit and it is deliberate: this gate asserts which
builtins go inert ACROSS THE SHIPPED ADAPTER PAIR, which is fully determined by
those two objects. A gate asserting what Codex's real wire dialect IS would need
the binary, and is still owed — see the header of `translation-gate.sh`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lazy_harness.agents.base import FileEdit, Operation, ToolCall
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.agents.codex import CodexAdapter

# The stub maps the control fixtures install in place of `CodexAdapter`'s.
#
# `full` and `operations` differ in ONE thing and it is the entire thesis of this
# gate: both map every tool name to the right `Operation`, and only `full` also
# builds the `edits`/`reads` structures. `operations` is therefore a faithful
# model of somebody "fixing `_TOOL_OPERATIONS`" — and the gate still fails it,
# naming the three builtins that gate on `native_name` and then die iterating
# `tool.edits`. That is the failure mode the backlog entry says will otherwise be
# mistaken for a closed gap.
_FULL_MAP: dict[str, Operation] = {
    "Bash": Operation.RUN_COMMAND,
    "Read": Operation.READ_FILE,
    "Edit": Operation.MODIFY_FILE,
    "Write": Operation.MODIFY_FILE,
    "NotebookEdit": Operation.MODIFY_FILE,
    # Codex's own edit tool, added when the gate started feeding Codex's real
    # dialect. Without it the `operations` stub would fail at the *mapping*
    # step and stop discriminating: the thing it exists to model is a fix that
    # maps everything correctly and builds no structure.
    "apply_patch": Operation.MODIFY_FILE,
}
_BASH_ONLY_MAP: dict[str, Operation] = {"Bash": Operation.RUN_COMMAND}


def _stub_codex_tool(payload: dict, *, mapping: dict[str, Operation], structures: bool) -> ToolCall:
    """`CodexAdapter._parse_tool`, with the tool map and the structures swapped in.

    Deliberately a reimplementation rather than a monkeypatch of the shipped
    adapter: a fixture that reaches into `codex._TOOL_OPERATIONS` would keep
    passing if that name moved, and would then be emulating nothing.
    """
    name = payload.get("tool_name")
    if not isinstance(name, str) or not name:
        raise SystemExit("stub: payload carries no tool_name")
    args = payload.get("tool_input")
    args = args if isinstance(args, dict) else {}
    operation = mapping.get(name)
    # `file_path` only. The stub is deliberately blind to the patch blob: that
    # blindness is what `--codex-map operations` models, and what the shipped
    # adapter no longer has.
    path = args.get("file_path")
    edits: tuple[FileEdit, ...] = ()
    reads: tuple[Path, ...] = ()
    if structures and path:
        if operation is Operation.READ_FILE:
            reads = (Path(str(path)),)
        elif operation is Operation.MODIFY_FILE:
            edits = (FileEdit(path=Path(str(path))),)
    command = args.get("command")
    return ToolCall(
        native_name=name,
        operation=operation,
        command=command if isinstance(command, str) else None,
        reads=reads,
        edits=edits,
        raw_input=args,
    )


def _render(tool: ToolCall | None) -> str:
    if tool is None:
        # Not a degradation the gate can attribute to a field, so it is rendered
        # as its own token rather than as an empty `ToolCall`. The gate treats it
        # as total degradation and says so.
        return "\t".join(("NOTOOL", "NONE", "0", "0"))
    operation = tool.operation.value if tool.operation is not None else "NONE"
    return "\t".join((tool.native_name, operation, str(len(tool.edits)), str(len(tool.reads))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex-map",
        required=True,
        choices=("real", "full", "operations", "bash"),
        help=(
            "which codex-side adapter to translate with: 'real' is the shipped "
            "CodexAdapter; the other three are control stubs."
        ),
    )
    args = parser.parse_args(argv)

    claude = ClaudeCodeAdapter()
    codex = CodexAdapter()

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line:
            continue
        hook, operation, agent, payload_text = line.split("\t", 3)
        payload = json.loads(payload_text)
        if agent == "claude-code":
            # Never stubbed. The defect under measurement is one-sided, and a
            # fixture that moved both sides could not tell translation loss from
            # a fixture bug.
            tool = claude.parse_hook_input("pre_tool_use", payload, profile="f8").tool
        elif agent not in ("codex", "codex-blobless"):
            # `codex-blobless` is the same translator on a payload whose patch
            # blob names no file. It is an agent LABEL rather than a fourth map
            # so the control shims keep varying exactly one thing — the adapter
            # — while the gate varies the payload.
            raise SystemExit(f"unknown agent {agent!r}")
        elif args.codex_map == "real":
            tool = codex.parse_hook_input("pre_tool_use", payload, profile="f8").tool
        elif args.codex_map == "full":
            tool = _stub_codex_tool(payload, mapping=_FULL_MAP, structures=True)
        elif args.codex_map == "operations":
            tool = _stub_codex_tool(payload, mapping=_FULL_MAP, structures=False)
        else:
            tool = _stub_codex_tool(payload, mapping=_BASH_ONLY_MAP, structures=False)
        print("\t".join((hook, operation, agent, _render(tool))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
