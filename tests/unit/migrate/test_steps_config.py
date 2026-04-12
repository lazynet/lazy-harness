from pathlib import Path

from lazy_harness.migrate.state import LazyClaudecodeSetup, StepStatus
from lazy_harness.migrate.steps.config_step import GenerateConfigStep


def test_generate_config_writes_toml_with_profiles(tmp_path: Path):
    lazy_dir = tmp_path / ".claude-lazy"
    flex_dir = tmp_path / ".claude-flex"
    for d in (lazy_dir, flex_dir):
        d.mkdir()

    detected = LazyClaudecodeSetup(
        profiles=["lazy", "flex"],
        claude_dirs={"lazy": lazy_dir, "flex": flex_dir},
        skills_dirs={},
        settings_paths={},
    )

    out = tmp_path / "config" / "config.toml"
    step = GenerateConfigStep(
        target=out,
        lazy_claudecode=detected,
        knowledge_path=tmp_path / "knowledge",
    )
    result = step.execute(backup_dir=tmp_path / "backup", dry_run=False)

    assert result.status == StepStatus.DONE
    content = out.read_text()
    assert "[profiles.lazy]" in content
    assert "[profiles.flex]" in content
    assert "claude-code" in content


def test_generate_config_no_profiles_fallback_to_personal(tmp_path: Path):
    out = tmp_path / "config.toml"
    step = GenerateConfigStep(
        target=out,
        lazy_claudecode=None,
        knowledge_path=tmp_path / "knowledge",
    )
    result = step.execute(backup_dir=tmp_path / "backup", dry_run=False)
    assert result.status == StepStatus.DONE
    assert "[profiles.personal]" in out.read_text()


def test_generate_config_dry_run_no_write(tmp_path: Path):
    out = tmp_path / "config.toml"
    step = GenerateConfigStep(
        target=out,
        lazy_claudecode=None,
        knowledge_path=tmp_path / "knowledge",
    )
    result = step.execute(backup_dir=tmp_path / "backup", dry_run=True)
    assert result.status == StepStatus.DONE
    assert not out.exists()
