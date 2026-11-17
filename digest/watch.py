"""Ранній сигнал із телеграм-каналів. Якщо свіжий пост каналу стосується теми, що вже давно чекає в черзі, —
позначаємо її застарілою й запускаємо позачергове оновлення з RSS (не частіше за refresh_gap_minutes).
Стару версію прибираємо лише тоді, коли з'явилась свіжа про те саме; інакше вона піде в канал як є."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta

from . import tgwatch
from .state import State, similar_headlines

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_cfg(path: pathlib.Path | None = None) -> dict:
    try:
        return json.loads((path or ROOT / "watch.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run_refresh() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "digest.run", "--slot", "refresh", "--synth", "--enqueue", "--polish", "0"], cwd=ROOT, timeout=600)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"(оновлення не вдалося: {exc})", file=sys.stderr)
        return False


def _load(st: State) -> dict:
    try:
        return json.loads((st.dir / "watch.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(st: State, d: dict) -> None:
    (st.dir / "watch.json").write_text(json.dumps(d), encoding="utf-8")


def tick(st: State, now: datetime, cfg: dict, fetcher=tgwatch.fetch_channel, refresher=run_refresh) -> str:
    """Один крок спостереження. Повертає короткий опис для журналу."""
    if not cfg.get("channels"):
        return "канали не задано"
    w = _load(st)
    last_poll = datetime.fromisoformat(w["last_poll"]) if w.get("last_poll") else None
    if last_poll and now - last_poll < timedelta(minutes=cfg.get("poll_minutes", 10)):
        return "рано"
    w["last_poll"] = now.isoformat()
    posts = []
    for ch in cfg["channels"]:
        try:
            posts += tgwatch.fresh(fetcher(ch), now, cfg.get("fresh_minutes", 90))
        except Exception as exc:  # noqa: BLE001
            print(f"(канал {ch} недоступний: {exc})", file=sys.stderr)
    _save(st, w)
    q = st.load_queue()
    old = timedelta(hours=cfg.get("stale_hours", 2))
    hit = [e for e in q if now - datetime.fromisoformat(e["created"]) > old and any(tgwatch.overlap(e["headline"], p["text"]) for p in posts)]
    if not hit:
        return f"свіжих постів: {len(posts)}; застарілих тем не знайдено"
    gap = timedelta(minutes=cfg.get("refresh_gap_minutes", 120))
    last_ref = datetime.fromisoformat(w["last_refresh"]) if w.get("last_refresh") else None
    if last_ref and now - last_ref < gap:
        return f"застарілих тем: {len(hit)}, але оновлення було нещодавно"
    for e in hit:
        st.forget(e["headline"])  # інакше нову версію відкинуть як повтор
        st.log_event("tg-stale", e["headline"], now)
    w["last_refresh"] = now.isoformat()
    _save(st, w)
    before = {e["headline"] for e in q}
    ok = refresher()
    q2 = st.load_queue()
    new = [e for e in q2 if e["headline"] not in before]
    drop = {h["headline"] for h in hit if any(similar_headlines(h["headline"], n["headline"]) for n in new)}
    if drop:
        st.save_queue([e for e in q2 if e["headline"] not in drop])
        for h in drop:
            st.log_event("tg-replaced", h, now)
    return f"оновлення {'ок' if ok else 'не вдалось'}; застарілих: {len(hit)}, замінено свіжими: {len(drop)}"
