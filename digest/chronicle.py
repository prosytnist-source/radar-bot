"""Дві щоденні рубрики з перевіреним змістом: «Визначні постаті» (12:00) і «Історичний факт» (17:00).
Джерело: українська Вікіпедія (сторінка дня, напр. «18 листопада») + стислий опис статті. Нічого не вигадується:
текст пишеться ЛИШЕ з джерела, а кожну цифру й власну назву в ньому програма перевіряє; не пройшов перевірку — беремо
дослівний уривок із Вікіпедії (з вказівкою джерела). Немає даних — нічого не публікуємо, власнику надходить повідомлення."""
from __future__ import annotations

import html
import json
import re
import time
from datetime import date
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import llm

UA = {"User-Agent": "RadarBot/1.0 (https://github.com/prosytnist-source/radar-bot)"}
DAY_API = "https://uk.wikipedia.org/w/api.php?action=parse&page={page}&prop=wikitext&format=json&formatversion=2&redirects=1"
SUMMARY_API = "https://uk.wikipedia.org/api/rest_v1/page/summary/{title}?redirect=true"
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
SECTIONS = {"event": ("події",), "birth": ("народились", "народилися"), "death": ("померли", "пам'ятні дати", "пам’ятні дати")}

PERSON_UA = re.compile(r"україн|Україн|українськ", re.I)
NOT_UA = re.compile(r"російськ|радянськ(?!.*україн)|білоруськ", re.I)
EVENT_UA = re.compile(
    r"Україн|україн|Київ|Київськ|Львів|Харків|Одес|Дніпр|Запоріж|Чернігів|Полтав|Крим|Галичин|Буковин|Закарпат|Волин|Донецьк|Луганськ|Херсон|Миколаїв|"
    r"Миколаїв|Чорнобил|УНР|ЗУНР|УПА|ОУН|Гетьман|гетьман|козац|Козац|Січ|Хмельницьк|Мазеп|Голодомор|Верховн\w+ Рад|Майдан|Русь|Руськ|Київськ\w+ Русь"
)
DECEASED = re.compile(r"\(\s*[^()]*?\d{4}[^()]*?[–—-]\s*[^()]*?\d{4}[^()]*?\)")


BUDGET = 150  # секунд на весь пошук і писання; далі — дослівний уривок без моделі
_deadline = [0.0]


def get_json(url: str, timeout: int = 20) -> dict:
    with urlopen(Request(url, headers=UA), timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------- сторінка дня ----------
def day_page(d: date) -> str:
    return f"{d.day}_{MONTHS[d.month - 1]}"


def clean(s: str) -> str:
    s = re.sub(r"<ref[^>/]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    for _ in range(4):
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:Файл|File|Категорія|Category)[^\]]*\]\]", "", s)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(" ".join(s.split())).strip(" ,;")


LINE = re.compile(r"^(?:\[\[)?(\d{1,4})(?:\]\])?\s*(?:р\.|року|рік|р)?\s*[—–:\-]+\s*(.+)$")


def _line(ln: str):
    """'* ...' → (рік, решта) або None. Терпимий до жирного/курсиву, &nbsp;, шаблонів, різних тире."""
    ln = ln.strip()
    if not ln.startswith("*"):
        return None
    ln = re.sub(r"^\*+\s*", "", ln)
    ln = ln.replace("&nbsp;", " ").replace(" ", " ").replace("'" * 3, "").replace("'" * 2, "")
    ln = re.sub(r"^\{\{\s*(\d{1,4})[^{}]*\}\}", r"\1", ln)
    m = LINE.match(ln.strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def parse_day(wikitext: str) -> list[dict]:
    """Рядки розділів «Події», «Народились», «Померли» → [{kind, year, text, link}] (link — перше посилання після року)."""
    out, kind = [], None
    for ln in wikitext.splitlines():
        h = re.match(r"^(=+)\s*(.+?)\s*\1\s*$", ln)
        if h:
            title = clean(h.group(2)).lower()
            found = next((k for k, names in SECTIONS.items() if any(title.startswith(n) for n in names)), None)
            if found:
                kind = found
            elif len(h.group(1)) <= 2:
                kind = None  # новий розділ верхнього рівня; підрозділи («XX століття») лишаються в поточному
            continue
        if not kind:
            continue
        m = _line(ln)
        if not m:
            continue
        year, rest = m
        link = None
        lm = re.search(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", rest)
        if lm:
            link = lm.group(1).strip()
        text = clean(rest)
        if len(text) >= 12:
            out.append({"kind": kind, "year": year, "text": text, "link": link})
    return out


def anniversary_score(n: int) -> int:
    if n <= 0:
        return 0
    return (5 if n % 100 == 0 else 4 if n % 50 == 0 else 3 if n % 25 == 0 else 2 if n % 10 == 0 else 1 if n % 5 == 0 else 0)


def candidates(items: list[dict], kind: str, today: date) -> list[dict]:
    """kind='figure' — народження й дні пам'яті українців; kind='fact' — події, пов'язані з Україною."""
    res = []
    for it in items:
        if kind == "figure":
            if it["kind"] not in ("birth", "death") or not PERSON_UA.search(it["text"]) or NOT_UA.search(it["text"]):
                continue
        else:
            if it["kind"] != "event" or not EVENT_UA.search(it["text"]) or it["year"] > today.year:
                continue
        n = today.year - it["year"]
        res.append({**it, "n": n, "score": anniversary_score(n)})
    return res


def pick(cands: list[dict], used: set[str], today: date) -> list[dict]:
    """Відсортувати: ще не було, круглі річниці першими, далі стабільно за датою. Повертає впорядкований список."""
    def key(c):
        k = (c["link"] or c["text"][:40]).lower()
        return (k in used, -c["score"], hash_stable(f"{today.isoformat()}{k}"))
    return sorted(cands, key=key)


def hash_stable(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 131 + ord(ch)) % 1_000_003
    return h


# ---------- опис статті ----------
def summary(title: str, fetch=get_json) -> dict:
    try:
        d = fetch(SUMMARY_API.format(title=quote(title.replace(" ", "_"), safe="")))
    except Exception:  # noqa: BLE001
        return {}
    return {"title": d.get("title") or title, "extract": (d.get("extract") or "").strip(), "description": d.get("description") or ""}


def first_sentences(text: str, limit: int) -> str:
    sents = re.split(r"(?<=[.!?…])\s+(?=[А-ЯІЇЄҐA-Z«\"])", text.strip())
    out = ""
    for s in sents:
        if len(out) + len(s) + 1 > limit and out:
            break
        out = (out + " " + s).strip()
    return out[:limit].rstrip()


# ---------- перевірка тексту ----------
def grounded(text: str, source: str, n: int | None = None) -> bool:
    src = source.lower().replace("’", "'").replace("ʼ", "'")
    t = text.replace("’", "'").replace("ʼ", "'")
    for num in re.findall(r"\d+", t):
        if num not in source and not (n is not None and num == str(n)):
            return False
    for m in re.finditer(r"(?<=[а-яіїєґ,;:—–«(] )([А-ЯІЇЄҐ][а-яіїєґ'\-]{3,})", t):
        if m.group(1)[:5].lower() not in src:
            return False
    return True


SYSTEM = (
    "Ти редактор рубрики українського новинного каналу. Пиши українською, спокійно й по-людськи, без пафосу, без вигуків і без оцінок. "
    "ВИКОРИСТОВУЙ ЛИШЕ факти з блоку ДЖЕРЕЛО. Не додавай жодних дат, цифр, імен, місць і подробиць, яких там немає. "
    "Не вигадуй цитат. Поверни JSON: {\"title\": \"...\", \"text\": \"...\"}. title до 48 символів; text 3–4 речення, до 520 символів, "
    "без заголовка й без згадки джерела."
)


def write(cand: dict, kind: str, src: dict, key: str | None, model: str | None = None, call=llm.generate_json) -> tuple[str, str]:
    """(title, text): через модель із перевіркою, інакше — дослівний уривок із Вікіпедії."""
    source = (cand["text"] + "\n" + src.get("extract", "")).strip()
    fallback_title = clean(src.get("title") or cand.get("link") or "")[:60] or ("Визначна постать" if kind == "figure" else "Подія дня")
    if kind == "figure":
        fb_text = first_sentences(src.get("extract") or cand["text"], 420)
    else:
        fb_text = first_sentences(f"{cand['year']} року: {cand['text']}. {src.get('extract', '')}".replace("..", "."), 460)
    if not key:
        return fallback_title, fb_text
    what = {"birth": "постать; сьогодні її день народження (вона народилася цього дня)", "death": "постать; сьогодні день її пам'яті (вона померла цього дня)"}.get(cand["kind"], "історична подія")
    prompt = f"Тема: {what}. Річниця: {cand['n']} років тому ({cand['year']} рік). Не пиши «народився або» чи подібних вагань.\n\nДЖЕРЕЛО:\n{source[:2200]}"
    for mdl in (model or llm.DEFAULT_MODEL, llm.FALLBACK_MODEL):
        if time.monotonic() > _deadline[0] - 40:
            break  # бракує часу — беремо дослівний уривок
        try:
            out = json.loads(call(SYSTEM, prompt, mdl, key, retries=1, timeout=35))
            title, text = str(out.get("title", "")).strip(), str(out.get("text", "")).strip()
        except Exception as exc:  # noqa: BLE001
            if llm.is_busy(exc):
                continue
            continue
        if kind == "figure":
            title = fallback_title  # заголовок — точне ім'я зі статті
        if 80 <= len(text) <= 640 and title and len(title) <= 60 and grounded(text, source, cand["n"]) and grounded(title, source, cand["n"]):
            return title, text
    return fallback_title, fb_text


def occasion(cand: dict, today: date) -> str:
    n = cand["n"]
    yrs = f"{n} " + ("рік" if n % 10 == 1 and n % 100 != 11 else "роки" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "років")
    if cand["kind"] == "birth":
        return f"Сьогодні день народження ({yrs} тому)"
    if cand["kind"] == "death":
        return f"День пам'яті ({yrs} від дня смерті)"
    return f"{today.day} {MONTHS[today.month - 1]} {cand['year']} року · {yrs} тому"


def build(kind: str, today: date, used: list[str], fetch=get_json, key: str | None = None, call=llm.generate_json, model: str | None = None):
    """→ {title, subtitle, chips, caption, key} або None, якщо підходящого запису немає. Помилка мережі — виняток (власник дізнається)."""
    _deadline[0] = time.monotonic() + BUDGET
    raw = fetch(DAY_API.format(page=quote(day_page(today))))
    wt = (raw.get("parse") or {}).get("wikitext") or ""
    if not wt:
        raise RuntimeError("Вікіпедія не віддала сторінку дня")
    items = parse_day(wt)
    if not items:
        lines = wt.splitlines()
        heads = re.findall(r"^=+\s*(.+?)\s*=+\s*$", wt, flags=re.M)[:10]
        i = next((n for n, l in enumerate(lines) if re.match(r"^=+\s*Події", l)), 0)
        sample = [l[:80] for l in lines[i + 1:i + 8] if l.strip()][:4]
        raise RuntimeError(f"не вдалося розібрати сторінку дня; розділи: {heads}; після «Події»: {sample}")
    cands = pick(candidates(items, kind, today), set(used), today)
    for cand in cands[:8]:
        if time.monotonic() > _deadline[0]:
            break
        src = summary(cand["link"], fetch) if cand.get("link") else {}
        if kind == "figure" and cand["kind"] == "birth" and not DECEASED.search((src.get("extract") or "")[:300]):
            continue  # живих людей не публікуємо
        if kind == "figure" and not src.get("extract"):
            continue
        title, text = write(cand, kind, src, key, model, call)
        occ = occasion(cand, today)
        life = ""
        if kind == "figure":
            m = re.search(r"\(([^()]*?\d{4}[^()]*?[–—-][^()]*?\d{4}[^()]*?)\)", src.get("extract", "")[:300])
            years = re.findall(r"\d{4}", m.group(1)) if m and not re.search(r"бл\.|\?|~|прибл", m.group(1)) else []
            life = f"{years[0]}–{years[-1]}" if len(years) >= 2 else ""
        caption = f"<b>{html.escape(title, quote=False)}</b>\n"
        if life:
            caption += f"<i>{life}</i>\n"
        caption += f"\n{html.escape(text, quote=False)}\n\n<i>{html.escape(occ, quote=False)}. Джерело: Вікіпедія.</i>"
        head = "Визначні постаті" if kind == "figure" else "Історичний факт"
        short = {"birth": "день народження", "death": "день пам'яті"}.get(cand["kind"])
        sub = f"{life} · {short}" if (life and short) else (life or f"{today.day} {MONTHS[today.month - 1]} {cand['year']} року")
        return {"title": title, "subtitle": sub, "chips": [head], "caption": caption,
                "key": (cand["link"] or cand["text"][:40]).lower()}
    return None
