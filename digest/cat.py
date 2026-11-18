"""Щовечірня рубрика «Котик дня» (22:00): нове миле й кумедне зображення кота.
Генерація мультяшного зображення моделлю Gemini зі зразками стилю (assets/cat). Безкоштовні запасні варіанти (Pollinations, фото) вимкнені: їхня якість нижча (назву моделі шукаємо серед доступних). Запасні варіанти allow_free / allow_photo за замовчуванням вимкнені. Підпис — коротка тепла фраза з готового списку (нічого не вигадується моделлю)."""
from __future__ import annotations

import base64
import json
import math
import os
import pathlib
import time
from datetime import date
from urllib.request import Request, urlopen

from . import llm

UA = {"User-Agent": "RadarBot/1.0 (https://github.com/prosytnist-source/radar-bot)"}
BUDGET = 150
last_error: list[str] = []

# Кіт-Радар — постійний персонаж: сучасний, впевнений, трохи нахабний «крутий» кіт, а не казковий. Амплуа за днем тижня (0 = понеділок).
CHARACTER = ("Kit-Radar: a modern, charismatic, slim-bodied ginger tabby cat (NOT fat, normal athletic body; only the cheeks are round and full) "
             "with a white muzzle and white chest, thick dark curved expressive eyebrows, a small pink nose, pink inner ears, long thin white whiskers, "
             "huge glossy eyes with large white sclera - either glancing sideways and up with a smug look, or closed in a blissful smile - "
             "a small content closed-mouth smile, a fluffy tail, relaxed human-like posture. "
             "Wears a dark charcoal knit hoodie, white t-shirt, blue jeans and white sneakers when the scene fits")
STYLE = ("Ultra-detailed 3D animated film still, premium Pixar-quality rendering, cinematic and modern. "
         "Low camera angle, close shot: the cat's face is large and fills at least 40 percent of the frame, head slightly tilted. "
         "Cinematic contrast lighting with a warm orange accent light and soft glowing rim light on the fur, shallow depth of field with creamy bokeh. "
         "Hyper-detailed individual fur strands and long visible whiskers. Square 1:1. "
         "Recurring brand details: a cream mug or object with a small black paw-print logo; in indoor scenes a dark navy wall with a gold-framed picture of a peace-sign hand, a shelf with books, a plant and a warm lamp. "
         "NOT a children's storybook, NOT a plush toy look, NOT a full-body centered frontal pose, NOT fat, no wide-open mouth. No text, no letters, no watermark.")
ROLES = {
    0: ("Кіт на роботі", [
        ("slouched at a desk in front of a laptop late in the evening, a steaming mug nearby, tired but proud smirk, city lights in the window behind", "Робочий день завершено. Я молодець."),
        ("peeking over a laptop screen during an online meeting, nervous smug half-smile, headphones around the neck, home office", "Мікрофон вимкнений? Так? Точно вимкнений?"),
        ("leaning back in an office chair with hands behind the head and feet up on the desk next to a stack of papers, confident boss pose, cozy lamp light", "Нарада закінчилась, але я ще офіційний."),
        ("holding a to-go coffee cup with both paws, sleepy half-closed eyes, messy fur, early Monday morning street with soft bokeh", "Понеділок — це коли кава працює за двох."),
    ]),
    1: ("Кіт-відпочивальник", [
        ("sprawled on a sofa under a blanket with a game controller, blissfully relaxed smirk, TV glow in the dark living room", "Вечір. Плед. Спокій."),
        ("lying in a hammock with sunglasses and a cold drink, total relaxation, palm tree and golden sunset behind", "Відпустка — стан душі. Тримаю його."),
        ("big headphones on, eyes closed, swaying to music, colorful abstract light streaks around, dark moody room", "Світ стишено. Музика — на повну."),
        ("relaxing in a hot bath with a face mask and a rubber duck, smug satisfied half-closed eyes, spa candles soft bokeh", "Сеанс відновлення. Не турбувати."),
    ]),
    2: ("Кіт-господар", [
        ("cooking at a modern kitchen counter with a pan, proud smug look at a slightly burnt pancake, apron over a hoodie, warm kitchen light", "Це не підгоріло. Це золота скоринка."),
        ("opening the door in a hoodie and holding a pizza box delivered, delighted greedy smirk, apartment hallway light", "Гості будуть. Піца — вже тут."),
        ("watering a green houseplant with a tiny can on a sunny windowsill, gentle caring half-smile, relaxed morning", "Квіти теж люблять увагу. Як і я."),
        ("wearing rubber gloves and a hoodie, wiping a kitchen table with a cloth, determined deadpan face, bright modern flat", "Прибирання — це коли знаходиш свої речі."),
    ]),
    3: ("Кіт-філософ", [
        ("chin on a paw, eyes rolled thoughtfully up to the side, deep in thought, dark background with warm rim light", "Хм. Це треба обміркувати."),
        ("reading a thick book in a leather armchair with round glasses, a mug of tea beside, library lamp light", "Мудрість приходить повільно, зате з печивом."),
        ("sitting on a windowsill in a hoodie looking at the night city and stars with a dreamy smirk, soft bokeh lights", "Іноді просто дивитися на зорі — теж робота."),
        ("walking through an autumn park in a coat and scarf, hands behind the back, calm philosophical smirk, golden leaves bokeh", "Осінь навчає відпускати. Листя вже навчилось."),
    ]),
    4: ("Кіт-тусовщик", [
        ("pointing at the camera with a huge cocky grin, party lights and confetti behind, sunglasses on the forehead, Friday night", "П'ятниця! Хвіст у ритмі."),
        ("dancing at a club in a bright jacket, disco lights and smoke, relaxed confident smirk, motion blur", "Я не танцюю. Я просто рухаюсь у ритмі."),
        ("holding a bouquet of flowers and a small gift, blushing a little but smug, warm evening street bokeh", "Мені? Дякую. Я зворушений."),
        ("laughing out loud while looking at a smartphone, tears of joy, lying on a sofa, phone light on the face", "Ще один мем — і справді спати."),
    ]),
    5: ("Кіт-мандрівник", [
        ("riding an electric scooter through a sunlit city street in a hoodie, wind in the whiskers, cocky smile, motion blur", "Іду по справах. Із вітерцем."),
        ("standing on a mountain viewpoint with a backpack and a phone, impressed raised eyebrow smirk, golden hour", "Дорога сама себе не пройде. Пішли."),
        ("carrying many shopping bags down a lit evening street, tired but smug, city lights bokeh", "Купив лише найнеобхідніше. (Не лише.)"),
        ("standing under a transparent umbrella in the rain, looking up with a mildly offended deadpan face, neon reflections", "Знову дощ? Я ж планував гуляти."),
    ]),
    6: ("Кіт-ледар", [
        ("waking up in a messy bed stretching and yawning, one eye half open, sunbeam through blinds, cozy morning", "Доброго ранку. Будь ласка, без швидких рішень."),
        ("hugging a big pillow in bed at night, dark circles under half-closed eyes, phone glow, sleepy smirk", "Ще одну серію — і спати. Так я собі казав годину тому."),
        ("wrapped in a thick knitted sweater holding hot chocolate by a snowy window, smug cozy half-smile", "Зима за вікном, тепло всередині."),
        ("standing on a bathroom scale looking down in exaggerated shock, one eyebrow raised, bright bathroom", "Це точно не мої цифри. Це зважування помилилось."),
    ]),
}


def theme_for(d: date) -> tuple[str, str, str]:
    """(амплуа, сцена англійською, підпис) за днем тижня; сцени в межах амплуа чергуються по тижнях."""
    role, scenes = ROLES[d.weekday()]
    scene, line = scenes[(d.toordinal() // 7) % len(scenes)]
    return role, scene, line


def _gen_models(key: str, call=llm._call) -> list[str]:
    """Імена моделей, що вміють малювати (за назвою «image»): повна якість першою, потім preview, lite — останньою."""
    names = []
    try:
        out = call(f"{llm.API}/models?pageSize=200", key, None, 30)
        for m in out.get("models", []):
            n = m["name"].removeprefix("models/")
            if "image" in n and "generateContent" in m.get("supportedGenerationMethods", []) and "imagen" not in n:
                names.append(n)
    except Exception:  # noqa: BLE001
        pass
    names.sort(key=lambda n: ("lite" in n, "preview" in n, n))
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
    for model in models[:3]:
        if time.monotonic() - t0 > BUDGET - 50:
            break
        parts = [{"text": f"{STYLE} Draw the SAME recurring character as in the attached reference images (they show one cat in different moods): copy its face EXACTLY - eyebrows, eyes, nose, cheeks, whiskers, ears, fur color, 3D rendering style, lighting quality. Character: {CHARACTER}. New scene: {prompt_en}."}]
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


def brand_mark(path) -> None:
    """Накласти знак «відбиток лапки + КІТ-РАДАР» у правий нижній кут (малюємо самі: текст від моделі ненадійний). Без Pillow — пропускаємо."""
    try:
        from PIL import Image, ImageDraw
        from .card import _font
    except Exception:  # noqa: BLE001
        return
    try:
        im = Image.open(path).convert("RGB")
    except Exception:  # noqa: BLE001
        return
    W, H = im.size
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    h = max(44, int(H * 0.058))
    f = _font(int(h * 0.50))
    text = "КІТ-РАДАР"
    tw = d.textlength(text, font=f)
    pad = int(h * 0.30)
    w = int(h * 0.95 + tw + pad * 2)
    x1, y1 = W - int(W * 0.03), H - int(H * 0.03)
    x0, y0 = x1 - w, y1 - h
    d.rounded_rectangle((x0, y0, x1, y1), radius=h // 2, fill=(247, 238, 220, 235))
    # як на кружці: чорна лапка на кремовій «таблетці»
    cx, cy, u = x0 + pad + h * 0.30, y0 + h * 0.60, h * 0.2
    black = (20, 20, 22, 255)
    d.ellipse((cx - 1.35 * u, cy - 0.7 * u, cx + 1.35 * u, cy + 1.25 * u), fill=black)
    for dx in (-1.1, 1.1):
        d.ellipse((cx + dx * u - 0.55 * u, cy + 0.35 * u, cx + dx * u + 0.55 * u, cy + 1.3 * u), fill=black)
    for dx, dy, rot in ((-1.75, -0.55, -35), (-0.65, -1.45, -12), (0.65, -1.45, 12), (1.75, -0.55, 35)):
        a_ = math.radians(rot); pts = []
        for k in range(24):
            t = 2 * math.pi * k / 24
            ex, ey = 0.42 * u * math.cos(t), 0.62 * u * math.sin(t)
            pts.append((cx + dx * u + ex * math.cos(a_) - ey * math.sin(a_), cy + dy * u + ex * math.sin(a_) + ey * math.cos(a_)))
        d.polygon(pts, fill=black)
    d.text((x0 + pad + h * 0.95, y0 + (h - h * 0.50) / 2 - h * 0.04), text, font=f, fill=(25, 25, 28, 255))
    Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB").save(path, "JPEG", quality=92)


def build(today: date, key: str | None, out_dir="/tmp", call=llm._call, get=_get, allow_photo: bool = False, allow_free: bool = False):
    """→ (шлях, підпис, походження) або None."""
    role, prompt, line = theme_for(today)
    custom = os.environ.get("CAT_SCENE", "").strip()
    if custom:  # ручна проба зі сценою від користувача (будь-якою мовою)
        role, prompt, line = "Кіт-Радар", custom, "Кіт-Радар на зв'язку."
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
    brand_mark(path)
    caption = f"<b>Кіт-Радар 🐱</b> · {role}\n{line}"
    return path, caption, origin
