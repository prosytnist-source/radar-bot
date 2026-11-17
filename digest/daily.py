"""Вечірній звіт власнику в особисті повідомлення: що вийшло за добу, що в черзі, чи не стоїть пауза.
Запуск: python3 -m digest.daily [--dry] [--now 'YYYY-MM-DDTHH:MM' (UTC)]"""
from __future__ import annotations

import argparse
import html
import pathlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import publish
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent


def build(st: State, now: datetime, tz: str = "Europe/Kyiv") -> str:
    z = ZoneInfo(tz)
    day = now.astimezone(z).date()
    ev = [e for e in st.events() if datetime.fromisoformat(e["t"]).astimezone(z).date() == day]
    sent = [e for e in ev if e["kind"] == "sent"]
    expired = [e for e in ev if e["kind"] == "expired"]
    q = st.load_queue()
    lines = [f"<b>РАДАР · звіт за {day:%d.%m}</b>", ""]
    if st.paused():
        lines += ["⏸ <b>Пауза увімкнена</b> (/start — щоб відновити)", ""]
    lines.append(f"Опубліковано сьогодні: <b>{len(sent)}</b>")
    for e in sent[-12:]:
        t = datetime.fromisoformat(e["t"]).astimezone(z)
        lines.append(f"• {t:%H:%M} {html.escape(e['headline'][:90], quote=False)}")
    if expired:
        lines.append(f"Не встигли вийти й застаріли: {len(expired)}")
    lines.append(f"У черзі на завтра: {len(q)}")
    if not sent and not st.paused():
        lines += ["", "⚠️ Сьогодні жодного поста: перевірте Actions на GitHub (помилки, квота Gemini)."]
    return "\n".join(lines)[:4000]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--now")
    ap.add_argument("--dry", action="store_true", help="показати звіт, не надсилати")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    text = build(State(ROOT / "state"), now)
    if a.dry:
        print(text)
        return 0
    publish.send(publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID"), text)
    print("Звіт надіслано.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
