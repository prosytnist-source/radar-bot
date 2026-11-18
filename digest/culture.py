"""Рубрика «Культурні діячі» (14:00): лаконічний допис про діяча української культури.
Джерело — українська Вікіпедія (категорії: письменники, поети, художники, композитори, режисери, актори тощо). Вибір випадковий, але без повторів
(state/culture.json пам'ятає всіх, про кого вже писали). Текст — лише з вступу статті, з перевіркою цифр і назв (як у «Постатей»), інакше дослівний уривок.
Цитата — ТІЛЬКИ дослівна зі сторінки діяча в Вікіцитатах (uk.wikiquote.org); немає — допис виходить без цитати. Нічого не вигадується."""
from __future__ import annotations

import html
import json
import random
import re
import time
from datetime import date
from urllib.parse import quote

from . import llm
from .chronicle import clean, first_sentences, get_json, grounded, summary

CATS = ["Українські письменники", "Українські поети", "Українські поетеси", "Українські художники", "Українські композитори",
        "Українські кінорежисери", "Українські актори", "Українські скульптори", "Українські драматурги", "Українські співаки",
        "Українські художниці", "Українські письменниці", "Українські архітектори", "Українські кінооператори", "Українські диригенти"]
CAT_API = "https://uk.wikipedia.org/w/api.php?action=query&list=categorymembers&cmtitle={t}&cmlimit=500&cmtype=page|subcat&format=json&formatversion=2"
QUOTE_API = "https://uk.wikiquote.org/w/api.php?action=parse&page={p}&prop=wikitext&format=json&formatversion=2&redirects=1"
BUDGET = 150
last_error: list[str] = []
BAD_TITLE = re.compile(r"^(Список|Категорія|Портал|Шаблон|Вікіпедія|Файл|Українські |Українка|Українець)|:")


def _members(cat: str, fetch) -> tuple[list[str], list[str]]:
    try:
        d = fetch(CAT_API.format(t=quote("Категорія:" + cat.replace(" ", "_"), safe=":")))
    except Exception as exc:  # noqa: BLE001
        last_error.append(f"{cat}: {str(exc)[:60]}")
        return [], []
    pages, subs = [], []
    for m in d.get("query", {}).get("categorymembers", []):
        t = m.get("title", "")
        if t.startswith("Категорія:"):
            subs.append(t.removeprefix("Категорія:"))
        elif not BAD_TITLE.search(t):
            pages.append(t)
    return pages, subs


def pool(rng: random.Random, fetch, tries: int = 6) -> list[str]:
    """Кілька випадкових кандидатів (імен сторінок) з категорій і їхніх підкатегорій."""
    out: list[str] = []
    cats = CATS[:]
    rng.shuffle(cats)
    for cat in cats[:tries]:
        pages, subs = _members(cat, fetch)
        if subs and (not pages or rng.random() < 0.7):
            pages2, _ = _members(rng.choice(subs), fetch)
            pages = pages2 or pages
        out += rng.sample(pages, min(8, len(pages)))
    rng.shuffle(out)
    return out


def quote_for(name: str, fetch=get_json) -> str:
    """Дослівна цитата зі сторінки Вікіцитат або ''. Беремо лише прості рядки-цитати без посилань і дрібного шрифту."""
    try:
        wt = fetch(QUOTE_API.format(p=quote(name.replace(" ", "_"), safe=""))).get("parse", {}).get("wikitext", "")
    except Exception:  # noqa: BLE001
        return ""
    cands = []
    for ln in wt.splitlines():
        if re.match(r"^\*(?!\*)\s*\S", ln):
            q = clean(re.sub(r"^\*\s*", "", ln))
            q = q.strip("«»\"“” ")
            if 40 <= len(q) <= 220 and not re.search(r"https?:|\bISBN\b|\bс\.\s*\d|^\d{4}", q):
                cands.append(q)
    if not cands:
        return ""
    return random.Random(name).choice(cands)


SYSTEM = (
    "Ти редактор рубрики українського каналу про культуру. Пиши українською, тепло й зрозуміло, без пафосу й оцінок. "
    "ВИКОРИСТОВУЙ ЛИШЕ факти з блоку ДЖЕРЕЛО. Не додавай жодних дат, цифр, імен, творів і подробиць, яких там немає. "
    "Поверни JSON: {\"text\": \"...\"}. text — 3–4 короткі речення, до 520 символів: хто це, чим відомий(а), що варто знати. Без заголовка й без згадки джерела."
)


def write(src: dict, key: str | None, call=llm.generate_json, deadline: float = 0.0) -> str:
    extract = (src.get("extract") or "").replace("́", "")
    fallback = first_sentences(extract, 520)
    if not key:
        return fallback
    for mdl in (llm.DEFAULT_MODEL, llm.FALLBACK_MODEL):
        if time.monotonic() > deadline - 40:
            break
        try:
            text = str(json.loads(call(SYSTEM, f"ДЖЕРЕЛО:\n{extract[:2200]}", mdl, key, retries=1, timeout=35)).get("text", "")).strip()
        except Exception:  # noqa: BLE001
            continue
        if 80 <= len(text) <= 640 and grounded(text, extract):
            return text
    return fallback


def build(today: date, used: list[str], fetch=get_json, key: str | None = None, call=llm.generate_json):
    """→ {title, subtitle, chips, caption, key} або None. Помилка мережі — виняток із діагностикою."""
    t0 = time.monotonic()
    last_error.clear()
    rng = random.Random(today.toordinal() * 7919)
    seen = set(used)
    for name in pool(rng, fetch):
        if time.monotonic() - t0 > BUDGET - 60:
            break
        if name in seen:
            continue
        s = summary(name, fetch)
        ext = s.get("extract", "")
        if len(ext) < 200 or not re.search(r"україн|Україн", ext + " " + s.get("description", "")):
            continue
        title = clean(s.get("title") or name)[:60]
        life = re.search(r"\(([^()]*?\d{3,4}[^()]*?)\)", ext[:200])
        text = write(s, key, call, t0 + BUDGET)
        q = quote_for(name, fetch)
        cap = f"<b>{html.escape(title, quote=False)}</b>\n"
        if life:
            cap += f"<i>{html.escape(life.group(1).strip(), quote=False)}</i>\n"
        cap += f"\n{html.escape(text, quote=False)}\n"
        if q:
            cap += f"\n«{html.escape(q, quote=False)}»\n"
        cap += "\n<i>Джерело: Вікіпедія" + (", Вікіцитати" if q else "") + ".</i>"
        return {"title": title, "subtitle": life.group(1).strip() if life else "", "chips": ["Культурні діячі"], "caption": cap, "key": name}
    raise RuntimeError("не знайшов діяча для допису. " + " | ".join(last_error)[:300])
