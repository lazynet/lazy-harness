from pathlib import Path

from lazy_harness.migrate.planner import build_plan
from lazy_harness.migrate.state import (
    DeployedScript,
    DetectedState,
    LazyClaudecodeSetup,
)


def test_build_plan_empty_state(tmp_path: Path):
    state = DetectedState()
    plan = build_plan(
        state,
        backup_dir=tmp_path / "bk",
        target_config=tmp_path / "cfg.toml",
        knowledge_path=tmp_path / "knowledge",
    )
    names = [s.name for s in plan.steps]
    assert "backup" in names
    assert "generate-config" in names
    assert "remove-scripts" not in names  # no scripts detected


def test_build_plan_full_state(tmp_path: Path):
    lazy = tmp_path / ".claude-lazy"
    lazy.mkdir()
    state = DetectedState(
        lazy_claudecode=LazyClaudecodeSetup(
            profiles=["lazy"],
            claude_dirs={"lazy": lazy},
            skills_dirs={},
            settings_paths={},
        ),
        deployed_scripts=[
            DeployedScript(name="lcc-x", symlink=tmp_path / "lcc-x", target=None),
        ],
    )
    plan = build_plan(
        state,
        backup_dir=tmp_path / "bk",
        target_config=tmp_path / "cfg.toml",
        knowledge_path=tmp_path / "knowledge",
    )
    names = [s.name for s in plan.steps]
    assert names[0] == "backup"
    assert "generate-config" in names
    assert "remove-scripts" in names
