"""Форматування допису Telegram (parse_mode=HTML), українською та англійською."""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from .rank import Ranked
from .report import TYPE_LABEL

LIMIT = 4000  # ліміт Telegram 4096, лишаємо запас

T = {
    "uk": {"known": "Що відомо", "diff": "Де розходяться", "views": "Погляди видань", "asof": "Станом на", "outlets": "видань", "also": "Також пишуть", "by": "За даними {name}: ", "foot": "Підсумок складено за заголовками й анонсами з RSS; перевіряйте оригінали за посиланнями.", "single": "Це повідомляє лише одне видання: ще не підтверджено кількома джерелами."},
    "en": {"known": "What is known", "diff": "Where they differ", "views": "Outlets' views", "asof": "As of", "outlets": "outlets", "also": "Also reporting", "by": "According to {name}: ", "foot": "Summary is based on headlines and RSS snippets; check the originals via the links.", "single": "Reported by a single outlet so far: not yet confirmed by several sources."},
}
TYPE_EN = {"public": "public broadcaster", "state": "state-funded", "commercial": "commercial", "nonprofit": "non-profit", "independent_exile": "independent, in exile"}


def _outlets(n: int, lang: str) -> str:
    if lang == "uk":
        w = "видання" if n % 10 in (1, 2, 3, 4) and n % 100 not in (11, 12, 13, 14) else "видань"
        if n % 10 == 1 and n % 100 != 11:
            w = "видання"
        return f"Пишуть {n} {w}"
    return f"Reported by {n} outlet{'s' if n != 1 else ''}"


def _bul(items: list[str]) -> str:
    return "\n".join(f"• {html.escape(i, quote=False)}" for i in items)


def _tag(src: dict, lang: str) -> str:
    base = (TYPE_LABEL if lang == "uk" else TYPE_EN).get(src.get("type", ""), "")
    warn = " ⚠️" if src.get("caution") or src.get("type") in ("state", "independent_exile") else ""
    return f"{src.get('country', '')}, {base}{warn}".strip(", ")


def render_post(r: Ranked, s: dict, sources: dict[str, dict], now: datetime, lang: str, tz: str = "Europe/Kyiv") -> str:
    t = T[lang]
    off = set(s.get("off_topic", []))
    links = {i.source_id: i for i in r.cluster.items if i.source_id not in off}
    parts = [f"<b>{html.escape(s['headline'][lang], quote=False)}</b>", f"<i>{_outlets(len(links), lang)}</i>"]
    if s.get("context"):
        parts += ["", html.escape(s["context"][lang], quote=False)]
    known = []
    for k in s["known"]:
        by = links.get(k["by"]) if k.get("by") else None
        known.append((t["by"].format(name=by.source_name) if by else "") + k[lang])
    if known:
        parts += ["", f"<b>{t['known']}</b>", _bul(known)]
    if s["differences"]:
        parts += ["", f"<b>{t['diff']}</b>", _bul([d[lang] for d in s["differences"]])]
    views = []
    for o in s["outlets"]:
        it = links.get(o["id"])
        if not it:
            continue
        src = sources.get(o["id"], {})
        views.append(f'• <a href="{html.escape(it.link, quote=True)}">{html.escape(it.source_name, quote=False)}</a> ({html.escape(_tag(src, lang), quote=False)}): {html.escape(o[lang], quote=False)}')
    if views:
        parts += ["", f"<b>{t['views']}</b>", "\n".join(views)]
    listed = {o["id"] for o in s["outlets"] if o["id"] in links}
    rest, seen = [], set()
    for it in sorted(links.values(), key=lambda i: i.published, reverse=True):
        if it.source_id in listed or it.source_id in seen:
            continue
        seen.add(it.source_id)
        src = sources.get(it.source_id, {})
        rest.append(f'<a href="{html.escape(it.link, quote=True)}">{html.escape(it.source_name, quote=False)}</a>')
    if rest:
        parts += ["", f"<b>{t['also']}:</b> " + " · ".join(rest)]
    cav = list(s["caveats"][lang])
    if r.single_source:
        cav.insert(0, t["single"])
    if cav:
        parts += ["", "⚠️ " + "\n⚠️ ".join(html.escape(c, quote=False) for c in cav)]
    text = "\n".join(parts)
    if len(text) > LIMIT:  # скорочуємо перелік поглядів, а не обрізаємо посеред тегу
        while views and len("\n".join(parts)) > LIMIT:
            views.pop()
            idx = parts.index(f"<b>{t['views']}</b>")
            parts[idx + 1] = "\n".join(views)
        text = "\n".join(parts)
    return text


def render_digest(d: dict, rs: list[Ranked], sources: dict[str, dict], now: datetime, tz: str = "Europe/Kyiv") -> str:
    """Вечірній підсумок дня (лише українською). Кожен пункт має посилання на видання, що його підтверджує."""
    link = {}
    for r in rs:
        for i in r.cluster.items:
            link.setdefault(i.source_id, i)
    parts = [f"<b>{html.escape(d['headline'], quote=False)}</b>", f"<i>Підсумок дня · {now.astimezone(ZoneInfo(tz)):%d.%m}</i>", ""]
    for p in d["points"]:
        it = link.get(p["by"])
        src = f' (<a href="{html.escape(it.link, quote=True)}">{html.escape(it.source_name, quote=False)}</a>)' if it else ""
        parts.append(f"• {html.escape(p['uk'], quote=False)}{src}")
    if d.get("watch"):
        parts += ["", f"<b>Що далі:</b> {html.escape(d['watch'], quote=False)}"]
    return "\n".join(parts)[:LIMIT]
