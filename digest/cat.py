"""Щовечірня рубрика «Котик дня» (22:00): нове миле й кумедне зображення кота.
Спершу — генерація зображення моделлю Gemini (назву моделі шукаємо серед доступних); якщо недоступно — запасне фото
з відкритих сервісів (The Cat API, CATAAS). Підпис — коротка тепла фраза з готового списку (нічого не вигадується моделлю)."""
from __future__ import annotations

import base64
import json
import pathlib
import time
from datetime import date
from urllib.request import Request, urlopen

from . import llm

UA = {"User-Agent": "RadarBot/1.0 (https://github.com/prosytnist-source/radar-bot)"}
BUDGET = 150

# (що намалювати англійською, підпис українською)
THEMES = [
    ("a fluffy kitten asleep inside a cardboard box, soft morning light", "Якщо я вміщуюсь, то це моя коробка."),
    ("a ginger cat wearing a tiny knitted hat, cozy home", "Сьогодні в мене офіційний вигляд."),
    ("a tabby cat peeking from behind a curtain with huge eyes", "Я тут не ховаюсь. Я стратегічно спостерігаю."),
    ("a sleepy kitten curled up on a warm laptop keyboard", "Працюю. Дуже уважно працюю."),
    ("a black cat with golden eyes sitting next to a cup of tea", "Чай є, настрій є, решта на завтра."),
    ("a chubby grey cat lying belly-up in a sunny spot", "Сонячна ванна. Не турбувати до весни."),
    ("a kitten with a wool ball tangled around its paws", "Я її не чіпав. Вона сама."),
    ("a white fluffy cat sitting in a flower pot among green plants", "Тут тепер росте кіт."),
    ("a kitten wearing a tiny scarf in a snowy window", "Зимовий режим: увімкнено."),
    ("a cat balancing on a stack of books, funny curious expression", "Мудрість треба вивчати з висоти."),
    ("two kittens hugging while sleeping, pastel colors", "Дружба — це коли гріємо одне одного."),
    ("a Siamese cat looking surprised at a bowl of food", "Це точно вся порція? Я перепитаю."),
    ("a cat in a small paper bag with only the tail sticking out", "Мене тут немає. Це лише хвіст."),
    ("a kitten sitting under a tiny umbrella in a rainy cozy scene", "Дощ — привід залишитися вдома."),
    ("a ginger kitten yawning widely, comic expression", "Доба була довга. Я втомився гарно."),
    ("a cat sitting like a person on a sofa with a blanket", "Вечір. Плед. Спокій."),
    ("a tuxedo cat with a funny little mustache pattern, studio portrait", "Поважний кіт на вечірньому прийомі."),
    ("a fluffy kitten chasing a soap bubble, playful", "Піймаю! Ні, не піймаю. Ще раз!"),
    ("a calico cat sleeping on a pile of fresh laundry", "Це було чисте. Тепер — моє."),
    ("a kitten with a paper crown looking proud", "Королівський указ: мене погладити."),
    ("a cat sitting by the window watching falling autumn leaves", "Вечірній огляд території завершено."),
    ("a tiny kitten in a teacup, cute and funny", "Невеличка порція щастя."),
    ("a big fluffy Maine Coon wrapped in a blanket like a burrito", "Кіт-буріто. Не розгортати."),
]


def theme_for(d: date) -> tuple[str, str]:
    return THEMES[d.toordinal() % len(THEMES)]


def _gen_models(key: str, call=llm._call) -> list[str]:
    """Імена моделей, що вміють малювати (за назвою «image»), нові першими."""
    names = []
    try:
        out = call(f"{llm.API}/models?pageSize=200", key, None, 30)
        for m in out.get("models", []):
            n = m["name"].removeprefix("models/")
            if "image" in n and "generateContent" in m.get("supportedGenerationMethods", []) and "imagen" not in n:
                names.append(n)
    except Exception:  # noqa: BLE001
        pass
    names.sort(reverse=True)
    return names or ["gemini-2.5-flash-image"]


def generate(prompt_en: str, key: str, call=llm._call) -> bytes | None:
    """Картинка від моделі або None."""
    t0 = time.monotonic()
    for model in _gen_models(key, call)[:2]:
        if time.monotonic() - t0 > BUDGET - 50:
            break
        payload = {"contents": [{"role": "user", "parts": [{"text": f"Create a cute, funny, high-quality picture: {prompt_en}. No text, no letters, no watermark."}]}],
                   "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
        try:
            out = call(f"{llm.API}/models/{model}:generateContent", key, payload, 60)
            for part in out["candidates"][0]["content"]["parts"]:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    raw = base64.b64decode(inline["data"])
                    if len(raw) > 5000:
                        return raw
        except Exception:  # noqa: BLE001
            continue
    return None


def _get(url: str, timeout: int = 25) -> bytes:
    with urlopen(Request(url, headers=UA), timeout=timeout) as r:  # noqa: S310
        return r.read()


def stock_photo(get=_get) -> bytes | None:
    """Запасний варіант: випадкове фото кота з відкритих сервісів."""
    try:
        meta = json.loads(get("https://api.thecatapi.com/v1/images/search?mime_types=jpg,png"))
        raw = get(meta[0]["url"])
        if len(raw) > 5000:
            return raw
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = get("https://cataas.com/cat")
        if len(raw) > 5000:
            return raw
    except Exception:  # noqa: BLE001
        pass
    return None


def build(today: date, key: str | None, out_dir="/tmp", call=llm._call, get=_get):
    """→ (путь, підпис, походження) або None."""
    prompt, line = theme_for(today)
    img, origin = None, ""
    if key:
        img = generate(prompt, key, call)
        origin = "ШІ-картинка"
    if img is None:
        img = stock_photo(get)
        origin = "фото з відкритого сервісу (ШІ-картинка недоступна)"
    if img is None:
        return None
    path = pathlib.Path(out_dir) / f"cat-{today.isoformat()}.jpg"
    path.write_bytes(img)
    caption = f"<b>Котик дня 🐱</b>\n{line}"
    return path, caption, origin
