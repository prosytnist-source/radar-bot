"""Фото без повторів: пам'ятаємо, які ілюстрації вже використані (state/images.json, 30 діб), і не беремо їх удруге."""
from __future__ import annotations

import io
import json
import pathlib
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

KEEP_DAYS = 30


def key(url: str) -> str:
    """Адреса без параметрів (?w=800 тощо) і без регістру: та сама картинка в різних розмірах — одна."""
    s = urlsplit(url or "")
    return f"{s.netloc}{s.path}".lower()


def usable(url: str, timeout: float = 10, min_side: int = 300, max_bytes: int = 2_000_000) -> bool:
    """Справжнє фото, а не заглушка: це зображення, не менше min_side пікселів з меншого боку й не однотонне (біла чи чорна картинка — не фото).
    Не вдалося завантажити чи розпізнати — не використовуємо (ставимо власну картку)."""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; RadarBot/1.0)", "Accept": "image/*"})
        with urlopen(req, timeout=timeout) as r:  # noqa: S310
            ctype = (r.headers.get("Content-Type") or "").lower()
            data = r.read(max_bytes)
    except Exception:  # noqa: BLE001
        return False
    if not ctype.startswith("image/") or len(data) < 8000:
        return False
    try:
        from PIL import Image, ImageFile, ImageStat
    except ImportError:
        return True  # без Pillow глибше перевірити не можемо
    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        im = Image.open(io.BytesIO(data))
        if min(im.size) < min_side:
            return False
        small = im.convert("L").resize((64, 64))
        return ImageStat.Stat(small).stddev[0] >= 12  # майже однотонне — заглушка
    except Exception:  # noqa: BLE001
        return False


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
