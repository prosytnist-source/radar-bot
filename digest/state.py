"""Пам'ять каналу: що вже опубліковано (щоб не повторюватись) і чи не стоїть пауза. Зберігається у теці state/ поруч із програмою."""
from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timedelta

from .cluster import tokens

KEEP_DAYS = 3
DUP_WINDOW_H = 48
JACCARD = 0.5


def stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[\w']+", text.lower()) if len(w) >= 4}


def similar_headlines(a: str, b: str) -> bool:
    """Два заголовки про одне й те саме: щонайменше 2 спільні основи слів і ≥35 % меншого набору."""
    x, y = stems(a), stems(b)
    sh = x & y
    return len(sh) >= 2 and len(sh) / max(min(len(x), len(y)), 1) >= 0.35


def _tok(r) -> set[str]:
    return {t for i in r.cluster.items for t in tokens(i.title)}


class State:
    def __init__(self, root: pathlib.Path):
        self.dir = pathlib.Path(root)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pub_file = self.dir / "published.json"
        self.pause_file = self.dir / "PAUSED"
        try:
            self.published = json.loads(self.pub_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.published = []

    # --- черга публікацій (крапельна подача) ---
    def load_queue(self) -> list[dict]:
        try:
            return json.loads((self.dir / "queue.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def save_queue(self, q: list[dict]) -> None:
        (self.dir / "queue.json").write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")

    def last_sent(self) -> datetime | None:
        try:
            return datetime.fromisoformat((self.dir / "last_sent.txt").read_text().strip())
        except (OSError, ValueError):
            return None

    def set_last_sent(self, t: datetime) -> None:
        (self.dir / "last_sent.txt").write_text(t.isoformat(), encoding="utf-8")

    # --- журнал подій (для вечірнього звіту) ---
    def log_event(self, kind: str, headline: str, now: datetime) -> None:
        try:
            ev = json.loads((self.dir / "log.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ev = []
        ev.append({"t": now.isoformat(), "kind": kind, "headline": headline})
        cut = now - timedelta(days=7)
        ev = [e for e in ev if datetime.fromisoformat(e["t"]) >= cut]
        (self.dir / "log.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")

    def events(self) -> list[dict]:
        try:
            return json.loads((self.dir / "log.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    # --- пауза ---
    def paused(self) -> bool:
        return self.pause_file.exists()

    def set_paused(self, value: bool) -> None:
        if value:
            self.pause_file.write_text("paused\n", encoding="utf-8")
        elif self.pause_file.exists():
            self.pause_file.unlink()

    # --- повтори ---
    def is_duplicate(self, r, now: datetime) -> bool:
        links = {i.link for i in r.cluster.items}
        tk = _tok(r)
        start = now - timedelta(hours=DUP_WINDOW_H)
        for e in self.published:
            if datetime.fromisoformat(e["t"]) < start:
                continue
            if links & set(e["links"]):
                return True
            old = set(e["tokens"])
            if tk and old and len(tk & old) / len(tk | old) >= JACCARD:
                return True
        return False

    def headline_seen(self, headline: str, now: datetime) -> bool:
        start = now - timedelta(hours=DUP_WINDOW_H)
        return any(similar_headlines(headline, e.get("headline", "")) for e in self.published if datetime.fromisoformat(e["t"]) >= start)

    def add(self, r, now: datetime, headline: str = "") -> None:
        self.published.append({"t": now.isoformat(), "links": sorted({i.link for i in r.cluster.items}), "tokens": sorted(_tok(r)), "headline": headline})
        cut = now - timedelta(days=KEEP_DAYS)
        self.published = [e for e in self.published if datetime.fromisoformat(e["t"]) >= cut]
        self.pub_file.write_text(json.dumps(self.published, ensure_ascii=False), encoding="utf-8")
