from __future__ import annotations

import errno
import tempfile
from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.knowledge.marker import MarkerError, read_marker, resolve_root
from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_knowledge(*, config_path: Path) -> list[CheckResult]:
    """Verify knowledge path exists, is writable, and expected subdirs are present."""
    results: list[CheckResult] = []
    group = "knowledge"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name="load", status=CheckStatus.FAILED, message=str(e))]

    knowledge_path = resolve_root(cfg.knowledge.root or None)

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
        # EACCES/EPERM here is this environment refusing the probe write,
        # not proof the configured root is actually broken — same
        # unverifiable-vs-genuine split as `monitoring_check`'s db-path
        # probe. Anything else (ENOSPC, …) is a real finding.
        if e.errno in (errno.EACCES, errno.EPERM):
            results.append(
                CheckResult(
                    group=group,
                    name="path:writable",
                    status=CheckStatus.WARNING,
                    message=f"cannot verify write access (permission denied): {e}",
                )
            )
        else:
            results.append(
                CheckResult(
                    group=group,
                    name="path:writable",
                    status=CheckStatus.FAILED,
                    message=f"not writable: {e}",
                )
            )

    try:
        marker = read_marker(knowledge_path)
    except MarkerError as e:
        results.append(
            CheckResult(group=group, name="marker", status=CheckStatus.FAILED, message=str(e))
        )
        return results
    results.append(CheckResult(group=group, name="marker", status=CheckStatus.PASSED))

    for subdir in (marker.sessions, marker.learnings):
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
