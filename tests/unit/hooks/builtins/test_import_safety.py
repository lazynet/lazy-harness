"""Import-safety contract for builtin hooks (ADR-006).

Builtin hooks are invoked by the agent as bare scripts (``python <path>``).
When the lazy_harness package is broken or not importable in that
interpreter, the hook must silently no-op (exit 0, no traceback) — it must
never block the agent's session lifecycle.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BUILTINS_DIR = Path(__file__).parents[4] / "src" / "lazy_harness" / "hooks" / "builtins"

# Hooks whose ImportError guard must cover every lazy_harness import.
GUARDED_HOOKS = [
    "compound_loop",
    "context_inject",
    "post_compact",
    "pre_compact",
    "session_end",
    "session_export",
    "user_prompt_goal",
]

# Payload that drives each hook past its early exits and into the imports the
# guard has to cover. A hook fed `{}` may return before importing anything,
# which would make this suite pass without exercising the guard at all.
_PAYLOADS = {
    "user_prompt_goal": '{"session_id": "s1", "prompt": "fix db.py", "cwd": "."}',
}


@pytest.mark.parametrize("hook_name", GUARDED_HOOKS)
def test_hook_exits_zero_when_lazy_harness_not_importable(tmp_path: Path, hook_name: str) -> None:
    poison = tmp_path / "poison"
    (poison / "lazy_harness").mkdir(parents=True)
    (poison / "lazy_harness" / "__init__.py").write_text(
        'raise ImportError("simulated broken install")\n'
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(poison)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude")

    result = subprocess.run(
        [sys.executable, str(BUILTINS_DIR / f"{hook_name}.py")],
        input=_PAYLOADS.get(hook_name, "{}"),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
