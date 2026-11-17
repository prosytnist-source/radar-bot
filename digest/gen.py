"""Свіжа порція в чергу зсередини безперервного циклу (cron GitHub запізнюється на десятки хвилин, цей цикл працює майже без перерв).
Раз на `every` хвилин удень (ввечері й уночі рідше) запускає невеликий запуск `--slot hourly` на запасній моделі; не додає, якщо черга й так повна."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .state import State

MAX_QUEUE = 5  # якщо в черзі вже стільки, нових не генеруємо: вони лише застарівали б


def _path(st: State):
    return st.dir / "gen.json"


def _load(st: State) -> dict:
    try:
        return json.loads(_path(st).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run_hourly() -> bool:
    try:
        r = subprocess.run([sys.executable, "-m", "digest.run", "--slot", "hourly", "--synth", "--enqueue", "--polish", "0"], timeout=600)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"(генерація не вдалася: {exc})", file=sys.stderr)
        return False


def tick(st: State, now: datetime, every: float, runner=run_hourly, tz: str = "Europe/Kyiv") -> str:
    if st.paused():
        return "пауза"
    hour = now.astimezone(ZoneInfo(tz)).hour
    gap = timedelta(minutes=every * (3 if (hour >= 23 or hour < 7) else 1))  # вночі рідше: публікується лише термінове
    d = _load(st)
    last = datetime.fromisoformat(d["last"]) if d.get("last") else None
    if last and now - last < gap:
        return "рано"
    n = len(st.load_queue())
    if n >= MAX_QUEUE:
        return f"у черзі вже {n}"
    _path(st).write_text(json.dumps({"last": now.isoformat()}), encoding="utf-8")
    ok = runner()
    return f"порція {'ок' if ok else 'не вдалась'}; було в черзі {n}"
