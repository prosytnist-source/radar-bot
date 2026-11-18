import json, pathlib, tempfile, unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from digest import drip, tgwatch, watch
from digest.state import State

PAGE = '''<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="lachentyt/1">
<div class="tgme_widget_message_text js-message_text" dir="auto">Удар по <b>Кримському мосту</b>:<br/>рух зупинено &amp; дрони</div>
<a class="tgme_widget_message_date"><time datetime="2026-11-17T06:10:00+00:00" class="time">08:10</time></a></div></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="lachentyt/2">
<div class="tgme_widget_message_text js-message_text" dir="auto">Старий пост</div>
<a class="tgme_widget_message_date"><time datetime="2026-11-16T06:10:00+00:00" class="time">08:10</time></a></div></div>'''
NOW = datetime(2026, 11, 17, 6, 30, tzinfo=timezone.utc)


class V40(unittest.TestCase):
    def test_parse_and_fresh(self):
        posts = tgwatch.parse(PAGE)
        self.assertEqual(len(posts), 2)
        self.assertIn("Кримському мосту", posts[0]["text"])
        self.assertIn("& дрони", posts[0]["text"])
        self.assertEqual(len(tgwatch.fresh(posts, NOW, 90)), 1)

    def test_overlap(self):
        self.assertTrue(tgwatch.overlap("Удар по Кримському мосту та атака дронів", "Кримський міст: удар, рух зупинено"))
        self.assertFalse(tgwatch.overlap("Удар по Кримському мосту та атака дронів", "Курс долара зріс"))

    def test_urgent_expires_faster(self):
        a = Namespace(max_age=13)
        self.assertEqual(drip._limit({"importance": 9}, a), 4.0)
        self.assertEqual(drip._limit({"importance": 7}, a), 13)

    def test_tick_replaces_stale(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            old = {"created": (NOW - timedelta(hours=6)).isoformat(), "importance": 9, "headline": "Удар по Кримському мосту та атака дронів", "preview": None, "html": "x"}
            st.save_queue([old, {"created": NOW.isoformat(), "importance": 6, "headline": "Курс долара", "preview": None, "html": "y"}])
            st.published = [{"t": NOW.isoformat(), "links": [], "tokens": [], "headline": old["headline"]}]

            def refresher():
                q = st.load_queue()
                q.append({"created": NOW.isoformat(), "importance": 9, "headline": "Кримський міст зруйновано: удар дронів", "preview": None, "html": "z"})
                st.save_queue(q)
                return True

            r = watch.tick(st, NOW, {"channels": ["c"]}, fetcher=lambda ch: tgwatch.parse(PAGE), refresher=refresher)
            heads = [e["headline"] for e in st.load_queue()]
            self.assertNotIn(old["headline"], heads)
            self.assertIn("Кримський міст зруйновано: удар дронів", heads)
            self.assertEqual(st.published, [])
            self.assertIn("замінено свіжими: 1", r)
            # повторно одразу — не частіше за інтервал опитування
            self.assertEqual(watch.tick(st, NOW + timedelta(minutes=1), {"channels": ["c"]}, fetcher=lambda ch: [], refresher=refresher), "рано")

    def test_tick_keeps_old_if_refresh_fails(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            old = {"created": (NOW - timedelta(hours=6)).isoformat(), "importance": 9, "headline": "Удар по Кримському мосту та атака дронів", "preview": None, "html": "x"}
            st.save_queue([old])
            watch.tick(st, NOW, {"channels": ["c"]}, fetcher=lambda ch: tgwatch.parse(PAGE), refresher=lambda: False)
            self.assertEqual([e["headline"] for e in st.load_queue()], [old["headline"]])

    def test_channel_failure_is_harmless(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            def boom(ch): raise OSError("net")
            self.assertIn("не знайдено", watch.tick(st, NOW, {"channels": ["c"]}, fetcher=boom))


if __name__ == "__main__":
    unittest.main()


class Cheap(unittest.TestCase):
    def test_refresh_uses_no_premium(self):
        from digest import run
        self.assertEqual(run.SLOTS["refresh"]["premium"], 0)
        self.assertIn('"--polish", "0"', pathlib.Path(watch.__file__).read_text(encoding="utf-8"))


class Silence(unittest.TestCase):
    def test_no_silence_post(self):
        import time as _t
        from unittest import mock
        calls = []
        with mock.patch("digest.fixed.main", side_effect=lambda argv: calls.append(argv[1])):
            drip.fixed_tick(Namespace(), 60, _t.time() + 3000, {})
        self.assertEqual(calls, ["holiday", "rates", "fuel"])
