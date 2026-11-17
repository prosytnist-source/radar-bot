"""Телеграм-канали як ранній сигнал: читаємо публічну веб-версію t.me/s/<канал> (без ключів і бота).
Тексти з каналів НЕ публікуються й не цитуються: вони лише підказують, що тема в черзі застаріла й її час оновити з RSS."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (compatible; RadarWatch/1.0)"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def parse(page: str) -> list[dict]:
    """Пости зі сторінки t.me/s/...: [{id, t (UTC), text}]."""
    out = []
    for chunk in page.split("tgme_widget_message_wrap")[1:]:
        m_id = re.search(r'data-post="([^"]+)"', chunk)
        m_tx = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        m_t = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        if not (m_id and m_tx and m_t):
            continue
        try:
            t = datetime.fromisoformat(m_t.group(1)).astimezone(timezone.utc)
        except ValueError:
            continue
        text = _WS.sub(" ", html.unescape(_TAG.sub(" ", re.sub(r"<br\s*/?>", " ", m_tx.group(1))))).strip()
        out.append({"id": m_id.group(1), "t": t, "text": text})
    return out


def fetch_channel(name: str, timeout: float = 20) -> list[dict]:
    req = Request(f"https://t.me/s/{name}", headers={"User-Agent": UA, "Accept-Language": "uk,en;q=0.8"})
    with urlopen(req, timeout=timeout) as r:  # noqa: S310
        return parse(r.read().decode("utf-8", "replace"))


def fresh(posts: list[dict], now: datetime, minutes: float) -> list[dict]:
    cut = now - timedelta(minutes=minutes)
    return [p for p in posts if p["t"] >= cut]


def stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[\w']+", text.lower()) if len(w) >= 4}


def overlap(headline: str, text: str) -> bool:
    """Пост стосується теми заголовка: ≥2 спільні основи слів і ≥30 % основ заголовка."""
    hs = stems(headline)
    sh = hs & stems(text)
    return len(sh) >= 2 and len(sh) / max(len(hs), 1) >= 0.3
