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
    """Top `k` titles by cosine similarity to `query`, same project first.

    Up to half of `k` goes to the best `project` titles with a non-zero score,
    listed first; the rest come from the global ranking, never repeating a title.
    Ties go to the newer `mtime`. A query with no tokens scores every title 0,
    so it ranks by recency alone and nothing is promoted by project.
    """
    qvec = _vector(query)
    qnorm = math.sqrt(sum(v * v for v in qvec.values()))
    scored: list[tuple[float, float, TitleEntry]] = []
    for entry in titles:
        tvec = _vector(entry.title)
        dot = sum(n * tvec[tok] for tok, n in qvec.items() if tok in tvec)
        score = dot / (qnorm * math.sqrt(sum(v * v for v in tvec.values()))) if dot else 0.0
        scored.append((score, entry.mtime, entry))
    scored.sort(key=lambda t: t[:2], reverse=True)
    mine = [t[2] for t in scored if project is not None and t[2].origin == project and t[0] > 0][
        : k // 2
    ]
    chosen = list(mine)
    taken = set(mine)
    for _, _, entry in scored:
        if len(chosen) >= k:
            break
        if entry not in taken:
            chosen.append(entry)
            taken.add(entry)
    return chosen[:k]
