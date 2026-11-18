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
         "Hyper-detailed individual fur strands and long visible whiskers. Aspect ratio as requested (default square 1:1). "
         "Recurring brand details: a cream mug or object with a small black paw-print logo; in indoor scenes a dark navy wall with a gold-framed picture of a peace-sign hand, a shelf with books, a plant and a warm lamp. "
         "NOT a children's storybook, NOT a plush toy look, NOT a full-body centered frontal pose, NOT fat, no wide-open mouth. No text, no letters, no watermark.")
FRAMING = ("MANDATORY FRAMING (highest priority, overrides the scene wording): EXTREME CLOSE-UP hero shot, camera a meter from the cat, wide-angle lens, low angle. "
           "The cat's head and upper body fill about 75 percent of the frame; paws, tail, legs and props may be cropped by the frame edges - that is good. "
           "Large objects from the scene (a parachute canopy, buildings, mountains) are only partly visible, cropped or far behind as a backdrop. "
           "NEVER a distant, aerial or wide shot, NEVER a small cat with lots of empty background. "
           "Dynamic alive pose, never stiff or hanging like a doll; wind or motion in the fur and whiskers; "
           "a vivid facial emotion (blissful closed-eye grin or a smug sideways glance). "
           "Realistic real-world objects and gear (a real paraglider with proper lines, real skateboard, real food) - never toy-like. "
           "Rich tactile detail: individual fur strands, fabric texture of the hoodie and jeans. Sharp detailed background with natural saturated colors and strong contrast, no milky haze.")
ROLES = {
    0: ("Кіт на роботі", [
        ("slouched at a desk in front of a laptop late in the evening, a steaming mug nearby, tired but proud smirk, city lights in the window behind", "Робочий день завершено. Я молодець."),
        ("peeking over a laptop screen during an online meeting, nervous smug half-smile, headphones around the neck, home office", "Мікрофон вимкнений? Так? Точно вимкнений?"),
        ("leaning back in an office chair with hands behind the head and feet up on the desk next to a stack of papers, confident boss pose, cozy lamp light", "Нарада закінчилась, але я ще офіційний."),
        ("holding a to-go coffee cup with both paws, sleepy half-closed eyes, messy fur, early Monday morning street with soft bokeh", "День минув на каві. Вечір — на чаї."),
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
        ("watering a green houseplant with a tiny can on a sunny windowsill, gentle caring half-smile, relaxed morning", "Квіти полив. Тепер можна й мені увагу."),
        ("wearing rubber gloves and a hoodie, wiping a kitchen table with a cloth, determined deadpan face, bright modern flat", "Прибирання — це коли знаходиш свої речі."),
    ]),
    3: ("Кіт-філософ", [
        ("chin on a paw, eyes rolled thoughtfully up to the side, deep in thought, dark background with warm rim light", "Хм. Це треба обміркувати."),
        ("reading a thick book in a leather armchair with round glasses, a mug of tea beside, library lamp light", "Мудрість приходить повільно, зате з печивом."),
        ("sitting on a windowsill in a hoodie looking at the night city and stars with a dreamy smirk, soft bokeh lights", "Іноді просто дивитися на зорі — теж робота."),
        ("walking through an autumn park in a coat and scarf, hands behind the back, calm philosophical smirk, golden leaves bokeh", "Вечір навчає відпускати день. Листя вже навчилось."),
    ]),
    4: ("Кіт-тусовщик", [
        ("pointing at the camera with a huge cocky grin, party lights and confetti behind, sunglasses on the forehead, Friday night", "Вечір починається тоді, коли я кажу."),
        ("dancing at a club in a bright jacket, disco lights and smoke, relaxed confident smirk, motion blur", "Я не танцюю. Я просто рухаюсь у ритмі."),
        ("holding a bouquet of flowers and a small gift, blushing a little but smug, warm evening street bokeh", "Мені? Дякую. Я зворушений."),
        ("laughing out loud while looking at a smartphone, tears of joy, lying on a sofa, phone light on the face", "Ще один мем — і справді спати."),
    ]),
    5: ("Кіт-мандрівник", [
        ("riding an electric scooter through a sunlit city street in a hoodie, wind in the whiskers, cocky smile, motion blur", "Вечірня прогулянка — найкращий спосіб закрити день."),
        ("standing on a mountain viewpoint with a backpack and a phone, impressed raised eyebrow smirk, golden hour", "Дорога сама себе не пройде. Пішли."),
        ("carrying many shopping bags down a lit evening street, tired but smug, city lights bokeh", "Купив лише найнеобхідніше. (Не лише.)"),
        ("standing under a transparent umbrella in the rain, looking up with a mildly offended deadpan face, neon reflections", "Знову дощ? Я ж планував гуляти."),
    ]),
    6: ("Кіт-ледар", [
        ("waking up in a messy bed stretching and yawning, one eye half open, sunbeam through blinds, cozy morning", "Лягаю з думкою про ранок. Будильнику — не вірю."),
        ("hugging a big pillow in bed at night, dark circles under half-closed eyes, phone glow, sleepy smirk", "Ще одну серію — і спати. Так я собі казав годину тому."),
        ("wrapped in a thick knitted sweater holding hot chocolate by a snowy window, smug cozy half-smile", "Зима за вікном, тепло всередині."),
        ("standing on a bathroom scale looking down in exaggerated shock, one eyebrow raised, bright bathroom", "Це точно не мої цифри. Це зважування помилилось."),
    ]),
}


EXTRA = [
    ("Кіт-спортсмен", "a lively gym scene: lifting a dumbbell with a proud smug grin, towel around the neck, gym lights", "Сьогодні — день ніг. Завтра вранці буде «чому все болить»."),
    ("Кіт-спортсмен", "jogging in a park at sunrise in a sports hoodie and headphones, breathing out a cloud of steam, golden light", "Пробіжка в планах на завтра. Вечірня версія мене проти."),
    ("Кіт-спортсмен", "doing yoga on a mat by a big window, eyes closed in a calm smile, one leg raised, soft morning light", "Вечірня розтяжка — і день нарешті відпускає."),
    ("Кіт-відрядження", "pulling a cabin suitcase through a busy airport terminal with a travel pillow around the neck, sleepy smug smile, departure board bokeh", "Відрядження завтра. Валіза готова, настрій — майже."),
    ("Кіт-відрядження", "looking out the window of a fast train at passing landscapes with a coffee cup, dreamy content smile, golden hour", "Дорога — це теж робота. Принаймні так я скажу бухгалтеру."),
    ("Кіт-відрядження", "checking into a hotel room, bouncing on a huge white bed with arms spread, delighted closed-eye grin", "Готель. Тиша. Подушок забагато — саме те."),
    ("Кіт-гігієна", "brushing teeth in front of a bathroom mirror in a hoodie, foamy toothpaste, sleepy half-open eyes, morning light", "Зуби почищено. Можна офіційно йти в сон."),
    ("Кіт-гігієна", "washing his face at a sink with water splashes flying, eyes squeezed shut, towel on the shoulder, bright bathroom", "Умився — і день вважається закритим."),
    ("Кіт-сніданок", "making toast and eggs at a kitchen counter, humming happily, steam rising from a pan, cozy morning light", "Завтра зроблю сніданок. А сьогодні мрію про нього."),
    ("Кіт-сніданок", "sitting at a breakfast table with croissants and a big cup of coffee, eyes closed inhaling the aroma, blissful smile", "Круасани — на завтра. Мрії — на сьогодні."),
    ("Кіт-новини", "reading the news on a tablet with a coffee mug, one eyebrow raised in mild surprise, cozy armchair, warm lamp", "Новини за день прочитав. Чай допомагає перетравити."),
    ("Кіт-новини", "holding a newspaper wide open and peeking over it with a knowing smirk, round glasses, morning kitchen light", "Заголовки за день прочитав. Висновки роблю сам."),
    ("Кіт-хобі", "playing an acoustic guitar on a sofa with closed eyes and a dreamy smile, warm lamp light, wooden shelves", "Три акорди — і я вже рок-зірка."),
    ("Кіт-хобі", "painting on a small canvas at an easel with a brush in the mouth corner, paint on the cheek, bright studio", "Мистецтво вимагає жертв. Особливо худі."),
    ("Кіт-хобі", "taking a photo with a vintage camera at a street, one eye squinting, golden hour city bokeh", "Кадр дня. І ще дев'ятнадцять про запас на добраніч."),
    ("Кіт-офіс", "sitting in a modern open-space office, stacked with sticky notes on the monitor, deadpan stressed grin, fluorescent bokeh", "Дедлайн — це коли час нарешті стає цікавим."),
    ("Кіт-офіс", "high-fiving a colleague's paw in a bright office after a successful meeting, huge proud grin", "Домовились! Навіть без «можна на пошту»."),
]


def _pool() -> list[tuple[str, str, str]]:
    return [(r, sc, ln) for r, scs in ROLES.values() for sc, ln in scs] + EXTRA


def theme_for(d: date) -> tuple[str, str, str]:
    """(амплуа, сцена англійською, підпис): випадкова, але без повторів у межах кола — день за днем проходимо весь список у перемішаному порядку (порядок залежить від номера кола)."""
    import random
    pool = _pool()
    n = d.toordinal()
    order = list(range(len(pool)))
    random.Random(n // len(pool)).shuffle(order)
    return pool[order[n % len(pool)]]


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


def generate(prompt_en: str, key: str, call=llm._call, aspect: str = "1:1") -> bytes | None:
    """Картинка від моделі або None."""
    t0 = time.monotonic()
    models = _gen_models(key, call)
    last_error.append(f"моделі для малювання: {models[:3]}")
    for model in models[:3]:
        if time.monotonic() - t0 > BUDGET - 50:
            break
        parts = [{"text": f"{STYLE} Draw the SAME recurring character as in the attached reference images (they show one cat in different moods): copy its face EXACTLY - eyebrows, eyes, nose, cheeks, whiskers, ears, fur color, 3D rendering style, lighting quality. Character: {CHARACTER}. New scene: {prompt_en}. {FRAMING}"}]
        for ref in _refs():
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": ref}})
        try:
            out = None
            for cfg in ({"responseModalities": ["IMAGE", "TEXT"], "imageConfig": {"aspectRatio": aspect, "imageSize": "2K"}},
                        {"responseModalities": ["IMAGE", "TEXT"]}):  # 2K підтримують не всі моделі — тоді звичайний розмір
                payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
                try:
                    out = call(f"{llm.API}/models/{model}:generateContent", key, payload, 90)
                    break
                except Exception as exc:  # noqa: BLE001
                    if "400" in str(exc) and "imageConfig" in cfg:
                        last_error.append(f"{model}: 2K не підтримано")
                        continue
                    raise
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


def upscale(path, target: int = 2048) -> None:
    """Якщо картинка менша за 2048 px — збільшуємо (LANCZOS) з легким підвищенням різкості. Без Pillow — пропуск."""
    try:
        from PIL import Image, ImageFilter
        im = Image.open(path).convert("RGB")
    except Exception:  # noqa: BLE001
        return
    if im.width >= target:
        return
    k = target / im.width
    im = im.resize((target, int(im.height * k)), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))
    im.save(path, "JPEG", quality=92)


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
    if custom.lower() in ("random", "рандом", "випадкова"):  # випадкова сцена з усього списку
        import random
        role, prompt, line = random.choice(_pool())
        custom = ""
    if custom:  # ручна проба зі сценою від користувача (будь-якою мовою)
        role, prompt, line = "Кіт-Радар", custom, "На зв'язку."
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
    upscale(path)
    brand_mark(path)
    caption = f"<b>Радар 🐱</b>\n{line}"
    return path, caption, origin


# ---------- постійні банери рубрик (генеруються раз, потім використовуються щодня) ----------
BANNERS = {
    "holiday": ("Свято", "wide 16:9 composition, cat on the left two thirds: cheerful and festive, raising a mug in a toast, confetti in the air, warm string lights, a blank wall calendar page with a red circle behind"),
    "rates": ("Курс валют", "wide 16:9 composition: cat at a desk counting a neat fan of banknotes and a stack of gold coins, a laptop behind with abstract green and red rising-falling charts without any numbers, smug analytical sideways glance, round reading glasses"),
    "fuel": ("Пальне", "wide 16:9 composition: cat in a hoodie holding a fuel nozzle at a modern gas station at blue dusk, a sleek car behind, a glowing blurred price sign in the distance, raised eyebrow, skeptical smug glance"),
    "figure": ("Визначні постаті", "wide 16:9 composition: cat in a dark blazer over a white shirt standing proudly beside a classic marble bust on a pedestal, holding an open old book, dignified proud smile, warm library with shelves and a brass lamp"),
    "culture": ("Культурні діячі", "wide 16:9 composition: cat in a black turtleneck and a scarf in a warm theater foyer, holding an old poetry book and a theater program, framed portraits and golden theater lights behind, refined proud smug sideways glance"),
    "ask": ("Питання дня", "wide 16:9 composition: cat as a friendly street pollster in a hoodie, holding a retro microphone in one paw and a tablet in the other, leaning toward the viewer with a curious raised eyebrow, warm blurred city street with soft lights behind, bright inviting mood"),
    "expert": ("Експертна думка", "wide 16:9 composition: cat expert in a dark blazer and round glasses sitting in a leather armchair in a warm TV-studio set with bookshelves and a lamp, one paw raised thoughtfully, calm authoritative smug glance, warm contrast lighting"),
    "fact": ("Історичний факт", "wide 16:9 composition: cat with a magnifying glass studying an old unrolled map and parchment scrolls on a wooden table, an hourglass and a candle, curious thoughtful sideways glance, warm candlelight"),
}


def build_banners(key: str, out_dir, only: str | None = None, call=llm._call):
    """Згенерувати банери (усі або один за ключем). → список (ключ, назва, шлях); невдалі пропускаються з записом у last_error."""
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    done = []
    last_error.clear()
    for k, (label, scene) in BANNERS.items():
        if only and k != only:
            continue
        img = generate(scene, key, call, aspect="16:9")
        if img is None:
            continue
        path = out / f"{k}.jpg"
        path.write_bytes(img)
        upscale(path)
        brand_mark(path)
        done.append((k, label, path))
    return done
