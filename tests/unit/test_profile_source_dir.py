"""`profile_source_dir` — the one place every `profiles/<name>` join resolves
through, keyed by identity rather than profile name.
"""

from __future__ import annotations

import re
from pathlib import Path

import lazy_harness
from lazy_harness.core.config import AgentConfig, Config, ProfileEntry, ProfilesConfig
from lazy_harness.core.profile_identity import profile_source_dir


def _cfg(**profiles: dict) -> Config:
    items = {
        name.replace("_", "-"): ProfileEntry(**{k: v for k, v in kwargs.items()})
        for name, kwargs in profiles.items()
    }
    cfg = Config()
    cfg.agent = AgentConfig(type="claude-code")
    cfg.profiles = ProfilesConfig(default=next(iter(items)), items=items)
    return cfg


def test_source_dir_is_keyed_by_identity(tmp_path: Path) -> None:
    cfg = _cfg(
        claude_personal=dict(identity="personal"),
        codex_personal=dict(identity="personal", agent="codex"),
    )
    assert profile_source_dir(cfg, "claude-personal", tmp_path) == tmp_path / "personal"
    assert profile_source_dir(cfg, "codex-personal", tmp_path) == tmp_path / "personal"


def test_source_dir_without_identity_is_the_name(tmp_path: Path) -> None:
    cfg = _cfg(p1=dict())
    assert profile_source_dir(cfg, "p1", tmp_path) == tmp_path / "p1"


def test_source_dir_for_unknown_name_falls_back_to_the_name(tmp_path: Path) -> None:
    cfg = _cfg(p1=dict())
    assert profile_source_dir(cfg, "ghost", tmp_path) == tmp_path / "ghost"


def test_no_stray_profile_joins_in_src() -> None:
    """Any `"profiles" / <var>`-style join outside the helper is a regression:
    the fix is to resolve through `profile_source_dir` (or `profile_identity`
    when only an `entry` is in scope), never by re-deriving the join.
    """
    pattern = re.compile(
        r'(profiles_src|profiles_dir|"profiles")\s*/\s*(name|profile|entry\.name)\b'
    )
    src = Path(lazy_harness.__file__).parent
    hits = [
        f"{p}:{i}"
        for p in src.rglob("*.py")
        if p.name != "profile_identity.py"
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []
