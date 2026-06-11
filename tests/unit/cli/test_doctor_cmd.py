"""Unit tests for lh doctor."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest
from click.testing import CliRunner

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
    '[knowledge]\npath = ""\n'
)


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_BASE_TOML)
    return cfg


def test_doctor_warns_when_ruff_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "ruff not found" in result.output.lower()


def test_doctor_does_not_warn_when_ruff_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr(
        "lazy_harness.cli.doctor_cmd.shutil.which",
        lambda name: "/opt/bin/ruff" if name == "ruff" else None,
    )
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "ruff not found" not in result.output.lower()


def test_doctor_renders_features_section(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import doctor
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    runner = CliRunner()
    result = runner.invoke(doctor, [])

    assert "Features" in result.output
    assert "qmd" in result.output
    assert "engram" in result.output
    assert "graphify" in result.output


def test_engram_persist_metrics_path_routes_through_agent_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ADR-032 L3: the metrics path must come from the agent adapter, not a
    hardcoded ~/.claude fallback."""
    from lazy_harness.agents.registry import NullAdapter
    from lazy_harness.cli.doctor_cmd import _engram_persist_metrics_path

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    result = _engram_persist_metrics_path(NullAdapter())

    assert result == home / ".null" / "logs" / "engram_persist_metrics.jsonl"


# --- LLM backend section (ADR-033) ---


def _recording_console():
    import io

    from rich.console import Console

    buf = io.StringIO()
    return Console(file=buf, force_terminal=False), buf


def test_render_llm_backend_claude_ok_when_binary_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import CompoundLoopConfig

    monkeypatch.setattr(
        "lazy_harness.cli.doctor_cmd.shutil.which",
        lambda name: "/opt/bin/claude" if name == "claude" else None,
    )
    console, buf = _recording_console()
    assert _render_llm_backend(console, CompoundLoopConfig()) is True
    assert "claude" in buf.getvalue()


def test_render_llm_backend_claude_missing_binary_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import CompoundLoopConfig

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    console, buf = _recording_console()
    assert _render_llm_backend(console, CompoundLoopConfig()) is True
    assert "not found" in buf.getvalue()


def test_render_llm_backend_ollama_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import CompoundLoopConfig

    captured: dict = {}

    def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        captured["url"] = url
        captured["timeout"] = kwargs.get("timeout")
        return object()

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.httpx.get", fake_get)
    console, buf = _recording_console()
    cfg = CompoundLoopConfig(backend="ollama")
    assert _render_llm_backend(console, cfg) is True
    assert captured["url"] == "http://localhost:11434"
    assert captured["timeout"] == 2
    assert "reachable" in buf.getvalue()


def test_render_llm_backend_unreachable_is_warning_not_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import CompoundLoopConfig

    def fake_get(url, **kwargs):  # noqa: ANN001, ANN003
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.httpx.get", fake_get)
    console, buf = _recording_console()
    cfg = CompoundLoopConfig(backend="mlx")
    assert _render_llm_backend(console, cfg) is True
    assert "not reachable" in buf.getvalue()


def test_render_llm_backend_unknown_backend_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli.doctor_cmd import _render_llm_backend
    from lazy_harness.core.config import CompoundLoopConfig

    console, buf = _recording_console()
    cfg = CompoundLoopConfig(backend="no-such-backend")
    assert _render_llm_backend(console, cfg) is False
    out = buf.getvalue()
    assert "no-such-backend" in out
    assert "ollama" in out


def test_doctor_output_includes_llm_backend_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    cfg = _write_config(tmp_path)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "LLM backend" in result.output


def test_render_memory_hygiene_skips_when_no_memory_dir(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, tmp_path / "missing") is True
    assert "Memory hygiene" not in buf.getvalue()


def test_render_memory_hygiene_reports_healthy_state(tmp_path: Path) -> None:
    from datetime import datetime

    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("\n".join(f"- line {i}" for i in range(10)) + "\n")
    (memory / "claude-md.proposal.md").write_text(
        "## 2026-06-10T09:00:00-03:00\n\n"
        "- **Rule:** keep it simple\n"
        "  - **Rationale:** because\n"
    )
    (memory / "claude-md.accepted.md").write_text("- **Rule:** old accepted rule\n")
    (memory / "claude-md.rejected.md").write_text("- **Rule:** old rejected rule\n")

    console, buf = _recording_console()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assert _render_memory_hygiene(console, memory, now=now) is True
    out = buf.getvalue()
    assert "Memory hygiene" in out
    assert "10/200" in out
    assert "1 pending" in out
    assert "1 accepted" in out
    assert "1 rejected" in out


def test_render_memory_hygiene_warns_near_memory_cap(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("\n".join(f"- line {i}" for i in range(185)) + "\n")

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, memory) is True
    assert "185/200" in buf.getvalue()
    assert "!" in buf.getvalue()


def test_render_memory_hygiene_fails_over_memory_cap(tmp_path: Path) -> None:
    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("\n".join(f"- line {i}" for i in range(205)) + "\n")

    console, buf = _recording_console()
    assert _render_memory_hygiene(console, memory) is False
    assert "205/200" in buf.getvalue()


def test_render_memory_hygiene_warns_on_stale_pending_proposals(tmp_path: Path) -> None:
    from datetime import datetime

    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "## 2026-05-01T10:00:00-03:00\n\n"
        "- **Rule:** stale rule\n"
        "  - **Rationale:** old\n"
    )

    console, buf = _recording_console()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    assert _render_memory_hygiene(console, memory, now=now) is True
    out = buf.getvalue()
    assert "1 pending" in out
    assert "41d" in out
    assert "lh memory proposals" in out
