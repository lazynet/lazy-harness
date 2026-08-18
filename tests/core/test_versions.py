"""Tests for parsing a version out of a `--version` line."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        # The one that was wrong in production: qmd appends a build hash, and
        # taking the last token reported `(5b90e281d4)` as the version.
        ("qmd 2.5.3 (5b90e281d4)", "2.5.3"),
        ("engram 1.20.0", "1.20.0"),
        ("graphify 0.9.41", "0.9.41"),
        # A leading `v` is decoration, not part of the number — comparing it
        # against a bare pin would report drift between equal versions.
        ("engram v1.16.1", "1.16.1"),
        ("lazy-harness, version 0.44.2", "0.44.2"),
        # Two-component and pre-release forms both stay intact.
        ("tool 1.2", "1.2"),
        ("tool 1.2.3-rc1", "1.2.3-rc1"),
    ],
)
def test_parse_version_extracts_the_number(output: str, expected: str) -> None:
    from lazy_harness.core.versions import parse_version

    assert parse_version(output) == expected


@pytest.mark.parametrize("output", ["", "   ", "no version here", "build abc123"])
def test_parse_version_returns_empty_when_absent(output: str) -> None:
    """An unparseable line is empty, never a guess.

    `lh doctor` renders a non-empty value as the installed version, so a
    fallback to some arbitrary token is how a build hash ends up printed as
    if it were a release.
    """
    from lazy_harness.core.versions import parse_version

    assert parse_version(output) == ""


def test_parse_version_takes_the_first_number_not_the_last() -> None:
    """The tool name comes first and the decoration last."""
    from lazy_harness.core.versions import parse_version

    assert parse_version("tool 1.0.0 (built against 2.9.9)") == "1.0.0"
