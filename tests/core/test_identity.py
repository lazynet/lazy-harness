"""Tests for core.identity."""

from __future__ import annotations

import os
from unittest.mock import patch

from lazy_harness.core.identity import resolve_identity


def test_explicit_user_id_wins() -> None:
    ident = resolve_identity(explicit="martin-flex")
    assert ident.user_id == "martin-flex"
    assert ident.source == "explicit"


def test_gh_used_when_explicit_missing() -> None:
    def fake_run_gh() -> str | None:
        return "martin-gh"

    ident = resolve_identity(
        explicit=None,
        _gh_reader=fake_run_gh,
    )
    assert ident.user_id == "martin-gh"
    assert ident.source == "gh"


def test_git_email_used_when_gh_missing() -> None:
    ident = resolve_identity(
        explicit=None,
        _gh_reader=lambda: None,
        _git_email_reader=lambda: "martin@example.com",
    )
    assert ident.user_id == "martin"
    assert ident.source == "git"


def test_implicit_fallback_stamps_user_at_host() -> None:
    with patch.dict(os.environ, {"USER": "martin", "HOSTNAME": "laptop"}, clear=False):
        ident = resolve_identity(
            explicit=None,
            _gh_reader=lambda: None,
            _git_email_reader=lambda: None,
        )
    assert ident.user_id == "martin@laptop"
    assert ident.source == "implicit"


def test_explicit_empty_string_is_ignored() -> None:
    ident = resolve_identity(
        explicit="",
        _gh_reader=lambda: "fallback",
    )
    assert ident.user_id == "fallback"
    assert ident.source == "gh"


def test_gh_reader_returning_empty_string_treated_as_missing() -> None:
    ident = resolve_identity(
        explicit=None,
        _gh_reader=lambda: "",
        _git_email_reader=lambda: "martin@example.com",
    )
    assert ident.source == "git"
