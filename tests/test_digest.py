import json
import pathlib
import unittest
from datetime import datetime, timezone

from digest.cluster import cluster_items, tokens
from digest.fetch import clean, parse_date, parse_feed
from digest.rank import rank
from digest.report import render
from digest.run import main

FX = pathlib.Path(__file__).parent / "fixtures"
SRC = {s["id"]: s for s in json.loads((pathlib.Path(__file__).parent.parent / "sources.json").read_text(encoding="utf-8"))["sources"]}
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def load():
    items = []
    for f in FX.glob("*.xml"):
        items += parse_feed(f.read_bytes(), f.stem, SRC[f.stem]["name"])
    return items


class Parse(unittest.TestCase):
    def test_rss_and_atom(self):
        self.assertEqual(len(parse_feed((FX / "bbc.xml").read_bytes(), "bbc", "BBC")), 3)
        a = parse_feed((FX / "meduza.xml").read_bytes(), "meduza", "Meduza")
        self.assertEqual(a[0].link, "https://meduza.example/1")
        self.assertNotIn("<p>", a[0].summary)

    def test_dates_and_clean(self):
        self.assertEqual(parse_date("Tue, 10 Nov 2026 14:30:00 GMT").hour, 14)
        self.assertEqual(parse_date("2026-11-10T16:00:00Z").hour, 16)
        self.assertIsNone(parse_date("вчора"))
        self.assertEqual(clean("<b>A&amp;B</b>  x"), "A&B x")

    def test_item_without_date_skipped(self):
        xml = b"<rss><channel><item><title>T</title><link>http://x</link></item></channel></rss>"
        self.assertEqual(parse_feed(xml, "x", "X"), [])

    def test_tokens(self):
        self.assertNotIn("the", tokens("The talks"))


class Cluster(unittest.TestCase):
    def test_same_event_grouped_others_apart(self):
        cl = cluster_items(load())
        big = max(cl, key=lambda c: len(c.sources))
        self.assertGreaterEqual(len(big.sources), 4)  # BBC, AJ, Meduza, KI
        titles = " ".join(i.title for c in cl if c is not big for i in c.items)
        self.assertIn("Russell Brand", titles)
        self.assertNotIn("Abu Dhabi", titles)


class Ranking(unittest.TestCase):
    def test_window_and_order(self):
        cl = cluster_items(load())
        week = rank(cl, NOW, "week")
        self.assertIn("Abu Dhabi", week[0].cluster.items[0].title)
        self.assertEqual(week[0].sources, 4)
        day = rank(cl, NOW, "day")
        flat = " ".join(i.title for r in day for i in r.cluster.items)
        self.assertNotIn("Old story", flat)  # поза вікном
        self.assertNotIn("Russell", flat)  # понад 24 год

    def test_single_source_flagged_and_last(self):
        r = rank(cluster_items(load()), NOW, "week")
        self.assertFalse(r[0].single_source)
        self.assertTrue(r[-1].single_source)


class Soft(unittest.TestCase):
    def test_entertainment_ranks_below_politics(self):
        from digest.fetch import Item
        t = datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)
        items = [Item(s, s, "Pattinson named new James Bond actor", f"https://{s}.x/culture/bond", "", t) for s in "abcd"]
        items += [Item(s, s, "Parliament passes budget reform bill", f"https://{s}.x/politics/budget", "", t) for s in "ab"]
        r = rank(cluster_items(items), NOW, "day")
        self.assertIn("budget", r[0].cluster.items[0].title)
        self.assertTrue(r[1].soft)


class Report(unittest.TestCase):
    def test_labels_and_links(self):
        text = render(rank(cluster_items(load()), NOW, "week"), SRC, NOW, window="week")
        self.assertIn("https://aj.example/1", text)
        self.assertIn("державне фінансування", text)
        self.assertIn("потребують перевірки", text)  # обережність щодо Meduza
        self.assertIn("лише одне видання", text)


class Cli(unittest.TestCase):
    def test_runs_offline(self):
        out = pathlib.Path(__file__).parent / "out.md"
        try:
            self.assertEqual(main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--out", str(out)]), 0)
            self.assertIn("Abu Dhabi", out.read_text(encoding="utf-8"))
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
