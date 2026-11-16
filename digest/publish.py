"""Надсилання чернеток у Telegram (Bot API, без залежностей). Токен і id чату — лише у ~/.multiview.env, ніколи в коді чи чаті.
  python3 -m digest.publish --find-chat            # показати чати, які бачить бот (після того, як написати боту / додати в канал)
  python3 -m digest.publish --test                 # надіслати тестове повідомлення
  python3 -m digest.publish --send drafts/ДАТА     # показати, що буде надіслано (нічого не шле)
  python3 -m digest.publish --send drafts/ДАТА --yes
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .llm import ENV_FILE


def env(name: str) -> str:
    import os
    v = os.environ.get(name, "").strip()
    if not v and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not v:
        raise SystemExit(f"Немає {name} у ~/.multiview.env (див. інструкцію).")
    return v


def api(method: str, token: str, params: dict | None = None) -> dict:
    data = urlencode(params).encode() if params else None
    try:
        with urlopen(Request(f"https://api.telegram.org/bot{token}/{method}", data=data), timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"Telegram: HTTP {e.code} {body.replace(token, '***')}") from None


def send(token: str, chat: str, html_text: str, preview: str | None = None) -> None:
    """preview — адреса статті: Telegram покаже над текстом її ілюстрацію з назвою видання (джерело видно одразу)."""
    params = {"chat_id": chat, "text": html_text, "parse_mode": "HTML"}
    if preview:
        params["link_preview_options"] = json.dumps({"url": preview, "prefer_large_media": True, "show_above_text": True})
    else:
        params["link_preview_options"] = json.dumps({"is_disabled": True})
    api("sendMessage", token, params)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--find-chat", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--send", help="тека з чернетками (drafts/...)")
    ap.add_argument("--yes", action="store_true", help="справді надіслати")
    ap.add_argument("--lang", default="uk")
    a = ap.parse_args(argv)
    token = env("TELEGRAM_BOT_TOKEN")
    if a.find_chat:
        seen = {}
        for u in api("getUpdates", token).get("result", []):
            m = u.get("message") or u.get("channel_post") or u.get("my_chat_member", {})
            c = m.get("chat") if isinstance(m, dict) else None
            if c:
                seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name", "")
        for cid, name in seen.items():
            print(f"{cid}\t{name}")
        if not seen:
            print("Чатів не видно: надішліть боту повідомлення (або додайте його адміністратором у канал і напишіть у каналі пост), потім повторіть.")
        return 0
    chat = env("TELEGRAM_CHAT_ID")
    if a.test:
        send(token, chat, "✅ РАДАР: тестове повідомлення від бота")
        print("Надіслано.")
        return 0
    if a.send:
        files = sorted(pathlib.Path(a.send).glob(f"*-{a.lang}.html"))
        print(f"Постів: {len(files)} → чат {chat}")
        for f in files:
            print(" ", f.name, len(f.read_text(encoding="utf-8")), "симв.")
        if not a.yes:
            print("Нічого не надіслано. Додайте --yes, щоб надіслати.")
            return 0
        for f in files:
            meta = f.with_suffix(".json")
            preview = json.loads(meta.read_text(encoding="utf-8")).get("preview") if meta.exists() else None
            send(token, chat, f.read_text(encoding="utf-8"), preview)
            time.sleep(1.5)
        print("Надіслано.")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
