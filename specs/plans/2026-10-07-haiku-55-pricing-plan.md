# Haiku 5.5 prompt-length pricing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD: every production line follows a failing test you watched fail.

**Goal:** Price `claude-haiku-5-5` at its short and long prompt-length rates per request, fix the `claude-sonnet-5-5` cache-read rate, declare `context_class` on the Anthropic rate table, and pin the Claude Code alias targets with a completeness test.

**Architecture:** `DEFAULT_PRICING` keeps one short-prompt row per model. `LONG_CONTEXT_PRICING` holds the threshold and higher rates for the models priced by prompt length. `anthropic_context_class` classifies one response from `input + cache_read + cache_create + cache_create_1h`. Ingest and `session_cost_from_disk` aggregate per `(session, model, context_class)` and price each class bucket at its own rates. Stored rows stay per `(session, model)`.

**Tech Stack:** Python 3.11+, pytest, ruff, uv, SQLite (`monitoring/db.py`).

**Spec:** `specs/adrs/070-anthropic-prompt-length-pricing-is-classified-per-response.md`. Read it before Task 1.

## Global constraints

- Work only in the worktree the orchestrator assigns. Never on `main`.
- Commits use `type: short description`, with no AI trailers and never `--no-verify`. Use one commit per task, `fix:` or `feat:` as named in each task.
- Before every commit, run the four gate commands and keep their tail output for your report:
  `uv run --frozen pytest -q`, `uv run --frozen ruff check src tests`, `uv run --frozen ruff format --check src tests`, `uv run --frozen --group docs mkdocs build --strict`.
  If the last one errors on flag order, run `uv run --group docs --frozen mkdocs build --strict`.
- Never hand-bump versions. Never touch `~/.config/lazy-harness`, `~/.claude-*` or `~/.codex-*`, and never run `lh deploy` or `lh metrics ingest` against the live DB.
- Public repo: keep personal names out of code, docs and commits.
- **Mutation check** in each task: after the task is green, remove or alter the named guard **by hand in the editor**. Run the named test and see it fail, then restore by hand. Never use `git checkout` or `git restore`, which also revert uncommitted work. Record each mutation and its failing assertion in your report.
- Rates, per million tokens, from platform.claude.com/docs/en/about-claude/pricing (read 2026-10-07):
  - `claude-haiku-5-5` short (prompt ≤ 100,000): `input 0.10, output 0.50, cache_read 0.01, cache_create 0.125, cache_create_1h 0.20`
  - `claude-haiku-5-5` long (prompt > 100,000): `input 0.50, output 2.50, cache_read 0.05, cache_create 0.625, cache_create_1h 1.0`
  - `claude-sonnet-5-5`: `cache_read 0.10`. The other fields are unchanged.

## Review focus

1. A session whose responses are each under 100K but whose sum is over 100K must bill at the short rate (Task 7).
2. Cache writes count toward the prompt size. Cache reads count too. The comparison is strict `>`.
3. A `[monitoring.pricing]` override of `claude-haiku-5-5` must never be switched to the shipped long rates.
4. A flat-priced model must bill the same whichever class it is given.
5. `price_api_response` and `calculate_cost` must give the same figure for every `(model, context_class)` key.

---

### Task 1: Alias completeness test and the Haiku 5.5 short row (`feat:`)

**Files:** `tests/unit/test_pricing.py`, `src/lazy_harness/monitoring/pricing.py`

- [ ] **Red.** Append to `tests/unit/test_pricing.py`:

```python
# What each Claude Code model alias resolved to, probed 2026-10-07 with
# Claude Code 2.1.293: `claude -p --model <alias> --output-format json
# "Reply with ok"` reports the resolved id as the `modelUsage` key. Re-probe
# when Anthropic ships a model, and update this map: an alias that moves to an
# unpriced model makes every `flat_rate` row `unknown_model` silently, because
# `unknown_models` only fires for `per_token` profiles.
CLAUDE_CODE_ALIAS_TARGETS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}


@pytest.mark.parametrize(("alias", "model"), sorted(CLAUDE_CODE_ALIAS_TARGETS.items()))
def test_every_claude_code_alias_target_is_priced(alias: str, model: str) -> None:
    from lazy_harness.monitoring.pricing import DEFAULT_PRICING, price_api_response

    assert model in DEFAULT_PRICING, f"`{alias}` resolves to {model}, which has no rate"
    result = price_api_response(
        model, {"input": 1}, service_tier="standard", context_class=None, on="2026-10-07"
    )
    assert result.status == "priced"


def test_default_pricing_includes_haiku_5_5_short_rates() -> None:
    from lazy_harness.monitoring.pricing import default_pricing

    assert default_pricing()["claude-haiku-5-5"] == {
        "input": 0.10,
        "output": 0.50,
        "cache_read": 0.01,
        "cache_create": 0.125,
        "cache_create_1h": 0.20,
    }
```

  Run `uv run --frozen pytest tests/unit/test_pricing.py -q -k "alias_target or haiku_5_5"`. Expected: the `haiku` case and the rate test fail with `KeyError`/`AssertionError`. `sonnet` and `opus` pass.

- [ ] **Green.** In `DEFAULT_PRICING`, insert before `"claude-haiku-4-5-20251001"`:

```python
    # Haiku 5.5 is the one current model priced by prompt length. This row is
    # the rate for prompts up to 100K tokens; the higher tier lives in
    # LONG_CONTEXT_PRICING (ADR-070).
    "claude-haiku-5-5": {
        "input": 0.10,
        "output": 0.50,
        "cache_read": 0.01,
        "cache_create": 0.125,
        "cache_create_1h": 0.20,
    },
```

  The `LONG_CONTEXT_PRICING` name in the comment is created in Task 4. Re-run the same `-k`: all green.

- [ ] **Mutation.** Delete the `claude-haiku-5-5` row. `test_every_claude_code_alias_target_is_priced[haiku-claude-haiku-5-5]` fails. Restore it.
- [ ] Gate, then commit `feat: price claude-haiku-5-5 short prompts and pin alias targets`.

### Task 2: Sonnet 5.5 cache reads at $0.10 (`fix:`)

**Files:** `tests/unit/test_pricing.py`, `src/lazy_harness/monitoring/pricing.py`

- [ ] **Red.** In `test_default_pricing_includes_sonnet_5_5`, change the expected `"cache_read": 0.2` to `"cache_read": 0.1`. Add:

```python
def test_sonnet_5_5_cache_reads_bill_at_five_percent_of_input() -> None:
    """Published: "$0.10 / MTok", 0.05x base input, like Opus 5.5.

    The row was a copy of claude-sonnet-5 (0.1x) and charged every read twice.
    """
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    cost = calculate_cost("claude-sonnet-5-5", {"cache_read": 1_000_000}, default_pricing())
    assert cost == pytest.approx(0.10)
```

  Run `-k sonnet_5_5`. Both fail with `0.2`.

- [ ] **Green.** Set `claude-sonnet-5-5` `"cache_read": 0.1` and add this comment above the row: `# Sonnet 5.5 reads bill at 0.05x base input ($0.10), like Opus 5.5 — not sonnet-5's 0.1x.` Re-run: green.
- [ ] **Mutation.** Put back `0.2`. The new test fails with `0.2 != 0.1`. Restore.
- [ ] Gate, then commit `fix: bill claude-sonnet-5-5 cache reads at 0.05x input`.

### Task 3: Anthropic API-equivalent keeps sub-micro amounts (`fix:`)

**Files:** `tests/unit/test_pricing.py`, `src/lazy_harness/monitoring/pricing.py`

- [ ] **Red.** Add next to `test_api_equivalent_keeps_sub_micro_response_costs`:

```python
def test_api_equivalent_keeps_sub_micro_anthropic_response_costs() -> None:
    """Rounding per response erased this; measured 0.0 on 2026-10-07."""
    from lazy_harness.monitoring.pricing import price_api_response

    result = price_api_response(
        "claude-opus-5", {"cache_read": 1}, service_tier="standard", context_class=None, on=None
    )
    assert result.status == "priced"
    assert result.amount == pytest.approx(0.0000005)
```

  Run it. It fails with `0.0`.

- [ ] **Green.** In `pricing.py`, split `calculate_cost` into two module-private helpers and keep its signature:

```python
def _select_rates(
    model: str,
    pricing: dict[str, dict[str, float]],
    *,
    on: str | None,
) -> dict[str, float] | None:
    rates = pricing.get(model)
    if not rates:
        return None
    intro = INTRODUCTORY_PRICING.get(model)
    if intro and on and intro.covers(on) and rates == DEFAULT_PRICING.get(model):
        rates = intro.rates
    return rates


def _raw_cost(rates: dict[str, float], tokens: dict[str, int]) -> float:
    one_hour = rates.get("cache_create_1h", 2.0 * rates.get("input", 0.0))
    return (
        tokens.get("input", 0) * rates.get("input", 0)
        + tokens.get("output", 0) * rates.get("output", 0)
        + tokens.get("cache_read", 0) * rates.get("cache_read", 0)
        + tokens.get("cache_create", 0) * rates.get("cache_create", 0)
        + tokens.get("cache_create_1h", 0) * one_hour
    ) / 1_000_000
```

  Move the existing comments of `calculate_cost` onto the matching lines of the helpers. `calculate_cost` becomes: `rates = _select_rates(model, pricing, on=on)`, `if not rates: return 0.0`, `return round(_raw_cost(rates, tokens), 6)`. In the Anthropic branch of `price_api_response`, replace `calculate_cost(model, tokens, DEFAULT_PRICING, on=on)` with `_raw_cost(_select_rates(model, DEFAULT_PRICING, on=on) or {}, tokens)`. Update that branch's comment: both figures come from the same `_select_rates`/`_raw_cost`, and only the per-session figure rounds.

- [ ] Run `uv run --frozen pytest tests/unit/test_pricing.py tests/unit/test_ingest.py tests/unit/test_collector.py -q`: green.
- [ ] **Mutation.** Wrap the Anthropic amount in `round(..., 6)`. The new test fails with `0.0`. Restore.
- [ ] Gate, then commit `fix: keep sub-micro anthropic api-equivalent amounts`.

### Task 4: `LONG_CONTEXT_PRICING` and `anthropic_context_class` (`feat:`)

**Files:** `tests/unit/test_pricing.py`, `src/lazy_harness/monitoring/pricing.py`

- [ ] **Red.** Add:

```python
def test_haiku_5_5_carries_its_published_long_prompt_tier() -> None:
    from lazy_harness.monitoring.pricing import LONG_CONTEXT_PRICING, LongContextRate

    assert LONG_CONTEXT_PRICING == {
        "claude-haiku-5-5": LongContextRate(
            threshold=100_000,
            rates={
                "input": 0.50,
                "output": 2.50,
                "cache_read": 0.05,
                "cache_create": 0.625,
                "cache_create_1h": 1.0,
            },
        )
    }


@pytest.mark.parametrize("bucket", ["cache_create", "cache_create_1h", "cache_read"])
def test_anthropic_prompt_size_counts_every_cached_bucket(bucket: str) -> None:
    """Anthropic reports cache reads and writes beside `input_tokens`, not in it.

    The one Haiku 5.5 response observed so far is 2 input tokens and 47,703
    1-hour write tokens: the prompt is almost entirely cache write.
    """
    from lazy_harness.monitoring.pricing import anthropic_context_class

    assert anthropic_context_class("claude-haiku-5-5", {"input": 2, bucket: 120_000}) == "long"


def test_anthropic_context_boundary_is_strict() -> None:
    """Published as "over 100,000 tokens"."""
    from lazy_harness.monitoring.pricing import anthropic_context_class

    assert anthropic_context_class("claude-haiku-5-5", {"input": 100_000}) == "short"
    assert anthropic_context_class("claude-haiku-5-5", {"input": 100_000, "cache_read": 1}) == "long"


def test_a_flat_priced_anthropic_model_is_always_short() -> None:
    from lazy_harness.monitoring.pricing import anthropic_context_class

    assert anthropic_context_class("claude-opus-5-5", {"input": 900_000}) == "short"
    assert anthropic_context_class("claude-unknown-9", {"input": 900_000}) == "short"
```

  Run `-k "long_prompt_tier or prompt_size or context_boundary or flat_priced"`. All fail with `ImportError`.

- [ ] **Green.** After `INTRODUCTORY_PRICING`, add:

```python
@dataclass(frozen=True)
class LongContextRate:
    """A higher tier a model bills for prompts above a published size (ADR-070)."""

    threshold: int
    """Prompt tokens above which, strictly, `rates` apply to the whole request."""

    rates: dict[str, float]


# Only Haiku 5.5 is priced by prompt length; every other current model is
# published flat across its 1M window. A config override of the model's
# DEFAULT_PRICING row is the last word and disables this tier for it.
LONG_CONTEXT_PRICING: dict[str, LongContextRate] = {
    "claude-haiku-5-5": LongContextRate(
        threshold=100_000,
        rates={
            "input": 0.50,
            "output": 2.50,
            "cache_read": 0.05,
            "cache_create": 0.625,
            "cache_create_1h": 1.0,
        },
    ),
}

# Anthropic reports `input_tokens` net of both cache buckets, and "all three
# count toward the window" — so its prompt is the sum. OpenAI's differs
# (ADR-067): its input already includes the write.
_ANTHROPIC_PROMPT_BUCKETS = ("input", "cache_read", "cache_create", "cache_create_1h")


def anthropic_context_class(model: str, tokens: dict[str, int]) -> str:
    """Classify one response. Never call it on a session's summed tokens."""
    tier = LONG_CONTEXT_PRICING.get(model)
    if tier is None:
        return "short"
    gross = sum(int(tokens.get(name, 0) or 0) for name in _ANTHROPIC_PROMPT_BUCKETS)
    return "long" if gross > tier.threshold else "short"
```

  Re-run: green.

- [ ] **Mutation A.** Remove `"cache_create_1h"` from `_ANTHROPIC_PROMPT_BUCKETS`. The `[cache_create_1h]` case fails. Restore.
- [ ] **Mutation B.** Change `>` to `>=`. `test_anthropic_context_boundary_is_strict` fails. Restore.
- [ ] Gate, then commit `feat: classify anthropic responses by prompt length`.

### Task 5: `calculate_cost` and `cost_for_billing_model` take a `context_class` (`feat:`)

**Files:** `tests/unit/test_pricing.py`, `src/lazy_harness/monitoring/pricing.py`

Fixture used below: `_LONG_HAIKU = {"input": 2, "output": 1000, "cache_create_1h": 120_000}`, a module-level constant in the test file. Long: `(2*0.5 + 1000*2.5 + 120_000*1.0) / 1e6 = 0.122501`. Short: `(2*0.1 + 1000*0.5 + 120_000*0.2) / 1e6 = 0.0245002`.

- [ ] **Red.** Add:

```python
_LONG_HAIKU = {"input": 2, "output": 1000, "cache_create_1h": 120_000}


def test_calculate_cost_bills_a_long_haiku_5_5_request_at_the_long_tier() -> None:
    """The whole request moves tier — output and writes included."""
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    assert calculate_cost(
        "claude-haiku-5-5", _LONG_HAIKU, pricing, context_class="long"
    ) == pytest.approx(0.122501, abs=1e-6)
    assert calculate_cost(
        "claude-haiku-5-5", _LONG_HAIKU, pricing, context_class="short"
    ) == pytest.approx(0.0245002, abs=1e-6)


def test_a_long_class_on_a_flat_model_bills_the_standing_rate() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    assert calculate_cost(
        "claude-opus-5-5", {"input": 1_000_000}, default_pricing(), context_class="long"
    ) == pytest.approx(4.0)


def test_an_overridden_haiku_5_5_row_never_switches_to_the_shipped_long_tier() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, load_pricing

    pricing = load_pricing(
        {
            "claude-haiku-5-5": {
                "input": 0.3,
                "output": 1.0,
                "cache_read": 0.03,
                "cache_create": 0.375,
                "cache_create_1h": 0.6,
            }
        }
    )
    assert calculate_cost(
        "claude-haiku-5-5", {"input": 1_000_000}, pricing, context_class="long"
    ) == pytest.approx(0.3)


def test_an_unknown_context_class_is_refused() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    with pytest.raises(ValueError, match="context_class"):
        calculate_cost("claude-haiku-5-5", {"input": 1}, default_pricing(), context_class="medium")


def test_cost_for_billing_model_forwards_the_context_class() -> None:
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    assert cost_for_billing_model(
        "claude-haiku-5-5",
        {"input": 1_000_000},
        default_pricing(),
        billing_model="per_token",
        context_class="long",
    ) == (pytest.approx(0.5), "pricing")
```

  Run `-k "long_haiku or flat_model or overridden_haiku or unknown_context or forwards_the_context"`. All fail with `TypeError: unexpected keyword argument 'context_class'`.

- [ ] **Green.**
  - `_select_rates` gains a keyword `context_class: str`. Its first line is `if context_class not in ("short", "long"): raise ValueError(f"context_class must be 'short' or 'long', got {context_class!r}")`. After the intro block and before `return rates`, add: `tier = LONG_CONTEXT_PRICING.get(model)` then `if context_class == "long" and tier is not None and pricing.get(model) == DEFAULT_PRICING.get(model): rates = tier.rates`.
  - `calculate_cost(..., *, on: str | None = None, context_class: str = "short")` passes it through. In its docstring, add one sentence: the class belongs to one response, so callers classify before summing (ADR-070).
  - `cost_for_billing_model(..., context_class: str = "short")` passes it to `calculate_cost`.
  - The Anthropic branch of `price_api_response` passes `context_class="short"` for now. Task 6 replaces it.
- [ ] Run the full `tests/unit/test_pricing.py`: green.
- [ ] **Mutation A.** Remove the `pricing.get(model) == DEFAULT_PRICING.get(model)` condition. The override test fails with `0.5`. Restore.
- [ ] **Mutation B.** In `cost_for_billing_model`, drop `context_class=context_class` from the call. The forwarding test fails. Restore.
- [ ] Gate, then commit `feat: price a context class in calculate_cost`.

### Task 6: The Anthropic rate table declares `context_class` (`feat:`)

**Files:** `tests/unit/test_pricing.py`, `src/lazy_harness/monitoring/pricing.py`

- [ ] **Red.** Add:

```python
def test_anthropic_table_declares_a_derived_context_class() -> None:
    from lazy_harness.monitoring.pricing import API_RATE_TABLES

    table = API_RATE_TABLES["anthropic"]
    assert table.dimensions == ("context_class",)
    assert table.required == ()
    assert table.version == "anthropic-2026-10-07"


def test_only_a_model_with_a_long_tier_has_distinct_long_rates() -> None:
    from lazy_harness.monitoring.pricing import (
        API_RATE_TABLES,
        DEFAULT_PRICING,
        LONG_CONTEXT_PRICING,
    )

    rates = API_RATE_TABLES["anthropic"].rates
    for model, row in DEFAULT_PRICING.items():
        assert rates[(model, "short")] == row
        expected_long = LONG_CONTEXT_PRICING[model].rates if model in LONG_CONTEXT_PRICING else row
        assert rates[(model, "long")] == expected_long


def test_api_equivalent_derives_the_haiku_5_5_class_from_the_prompt() -> None:
    from lazy_harness.monitoring.pricing import price_api_response

    result = price_api_response(
        "claude-haiku-5-5", _LONG_HAIKU, service_tier="standard", context_class=None, on="2026-10-07"
    )
    assert result.status == "priced"
    assert result.amount == pytest.approx(0.122501)
    assert result.basis is not None
    assert result.basis.rate_table_version == "anthropic-2026-10-07"


def test_an_explicit_anthropic_context_class_beats_the_derivation() -> None:
    from lazy_harness.monitoring.pricing import price_api_response

    result = price_api_response(
        "claude-haiku-5-5", _LONG_HAIKU, service_tier="standard", context_class="short", on=None
    )
    assert result.amount == pytest.approx(0.0245002)


def test_api_equivalent_and_calculate_cost_agree_on_every_anthropic_key() -> None:
    """Two paths answer one question; they must give one answer."""
    from lazy_harness.monitoring.pricing import (
        API_RATE_TABLES,
        DEFAULT_PRICING,
        calculate_cost,
        price_api_response,
    )

    tokens = dict.fromkeys(
        ("input", "output", "cache_read", "cache_create", "cache_create_1h"), 1_000_000
    )
    for (model, context_class), rates in API_RATE_TABLES["anthropic"].rates.items():
        equivalent = price_api_response(
            model, tokens, service_tier="standard", context_class=context_class, on=None
        )
        billed = calculate_cost(model, tokens, DEFAULT_PRICING, context_class=context_class)
        assert equivalent.amount == pytest.approx(billed) == pytest.approx(sum(rates.values()))
```

  Run `-k "derived_context_class or distinct_long or derives_the_haiku or explicit_anthropic or agree_on_every"`. They fail on the declaration, the `KeyError` on tuple keys, and the short-rate amount.

- [ ] **Green.**
  - `_ANTHROPIC_API_RATE_VERSION = "anthropic-2026-10-07"`.
  - Add, after `LONG_CONTEXT_PRICING` and before `API_RATE_TABLES` (move `API_RATE_TABLES` below `LONG_CONTEXT_PRICING` if needed):

```python
def _anthropic_rates() -> dict[tuple[str, str], dict[str, float]]:
    """Key every model by class; a flat-priced model's two rows are equal."""
    rates: dict[tuple[str, str], dict[str, float]] = {}
    for model, row in DEFAULT_PRICING.items():
        tier = LONG_CONTEXT_PRICING.get(model)
        rates[(model, "short")] = row
        rates[(model, "long")] = tier.rates if tier is not None else row
    return rates
```

  - `API_RATE_TABLES["anthropic"]` becomes `ApiRateTable(provider="anthropic", version=_ANTHROPIC_API_RATE_VERSION, dimensions=("context_class",), rates=_anthropic_rates(), required=())`. Add a comment: the class is derived from the usage record (ADR-070), so it is never required.
  - In `price_api_response`, change `if model in anthropic.rates:` to `if model in {key[0] for key in anthropic.rates}:`. After the `required` check, set `context_class = context_class or anthropic_context_class(model, tokens)`. Then compute the amount as `_raw_cost(_select_rates(model, DEFAULT_PRICING, on=on, context_class=context_class) or {}, tokens)`.
- [ ] Run the full `tests/unit/test_pricing.py`. Green, including `test_each_rate_table_declares_the_dimensions_its_keys_carry` and `test_a_declared_dimension_is_demanded_of_anthropic_too`.
- [ ] **Mutation A.** Set the Anthropic `dimensions=()`. The arity test fails. Restore.
- [ ] **Mutation B.** Replace the derivation with `context_class = context_class or "short"`. `test_api_equivalent_derives_the_haiku_5_5_class_from_the_prompt` fails. Restore.
- [ ] **Mutation C.** Replace it with `context_class = anthropic_context_class(model, tokens)`, ignoring the caller. `test_an_explicit_anthropic_context_class_beats_the_derivation` fails. That test may pass in the red run, because Task 5 left the branch hard-coded to `"short"`. Restore.
- [ ] Gate, then commit `feat: key the anthropic rate table by context class`.

### Task 7: Ingest bills each response's class (`fix:`)

**Files:** `tests/unit/test_ingest.py`, `src/lazy_harness/monitoring/ingest.py`

- [ ] **Red.** Add, using the file's existing `_profile`, `_write_session` and `_assistant_msg` helpers:

```python
def _ingest_haiku_5_5(tmp_path: Path, *inputs: int) -> dict:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        [
            _assistant_msg(
                model="claude-haiku-5-5",
                inp=inp,
                out=0,
                ts=f"2026-10-07T10:00:{i:02d}",
                msg_id=f"msg_{i}",
            )
            for i, inp in enumerate(inputs)
        ],
    )
    db = MetricsDB(tmp_path / "metrics.db")
    try:
        ingest_profile(prof, db, load_pricing())
        return db.query_stats(period="all")[0]
    finally:
        db.close()


def test_ingest_classifies_each_request_not_the_session_sum(tmp_path: Path) -> None:
    """Two 60K prompts are two short requests; their 120K sum is no prompt at all."""
    row = _ingest_haiku_5_5(tmp_path, 60_000, 60_000)
    assert row["input_tokens"] == 120_000
    assert row["cost"] == pytest.approx(0.012)
    assert row["api_equivalent_cost"] == pytest.approx(0.012)


def test_ingest_bills_a_long_request_at_the_long_tier(tmp_path: Path) -> None:
    row = _ingest_haiku_5_5(tmp_path, 150_000, 10_000)
    # 150K at $0.50 (long) + 10K at $0.10 (short); one stored row.
    assert row["input_tokens"] == 160_000
    assert row["cost"] == pytest.approx(0.076)
    assert row["api_equivalent_cost"] == pytest.approx(0.076)
```

  Run `-k "each_request_not or long_request_at"`. Expected before the fix: `test_ingest_bills_a_long_request_at_the_long_tier` fails on billed `cost` (`0.016`, everything at the short tier). `test_ingest_classifies_each_request_not_the_session_sum` already passes, because the billed path does not classify at all yet. It guards the wrong fix, which the mutation below exercises.

- [ ] **Green.** In `ingest_profile`:
  - Add `"by_class": {}` to each new `agg` dict. Keep the five summed token keys as they are, because the stored row still reads them.
  - After `response_tokens` is built, add: `context_class = event.context_class or anthropic_context_class(event.model or "unknown", response_tokens)`. Then accumulate `response_tokens` into `agg["by_class"].setdefault(context_class, dict.fromkeys(response_tokens, 0))`, key by key. Import `anthropic_context_class` from `pricing`.
  - In the pricing loop, replace the single `cost_for_billing_model` call with a sum over classes:

```python
        cost = 0.0
        cost_source: str | None = None
        for context_class, class_tokens in sorted(agg["by_class"].items()):
            class_cost, cost_source = cost_for_billing_model(
                model,
                class_tokens,
                pricing,
                billing_model=billing_model,
                on=agg["date"],
                context_class=context_class,
            )
            cost += class_cost
        cost = round(cost, 6)
```

  Every `agg` is created by an event, so `by_class` is never empty.

  `cost_source` depends only on the model and billing model, so the last call's value is every call's value. Add a one-line comment saying so.

  A non-Anthropic event (Codex) reaches `anthropic_context_class` with a model that has no `LONG_CONTEXT_PRICING` entry, so it is `"short"`, and `calculate_cost` for an OpenAI model is unchanged. The existing Codex ingest tests are the evidence; run them.
- [ ] Run `uv run --frozen pytest tests/unit/test_ingest.py -q`: green.
- [ ] **Mutation.** Replace the per-response class with `anthropic_context_class(model, <the session's summed tokens>)` computed once in the pricing loop. The first test fails with `0.06`. Restore.
- [ ] Gate, then commit `fix: bill each haiku 5.5 request at its own prompt-length tier`.

### Task 8: `lh exec` cost classifies each request, and agrees with ingest (`fix:`)

**Files:** `tests/unit/test_collector.py`, `tests/unit/test_ingest.py`, `src/lazy_harness/monitoring/collector.py`

- [ ] **Red.** In `tests/unit/test_collector.py`, using `_project_dir`, `_write_session_jsonl`, `_assistant` and `_usage`:

```python
def test_session_cost_from_disk_classifies_each_request(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import session_cost_from_disk
    from lazy_harness.monitoring.pricing import default_pricing

    project = _project_dir(tmp_path)
    session_id = "0f6b0e0e-1111-4222-8333-444455556667"
    short = _usage(inp=60_000, out=0, cache_read=0, c5m=0, c1h=0)
    long = _usage(inp=2, out=1000, cache_read=0, c5m=0, c1h=120_000)
    _write_session_jsonl(
        project / f"{session_id}.jsonl",
        [
            _assistant("msg_1", "claude-haiku-5-5", short),
            _assistant("msg_2", "claude-haiku-5-5", short),
            _assistant("msg_3", "claude-haiku-5-5", long),
        ],
    )

    cost = session_cost_from_disk(project.parent, session_id, default_pricing())

    # 2 x 60K short ($0.012) + one long write-heavy request ($0.122501).
    assert cost.cost_usd == pytest.approx(0.134501, abs=1e-6)
```

  In `tests/unit/test_ingest.py`, add the agreement test:

```python
def test_ingest_and_exec_price_a_mixed_haiku_5_5_session_alike(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import session_cost_from_disk
    from lazy_harness.monitoring.pricing import load_pricing

    row = _ingest_haiku_5_5(tmp_path, 150_000, 10_000, 60_000)
    exec_cost = session_cost_from_disk(
        tmp_path / "lazy" / "projects", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", load_pricing()
    )
    assert exec_cost.cost_usd == pytest.approx(row["cost"])
```

  Run both. Both fail: the collector sums before classifying.

- [ ] **Green.** In `session_cost_from_disk`, key `per_model` by `(model, context_class)`, where `context_class = anthropic_context_class(msg["model"], msg)`. `msg` already carries the five bucket keys. Key `dates` by the same tuple. The `unpriced` check iterates `model for model, _ in per_model`. The sum calls `calculate_cost(model, agg, pricing, on=dates[key], context_class=context_class)`. Totals are unchanged.
- [ ] Run `uv run --frozen pytest tests/unit/test_collector.py tests/unit/test_ingest.py -q`: green.
- [ ] **Mutation.** Force `context_class = "short"` in the collector. Both new tests fail. Restore.
- [ ] Gate, then commit `fix: classify each request in session_cost_from_disk`.

### Task 9: Documents that name these rates (`docs:`)

**Files:** `docs/how/metrics-ingest.md`, `docs/how/cost-reporting.md`, `docs/reference/cli.md`, `specs/backlog.md`, `docs/roadmap.md`, `specs/adrs/070-…md`, `specs/adrs/README.md`

- [ ] `docs/how/metrics-ingest.md`, section `## Pricing`. In the multiplier table, change the cache-read multiplier cell from `0.1×` to `0.1× (0.05× on Opus 5.5 and Sonnet 5.5; 0.025× on Fable 5.1 and Mythos 5.1)`. After the `### Cache writes are priced by TTL` subsection, add `### Haiku 5.5 is priced by prompt length`, at most two short paragraphs, saying:
  - a request whose prompt (`input + cache_read + cache_create + cache_create_1h`) is over 100,000 tokens pays the higher tier on every bucket, output included;
  - `LONG_CONTEXT_PRICING` holds the tier, `anthropic_context_class` classifies each response, and ingest prices each class bucket before summing, so stored rows stay per `(session, model)`;
  - a `[monitoring.pricing]` override of the model's row disables the shipped long tier for it.
- [ ] `docs/how/cost-reporting.md`: replace the three sentences from `The captured Codex` through `provide live coverage.` with:
  `API-equivalent pricing runs per response, and the context class is derived from the prompt the usage record reports: OpenAI's 272K boundary (ADR-067) and Haiku 5.5's 100K boundary (ADR-070). No reader has to supply it.`
  Leave the rest of the paragraph alone.
- [ ] `docs/reference/cli.md`, under `### lh metrics ingest`: replace `it tracks each session's file mtime in a separate \`ingest_meta\` table and skips files that haven't changed since the previous run` with `it re-reads every transcript on each run, so a pricing change reprices every session whose transcript is still on disk`.
- [ ] **Grep gate**, both directions. `grep -rn "LONG_CONTEXT_PRICING\|anthropic_context_class" docs src` must show each identifier in `src/`. `grep -rn "ingest_meta" docs` must no longer claim a skip.
- [ ] `specs/backlog.md`: under `## Done`, after the `Tarifas para \`claude-opus-5-5\`…` entry, add one entry in the surrounding style (Spanish, bold title, PR number left as `PR #<n>` for the orchestrator to fill):
  `- [x] **Haiku 5.5 se precia por largo de prompt, por request (ADR-070)** — \`claude-haiku-5-5\` preciaba 0 y \`claude-sonnet-5-5\` cobraba cada cache read al doble ($0.20 en vez de $0.10). La clase se decide por respuesta con \`input + cache_read + cache_creation\` > 100K; ingest y \`lh exec\` suman por clase y las filas siguen por sesión. Un test fija los modelos a los que resuelven los alias de Claude Code. PR #<n>.`
- [ ] `docs/roadmap.md`, Theme 6: add `- [x] Price Claude Haiku 5.5 per request by prompt length and fix the Sonnet 5.5 cache-read rate ([ADR-070](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/070-anthropic-prompt-length-pricing-is-classified-per-response.md))`.
- [ ] ADR-070: set `**Status:** accepted` and add an `**Implemented:** <date> — …` line in ADR-067's format. In `specs/adrs/README.md`, set row 070's status to `accepted`.
- [ ] Gate (the mkdocs build is the one that matters here), then commit `docs: document haiku 5.5 prompt-length pricing`.

### Task 10: Hand-off checks (report only, no commit)

- [ ] `uv run --frozen python -c "from lazy_harness.monitoring.pricing import price_api_response as p; print(p('claude-haiku-5-5', {'input': 2, 'cache_create_1h': 47703, 'output': 288}, service_tier='standard', context_class=None, on='2026-10-08'))"`. This is the one real Haiku 5.5 response observed. Expected `amount ≈ 0.0096`, status `priced`.
- [ ] Report the four gate tails, every mutation with its failing assertion, and the commit SHAs.
- [ ] **Not yours, for the orchestrator after merge and release:** reinstall `lh`, then run `lh metrics ingest` before about 2026-10-28, while every affected transcript is still on disk (ADR-070, Consequences). After that run, confirm on the live DB that the `claude-haiku-5-5` row reads `api_equivalent_status = priced`, and that summed Sonnet 5.5 `api_equivalent_cost` fell by about 0.10 USD per million stored cache-read tokens.
