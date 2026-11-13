from __future__ import annotations

import time

from lazy_harness.knowledge.title_rank import TitleEntry, rank_titles

_OLD = "grep -q under pipefail gives a false negative"


def test_old_similar_title_beats_recent_unrelated() -> None:
    recent = [
        TitleEntry(f"Unrelated topic number {i} about widgets", "p", 1000.0 + i) for i in range(60)
    ]
    old = TitleEntry(_OLD, "p", 1.0)
    ranked = rank_titles("pipefail grep -q false negative in a pipe", [*recent, old], 50, None)
    assert ranked[0] == old
    assert len(ranked) == 50


def test_same_project_breaks_ties() -> None:
    other = TitleEntry("shared words here", "other", 5.0)
    mine = TitleEntry("shared words here", "lazy-harness", 1.0)
    ranked = rank_titles("shared words here", [other, mine], 2, "lazy-harness")
    assert ranked[0] == mine


def test_empty_query_returns_most_recent() -> None:
    entries = [TitleEntry(f"title {i}", "p", float(i)) for i in range(10)]
    ranked = rank_titles("  ", entries, 3, None)
    assert [e.mtime for e in ranked] == [9.0, 8.0, 7.0]


def test_ranking_12k_titles_under_two_seconds() -> None:
    entries = [
        TitleEntry(f"learning {i} about topic{i % 97} and thing{i % 13} under load", "p", float(i))
        for i in range(12_000)
    ]
    start = time.perf_counter()
    rank_titles("topic5 thing3 load behaviour in the worker", entries, 50, "p")
    assert time.perf_counter() - start < 2.0


def _mine(title: str, mtime: float = 1.0) -> TitleEntry:
    return TitleEntry(title, "lazy-harness", mtime)


def _other(title: str, mtime: float = 1.0) -> TitleEntry:
    return TitleEntry(title, "other", mtime)


def test_same_project_title_with_a_lower_score_is_still_shown() -> None:
    """Spec: same project first, then global. A weaker same-project match must
    not lose its slot to three stronger global ones when k leaves room."""
    glob = [
        _other("pipefail grep false negative"),
        _other("pipefail grep false"),
        _other("pipefail grep"),
    ]
    mine = _mine("grep notes about unrelated topics at length today")
    ranked = rank_titles("pipefail grep false negative", [*glob, mine], 2, "lazy-harness")
    assert mine in ranked
    assert ranked[0] == mine


def test_same_project_takes_at_most_half_of_k() -> None:
    mine = [_mine(f"grep pipefail variant{i}") for i in range(6)]
    glob = [_other(f"pipefail grep false negative case{i}") for i in range(6)]
    ranked = rank_titles("pipefail grep false negative", [*mine, *glob], 4, "lazy-harness")
    assert sum(e.origin == "lazy-harness" for e in ranked) == 2
    assert len(ranked) == 4


def test_a_same_project_title_with_zero_score_is_not_promoted() -> None:
    unrelated_mine = _mine("completely different words here", mtime=99.0)
    glob = [_other("pipefail grep false negative"), _other("pipefail grep")]
    ranked = rank_titles("pipefail grep false negative", [unrelated_mine, *glob], 2, "lazy-harness")
    assert unrelated_mine not in ranked


def test_the_same_title_is_never_listed_twice() -> None:
    best = _mine("pipefail grep false negative")
    glob = [_other(f"pipefail grep case{i}") for i in range(5)]
    ranked = rank_titles("pipefail grep false negative", [best, *glob], 4, "lazy-harness")
    assert len(ranked) == len(set(ranked)) == 4
    assert ranked.count(best) == 1
