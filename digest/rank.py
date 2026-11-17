"""Рейтинг подій: скільки різних видань пишуть, наскільки це свіже і наскільки швидко зростає."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .cluster import Cluster

# Матеріали про культуру, спорт і розваги не вилучаємо, але вони йдуть нижче за політику, війну й економіку.
SOFT = re.compile(r"/(culture|entertainment|sport|sports|football|lifestyle|travel|celebrity|music|film|movies|tv|arts|style|food)(/|-|_)", re.I)
SOFT_FACTOR = 0.4
WINDOWS_HOURS = {"hour": 3, "day": 24, "week": 168}


@dataclass
class Ranked:
    cluster: Cluster
    score: float
    sources: int
    fresh_sources: int
    single_source: bool
    soft: bool = False
    countries: int = 0


def rank(clusters: list[Cluster], now: datetime, window: str = "day", min_sources: int = 2, top: int = 10) -> list[Ranked]:
    hours = WINDOWS_HOURS[window]
    start = now - timedelta(hours=hours)
    fresh_start = now - timedelta(hours=max(hours / 4, 0.5))
    out: list[Ranked] = []
    for c in clusters:
        inside = [i for i in c.items if i.published >= start]
        if not inside:
            continue
        srcs = {i.source_id for i in inside}
        fresh = {i.source_id for i in inside if i.published >= fresh_start}
        age_h = max((now - max(i.published for i in inside)).total_seconds() / 3600, 0.0)
        recency = math.exp(-age_h / (hours / 2))
        countries = {i.country for i in inside if i.country}
        # різноманітність країн важить більше за кількість видань: «радар» цінний, коли думки з різних куточків світу
        score = len(srcs) + 0.5 * len(fresh) + 2.0 * recency + 0.8 * min(len(countries), 6)
        soft = sum(1 for i in inside if SOFT.search(i.link)) * 4 >= len(inside)  # чверті матеріалів із розділу «культура/спорт» достатньо
        if soft:
            score *= SOFT_FACTOR
        out.append(Ranked(Cluster(items=inside, vec=c.vec), score, len(srcs), len(fresh), len(srcs) < min_sources, soft, len(countries)))
    # події з одного джерела не відкидаємо, але вони йдуть після підтверджених
    out.sort(key=lambda r: (r.single_source, -r.score))  # м'які теми вже здешевлені коефіцієнтом
    return out[:top]
