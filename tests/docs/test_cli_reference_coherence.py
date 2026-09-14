"""Deterministic coherence check: every doc under docs/** vs the click command tree.

Direction is doc ⊆ code (lax): every `lh <command> [subcommand]` named anywhere
under docs/ must resolve against `lazy_harness.cli.main.cli`. The reverse is not
checked — plenty of subcommands are intentionally undocumented.

Scoped to all of docs/**, not just docs/reference/cli.md: the design spec's own
motivating example of deterministic drift (`docs/getting-started/first-run.md`
naming `lh profile deploy` / `lh profile ls`, neither of which exists) lives
outside the CLI reference page. A scan limited to cli.md would ship green while
that exemplar drift stayed uncaught.

Doc anchors this test depends on (a doc restructure that breaks these should fail
loudly, not silently extract nothing):
- fenced ```bash code blocks whose lines start with "lh "
- inline code spans of the shape `` `lh ...` ``

Unmarked prose is out of scope on purpose: `lh deploy --dry-run` written with
neither a fence nor backticks is not extracted, and no scan here sees it. Both
anchors require the author to have marked the text up as a command, which is
what makes the extraction unambiguous — over running prose the extractor would
have to guess where the invocation ends, and would read "run lh deploy first" as
a command taking the argument `first`. Marking commands up is already the house
style across docs/, so an unmarked one is a docs-style miss rather than a hole
this file should paper over with a heuristic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import click

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"

_FENCED_BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)
_INLINE_LH_SPAN = re.compile(r"`(lh [^`\n]+)`")
_COMMAND_TOKEN_SHAPE = re.compile(r"^[a-z][a-z-]*$")


def _extract_lh_invocations(doc_text: str) -> list[str]:
    """Pull every `lh ...` invocation out of fenced ```bash blocks and inline spans.

    Conservative on purpose: only lines that literally start with "lh " inside a
    ```bash block, and inline code spans that literally start with "lh ", are
    considered. Anything else (prose, other languages, JSON payloads) is ignored.
    """
    invocations: list[str] = []

    for block in _FENCED_BASH_BLOCK.findall(doc_text):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("lh "):
                invocations.append(line)

    invocations.extend(span.strip() for span in _INLINE_LH_SPAN.findall(doc_text))

    return invocations


class _Walk(NamedTuple):
    """Where a doc invocation's tokens land in the click tree.

    One traversal, consumed by both directions of the scan: the command check
    asks whether the walk broke on a name that does not exist, the flag check
    asks which command the remaining tokens were written against. Two walks
    would be two subtly different answers to the same question.
    """

    node: click.Command
    path: list[str]
    rest: list[str]
    stop: str


def _walk_command_path(root: click.Group, tokens: list[str]) -> _Walk:
    """Descend through click.Group nodes for as long as the tokens name one.

    `stop` records why the descent ended, which is the whole point: `unknown`
    means a doc named a subcommand that does not exist, while `placeholder`,
    `shape` and `comment` mean the tokens stopped being classifiable at all.
    """
    node: click.Command = root
    path: list[str] = []
    for index, token in enumerate(tokens):
        if not isinstance(node, click.Group):
            return _Walk(node, path, tokens[index:], "leaf")
        if token.startswith("-"):
            return _Walk(node, path, tokens[index:], "flag")
        if token.startswith("#"):
            return _Walk(node, path, tokens[index:], "comment")
        if "<" in token or ">" in token:
            # Placeholder syntax (e.g. `lh <command> --help`), not a real
            # subcommand name — cannot confidently classify, so skip it.
            return _Walk(node, path, tokens[index:], "placeholder")
        if not _COMMAND_TOKEN_SHAPE.match(token):
            # Catch-all conservatism for shapes the checks above don't name
            # explicitly: entry-point syntax (`lh = "pkg:cli"`), slash
            # shorthand (`lh profile add/remove`), and anything else that
            # isn't a plausible lowercase-hyphenated subcommand name.
            return _Walk(node, path, tokens[index:], "shape")
        child = node.commands.get(token)
        if child is None:
            return _Walk(node, path, tokens[index:], "unknown")
        node = child
        path.append(token)
    return _Walk(node, path, [], "exhausted")


def find_missing_lh_invocations(root: click.Group, doc_text: str) -> list[str]:
    """Return every extracted invocation whose command path does not exist.

    Walks tokens through the click tree starting at `root`, descending through
    click.Group nodes only. Stops as soon as a leaf Command is reached (the
    remaining tokens are arguments/flags, not subcommands) or a token looks like
    a flag/comment. A missing subcommand along the walked path is a failure.
    """
    return [
        invocation
        for invocation in _extract_lh_invocations(doc_text)
        if _walk_command_path(root, invocation.split()[1:]).stop == "unknown"
    ]


def find_missing_lh_invocations_in_docs(root: click.Group, docs_dir: Path) -> dict[str, list[str]]:
    """Run `find_missing_lh_invocations` over every markdown file under `docs_dir`.

    Returns `{relative_path: [bad_invocation, ...]}` for files with at least
    one unresolved invocation; files with none are omitted.
    """
    result: dict[str, list[str]] = {}
    for path in sorted(docs_dir.rglob("*.md")):
        doc_text = path.read_text(encoding="utf-8")
        missing = find_missing_lh_invocations(root, doc_text)
        if missing:
            result[str(path.relative_to(docs_dir.parent))] = missing
    return result


def test_self_test_extractor_flags_only_the_bad_invocation() -> None:
    """Feed a tiny doc fragment with one real and one fake invocation.

    Proves the checker can fail before we trust it passing against the real doc.
    """

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.group("foo")
    def foo_group() -> None:
        pass

    @foo_group.command("bar")
    def bar_cmd() -> None:
        pass

    doc = """
Some prose.

```bash
lh foo bar
```

Also see `lh foo baz` for the broken one.
"""

    missing = find_missing_lh_invocations(fake_cli, doc)

    assert missing == ["lh foo baz"]


def test_flag_and_comment_tokens_stop_the_walk_without_a_false_positive() -> None:
    """A flag or a trailing comment after a real subcommand must not be treated
    as a missing sub-subcommand — `lh foo --bar` and `lh foo # note` should both
    resolve cleanly once `foo` itself is found."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    def foo_cmd() -> None:
        pass

    doc = """
```bash
lh foo --bar
lh foo # a trailing comment
```
"""

    assert find_missing_lh_invocations(fake_cli, doc) == []


def test_placeholder_tokens_are_not_guessed_as_missing() -> None:
    """`<command>`-shaped placeholders are template syntax, not real subcommand
    names, and must not be flagged just because they don't resolve."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    def foo_cmd() -> None:
        pass

    doc = "Run `lh foo <target>` for any target."

    assert find_missing_lh_invocations(fake_cli, doc) == []


def test_leaf_command_stop_does_not_descend_into_arguments() -> None:
    """Once a leaf Command is reached, remaining tokens are positional
    arguments, not subcommands — even when they are shaped like a plausible
    subcommand name. Also guards against an AttributeError: a leaf Command has
    no `.commands` dict to walk into."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("leafcmd")
    def leaf_cmd() -> None:
        pass

    doc = "See `lh leafcmd something-real-looking-but-actually-an-argument`."

    assert find_missing_lh_invocations(fake_cli, doc) == []


def test_non_command_token_shapes_are_not_guessed_as_missing() -> None:
    """`lh = "..."` (a pyproject entry-point declaration) and slash-shorthand
    subcommand mentions are not real invocations. Their tokens are not
    command-shaped, so they must be skipped rather than guessed as missing.
    """

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.group("profile")
    def profile_group() -> None:
        pass

    @profile_group.command("add")
    def add_cmd() -> None:
        pass

    doc = """
See `lh = "lazy_harness.cli.main:cli"` in pyproject.toml.

Slash shorthand: `lh profile add/remove`.
"""

    missing = find_missing_lh_invocations(fake_cli, doc)

    assert missing == []


def test_cli_reference_commands_exist_in_the_click_tree() -> None:
    from lazy_harness.cli.main import cli

    doc_files = sorted(DOCS_DIR.rglob("*.md"))
    total_invocations = sum(
        len(_extract_lh_invocations(path.read_text(encoding="utf-8"))) for path in doc_files
    )

    # Guards the anchor set: if docs/** is restructured so fenced ```bash blocks
    # and inline `lh ...` spans mostly stop matching, this must fail loudly
    # rather than silently checking almost nothing. Proportionate to the doc
    # tree's real, measured count (245 at the time of writing) — not the old
    # arbitrary ">10" against ~100, which would have missed an anchor shape
    # break that dropped 89 out of every 100 invocations. Some headroom is
    # kept because normal prose edits nudge this count by a handful over time;
    # it is not the fixed, enumerable anchor list the config test guards
    # exactly.
    assert total_invocations > 200

    missing = find_missing_lh_invocations_in_docs(cli, DOCS_DIR)
    assert missing == {}


# The lax scan above catches a doc naming a command that does not exist. It is
# blind to the opposite drift — a command that ships and is documented nowhere —
# which is how `lh profile sync-claude-md` and `lh memory rightsize` reached
# users with no reference entry. This half closes that direction, and only for
# docs/reference/cli.md, which is the page that claims to be exhaustive.

CLI_MD = Path(__file__).parent.parent.parent / "docs" / "reference" / "cli.md"

# Commands deliberately absent from the reference page. Each needs a reason:
# an undocumented command is a bug unless someone decided otherwise.
_UNDOCUMENTED_ON_PURPOSE: dict[str, str] = {
    # Invoked by the agent through settings.json, never typed by a user. Its
    # per-hook behaviour is documented in docs/how/hooks.md instead.
    "lh hook": "agent-invoked dispatcher; documented per hook in docs/how/hooks.md",
}


def documented_command_paths(root: click.Group) -> list[str]:
    """Every leaf command path in the click tree, as `lh a b` strings."""
    paths: list[str] = []

    def walk(node: click.Command, prefix: list[str]) -> None:
        if isinstance(node, click.Group) and node.commands:
            for name, child in sorted(node.commands.items()):
                walk(child, [*prefix, name])
        else:
            paths.append(" ".join(["lh", *prefix]))

    walk(root, [])
    return paths


def find_undocumented_commands(root: click.Group, doc_text: str) -> list[str]:
    """Return every leaf command path the reference page never names."""
    return [
        path
        for path in documented_command_paths(root)
        if path not in _UNDOCUMENTED_ON_PURPOSE and path not in doc_text
    ]


def test_self_test_reverse_extractor_flags_the_undocumented_command() -> None:
    """Guards the anchor: prove it can fail before trusting it to pass."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.group("foo")
    def foo_group() -> None:
        pass

    @foo_group.command("bar")
    def bar_cmd() -> None:
        pass

    @foo_group.command("baz")
    def baz_cmd() -> None:
        pass

    assert find_undocumented_commands(fake_cli, "Only `lh foo bar` is here.") == ["lh foo baz"]


def test_cli_reference_documents_every_shipped_command() -> None:
    from lazy_harness.cli.main import cli

    undocumented = find_undocumented_commands(cli, CLI_MD.read_text(encoding="utf-8"))

    assert undocumented == [], (
        "docs/reference/cli.md names none of these shipped commands: "
        f"{undocumented}. Document them, or add an entry to "
        "_UNDOCUMENTED_ON_PURPOSE with the reason."
    )


# Both scans above walk tokens only far enough to name a command, then stop at
# the first token starting with `-`. That blindness is what let `lh deploy
# --dry-run` live in docs/how/profiles-and-deploy.md twice while `lh deploy`
# declared no options at all (measured 2026-09-12; caught by /coherence-audit,
# not by this file). This third scan checks the flags themselves.
#
# Strict by design: a flag is resolved against the options declared on the
# command it is written after, never against an ancestor group's. That is
# click's own semantics — group options parse at the group's position, so
# `lh --version` works and `lh status --version` is `No such option`. Measured
# against docs/** as it stands, strict and lax agree exactly (97 known, 1
# unknown), so the stricter rule costs nothing today and stays correct when a
# doc eventually does write one in the wrong place.


def _accepted_options(command: click.Command) -> set[str]:
    """Every option string `command` itself accepts, `--help` included.

    `secondary_opts` carries the `--no-x` half of a boolean pair; reading only
    `opts` would report every negated flag as unknown.
    """
    accepted = {"--help"}
    for param in command.params:
        if isinstance(param, click.Option):
            accepted.update(param.opts)
            accepted.update(param.secondary_opts)
    return accepted


def _attributable_flags(
    root: click.Group, doc_text: str
) -> list[tuple[str, str, click.Command]]:
    """Every (invocation, flag, command) the flag scan can attribute.

    A flag is attributable only when the walk ended somewhere that names a real
    command: on a leaf, on the flag itself, or with the tokens exhausted. A walk
    halted by a placeholder, an unclassifiable token shape or a subcommand that
    does not exist leaves the owning command unknown, so its flags are
    unverifiable rather than wrong — and an unresolved command is already
    reported by `find_missing_lh_invocations`.
    """
    attributable: list[tuple[str, str, click.Command]] = []

    for invocation in _extract_lh_invocations(doc_text):
        walk = _walk_command_path(root, invocation.split()[1:])
        if walk.stop not in ("leaf", "flag", "exhausted"):
            continue
        for token in walk.rest:
            if token == "--":
                # click's end-of-options marker: the rest belongs to whatever
                # process the command forwards to, not to `lh`.
                break
            if token.startswith("#"):
                break
            if not token.startswith("-") or token == "-":
                continue
            attributable.append((invocation, token.split("=", 1)[0], walk.node))

    return attributable


def checked_lh_flags(root: click.Group, doc_text: str) -> list[tuple[str, str]]:
    """Every (invocation, flag) pair this scan actually looks up.

    Exposed so the real-docs test can guard its own anchor: a doc restructure
    that stops flags resolving must fail loudly, not check nothing.
    """
    return [(invocation, flag) for invocation, flag, _ in _attributable_flags(root, doc_text)]


def find_unknown_lh_flags(root: click.Group, doc_text: str) -> list[tuple[str, str]]:
    """Return every (invocation, flag) whose command does not declare that flag."""
    return [
        (invocation, flag)
        for invocation, flag, command in _attributable_flags(root, doc_text)
        if flag not in _accepted_options(command)
    ]


def find_unknown_lh_flags_in_docs(
    root: click.Group, docs_dir: Path
) -> dict[str, list[tuple[str, str]]]:
    """Run `find_unknown_lh_flags` over every markdown file under `docs_dir`."""
    result: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(docs_dir.rglob("*.md")):
        unknown = find_unknown_lh_flags(root, path.read_text(encoding="utf-8"))
        if unknown:
            result[str(path.relative_to(docs_dir.parent))] = unknown
    return result


def test_self_test_flag_checker_flags_only_the_invented_flag() -> None:
    """Prove the flag scan can fail before we trust it passing against docs/."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    @click.option("--real", is_flag=True)
    def foo_cmd() -> None:
        pass

    doc = """
```bash
lh foo --real
lh foo --invented
```
"""

    assert find_unknown_lh_flags(fake_cli, doc) == [("lh foo --invented", "--invented")]


def test_flags_after_the_end_of_options_marker_are_not_checked() -> None:
    """`--` is click's end-of-options marker: everything after it belongs to the
    forwarded process, not to `lh`. `lh run --dry-run -- --resume` in
    docs/reference/cli.md is exactly this shape, and `--resume` is a flag of the
    agent binary `run_cmd` execs, not one `lh run` declares."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    @click.option("--real", is_flag=True)
    def foo_cmd() -> None:
        pass

    doc = "Run `lh foo --real -- --resume --not-ours` to forward them."

    assert find_unknown_lh_flags(fake_cli, doc) == []


def test_flags_after_a_placeholder_are_not_checked() -> None:
    """A placeholder halts the walk, so the command the flag belongs to is
    unknown and the flag is unverifiable — not wrong. `lh config <feature>
    --init` appears in four docs and `--init` is real, but only on the leaves
    (`lh config memory --init`), never on the `lh config` group itself."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.group("config")
    def config_group() -> None:
        pass

    @config_group.command("memory")
    @click.option("--init", is_flag=True)
    def memory_cmd() -> None:
        pass

    doc = "Run `lh config <feature> --init` for any feature."

    assert find_unknown_lh_flags(fake_cli, doc) == []


def test_flag_value_syntax_is_tokenised_before_lookup() -> None:
    """`--profile=lazy` is one token carrying a declared option. Looking the
    whole token up verbatim would report a real flag as unknown — a false
    positive, which is the failure mode that makes a checker untrustworthy."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    @click.option("--profile", default=None)
    def foo_cmd() -> None:
        pass

    doc = """
```bash
lh foo --profile=lazy
lh foo --invented=lazy
```
"""

    assert find_unknown_lh_flags(fake_cli, doc) == [("lh foo --invented=lazy", "--invented")]


def test_short_flags_resolve_against_the_declared_option() -> None:
    """A short flag is an entry in the same `opts` list as its long form."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    @click.option("-p", "--profile", default=None)
    def foo_cmd() -> None:
        pass

    doc = """
```bash
lh foo -p lazy
lh foo -q lazy
```
"""

    assert find_unknown_lh_flags(fake_cli, doc) == [("lh foo -q lazy", "-q")]


def test_negated_boolean_flags_are_accepted() -> None:
    """`--no-tools` is in `secondary_opts`, not `opts`."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    @click.option("--tools/--no-tools", default=True)
    def foo_cmd() -> None:
        pass

    doc = "Deny everything with `lh foo --no-tools`."

    assert find_unknown_lh_flags(fake_cli, doc) == []


def test_group_options_do_not_carry_into_subcommands() -> None:
    """The strict rule, stated as a test: `--version` on the root group is
    valid at the root's own position and invalid after a subcommand, which is
    what click itself does."""

    @click.group()
    @click.option("--version", is_flag=True)
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    def foo_cmd() -> None:
        pass

    doc = """
```bash
lh --version
lh foo --version
```
"""

    assert find_unknown_lh_flags(fake_cli, doc) == [("lh foo --version", "--version")]


def test_help_is_accepted_on_every_command() -> None:
    """click adds `--help` itself, so it is never in a command's own params."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    def foo_cmd() -> None:
        pass

    doc = "Run `lh foo --help`."

    assert find_unknown_lh_flags(fake_cli, doc) == []


def test_flags_after_a_trailing_comment_are_not_checked() -> None:
    """A `#` starts shell prose. Whatever follows is not an invocation."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    def foo_cmd() -> None:
        pass

    doc = """
```bash
lh foo # pass --invented here later
```
"""

    assert find_unknown_lh_flags(fake_cli, doc) == []


def test_flags_on_an_unresolved_command_are_not_double_reported() -> None:
    """A doc naming a command that does not exist is already a failure of
    `find_missing_lh_invocations`. Reporting its flags too would bury the real
    finding under noise, and the flags cannot be attributed to anything."""

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.group("foo")
    def foo_group() -> None:
        pass

    doc = "Run `lh foo nonexistent --whatever`."

    assert find_missing_lh_invocations(fake_cli, doc) == ["lh foo nonexistent --whatever"]
    assert find_unknown_lh_flags(fake_cli, doc) == []


def test_cli_reference_flags_exist_on_the_commands_they_follow() -> None:
    from lazy_harness.cli.main import cli

    doc_files = sorted(DOCS_DIR.rglob("*.md"))
    total_checked = sum(
        len(checked_lh_flags(cli, path.read_text(encoding="utf-8"))) for path in doc_files
    )

    # Same anchor guard as the command scan: a doc restructure that stops the
    # flag tokens resolving must fail loudly rather than check almost nothing.
    # 97 flag tokens were attributable when this was written, out of 104 present
    # (6 sit after a `<placeholder>`, 1 after a `--`).
    assert total_checked > 80

    unknown = find_unknown_lh_flags_in_docs(cli, DOCS_DIR)
    assert unknown == {}


def test_unmarked_prose_is_deliberately_not_extracted() -> None:
    """The documented limit of the anchor set, made executable.

    Both marked-up shapes are covered; bare prose is not. Locked in so that
    widening the extractor is a deliberate act with a test to update, not a
    silent change of what the whole file is understood to guarantee.
    """

    @click.group()
    def fake_cli() -> None:
        pass

    @fake_cli.command("foo")
    def foo_cmd() -> None:
        pass

    fenced = "```bash\nlh foo --invented\n```"
    inline = "Run `lh foo --invented` first."
    prose = "Run lh foo --invented first."

    assert find_unknown_lh_flags(fake_cli, fenced) == [("lh foo --invented", "--invented")]
    assert find_unknown_lh_flags(fake_cli, inline) == [("lh foo --invented", "--invented")]
    assert find_unknown_lh_flags(fake_cli, prose) == []
    assert find_missing_lh_invocations(fake_cli, "Run lh nonexistent first.") == []
