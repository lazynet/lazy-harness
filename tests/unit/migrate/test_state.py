from pathlib import Path

from lazy_harness.migrate.state import ClaudeCodeSetup, DetectedState


def test_detected_state_defaults_empty():
    state = DetectedState()
    assert state.claude_code is None
    assert state.lazy_claudecode is None
    assert state.lazy_harness_config is None
    assert state.deployed_scripts == []
    assert state.launch_agents == []
    assert state.knowledge_paths == []
    assert state.qmd_available is False
    assert state.has_existing_setup() is False


def test_has_existing_setup_true_when_any_field_present(tmp_path: Path):
    state = DetectedState(claude_code=ClaudeCodeSetup(path=tmp_path))
    assert state.has_existing_setup() is True
