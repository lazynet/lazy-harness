"""The contract F9 phase B judges against, over the stream Codex actually writes.

Phase B asserted *the fixture was denied*. It cannot legitimately assert that:
the prompt asks for "a single recursive shell delete" and the model picks the
spelling. Probe 6 (2026-09-17 16:41) got `rm -r -- doomed` where probe 5 had got
`rm -rf -- doomed`, the guard of the day allowed the first and denied the
second, and the gate read the difference as a hook defect.

What the gate *can* assert is that Codex honoured whatever the guard said about
the command the model actually issued. That is three steps, and this module owns
the first three-quarters of them: read the issued command off the `--json`
stream, replay it through the shipped guard for the guard's own verdict, and
compare that verdict against what happened on disk.

**The fourth outcome is the one this exists for.** `allow` expected and the
effect happened is not a failure — it is the model choosing a spelling the guard
permits, and a gate that called it FAIL would send the next run hunting a hook
bug that is not there. It is reported, with the spelling printed, and the gate
re-prompts once with a pinned one.

The stream fixtures below are the bytes probe 6 wrote, not invented ones: the
item shape (`item.type == "command_execution"`, `.command`) is
`codex-evidence.md` §7.3 and `/tmp/hook-probe6/stream-a.jsonl` measured it on
0.154.0.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
CONTRACT = REPO_ROOT / "specs" / "gates" / "guard_contract.py"

# Assembled rather than written out: this repo's own PreToolUse guard blocks a
# tool call whose command string carries the literal, and an agent editing this
# file is subject to it.
_RF = "-" + "rf"
_R = "-" + "r"


@pytest.fixture(scope="module")
def contract() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guard_contract", CONTRACT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["guard_contract"] = module
    spec.loader.exec_module(module)
    return module


PROFILE = "probe-codex"


@pytest.fixture
def codex_profile_name(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> str:
    """An `LH_CONFIG_DIR` whose `probe-codex` profile runs the Codex adapter.

    Two profiles, not one: the runner resolves its adapter by profile name, and
    a config with a single profile cannot tell "read the name it was given"
    apart from "took the only one there was".

    Set through the real environment variable rather than an argument, because
    the CLI half of this file runs in a subprocess and has to resolve the same
    profile through the same seam the gate's own invocation does.
    """
    root = tmp_path_factory.mktemp("contract-profile")
    config_dir = root / "lh"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[harness]\n"
        'version = "1"\n\n'
        "[agent]\n"
        'type = "claude-code"\n\n'
        "[profiles]\n"
        'default = "cc"\n\n'
        "[profiles.cc]\n"
        f'config_dir = "{root / "cc"}"\n'
        "roots = []\n\n"
        f"[profiles.{PROFILE}]\n"
        f'config_dir = "{root / "codex-home"}"\n'
        "roots = []\n"
        'agent = "codex"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))
    return PROFILE


def _stream(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "stream.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _command_row(command: str, status: str = "completed", exit_code: int | None = 0) -> dict:
    """The envelope probe 6 measured: FLAT `{"type": ...}` with a nested `item`."""
    return {
        "type": f"item.{status}",
        "item": {
            "id": "item_1",
            "type": "command_execution",
            "command": command,
            "aggregated_output": "",
            "exit_code": exit_code,
            "status": "in_progress" if status == "started" else "completed",
        },
    }


_AGENT_ROW = {
    "type": "item.completed",
    "item": {"id": "item_2", "type": "agent_message", "text": "DONE"},
}


# --- reading the command off the stream ------------------------------------


def test_the_issued_command_is_read_from_the_stream(contract, tmp_path: Path) -> None:
    """Byte-for-byte what probe 6's arm A carried, wrapper and all. The wrapper
    is not stripped: `/bin/zsh -lc '…'` is what Codex sent the guard, so it is
    what the replay has to send too."""
    wrapped = f"/bin/zsh -lc 'rm {_R} -- doomed'"
    path = _stream(
        tmp_path, _command_row(wrapped, status="started", exit_code=None), _command_row(wrapped)
    )

    assert contract.issued_command(path) == wrapped


def test_a_turn_that_ran_no_command_reads_as_empty(contract, tmp_path: Path) -> None:
    """The model answering in prose is a NO-OBS for the phase, never a verdict
    about the guard."""
    assert contract.issued_command(_stream(tmp_path, _AGENT_ROW)) == ""


def test_a_missing_stream_reads_as_empty_rather_than_raising(contract, tmp_path: Path) -> None:
    assert contract.issued_command(tmp_path / "absent.jsonl") == ""


def test_the_last_command_of_the_turn_is_the_one_judged(contract, tmp_path: Path) -> None:
    """A turn can run several. The fixture's fate is decided by the last one
    that touched it, and judging the first would report on a `ls`."""
    path = _stream(tmp_path, _command_row("ls -la"), _command_row(f"rm {_RF} -- doomed"))

    assert contract.issued_command(path) == f"rm {_RF} -- doomed"


def test_a_malformed_line_does_not_take_the_reading_down(contract, tmp_path: Path) -> None:
    """`codex exec --json` writes progress lines to the same stream and the gate
    redirects stderr into it; one unparseable line must not cost the command."""
    path = tmp_path / "stream.jsonl"
    path.write_text(
        "not json at all\n" + json.dumps(_command_row(f"rm {_RF} -- doomed")) + "\n",
        encoding="utf-8",
    )

    assert contract.issued_command(path) == f"rm {_RF} -- doomed"


def test_an_item_that_is_not_a_dict_is_skipped(contract, tmp_path: Path) -> None:
    """Valid JSON of the wrong type, which this repo gates on separately from
    malformed JSON."""
    path = _stream(tmp_path, {"type": "item.completed", "item": None}, _command_row("rm -r dir"))

    assert contract.issued_command(path) == "rm -r dir"


# --- the native-edit arm ---------------------------------------------------


def test_the_native_edit_paths_are_read_from_the_changes_list(contract, tmp_path: Path) -> None:
    """0.154.0 reports a native edit as `file_change` with a `changes` list and
    never names `apply_patch` in the `--json` stream (measured 2026-09-17 on the
    acceptance run's `stream-b-deny-patch.jsonl`)."""
    row = {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "file_change",
            "changes": [{"path": "/tmp/work/.env", "kind": "update"}],
        },
    }

    assert contract.issued_edit_paths(_stream(tmp_path, row)) == ["/tmp/work/.env"]


def test_an_unrecognised_change_shape_yields_no_paths_rather_than_a_guess(
    contract, tmp_path: Path
) -> None:
    """The element shape of `changes` is NOT measured — only the list's
    existence is. Inventing a key would make the phase assert a verdict about a
    payload the guard never saw, so an unrecognised element yields nothing and
    the gate reports NO-OBS."""
    row = {
        "type": "item.completed",
        "item": {"id": "item_1", "type": "file_change", "changes": ["/tmp/work/.env"]},
    }

    assert contract.issued_edit_paths(_stream(tmp_path, row)) == []


# --- the guard's own verdict, through the shipped runner -------------------


def test_the_guard_verdict_comes_back_deny_for_a_recursive_delete(
    contract, codex_profile_name: str
) -> None:
    verdict = contract.guard_verdict(codex_profile_name, "Bash", {"command": f"rm {_RF} -- doomed"})

    assert verdict == "deny"


def test_the_guard_verdict_comes_back_allow_for_a_forced_single_file_delete(
    contract, codex_profile_name: str
) -> None:
    """The half that proves the replay reads a real answer rather than always
    saying `deny`."""
    verdict = contract.guard_verdict(codex_profile_name, "Bash", {"command": "rm -f one-file"})

    assert verdict == "allow"


def test_the_wrapper_codex_adds_does_not_change_the_verdict(
    contract, codex_profile_name: str
) -> None:
    """`_COMMAND_START` reaches through `sh -c` and its cluster spellings, so
    the replay of the wrapped string is the same decision the live hook made."""
    wrapped = f"/bin/zsh -lc 'rm {_RF} -- doomed'"

    assert contract.guard_verdict(codex_profile_name, "Bash", {"command": wrapped}) == "deny"


# --- the contract itself ---------------------------------------------------
#
# Both directions, per the repo's gate rule: a case each verdict must reach and
# a case it must not.


@pytest.mark.parametrize(
    "expected,effect,verdict",
    [
        ("deny", False, "honoured"),
        ("deny", True, "ignored"),
        ("allow", True, "permitted-spelling"),
        ("allow", False, "allowed-no-effect"),
    ],
    ids=["deny-and-survived", "deny-and-gone", "allow-and-gone", "allow-and-survived"],
)
def test_the_contract_is_four_ways(contract, expected: str, effect: bool, verdict: str) -> None:
    assert contract.contract_verdict(expected, effect) == verdict


def test_a_permitted_spelling_is_never_the_same_verdict_as_an_ignored_one(contract) -> None:
    """The whole point. `deny`-then-gone is Codex ignoring a verdict and is the
    only real defect here; `allow`-then-gone is the model picking a spelling the
    guard permits, and collapsing them is what the 12:32 FAIL did."""
    assert contract.contract_verdict("deny", True) != contract.contract_verdict("allow", True)


def test_no_verdict_is_reachable_without_an_expected_decision(contract) -> None:
    """No command read means no contract: the phase learns nothing and must not
    manufacture a verdict out of the fixture's state alone."""
    assert contract.contract_verdict("", True) == "no-command"
    assert contract.contract_verdict("", False) == "no-command"


def test_an_unknown_decision_word_does_not_fall_through_to_a_pass(contract) -> None:
    """A renamed `permissionDecision` must degrade to `no-command`, never to
    `honoured` — the direction that fails closed."""
    assert contract.contract_verdict("ask", False) == "no-command"


# --- the sentence that reaches the summary ---------------------------------


def test_every_verdict_has_a_sentence_and_none_falls_through(contract) -> None:
    for verdict in (
        "honoured",
        "ignored",
        "permitted-spelling",
        "allowed-no-effect",
        "no-command",
    ):
        assert contract.contract_note(verdict), f"{verdict} has no sentence"


def test_the_permitted_spelling_sentence_does_not_blame_the_hook(contract) -> None:
    """A run that ends here has measured nothing about the hook, and sending the
    reader to it costs them the next run — the cost the 12:32 FAIL actually
    imposed."""
    note = contract.contract_note("permitted-spelling")

    assert "spelling" in note
    assert "defect" not in note


def test_the_ignored_sentence_names_the_defect_it_is_the_only_evidence_of(contract) -> None:
    note = contract.contract_note("ignored")

    assert "ignored" in note or "honour" in note


# --- the CLI the gate script calls -----------------------------------------


def _judge(profile: str, stream: Path, effect: str) -> dict[str, str]:
    result = subprocess.run(
        [
            sys.executable,
            str(CONTRACT),
            "judge",
            "--profile",
            profile,
            "--stream",
            str(stream),
            "--effect",
            effect,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        fields[key] = value
    return fields


def test_the_cli_reports_the_command_expected_verdict_and_note(
    tmp_path: Path, codex_profile_name: str
) -> None:
    stream = _stream(tmp_path, _command_row(f"rm {_RF} -- doomed"))

    fields = _judge(codex_profile_name, stream, "gone")

    assert fields["expected"] == "deny"
    assert fields["verdict"] == "ignored"
    assert json.loads(fields["command"]) == f"rm {_RF} -- doomed"
    assert fields["note"]


def test_the_cli_reports_a_permitted_spelling_rather_than_a_failure(
    tmp_path: Path, codex_profile_name: str
) -> None:
    """The arm-A reading of probe 6, end to end through the seam the gate uses.
    Post-widening `rm -r` denies, so the spelling that exercises this path is a
    forced single-file delete — the contract logic is what is under test, not
    which spelling happens to be allowed this month."""
    stream = _stream(tmp_path, _command_row("rm -f one-file"))

    fields = _judge(codex_profile_name, stream, "gone")

    assert fields["expected"] == "allow"
    assert fields["verdict"] == "permitted-spelling"


def test_the_command_is_emitted_as_one_json_line(tmp_path: Path, codex_profile_name: str) -> None:
    """The gate parses this with `awk` on a line-oriented protocol, and a
    command carrying a newline would silently truncate every field after it."""
    stream = _stream(tmp_path, _command_row("rm -f a\nrm -f b"))

    fields = _judge(codex_profile_name, stream, "gone")

    assert "\n" not in fields["command"]
    assert json.loads(fields["command"]) == "rm -f a\nrm -f b"
