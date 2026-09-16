"""Unit tests for the session_start_preflight hook.

The hook reports what would strand a long session partway through: an expired
login, a git remote pointing somewhere unexpected, a missing or duplicated
tool. It never blocks — SessionStart has no blocking semantics — so every path
exits 0 and the worst case is a section that says it could not tell.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lazy_harness.hooks.engine import CLI_BOOTSTRAP

_HOUR = 3600.0
_NOW = 1_800_000_000.0


def _credentials(refresh_expires_at_ms: int | None, **extra: object) -> str:
    oauth: dict[str, object] = {"accessToken": "x", "refreshToken": "y", **extra}
    if refresh_expires_at_ms is not None:
        oauth["refreshTokenExpiresAt"] = refresh_expires_at_ms
    return json.dumps({"claudeAiOauth": oauth})


def _write_credentials(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".credentials.json"
    path.write_text(body)
    return path


class TestCheckAuth:
    def test_a_live_refresh_token_passes(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW + 100 * _HOUR) * 1000)))
        assert check_auth(creds, now=_NOW).status == "pass"

    def test_an_expired_refresh_token_fails(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW - _HOUR) * 1000)))
        result = check_auth(creds, now=_NOW)
        assert result.status == "fail"
        assert "log in" in result.detail.lower() or "login" in result.detail.lower()

    def test_a_refresh_token_expiring_soon_warns(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW + 3 * _HOUR) * 1000)))
        assert check_auth(creds, now=_NOW).status == "warn"

    def test_an_expired_access_token_alone_is_not_a_failure(self, tmp_path: Path) -> None:
        """The access token expires constantly and is refreshed transparently.

        Measured on a real profile: `expiresAt` 61 hours in the past while the
        session worked fine, because the refresh token had 84 hours left.
        Reading the wrong field makes this check cry wolf on every session.
        """
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(
            tmp_path,
            _credentials(
                int((_NOW + 100 * _HOUR) * 1000),
                expiresAt=int((_NOW - 61 * _HOUR) * 1000),
            ),
        )
        assert check_auth(creds, now=_NOW).status == "pass"

    @pytest.mark.parametrize(
        "body,label",
        [
            ("", "empty file"),
            ("not json", "malformed json"),
            ("null", "valid json, null"),
            ("[]", "valid json, list"),
            ('{"claudeAiOauth": null}', "oauth is null"),
            ('{"claudeAiOauth": 5}', "oauth is an int"),
            ("{}", "no oauth section"),
            ('{"claudeAiOauth": {"refreshTokenExpiresAt": "soon"}}', "expiry is a string"),
            ('{"claudeAiOauth": {"refreshTokenExpiresAt": null}}', "expiry is null"),
            ('{"claudeAiOauth": {}}', "expiry missing"),
        ],
        ids=lambda v: v if isinstance(v, str) and " " in v else "",
    )
    def test_unreadable_credentials_report_unknown_never_fail(
        self, body: str, label: str, tmp_path: Path
    ) -> None:
        """Unknown is not the same as expired.

        A shape this hook does not understand must not be reported as a dead
        login — that would train the reader to ignore the section.
        """
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, body)
        assert check_auth(creds, now=_NOW).status == "unknown", label

    def test_a_missing_credentials_file_is_unknown(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        assert check_auth(tmp_path / "absent.json", now=_NOW).status == "unknown"

    def test_it_never_reports_a_token_value(self, tmp_path: Path) -> None:
        """The detail string is injected into the transcript. No secrets in it."""
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(
            tmp_path,
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "SECRET-ACCESS-VALUE",
                        "refreshToken": "SECRET-REFRESH-VALUE",
                        "refreshTokenExpiresAt": int((_NOW + 100 * _HOUR) * 1000),
                    }
                }
            ),
        )
        rendered = check_auth(creds, now=_NOW)
        assert "SECRET-ACCESS-VALUE" not in rendered.detail
        assert "SECRET-REFRESH-VALUE" not in rendered.detail

    def test_it_does_not_execute_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole reason this reads a file: no credential subprocess.

        Running the auth CLI from a hook is what the operator's rules forbid —
        a helper that cannot reach the keychain has deleted credentials before.
        """
        from lazy_harness.hooks.builtins import session_start_preflight as hook

        def explode(*args: object, **kwargs: object) -> None:
            raise AssertionError("check_auth must not spawn a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        creds = _write_credentials(tmp_path, _credentials(int((_NOW + 100 * _HOUR) * 1000)))
        assert hook.check_auth(creds, now=_NOW).status == "pass"


class TestCredentialsAreMirrored:
    """Which (agent, platform) pairs keep the live credential somewhere else.

    A pure function taking the platform explicitly, so the tests are hermetic on
    whatever runner they land on, plus one parameter-less case proving the
    default is wired to the running platform and not to a constant.
    """

    def test_claude_code_on_darwin_is_mirrored(self) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import credentials_are_mirrored

        assert credentials_are_mirrored("claude-code", "darwin") is True

    def test_claude_code_on_linux_is_not(self) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import credentials_are_mirrored

        assert credentials_are_mirrored("claude-code", "linux") is False

    def test_another_agent_on_darwin_is_not(self) -> None:
        """The claim is about one agent's store, not about the platform.

        macOS having a keychain says nothing about where an agent that never
        used it keeps its credentials.
        """
        from lazy_harness.hooks.builtins.session_start_preflight import credentials_are_mirrored

        assert credentials_are_mirrored("codex", "darwin") is False

    def test_the_default_reads_the_platform_the_hook_is_running_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from lazy_harness.hooks.builtins import session_start_preflight as hook

        monkeypatch.setattr(hook.sys, "platform", "darwin")
        assert hook.credentials_are_mirrored("claude-code") is True
        monkeypatch.setattr(hook.sys, "platform", "linux")
        assert hook.credentials_are_mirrored("claude-code") is False


class TestAMirroredCredentialsFile:
    """macOS keeps the live credential in the keychain and leaves a stale file.

    Measured 2026-09-16 on a profile logged in that morning: the keychain entry
    was hours old, `.credentials.json` was eight days old with an expired
    refresh token, and the check reported `fail` — the file opens, parses and
    has a valid shape, so no degradation branch applied. A false FAIL trains the
    reader to skip the whole block, which the check's own docstring says.
    """

    def test_an_expired_mirror_reports_unknown_rather_than_fail(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW - _HOUR) * 1000)))

        result = check_auth(creds, now=_NOW, mirrored=True)

        assert result.status == "unknown"
        assert "keychain" in result.detail
        assert "mirror" in result.detail

    def test_an_expiring_mirror_reports_unknown_rather_than_warn(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW + 3 * _HOUR) * 1000)))

        assert check_auth(creds, now=_NOW, mirrored=True).status == "unknown"

    def test_a_healthy_mirror_still_passes(self, tmp_path: Path) -> None:
        """A mirror cannot claim more life than the store it mirrors.

        The file is rewritten from the keychain, never ahead of it, so a file
        saying the refresh token is good is a lower bound on the truth. Keeping
        `pass` is what stops the macOS branch from making the check useless
        instead of merely quieter.
        """
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW + 100 * _HOUR) * 1000)))

        assert check_auth(creds, now=_NOW, mirrored=True).status == "pass"

    def test_an_unreadable_mirror_is_still_unknown(self, tmp_path: Path) -> None:
        """The weakest statement available was already what this branch made."""
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        assert check_auth(tmp_path / "absent.json", now=_NOW, mirrored=True).status == "unknown"

    def test_the_same_file_unmirrored_still_fails(self, tmp_path: Path) -> None:
        """The control. Without it a check that had regressed to reporting
        `unknown` unconditionally would satisfy every assertion above."""
        from lazy_harness.hooks.builtins.session_start_preflight import check_auth

        creds = _write_credentials(tmp_path, _credentials(int((_NOW - _HOUR) * 1000)))

        assert check_auth(creds, now=_NOW, mirrored=False).status == "fail"


class TestAuthCheck:
    """The composed check: ask the adapter for the filename, then read it."""

    def test_an_adapter_that_exposes_no_credentials_file_says_so(self, tmp_path: Path) -> None:
        """Exercised through the shipped sentinel, not a local fake.

        `NullAdapter` is the Protocol's refusal path as it actually ships, and
        `n/a` is a different statement from `unknown`: one says the check ran and
        could not tell, the other that it does not apply to this agent. A reader
        triaging the block acts differently on each.
        """
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.hooks.builtins.session_start_preflight import auth_check

        result = auth_check(get_agent("null"), tmp_path, now=_NOW)

        assert result.status == "n/a"
        assert "null" in result.detail
        assert "credentials file" in result.detail

    def test_it_does_not_read_a_file_for_an_adapter_that_names_none(self, tmp_path: Path) -> None:
        """A planted Claude Code file must not be read for a non-Claude agent.

        Without this, an implementation that fell back to the old hardcoded
        filename would satisfy the assertion above on an empty directory and
        report a dead login on a populated one.
        """
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.hooks.builtins.session_start_preflight import auth_check

        _write_credentials(tmp_path, _credentials(int((_NOW - _HOUR) * 1000)))

        assert auth_check(get_agent("null"), tmp_path, now=_NOW).status == "n/a"

    def test_codex_cannot_be_spoken_for(self, tmp_path: Path) -> None:
        """The case the backlog entry opened with: a non-Claude profile used to
        report `unknown — could not read the credentials file`, which reads as a
        broken install rather than an unprobed one."""
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.hooks.builtins.session_start_preflight import auth_check

        result = auth_check(get_agent("codex"), tmp_path, now=_NOW)

        assert result.status == "n/a"
        assert "codex" in result.detail

    def test_claude_code_reads_the_file_the_adapter_names(self, tmp_path: Path) -> None:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.hooks.builtins.session_start_preflight import auth_check

        _write_credentials(tmp_path, _credentials(int((_NOW + 100 * _HOUR) * 1000)))

        result = auth_check(get_agent("claude-code"), tmp_path, now=_NOW, platform="linux")

        assert result.status == "pass"

    def test_claude_code_on_darwin_does_not_report_the_mirrors_verdict(
        self, tmp_path: Path
    ) -> None:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.hooks.builtins.session_start_preflight import auth_check

        _write_credentials(tmp_path, _credentials(int((_NOW - _HOUR) * 1000)))

        linux = auth_check(get_agent("claude-code"), tmp_path, now=_NOW, platform="linux")
        darwin = auth_check(get_agent("claude-code"), tmp_path, now=_NOW, platform="darwin")

        assert linux.status == "fail"
        assert darwin.status == "unknown"


class TestRender:
    def test_a_failing_check_is_visible_in_the_rendered_block(self) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import Check, render

        body = render([Check("auth", "fail", "refresh token expired 3 h ago")])
        assert "auth" in body
        assert "refresh token expired 3 h ago" in body

    def test_an_all_clear_block_stays_short(self) -> None:
        """A preflight nobody reads is worse than none. Quiet when clean."""
        from lazy_harness.hooks.builtins.session_start_preflight import Check, render

        body = render([Check("auth", "pass", "ok"), Check("git", "pass", "ok")])
        assert len(body.splitlines()) <= 3

    def test_returns_empty_when_there_is_nothing_to_say(self) -> None:
        from lazy_harness.hooks.builtins.session_start_preflight import render

        assert render([]) == ""

    def test_an_inapplicable_check_gets_a_line_rather_than_the_clear_tail(self) -> None:
        """`Clear:` asserts a check that ran. An `n/a` one did not.

        One line per session for a profile whose auth coverage is a known blind
        spot is the point: it disappears the moment that agent's credential
        shape is probed and the adapter starts naming a file.
        """
        from lazy_harness.hooks.builtins.session_start_preflight import Check, render

        body = render(
            [
                Check("auth", "n/a", "codex exposes no credentials file this check can read"),
                Check("git", "pass", "ok"),
            ]
        )

        assert "- **auth** [n/a] — codex exposes no credentials file this check can read" in body
        assert "- Clear: git." in body


def _run_hook(payload: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the *deployed* command, not `python -m <module>`.

    Trap 4 of the migration plan: a migrated module defines `main(event)` and
    has no `__main__` block, so `python -m` imports it, runs nothing and exits
    0 — the same exit code the working hook returns. Every assertion below
    would keep passing against a hook that had stopped doing anything at all.
    `lh hook <name>` is the command `settings.json` actually carries, and it is
    the only path on which the adapter's `format_hook_output` reaches stdout.
    """
    return subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "hook", "session-start-preflight"],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


class TestHookEntrypoint:
    @pytest.mark.parametrize(
        "payload",
        ["", "   ", "not json", "null", "42", "[]", '{"cwd": 5}', '{"session_id": null}'],
        ids=lambda v: repr(v)[:24],
    )
    def test_always_exits_0(self, payload: str) -> None:
        """SessionStart honours no verdict at all, so no payload may refuse.

        `BuiltinHookSpec.blocking` is `False` here, which is what puts an
        unparseable payload in decision 3's *informational* column: exit 0 with
        a warning on stderr rather than exit 2. A hook wired to an event the
        agent cannot block must never hand back a non-zero code, because the
        agent has nothing to do with it but log it.
        """
        assert _run_hook(payload).returncode == 0

    def test_emits_valid_hook_specific_output_or_nothing(self, tmp_path: Path) -> None:
        result = _run_hook({"hook_event_name": "SessionStart", "cwd": str(tmp_path)})
        assert result.returncode == 0
        if result.stdout.strip():
            parsed = json.loads(result.stdout)
            assert "hookSpecificOutput" in parsed
            assert "additionalContext" in parsed["hookSpecificOutput"]
