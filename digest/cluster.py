"""Групування матеріалів різних видань в одну подію (TF-IDF + косинусна близькість, без залежностей)."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .fetch import Item

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
STOP = set(
    "the a an and or of to in on at for with by from as is are was were be been it its this that these those he she they his her their "
    "after over into about says said say will would could may might new more than not no up out amid against us".split()
)


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        w = w.strip("'’-")
        if len(w) < 3 and not w.isdigit():
            continue
        if w in STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # дуже грубе зведення множини
        out.append(w)
    return out


@dataclass
class Cluster:
    items: list[Item] = field(default_factory=list)
    vec: Counter = field(default_factory=Counter)
    words: set = field(default_factory=set)  # слова заголовків групи

    @property
    def sources(self) -> set[str]:
        return {i.source_id for i in self.items}

    @property
    def latest(self):
        return max(i.published for i in self.items)


def _vectorize(item: Item, idf: dict[str, float]) -> Counter:
    tf: Counter = Counter()
    for t in tokens(item.title):
        tf[t] += 2.0  # заголовок важить більше, ніж опис
    for t in tokens(item.summary[:300]):
        tf[t] += 0.5
    return Counter({t: c * idf.get(t, 1.0) for t, c in tf.items()})


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def cluster_items(items: list[Item], threshold: float = 0.25) -> list[Cluster]:
    """Жадібне групування: кожен матеріал іде до найближчої групи, якщо близькість ≥ threshold."""
    docs = [set(tokens(i.title + " " + i.summary[:300])) for i in items]
    df: Counter = Counter()
    for d in docs:
        df.update(d)
    n = max(len(items), 1)
    idf = {t: math.log((n + 1) / (c + 0.5)) + 1.0 for t, c in df.items()}

    clusters: list[Cluster] = []
    for item in sorted(items, key=lambda i: i.published):
        v = _vectorize(item, idf)
        words = set(tokens(item.title))
        best, best_s = None, 0.0
        for c in clusters:
            # запобіжник від хибних злиттів: мають збігатися щонайменше два слова заголовків
            if len(words & c.words) < 2:
                continue
            s = _cos(v, c.vec)
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s >= threshold:
            best.items.append(item)
            best.vec.update(v)
            best.words |= words
        else:
            clusters.append(Cluster(items=[item], vec=Counter(v), words=set(words)))
    return clusters
