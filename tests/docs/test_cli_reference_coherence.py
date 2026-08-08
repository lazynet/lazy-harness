"""Deterministic coherence check: docs/reference/cli.md vs the click command tree.

Direction is doc ⊆ code (lax): every `lh <command> [subcommand]` named in the doc
must resolve against `lazy_harness.cli.main.cli`. The reverse is not checked —
plenty of subcommands are intentionally undocumented.

Doc anchors this test depends on (a doc restructure that breaks these should fail
loudly, not silently extract nothing):
- fenced ```bash code blocks whose lines start with "lh "
- inline code spans of the shape `` `lh ...` ``
"""

from __future__ import annotations

import re
from pathlib import Path

import click

CLI_MD = Path(__file__).parent.parent.parent / "docs" / "reference" / "cli.md"

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


def find_missing_lh_invocations(root: click.Group, doc_text: str) -> list[str]:
    """Return every extracted invocation whose command path does not exist.

    Walks tokens through the click tree starting at `root`, descending through
    click.Group nodes only. Stops as soon as a leaf Command is reached (the
    remaining tokens are arguments/flags, not subcommands) or a token looks like
    a flag/comment. A missing subcommand along the walked path is a failure.
    """
    missing: list[str] = []

    for invocation in _extract_lh_invocations(doc_text):
        tokens = invocation.split()[1:]  # drop the leading "lh"
        node: click.Command = root
        broken = False
        for token in tokens:
            if not isinstance(node, click.Group):
                break
            if token.startswith("-") or token.startswith("#"):
                break
            if "<" in token or ">" in token:
                # Placeholder syntax (e.g. `lh <command> --help`), not a real
                # subcommand name — cannot confidently classify, so skip it.
                break
            if not _COMMAND_TOKEN_SHAPE.match(token):
                # Catch-all conservatism for shapes the checks above don't name
                # explicitly: entry-point syntax (`lh = "pkg:cli"`), slash
                # shorthand (`lh profile add/remove`), and anything else that
                # isn't a plausible lowercase-hyphenated subcommand name.
                break
            next_node = node.commands.get(token)
            if next_node is None:
                broken = True
                break
            node = next_node
        if broken:
            missing.append(invocation)

    return missing


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

    doc_text = CLI_MD.read_text(encoding="utf-8")
    invocations = _extract_lh_invocations(doc_text)

    # Guards the anchor: if docs/reference/cli.md is restructured so no ```bash
    # block or inline `lh ...` span survives, this must fail loudly rather than
    # silently pass with zero candidates checked.
    assert len(invocations) > 10

    missing = find_missing_lh_invocations(cli, doc_text)
    assert missing == []
