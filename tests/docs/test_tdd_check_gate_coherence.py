"""Every surface that enumerates the pre-commit gate enumerates all of it.

`.claude/commands/tdd-check.md` is the gate. Five other surfaces describe it —
`CLAUDE.md` mandates it, `CONTRIBUTING.md` spells it out for contributors, the
PR template asks a human to tick it off, CI enforces it, and `docs/roadmap.md`
names it as the floor Theme 1 builds on — and each one is a separate place to
forget a check.

A gate that only runs locally is a convention, not a gate: the next PR that
never runs `/tdd-check` reintroduces whatever it was meant to catch. So the
enforcement surfaces are covered here too, not just the prose.

Everything is derived from the command's own numbered headings rather than
written down again, so adding a fifth check fails this test in every surface
that has not caught up. `specs/designs/` and `specs/adrs/` are deliberately out
of scope for the same reason `test_uv_frozen_coherence.py` excludes them: they
record what was decided and run at the time, and editing them to satisfy a
present-day rule would be the opposite of a record.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TDD_CHECK = REPO_ROOT / ".claude/commands/tdd-check.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
PR_TEMPLATE = REPO_ROOT / ".github/PULL_REQUEST_TEMPLATE.md"
TESTS_WORKFLOW = REPO_ROOT / ".github/workflows/tests.yml"
ROADMAP = REPO_ROOT / "docs/roadmap.md"

_CHECK_HEADING = re.compile(r"^## (?P<n>\d+)\. (?P<title>.+)$", re.MULTILINE)

# The command each heading names, as a backticked tail of the title.
_HEADING_COMMAND = re.compile(r"`(?P<cmd>uv run --frozen[^`]*)`")

# Only the counts the rules could plausibly carry; an unmapped word should read
# as a parse failure rather than silently scoring zero.
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

_CLAUDE_MD_COUNT = re.compile(
    r"`/tdd-check` passes before every commit\*\*, all (?P<word>\w+) checks",
)
_CONTRIBUTING_COUNT = re.compile(r"All (?P<word>\w+) must pass with pristine output")

# `uv run` flags that swallow the token after them, so stripping the runner
# prefix does not eat the tool name.
_VALUE_FLAGS = {"--group", "--python"}

# Paths the gate commands pass to their tools. Prose naming the check names the
# tool and its mode, not the trees it is pointed at.
_PATH_ARGS = {"src", "tests", "."}

# The one roadmap sentence that enumerates the gate. Anchored rather than
# searched for across the page: the roadmap names the gate twice, so a
# whole-file grep is satisfied by the *other* mention and a stale enumeration
# here survives it — measured, by mutating this line and watching the test pass.
_ROADMAP_GATE = re.compile(r"^The pre-commit gate defined in .+?\.$", re.MULTILINE | re.DOTALL)


def _gate_checks() -> list[str]:
    """The numbered check titles `/tdd-check` declares, in order."""
    return [m.group("title") for m in _CHECK_HEADING.finditer(TDD_CHECK.read_text())]


def _gate_commands() -> list[str]:
    """The full `uv run --frozen …` command each numbered check prescribes."""
    commands = []
    for title in _gate_checks():
        match = _HEADING_COMMAND.search(title)
        assert match is not None, f"check heading names no command: {title!r}"
        commands.append(match.group("cmd"))
    return commands


def _tool_invocation(command: str) -> str:
    """The command with its `uv run …` runner prefix stripped.

    CI interpolates `--python ${{ matrix.python-version }}` into the middle of
    the invocation, so the workflow can never contain the command verbatim.
    What both surfaces do share is the tool call at the end.
    """
    tokens = command.split()
    assert tokens[:2] == ["uv", "run"], command
    rest = tokens[2:]
    while rest and rest[0].startswith("--"):
        flag = rest.pop(0)
        if flag in _VALUE_FLAGS and rest:
            rest.pop(0)
    return " ".join(rest)


def _tool_phrase(command: str) -> str:
    """The tool and its mode, with the runner prefix and path arguments gone.

    `uv run --frozen ruff format --check src tests` reduces to
    `ruff format --check`. Prose that names a check names it this way — the
    roadmap says what runs, not which trees it is pointed at — so the phrase is
    derived rather than restated, and a fifth check appears here for free.
    """
    tokens = [t for t in _tool_invocation(command).split() if t not in _PATH_ARGS]
    return " ".join(tokens)


def test_the_gate_headings_are_actually_found() -> None:
    """Guards the parser: a regex that matches nothing would make every
    assertion below vacuously true."""
    checks = _gate_checks()
    assert len(checks) >= 3, checks
    assert len(_gate_commands()) == len(checks)


def test_the_gate_runs_the_formatter() -> None:
    """`ruff check` and `ruff format` are disjoint. Lint rules do not reformat,
    so a repo running only the former drifts until a reformat lands as an
    unreviewable 44-file diff on top of somebody's logic change.
    """
    assert "ruff format --check" in TDD_CHECK.read_text()
    assert any("format" in title.lower() for title in _gate_checks()), _gate_checks()


def test_claude_md_states_the_number_of_checks_the_gate_actually_runs() -> None:
    match = _CLAUDE_MD_COUNT.search(CLAUDE_MD.read_text())
    assert match is not None, "the /tdd-check non-negotiable no longer states a count"
    stated = _NUMBER_WORDS.get(match.group("word"))
    assert stated is not None, f"unmapped count word: {match.group('word')!r}"
    assert stated == len(_gate_checks()), (
        f"CLAUDE.md says {match.group('word')} checks, "
        f"tdd-check.md declares {len(_gate_checks())}: {_gate_checks()}"
    )


def test_contributing_states_the_number_of_checks_the_gate_actually_runs() -> None:
    match = _CONTRIBUTING_COUNT.search(CONTRIBUTING.read_text())
    assert match is not None, "CONTRIBUTING.md no longer states a gate count"
    stated = _NUMBER_WORDS.get(match.group("word"))
    assert stated is not None, f"unmapped count word: {match.group('word')!r}"
    assert stated == len(_gate_checks()), (
        f"CONTRIBUTING.md says {match.group('word')}, tdd-check.md declares {len(_gate_checks())}"
    )


def test_contributing_spells_out_every_gate_command() -> None:
    body = CONTRIBUTING.read_text()
    missing = [cmd for cmd in _gate_commands() if cmd not in body]
    assert not missing, f"CONTRIBUTING.md omits: {missing}"


def test_the_pr_template_asks_about_every_gate_command() -> None:
    body = PR_TEMPLATE.read_text()
    missing = [cmd for cmd in _gate_commands() if cmd not in body]
    assert not missing, f"PULL_REQUEST_TEMPLATE.md omits: {missing}"


def test_ci_enforces_every_gate_command() -> None:
    """The half that makes it a gate rather than a convention.

    A check present in the local command and absent from CI is enforced only
    on contributors who remember to run it.
    """
    body = TESTS_WORKFLOW.read_text()
    missing = [
        invocation
        for invocation in (_tool_invocation(cmd) for cmd in _gate_commands())
        if invocation not in body
    ]
    assert not missing, f"tests.yml runs no step for: {missing}"


def test_the_roadmap_names_every_gate_check() -> None:
    """`docs/roadmap.md` calls the gate the floor every other change builds on.

    It is the one surface of the five that enforces nothing, which is exactly
    why it was the one left uncovered: a stale enumeration here breaks no build
    and contradicts the four that do. It has already gone stale once — the same
    line named `ruff` where the gate runs two distinct ruff checks.
    """
    match = _ROADMAP_GATE.search(ROADMAP.read_text())
    assert match is not None, "docs/roadmap.md no longer defines the pre-commit gate"
    sentence = match.group(0)

    missing = [
        phrase for phrase in (_tool_phrase(c) for c in _gate_commands()) if phrase not in sentence
    ]
    assert not missing, f"the roadmap's gate sentence names no check for: {missing}"
