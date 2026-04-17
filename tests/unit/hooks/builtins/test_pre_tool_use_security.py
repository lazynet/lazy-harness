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
