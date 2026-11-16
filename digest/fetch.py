"""Завантаження й розбір RSS/Atom без зовнішніх залежностей."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen

USER_AGENT = "MultiviewBot/0.1 (+RSS reader; contact: see repository)"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_IMG = re.compile(r"""<img[^>]+src=["'](https?://[^"']+)["']""", re.I)
MEDIA_NS = "{http://search.yahoo.com/mrss/}"


@dataclass
class Item:
    source_id: str
    source_name: str
    title: str
    link: str
    summary: str
    published: datetime  # завжди з часовим поясом (UTC)
    image: str = ""  # адреса ілюстрації з RSS (media:thumbnail/content, enclosure або <img>), якщо є


def clean(text: str | None) -> str:
    if not text:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()


def parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    dt = None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    if dt is None:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _image(el, fields: dict) -> str:
    """Перша придатна ілюстрація запису: media:*, enclosure, потім <img> в анонсі. Лише http(s)."""
    for sub in el.iter():
        url = sub.get("url") or ""
        if not url.startswith("http"):
            continue
        name = _local(sub.tag)
        typ = (sub.get("type") or "").lower()
        if sub.tag.startswith(MEDIA_NS) and (name == "thumbnail" or sub.get("medium") == "image" or typ.startswith("image")):
            return url
        if name == "enclosure" and typ.startswith("image"):
            return url
    for key in ("description", "summary", "content", "encoded"):
        m = _IMG.search(html.unescape(fields.get(key) or ""))
        if m:
            return m.group(1)
    return ""


def parse_feed(xml_bytes: bytes, source_id: str, source_name: str) -> list[Item]:
    """Розбирає RSS 2.0 / RDF / Atom. Записи без дати пропускаються: свіжість не можна перевірити."""
    root = ET.fromstring(xml_bytes)
    items: list[Item] = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f: dict[str, str] = {}
        link = ""
        for ch in el:
            name = _local(ch.tag)
            if name == "link":
                href = ch.get("href")
                if href:
                    if ch.get("rel") in (None, "alternate"):
                        link = link or href
                else:
                    link = link or (ch.text or "").strip()
            elif name in ("title", "description", "summary", "content", "encoded", "pubdate", "published", "updated", "date"):
                f.setdefault(name, ch.text or "")
        image = _image(el, f)
        published = parse_date(f.get("pubdate") or f.get("published") or f.get("date") or f.get("updated"))
        title = clean(f.get("title"))
        if not published or not title or not link:
            continue
        summary = clean(f.get("description") or f.get("summary") or f.get("content"))
        items.append(Item(source_id, source_name, title, link, summary[:600], published, image))
    return items


def fetch_one(source: dict, timeout: int = 15) -> tuple[list[Item], str | None]:
    """Повертає (записи, помилка). Збій одного видання не зупиняє решту."""
    try:
        req = Request(source["feed"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, */*"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — адреси беруться з нашого sources.json
            data = resp.read()
        return parse_feed(data, source["id"], source["name"]), None
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def fetch_all(sources: list[dict], workers: int = 8) -> tuple[list[Item], dict[str, str]]:
    items: list[Item] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for src, (got, err) in zip(sources, pool.map(fetch_one, sources)):
            if err:
                errors[src["id"]] = err
            items.extend(got)
    return items, errors
