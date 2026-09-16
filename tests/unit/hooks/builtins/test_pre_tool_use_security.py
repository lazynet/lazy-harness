"""Unit tests for pre_tool_use_security hook."""

from __future__ import annotations

import re

import pytest

from lazy_harness.agents.base import HookDecision, Verdict
from lazy_harness.agents.claude_code import ClaudeCodeAdapter


def test_block_rule_is_frozen_and_has_category_pattern_reason() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BlockRule

    rule = BlockRule(
        category="filesystem",
        pattern=re.compile(r"\brm\b"),
        reason="demo",
    )
    assert rule.category == "filesystem"
    assert rule.pattern.search("rm foo") is not None
    assert rule.reason == "demo"
    with pytest.raises(Exception):
        rule.category = "sql"  # type: ignore[misc]  # frozen


def test_block_decision_holds_rule_and_matched_text() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BlockDecision, BlockRule

    rule = BlockRule(category="filesystem", pattern=re.compile(r"rm"), reason="demo")
    decision = BlockDecision(rule=rule, matched_text="rm")
    assert decision.rule is rule
    assert decision.matched_text == "rm"


def test_block_rules_is_nonempty_tuple_of_block_rule() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BLOCK_RULES, BlockRule

    assert isinstance(BLOCK_RULES, tuple)
    assert len(BLOCK_RULES) >= 10
    for rule in BLOCK_RULES:
        assert isinstance(rule, BlockRule)


def test_block_rules_cover_all_categories() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BLOCK_RULES

    categories = {rule.category for rule in BLOCK_RULES}
    assert categories == {"filesystem", "sql", "terraform", "credentials", "git"}


# Format: (command, expected_category_or_None, human_label)
BLOCK_CASES: list[tuple[str, str | None, str]] = [
    # Filesystem
    ("rm -rf /", "filesystem", "rm -rf root"),
    ("rm -rf /tmp/foo", "filesystem", "rm -rf /tmp path"),
    ("rm -rf ./build", "filesystem", "rm -rf relative"),
    ("rm -fr ./build", "filesystem", "rm -fr reversed cluster"),
    ("rm -r -f ./build", "filesystem", "rm -r -f split flags"),
    ("rm -f -r ./build", "filesystem", "rm -f -r split flags reversed"),
    ("rm --recursive --force ./build", "filesystem", "rm long flags"),
    ("rm -rfv ./build", "filesystem", "rm -rfv extra letter"),
    ("rm file.txt", None, "plain rm single file"),
    ("rm -r dir", None, "rm -r without -f"),
    ("rm -f single.txt", None, "rm -f without -r"),
    ("rm -fv single.txt", None, "rm -fv without -r"),
    ("rm --force single.txt", None, "rm --force without recursive"),
    ("rm -i single.txt", None, "rm interactive"),
    ('grep -rn "rm -rf" src', None, "rm -rf quoted inside another command"),
    ("echo 'rm -rf /tmp'", None, "rm -rf inside echo string"),
    ("./scripts/confirm -rf x", None, "rm as suffix of another command name"),
    ("rm -rf ./build && echo done", "filesystem", "rm -rf first in chain"),
    ("cd /tmp && rm -rf ./build", "filesystem", "rm -rf after && operator"),
    ("cd /tmp; rm -rf ./build", "filesystem", "rm -rf after ; operator"),
    ("cat list | xargs rm -rf", "filesystem", "rm -rf as xargs target"),
    ("sudo rm -rf /var/lib/foo", "filesystem", "rm -rf under sudo"),
    ("/bin/rm -rf ./build", "filesystem", "rm -rf by absolute path"),
    ('bash -c "rm -rf /"', "filesystem", "rm -rf wrapped in bash -c"),
    ('git commit -m "fix: rm -rf guard pattern"', None, "rm -rf inside commit message"),
    ("truncate -s 0 log.txt", "filesystem", "truncate with size"),
    # Git
    ("git push --force origin main", "git", "force push plain"),
    ("git push -f origin main", "git", "short force flag"),
    ("git push --force-with-lease origin main", None, "lease is safe"),
    ("git push origin main", None, "normal push"),
    ("git reset --hard HEAD~3", "git", "hard reset"),
    ("git reset --soft HEAD~3", None, "soft reset"),
    ("git add -f .env", "git", "forced add of dotenv"),
    ("git add -f README.md", None, "forced add of non-secret"),
    # SQL
    ("DROP TABLE users", "sql", "drop table uppercase"),
    ("drop database prod", "sql", "drop database lower"),
    ("SELECT * FROM users", None, "select"),
    # Terraform
    ("terraform destroy", "terraform", "tf destroy"),
    ("terraform destroy -auto-approve", "terraform", "tf destroy auto"),
    ("terraform apply -auto-approve", "terraform", "tf apply auto"),
    ("terraform apply", None, "tf apply interactive"),
    ("terraform apply -replace=aws_instance.web", "terraform", "tf replace"),
    ("terraform state rm aws_instance.web", "terraform", "tf state rm"),
    ("terraform state push state.tfstate", "terraform", "tf state push"),
    ("terraform plan", None, "tf plan"),
    # Credentials
    ("cat .env", "credentials", "cat .env"),
    ("cat .env.example", None, "example allowed"),
    ("cat .env.local", "credentials", "cat env local"),
    ("cat ./.env", "credentials", "dotenv relative path"),
    ("cat config/.env", "credentials", "dotenv in subdirectory"),
    # `.env` as a suffix of an identifier is an API, not the dotenv file.
    (r'grep -rn "process\.env" src/', None, "process.env is a node api"),
    ("rg 'import.meta.env' src/", None, "import.meta.env is a vite api"),
    ("less /home/user/.ssh/id_rsa", "credentials", "less private ssh"),
    ("cat /home/user/.ssh/id_rsa.pub", None, "public ssh key ok"),
    ("grep AWS_KEY /home/user/.aws/credentials", "credentials", "grep aws creds"),
    ("head server.pem", "credentials", "head cert"),
]


@pytest.mark.parametrize(
    "command,expected_category,label",
    BLOCK_CASES,
    ids=[c[2] for c in BLOCK_CASES],
)
def test_should_block_matrix(command: str, expected_category: str | None, label: str) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    if expected_category is None:
        assert decision is None, f"expected allow for {label}: {command!r}"
    else:
        assert decision is not None, f"expected block for {label}: {command!r}"
        assert decision.rule.category == expected_category


# A git global option between `git` and its subcommand must not make the rule
# abstain. Format: (command, expected_category_or_None, label)
GIT_GLOBAL_OPTION_CASES: list[tuple[str, str | None, str]] = [
    ("git -C /tmp/repo push --force origin main", "git", "force push after -C"),
    ("git -c user.name=x push --force origin main", "git", "force push after -c"),
    (
        "git --git-dir=/tmp/repo/.git reset --hard HEAD~1",
        "git",
        "hard reset after --git-dir=",
    ),
    (
        "git --work-tree=/tmp --git-dir=/tmp/.git reset --hard",
        "git",
        "hard reset after stacked --work-tree= and --git-dir=",
    ),
    ("git --no-pager push --force origin main", "git", "force push after --no-pager"),
    (
        "git -C /tmp -c user.email=a@b push --force origin main",
        "git",
        "force push after stacked -C and -c",
    ),
    (
        "git -C /tmp/repo push --force-with-lease origin main",
        None,
        "lease still safe after -C",
    ),
    ("git -C /tmp/repo status", None, "uncovered subcommand after -C"),
]


@pytest.mark.parametrize(
    "command,expected_category,label",
    GIT_GLOBAL_OPTION_CASES,
    ids=[c[2] for c in GIT_GLOBAL_OPTION_CASES],
)
def test_should_block_git_rules_survive_global_options(
    command: str, expected_category: str | None, label: str
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    if expected_category is None:
        assert decision is None, f"expected allow for {label}: {command!r}"
    else:
        assert decision is not None, f"expected block for {label}: {command!r}"
        assert decision.rule.category == expected_category


def test_should_block_allowlist_rescues_match() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    assert should_block("rm -rf .worktrees/foo", allow_patterns=[r"\.worktrees/"]) is None


# An allow_pattern written to rescue one legitimate operation must not rescue a
# different, destructive one chained onto it. Format: (chained_command, label)
CHAINED_RESCUE_CASES: list[tuple[str, str]] = [
    ("rm -rf /tmp/foo && git push --force origin main", "&& operator"),
    ("rm -rf /tmp/foo; git push --force origin main", "; operator"),
    ("rm -rf /tmp/foo || git push --force origin main", "|| operator"),
    ("rm -rf /tmp/foo\ngit push --force origin main", "newline"),
]


@pytest.mark.parametrize(
    "chained_command,label", CHAINED_RESCUE_CASES, ids=[c[1] for c in CHAINED_RESCUE_CASES]
)
def test_should_block_allow_pattern_does_not_rescue_a_chained_segment(
    chained_command: str, label: str
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(chained_command, allow_patterns=[r"git push"])
    assert decision is not None, f"allow_pattern rescued the wrong segment for {label}"
    assert decision.rule.category == "filesystem"


def test_should_block_allow_pattern_rescues_only_the_segment_it_matches() -> None:
    """A pattern legitimately meant for one segment still works within it."""
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    assert should_block("rm -rf .worktrees/foo && ls -la", allow_patterns=[r"\.worktrees/"]) is None


def test_should_block_allow_pattern_still_spans_a_pipe() -> None:
    """A pipe composes one command; it is not a chaining operator to split on."""
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    assert (
        should_block("echo .worktrees/foo | xargs rm -rf", allow_patterns=[r"\.worktrees/"]) is None
    )


def test_should_block_invalid_allow_pattern_is_ignored() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block("rm -rf /tmp/x", allow_patterns=["(["])
    assert decision is not None
    assert decision.rule.category == "filesystem"


def test_format_block_message_contains_reason_category_and_hint() -> None:
    import re as _re

    from lazy_harness.hooks.builtins.pre_tool_use_security import (
        BlockDecision,
        BlockRule,
        _format_block_message,
    )

    rule = BlockRule(
        category="filesystem",
        pattern=_re.compile(r"rm -rf"),
        reason="Recursive delete",
    )
    msg = _format_block_message(BlockDecision(rule=rule, matched_text="rm -rf /tmp"))
    assert "Blocked by lazy-harness PreToolUse" in msg
    assert "Recursive delete" in msg
    assert "filesystem" in msg
    assert "rm -rf /tmp" in msg
    assert "allow_patterns" in msg


def test_format_block_message_truncates_long_match() -> None:
    import re as _re

    from lazy_harness.hooks.builtins.pre_tool_use_security import (
        BlockDecision,
        BlockRule,
        _format_block_message,
    )

    rule = BlockRule(category="filesystem", pattern=_re.compile(r"x"), reason="r")
    huge = "x" * 500
    msg = _format_block_message(BlockDecision(rule=rule, matched_text=huge))
    # Truncated to MAX_MATCH_LEN (120) + ellipsis
    assert huge not in msg
    assert "…" in msg or "..." in msg


def test_load_allowlist_returns_empty_when_config_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == []


def test_load_allowlist_reads_patterns_from_config_toml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[hooks.pre_tool_use]\n"
        'scripts = ["pre-tool-use-security"]\n'
        'allow_patterns = ["\\\\.worktrees/", "/tmp/"]\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == ["\\.worktrees/", "/tmp/"]


def test_load_allowlist_returns_empty_when_section_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    cfg = tmp_path / "config.toml"
    cfg.write_text("[monitoring]\nenabled = true\n")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == []


def test_load_allowlist_returns_empty_on_malformed_toml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not [ valid toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == []


def _decide(payload: dict[str, object]) -> HookDecision:
    """Drive `main()` the way the runner does: payload -> adapter -> event.

    Going through the real adapter rather than hand-building a `HookEvent` is
    the point of these tests now — the guard reads normalised operations, and a
    hand-built event would assert against the normalisation this asserts.
    """
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    event = ClaudeCodeAdapter().parse_hook_input("pre_tool_use", payload, profile="")
    return mod.main(event)


def test_abstains_when_the_tool_reads_a_file_it_does_not_object_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _decide({"tool_name": "Read", "tool_input": {}}).verdict is None


def test_abstains_for_an_allowed_bash_command(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    assert _decide(payload).verdict is None


def test_denies_with_the_block_message_as_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The reason is the stderr bytes: the adapter writes it there on `DENY`."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    decision = _decide({"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}})
    assert decision.verdict is Verdict.DENY
    assert "Blocked by lazy-harness PreToolUse" in decision.reason
    assert "filesystem" in decision.reason


def test_logs_the_block_to_hooks_log(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """An unlogged guardrail cannot be audited — blocks must leave a trace."""
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    _decide({"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}})

    log = (claude_dir / "logs" / "hooks.log").read_text()
    assert "pre-tool-use-security" in log
    assert "blocked" in log
    assert "filesystem" in log


def test_does_not_log_allowed_commands(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Every Bash call passes through here; logging them all would drown the log."""
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    _decide({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})

    assert not (claude_dir / "logs" / "hooks.log").exists()


def test_abstains_when_the_payload_carries_no_tool_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """What an empty or unreadable payload becomes by the time it gets here."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _decide({}).verdict is None


# --- file-tool path guard (moved here from permissions.deny) -----------------


@pytest.mark.parametrize(
    "path",
    [
        "/Users/x/proj/.env",
        "/Users/x/proj/.env.production",
        "/Users/x/proj/.dev.vars",
        "/Users/x/certs/server.pem",
        "/Users/x/certs/server.key",
        "/Users/x/.ssh/id_rsa",
        "/Users/x/.ssh/id_ed25519",
        "/Users/x/.ssh/config",
        "/Users/x/repo/secrets/prod.yaml",
        "/Users/x/repo/deep/secrets/nested/token.txt",
        "/Users/x/repo/credentials/gcp.json",
        "/Users/x/.aws/credentials",
        "/Users/x/.gnupg/secring.gpg",
        "/Users/x/app/config/database.yml",
        "/Users/x/app/config/credentials.json",
        "/Users/x/.npmrc",
        "/Users/x/.pypirc",
        "/Users/x/.netrc",
    ],
)
def test_should_block_path_blocks_secrets(path: str) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    decision = mod.should_block_path(path)
    assert decision is not None
    assert decision.rule.category == "credentials"


@pytest.mark.parametrize(
    "path",
    [
        "/Users/x/proj/src/main.py",
        "/Users/x/proj/README.md",
        "/Users/x/.ssh_backup_notes.md",
        "/Users/x/proj/.env.example",
        "/Users/x/proj/.env.sample",
        "/Users/x/.ssh/id_ed25519.pub",
        "/Users/x/proj/environment.ts",
        "/Users/x/proj/keychain.md",
    ],
)
def test_should_block_path_allows_ordinary_files(path: str) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    assert mod.should_block_path(path) is None


def test_should_block_path_resolves_relative_paths() -> None:
    """A relative path is absolutised first, so the anchored globs still match."""
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    assert mod.should_block_path("sub/.env") is not None


def test_should_block_path_ignores_empty_path() -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    assert mod.should_block_path("") is None


def test_should_block_path_ignores_command_allow_patterns() -> None:
    """`allow_patterns` rescues commands, never paths.

    The two share a config key but not a threat model: a pattern broad enough to
    wave through a shell command — `\\.worktrees/` is real in this repo — would
    silently exempt every secret living under it. Paths are rescued only by
    SECRET_PATH_EXCEPTIONS.
    """
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    path = "/Users/x/proj/.worktrees/wt/secrets/prod.yaml"
    assert mod.should_block_path(path) is not None


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
def test_denies_a_secret_path_for_file_tools(
    tool: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    payload = {"tool_name": tool, "tool_input": {"file_path": "/Users/x/proj/.env"}}
    assert _decide(payload).verdict is Verdict.DENY


def test_reads_the_notebook_path_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """`NotebookEdit` names its path differently; both spellings are one path."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    payload = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": "/Users/x/secrets/nb.ipynb"},
    }
    assert _decide(payload).verdict is Verdict.DENY


def test_abstains_on_an_ordinary_path_for_file_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/Users/x/proj/main.py"}}
    assert _decide(payload).verdict is None


def test_abstains_on_a_tool_whose_operation_it_does_not_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """`Grep` parses with `operation=None` — known to have run, nothing to judge."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    payload = {"tool_name": "Grep", "tool_input": {"pattern": ".env"}}
    assert _decide(payload).verdict is None
