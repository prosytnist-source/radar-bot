import json
import pathlib
import unittest
from datetime import datetime, timezone

from digest import focus, rank, synth, telegram_fmt
from digest.cluster import Cluster
from digest.fetch import Item

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
ROOT = pathlib.Path(__file__).resolve().parent.parent


def item(sid, title, summary="", country="", mins=10):
    from datetime import timedelta
    return Item(sid, sid, title, f"https://{sid}.x/a", summary, NOW - timedelta(minutes=mins), country=country)


class Focus(unittest.TestCase):
    cfg = {"focus": {"require": ["ukrain", "kyiv"]}}

    def test_keeps_only_ukraine(self):
        its = [item("a", "Kyiv hit by drones"), item("b", "Budget vote in Paris"), item("c", "Talks", "on Ukrainian grain")]
        self.assertEqual([i.source_id for i in focus.apply(its, self.cfg)], ["a", "c"])

    def test_no_config_keeps_all(self):
        its = [item("a", "x")]
        self.assertEqual(focus.apply(its, {}), its)

    def test_sources_file_valid(self):
        d = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        ids = [s["id"] for s in d["sources"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(d["focus"]["require"])
        for s in d["sources"]:
            self.assertTrue(s["feed"].startswith("http"))
        on = {s["country"] for s in d["sources"] if s.get("enabled", True)}
        for c in ("China", "Japan", "Turkey", "USA", "Germany"):
            self.assertIn(c, on)


class Countries(unittest.TestCase):
    def test_diversity_beats_count(self):
        same = Cluster(items=[item("a", "Kyiv talks", country="UK"), item("b", "Kyiv talks", country="UK"), item("c", "Kyiv talks", country="UK")], vec={})
        mixed = Cluster(items=[item("a", "Kyiv talks", country="UK"), item("b", "Kyiv talks", country="Japan"), item("c", "Kyiv talks", country="Turkey")], vec={})
        r = rank.rank([same, mixed], NOW, "day", 2, 5)
        self.assertEqual(r[0].countries, 3)
        self.assertGreater(r[0].score, r[1].score)


class Format(unittest.TestCase):
    def test_flags_and_country_names(self):
        self.assertEqual(telegram_fmt._flags([{"country": "Japan"}, {"country": "Japan"}, {"country": "USA"}]), "🇯🇵 🇺🇸")
        src = {"country": "China", "type": "state", "caution": "x"}
        self.assertIn("Китай", telegram_fmt._tag(src, "uk"))
        self.assertIn("⚠️", telegram_fmt._tag(src, "uk"))

    def test_prompt_has_focus(self):
        p = synth.system_for(("uk",), batch=True)
        self.assertIn("ABOUT UKRAINE", p)
        self.assertIn("at most 5 outlets", p)


if __name__ == "__main__":
    unittest.main()
