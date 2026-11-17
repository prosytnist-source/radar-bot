"""Крапельна подача: кожен запуск публікує НЕ БІЛЬШЕ ОДНОГО допису з черги, щоб канал жив рівномірно.
Запускати часто (наприклад, кожні 15–30 хв): python3 -m digest.drip
Правила: нічні години (23:00–07:00 за Києвом) — лише термінове (важливість ≥ 9); інтервал між постами залежить від розміру черги (15–60 хв);
застарілі (> --max-age годин) дописи відкидаються; вищу важливість — першою."""
from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import control, publish
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent
URGENT = 9


def interval_minutes(n: int) -> float:
    return min(60.0, max(15.0, 240.0 / max(n, 1)))


def choose(q: list[dict], now: datetime, last: datetime | None, tz: str = "Europe/Kyiv", night=(23, 7)) -> dict | None:
    if not q:
        return None
    urgent = [e for e in q if e["importance"] >= URGENT]
    if urgent:
        return sorted(urgent, key=lambda e: e["created"])[0]
    hour = now.astimezone(ZoneInfo(tz)).hour
    if hour >= night[0] or hour < night[1]:
        return None
    if last and now - last < timedelta(minutes=interval_minutes(len(q))):
        return None
    return sorted(q, key=lambda e: (-e["importance"], e["created"]))[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-age", type=float, default=13.0, help="скільки годин пост може чекати в черзі (вечірня порція має дожити до ранку)")
    ap.add_argument("--now", help="фіксований час UTC 'YYYY-MM-DDTHH:MM' (для перевірки)")
    ap.add_argument("--dry", action="store_true", help="лише показати, що було б надіслано")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    st = State(ROOT / "state")
    try:
        control.sync(st, publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"))
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"(команди керування недоступні: {exc})", file=sys.stderr)
    if st.paused():
        print("⏸ Пауза (/stop): нічого не публікую.")
        return 0
    full = st.load_queue()
    q = [e for e in full if now - datetime.fromisoformat(e["created"]) <= timedelta(hours=a.max_age)]
    if not a.dry:
        for e in full:
            if e not in q:
                st.log_event("expired", e["headline"], now)
    e = choose(q, now, st.last_sent())
    if not e:
        print(f"Черга: {len(q)}; зараз нічого публікувати (інтервал, ніч або порожньо).")
        if not a.dry:
            st.save_queue(q)
        return 0
    print(f"Публікую: {e['headline']} (важливість {e['importance']}); у черзі лишиться {len(q) - 1}")
    if not a.dry:
        try:
            publish.send(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID"), e["html"], e.get("preview"))
        except SystemExit as exc:
            print(f"✗ не надіслано: {exc}", file=sys.stderr)
            st.save_queue(q)  # лишаємо в черзі, спробуємо наступного разу
            return 0
        q.remove(e)
        st.set_last_sent(now)
        st.log_event("sent", e["headline"], now)
        st.save_queue(q)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
