"""«Топ-рейтинг» о 21:00: огляд видань світу на тему, яку обрали читачі (голоси за 7 діб).
Немає голосів — береться тема, про яку власні матеріали каналу за тиждень писали найбільше; про це в пості не згадується.
Закритий перелік тем (topics.json) і перевірка цитат дозволяють лише те, що є в межах інтересів каналу."""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import card, deliver, focus, llm, poll, publish, synth, telegram_fmt
from .cluster import Cluster, cluster_items, tokens
from .fetch import Item, fetch_all
from .rank import rank
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = "Europe/Kyiv"
AT = (21, 0)
LATE_UNTIL = (23, 30)

TOP_SYSTEM = """You write the daily rubric "Топ-рейтинг" for a Ukrainian Telegram channel that shows what the world's media say about Ukraine.
TOPIC OF TODAY: {title} ({scope}).
Below are several stories (headlines and snippets of outlets that fit this topic). Write a review of how these outlets cover Ukraine within the topic.
Rules: use ONLY the provided texts, no new facts. Every point needs a short VERBATIM quote (at least 12 characters, exactly as in the text) from the outlet that supports it, with that outlet's id.
Each point: at most 25 words, neutral wording, says WHAT the outlet stresses or reports (name the angle: whom it quotes, what it emphasises). Prefer outlets from different countries; include sceptical or critical framings when present; never add praise or opinions.
An outlet flagged state-funded is quoted as that outlet's/government's position, not as established fact.
Never mention how the topic was chosen. Write Ukrainian only.
Return JSON only: {{"headline":"<one line, Ukrainian, what the review is about>","points":[{{"uk":"","evidence":[{{"id":"<outlet id>","quote":"<verbatim>"}}]}}],"watch":""}}
Give 4 to 6 points, one per distinct story, most important first."""


def _kyiv(now: datetime) -> datetime:
    return now.astimezone(ZoneInfo(TZ))


def matches(topic: dict, it: Item, by_id: dict) -> bool:
    if topic["kind"] == "story":  # історія дня: те саме посилання або достатньо спільних слів із заголовками, на яких писали пост
        if it.link in topic.get("links", []):
            return True
        have = set(topic.get("tokens", []))
        inter = set(tokens(it.title)) & have
        return len(inter) >= 3 and len(inter) / max(len(have), 1) >= 0.25
    if topic["kind"] == "country":
        c = by_id.get(it.source_id, {}).get("country") or it.country
        return c in topic["countries"]
    text = f"{it.title} {it.summary}".lower()
    return any(s in text for s in topic["stems"])


def _stats(st: State) -> dict:
    try:
        return json.loads((st.dir / "topicstats.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record_stats(st: State, now: datetime, counts: dict[str, int]) -> dict[str, int]:
    """Власна статистика тем: скільки матеріалів про Україну за день припадає на кожну тему; повертає суму за 7 діб."""
    d = _stats(st)
    d[_kyiv(now).date().isoformat()] = counts
    cut = (now - timedelta(days=7)).date().isoformat()
    d = {k: v for k, v in d.items() if k >= cut}
    (st.dir / "topicstats.json").write_text(json.dumps(d), encoding="utf-8")
    tot: dict[str, int] = {}
    for rec in d.values():
        for k, v in rec.items():
            tot[k] = tot.get(k, 0) + v
    return tot


def order_topics(topics: list[dict], votes: dict[str, int], own: dict[str, int], min_votes: int, last: str | None, voters: int | None = None) -> tuple[list[dict], bool]:
    """Теми від найпопулярнішої. Голосів досить — за голосами (не повторюємо вчорашню тему, якщо є інша з голосами); інакше за власною статистикою."""
    total = sum(votes.values()) if voters is None else voters
    if total >= min_votes:
        ranked = sorted(topics, key=lambda t: -votes.get(t["id"], 0))
        voted = [t for t in ranked if votes.get(t["id"], 0) > 0]
        if last and len(voted) > 1 and voted[0]["id"] == last:
            ranked = [t for t in ranked if t["id"] != last] + [t for t in ranked if t["id"] == last]
        return ranked, True
    ranked = sorted(topics, key=lambda t: -own.get(t["id"], 0))
    if last and len(ranked) > 1 and ranked[0]["id"] == last:
        ranked = ranked[1:] + ranked[:1]
    return ranked, False


def build(topic: dict, items: list[Item], by_id: dict, now: datetime):
    its = [i for i in items if matches(topic, i, by_id)]
    rs = rank(cluster_items(its, 0.25), now, "week", 1, 6)
    return [r for r in rs if r.cluster.items]


def generate(topic: dict, rs, by_id: dict, key: str, model: str, fallback: str) -> dict | None:
    if topic["kind"] == "story":
        scope = "one story of the day"
    elif topic["kind"] == "country":
        scope = ", ".join(topic.get("countries", []))
    else:
        scope = "theme: " + ", ".join(topic["stems"][:6])
    system = TOP_SYSTEM.format(title=topic["title"], scope=scope)
    prompt = synth.build_digest_prompt(rs, by_id)
    for _ in range(2):
        try:
            return synth.parse_digest(llm.generate_json(system, prompt, model, key), rs)
        except llm.LLMError as exc:
            if llm.is_busy(exc) and fallback and model != fallback:
                model = fallback
                continue
            print(f"  ✗ {str(exc)[:160]}", file=sys.stderr)
            return None
        except synth.BadSynthesis as exc:
            print(f"  ✗ {exc}", file=sys.stderr)
    return None


def run(st: State, now: datetime, items: list[Item], by_id: dict, cfg: dict, key: str, sender=None, model: str = llm.DEFAULT_MODEL, fallback: str = llm.FALLBACK_MODEL) -> str:
    static = cfg["topics"]
    topics = static + poll.dynamic_topics(st, now)  # плюс «історії дня» з останніх опитувань
    counts = {t["id"]: sum(1 for i in items if matches(t, i, by_id)) for t in static}
    own = record_stats(st, now, counts)
    votes = poll.weekly(st, now)
    try:
        last = json.loads((st.dir / "top.json").read_text(encoding="utf-8")).get("topic")
    except (OSError, json.JSONDecodeError):
        last = None
    order, from_votes = order_topics(topics, votes, own, cfg["poll"].get("min_votes", 3), last, poll.voters(st, now))
    for t in order[:4]:
        rs = build(t, items, by_id, now)
        if len(rs) < 2:
            continue
        d = generate(t, rs, by_id, key, model, fallback)
        if not d:
            continue
        html_text = telegram_fmt.render_top(d, rs, by_id, t, now, from_votes)
        chips = telegram_fmt.chips(rs, by_id)
        spec = {"title": "Топ-рейтинг", "subtitle": t["title"], "chips": chips, "kind": "top"}
        if sender:
            sender(spec, html_text)
        else:
            tok, chat = publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID")
            if not deliver.send_card_text(tok, chat, spec, html_text):
                publish.send(tok, chat, html_text, None)
        (st.dir / "top.json").write_text(json.dumps({"day": _kyiv(now).date().isoformat(), "topic": t["id"], "votes": from_votes}), encoding="utf-8")
        st.log_event("toprating", t["title"], now)
        return f"опубліковано: {t['title']} ({'за голосами' if from_votes else 'за власною статистикою'})"
    return "немає достатньо матеріалів для жодної теми"


def tick(st: State, now: datetime, cfg: dict | None = None) -> str:
    if st.paused():
        return "пауза"
    local = _kyiv(now)
    if not (AT <= (local.hour, local.minute) < LATE_UNTIL):
        return "рано" if (local.hour, local.minute) < AT else "пізно"
    try:
        if json.loads((st.dir / "top.json").read_text(encoding="utf-8")).get("day") == local.date().isoformat():
            return "сьогодні вже було"
    except (OSError, json.JSONDecodeError):
        pass
    cfg = cfg or poll.load_topics()
    marker = st.dir / "top.json"  # відмічаємо спробу, щоб не повторювати збої щохвилини
    try:
        prev = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        prev = {}
    if prev.get("tried") == local.date().isoformat():
        return "сьогодні вже пробували"
    prev["tried"] = local.date().isoformat()
    marker.write_text(json.dumps(prev), encoding="utf-8")
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    on = [s for s in sources["sources"] if s.get("enabled", True)]
    items, _ = fetch_all(on)
    items = focus.apply(items, sources)
    return run(st, now, items, {s["id"]: s for s in on}, cfg, llm.load_key())
