"""Вечірній огляд: ОДИН великий аналітичний пост на день.
Протягом дня алгоритм збирає матеріали (collect_tick), ближче до вечора (за замовчуванням 20:00 за Києвом) обирає тему дня:
подію, про яку пишуть видання щонайменше трьох країн, читає ПОВНІ тексти статей, пише розбір (що сталося, як це бачать, де розходяться,
що це означає для України, за чим стежити, проста порада й побажання) і перевіряє кожне фактичне твердження дослівною цитатою з тексту.
Недостатньо матеріалу для сильного огляду — цього дня поста немає."""
from __future__ import annotations

import html as htmllib
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import deliver, focus, fulltext, llm, publish, synth, telegram_fmt
from .cluster import Cluster, cluster_items
from .fetch import Item, fetch_all
from .rank import rank
from .report import label
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = "Europe/Kyiv"
LIMIT = 3900  # Telegram: до 4096 символів тексту повідомлення
KEEP_HOURS = 40
MAX_TRIES = 4


def load_cfg() -> dict:
    cfg = {"mode": "preview", "at": [20, 0], "until": [23, 20], "min_outlets": 3, "min_countries": 3, "max_outlets": 5, "min_text": 800, "collect_every": 60, "retry_minutes": 15}
    try:
        cfg.update(json.loads((ROOT / "evening.json").read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def _kyiv(now: datetime) -> datetime:
    return now.astimezone(ZoneInfo(TZ))


def _jload(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# ---------- збір протягом дня ----------
def _to_dict(i: Item) -> dict:
    return {"s": i.source_id, "n": i.source_name, "t": i.title, "l": i.link, "m": i.summary, "p": i.published.isoformat(), "c": i.country, "i": i.image}


def _from_dict(d: dict) -> Item:
    return Item(d["s"], d["n"], d["t"], d["l"], d.get("m", ""), datetime.fromisoformat(d["p"]), d.get("c", ""), d.get("i", ""))


def collect(st: State, now: datetime, items: list[Item]) -> int:
    """Додає нові матеріали до денного накопичувача (state/day.json); старше KEEP_HOURS прибирає."""
    path = st.dir / "day.json"
    data = _jload(path)
    known = {d["l"]: d for d in data.get("items", [])}
    for i in items:
        known.setdefault(i.link, _to_dict(i))
    cut = now - timedelta(hours=KEEP_HOURS)
    kept = [d for d in known.values() if datetime.fromisoformat(d["p"]) >= cut]
    path.write_text(json.dumps({"last": now.isoformat(), "items": kept}, ensure_ascii=False), encoding="utf-8")
    return len(kept)


def _fetch_focus() -> tuple[list[Item], dict[str, dict], dict]:
    cfg = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    on = [s for s in cfg["sources"] if s.get("enabled", True)]
    items, _ = fetch_all(on)
    return focus.apply(items, cfg), {s["id"]: s for s in on}, cfg


def collect_tick(st: State, now: datetime, ecfg: dict | None = None) -> str:
    ecfg = ecfg or load_cfg()
    last = _jload(st.dir / "day.json").get("last")
    if last and now - datetime.fromisoformat(last) < timedelta(minutes=ecfg["collect_every"]):
        return "рано"
    items, _, _ = _fetch_focus()
    return f"зібрано {collect(st, now, items)} матеріалів"


# ---------- вибір теми й повні тексти ----------
def pick_topic(st: State, now: datetime, items: list[Item], by_id: dict, ecfg: dict, get=fulltext.fetch_page) -> tuple[Cluster, dict[str, dict]] | None:
    """Перша тема з рейтингу, для якої вдалося прочитати повні тексти щонайменше min_outlets видань із min_countries країн."""
    ranked = rank(cluster_items(items, 0.25), now, "day", 2, 14)
    for r in ranked:
        if st.is_duplicate(r, now):
            continue
        by_src: dict[str, Item] = {}
        for it in sorted(r.cluster.items, key=lambda i: i.published, reverse=True):
            by_src.setdefault(it.source_id, it)
        if len(by_src) < ecfg["min_outlets"] or len({i.country for i in by_src.values() if i.country}) < ecfg["min_countries"]:
            continue
        # спершу видання з нових країн, щоб огляд був різноголосим
        order, seen_c = [], set()
        for it in sorted(by_src.values(), key=lambda i: (i.country in seen_c, -i.published.timestamp())):
            order.append(it)
            seen_c.add(it.country)
        texts: dict[str, dict] = {}
        for it in order:
            body = fulltext.fetch_text(it.link, ecfg["min_text"], get)
            if body:
                texts[it.source_id] = {"item": it, "text": body, "src": by_id.get(it.source_id, {})}
            if len(texts) >= ecfg["max_outlets"]:
                break
        countries = {t["item"].country for t in texts.values() if t["item"].country}
        if len(texts) >= ecfg["min_outlets"] and len(countries) >= ecfg["min_countries"]:
            return r.cluster, texts
        print(f"  (тема пропущена: повні тексти лише від {len(texts)} видань: {r.cluster.items[0].title[:60]})", file=sys.stderr)
    return None


# ---------- запит до моделі ----------
VOICE = ("VOICE: lively, warm, ironic colloquial Ukrainian in the spirit of the spoken manner of Kuzma Skryabin - playful, folksy, self-ironic, with vivid homely images and unexpected comparisons, like a witty friend telling the news over tea (a manner of speaking only: never quote or imitate his songs or lyrics, never put words in his mouth): short sentences, direct address ('слухай', 'запам'ятай'), "
         "dry humour and folk turns of phrase. The headings are the place for wit: each heading is a short folksy line with a twist (for example in the spirit of 'Хто що бачить, поки чайник википає', "
         "'Де сходяться, а де розходяться', 'А тепер без прикрас'), never generic labels. NEVER vulgar, no slang like 'налупили', no swearing, no mocking tone about the war. "
         "Humour lives ONLY in headings, transitions, the advice and the wish; factual statements stay precise and plain. Never joke about victims, deaths, injuries or suffering. "
         "Do not quote or imitate any real person's songs or lyrics, and do not attribute words to anyone who is not quoted in the articles.")

SYSTEM = """You are the author of the single daily EVENING REVIEW for a Ukrainian Telegram channel "РАДАР | Україна у світі": what the world's leading outlets say ABOUT UKRAINE.
You get the FULL TEXTS of several articles on one story from outlets of different countries. Write ONE substantial analytical post in Ukrainian that a reader would finish and share: concrete, insightful, never grey or generic.
Rules:
1. Facts ONLY from the provided texts. Never add facts, names, figures or quotes that are not there.
2. EVIDENCE IS MANDATORY: every factual statement ("event", "views", "agree", "clash") must carry a VERBATIM quote (12 to 150 characters, copied exactly from that outlet's text, in the text's original language, no ellipses) with the outlet's id. Statements without a real quote will be deleted by a program. Numbers in your sentences must appear in the texts. Prefer quotes that carry a concrete detail: a figure, a name, a place, a precise claim.
3. "event": 3-4 sentences with the concrete facts: who, what, where, how many, what was said. Not vague summaries.
4. "views": one item per outlet (3 to 5). Each item is 2-3 sentences about THAT outlet's own angle: what it stresses, whom it quotes, how it frames Ukraine or the event, what it leaves out. Not a repeat of common facts. Mention a concrete detail from its text. Its "quote" is shown to readers, so choose the most telling short fragment. An outlet flagged state-funded is a government/state position, never established fact. Include sceptical or critical framings when the texts contain them; never add praise or opinions of your own.
5. "agree": 1-2 points on which at least two outlets agree (same fact or same assessment), each with quotes from two different outlets. "clash": real conflicts only (different facts, claims, interpretations), each with quotes from at least two different outlets. Empty lists are fine. Never invent agreement or disagreement.
6. "meaning": 2-3 sentences, YOUR OWN reading of what this means for Ukraine. It is labelled as an editorial reading, so make it a clear thesis with reasoning drawn only from the facts above, no new facts; at most one hedge word in the whole paragraph, no vague filler.
7. "watch": 2-3 short concrete items about what to watch next, derived from the texts (dates, decisions, open questions).
8. "advice": one simple, human, practical sentence that follows from today's topic (information habits, planning, calm, caring for others), concrete and usable today; no clichés, no politics, no taking sides. "wish": one warm, human, specific wish (1-2 sentences), like a friend saying goodbye; never promise the end of the war or anything political.
9. "intro": 1-2 framing sentences, NO facts or numbers. "headline": at most 80 characters, names the story. "h": short witty headings (at most 55 characters, in the VOICE, plain text, no HTML) for sections event, views, agree, clash, meaning, watch, advice, wish.
10. Length: the whole post must be about 3200-3600 characters of Ukrainian (it must fit one Telegram message). Each sentence at most 28 words.
{voice}
Return JSON only:
{{"same_event":true,"importance":1-10,"headline":"","intro":"","h":{{"event":"","views":"","agree":"","clash":"","meaning":"","watch":"","advice":"","wish":""}},
"event":[{{"text":"","evidence":[{{"id":"","quote":""}}]}}],
"views":[{{"id":"","text":"","quote":""}}],
"agree":[{{"text":"","evidence":[{{"id":"","quote":""}},{{"id":"","quote":""}}]}}],
"clash":[{{"text":"","evidence":[{{"id":"","quote":""}},{{"id":"","quote":""}}]}}],
"meaning":[""],"watch":[""],"advice":"","wish":""}}"""


def system_prompt(ecfg: dict) -> str:
    return SYSTEM.format(voice=ecfg.get("voice") or VOICE)


def build_prompt(texts: dict[str, dict]) -> str:
    out = ["Write the evening review from these articles (full text, possibly trimmed).", ""]
    for sid, t in texts.items():
        it, src = t["item"], t["src"]
        out.append(f"=== OUTLET id={sid} | name={it.source_name} | profile={label(src)} | published={it.published:%Y-%m-%d %H:%M} UTC")
        out.append(f"headline: {it.title}")
        out.append(t["text"])
        out.append("")
    return "\n".join(out)


class BadReview(ValueError):
    pass


_NUM = re.compile(r"\d+")


def _plain(v, limit: int) -> str:
    s = re.sub(r"<[^>]*>", "", str(v or "")).strip()
    return s[:limit]


def parse(raw: str, texts: dict[str, dict]) -> dict:
    """Перевіряє відповідь: зайве без цитат видаляється; якщо лишилося замало — BadReview (цього дня поста не буде)."""
    try:
        data = json.loads(synth._FENCE.sub("", raw.strip()))
    except json.JSONDecodeError as e:
        raise BadReview(f"не JSON: {e}") from e
    if not isinstance(data, dict):
        raise BadReview("очікувався JSON-об'єкт")
    if data.get("same_event") is False:
        raise BadReview("модель вважає матеріали різними подіями")
    tn = {sid: synth._norm(t["text"] + " " + t["item"].title) for sid, t in texts.items()}
    allnums = set(_NUM.findall(" ".join(tn.values())))
    dropped = 0

    def nums_ok(s: str) -> bool:
        return all(n in allnums for n in _NUM.findall(s))

    def items(key):
        v = data.get(key)
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

    head = _plain(data.get("headline"), 200).rstrip(" .")
    if not head or len(head) > 100:
        raise BadReview("немає заголовка або він задовгий")
    event, views, clash = [], [], []
    for x in items("event"):
        txt = _plain(x.get("text"), 400)
        ok = any(synth._quote_ok(e, tn) for e in (x.get("evidence") or []))
        if txt and ok and nums_ok(txt):
            event.append(txt)
        else:
            dropped += 1
    seen = set()
    for x in items("views"):
        sid, txt = x.get("id"), _plain(x.get("text"), 400)
        if sid in texts and sid not in seen and txt and synth._quote_ok({"id": sid, "quote": x.get("quote")}, tn) and nums_ok(txt):
            q = _plain(x.get("quote"), 200)
            views.append({"id": sid, "text": txt, "quote": q if 12 <= len(q) <= 160 else ""})
            seen.add(sid)
        else:
            dropped += 1
    agree = []
    for key, bucket in (("agree", agree), ("clash", clash)):
        for x in items(key):
            txt = _plain(x.get("text"), 450)
            ids = {i for i in (synth._quote_ok(e, tn) for e in (x.get("evidence") or [])) if i}
            if txt and len(ids) >= 2 and nums_ok(txt):
                bucket.append(txt)
            else:
                dropped += 1
    if len(event) < 2:
        raise BadReview(f"замало підтверджених фактів про подію ({len(event)})")
    if len(views) < 3:
        raise BadReview(f"замало підтверджених поглядів видань ({len(views)})")
    h = data.get("h") if isinstance(data.get("h"), dict) else {}
    defaults = {"event": "Що сталося", "views": "Як це бачать у світі", "agree": "Де сходяться", "clash": "Де не сходяться", "meaning": "Що це означає для України", "watch": "За чим стежимо далі", "advice": "Проста порада", "wish": "І побажання"}
    heads = {k: (_plain(h.get(k), 60) or v) for k, v in defaults.items()}
    meaning = [m for m in (_plain(x, 400) for x in (data.get("meaning") or [])) if m][:3] if isinstance(data.get("meaning"), list) else []
    watch = [m for m in (_plain(x, 250) for x in (data.get("watch") or [])) if m][:3] if isinstance(data.get("watch"), list) else []
    try:
        imp = int(data.get("importance", 6))
    except (TypeError, ValueError):
        imp = 6
    return {"headline": head, "intro": _plain(data.get("intro"), 350), "heads": heads, "event": event, "views": views, "agree": agree, "clash": clash, "meaning": meaning, "watch": watch,
            "advice": _plain(data.get("advice"), 300), "wish": _plain(data.get("wish"), 350), "importance": imp, "dropped": dropped}


# ---------- вигляд поста ----------
def _esc(s: str) -> str:
    return htmllib.escape(s, quote=False)


def render(d: dict, texts: dict[str, dict], now: datetime) -> str:
    countries = []
    for t in texts.values():
        if t["item"].country and t["item"].country not in countries:
            countries.append(t["item"].country)
    exile_c = {t["item"].country for t in texts.values() if t["src"].get("type") == "independent_exile"}
    flags = " ".join([telegram_fmt.FLAG.get(c, "🌐") for c in countries if c not in exile_c] + (["🕊"] if exile_c else []))
    h = d["heads"]
    parts = [f"<b>{_esc(d['headline'].upper())}</b>", f"<i>Огляд світових медіа · {_kyiv(now):%d.%m}{(' · ' + flags) if flags else ''}</i>"]
    if d["intro"]:
        parts.append(_esc(d["intro"]))
    parts.append(f"<b>{_esc(h['event'])}</b>\n" + "\n".join(_esc(x) for x in d["event"]))
    views = []
    for v in d["views"]:
        t = texts[v["id"]]
        fl = telegram_fmt.FLAG.get(t["item"].country, "🌐")
        exile = t["src"].get("type") == "independent_exile"
        mark = "🕊" if exile else fl
        who = f"<i>{_esc(t['item'].source_name)}</i>" + (" <i>(незалежне, у вигнанні)</i>" if exile else "")
        quote = f" <i>«{_esc(v['quote'])}»</i>" if v.get("quote") else ""
        views.append(f"{mark + ' ' if mark else ''}{who}. {_esc(v['text'])}{quote}")
    parts.append(f"<b>{_esc(h['views'])}</b>\n" + "\n".join(views))
    if d.get("agree"):
        parts.append(f"<b>{_esc(h['agree'])}</b>\n" + "\n".join("• " + _esc(x) for x in d["agree"]))
    if d["clash"]:
        parts.append(f"<b>{_esc(h['clash'])}</b>\n" + "\n".join(_esc(x) for x in d["clash"]))
    if d["meaning"]:
        parts.append(f"<b>{_esc(h['meaning'])}</b> <i>(наш висновок із прочитаного, не факт із джерел)</i>\n" + " ".join(_esc(x) for x in d["meaning"]))
    if d["watch"]:
        parts.append(f"<b>{_esc(h['watch'])}</b>\n" + "\n".join("• " + _esc(x) for x in d["watch"]))
    if d["advice"]:
        parts.append(f"<b>{_esc(h['advice'])}</b>\n{_esc(d['advice'])}")
    if d["wish"]:
        parts.append(f"<b>{_esc(h['wish'])}</b>\n{_esc(d['wish'])}")
    links = ", ".join(f'<a href="{htmllib.escape(t["item"].link, quote=True)}">{_esc(t["item"].source_name)}</a>' for t in texts.values() if any(v["id"] == t["item"].source_id for v in d["views"]))
    parts.append(f"<i>Джерела:</i> {links}")
    return "\n\n".join(parts)


def fit(d: dict, texts: dict[str, dict], now: datetime, limit: int = LIMIT) -> str | None:
    """Скорочує розбір (від менш важливого), поки не влізе в одне повідомлення. None — не вдалося."""
    d = {**d, "event": list(d["event"]), "views": [dict(v) for v in d["views"]], "agree": list(d.get("agree", [])), "clash": list(d["clash"]), "meaning": list(d["meaning"]), "watch": list(d["watch"])}
    # спершу прибираємо цитати з тексту та другорядне, потім зменшуємо розділи
    def drop_quotes(n):
        for v in d["views"][n:]:
            v["quote"] = ""
    steps = (("watch", 2), ("agree", 1), ("meaning", 2), ("clash", 1), ("quotes", 3), ("quotes", 1), ("event", 3), ("views", 4), ("watch", 1), ("quotes", 0), ("clash", 0), ("agree", 0), ("views", 3), ("event", 2))
    text = render(d, texts, now)
    for key, n in steps:
        if len(text) <= limit:
            return text
        if key == "quotes":
            drop_quotes(n)
        else:
            d[key] = d[key][:n]
        text = render(d, texts, now)
    return text if len(text) <= limit else None


# ---------- запуск ----------
def generate(texts: dict[str, dict], ecfg: dict, key: str, model: str | None = None, fallback: str | None = None, call=llm.generate_json, sleep=None) -> dict:
    import time
    sleep = sleep or time.sleep
    model = model or ecfg.get("model") or llm.DEFAULT_MODEL
    fallback = fallback or llm.FALLBACK_MODEL
    system, prompt = system_prompt(ecfg), build_prompt(texts)
    last = None
    waits = 0
    attempt = 0
    while attempt < 2:
        try:
            raw = call(system, prompt if attempt == 0 else prompt + "\n\nMake it SHORTER: about 2800 characters in total.", model, key)
        except llm.LLMError as exc:
            if llm.is_busy(exc):
                if model != fallback:
                    print(f"  ↪ модель {model} недоступна, переходжу на {fallback}", file=sys.stderr)
                    model = fallback
                    continue
                if waits < 4:  # перевантаження зазвичай коротке: чекаємо й пробуємо знову
                    waits += 1
                    print(f"  … {model} перевантажена, чекаю {30 * waits} с", file=sys.stderr)
                    sleep(30 * waits)
                    continue
            raise
        try:
            return parse(raw, texts)
        except BadReview as exc:
            last = exc
            attempt += 1
            print(f"  ✗ відповідь не пройшла перевірку: {exc}", file=sys.stderr)
    raise last or BadReview("порожня відповідь")


def run(st: State, now: datetime, items: list[Item], by_id: dict, ecfg: dict, key: str, send=True, get=fulltext.fetch_page, call=llm.generate_json) -> str:
    picked = pick_topic(st, now, items, by_id, ecfg, get)
    if not picked:
        return "немає теми, про яку пишуть видання кількох країн і можна прочитати повні тексти: цього дня поста не буде"
    cluster, texts = picked
    d = generate(texts, ecfg, key, call=call)
    text = fit(d, texts, now)
    if not text:
        return "розбір не вдалося вмістити в один пост"
    if not send:
        print(text)
        return "чернетку показано"
    token = publish.env("TELEGRAM_BOT_TOKEN")
    preview = ecfg.get("mode", "preview") != "live"
    chat = publish.env("TELEGRAM_OWNER_ID") if preview else publish.env("TELEGRAM_CHAT_ID")
    countries = []
    for t in texts.values():
        if t["item"].country and t["item"].country not in countries:
            countries.append(t["item"].country)
    spec = {"title": d["headline"], "subtitle": "Вечірній огляд", "chips": [telegram_fmt.COUNTRY_UK.get(c, c) for c in countries], "kind": "evening"}
    if preview:
        publish.send(token, chat, "🔎 ПОПЕРЕДНІЙ ПЕРЕГЛЯД вечірнього огляду (в канал це не надіслано).", None)
    if not deliver.send_card_text(token, chat, spec, text):
        publish.send(token, chat, text, None)
    if not preview:
        from .rank import Ranked
        r = Ranked(cluster, 0.0, len(texts), len(texts), False)
        st.add(r, now, d["headline"])
        st.log_event("sent", d["headline"], now)
        st.set_last_sent(now)
    return f"{'перегляд надіслано власнику' if preview else 'опубліковано в канал'}: {d['headline']}"


def tick(st: State, now: datetime, ecfg: dict | None = None) -> str:
    ecfg = ecfg or load_cfg()
    if st.paused():
        return "пауза"
    local = _kyiv(now)
    hm = (local.hour, local.minute)
    if hm < tuple(ecfg["at"]):
        return "рано"
    if hm >= tuple(ecfg["until"]):
        return "пізно"
    marker = st.dir / "evening.json"
    m = _jload(marker)
    today = local.date().isoformat()
    if m.get("day") == today:
        if m.get("done"):
            return "сьогодні вже було"
        if m.get("tries", 0) >= MAX_TRIES:
            return "сьогодні спроби вичерпано"
        if m.get("last") and now - datetime.fromisoformat(m["last"]) < timedelta(minutes=ecfg["retry_minutes"]):
            return "чекаю наступної спроби"
    else:
        m = {"day": today, "tries": 0}
    m["tries"] = m.get("tries", 0) + 1
    m["last"] = now.isoformat()
    marker.write_text(json.dumps(m), encoding="utf-8")  # відмічаємо до відправки: збій не повинен породити дубль
    fresh, by_id, _ = _fetch_focus()
    collect(st, now, fresh)
    items = [_from_dict(d) for d in _jload(st.dir / "day.json").get("items", [])]
    try:
        msg = run(st, now, items, by_id, ecfg, llm.load_key())
    except (BadReview, llm.LLMError) as exc:
        return f"спроба {m['tries']} не вдалась: {str(exc)[:160]}"
    if msg.startswith(("перегляд", "опубліковано")):
        m["done"] = True
        marker.write_text(json.dumps(m), encoding="utf-8")
    return msg


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Вечірній огляд: показати чернетку тут і зараз (нічого не публікує)")
    ap.add_argument("--now", action="store_true", help="зібрати тему й показати чернетку в терміналі")
    a = ap.parse_args(argv)
    ecfg = load_cfg()
    st = State(ROOT / "state")
    now = datetime.now(timezone.utc)
    items, by_id, _ = _fetch_focus()
    collect(st, now, items)
    allitems = [_from_dict(d) for d in _jload(st.dir / "day.json").get("items", [])]
    print(run(st, now, allitems, by_id, ecfg, llm.load_key(), send=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
