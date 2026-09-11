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


def _run_hook(payload: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "lazy_harness.hooks.builtins.session_start_preflight"],
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
        """SessionStart has no blocking semantics. Every path exits 0."""
        assert _run_hook(payload).returncode == 0

    def test_emits_valid_hook_specific_output_or_nothing(self, tmp_path: Path) -> None:
        result = _run_hook({"hook_event_name": "SessionStart", "cwd": str(tmp_path)})
        assert result.returncode == 0
        if result.stdout.strip():
            parsed = json.loads(result.stdout)
            assert "hookSpecificOutput" in parsed
            assert "additionalContext" in parsed["hookSpecificOutput"]
