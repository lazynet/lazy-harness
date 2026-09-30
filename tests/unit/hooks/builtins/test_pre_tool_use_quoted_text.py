"""Text the shell provably never runs does not trip the PreToolUse guards.

Both guards anchor their rules on command position, and before this change
they found that position with regexes blind to quoting: a `;`, `|` or backtick
inside a quoted argument read as a shell operator, so an ordinary search
pattern, a PR body or a heredoc of prose that *quoted* a dangerous spelling
blocked like the invocation itself. Four backlog entries recorded the shapes.

The fix is deliberately narrow and fails closed. A quoted span is exempt only
when the shell treats it as inert text -- single quotes, double quotes with no
`$` or backtick, the body of a heredoc whose delimiter is quoted -- *and* every
command in the string is one whose arguments are data rather than code. Anything
the scanner cannot classify leaves the whole command judged exactly as before.
The second half of this file is the attack on that claim: evasions routed
through quoting, every one of which must still block.
"""

from __future__ import annotations

import pytest

# (command, label). Each is a false positive the backlog recorded, in shape.
SECURITY_FALSE_POSITIVES: list[tuple[str, str]] = [
    # "Falso positivo del hook de seguridad con backticks en el argumento de
    # otro comando": a PR body quoting a destructive command in markdown.
    (
        "gh pr create --title 'docs: guard' --body \"$(cat <<'EOF'\n"
        "Never run `git reset --hard` on a shared checkout.\n"
        "EOF\n"
        ')"',
        "PR body in the substituted-heredoc idiom quoting a hard reset",
    ),
    (
        "gh pr create --title 'docs' --body 'Never run `git reset --hard` here.'",
        "single-quoted PR body quoting a hard reset in backticks",
    ),
    (
        "git commit -m 'docs: explain why; git push --force is banned'",
        "commit message whose prose carries a separator before a force push",
    ),
    # "El denylist de seguridad y el guard de git-scope bloquean prosa que sólo
    # cita una grafía peligrosa".
    (
        "cat > notes.md <<'EOF'\nTo clean up; rm -rf build is what we never type.\nEOF",
        "heredoc prose with a separator before a recursive delete",
    ),
    # "El guard de recursive-delete dispara con un operador de shell dentro de
    # un argumento citado, delante de la grafía -rf".
    (
        "grep -rn 'a\\|rm -rf\\|b' tests/",
        "grep alternation whose pipe precedes a recursive delete",
    ),
    (
        "cat > probe.py <<'EOF'\nCMD = \"/bin/zsh -lc 'rm -rf /tmp/x'\"\nEOF",
        "python string naming a shell -c delete, written to a file",
    ),
    (
        'cat > mod.py <<\'EOF\'\n"""Refuses every `rm -rf` spelling."""\nEOF',
        "docstring with a backtick before the delete, written to a file",
    ),
    # "Falso positivo del PreToolUse de seguridad con backticks de markdown".
    (
        "cat > doc.md <<'EOF'\nThe guard refuses `rm -rf /tmp/scratch`.\nEOF",
        "markdown backticks around a recursive delete in a quoted heredoc",
    ),
    (
        'echo "then; terraform destroy is irreversible"',
        "double-quoted prose without expansions",
    ),
]


@pytest.mark.parametrize(
    "command,label", SECURITY_FALSE_POSITIVES, ids=[c[1] for c in SECURITY_FALSE_POSITIVES]
)
def test_security_lets_inert_quoted_text_through(command: str, label: str) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    assert decision is None, (
        f"false positive for {label}: {decision.rule.reason if decision else ''}"
        f" / {decision.matched_text if decision else ''}"
    )


GIT_SCOPE_FALSE_POSITIVES: list[tuple[str, str]] = [
    (
        "cat > notes.md <<'EOF'\nNever `git stash pop` on a shared stack.\nEOF",
        "heredoc prose quoting a stash pop in backticks",
    ),
    (
        "git commit -m 'docs: why; git stash pop is unsafe'",
        "commit message naming a stash pop after a separator",
    ),
    (
        "gh pr create --title 'x' --body \"$(cat <<'EOF'\n"
        "Replaces `git stash` with a WIP commit.\n"
        "EOF\n"
        ')"',
        "PR body quoting a bare stash",
    ),
]


@pytest.mark.parametrize(
    "command,label", GIT_SCOPE_FALSE_POSITIVES, ids=[c[1] for c in GIT_SCOPE_FALSE_POSITIVES]
)
def test_git_scope_lets_inert_quoted_text_through(command: str, label: str) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

    assert is_unsafe_stash(command) is None, label


# (command, expected_category, label). Evasions *through* quoting. Each one
# blocks on main before this change; the table asserts none of them was opened.
SECURITY_EVASIONS: list[tuple[str, str, str]] = [
    ("sh -c 'echo x; rm -rf build'", "filesystem", "single-quoted string run by sh -c"),
    ('bash -c "cd /; rm -rf build"', "filesystem", "double-quoted string run by bash -c"),
    ("bash -c 'echo x; terraform destroy'", "terraform", "regex-only rule inside bash -c"),
    ("eval 'echo x; rm -rf build'", "filesystem", "single-quoted string run by eval"),
    ('echo "$(rm -rf build)"', "filesystem", "command substitution inside double quotes"),
    ('echo "`rm -rf build`"', "filesystem", "backticks inside double quotes"),
    ("echo 'never closed; rm -rf build", "filesystem", "unterminated single quote"),
    ('echo "never closed; rm -rf build', "filesystem", "unterminated double quote"),
    ("echo $'a; rm -rf build'", "filesystem", "ANSI-C quoting"),
    ("r'm' -rf build", "filesystem", "quote concatenation in the command name"),
    ("echo 'x'; 'rm' -rf build", "filesystem", "quoted command name after inert text"),
    ("cat <<EOF\n$(rm -rf build)\nEOF", "filesystem", "unquoted heredoc expanding $()"),
    ("cat <<EOF\n`rm -rf build`\nEOF", "filesystem", "unquoted heredoc expanding backticks"),
    ("cat <<'EOF' | sh\nrm -rf build\nEOF", "filesystem", "quoted heredoc piped into sh"),
    ("bash <<'EOF'\nrm -rf build\nEOF", "filesystem", "quoted heredoc fed to bash"),
    (
        "python3 - <<'EOF'\nimport os\nos.system('rm -rf build')\nEOF",
        "filesystem",
        "quoted heredoc fed to an interpreter",
    ),
    ("echo 'x; rm -rf build' | sh", "filesystem", "inert-looking echo piped into sh"),
    (
        "printf -v c 'x; rm -rf build'; eval \"$c\"",
        "filesystem",
        "text stored in a variable and evaluated",
    ),
    (
        "cat > s.sh <<'EOF'\nrm -rf build\nEOF\nbash s.sh",
        "filesystem",
        "quoted heredoc written to a script run in the same command",
    ),
    (
        "cat > .git/hooks/pre-commit <<'EOF'\nrm -rf build\nEOF\ngit commit -m x",
        "filesystem",
        "quoted heredoc written to a hook that a commit then runs",
    ),
    (
        "bash -c \"$(cat <<'EOF'\nrm -rf build\nEOF\n)\"",
        "filesystem",
        "substituted-heredoc idiom handed to bash -c",
    ),
    (
        "eval \"$(cat <<'EOF'\nrm -rf build\nEOF\n)\"",
        "filesystem",
        "substituted-heredoc idiom handed to eval",
    ),
    (
        "gh pr create --body \"$(cat <<'EOF'\nx\nEOF\n) $(rm -rf build)\"",
        "filesystem",
        "a second substitution after the idiom",
    ),
    (
        "echo x # it's a note\nrm -rf build # it's done",
        "filesystem",
        "apostrophes in two comments pairing across a real command",
    ),
    ("echo <(sh -c 'x; rm -rf build')", "filesystem", "process substitution"),
    ("echo `sh -c 'x; rm -rf build'`", "filesystem", "unquoted backticks around sh -c"),
    (
        "printf -v 'a[$(rm -rf build)]' x",
        "filesystem",
        "array subscript in printf -v evaluates a quoted substitution",
    ),
    (
        "printf '-va[$(rm -rf build)]' x",
        "filesystem",
        "the same subscript attached to -v",
    ),
    (
        # The quote after `echo '` closes the outer string for the shell; a
        # scanner that resumed outside it would pair the apostrophes instead.
        "echo \"$(cat <<'EOF'\nhi\nEOF\n) echo '\"\nrm -rf build\n# '",
        "filesystem",
        "text after the idiom's closing parenthesis that closes the quote",
    ),
    ("grep 'x; cat' .env", "credentials", "quoted separator hiding a dotenv read"),
    ("grep -rn 'x' '.env'", "credentials", "quoted dotenv path as a grep operand"),
    ("git add -f 'deploy.pem'", "git", "quoted secret path in a forced add"),
    ("echo 'x' && git -C . reset --hard", "git", "hard reset after inert text"),
    (
        "git -c alias.x='!sh -c \"rm -rf build\"' x",
        "filesystem",
        "git config alias running a shell",
    ),
]


@pytest.mark.parametrize(
    "command,expected_category,label",
    SECURITY_EVASIONS,
    ids=[c[2] for c in SECURITY_EVASIONS],
)
def test_security_quoting_does_not_open_an_evasion(
    command: str, expected_category: str, label: str
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    assert decision is not None, f"evasion through quoting: {label}"
    assert decision.rule.category == expected_category, label


GIT_SCOPE_EVASIONS: list[tuple[str, str]] = [
    ("bash -c 'cd /tmp && git stash pop'", "compound run by bash -c"),
    ("echo 'x; git stash pop' | sh", "echo piped into sh"),
    ("cat <<'EOF' | bash\ngit stash pop\nEOF", "quoted heredoc piped into bash"),
    ("echo 'x'; git stash pop", "real pop after inert text"),
    ('echo "$(git stash pop)"', "command substitution inside double quotes"),
]


@pytest.mark.parametrize(
    "command,label", GIT_SCOPE_EVASIONS, ids=[c[1] for c in GIT_SCOPE_EVASIONS]
)
def test_git_scope_quoting_does_not_open_an_evasion(command: str, label: str) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

    assert is_unsafe_stash(command) is not None, f"evasion through quoting: {label}"


def test_the_hooks_doc_names_every_text_command() -> None:
    """The doc lists the commands the exemption trusts; the constant decides."""
    from pathlib import Path

    from lazy_harness.hooks.builtins._inert_text import (
        _GIT_TEXT_SUBCOMMANDS,
        _TEXT_COMMANDS,
    )

    doc = (Path(__file__).resolve().parents[4] / "docs" / "how" / "hooks.md").read_text()
    section = doc[doc.index("**Quoted text the shell never runs.**") :]
    section = section[: section.index("\n\n")]
    missing = [name for name in sorted(_TEXT_COMMANDS) if f"`{name}`" not in section]
    missing += [sub for sub in sorted(_GIT_TEXT_SUBCOMMANDS) if sub not in section]
    assert missing == [], f"trusted commands the doc does not name: {missing}"


# (command, the text each span covers, label). The scanner's contract, stated
# directly: several of its refusals are backed up by the command gate, so only a
# test on the spans themselves fails when one of them is removed.
SPAN_CONTRACT: list[tuple[str, list[str], str]] = [
    ("echo 'a; b'", ["a; b"], "single quotes"),
    ('echo "a; b"', ["a; b"], "double quotes without expansions"),
    ('echo "a $x; b"', [], "double quotes with a parameter expansion"),
    ("cat <<'EOF'\na; b\nEOF", ["a; b\n"], "quoted heredoc delimiter"),
    ("cat <<EOF\na; b\nEOF", [], "unquoted heredoc delimiter"),
    ("echo 'a; b' $(true)", [], "unquoted command substitution"),
    ("echo 'a; b' <(echo c)", [], "process substitution"),
    ("echo 'a; b' $'c'", [], "ANSI-C quoting"),
    ("echo 'a; b' ${x}", [], "braced parameter expansion"),
    ("echo 'a; b' `true`", [], "unquoted backticks"),
    ("echo 'a; b", [], "unterminated quote"),
    ("cat <<'EOF'\na; b", [], "heredoc without its terminator"),
    ("echo 'a; b' | sh", [], "a command that runs its input"),
]


@pytest.mark.parametrize("command,covered,label", SPAN_CONTRACT, ids=[c[2] for c in SPAN_CONTRACT])
def test_inert_spans_cover_only_what_the_shell_never_runs(
    command: str, covered: list[str], label: str
) -> None:
    from lazy_harness.hooks.builtins._inert_text import inert_spans

    assert [command[start:end] for start, end in inert_spans(command)] == covered, label
