"""Повне очищення каналу: видаляє всі повідомлення бота. Незворотно.
Надсилаємо службове повідомлення, щоб дізнатися останній номер, і видаляємо пакетами по 100 номерів від нього до 1.
Бот з правом публікації може видаляти власні повідомлення в каналі без обмеження за часом; те, що видалити не можна, Telegram пропускає."""
from __future__ import annotations

import argparse
import json
import sys

from . import publish

BATCH = 100


def last_id(token: str, chat: str) -> int:
    r = publish.api("sendMessage", token, {"chat_id": chat, "text": "…", "disable_notification": "true"})
    return int(r["result"]["message_id"])


def wipe(token: str, chat: str, api=publish.api, top: int | None = None) -> int:
    """Пакет із хоча б одним невидалюваним повідомленням (службовим, чужим) Telegram відхиляє цілком,
    тому при збої пакет розбираємо й видаляємо повідомлення по одному. Повертає найбільший номер."""
    n = top if top is not None else last_id(token, chat)
    deleted = skipped = 0
    for hi in range(n, 0, -BATCH):
        ids = list(range(max(hi - BATCH + 1, 1), hi + 1))
        try:
            r = api("deleteMessages", token, {"chat_id": chat, "message_ids": json.dumps(ids)})
            if r.get("ok"):
                deleted += len(ids)
                continue
        except SystemExit:
            pass
        for i in ids:  # пакет не пройшов: по одному
            try:
                r = api("deleteMessage", token, {"chat_id": chat, "message_id": i})
                if r.get("ok"):
                    deleted += 1
                else:
                    skipped += 1
            except SystemExit:
                skipped += 1  # службове повідомлення, чуже або вже видалене
    print(f"Видалено: {deleted}; пропущено (службові, чужі чи вже видалені): {skipped}", file=sys.stderr)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--confirm", default="", help='має бути рівно «ТАК, ВИДАЛИТИ»')
    a = ap.parse_args(argv)
    if a.confirm.strip() != "ТАК, ВИДАЛИТИ":
        print("Без підтвердження нічого не видалено.")
        return 1
    token, chat = publish.env("TELEGRAM_BOT_TOKEN"), publish.env("TELEGRAM_CHAT_ID")
    n = wipe(token, chat)
    print(f"Очищено канал: оброблено повідомлення з номерами 1–{n}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
