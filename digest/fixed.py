"""Щоденні фіксовані пости: свято, курс НБУ, ціни на пальне, хвилина мовчання (картка + короткий підпис).
  python3 -m digest.fixed --kind holiday|rates|fuel|figure|fact [--dry] [--now 'YYYY-MM-DDTHH:MM' UTC] [--force]
Правила: на паузі (/stop) не публікує; не публікує повторно за ту саму дату; запізнившись надто сильно — пропускає;
помилка джерела — нічого не публікує, а надсилає власнику коротке повідомлення (вигаданих чисел не буває)."""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from . import publish
from .calendar_ua import LABEL, holidays_for
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent
CARDS = ROOT / "assets" / "cards"
TZ = "Europe/Kyiv"
TARGET = {"holiday": (6, 0), "rates": (6, 30), "fuel": (7, 0), "silence": (9, 0), "figure": (12, 0), "culture": (14, 0), "fact": (17, 0), "cat": (22, 0)}
LATE = {"holiday": 180, "rates": 180, "fuel": 180, "silence": 1, "figure": 300, "culture": 300, "fact": 300, "cat": 180}  # хвилини: пізніше — пропускаємо
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
NBU = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json&date={d:%Y%m%d}"
FUEL_URL = "https://index.minfin.com.ua/ua/markets/fuel/tm/"
FOOT = "<i>Автоматичний пост каналу РАДАР.</i>"


def get(url: str, timeout: int = 30) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; RadarBot/1.0)"})
    with urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read().decode("utf-8", "replace")


def human(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def banner(key: str, default):
    """Постійний банер з котом для рубрики (state/banners/<ключ>.jpg), якщо він є і в rubrics.json banners=live; інакше — звичайна картка."""
    try:
        if json.loads(RUBRICS.read_text(encoding="utf-8")).get("banners") == "live" and (BANNER_DIR / f"{key}.jpg").exists():
            return BANNER_DIR / f"{key}.jpg"
    except (OSError, json.JSONDecodeError):
        pass
    return default


# ---------- свято ----------
def holiday_post(d: date):
    hs = holidays_for(d)
    if not hs:
        return None
    lines = [f"<b>Сьогодні, {human(d)}</b>", ""]
    for name, kind in hs:
        lines.append(f"• {html.escape(name, quote=False)} <i>({LABEL[kind]})</i>")
    lines += ["", FOOT]
    return banner("holiday", CARDS / f"holiday-{d.day}.jpg"), "\n".join(lines)


# ---------- курс НБУ ----------
def parse_nbu(raw: str) -> dict[str, float]:
    return {x["cc"]: float(x["rate"]) for x in json.loads(raw) if x.get("cc") in ("USD", "EUR", "PLN", "GBP")}


def rates_post(d: date, fetch=get):
    today = parse_nbu(fetch(NBU.format(d=d)))
    if not {"USD", "EUR"} <= set(today):
        raise RuntimeError("НБУ не віддав USD/EUR")
    try:
        prev = parse_nbu(fetch(NBU.format(d=d - timedelta(days=1))))
    except Exception:  # noqa: BLE001
        prev = {}
    lines = [f"<b>Офіційний курс НБУ на {d:%d.%m}</b>", ""]
    for cc, sym in (("USD", "Долар США"), ("EUR", "Євро"), ("PLN", "Злотий")):
        if cc not in today:
            continue
        ch = ""
        if cc in prev and abs(today[cc] - prev[cc]) >= 0.005:
            dl = today[cc] - prev[cc]
            ch = f" ({'▲' if dl > 0 else '▼'} {abs(dl):.2f})"
        lines.append(f"{sym}: <b>{today[cc]:.2f}</b> грн{ch}".replace(".", ","))
    lines += ["", "<i>Джерело: Національний банк України. Зміна — до попереднього дня.</i>"]
    return banner("rates", CARDS / "rates.jpg"), "\n".join(lines)


# ---------- пальне ----------
class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in = [], None, "", False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._in, self._cell = True, ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._in:
            self._row.append(" ".join(self._cell.split()))
            self._in = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in:
            self._cell += data


def parse_fuel(page: str) -> dict:
    """Середні ціни за провідними операторами зі сторінки Мінфіну: {'date': 'ДД.ММ.РРРР', 'А-95': 76.3, 'ДП': …, 'Газ': …, 'n': {...}}."""
    t = _Table()
    t.feed(page)
    hdr_i = next((i for i, r in enumerate(t.rows) if "Оператор" in r and "ДП" in r), None)
    if hdr_i is None:
        raise RuntimeError("не знайдено таблицю цін")
    hdr = t.rows[hdr_i]
    # Шапка й рядки даних можуть мати різну кількість клітинок (порожні/об'єднані): тому рахуємо колонки від ПРАВОГО краю таблиці.
    def from_right(pred):
        i = next((i for i, h in enumerate(hdr) if pred(h.replace(" ", ""))), None)
        return None if i is None else len(hdr) - 1 - i
    cols = {"А-95": from_right(lambda h: h == "А95"), "А-92": from_right(lambda h: h == "А92"),
            "ДП": from_right(lambda h: h == "ДП"), "Газ": from_right(lambda h: h == "Газ")}
    vals: dict[str, list[float]] = {k: [] for k, v in cols.items() if v is not None}
    for r in t.rows[hdr_i + 1:]:
        for k, fr in cols.items():
            if fr is None or len(r) - 1 - fr < 1:
                continue
            try:
                v = float(r[len(r) - 1 - fr].replace(",", "."))
            except ValueError:
                continue
            if 20 < v < 300:  # відсікаємо сміття
                vals[k].append(v)
    import re
    m = re.search(r"на\s+(\d{2}\.\d{2}\.\d{4})", page)
    out = {k: round(statistics.mean(v), 2) for k, v in vals.items() if len(v) >= 3}
    if "А-95" not in out or "ДП" not in out:
        raise RuntimeError("замало даних у таблиці")
    # перевірка правдоподібності: при зсуві колонок краще не публікувати нічого, ніж неправду
    a95, dp, gas = out["А-95"], out["ДП"], out.get("Газ")
    if not (45 < a95 < 140 and 45 < dp < 160 and (gas is None or 20 < gas < min(a95, dp)) and ("А-92" not in out or out["А-92"] <= a95 + 0.5)):
        raise RuntimeError(f"ціни виглядають неправдоподібно (А-95 {a95}, ДП {dp}, газ {gas}): можливо, змінилась таблиця")
    out["n"] = {k: len(v) for k, v in vals.items()}
    out["date"] = m.group(1) if m else ""
    return out


def fuel_post(d: date, st: State, fetch=get):
    cur = parse_fuel(fetch(FUEL_URL))
    prev_file = st.dir / "fuel.json"
    try:
        prev = json.loads(prev_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        prev = {}
    lines = [f"<b>Вартість пального на {d:%d.%m}</b>", "<i>середнє за провідними мережами АЗС, грн/л</i>", ""]
    for k, name in (("А-95", "Бензин А-95"), ("А-92", "Бензин А-92"), ("ДП", "Дизель"), ("Газ", "Автогаз")):
        if k not in cur:
            continue
        ch = ""
        if k in prev and abs(cur[k] - prev[k]) >= 0.005:
            dl = cur[k] - prev[k]
            ch = f" ({'▲' if dl > 0 else '▼'} {abs(dl):.2f})"
        lines.append(f"{name}: <b>{cur[k]:.2f}</b>{ch}".replace(".", ","))
    note = f" (дані на {cur['date']})" if cur.get("date") and cur["date"] != f"{d:%d.%m.%Y}" else ""
    lines += ["", f"<i>Джерело: Мінфін / A-95 Consulting{note}. Зміна — до попереднього допису.</i>"]
    return banner("fuel", CARDS / "fuel.jpg"), "\n".join(lines), {k: v for k, v in cur.items() if k in ("А-95", "А-92", "ДП", "Газ")}


# ---------- хвилина мовчання ----------
def silence_post(d: date):
    text = ("<b>Хвилина мовчання</b>\n\nО 9:00 вшановуємо пам'ять тих, хто загинув, захищаючи Україну. "
            "Зупинімося на хвилину.\n\n<i>Вічна пам'ять і шана.</i>")
    return CARDS / "silence.jpg", text


# ---------- рубрики «Визначні постаті» і «Історичний факт» ----------
RUBRICS = ROOT / "rubrics.json"
BANNER_DIR = ROOT / "state" / "banners"
RUBRIC_NAMES = {"figure": "Визначні постаті", "culture": "Культурні діячі", "fact": "Історичний факт", "cat": "Кіт-Радар"}


def rubric_mode(kind: str) -> str:
    """'preview' — надсилати лише власнику (пробний показ), 'live' — у канал."""
    try:
        return json.loads(RUBRICS.read_text(encoding="utf-8")).get(kind, "preview")
    except (OSError, json.JSONDecodeError):
        return "preview"


def cat_post(d: date, st: State):
    from . import cat, llm
    try:
        key = llm.load_key()
    except llm.LLMError:
        key = None
    r = cat.build(d, key)
    if r is None:
        return None
    path, caption, origin = r
    return path, caption, None, [origin]


def rubric_post(kind: str, d: date, st: State, fetch=None, key: str | None = None, call=None):
    if kind == "cat":
        return cat_post(d, st)
    from . import card, chronicle, llm
    used_file = st.dir / ("culture.json" if kind == "culture" else "chronicle.json")
    try:
        used = json.loads(used_file.read_text(encoding="utf-8")).get("used", [])
    except (OSError, json.JSONDecodeError):
        used = []
    if key is None:
        try:
            key = llm.load_key()
        except llm.LLMError:
            key = None  # без ключа — дослівний уривок із Вікіпедії
    if kind == "culture":
        from . import culture
        res = culture.build(d, [u["k"] for u in used], fetch or culture.get_json, key, call or llm.generate_json)
    else:
        res = chronicle.build(kind, d, [u["k"] for u in used], fetch or chronicle.get_json, key, call or llm.generate_json)
    if res is None:
        return None
    out = pathlib.Path("/tmp") / f"rubric-{kind}-{d.isoformat()}.jpg"
    glyph, accent = ("clock", "history") if kind == "fact" else ("person", "figure")
    ban = banner(kind, None)
    if ban is not None:
        out = ban
    elif card.available():
        card.render(res["title"], out, subtitle=res["subtitle"], chips=res["chips"], kind=accent, glyph=glyph)
    else:
        out = CARDS / "holiday-1.jpg"
    used = [u for u in used if kind == "culture" or u["d"] >= (d - timedelta(days=400)).isoformat()] + [{"k": res["key"], "d": d.isoformat()}]
    return out, res["caption"], used_file, used


# ---------- запуск ----------
def due(kind: str, now: datetime) -> tuple[bool, str]:
    z = now.astimezone(ZoneInfo(TZ))
    h, m = TARGET[kind]
    target = z.replace(hour=h, minute=m, second=0, microsecond=0)
    late = (z - target).total_seconds() / 60
    if late < -10:
        return False, "ще рано"
    if late > LATE[kind]:
        return False, f"запізнення {int(late)} хв — пропускаю"
    return True, ""


def banners_main(a) -> int:
    """Разова генерація постійних банерів з котом: зберігаються в state/banners і надсилаються власнику на перегляд."""
    import os
    from . import cat, llm
    only = os.environ.get("CAT_SCENE", "").strip() or None
    if only and only not in cat.BANNERS:
        only = None
    key = llm.load_key()
    done = cat.build_banners(key, BANNER_DIR, only)
    for k, label, path in done:
        if not a.dry:
            publish.send_photo(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"), path, f"<b>👀 Банер «{label}»</b> ({k}) — пробний, у канал не йде")
    miss = [k for k in ([only] if only else cat.BANNERS) if k not in [d[0] for d in done]]
    if miss:
        print("Не вдалося:", miss, cat.last_error, file=sys.stderr)
        if not a.dry:
            publish.send(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"), html.escape(f"⚠️ Банери не намалювалися: {miss}. {' | '.join(cat.last_error)[:300]}", quote=False))
    print("Банери:", [d[0] for d in done])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", required=True, choices=list(TARGET) + ["banners"])
    ap.add_argument("--now")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true", help="ігнорувати паузу, «вже публікували» і запізнення (для ручної перевірки)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(TZ)).date()
    st = State(ROOT / "state")
    if a.kind == "banners":
        return banners_main(a)
    mark_file = st.dir / "fixed.json"
    try:
        marks = json.loads(mark_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        marks = {}
    if not a.force:
        if st.paused():
            print("⏸ Пауза: нічого не публікую.")
            return 0
        if marks.get(a.kind) == today.isoformat():
            print("Сьогодні вже опубліковано.")
            return 0
        ok, why = due(a.kind, now)
        if not ok:
            print(why)
            return 0
    extra = None
    try:
        if a.kind == "holiday":
            res = holiday_post(today)
        elif a.kind == "rates":
            res = rates_post(today)
        elif a.kind == "fuel":
            res = fuel_post(today, st)
            extra = res[2]
            res = res[:2]
        elif a.kind in RUBRIC_NAMES:
            r = rubric_post(a.kind, today, st)
            if r is None:
                raise RuntimeError("на сьогодні нічого не вдалося підготувати (для котика — Gemini не віддав малюнок)")
            res, extra = r[:2], r[2:]
        else:
            res = silence_post(today)
    except Exception as exc:  # noqa: BLE001
        msg = f"⚠️ РАДАР: пост «{a.kind}» не вийшов ({str(exc)[:400]}). Нічого не опубліковано."
        print(msg, file=sys.stderr)
        if a.kind in RUBRIC_NAMES and not a.force and marks.get("alert-" + a.kind) == today.isoformat():
            return 0  # про збій рубрики повідомляємо раз на добу; наступні спроби тихі
        if a.kind in RUBRIC_NAMES and not a.dry:
            marks["alert-" + a.kind] = today.isoformat()
            mark_file.write_text(json.dumps(marks), encoding="utf-8")
        if not a.dry:
            try:
                publish.send(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"), html.escape(msg, quote=False))
            except SystemExit:
                pass
        return 0
    if res is None:
        print("Сьогодні немає свят у календарі — пост пропущено.")
        return 0
    card, caption = res
    if a.dry:
        print(card, "\n", caption)
        return 0
    if a.kind in RUBRIC_NAMES:
        preview = rubric_mode(a.kind) != "live"
        chat = publish.env("TELEGRAM_OWNER_ID") if preview else publish.env("TELEGRAM_CHAT_ID")
        note = f" · {extra[1][0]}" if a.kind == "cat" else ""
        cap = (f"<b>👀 Пробний показ рубрики «{RUBRIC_NAMES[a.kind]}»</b> (у канал не йде{note})\n\n" if preview else "") + caption
        publish.send_photo(publish.env("TELEGRAM_BOT_TOKEN"), chat, card, cap)
        if extra[0] is not None:
            extra[0].write_text(json.dumps({"used": extra[1]}, ensure_ascii=False), encoding="utf-8")
        extra = None
    else:
        publish.send_photo(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID"), card, caption)
    marks[a.kind] = today.isoformat()
    mark_file.write_text(json.dumps(marks), encoding="utf-8")
    if extra:
        (st.dir / "fuel.json").write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    st.log_event("sent", {"holiday": "Свято сьогодні", "rates": "Курс валют НБУ", "fuel": "Вартість пального", "silence": "Хвилина мовчання", "figure": "Визначні постаті", "culture": "Культурні діячі", "fact": "Історичний факт", "cat": "Кіт-Радар"}[a.kind], now)
    print("Опубліковано:", a.kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
