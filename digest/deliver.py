"""Доставка допису в канал. Є фото — показуємо його (без повторів); немає — власна картка РАДАР; немає й Pillow — просто текст."""
from __future__ import annotations

import pathlib
import sys
import tempfile
from datetime import datetime

from . import card, images, publish

CAPTION_LIMIT = 1000
photo_ok = images.usable  # перевірка перед відправкою (у тестах підміняється)


def send_card_text(token: str, chat: str, spec: dict, html_text: str) -> bool:
    """Картка + текст. Короткий текст іде підписом до картки, довгий — окремим повідомленням. False, якщо картку створити не вдалося."""
    # v6.6: кіт з газетою прибраний із постів без фото видань — коти лишаються постійними рубриками; тут звичайна картка Радара
    if not card.available():
        return False
    try:
        out = pathlib.Path(tempfile.mkdtemp()) / "card.jpg"
        card.render(spec.get("title", ""), out, spec.get("subtitle", ""), spec.get("chips"), spec.get("kind", "news"))
    except Exception as exc:  # noqa: BLE001
        print(f"(картку не створено: {exc})", file=sys.stderr)
        return False
    if len(html_text) <= CAPTION_LIMIT:
        publish.send_photo(token, chat, out, html_text)
    else:
        publish.send_photo(token, chat, out, "")
        publish.send(token, chat, html_text, None)
    return True


def send_entry(e: dict, token: str, chat: str, st=None, now: datetime | None = None) -> None:
    """Допис із черги: фото джерела, якщо воно є й ще не використане; інакше картка; інакше текст."""
    used = images.Used(st) if st is not None else None
    prev = e.get("preview")
    if prev and used and used.has(prev):
        prev = None  # це фото вже було в каналі
    if prev and not photo_ok(prev):
        prev = None  # порожня чи дрібна картинка (заглушка): краще власна картка
    html_text = e["html"]
    if prev:
        if e.get("credit"):
            html_text += "\n\n" + e["credit"]
        publish.send(token, chat, html_text, prev)
        if used and now:
            used.add(prev, now)
        return
    if e.get("card") and send_card_text(token, chat, e["card"], html_text):
        return
    publish.send(token, chat, html_text, None)
