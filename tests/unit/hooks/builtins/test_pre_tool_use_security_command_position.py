"""The denylist fires on command position, not on the mere presence of a token.

Every rule whose token is the name of an executable is anchored on
`_COMMAND_START`. The anchor and its rationale predate this file — it was
written for the `rm` rule and documented there — but only that one rule ever
used it, so twelve others still matched a dangerous word anywhere in the
command string, including inside a quoted argument nobody was going to execute.
The fourteenth, `sql`, stays unanchored on purpose; the property test at the
bottom says why.

The fixtures below are the three measured false positives, generalised. The
sharpest one carries no heredoc at all: `herdr agent prompt` writes text into a
terminal pane, and the text happened to name an infra command.

Position has two halves and both are needed. Anchoring says where a command
starts; excluding the newline from the argument classes says where its
arguments end. The heredoc fixture naming two tokens only passes once both
hold.
"""

from __future__ import annotations

import pytest

# Prose that names a dangerous command without invoking it. Format:
# (command, human_label)
PROSE_CASES: list[tuple[str, str]] = [
    (
        "herdr agent prompt secfix 'the hook wrongly blocks "
        "terraform destroy when it appears in prose'",
        "infra token inside a quoted argument to a pane writer",
    ),
    (
        'cat > notes.md <<"EOF"\nThe runbook warns that terraform destroy is irreversible.\nEOF',
        "infra token in a heredoc body feeding a writer",
    ),
    (
        "echo 'remember to never cat .env in a shared pane'",
        "dotenv token inside a quoted argument",
    ),
    # The measured fixture, verbatim in shape: one heredoc naming both tokens.
    # Anchoring alone does not rescue it. `cat` really is in command position
    # here -- it is the writer -- and the credentials rule joins the command
    # word to its target with a class that excludes `|;&` but not a newline, so
    # `cat` on the first line reaches `.env` in the body three lines down.
    (
        'cat > notes.md <<"EOF"\n'
        "The runbook warns that terraform destroy is irreversible, and\n"
        "that a .env file must never be read in a shared pane.\n"
        "EOF",
        "heredoc naming an infra command and a secrets filename",
    ),
    (
        "cat > runbook.md <<EOF\nUse terraform apply, never with -auto-approve in production.\nEOF",
        "heredoc whose body names a flag the rule pairs across lines",
    ),
    (
        'git commit -m "docs: explain why git push --force is banned"',
        "force-push token inside a commit message",
    ),
    (
        'grep -rn "terraform state rm" infra/',
        "infra token as a search pattern",
    ),
    (
        "herdr agent prompt secfix 'do not run git reset --hard here'",
        "hard-reset token inside a quoted argument",
    ),
    # Writing security documentation is the use case this guard kept refusing.
    # Measured again while an audit report was being saved: the body narrated a
    # payload, the command being run was `cat`, and the guard called it a
    # delete. The `rm` rule was already anchored, so this direction held even
    # before this change -- nothing asserted it, which is why it is here now.
    (
        "cat > audit.md <<'EOF'\n"
        "I sent the hook a payload describing rm -rf / to see if it refused.\n"
        "EOF",
        "heredoc body of an audit report naming a recursive delete",
    ),
    (
        "cat > audit.md <<'EOF'\nThe payload was rm -rf /tmp/scratch and it refused.\nEOF",
        "heredoc prose naming a recursive delete mid-line",
    ),
]


@pytest.mark.parametrize("command,label", PROSE_CASES, ids=[c[1] for c in PROSE_CASES])
def test_prose_naming_a_dangerous_command_is_not_an_invocation(command: str, label: str) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    assert decision is None, (
        f"false positive for {label}: matched "
        f"{decision.rule.category if decision else ''}/"
        f"{decision.matched_text if decision else ''}"
    )


# The same tokens in real command position. Format:
# (command, expected_category, human_label)
INVOCATION_CASES: list[tuple[str, str, str]] = [
    ("terraform destroy", "terraform", "bare invocation"),
    ("cd infra && terraform destroy", "terraform", "after && operator"),
    ("cd infra; terraform destroy", "terraform", "after ; operator"),
    ("sudo terraform destroy", "terraform", "under sudo"),
    ('bash -c "terraform destroy"', "terraform", "wrapped in bash -c"),
    ("/bin/bash -c 'terraform destroy'", "terraform", "wrapped in absolute bash -c"),
    ('env bash -c "terraform destroy"', "terraform", "wrapped in env bash -c"),
    (
        "cat <<EOF | bash\nterraform destroy\nEOF",
        "terraform",
        "heredoc piped into a shell",
    ),
    ("cd infra\nterraform destroy", "terraform", "second line of a multi-line script"),
    # Command position survives indentation and the less common ways of handing
    # a string to an interpreter. Each of these was found by the mutation run
    # against the first cut of the anchor, which blocked prose correctly and
    # then let these four through.
    ("   terraform destroy", "terraform", "indented inside a script block"),
    ('bash -lc "terraform destroy"', "terraform", "login shell -lc flag"),
    (
        """python3 -c 'import os; os.system("terraform destroy")'""",
        "terraform",
        "python3 -c interpreter",
    ),
    ('eval "terraform destroy"', "terraform", "eval of a quoted string"),
    ("eval terraform destroy", "terraform", "eval of a bare command"),
    ("cat .env", "credentials", "bare dotenv read"),
    ("echo start; cat .env", "credentials", "dotenv read after ; operator"),
    ("/bin/cat .env", "credentials", "dotenv read by absolute path"),
    ("git push --force origin main", "git", "bare force push"),
    ("rm -rf ./build", "filesystem", "bare recursive delete"),
    # The other direction of the audit-report case above: the same heredoc, but
    # feeding an interpreter instead of a file. Body text stops being data the
    # moment something executes it, and `(?m)` is what keeps it in position.
    ("cat <<EOF | bash\nrm -rf /\nEOF", "filesystem", "recursive delete piped into a shell"),
    ("   rm -rf /var/lib/foo", "filesystem", "indented recursive delete in a script"),
]


@pytest.mark.parametrize(
    "command,expected_category,label",
    INVOCATION_CASES,
    ids=[c[2] for c in INVOCATION_CASES],
)
def test_a_real_invocation_is_still_blocked(
    command: str, expected_category: str, label: str
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    assert decision is not None, f"guard went silent for {label}: {command!r}"
    assert decision.rule.category == expected_category


def test_every_executable_token_rule_is_anchored_on_command_start() -> None:
    """The anchor is a property of the rule set, not of the cases that sample it.

    A rule added later without the anchor reopens the bug for its own token, and
    no case in `PROSE_CASES` would notice. `sql` is the one exemption and it is
    named explicitly: `DROP TABLE` is not an executable, it is the payload of
    one (`psql -c "DROP TABLE users"`), so anchoring it on command position
    would delete the rule rather than narrow it.
    """
    from lazy_harness.hooks.builtins.pre_tool_use_security import (
        _COMMAND_START,
        BLOCK_RULES,
    )

    unanchored = [
        rule.reason
        for rule in BLOCK_RULES
        if rule.category != "sql" and not rule.pattern.pattern.startswith(_COMMAND_START)
    ]
    assert unanchored == [], f"rules matching a token in any position: {unanchored}"
