# Config TUI Implementation Plan (waves 5, 7, 8, 9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One interactive surface that shows what is on, whether it is working, and lets you change it — with the change verified against the deployed artefact rather than reported from an exit code.

**Architecture:** The nine `lh status` views stop printing and start returning Rich renderables, which makes them both testable and hostable by Textual. The observe pane composes them. The configure pane is driven entirely by the capability registry, dispatching on cardinality. Saving is a four-step transaction that ends by re-reading `settings.json` and reporting per toggle.

**Tech Stack:** Python 3.11+, `rich` (already a dependency), `textual` (new, optional extra), `pytest`, `ruff`.

**Spec:** [`specs/designs/2026-08-17-config-tui-design.md`](../designs/2026-08-17-config-tui-design.md)

**Branches:** four, in order — `refactor/view-renderables` (no release), `feat/tui-observe` (0.41.0), `feat/tui-configure` (0.42.0), `feat/tui-write` (0.43.0).

## Global Constraints

- **Wave 5 is blocked by wave 3.** Wave 3 rewires `views/cron.py` and `views/overview.py` to drop `launchctl_loaded`; this plan changes every view's signature. Same files, same lines.
- **Wave 8 is blocked by wave 6**, wave 9 by waves 1 and 8.
- `lh status` behaviour is unchanged throughout. The subcommands are the scriptable, hook-and-CI-safe surface and stay that way.
- Textual is an **optional extra**, never a core dependency. Hooks and cron jobs run headless and will never open a TUI.
- No mouse-only affordances. Correct at 80×24. `NO_COLOR` honoured. State carried by glyph and text, never by colour alone.
- Strict TDD, every new test observed failing first. `/tdd-check` before every commit. No AI trailers.

---

# Wave 5 — `refactor/view-renderables`

Behaviour-preserving. Cuts no release; rides wave 7. Worth doing on its own merit: eight of the nine views have no dedicated test today because asserting on captured console output is unpleasant.

## File Structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/monitoring/views/*.py` | `render(...) -> RenderableType` instead of `render(..., console) -> None` |
| `src/lazy_harness/cli/status_cmd.py` | one-line adapter per subcommand: `Console().print(view.render(...))` |
| `tests/fixtures/status-output/` | **new** — captured output per subcommand |
| `tests/unit/monitoring/views/test_*.py` | **new** — one per view |

### Task 1: Capture the identity fixtures before touching anything

- [ ] **Step 1: Capture every subcommand's output**

```bash
mkdir -p tests/fixtures/status-output
for sub in overview profiles projects hooks cron queue memory; do
  uv run lh status "$sub" > "tests/fixtures/status-output/$sub.txt" 2>&1
done
uv run lh status sessions --period month > tests/fixtures/status-output/sessions.txt 2>&1
uv run lh status tokens --period month > tests/fixtures/status-output/tokens.txt 2>&1
wc -l tests/fixtures/status-output/*.txt
```

These embed machine-specific data (paths, counts, timestamps), so they are a **manual** diff gate, not an automated assertion. The automated tests come in Task 3 and assert on structure.

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/status-output/
git commit -m "test: capture lh status output before the renderable refactor"
```

### Task 2: Convert the views

**Interfaces:**
- Produces: `render(ctx: StatusContext) -> RenderableType` for `profiles`, `projects`, `hooks`, `cron`, `queue`, `memory`; `render(ctx, db) -> RenderableType` for `overview`; `render(db, period) -> RenderableType` for `sessions`; `render_table(agg, period) -> RenderableType` and `render_json(agg, period) -> str` for `tokens`

- [ ] **Step 1: Convert one view first — `queue`, the smallest at 13 lines of render**

Replace the interleaved `console.print` calls with a `Group` assembled and returned. `views/hooks.py` is the hard one: it prints inside a loop at lines 71–91, so the loop must build a list of renderables rather than emit as it goes.

- [ ] **Step 2: Adapt the CLI**

Each subcommand in `cli/status_cmd.py` becomes `Console().print(queue_view.render(sctx))`. `status_tokens`'s `--json` path returns a string and is printed directly, keeping the JSON contract byte-identical — that output is a data interface, not a display.

- [ ] **Step 3: Diff against the fixture after each view**

```bash
uv run lh status queue > /tmp/queue-after.txt 2>&1
diff tests/fixtures/status-output/queue.txt /tmp/queue-after.txt
```
Empty, or the refactor changed behaviour. Repeat per view; do not batch nine conversions and diff once.

- [ ] **Step 4: Commit per view**, e.g. `refactor: return a renderable from the queue view`.

### Task 3: A unit test per view

- [ ] For each of the nine, a test that builds a `StatusContext` against a `tmp_path` fixture and asserts on the returned renderable's structure. Example for `hooks`:

```python
def test_hooks_view_lists_every_configured_hook(tmp_path: Path) -> None:
    from rich.console import Console

    from lazy_harness.core.config import Config, HookEventConfig
    from lazy_harness.monitoring.views import hooks as hooks_view
    from lazy_harness.monitoring.views._helpers import StatusContext

    cfg = Config()
    cfg.hooks["session_start"] = HookEventConfig(scripts=["context-inject"])
    renderable = hooks_view.render(StatusContext.build(cfg))

    console = Console(width=120, no_color=True)
    with console.capture() as cap:
        console.print(renderable)
    assert "context-inject" in cap.get()
```

Capturing through a `Console` in the test is fine — the point is that the view no longer *owns* one, so the test controls width and colour.

- [ ] Commit as `test: cover every status view`.

### Task 4: Wave 5 gate

- [ ] `/tdd-check`. All nine fixture diffs empty. Push as `refactor: return renderables from the status views`. No release.

---

# Wave 7 — `feat/tui-observe`

Blocked by wave 5. Releases `0.41.0`, carrying waves 5 and 6 with it.

### Task 5: Add Textual as an optional extra

- [ ] **Step 1:** From the **root checkout**, add to `pyproject.toml`:

```toml
[project.optional-dependencies]
tui = ["textual>=0.80"]
```

Then `uv sync --extra tui` in the root checkout. Not from a worktree.

- [ ] **Step 2: Test the absent-dependency path first**

```python
def test_lh_tui_without_textual_prints_the_install_hint(monkeypatch) -> None:
    """Must be a clear message and a non-zero exit, never a traceback."""
    import builtins

    from click.testing import CliRunner

    real_import = builtins.__import__

    def no_textual(name, *args, **kwargs):
        if name.startswith("textual"):
            raise ImportError("No module named 'textual'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_textual)

    from lazy_harness.cli.tui_cmd import tui

    result = CliRunner().invoke(tui, [])
    assert result.exit_code != 0
    assert "lazy-harness[tui]" in result.output
    assert "Traceback" not in result.output


def test_lh_tui_in_a_non_tty_exits_cleanly() -> None:
    """Emitting escape codes into a pipe is worse than refusing."""
    from click.testing import CliRunner

    from lazy_harness.cli.tui_cmd import tui

    result = CliRunner().invoke(tui, [], input="")
    assert "\x1b[" not in result.output
```

- [ ] **Step 3:** Implement `src/lazy_harness/cli/tui_cmd.py` with the guarded import and the non-TTY check, register it in `cli/main.py:register_commands`, run, commit.

### Task 6: The observe pane

- [ ] **Step 1:** A Textual `App` with a header, a view switcher bound to single keys (`o`, `p`, `j`, `s`, `t`, `h`, `c`, `q`, `m`), and a content region that mounts the selected view's renderable inside a `Static`.
- [ ] **Step 2:** A refresh timer, default 5 s, **paused when the pane is not focused**. `views/cron.py` shells out per job through `job_state`, so a 1 s refresh would spawn subprocesses continuously.
- [ ] **Step 3:** Drill-down. Selecting a hook row shows the tail of the relevant `hooks.log`; selecting a job row shows its unit file or plist. This is the thing the subcommands cannot do and the reason the pane exists.
- [ ] **Step 4:** Verify at 80×24 and with `NO_COLOR=1`, in tmux, over ssh to a headless target. The repo requires assumptions about tool behaviour be verified in the target context — "a Textual app is legible over ssh" is exactly such an assumption.
- [ ] **Step 5:** Commit as `feat: lh tui observe pane over the status views`.

### Task 7: Docs and wave 7 gate

- [ ] `docs/reference/cli.md` gains an `lh tui` section; `docs/getting-started/install.md` gains the `[tui]` extra. In scope for this change, not deferred.
- [ ] `/tdd-check`, push as `feat: add lh tui with a live observability pane`. Deploy grep string: `tui_cmd`.
- [ ] **After deploying `0.41.0`, run the wave-5/6 hook comparison from the release train.** This release carries wave 6's registry migration, so this is the first moment its `settings.json` output reaches the installed binary.

---

# Wave 8 — `feat/tui-configure`

Blocked by waves 6 and 7. Toggles render but are **disabled**. Read-only, and worth shipping alone: a pane showing every capability and its state beats anything that exists today, at zero write risk.

### Task 8: The configure pane, read-only

- [ ] **Step 1: Write the test that the pane special-cases nothing**

```python
def test_configure_pane_renders_every_registered_capability() -> None:
    """The pane dispatches on cardinality. Adding a kind must not require editing it."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.tui.configure import build_rows

    rows = build_rows(builtin_registry(), Config())
    names = {r.name for r in rows}
    assert {"qmd", "engram", "graphify", "context-inject"} <= names


def test_one_cardinality_capabilities_render_as_a_radio_group() -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.tui.configure import build_rows

    rows = [r for r in build_rows(builtin_registry(), Config()) if r.kind == "scheduler"]
    assert {r.widget for r in rows} == {"radio"}
    assert sum(1 for r in rows if r.selected) == 1
```

- [ ] **Step 2:** Implement `src/lazy_harness/tui/configure.py` with `build_rows(registry, cfg) -> list[Row]`, where `Row` carries `name`, `kind`, `widget` (`"checkbox"` or `"radio"`), `selected`, `state`, and `hint`. `widget` derives from `cardinality`; `hint` is `install_hint` when the state is `BROKEN` or `MISSING`.
- [ ] **Step 3:** Mount it in the app behind `c`, with every control disabled and a footer explaining that writes arrive in the next release.
- [ ] **Step 4:** `/tdd-check`, push as `feat: lh tui configure pane showing capability state`.

---

# Wave 9 — `feat/tui-write`

Blocked by waves 1 and 8. The only wave that writes config from an interactive surface.

### Task 9: The save transaction

**Interfaces:**
- Produces: `save_and_verify(cfg: Config, path: Path, toggled: list[Capability]) -> list[VerifyResult]`, where `VerifyResult` carries `capability`, `profile`, `ok: bool`, `detail: str`

- [ ] **Step 1: Write the failing test for the four steps in order**

```python
def test_save_writes_a_backup_before_touching_the_config(tmp_path) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.tui.save import save_and_verify

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n# keep me\n')

    save_and_verify(Config(), cfg_path, toggled=[])

    backup = cfg_path.with_suffix(".toml.bak")
    assert backup.is_file()
    assert "# keep me" in backup.read_text()
```

- [ ] **Step 2: Write the failing test that verification catches a real divergence**

This is the test that matters most in the whole plan. A verification step never observed failing has not been tested.

```python
def test_verification_reports_a_profile_where_the_hook_did_not_land(tmp_path) -> None:
    """Make deploy fail for one profile; the result must be per-profile, not global."""
    from lazy_harness.core.config import Config, ProfileEntry
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.tui.save import save_and_verify

    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir(mode=0o500)  # not writable

    cfg = Config()
    cfg.profiles.items["good"] = ProfileEntry(config_dir=str(good))
    cfg.profiles.items["bad"] = ProfileEntry(config_dir=str(bad))

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')

    cap = builtin_registry().get("context-inject")
    results = save_and_verify(cfg, cfg_path, toggled=[cap])

    by_profile = {r.profile: r.ok for r in results}
    assert by_profile["good"] is True
    assert by_profile["bad"] is False
```

- [ ] **Step 3: Implement `src/lazy_harness/tui/save.py`**

In order, and not reordered: back up to `config.toml.bak`; write through wave 1's `save_config` (same-directory temp plus `os.replace`); call `deploy_hooks` / `deploy_mcp_servers` **in-process**, never a shelled-out `lh deploy` — the installed binary may be a different version than the running one; then re-read each profile's `settings.json` from disk and confirm each toggled hook is present or absent as intended.

A failed verification is rendered as a failure with the backup path offered. It is never rounded up to success.

- [ ] **Step 4: Prove the verification is load-bearing.** Stub the re-read to always return success, run the divergence test, confirm it passes when it should fail, then restore. A check that cannot fail is decoration.

- [ ] **Step 5:** Commit as `feat: verified save transaction for the tui configure pane`.

### Task 10: Read-only mode and the chezmoi reminder

- [ ] **Step 1:** The configure pane renders with controls disabled, and a stated reason, when `--read-only` is passed, when `config.toml` is not writable, or when chezmoi manages the file and its source is ahead of the destination.
- [ ] **Step 2:** After a successful save, if `chezmoi managed <path>` reports the file, print the `chezmoi re-add <path>` reminder. **Do not run it.** Running someone's dotfile manager as a side effect of a checkbox is a hidden action; the reminder is what the workflow actually asks for.
- [ ] **Step 3:** Test all three read-only triggers with an injected chezmoi probe, plus a parameter-less smoke test for the default.

### Task 11: Wave 9 gate

- [ ] `/tdd-check`.
- [ ] **Toggle one hook, save, then diff the raw TOML.** The only change may be the intended one. This is the regression net for wave 1 and it runs against the real config on a copy.
- [ ] **Observe the verification failing.** Make one profile's config dir read-only, toggle a hook on, save, confirm the TUI shows `✗` for that profile and not a global success.
- [ ] Confirm `config.toml.bak` exists after the first save and carries the pre-save content including comments.
- [ ] Push as `feat: enable configuration writes in lh tui`. Deploy grep string: `save_and_verify`.

### Task 12: Set the kill-criteria review date

The spec commits to a review four weeks after wave 9 ships, and the measurement parameters are frozen until then — widening what counts as adoption mid-window invalidates the comparison the window exists to enable.

- [ ] Record the date in `specs/backlog.md` with the three outcomes: Configure pane used → keep; only Observe used → **remove wave 9** and keep the TUI read-only; not invoked at all → remove the TUI and keep wave 5, because the renderable refactor is what made the views testable and is worth having regardless.

---

## Self-review

**Spec coverage.** D1 → Tasks 2, 3. D2 → Tasks 6, 8. D3 → Task 9. D4 → Task 10. D5 → Task 6 Step 4 and the global constraints. D6 → Task 5. D7's phasing is the wave structure. Kill criteria → Task 12.

**Placeholders.** Waves 7–9 compress per-step implement/run/commit cycles, since Tasks 1–3 establish the pattern in full. Every task names its files, its test code and its acceptance. Task 9 carries both its tests in full because it is the write path.

**Type consistency.** `render(ctx) -> RenderableType` across the six single-argument views, with `overview`, `sessions` and `tokens` keeping their extra parameters; `build_rows(registry, cfg) -> list[Row]` with `Row.widget in {"checkbox", "radio"}`; `save_and_verify(cfg, path, toggled) -> list[VerifyResult]`. `Capability` and `builtin_registry` come from wave 6 unchanged.

**Open risk.** Task 2's per-view diffs may not be empty for `overview` and `cron`, because wave 3 changed what they render — `UNKNOWN` states did not exist when the fixtures could first have been captured. Capture the fixtures in Task 1 **after** wave 3 has merged, which the branch ordering already enforces.
