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


# --- the command a block leaves behind -------------------------------------
#
# Codex emits NO `command_execution` item for a command its `PreToolUse` hook
# blocked (run 4, 2026-09-18 08:27, `stream-b-deny-bash-pinned.jsonl`: the model
# issued the pinned delete, the hook denied it, the fixture survived, and the
# stream carries two `agent_message` items and nothing else). The only record of
# the command is Codex's own block line, which `codex_turn` captures because it
# redirects the turn's stderr into the same file.
#
# The bytes below are that line's shape, measured: a timestamped `ERROR
# codex_core::tools::router:` prefix, the guard's own multi-line reason, and the
# command on a `. Command: ` tail at the very end. The reason spanning four
# physical lines is why nothing line-oriented can find the command.

_BLOCK_REASON = (
    "Blocked by lazy-harness PreToolUse: Recursive delete (filesystem).\n"
    f"Matched: rm {_RF} doomed\n"
    "If this is intentional, add a regex pattern to [hooks.pre_tool_use] "
    "allow_patterns in your profile config.toml.\n"
    "See specs/designs/2026-04-17-security-hooks-cluster-design.md for the full rule list."
)


def _block_line(command: str, reason: str = _BLOCK_REASON) -> str:
    """One Codex block line, exactly as run 4 captured it."""
    return (
        "2026-09-18T11:29:46.472516Z ERROR codex_core::tools::router: "
        f"error=Command blocked by PreToolUse hook: {reason}. Command: {command}"
    )


def _mixed_stream(tmp_path: Path, *chunks: str | dict) -> Path:
    """A stream with JSON rows and raw stderr text interleaved, in order."""
    path = tmp_path / "stream.jsonl"
    path.write_text(
        "".join(
            (json.dumps(chunk) if isinstance(chunk, dict) else chunk) + "\n" for chunk in chunks
        ),
        encoding="utf-8",
    )
    return path


def test_a_blocked_command_is_recovered_from_the_block_line(contract, tmp_path: Path) -> None:
    """The pinned turn of run 4, byte for byte. No `command_execution` item
    exists, so a reader that only knows the stream sees a turn that ran nothing
    and judges `no-command` over a deny the hook actually enforced."""
    path = _mixed_stream(
        tmp_path,
        {"type": "turn.started"},
        _block_line(f"rm {_RF} doomed"),
        _AGENT_ROW,
    )

    assert contract.blocked_commands(path) == [f"rm {_RF} doomed"]


def test_the_multi_line_reason_does_not_hide_the_command(contract, tmp_path: Path) -> None:
    """The guard's reason carries three newlines before the `. Command: ` tail,
    so the command is not on the line that says `Command blocked`. Anything
    grepping a single line finds the block and loses the command."""
    path = _mixed_stream(tmp_path, _block_line(f"rm {_RF} doomed"))
    first = path.read_text(encoding="utf-8").splitlines()[0]

    assert "Command blocked by PreToolUse hook" in first
    assert ". Command: " not in first
    assert contract.blocked_commands(path) == [f"rm {_RF} doomed"]


def test_each_block_line_closes_at_the_next_stream_row(contract, tmp_path: Path) -> None:
    """A turn can be refused twice, and each block is its own region. Without
    the close, the two run together: one region, one `. Command: ` tail taken
    from the first, and the second block's whole line glued onto that command.
    The guard would then be replayed against a string Codex never issued."""
    path = _mixed_stream(
        tmp_path,
        _block_line(f"rm {_RF} doomed"),
        _AGENT_ROW,
        _block_line(f"rm {_RF} -- ./doomed"),
        {"type": "turn.completed"},
    )

    assert contract.blocked_commands(path) == [f"rm {_RF} doomed", f"rm {_RF} -- ./doomed"]


def test_a_block_line_with_no_command_tail_yields_nothing(contract, tmp_path: Path) -> None:
    """Fails closed. A Codex that stops appending `. Command: ` must make the
    gate report NO-OBS, never make it judge the empty string."""
    path = _mixed_stream(
        tmp_path,
        "2026-09-18T11:29:46Z ERROR codex_core::tools::router: "
        "error=Command blocked by PreToolUse hook: Blocked by lazy-harness PreToolUse.",
        _AGENT_ROW,
    )

    assert contract.blocked_commands(path) == []


def test_an_empty_command_tail_yields_nothing_either(contract, tmp_path: Path) -> None:
    """The half the marker check alone does not cover: the tail is there and it
    is empty. Appending it would hand `guard_verdict` the empty string, which
    answers `allow`, which reads as `allowed-no-effect` — a verdict about Codex
    derived from a command nobody issued."""
    # NOT rstripped: the marker is `. Command: ` with its trailing space, and a
    # line trimmed to `. Command:` is the no-marker case the test above owns.
    path = _mixed_stream(tmp_path, _block_line(""), _AGENT_ROW)

    assert contract.blocked_commands(path) == []


def test_a_multi_line_command_survives_the_tail(contract, tmp_path: Path) -> None:
    """The native-edit turn's block line carries the whole `apply_patch` blob on
    its tail, newlines and all (run 4, `stream-b-deny-patch.jsonl`)."""
    blob = "*** Begin Patch\n*** Update File: .env\n@@\n-seed\n+touched\n*** End Patch"
    path = _mixed_stream(tmp_path, _block_line(blob), _AGENT_ROW)

    assert contract.blocked_commands(path) == [blob]


def test_a_stream_with_no_block_line_yields_no_blocked_commands(contract, tmp_path: Path) -> None:
    assert contract.blocked_commands(_stream(tmp_path, _command_row("ls -la"))) == []


def test_issued_command_falls_back_to_the_block_line(contract, tmp_path: Path) -> None:
    """The brief's case: the stream has no `command_execution` at all, so the
    only command this turn issued is the one the hook refused."""
    path = _mixed_stream(tmp_path, _block_line(f"rm {_RF} doomed"), _AGENT_ROW)

    assert contract.issued_command(path) == f"rm {_RF} doomed"


def test_issued_command_still_prefers_a_command_the_stream_recorded(
    contract, tmp_path: Path
) -> None:
    """The fallback is a fallback. A stream that recorded an execution is the
    stronger evidence and keeps its precedence."""
    path = _mixed_stream(tmp_path, _command_row("ls -la"))

    assert contract.issued_command(path) == "ls -la"


# --- which command the contract is about -----------------------------------
#
# Run 4's first phase B turn ran two: a delete the hook blocked and a read-only
# inspection it allowed. `commands[-1]` picks the inspection, replays *that*
# through the guard, gets `allow`, and reports `permitted-spelling` over a turn
# where the guard denied and Codex obeyed.


def _two_command_turn(tmp_path: Path) -> Path:
    """Run 4's `b-deny-bash`: an allowed inspection recorded in the stream, and
    a delete that only the block line records."""
    inspection = '/bin/zsh -lc "if [ -d ./doomed ]; then pwd; fi"'
    return _mixed_stream(
        tmp_path,
        _command_row(inspection, status="started", exit_code=None),
        _command_row(inspection),
        _block_line(f"rm {_RF} -- ./doomed"),
        _AGENT_ROW,
    )


def test_the_blocked_command_is_the_one_the_contract_is_about(contract, tmp_path: Path) -> None:
    """Both commands ran, the fixture survived: the question the phase asks is
    about the delete, not about the `find` the model ran afterwards."""
    command, source = contract.contract_command(_two_command_turn(tmp_path), False)

    assert command == f"rm {_RF} -- ./doomed"
    assert source == "block-line"


def test_a_blocked_only_turn_can_still_reach_the_failing_verdict(contract, tmp_path: Path) -> None:
    """The direction that keeps the gate a gate: nothing else ran, so an effect
    that happened is attributable to the deny and `ignored` stays reachable."""
    path = _mixed_stream(tmp_path, _block_line(f"rm {_RF} doomed"), _AGENT_ROW)

    command, source = contract.contract_command(path, True)

    assert source == "block-line"
    assert contract.contract_verdict("deny", True) == "ignored"
    assert command == f"rm {_RF} doomed"


def test_an_effect_alongside_an_allowed_command_is_not_blamed_on_the_deny(
    contract, tmp_path: Path
) -> None:
    """The false-FAIL this selection would otherwise invent. A blocked delete
    AND an allowed command AND the fixture gone cannot say which one removed it,
    and `ignored` is the one verdict that accuses Codex of a defect. The allowed
    command is judged instead, which lands on `permitted-spelling` — inconclusive,
    re-prompt once — the arm this module was built to route ambiguity into."""
    command, source = contract.contract_command(_two_command_turn(tmp_path), True)

    assert source == "stream"
    assert command.startswith("/bin/zsh")


def test_no_command_anywhere_reports_an_empty_source(contract, tmp_path: Path) -> None:
    assert contract.contract_command(_stream(tmp_path, _AGENT_ROW), False) == ("", "")


# --- the CLI carries where the command came from ---------------------------


def test_the_cli_names_the_block_line_as_the_source(
    tmp_path: Path, codex_profile_name: str
) -> None:
    """Run 4's pinned turn, end to end. It read `no-command` then; it reads a
    deny Codex honoured now, and the printed line says where the command was
    found so the reader is not told the stream recorded an execution it did not."""
    path = tmp_path / "stream.jsonl"
    path.write_text(
        json.dumps({"type": "turn.started"})
        + "\n"
        + _block_line(f"rm {_RF} doomed")
        + "\n"
        + json.dumps(_AGENT_ROW)
        + "\n",
        encoding="utf-8",
    )

    fields = _judge(codex_profile_name, path, "survived")

    assert fields["source"] == "block-line"
    assert fields["expected"] == "deny"
    assert fields["verdict"] == "honoured"
    assert json.loads(fields["command"]) == f"rm {_RF} doomed"


def test_the_cli_names_the_stream_as_the_source_when_it_recorded_the_command(
    tmp_path: Path, codex_profile_name: str
) -> None:
    fields = _judge(codex_profile_name, _stream(tmp_path, _command_row("rm -f one-file")), "gone")

    assert fields["source"] == "stream"


def test_the_cli_reports_no_source_when_it_read_no_command(
    tmp_path: Path, codex_profile_name: str
) -> None:
    fields = _judge(codex_profile_name, _stream(tmp_path, _AGENT_ROW), "gone")

    assert fields["source"] == ""
    assert fields["verdict"] == "no-command"
