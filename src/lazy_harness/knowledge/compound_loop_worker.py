"""Compound-loop worker — runnable via `python -m`.

Processes queued tasks sequentially. Single-instance enforced with fcntl.flock
on a lock file in the queue directory. Called in the background by the Stop
hook; stdout/stderr are redirected by the caller to compound-loop.log.
"""

from __future__ import annotations

import fcntl
import os
import sys
from datetime import datetime
from pathlib import Path

from lazy_harness.core.config import CompoundLoopConfig, Config, ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.knowledge.compound_loop import (
    move_to_done,
    process_task,
)


def _log(log_file: Path, msg: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} worker: {msg}\n")
    except OSError:
        pass


def _rotate_log(log_file: Path, max_bytes: int = 102400, keep_lines: int = 500) -> None:
    try:
        if log_file.is_file() and log_file.stat().st_size > max_bytes:
            lines = log_file.read_text().splitlines()
            log_file.write_text("\n".join(lines[-keep_lines:]) + "\n")
    except OSError:
        pass


def _load_config() -> Config | None:
    cf = config_file()
    if not cf.is_file():
        return None
    try:
        return load_config(cf)
    except ConfigError:
        return None


def _resolve_learnings_dir(cfg: Config) -> Path:
    """Resolve where learnings .md files go.

    Preference order:
    1. LCT_LEARNINGS_DIR env var (back-compat with lazy-claudecode)
    2. <knowledge.path>/<compound_loop.learnings_subdir>
    """
    env_override = os.environ.get("LCT_LEARNINGS_DIR")
    if env_override:
        return Path(os.path.expanduser(env_override))
    knowledge_path = os.path.expanduser(cfg.knowledge.path or "")
    return Path(knowledge_path) / cfg.compound_loop.learnings_subdir


def _drain_queue(
    queue_dir: Path,
    cl_cfg: CompoundLoopConfig,
    learnings_dir: Path,
    log_file: Path,
) -> None:
    while True:
        pending = sorted(queue_dir.glob("*.task"))
        if not pending:
            break
        for task_file in pending:
            if not task_file.is_file():
                continue
            _log(log_file, f"processing {task_file.name}")
            try:
                outcome = process_task(task_file, cl_cfg, learnings_dir)
            except Exception as e:  # noqa: BLE001 — worker must not crash the queue
                _log(log_file, f"error processing {task_file.name}: {e}")
                move_to_done(queue_dir, task_file)
                continue

            if outcome.skipped:
                _log(log_file, f"skipped: {outcome.skipped}")
            elif outcome.wrote:
                _log(log_file, "wrote: " + "; ".join(outcome.wrote))
            else:
                _log(log_file, "nothing to persist")
            move_to_done(queue_dir, task_file)


def main() -> int:
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    log_dir = claude_dir / "logs"
    queue_dir = claude_dir / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "done").mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "compound-loop.log"
    _rotate_log(log_file)

    lock_path = queue_dir / ".worker.lock"
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as e:
        _log(log_file, f"lock open failed: {e}")
        return 1

    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _log(log_file, "another worker is running, exiting")
            return 0

        cfg = _load_config()
        if cfg is None or not cfg.compound_loop.enabled:
            _log(log_file, "disabled in config, exiting")
            return 0

        learnings_dir = _resolve_learnings_dir(cfg)
        _log(log_file, "started, checking queue")
        _drain_queue(queue_dir, cfg.compound_loop, learnings_dir, log_file)
        _log(log_file, "queue empty, exiting")
        return 0
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
