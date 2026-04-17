"""Unit tests for pre_tool_use_security hook."""

from __future__ import annotations

import re

import pytest


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
    ("rm file.txt", None, "plain rm single file"),
    ("rm -r dir", None, "rm -r without -f"),
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
def test_should_block_matrix(
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


def test_should_block_invalid_allow_pattern_is_ignored() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block("rm -rf /tmp/x", allow_patterns=["(["])
    assert decision is not None
    assert decision.rule.category == "filesystem"


def test_read_stdin_json_returns_dict_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    from lazy_harness.hooks.builtins.pre_tool_use_security import _read_stdin_json

    monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "Bash"}'))
    assert _read_stdin_json() == {"tool_name": "Bash"}


def test_read_stdin_json_returns_empty_dict_on_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from lazy_harness.hooks.builtins.pre_tool_use_security import _read_stdin_json

    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    assert _read_stdin_json() == {}


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
        '[hooks.pre_tool_use]\n'
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
    cfg.write_text('[monitoring]\nenabled = true\n')
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
