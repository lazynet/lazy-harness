"""Every former `profiles/<name>` call site, exercised with two profiles that
share an identity: both must read the one `profiles/<identity>/` directory.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.artifact_version import collect_artifact_version_reports
from lazy_harness.core.config import Config, ProfileEntry


def _shared_identity_cfg(home: Path) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "claude-gate"
    cfg.profiles.items = {
        "claude-gate": ProfileEntry(config_dir=str(home / "claude-home"), identity="gate"),
        "codex-gate": ProfileEntry(
            config_dir=str(home / "codex-home"), agent="codex", identity="gate"
        ),
    }
    return cfg


def _seed_shared_source() -> Path:
    from lazy_harness.core.paths import config_dir

    src = config_dir() / "profiles" / "gate"
    (src / "claude-code").mkdir(parents=True)
    (src / "claude-code" / "settings.json").write_text("{}")
    (src / "codex").mkdir(parents=True)
    (src / "codex" / "AGENTS-extra.md").write_text("codex")
    (src / "CLAUDE.md").write_text("lh_version 0.0.0\n")
    (src / "AGENTS.md").write_text("lh_version 0.0.0\n")
    return src


def test_deploy_profiles_reads_both_agents_from_one_identity_dir(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    _seed_shared_source()
    cfg = _shared_identity_cfg(home_dir)

    deploy_profiles(cfg)

    assert (home_dir / "claude-home" / "settings.json").is_symlink()
    assert (home_dir / "codex-home" / "AGENTS-extra.md").is_symlink()
    assert not (home_dir / "codex-home" / "settings.json").exists()


def test_snapshot_targets_reads_both_agents_from_one_identity_dir(home_dir: Path) -> None:
    from lazy_harness.deploy.snapshot import snapshot_targets

    _seed_shared_source()
    cfg = _shared_identity_cfg(home_dir)

    targets = snapshot_targets(cfg)

    assert any(t.name == "settings.json" for t in targets)


def test_artifact_version_reports_read_the_doc_from_the_identity_dir(home_dir: Path) -> None:
    _seed_shared_source()
    cfg = _shared_identity_cfg(home_dir)
    from lazy_harness.core.paths import config_dir

    reports = collect_artifact_version_reports(cfg, config_dir() / "profiles")

    doc_reports = {r.profile: r for r in reports if r.kind in ("CLAUDE.md", "AGENTS.md")}
    assert "claude-gate" in doc_reports
    assert "codex-gate" in doc_reports
