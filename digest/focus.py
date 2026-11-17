"""Тематичний фільтр каналу: Радар збирає лише те, що закордонні видання пишуть ПРО УКРАЇНУ.
Матеріал проходить, якщо в заголовку або анонсі є одна з основ слів із sources.json → focus.require (без урахування регістру)."""
from __future__ import annotations

from .fetch import Item


def matches(item: Item, stems: list[str]) -> bool:
    text = f"{item.title} {item.summary}".lower()
    return any(s in text for s in stems)


def apply(items: list[Item], cfg: dict) -> list[Item]:
    stems = [s.lower() for s in (cfg.get("focus") or {}).get("require", [])]
    if not stems:
        return items
    return [i for i in items if matches(i, stems)]
