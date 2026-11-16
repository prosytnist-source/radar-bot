"""Текстова чернетка для перегляду людиною (поки без ШІ-синтезу і публікації)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .rank import Ranked

TYPE_LABEL = {
    "public": "суспільне мовлення",
    "state": "державне фінансування",
    "commercial": "комерційне",
    "nonprofit": "некомерційне / донори",
    "independent_exile": "незалежне, у екзилі",
}


def label(src: dict) -> str:
    base = TYPE_LABEL.get(src.get("type", ""), src.get("type", ""))
    country = src.get("country", "")
    text = f"{country}, {base}" if country else base
    if src.get("caution"):
        text += f" ⚠️ {src['caution']}"
    return text


def render(ranked: list[Ranked], sources: dict[str, dict], now: datetime, tz: str = "Europe/Kyiv", window: str = "day") -> str:
    z = ZoneInfo(tz)
    lines = [f"# Чернетка дайджесту: {window}", f"Станом на {now.astimezone(z):%d.%m.%Y %H:%M} ({tz})", ""]
    if not ranked:
        lines.append("_За цей період подій не знайдено._")
    for n, r in enumerate(ranked, 1):
        items = sorted(r.cluster.items, key=lambda i: i.published, reverse=True)
        head = items[0]
        lines.append(f"## {n}. {head.title}")
        lines.append(f"Видань: {r.sources} · свіжих (остання чверть вікна): {r.fresh_sources} · рейтинг {r.score:.1f}")
        if r.single_source:
            lines.append("⚠️ Це повідомляє лише одне видання: ще не підтверджено кількома джерелами.")
        seen: set[str] = set()
        for it in items:
            if it.source_id in seen:
                continue
            seen.add(it.source_id)
            src = sources.get(it.source_id, {})
            lines.append(f"- **{it.source_name}** ({label(src)}) · {it.published.astimezone(z):%d.%m %H:%M}: [{it.title}]({it.link})")
        lines.append("")
    return "\n".join(lines)
