"""Persist-time duplicate detection between learning titles, stdlib only.

A new learning whose title is a near-paraphrase of an active one is folded into
that note instead of becoming a new file. Similarity is cosine over IDF-weighted
tokens, with the IDF taken over the store's own titles so that words every note
shares ("test", "para") carry no weight.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

_TOKEN = re.compile(r"[a-z0-9áéíóúñ]{3,}")

_STOPWORDS = frozenset(
    "the and for that this with you are was not but have has had from they will would there "
    "their what when which who how why can could should about into than then them these those "
    "your our out all any also just like more some such only over very been being were its "
    "does did done get got use used using one two while after before "
    "que los las con por para una uno unos unas del como pero sus más mas esto esta este estos "
    "estas ese esa eso son ser fue era hay han hemos tiene tienen entre sobre sin muy también "
    "cuando donde porque todo todos toda todas ahora solo sólo ya nos les así asi está están "
    "hacer hace desde hasta cada otro otra otros otras puede pueden debe deben tras ante bajo "
    "según".split()
)


def title_tokens(title: str) -> Counter[str]:
    return Counter(w for w in _TOKEN.findall(title.lower()) if w not in _STOPWORDS)


class TitleIndex:
    """Titles keyed by an opaque value, queryable for the closest one."""

    def __init__(self) -> None:
        self._vectors: list[Counter[str]] = []
        self._keys: list[Path] = []
        self._postings: dict[str, list[int]] = {}
        self._df: Counter[str] = Counter()

    def add(self, title: str, key: Path) -> None:
        vec = title_tokens(title)
        idx = len(self._vectors)
        self._vectors.append(vec)
        self._keys.append(key)
        for tok in vec:
            self._postings.setdefault(tok, []).append(idx)
        self._df.update(vec.keys())

    def _weight(self, tok: str, count: int) -> float:
        n = len(self._vectors)
        return count * (math.log((n + 1) / (self._df.get(tok, 0) + 1)) + 1.0)

    def closest(self, title: str) -> tuple[Path, float] | None:
        """The stored key whose title is most similar to `title`, with the cosine."""
        query = title_tokens(title)
        qweights = {tok: self._weight(tok, c) for tok, c in query.items()}
        qnorm = math.sqrt(sum(w * w for w in qweights.values()))
        candidates = {i for tok in qweights for i in self._postings.get(tok, ())}
        best: tuple[Path, float] | None = None
        for i in candidates:
            vec = self._vectors[i]
            dot = sum(w * self._weight(tok, vec[tok]) for tok, w in qweights.items() if tok in vec)
            norm = math.sqrt(sum(self._weight(t, c) ** 2 for t, c in vec.items()))
            score = dot / (qnorm * norm)
            if best is None or score > best[1]:
                best = (self._keys[i], score)
        return best
