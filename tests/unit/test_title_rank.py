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
