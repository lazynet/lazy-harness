import json
from pathlib import Path

import pytest

from lazy_harness.migrate.state import StepStatus
from lazy_harness.migrate.steps.backup import (
    BACKUP_MANIFEST_NAME,
    BackupManifestError,
    BackupStep,
    find_backup_entry,
    read_backup_manifest,
)


def test_backup_step_copies_files(tmp_path: Path):
    src1 = tmp_path / "file1.txt"
    src1.write_text("hello")
    src2_dir = tmp_path / "subdir"
    src2_dir.mkdir()
    (src2_dir / "nested.txt").write_text("nested")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[src1, src2_dir])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.DONE
    file_entry = find_backup_entry(backup_dir, src1)
    assert file_entry is not None
    assert (backup_dir / file_entry["content"]).read_text() == "hello"
    dir_entry = find_backup_entry(backup_dir, src2_dir)
    assert dir_entry is not None
    assert (backup_dir / dir_entry["content"] / "nested.txt").read_text() == "nested"


def test_backup_step_preserves_source_identity_across_basename_collision(tmp_path: Path):
    """Two distinct sources sharing a basename must both survive intact.

    Reproduces the confirmed bug: `dest = backup_dir / t.name` let the second
    `settings.json` silently clobber the first in the backup store.
    """
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    (one / "settings.json").write_text('{"profile": "one"}')
    (two / "settings.json").write_text('{"profile": "two"}')

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[one / "settings.json", two / "settings.json"])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.DONE
    entry_one = find_backup_entry(backup_dir, one / "settings.json")
    entry_two = find_backup_entry(backup_dir, two / "settings.json")
    assert entry_one is not None
    assert entry_two is not None
    assert (backup_dir / entry_one["content"]).read_text() == '{"profile": "one"}'
    assert (backup_dir / entry_two["content"]).read_text() == '{"profile": "two"}'


def test_backup_step_preserves_file_directory_basename_collision(tmp_path: Path):
    """A file and a directory sharing one basename must not collide either."""
    file_src = tmp_path / "a" / "foo"
    dir_src = tmp_path / "b" / "foo"
    file_src.parent.mkdir(parents=True)
    dir_src.mkdir(parents=True)
    file_src.write_text("file content")
    (dir_src / "inner.txt").write_text("dir content")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[file_src, dir_src])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.DONE
    file_entry = find_backup_entry(backup_dir, file_src)
    dir_entry = find_backup_entry(backup_dir, dir_src)
    assert file_entry is not None
    assert dir_entry is not None
    assert file_entry["kind"] == "file"
    assert dir_entry["kind"] == "directory"
    assert (backup_dir / file_entry["content"]).read_text() == "file content"
    assert (backup_dir / dir_entry["content"] / "inner.txt").read_text() == "dir content"


def test_backup_step_records_symlink_target_without_dereferencing(tmp_path: Path):
    """A symlink target — including one pointing at a directory — is recorded
    as a symlink, never resolved into a copied file/directory tree."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "CLAUDE.md").write_text("hi")
    link_to_dir = tmp_path / "link-to-dir"
    link_to_dir.symlink_to(real_dir)

    real_file = tmp_path / "real.txt"
    real_file.write_text("hi")
    link_to_file = tmp_path / "link-to-file"
    link_to_file.symlink_to(real_file)

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[link_to_dir, link_to_file])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.DONE
    dir_entry = find_backup_entry(backup_dir, link_to_dir)
    file_entry = find_backup_entry(backup_dir, link_to_file)
    assert dir_entry is not None
    assert file_entry is not None
    assert dir_entry["kind"] == "symlink"
    assert dir_entry["content"] is None
    assert dir_entry["target"] == str(real_dir)
    assert file_entry["kind"] == "symlink"
    assert file_entry["target"] == str(real_file)


def test_backup_step_records_absent_targets_explicitly(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    missing = tmp_path / "nope"
    step = BackupStep(targets=[missing])
    result = step.execute(backup_dir=backup_dir, dry_run=False)
    assert result.status == StepStatus.DONE
    entry = find_backup_entry(backup_dir, missing)
    assert entry is not None
    assert entry["kind"] == "absent"


def test_backup_step_marks_manifest_incomplete_on_partial_failure(tmp_path: Path, monkeypatch):
    """A failure partway through must not advertise a complete, recoverable backup."""
    import shutil

    good = tmp_path / "good.txt"
    good.write_text("ok")
    bad = tmp_path / "bad.txt"
    bad.write_text("also ok")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    real_copy2 = shutil.copy2
    calls = {"n": 0}

    def flaky_copy2(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", flaky_copy2)

    step = BackupStep(targets=[good, bad])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.FAILED
    manifest = read_backup_manifest(backup_dir)
    assert manifest is not None
    assert manifest["complete"] is False


def test_backup_step_dry_run_does_nothing(tmp_path: Path):
    src = tmp_path / "file.txt"
    src.write_text("x")
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[src])
    result = step.execute(backup_dir=backup_dir, dry_run=True)

    assert result.status == StepStatus.DONE
    assert not (backup_dir / "file.txt").exists()


def test_backup_step_ignores_missing_targets(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    step = BackupStep(targets=[tmp_path / "nope"])
    result = step.execute(backup_dir=backup_dir, dry_run=False)
    assert result.status == StepStatus.DONE


def test_backup_step_marks_incomplete_before_copying_starts(tmp_path: Path, monkeypatch):
    """A stale complete=True manifest from a prior run in the same directory
    must not survive an interruption that the Python except clause never
    sees (simulated here with BaseException, which `except Exception` in
    BackupStep does not catch)."""
    import shutil

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / BACKUP_MANIFEST_NAME).write_text(
        json.dumps({"format": "backup-manifest", "version": 1, "complete": True, "entries": []})
    )

    def boom(*args, **kwargs):
        raise SystemExit("simulated hard interruption")

    monkeypatch.setattr(shutil, "copy2", boom)

    target = tmp_path / "file.txt"
    target.write_text("x")
    step = BackupStep(targets=[target])
    with pytest.raises(SystemExit):
        step.execute(backup_dir=backup_dir, dry_run=False)

    on_disk = json.loads((backup_dir / BACKUP_MANIFEST_NAME).read_text())
    assert on_disk["complete"] is False


def test_read_backup_manifest_rejects_content_escaping_backup_dir(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / BACKUP_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "format": "backup-manifest",
                "version": 1,
                "complete": True,
                "entries": [
                    {
                        "path": str(tmp_path / "cfg.toml"),
                        "kind": "file",
                        "content": "../outside.txt",
                        "target": None,
                    }
                ],
            }
        )
    )
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_read_backup_manifest_rejects_missing_complete_field(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / BACKUP_MANIFEST_NAME).write_text(
        json.dumps({"format": "backup-manifest", "version": 1, "entries": []})
    )
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_read_backup_manifest_returns_none_only_when_file_absent(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    assert read_backup_manifest(backup_dir) is None


def test_read_backup_manifest_rejects_directory_at_manifest_path(tmp_path: Path):
    """A directory sitting where the manifest file should be is not legacy
    absence — it must be refused, not silently treated as 'no manifest'."""
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / BACKUP_MANIFEST_NAME).mkdir()
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_read_backup_manifest_rejects_dangling_symlink_at_manifest_path(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / BACKUP_MANIFEST_NAME).symlink_to(tmp_path / "nowhere")
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def _write_manifest(backup_dir: Path, **overrides) -> None:
    manifest = {"format": "backup-manifest", "version": 1, "complete": True, "entries": []}
    manifest.update(overrides)
    (backup_dir / BACKUP_MANIFEST_NAME).write_text(json.dumps(manifest))


def test_validate_entry_rejects_file_kind_missing_content(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    _write_manifest(
        backup_dir,
        entries=[{"path": str(tmp_path / "x"), "kind": "file", "content": None, "target": None}],
    )
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_validate_entry_rejects_symlink_kind_missing_target(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    _write_manifest(
        backup_dir,
        entries=[{"path": str(tmp_path / "x"), "kind": "symlink", "content": None, "target": None}],
    )
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


@pytest.mark.parametrize("root_spelling", ["", "."])
def test_validate_entry_rejects_content_pointing_at_backup_root(tmp_path: Path, root_spelling: str):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    _write_manifest(
        backup_dir,
        entries=[
            {
                "path": str(tmp_path / "x"),
                "kind": "directory",
                "content": root_spelling,
                "target": None,
            }
        ],
    )
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_validate_manifest_rejects_duplicate_source_paths(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    dup = str(tmp_path / "x")
    _write_manifest(
        backup_dir,
        entries=[
            {"path": dup, "kind": "absent", "content": None, "target": None},
            {"path": dup, "kind": "absent", "content": None, "target": None},
        ],
    )
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_validate_manifest_rejects_boolean_version(tmp_path: Path):
    """`True == 1` in Python — a boolean version must not slip past an `==`
    check against `BACKUP_MANIFEST_VERSION`."""
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    _write_manifest(backup_dir, version=True)
    with pytest.raises(BackupManifestError):
        read_backup_manifest(backup_dir)


def test_backup_step_returns_failed_result_when_backup_dir_cannot_be_created(tmp_path: Path):
    """mkdir belongs inside the try: a failure here must still produce a
    FAILED StepResult, not an uncaught exception out of execute()."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    backup_dir = blocker / "backup"

    target = tmp_path / "file.txt"
    target.write_text("x")
    step = BackupStep(targets=[target])

    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.FAILED
    assert "backup failed" in result.message


def test_backup_step_marker_write_failure_does_not_mask_original_error(tmp_path: Path, monkeypatch):
    """If marking the backup incomplete after a failure itself fails (e.g.
    disk truly full), the original failure must still be the one reported."""
    from lazy_harness.migrate.steps import backup as backup_module

    good = tmp_path / "good.txt"
    good.write_text("ok")
    backup_dir = tmp_path / "backup"

    real_write = backup_module.write_backup_manifest
    calls = {"n": 0}

    def flaky_write(bd, entries, *, complete):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("marker write also failed")
        return real_write(bd, entries, complete=complete)

    monkeypatch.setattr(backup_module, "write_backup_manifest", flaky_write)

    import shutil

    def boom_copy2(*args, **kwargs):
        raise OSError("original disk full")

    monkeypatch.setattr(shutil, "copy2", boom_copy2)

    step = BackupStep(targets=[good])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.FAILED
    assert "original disk full" in result.message
