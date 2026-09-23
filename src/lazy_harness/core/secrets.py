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

**A file inside this directory is the declaration** (ADR-045). No file means the
profile takes its values from the global environment, which is the default
profile's ordinary case on every machine. A file that exists and cannot be read
means somebody said this profile carries its own account and the harness cannot
honour it — so the launch stops, rather than inheriting whichever account the
ambient environment happened to carry.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.paths import default_secrets_dir, expand_path, metrics_secrets_file


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


class SecretsError(Exception):
    """A profile's declared secrets file exists and could not be read.

    Deliberately not an `OSError`: the caller is `resolve_launch`, which turns
    every resolution failure into a `LaunchError` carrying a stable `kind`. A
    bare `OSError` escaping this module would reach `lh run` as a traceback
    from three frames down.
    """


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


def read_metrics_secret(name: str) -> str:
    """Read one name from the owner-only metrics secrets file, or return empty."""
    path = metrics_secrets_file()
    if not path.is_file():
        return ""

    try:
        mode = path.stat().st_mode
    except OSError:
        return ""

    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        _warn(
            f"{path} is mode {mode & 0o777:04o}; refusing to read it for "
            f"{name} (secrets files must be owner-only, e.g. chmod 600)"
        )
        return ""

    try:
        text = path.read_text()
    except OSError:
        return ""

    values = parse_env_file(text, source=path.name)
    return values.get(name, "").strip()


def overlay_profile_secrets(
    env: dict[str, str], profile: str, *, secrets_dir: Path
) -> dict[str, str]:
    """`env` with `<secrets_dir>/<profile>.env` laid over it.

    Returns a new mapping; the caller's is untouched, so one profile's token
    cannot leak into anything else running in this process.

    Raises `SecretsError` when the file exists and cannot be read or decoded.
    An absent file returns the environment unchanged — that is the default
    profile, not a failure. ADR-045 D2 records why the two are not one branch:
    availability is the right trade for a profile that never declared its own
    account, and the wrong one for a profile that did.
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

    # Keyed on the errno of the read, not on a prior `Path.is_file()`. That gate
    # raises before the read on Python <=3.13 and answers False on Python 3.14
    # when the parent cannot be traversed. Only the read's errno distinguishes
    # an absent file from one the profile declared but cannot access.
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # The default profile takes its values from the global environment and
        # has no file. That is the normal case.
        return result
    except (OSError, UnicodeDecodeError) as e:
        raise SecretsError(
            f"profile {profile!r} declares {path.name} and it cannot be read: {e}. "
            f"Fix the file or remove it; launching would authenticate as whichever "
            f"account the environment already carries."
        ) from e

    try:
        mode = path.stat().st_mode
    except OSError:  # pragma: no cover - the read above already succeeded
        mode = 0
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        # Refusing would not un-leak a secret that is already readable, and
        # would break the launch. Saying nothing would let it persist.
        _warn(f"{path.name} is mode {mode & 0o777:04o}; secrets files should be 0600")

    result.update(parse_env_file(raw, source=path.name))
    return result
