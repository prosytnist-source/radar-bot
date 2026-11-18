"""Щовечірня рубрика «Котик дня» (22:00): нове миле й кумедне зображення кота.
Генерація мультяшного зображення моделлю Gemini зі зразками стилю (assets/cat). Безкоштовні запасні варіанти (Pollinations, фото) вимкнені: їхня якість нижча (назву моделі шукаємо серед доступних). Запасні варіанти allow_free / allow_photo за замовчуванням вимкнені. Підпис — коротка тепла фраза з готового списку (нічого не вигадується моделлю)."""
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
last_error: list[str] = []

# (сцена англійською, підпис українською). Герой завжди той самий: рудий кіт у стилі 3D-мультфільму з людськими емоціями.
THEMES = [
    ("sitting at a laptop late in the evening with a steaming mug, tired but proud, finishing the day's work", "Робочий день завершено. Я молодець."),
    ("lying on a sofa under a blanket with a remote control, blissfully relaxed, cozy living room", "Вечір. Плед. Спокій."),
    ("thinking hard with a paw on the chin, question marks floating in the air as soft shapes, no letters", "Хм. Це треба обміркувати."),
    ("pouring coffee in the morning kitchen, sleepy half-closed eyes, messy fur", "Кава — це не напій, це режим запуску."),
    ("celebrating with both paws up and a huge happy smile, confetti falling", "Усе вдалося! Навіть я здивований."),
    ("holding a tiny umbrella in light rain, looking at the sky with a mildly offended face", "Знову дощ? Я ж планував гуляти."),
    ("reading a thick book in an armchair with reading glasses, a cup of tea nearby", "Мудрість приходить повільно, зате з печивом."),
    ("standing on a bathroom scale looking shocked, comedic exaggerated expression", "Це точно не мої цифри. Це зважування помилилось."),
    ("hugging a big pillow, deeply sleepy, dark circles under the eyes, late night bedroom", "Ще одну серію — і спати. Так я собі казав годину тому."),
    ("wearing a cozy knitted sweater and scarf by a snowy window, holding hot chocolate", "Зима за вікном, тепло всередині."),
    ("cooking in the kitchen with a chef's hat, proud of a slightly burnt pancake", "Це не підгоріло. Це золота скоринка."),
    ("working out with tiny dumbbells, very serious face but sweating a little", "Спорт — це коли страждаєш за власним розкладом."),
    ("carrying a pile of shopping bags, tired but happy, evening city lights behind", "Купив лише найнеобхідніше. (Не лише.)"),
    ("sitting on a window sill looking at the starry night with a dreamy gentle smile", "Іноді просто дивитися на зорі — теж робота."),
    ("peeking over a laptop with wide eyes and a nervous smile during an online meeting", "Мікрофон вимкнений? Так? Точно вимкнений?"),
    ("receiving a bouquet of flowers, blushing, heart-shaped glow around, sweet surprised look", "Мені? Дякую. Я зворушений."),
    ("headphones on, listening to music with eyes closed, swaying, colorful abstract sound waves", "Світ стишено. Музика — на повну."),
    ("sitting behind a desk with a stack of papers and a tiny tie, serious boss pose", "Нарада закінчилась, але я ще офіційний."),
    ("stretching after waking up in a sunny bedroom, yawning widely, cheerful morning mood", "Доброго ранку. Будь ласка, без швидких рішень."),
    ("in a hammock under a tree with sunglasses and a cold drink, total relaxation", "Відпустка — стан душі. Тримаю його."),
    ("holding a phone and laughing out loud at a funny video, tears of joy", "Ще один мем — і справді спати."),
    ("walking in the autumn park with fallen leaves, hands behind back, calm philosophical mood", "Осінь навчає відпускати. Листя вже навчилось."),
    ("on a scooter in a city, wind in the whiskers, joyful carefree smile", "Іду по справах. Із вітерцем."),
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


def _refs() -> list[str]:
    """Зразки стилю (assets/cat/*.jpg) у base64."""
    d = pathlib.Path(__file__).resolve().parent.parent / "assets" / "cat"
    return [base64.b64encode(f.read_bytes()).decode() for f in sorted(d.glob("*.jpg"))[:3]] if d.is_dir() else []


def generate(prompt_en: str, key: str, call=llm._call) -> bytes | None:
    """Картинка від моделі або None."""
    t0 = time.monotonic()
    models = _gen_models(key, call)
    last_error.append(f"моделі для малювання: {models[:3]}")
    for model in models[:2]:
        if time.monotonic() - t0 > BUDGET - 50:
            break
        parts = [{"text": f"Create a new square 1:1 image in EXACTLY the style and with the SAME character as the attached reference images: a charming ginger cat in a Pixar-like 3D animated movie style, extremely detailed fur, big expressive eyes, human-like emotion and pose, cinematic soft lighting, warm friendly colors. New scene: {prompt_en}. No text, no letters, no watermark, no logos."}]
        for ref in _refs():
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": ref}})
        payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
        try:
            out = call(f"{llm.API}/models/{model}:generateContent", key, payload, 60)
            for part in out["candidates"][0]["content"]["parts"]:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    raw = base64.b64decode(inline["data"])
                    if len(raw) > 5000:
                        return raw
            last_error.append(f"{model}: відповідь без зображення")
        except Exception as exc:  # noqa: BLE001
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:200]  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            last_error.append(f"{model}: {str(exc)[:60]} {body[:60]}".strip())
            if "429" in str(exc):
                break  # квота вичерпана/відсутня — друга модель теж не допоможе
            continue
    return None


def _get(url: str, timeout: int = 25) -> bytes:
    with urlopen(Request(url, headers=UA), timeout=timeout) as r:  # noqa: S310
        return r.read()


def pollinations(prompt_en: str, d: date, get=_get) -> bytes | None:
    """Безкоштовне малювання без ключа (image.pollinations.ai). Стиль — мультяшний."""
    from urllib.parse import quote
    text = f"funny adorable cartoon cat character, {prompt_en}, colorful 2D cartoon, bold clean outlines, big expressive eyes, children's book sticker style, no text"
    url = f"https://image.pollinations.ai/prompt/{quote(text)}?width=1024&height=1024&nologo=true&model=flux&seed={d.toordinal()}"
    try:
        raw = get(url, 70)
    except Exception as exc:  # noqa: BLE001
        last_error.append(f"pollinations: {str(exc)[:80]}")
        return None
    if len(raw) > 5000 and (raw[:3] == b"\xff\xd8\xff" or raw[:4] == b"\x89PNG"):
        return raw
    last_error.append("pollinations: відповідь не є зображенням")
    return None


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


def build(today: date, key: str | None, out_dir="/tmp", call=llm._call, get=_get, allow_photo: bool = False, allow_free: bool = False):
    """→ (шлях, підпис, походження) або None."""
    prompt, line = theme_for(today)
    img, origin = None, ""
    last_error.clear()
    if key:
        img = generate(prompt, key, call)
        origin = "ШІ-картинка"
    if img is None and allow_free:
        img = pollinations(prompt, today, get)
        origin = "малюнок Pollinations (безкоштовний сервіс)"
    if img is None and allow_photo:
        img = stock_photo(get)
        origin = "фото з відкритого сервісу (ШІ-картинка недоступна)"
    if img is None:
        if not key:
            last_error.append("немає ключа Gemini")
        if last_error:
            raise RuntimeError("Котик не намалювався. " + " | ".join(last_error)[:420])
        return None
    path = pathlib.Path(out_dir) / f"cat-{today.isoformat()}.jpg"
    path.write_bytes(img)
    caption = f"<b>Котик дня 🐱</b>\n{line}"
    return path, caption, origin
