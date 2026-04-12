from __future__ import annotations

import tempfile
from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_knowledge(*, config_path: Path) -> list[CheckResult]:
    """Verify knowledge path exists, is writable, and expected subdirs are present."""
    results: list[CheckResult] = []
    group = "knowledge"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name="load", status=CheckStatus.FAILED, message=str(e))]

    if not cfg.knowledge.path:
        return [
            CheckResult(
                group=group,
                name="path",
                status=CheckStatus.PASSED,
                message="knowledge path not configured",
            )
        ]

    knowledge_path = Path(cfg.knowledge.path).expanduser()

    if not knowledge_path.is_dir():
        results.append(
            CheckResult(
                group=group,
                name="path:exists",
                status=CheckStatus.FAILED,
                message=f"{knowledge_path} does not exist",
            )
        )
        return results
    results.append(CheckResult(group=group, name="path:exists", status=CheckStatus.PASSED))

    try:
        with tempfile.NamedTemporaryFile(dir=knowledge_path, delete=True):
            pass
        results.append(CheckResult(group=group, name="path:writable", status=CheckStatus.PASSED))
    except OSError as e:
        results.append(
            CheckResult(
                group=group,
                name="path:writable",
                status=CheckStatus.FAILED,
                message=f"not writable: {e}",
            )
        )

    for subdir in ("sessions", "learnings"):
        if (knowledge_path / subdir).is_dir():
            results.append(
                CheckResult(group=group, name=f"subdir:{subdir}", status=CheckStatus.PASSED)
            )
        else:
            results.append(
                CheckResult(
                    group=group,
                    name=f"subdir:{subdir}",
                    status=CheckStatus.WARNING,
                    message=f"{subdir}/ missing (will be auto-created)",
                )
            )

    return results
