"""Per-profile secrets, overlaid onto the environment at launch.

The agent's credential is one global environment variable, and its stored
credentials live inside the profile's `config_dir`. Two profiles backed by two
accounts therefore cannot share one value, and a second entry in the user's
global environment replaces the first rather than sitting beside it.

Without this, launching the second profile authenticates as the first
account — with no error, and no visible difference until something is written
under the wrong identity.

Resolution is by precedence, not by merging: the file's values are laid over
the inherited environment, so the selection happens on its own.

The file format and its `0600` mode are a contract with whatever provisions the
machine. Changing either is a coordinated change, not a local one.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.paths import default_secrets_dir, expand_path


def secrets_dir_for(cfg: Config) -> Path:
    """Where per-profile secret files live.

    Honours `[secrets] dir` before falling back to `default_secrets_dir()`
    (`<config dir>/secrets`), which is the same order every other
    config-derived path in this repo resolves in. Two readers disagreeing
    about a path is how one of them ends up writing a file nothing reads.
    """
    if cfg.secrets.dir:
        return expand_path(cfg.secrets.dir)
    return default_secrets_dir()


def _warn(message: str) -> None:
    print(f"lh: {message}", file=sys.stderr)


def parse_env_file(text: str, *, source: str = "") -> dict[str, str]:
    """Parse `KEY=VALUE` lines, skipping comments and blanks.

    Deliberately not a shell: no interpolation, no `export`, no line
    continuations. The provisioner writes plain assignments, and a parser that
    accepted more would quietly diverge from what systemd's `environment.d`
    reads on the same machine.
    """
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            _warn(f"{source or 'secrets'}:{number}: not a KEY=VALUE assignment, skipped")
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def overlay_profile_secrets(
    env: dict[str, str], profile: str, *, secrets_dir: Path
) -> dict[str, str]:
    """`env` with `<secrets_dir>/<profile>.env` laid over it.

    Returns a new mapping; the caller's is untouched, so one profile's token
    cannot leak into anything else running in this process.

    Every failure degrades to "no overlay" with a message on stderr rather than
    raising: the caller is about to exec the agent, and a permissions problem
    on one profile's secrets is not a reason to produce a traceback instead.
    """
    result = dict(env)

    path = secrets_dir / f"{profile}.env"
    # A profile name is configuration, not user input, but a path built by
    # concatenation is worth closing anyway.
    try:
        # Resolved, not lexical: `relative_to` compares path components, so
        # `<dir>/../escaped.env` is "inside <dir>" as far as it is concerned.
        path.resolve().relative_to(secrets_dir.resolve())
    except (ValueError, OSError):
        _warn(f"profile {profile!r} names a secrets file outside {secrets_dir}, ignored")
        return result

    if not path.is_file():
        # The default profile takes its values from the global environment and
        # has no file. That is the normal case.
        return result

    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            # Refusing would not un-leak a secret that is already readable, and
            # would break the launch. Saying nothing would let it persist.
            _warn(f"{path.name} is mode {mode & 0o777:04o}; secrets files should be 0600")
        result.update(parse_env_file(path.read_text(), source=path.name))
    except OSError as e:
        _warn(f"could not read {path.name}: {e}")

    return result
