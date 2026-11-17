"""Щоденне опитування «Які теми про Україну у світових медіа вам цікаві?» (закритий перелік із topics.json).
Картка → опитування (з 10:00 до 18:00 за Києвом), о 20:50 опитування закривається й результат записується в state/poll.json.
Голоси за останні 7 діб визначають тему вечірнього «Топ-рейтингу». Опитування в каналі анонімні, тож ми бачимо лише підсумок по варіантах."""
from __future__ import annotations

import json
import pathlib
import random
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import deliver, publish
from .state import State, similar_headlines

ROOT = pathlib.Path(__file__).resolve().parent.parent
TZ = "Europe/Kyiv"


def load_topics(path: pathlib.Path | None = None) -> dict:
    return json.loads((path or ROOT / "topics.json").read_text(encoding="utf-8"))


def _load(st: State) -> dict:
    try:
        return json.loads((st.dir / "poll.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(st: State, d: dict) -> None:
    (st.dir / "poll.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def weekly(st: State, now: datetime, days: int = 7) -> dict[str, int]:
    """Сума голосів за кожну тему за останні `days` діб."""
    out: dict[str, int] = {}
    cut = (now - timedelta(days=days)).date().isoformat()
    for day, rec in (_load(st).get("days") or {}).items():
        if day >= cut:
            for k, v in rec.get("counts", {}).items():
                out[k] = out.get(k, 0) + int(v)
    return out


def voters(st: State, now: datetime, days: int = 7) -> int:
    """Скільки людей проголосувало за останні `days` діб (а не скільки варіантів вони обрали)."""
    cut = (now - timedelta(days=days)).date().isoformat()
    return sum(int(rec.get("total", 0)) for day, rec in (_load(st).get("days") or {}).items() if day >= cut)


def dynamic_topics(st: State, now: datetime, days: int = 2) -> list[dict]:
    """«Історії дня» з опитувань останніх `days` діб як теми для «Топ-рейтингу» (kind=story)."""
    out = []
    cut = (now - timedelta(days=days)).date().isoformat()
    for day, rec in (_load(st).get("days") or {}).items():
        if day >= cut:
            for tid, sp in (rec.get("dynamic") or {}).items():
                out.append({"id": tid, "title": sp["title"], "kind": "story", "links": sp.get("links", []), "tokens": sp.get("tokens", [])})
    return out


def story_options(st: State, now: datetime, n: int) -> list[dict]:
    """Головні історії дня: заголовки постів, що вийшли за останню добу (без повторів за змістом), із посиланнями й словами для пошуку в стрічках."""
    if n <= 0:
        return []
    start = now - timedelta(hours=24)
    pub = {e.get("headline"): e for e in st.published}
    out: list[dict] = []
    for ev in reversed(st.events()):
        if ev.get("kind") != "sent" or datetime.fromisoformat(ev["t"]) < start:
            continue
        h = ev["headline"]
        e = pub.get(h)
        if not e or any(similar_headlines(h, o["title"]) for o in out):
            continue
        out.append({"title": h, "links": e.get("links", []), "tokens": e.get("tokens", [])})
        if len(out) >= n:
            break
    return out


def build_options(st: State, now: datetime, cfg: dict) -> tuple[list[dict], dict]:
    """Варіанти для сьогоднішнього опитування у випадковому (але щодня іншому) порядку; і описи «історій дня» за їхніми id."""
    day = now.astimezone(ZoneInfo(TZ)).date().isoformat()
    opts = [{"id": t["id"], "text": t["option"][:100]} for t in cfg["topics"] if t.get("poll", True)]
    dyn = {}
    for i, s in enumerate(story_options(st, now, cfg["poll"].get("dynamic", 3)), 1):
        sid = f"story-{day}-{i}"
        title = s["title"] if len(s["title"]) <= 90 else s["title"][:89].rstrip() + "…"
        opts.append({"id": sid, "text": f"Історія дня: {title}"[:100]})
        dyn[sid] = s
    random.Random(day).shuffle(opts)
    return opts, dyn


def close(st: State, token: str, chat: str, api=publish.api) -> str:
    d = _load(st)
    o = d.get("open")
    if not o:
        return "відкритого опитування немає"
    try:
        res = api("stopPoll", token, {"chat_id": chat, "message_id": o["message_id"]}).get("result", {})
    except SystemExit as exc:
        d["open"] = None  # опитування недоступне (видалене тощо): не застрягаємо на ньому
        _save(st, d)
        return f"не вдалося закрити: {exc}"
    counts = {}
    for tid, opt in zip(o["order"], res.get("options", [])):
        counts[tid] = int(opt.get("voter_count", 0))
    d.setdefault("days", {})[o["day"]] = {"counts": counts, "total": int(res.get("total_voter_count", 0)), "dynamic": o.get("dynamic", {})}
    d["open"] = None
    _save(st, d)
    return f"закрито: голосів {res.get('total_voter_count', 0)}"


def send(st: State, now: datetime, token: str, chat: str, cfg: dict, api=publish.api) -> str:
    opts, dyn = build_options(st, now, cfg)
    day = now.astimezone(ZoneInfo(TZ)).date().isoformat()
    spec = {"title": "Які теми вас цікавлять?", "subtitle": "Голосуйте · Топ-рейтинг сьогодні о 21:00", "kind": "poll"}
    d = _load(st)
    d["sent_day"] = day  # відмічаємо до відправлення: краще пропустити день, ніж надіслати двічі
    _save(st, d)
    try:
        deliver.send_card_text(token, chat, spec, "")
        res = api("sendPoll", token, {"chat_id": chat, "question": cfg["poll"]["question"][:300], "options": json.dumps([o["text"] for o in opts], ensure_ascii=False),
                                      "is_anonymous": "true", "allows_multiple_answers": "true"})
    except SystemExit as exc:
        return f"не вдалося надіслати: {exc}"
    d = _load(st)
    d["open"] = {"message_id": res["result"]["message_id"], "day": day, "order": [o["id"] for o in opts], "dynamic": dyn}
    _save(st, d)
    return "опитування надіслано"


def _at(now_local: datetime, hm) -> bool:
    return (now_local.hour, now_local.minute) >= tuple(hm)


def tick(st: State, now: datetime, cfg: dict | None = None, api=publish.api, token: str | None = None, chat: str | None = None) -> str:
    cfg = cfg or load_topics()
    if st.paused():
        return "пауза"
    local = now.astimezone(ZoneInfo(TZ))
    day = local.date().isoformat()
    d = _load(st)
    o = d.get("open")
    try:
        token = token or publish.env("TELEGRAM_BOT_TOKEN")
        chat = chat or publish.env("TELEGRAM_CHAT_ID")
    except SystemExit as exc:
        return f"немає ключів: {exc}"
    p = cfg["poll"]
    if o and (o["day"] != day or _at(local, p["close_at"])):
        return close(st, token, chat, api)
    if not o and d.get("sent_day") != day and _at(local, p["open_from"]) and not _at(local, p["open_until"]):
        return send(st, now, token, chat, cfg, api)
    return "рано" if not o else "опитування триває"
