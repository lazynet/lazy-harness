"""Tests for core.identity."""

from __future__ import annotations

import os
import platform
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


def test_implicit_fallback_uses_hostname_reader_when_env_unset() -> None:
    """$HOSTNAME is a bashism neither zsh nor systemd exports.

    Without a real lookup the fallback stamped the literal "host", so every
    Linux machine collapsed onto a single identity.
    """
    env = {k: v for k, v in os.environ.items() if k != "HOSTNAME"}
    env["USER"] = "martin"
    with patch.dict(os.environ, env, clear=True):
        ident = resolve_identity(
            explicit=None,
            _gh_reader=lambda: None,
            _git_email_reader=lambda: None,
            _hostname_reader=lambda: "agents",
        )
    assert ident.user_id == "martin@agents"
    assert ident.source == "implicit"


def test_implicit_fallback_reads_real_hostname_without_injection() -> None:
    """Exercise the default reader, not an injected one."""
    node = platform.node()
    assert node, "platform.node() is empty; cannot exercise the default reader"
    env = {k: v for k, v in os.environ.items() if k != "HOSTNAME"}
    env["USER"] = "martin"
    with patch.dict(os.environ, env, clear=True):
        ident = resolve_identity(
            explicit=None,
            _gh_reader=lambda: None,
            _git_email_reader=lambda: None,
        )
    assert ident.user_id == f"martin@{node}"
    assert ident.source == "implicit"


def test_implicit_fallback_keeps_host_literal_when_hostname_unknown() -> None:
    env = {k: v for k, v in os.environ.items() if k != "HOSTNAME"}
    env["USER"] = "martin"
    with patch.dict(os.environ, env, clear=True):
        ident = resolve_identity(
            explicit=None,
            _gh_reader=lambda: None,
            _git_email_reader=lambda: None,
            _hostname_reader=lambda: "",
        )
    assert ident.user_id == "martin@host"


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
