"""Зупинка й запуск каналу командами в особистих повідомленнях боту: /stop, /start, /status.
Слухаємо лише власника (TELEGRAM_OWNER_ID у ~/.multiview.env). Локально: python3 -m digest.control --stop | --start | --status | --sync"""
from __future__ import annotations

import argparse
import pathlib

from . import publish
from .state import State

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sync(state: State, token: str, owner: str) -> list[str]:
    """Читає нові повідомлення боту, виконує команди власника, відповідає. Повертає виконані команди."""
    off_file = state.dir / "offset.txt"
    offset = int(off_file.read_text()) if off_file.exists() else 0
    res = publish.api("getUpdates", token, {"offset": offset, "timeout": 0}).get("result", [])
    done = []
    for u in res:
        offset = max(offset, u["update_id"] + 1)
        m = u.get("message")
        if not m or str(m.get("from", {}).get("id")) != str(owner):
            continue
        text = (m.get("text") or "").strip().lower().split("@")[0]
        reply = None
        if text == "/stop":
            state.set_paused(True)
            reply = "⏸ Канал на паузі: нові пости не публікуються. Відновити: /start"
        elif text == "/start":
            state.set_paused(False)
            reply = "▶️ Канал працює."
        elif text == "/status":
            reply = "⏸ Пауза" if state.paused() else "▶️ Працює"
            reply += f" · у черзі: {len(state.load_queue())} · опубліковано за 3 доби: {len(state.published)}"
        if reply:
            done.append(text)
            publish.api("sendMessage", token, {"chat_id": m["chat"]["id"], "text": reply})
    off_file.write_text(str(offset))
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sync", action="store_true", help="виконати команди з Telegram")
    a = ap.parse_args(argv)
    st = State(ROOT / "state")
    if a.stop:
        st.set_paused(True)
    if a.start:
        st.set_paused(False)
    if a.sync:
        print("Команди:", sync(st, publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_OWNER_ID")) or "немає")
    print("⏸ ПАУЗА" if st.paused() else "▶️ Працює", f"· записів про публікації: {len(st.published)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
