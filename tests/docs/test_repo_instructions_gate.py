"""This repository is the first pilot of ADR-060, and it gates itself."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.repo_instructions import check_repository

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_this_repository_passes_its_own_instruction_gate() -> None:
    findings = check_repository(REPO_ROOT)

    assert findings == [], "\n".join(f"{f.path}: {f.code} — {f.detail}" for f in findings)


def test_this_repository_has_no_claude_md_shadow() -> None:
    assert not (REPO_ROOT / "CLAUDE.md").exists()
