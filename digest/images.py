"""Фото без повторів: пам'ятаємо, які ілюстрації вже використані (state/images.json, 30 діб), і не беремо їх удруге."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta
from urllib.parse import urlsplit

KEEP_DAYS = 30


def key(url: str) -> str:
    """Адреса без параметрів (?w=800 тощо) і без регістру: та сама картинка в різних розмірах — одна."""
    s = urlsplit(url or "")
    return f"{s.netloc}{s.path}".lower()


class Used:
    def __init__(self, st):
        self.path = pathlib.Path(st.dir) / "images.json"
        try:
            self.d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.d = {}

    def has(self, url: str) -> bool:
        return bool(url) and key(url) in self.d

    def add(self, url: str, now: datetime) -> None:
        if not url:
            return
        self.d[key(url)] = now.isoformat()
        cut = now - timedelta(days=KEEP_DAYS)
        self.d = {k: v for k, v in self.d.items() if datetime.fromisoformat(v) >= cut}
        self.path.write_text(json.dumps(self.d), encoding="utf-8")
