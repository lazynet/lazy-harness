"""User identity resolution for metrics events.

Tries (in order): explicit profile value, `gh` CLI, `git config user.email`,
and finally `$USER@$HOSTNAME` marked as implicit. Every lookup is wrapped
so a failure moves to the next option instead of raising.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

IdentitySource = Literal["explicit", "gh", "git", "implicit"]


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    user_id: str
    source: IdentitySource


def _read_gh_login() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _read_git_email() -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_identity(
    *,
    explicit: str | None,
    _gh_reader: Callable[[], str | None] = _read_gh_login,
    _git_email_reader: Callable[[], str | None] = _read_git_email,
) -> ResolvedIdentity:
    if explicit:
        return ResolvedIdentity(user_id=explicit, source="explicit")

    gh_login = _gh_reader()
    if gh_login:
        return ResolvedIdentity(user_id=gh_login, source="gh")

    email = _git_email_reader()
    if email:
        local = email.split("@", 1)[0]
        if local:
            return ResolvedIdentity(user_id=local, source="git")

    user = os.environ.get("USER") or "unknown"
    host = os.environ.get("HOSTNAME") or "host"
    return ResolvedIdentity(user_id=f"{user}@{host}", source="implicit")
