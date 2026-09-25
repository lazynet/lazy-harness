"""Isolation boundaries exercised through their shipping consumers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, ConfigError, ProfileEntry, load_config, save_config
from lazy_harness.hooks import runner
from lazy_harness.hooks.builtins.context_inject import last_session_context, qmd_suggest_context
from lazy_harness.knowledge import qmd
from lazy_harness.knowledge.session_export import export_session


@pytest.mark.parametrize(
    "agent,marker,code", [("claude-code", "prompt_id", 2), ("codex", "turn_id", 0)]
)
@pytest.mark.parametrize("explicit", [True, False])
def test_unknown_profile_never_dispatches_builtin(
    tmp_path, monkeypatch, agent, marker, code, explicit
):
    cfg = Config()
    cfg.profiles.items = {
        "personal": ProfileEntry(agent=agent),
        "work": ProfileEntry(agent=agent),
    }
    cfg.profiles.default = "personal"
    save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("lazy_harness.hooks.builtins._shared.profile_name", lambda: "work-old")
    dispatch = Mock(side_effect=AssertionError("must not dispatch"))
    monkeypatch.setattr(runner, "_load_main", dispatch)
    args = ["hook", "pre-tool-use-security"]
    if explicit:
        args += ["--profile", "work-old"]
    result = CliRunner().invoke(
        cli,
        args,
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                marker: "id",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "cwd": str(tmp_path),
            }
        ),
    )
    assert result.exit_code == code, result.output
    assert "work-old" in result.stderr
    dispatch.assert_not_called()
    if agent == "codex":
        body = json.loads(result.stdout)["hookSpecificOutput"]
        assert body["hookEventName"] == "PreToolUse"
        assert body["permissionDecision"] == "deny"
        assert "work-old" in body["permissionDecisionReason"]
    else:
        assert result.stdout == ""


def test_unknown_profile_informational_hook_does_not_inject(tmp_path, monkeypatch):
    cfg = Config()
    cfg.profiles.items["personal"] = ProfileEntry()
    save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    dispatch = Mock()
    monkeypatch.setattr(runner, "_load_main", dispatch)
    result = runner.run_hook(
        "context-inject",
        profile="work-old",
        stdin_text=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "prompt_id": "id",
            }
        ),
    )
    assert result.exit_code == 0
    assert result.stdout is None
    assert "work-old" in result.stderr
    dispatch.assert_not_called()


@pytest.mark.parametrize("existing", [False, True])
def test_qmd_profile_scope_round_trip(tmp_path, existing):
    path = tmp_path / "config.toml"
    if existing:
        path.write_text('[harness]\nversion = "1"\n# retained\n[profiles.work]\nroots = []\n')
    cfg = load_config(path) if existing else Config()
    cfg.profiles.items["work"] = ProfileEntry(qmd_collection="work-notes")
    cfg.profiles.items["personal"] = ProfileEntry()
    for _ in range(2):
        save_config(cfg, path)
        cfg = load_config(path)
        assert cfg.profiles.items["work"].qmd_collection == "work-notes"
        assert cfg.profiles.items["personal"].qmd_collection == ""
    cfg.profiles.items["work"].qmd_collection = ""
    save_config(cfg, path)
    assert load_config(path).profiles.items["work"].qmd_collection == ""
    if existing:
        assert "# retained" in path.read_text()


@pytest.mark.parametrize("value", ['"--all"', '"work/notes"', '" "', "7", "[]", "true"])
def test_invalid_qmd_collection_names_the_profile_and_value(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(f'[harness]\nversion = "1"\n[profiles.work]\nqmd_collection = {value}\n')
    with pytest.raises(ConfigError, match=r"profiles.work.*qmd_collection") as exc:
        load_config(path)
    assert "unknown field" not in str(exc.value)


def test_automatic_suggestions_without_scope_do_not_search(monkeypatch):
    search = Mock(return_value=[qmd.QmdHit("qmd://personal/a.md", "Private", 1)])
    monkeypatch.setattr(qmd, "query", search)
    assert qmd_suggest_context("main") == ""
    search.assert_not_called()


def test_scoped_qmd_query_rejects_foreign_results_before_limiting(monkeypatch):
    results = [
        {"file": file, "title": file, "score": 1}
        for file in (
            "qmd://personal/private.md",
            "qmd://work-other/a.md",
            "/tmp/work/a.md",
            "qmd://work/a.md",
        )
    ]
    search = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(results), ""))
    monkeypatch.setattr(qmd.subprocess, "run", search)
    hits = qmd.query("main", limit=1, collection="work")
    assert [hit.file for hit in hits] == ["qmd://work/a.md"]
    assert search.call_args.args[0] == ["qmd", "search", "main", "--json", "--collection", "work"]


@pytest.mark.parametrize(
    "profile,expected", [("work", "work-notes"), ("personal", "personal-notes"), ("unscoped", None)]
)
def test_session_start_uses_invoked_profile_scope(tmp_path, monkeypatch, profile, expected):
    cfg = Config()
    cfg.profiles.items = {
        name: ProfileEntry(config_dir=str(tmp_path / name), qmd_collection=scope)
        for name, scope in (
            ("work", "work-notes"),
            ("personal", "personal-notes"),
            ("unscoped", ""),
        )
    }
    cfg.profiles.default = "personal"
    save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        "lazy_harness.hooks.builtins.context_inject.git_context", lambda _: "Branch: main"
    )
    search = Mock(return_value=[])
    monkeypatch.setattr(qmd, "query", search)
    result = runner.run_hook(
        "context-inject",
        profile=profile,
        stdin_text=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "cwd": str(tmp_path),
            }
        ),
    )
    assert result.exit_code == 0
    assert result.stderr == ""
    if expected:
        search.assert_called_once_with("main", limit=3, timeout=5, collection=expected)
    else:
        search.assert_not_called()


def _session(path: Path, **metadata: str) -> None:
    path.write_text("---\n" + yaml.safe_dump(metadata) + "---\n\n## User\n\nselected sentinel\n")


@pytest.mark.parametrize(
    "metadata",
    [
        {"project": "api-admin", "profile": "personal"},
        {"project": "api", "profile": "work"},
        {"project_key": "github.com/other/api", "source_identity": "work"},
        {"project_key": "github.com/team/api-admin", "source_identity": "work"},
        {"project_key": "github.com/team/api", "source_identity": "personal"},
        {"project_key": "github.com/team/api"},
        {"project_key": "github.com/team/api", "source_profile": "work"},
    ],
)
def test_last_session_rejects_ambiguous_or_foreign_metadata(tmp_path, metadata):
    _session(tmp_path / "session.md", **metadata)
    assert last_session_context(tmp_path, "github.com/team/api", identity="work") == ""


def test_unscoped_legacy_name_is_never_authoritative(tmp_path):
    _session(tmp_path / "session.md", project="api-admin", profile="personal")
    assert last_session_context(tmp_path, "api") == ""


def test_unscoped_project_key_is_never_authoritative(tmp_path):
    _session(tmp_path / "session.md", project_key="api", source_identity="work")
    assert last_session_context(tmp_path, "api", identity="work") == ""


@pytest.mark.parametrize(
    "text", ["null", "7", "[]", "{bad", "project_key: github.com/team/api\nsource_profile: [work]"]
)
def test_last_session_rejects_invalid_frontmatter(tmp_path, text):
    (tmp_path / "session.md").write_text(f"---\n{text}\n---\n## User\nprivate\n")
    assert last_session_context(tmp_path, "github.com/team/api", identity="work") == ""


def test_last_session_ignores_identity_in_body(tmp_path):
    (tmp_path / "session.md").write_text(
        "---\nproject: elsewhere\n---\nproject_key: github.com/team/api\nsource_identity: work\n"
    )
    assert last_session_context(tmp_path, "github.com/team/api", identity="work") == ""


@pytest.mark.parametrize("remote", [True, False])
def test_export_metadata_round_trips_through_session_lookup(git_checkout, tmp_path, remote):
    repo = git_checkout.repo
    if remote:
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
            cwd=repo,
            check=True,
        )
    session = tmp_path / "session.jsonl"
    session.write_text(
        "\n".join(
            json.dumps(entry)
            for entry in [
                {
                    "type": "system",
                    "cwd": str(git_checkout.worktree),
                    "timestamp": "2026-09-25T10:00:00",
                },
                {"type": "user", "message": {"content": "roundtrip sentinel"}},
            ]
        )
    )
    output = tmp_path / "exports"
    path, reason = export_session(
        session, output, force=True, source_profile="work", source_identity="work"
    )
    assert path is not None and reason is None
    metadata = yaml.safe_load(path.read_text().split("---")[1])
    key = "github.com/team/api" if remote else f"local/{repo.name}"
    assert metadata["project_key"] == key
    assert metadata["source_profile"] == "work"
    assert metadata["project_root"] == str(repo.resolve())
    result = last_session_context(output, key, identity="work", project_root=repo)
    assert "roundtrip sentinel" in result
    assert last_session_context(output, key, identity="personal", project_root=repo) == ""
    if not remote:
        assert (
            last_session_context(
                output, key, identity="work", project_root=tmp_path / "other" / repo.name
            )
            == ""
        )
        assert last_session_context(output, key, identity="work") == ""


def test_export_without_recorded_cwd_cannot_infer_scope_from_directory(tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text(json.dumps({"type": "user", "message": {"content": "legacy sentinel"}}))
    path, _ = export_session(
        session, tmp_path / "exports", force=True, source_profile="work", source_identity="work"
    )
    assert path is not None
    metadata = yaml.safe_load(path.read_text().split("---")[1])
    assert metadata["project_key"] == ""
    assert metadata["project_root"] == ""


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_export_hook_and_session_start_share_canonical_scope(
    git_checkout, tmp_path, monkeypatch, agent
):
    from lazy_harness.knowledge.marker import write_marker

    cfg = Config()
    cfg.profiles.items = {
        name: ProfileEntry(config_dir=str(tmp_path / name), agent=adapter, identity=identity)
        for name, adapter, identity in (
            ("claude-work", "claude-code", "work"),
            ("codex-work", "codex", "work"),
            ("claude-personal", "claude-code", "personal"),
            ("codex-personal", "codex", "personal"),
        )
    }
    cfg.knowledge.root = str(tmp_path / "knowledge")
    write_marker(Path(cfg.knowledge.root))
    save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("lazy_harness.hooks.builtins.session_export.shutil.which", lambda _: None)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=git_checkout.repo,
        check=True,
    )
    session = tmp_path / "transcript.jsonl"
    session.write_text(
        "\n".join(
            json.dumps(entry)
            for entry in [
                {"type": "permission-mode"},
                {
                    "type": "system",
                    "cwd": str(git_checkout.worktree),
                    "timestamp": "2026-09-25T10:00:00",
                },
                *[{"type": "user", "message": {"content": "exported sentinel"}} for _ in range(4)],
            ]
        )
    )
    if agent == "codex":
        session.write_text(
            "\n".join(
                json.dumps(entry)
                for entry in [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-09-25T10:00:00Z",
                        "payload": {
                            "id": "session",
                            "cwd": str(git_checkout.worktree),
                            "cli_version": "test",
                        },
                    },
                    *[
                        {
                            "type": "response_item",
                            "timestamp": "2026-09-25T10:00:01Z",
                            "payload": {
                                "type": "message",
                                "role": role,
                                "content": [
                                    {
                                        "type": "input_text" if role == "user" else "output_text",
                                        "text": "exported sentinel",
                                    }
                                ],
                            },
                        }
                        for role in ("user", "assistant", "user", "assistant")
                    ],
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "developer",
                            "content": [
                                {"type": "input_text", "text": "private system instructions"}
                            ],
                        },
                    },
                ]
            )
        )
    source_profile = "claude-work" if agent == "claude-code" else "codex-work"
    result = runner.run_hook(
        "session-export",
        profile=source_profile,
        stdin_text=json.dumps(
            {
                "hook_event_name": "Stop",
                "cwd": str(git_checkout.worktree),
                "transcript_path": str(session),
            }
        ),
    )
    assert result.exit_code == 0 and result.stderr == ""
    exported = list((Path(cfg.knowledge.root) / "sessions").rglob("*.md"))
    assert len(exported) == 1
    metadata = yaml.safe_load(exported[0].read_text().split("---")[1])
    assert metadata["source_profile"] == source_profile
    assert metadata["source_identity"] == "work"
    assert "private system instructions" not in exported[0].read_text()
    if agent == "codex":
        assert metadata["type"] == "codex-session"
    for cwd in (git_checkout.repo, git_checkout.worktree, git_checkout.subdir):
        for profile in cfg.profiles.items:
            result = runner.run_hook(
                "context-inject",
                profile=profile,
                stdin_text=json.dumps(
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": str(cwd),
                    }
                ),
            )
            assert result.exit_code == 0 and result.stderr == ""
            assert ("exported sentinel" in (result.stdout or "")) == profile.endswith("-work")
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/other/api.git"],
        cwd=git_checkout.repo,
        check=True,
    )
    result = runner.run_hook(
        "context-inject",
        profile=source_profile,
        stdin_text=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "cwd": str(git_checkout.repo),
            }
        ),
    )
    assert "exported sentinel" not in (result.stdout or "")


def test_unknown_profile_refuses_even_if_native_formatter_fails(tmp_path, monkeypatch):
    cfg = Config()
    cfg.profiles.items["personal"] = ProfileEntry()
    save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        "lazy_harness.agents.codex.CodexAdapter.format_hook_output",
        Mock(side_effect=RuntimeError("broken")),
    )
    result = runner.run_hook(
        "pre-tool-use-security",
        profile="work-old",
        stdin_text=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "turn_id": "id",
            }
        ),
    )
    assert result.exit_code == 2
    assert "work-old" in result.stderr


def test_missing_knowledge_marker_never_scans_working_directory(tmp_path, monkeypatch):
    cfg = Config()
    cfg.profiles.items["work"] = ProfileEntry(config_dir=str(tmp_path / "agent"))
    cfg.knowledge.root = str(tmp_path / "missing")
    save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    lookup = Mock(return_value="")
    monkeypatch.setattr("lazy_harness.hooks.builtins.context_inject.last_session_context", lookup)
    result = runner.run_hook(
        "context-inject",
        profile="work",
        stdin_text=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "cwd": str(tmp_path),
            }
        ),
    )
    assert result.exit_code == 0
    lookup.assert_not_called()


@pytest.mark.parametrize(
    "record",
    [None, 7, [], {"type": "session_meta", "payload": None}, {"type": "user", "message": 7}],
)
def test_export_skips_wrong_json_types(tmp_path, record):
    session = tmp_path / "session.jsonl"
    session.write_text(
        json.dumps(record)
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "valid sentinel"}})
    )
    path, _ = export_session(session, tmp_path / "exports", force=True)
    assert path is not None
    assert "valid sentinel" in path.read_text()


def test_export_session_id_cannot_escape_destination(tmp_path):
    session = tmp_path / "safe.jsonl"
    session.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {
                    "type": "session_meta",
                    "timestamp": "2026-09-25T10:00:00Z",
                    "payload": {"id": "../../escape", "cwd": str(tmp_path)},
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "valid sentinel"}],
                    },
                },
            ]
        )
    )
    output = tmp_path / "exports"
    path, _ = export_session(session, output, force=True)
    assert path is not None and path.name == "2026-09-25-safe.md"
    assert path.is_relative_to(output)
