"""Повний текст статті для вечірнього огляду: аналіз має спиратися на сам матеріал, а не на анонс з RSS.
Лише стандартна бібліотека: збираємо абзаци <p> (краще всередині <article>), відкидаємо меню, підвали й рекламу."""
from __future__ import annotations

import html
import re
import sys
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from .fetch import USER_AGENT

SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "figure", "svg", "iframe", "button", "template"}
MIN_PARA = 40
MAX_CHARS = 6500
_WS = re.compile(r"\s+")
_JUNK = re.compile(r"(subscribe|sign up|newsletter|cookie|all rights reserved|follow us|read more|advertisement|підписуйтесь|copyright)", re.I)


class _Paras(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.art = 0
        self.cur: list[str] | None = None
        self.in_art: list[str] = []
        self.anywhere: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag == "article":
            self.art += 1
        elif tag == "p" and not self.skip:
            self.cur = []

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag == "article" and self.art:
            self.art -= 1
        elif tag == "p" and self.cur is not None:
            text = _WS.sub(" ", html.unescape("".join(self.cur))).strip()
            self.cur = None
            if len(text) >= MIN_PARA and not _JUNK.search(text):
                self.anywhere.append(text)
                if self.art:
                    self.in_art.append(text)

    def handle_data(self, data):
        if self.cur is not None and not self.skip:
            self.cur.append(data)


def extract(page: str, max_chars: int = MAX_CHARS) -> str:
    """Текст статті з HTML. Порожній рядок, якщо схоже на стіну оплати чи на сторінку без тексту."""
    p = _Paras()
    try:
        p.feed(page)
    except Exception:  # noqa: BLE001 — зламана розмітка не повинна валити весь вечір
        pass
    paras = p.in_art if sum(map(len, p.in_art)) >= 600 else p.anywhere
    seen, out, total = set(), [], 0
    for t in paras:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return "\n".join(out)[:max_chars]


def fetch_page(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en,uk;q=0.8"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — адреси беремо з RSS наших джерел
        raw = resp.read(2_500_000)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


def fetch_text(url: str, min_chars: int = 800, get=fetch_page) -> str:
    try:
        text = extract(get(url))
    except Exception as exc:  # noqa: BLE001
        print(f"  (стаття недоступна: {url[:70]} — {type(exc).__name__})", file=sys.stderr)
        return ""
    return text if len(text) >= min_chars else ""
