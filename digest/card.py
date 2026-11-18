"""Власні картки каналу в стилі РАДАР (1280×720): темне тло з колами радара, назва RADAЯ, великий заголовок.
Потрібні лише коли в посту немає власного фото. Бібліотека Pillow необов'язкова: без неї картка просто не створюється (пост іде без неї)."""
from __future__ import annotations

import math
import pathlib

W, H = 1280, 720
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
ACCENT = {"news": (232, 142, 42), "poll": (74, 158, 255), "top": (122, 201, 134), "evening": (176, 124, 255), "figure": (240, 196, 72), "history": (64, 190, 175)}


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _font(size: int):
    from PIL import ImageFont
    for p in FONTS:
        if pathlib.Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return lines


def render(title: str, out: str | pathlib.Path, subtitle: str = "", chips: list[str] | None = None, kind: str = "news", glyph: str = "radar") -> pathlib.Path:
    from PIL import Image, ImageDraw
    acc = ACCENT.get(kind, ACCENT["news"])
    img = Image.new("RGB", (W, H), (8, 8, 10))
    px = img.load()
    cx, cy = 330, 360  # світіння за значком зліва
    for y in range(H):
        for x in range(0, W, 2):
            d = math.hypot(x - cx, y - cy) / 700
            k = max(0.0, 1 - d) ** 2.2
            c = (int(8 + acc[0] * 0.30 * k), int(8 + acc[1] * 0.30 * k), int(10 + acc[2] * 0.30 * k))
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
    d = ImageDraw.Draw(img, "RGBA")
    for r in range(90, 1200, 110):  # кола радара
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 22), width=2)
    d.line((cx, 0, cx, H), fill=(255, 255, 255, 14), width=2)
    d.line((0, cy, W, cy), fill=(255, 255, 255, 14), width=2)
    # значок: заокруглений квадрат з «радаром»
    box = (130, 160, 530, 560)
    d.rounded_rectangle(box, radius=70, fill=acc + (255,))
    d.rounded_rectangle((box[0], box[1], box[2], box[1] + 150), radius=70, fill=(255, 255, 255, 38))
    mx, my = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    if glyph == "person":  # силует: голова й плечі
        d.ellipse((mx - 62, my - 130, mx + 62, my - 6), fill=(255, 255, 255, 255))
        d.pieslice((mx - 135, my + 14, mx + 135, my + 284), 180, 360, fill=(255, 255, 255, 255))
    elif glyph == "clock":  # годинник: час, що минув
        d.ellipse((mx - 150, my - 150, mx + 150, my + 150), outline=(255, 255, 255, 255), width=14)
        d.line((mx, my, mx, my - 100), fill=(255, 255, 255, 255), width=14)
        d.line((mx, my, mx + 72, my + 42), fill=(255, 255, 255, 255), width=14)
        d.ellipse((mx - 16, my - 16, mx + 16, my + 16), fill=(255, 255, 255, 255))
    else:
        for r in (150, 100, 50):
            d.ellipse((mx - r, my - r, mx + r, my + r), outline=(255, 255, 255, 255), width=12)
        d.pieslice((mx - 150, my - 150, mx + 150, my + 150), -60, -20, fill=(255, 255, 255, 120))
        d.ellipse((mx - 14, my - 14, mx + 14, my + 14), fill=(255, 255, 255, 255))
    # праворуч: RADAЯ, лінія, заголовок
    x0, x1 = 660, 1230
    d.text((x0, 82), "RADAЯ", font=_font(46), fill=(255, 255, 255, 255))
    d.line((x0, 170, x1, 170), fill=(255, 255, 255, 235), width=2)
    title = title.upper()
    for size in (64, 56, 50, 44, 38, 34):
        f = _font(size)
        lines = wrap(d, title, f, x1 - x0, 6)
        if not lines[-1].endswith("…") and len(lines) * size * 1.22 <= 330 and all(d.textlength(l, font=f) <= x1 - x0 for l in lines):
            break
    y = 215
    for ln in lines:
        d.text((x0, y), ln, font=f, fill=(255, 255, 255, 255))
        y += int(size * 1.22)
    if subtitle:
        fs = _font(26)
        y += 22
        for ln in wrap(d, subtitle.upper(), fs, x1 - x0, 2):
            d.text((x0, y), ln, font=fs, fill=(255, 255, 255, 215))
            y += 36
    if chips:
        fc = _font(22)
        d.text((x0, 640), " · ".join(chips[:6]).upper(), font=fc, fill=acc + (255,))
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90)
    return out
