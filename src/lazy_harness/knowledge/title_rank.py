"""Rank learning titles by similarity to a query, stdlib only.

The compound loop shows the evaluator the titles most like the session being
distilled, so a learning older than a day is still visible to dedup.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class TitleEntry:
    title: str
    origin: str
    mtime: float


def _vector(text: str) -> Counter[str]:
    return Counter(_TOKEN.findall(text.lower()))


def rank_titles(
    query: str, titles: list[TitleEntry], k: int, project: str | None
) -> list[TitleEntry]:
    """Top `k` titles by cosine similarity to `query`.

    Ties go to the same `origin` as `project`, then to the newer `mtime`. A query
    with no tokens scores every title 0, so it ranks by recency alone.
    """
    qvec = _vector(query)
    qnorm = math.sqrt(sum(v * v for v in qvec.values()))
    scored: list[tuple[float, bool, float, TitleEntry]] = []
    for entry in titles:
        tvec = _vector(entry.title)
        dot = sum(n * tvec[tok] for tok, n in qvec.items() if tok in tvec)
        score = dot / (qnorm * math.sqrt(sum(v * v for v in tvec.values()))) if dot else 0.0
        scored.append((score, project is not None and entry.origin == project, entry.mtime, entry))
    scored.sort(key=lambda t: t[:3], reverse=True)
    return [t[3] for t in scored[:k]]
