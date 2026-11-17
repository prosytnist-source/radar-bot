import json
import pathlib
import tempfile
import unittest
from unittest import mock

from digest import llm, run, synth, telegram_fmt
from digest.cluster import cluster_items
from digest.rank import rank
from test_digest import FX, NOW, SRC, load

EV = lambda i, q: {"id": i, "quote": q}
GOOD = {
    "category": "war", "region": "Ukraine-Russia", "importance": 9,
    "headline": {"uk": "Переговори в Абу-Дабі <тест>", "en": "Abu Dhabi talks"},
    "known": [
        {"uk": "Переговори тривають", "en": "Talks continue", "evidence": [EV("bbc", "peace talks in Abu Dhabi"), EV("aljazeera", "Trilateral talks in Abu Dhabi")]},
        {"uk": "Другий день: обмін полоненими", "en": "Day two: prisoners", "evidence": [EV("kyivindependent", "focuses on prisoner exchange")]},
        {"uk": "Вигадка", "en": "Invented", "evidence": [EV("bbc", "this text is not in the feed at all")]},
    ],
    "differences": [
        {"uk": "Росія: безпека Європи", "en": "Russia: European security", "evidence": [EV("meduza", "postwar European security"), EV("bbc", "peace talks in Abu Dhabi")]},
        {"uk": "Лише одна сторона", "en": "One side", "evidence": [EV("meduza", "postwar European security")]},
    ],
    "outlets": [
        {"id": "bbc", "uk": "Пише про початок", "en": "Reports opening", "quote": "talks between Russia and Ukraine opened"},
        {"id": "invented", "uk": "x", "en": "x", "quote": "some invented quote here"},
        {"id": "meduza", "uk": "x", "en": "x", "quote": "completely made up phrase here"},
    ],
    "caveats": {"uk": ["Одне анонімне джерело"], "en": ["One anonymous source"]},
}


def top():
    return rank(cluster_items(load()), NOW, "week")


def parsed(data=GOOD, r=None):
    return synth.parse_synthesis(json.dumps(data), synth.texts_for(r or top()[0]))


class Parse(unittest.TestCase):
    def test_unsupported_claims_dropped(self):
        s = parsed()
        self.assertEqual([k["uk"] for k in s["known"]], ["Переговори тривають", "Другий день: обмін полоненими"])
        self.assertIsNone(s["known"][0]["by"])  # підтверджено двома
        self.assertEqual(s["known"][1]["by"], "kyivindependent")  # одне видання → «за даними»
        self.assertEqual(len(s["differences"]), 1)  # друга без двох сторін
        self.assertEqual([o["id"] for o in s["outlets"]], ["bbc"])
        self.assertEqual(s["dropped"], 4)

    def test_fenced_json(self):
        s = synth.parse_synthesis("```json\n" + json.dumps(GOOD) + "\n```", synth.texts_for(top()[0]))
        self.assertEqual(s["importance"], 9)

    def test_bad_inputs(self):
        with self.assertRaises(synth.BadSynthesis):
            synth.parse_synthesis("не json", {})
        with self.assertRaises(synth.BadSynthesis):
            parsed(dict(GOOD, headline={"uk": "", "en": "x"}))

    def test_defaults_clamped(self):
        s = parsed(dict(GOOD, importance=99, category="weird"))
        self.assertEqual((s["importance"], s["category"]), (10, "other"))

    def test_short_quote_rejected(self):
        d = dict(GOOD, known=[{"uk": "a", "en": "a", "evidence": [EV("bbc", "Abu Dhabi")]}])
        self.assertEqual(parsed(d)["known"], [])


class Select(unittest.TestCase):
    def test_soft_excluded_and_region_cap(self):
        r = top()[0]
        mk = lambda cat, reg, imp: (r, parsed(dict(GOOD, category=cat, region=reg, importance=imp, headline={"uk": "Подія " + chr(1040 + imp) * 6 + " " + chr(1072 + imp) * 7, "en": "Unique event " + chr(97 + imp)})))
        syn = [mk("culture", "UK", 10), mk("war", "Asia", 8), mk("war", "Asia", 7), mk("war", "Asia", 6), mk("politics", "Africa", 5)]
        got = synth.select(syn, top=5, max_per_region=2)
        self.assertEqual([s["region"] for _, s in got], ["asia", "asia", "africa"])
        self.assertEqual(len(synth.select(syn, top=5, max_per_region=2, include_soft=True)), 4)


class Render(unittest.TestCase):
    def test_post_escapes_and_uses_our_links(self):
        r = top()[0]
        s = parsed()
        text = telegram_fmt.render_post(r, s, SRC, NOW, "uk")
        self.assertIn("&lt;тест&gt;", text)
        self.assertIn('href="https://bbc.example/1"', text)
        self.assertNotIn("перевіряйте оригінали", text)
        self.assertNotIn("Станом на", text)
        self.assertIn("За даними Kyiv Independent: Другий день", text)
        self.assertNotIn("Вигадка", text)
        s2 = dict(s, caveats={"uk": ["пов'язаний із Alibaba"], "en": ["x"]})
        self.assertNotIn("&#x27;", telegram_fmt.render_post(r, s2, SRC, NOW, "uk"))
        self.assertIn("Where they differ", telegram_fmt.render_post(r, s, SRC, NOW, "en"))

    def test_other_outlets_listed_as_links(self):
        r = top()[0]
        text = telegram_fmt.render_post(r, parsed(), SRC, NOW, "uk")
        self.assertIn("Також пишуть", text)
        self.assertIn("https://aj.example/1", text)
        self.assertEqual(text.count("https://bbc.example/1"), 1)

    def test_length_limit(self):
        r = top()[0]
        s = parsed()
        s["outlets"] = [{"id": "bbc", "uk": "я" * 3000, "en": "x"}]
        self.assertLessEqual(len(telegram_fmt.render_post(r, s, SRC, NOW, "uk")), 4096)

    def test_single_source_warning(self):
        r = top()[-1]
        self.assertIn("лише одне видання", telegram_fmt.render_post(r, parsed(), SRC, NOW, "uk"))


class Pipeline(unittest.TestCase):
    SRCFILE = str(pathlib.Path(__file__).parent.parent / "sources.json")

    def test_run_with_fake_model(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", return_value=json.dumps(GOOD)), mock.patch.object(run, "ROOT", pathlib.Path(d)):
            code = run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--synth", "--top", "2", "--langs", "uk,en", "--sources", self.SRCFILE])
            self.assertEqual(code, 0)
            files = sorted(p.name for p in pathlib.Path(d, "drafts").rglob("*.html"))
            self.assertIn("01-uk.html", files)
            self.assertIn("01-en.html", files)

    def test_cache_avoids_second_call(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", return_value=json.dumps(GOOD)) as g, mock.patch.object(run, "ROOT", pathlib.Path(d)):
            args = ["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--synth", "--top", "1", "--sources", self.SRCFILE]
            run.main(args)
            first = g.call_count
            self.assertGreater(first, 0)
            run.main(args)
            self.assertEqual(g.call_count, first)  # друга робота: усе з кешу

    def test_fallback_model_on_429(self):
        calls = []

        def fake(system, prompt, model, key, retries=3):
            calls.append(model)
            if model == "main-m":
                raise llm.LLMError("HTTP 429: quota")
            return json.dumps(GOOD)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", side_effect=fake), mock.patch.object(run, "ROOT", pathlib.Path(d)):
            run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--synth", "--model", "main-m", "--fallback-model", "backup-m", "--sources", self.SRCFILE])
            self.assertEqual(calls[0], "main-m")
            self.assertTrue(all(c == "backup-m" for c in calls[1:]))
            self.assertGreater(len(calls), 1)

    def test_rate_limit_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", side_effect=llm.LLMError("HTTP 429: quota")), mock.patch.object(run, "ROOT", pathlib.Path(d)):
            self.assertEqual(run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--synth", "--window", "week", "--fallback-model", "", "--sources", self.SRCFILE]), 0)

    def test_503_switches_to_fallback(self):
        calls = []

        def fake(system, prompt, model, key, retries=3):
            calls.append(model)
            if model == "main-m":
                raise llm.LLMError("HTTP 503: high demand")
            return json.dumps(GOOD)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", side_effect=fake), mock.patch.object(run, "ROOT", pathlib.Path(d)):
            run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--synth", "--model", "main-m", "--fallback-model", "backup-m", "--sources", self.SRCFILE])
            self.assertIn("backup-m", calls)
            self.assertTrue(list(pathlib.Path(d, "drafts").rglob("01-uk.html")))

    def test_uk_only_by_default(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", return_value=json.dumps(dict(GOOD, headline={"uk": "Заголовок", "en": ""}))), mock.patch.object(run, "ROOT", pathlib.Path(d)):
            run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--synth", "--top", "1", "--sources", self.SRCFILE])
            names = {p.name for p in pathlib.Path(d, "drafts").rglob("*.html")}
            self.assertIn("01-uk.html", names)
            self.assertNotIn("01-en.html", names)


class Coherence(unittest.TestCase):
    def test_mixed_cluster_rejected(self):
        r = top()[0]
        with self.assertRaises(synth.BadSynthesis):
            synth.parse_synthesis(json.dumps(dict(GOOD, same_event=False)), synth.texts_for(r))

    def test_off_topic_outlet_removed_from_post(self):
        r = top()[0]
        ids = sorted({i.source_id for i in r.cluster.items})
        s = synth.parse_synthesis(json.dumps(dict(GOOD, off_topic=[ids[-1]])), synth.texts_for(r))
        self.assertEqual(s["off_topic"], [ids[-1]])
        text = telegram_fmt.render_post(r, s, SRC, NOW, "uk")
        off_link = [i.link for i in r.cluster.items if i.source_id == ids[-1]][0]
        self.assertNotIn(off_link, text)

    def test_batch_parse_per_event(self):
        rs = top()[:2]
        raw = json.dumps({"events": [dict(GOOD, event=1)]})
        out = synth.parse_batch(raw, rs)
        self.assertIsInstance(out[1][0], synth.BadSynthesis)  # події 2 немає в відповіді
        self.assertIsInstance(out[0][0], dict)

    def test_select_values_wide_coverage(self):
        a, b = top()[0], top()[1]
        sa = dict(parsed(), importance=8); sb = dict(parsed(), importance=7)
        a.sources, b.sources, b.single_source = 2, 9, False
        self.assertIs(synth.select([(a, sa), (b, sb)], 2)[0][0], b)


if __name__ == "__main__":
    unittest.main()


class Regions(unittest.TestCase):
    def test_region_normalised(self):
        self.assertEqual(synth.norm_region("Естонія-Росія"), "ukraine-russia")
        self.assertEqual(synth.norm_region("Ukraine"), "ukraine-russia")
        self.assertEqual(synth.norm_region("Mars"), "world")
        self.assertEqual(synth.norm_region("EU"), "eu")


class Slots(unittest.TestCase):
    def test_slot_sets_premium(self):
        self.assertEqual(run.SLOTS["morning"]["premium"] + run.SLOTS["noon"]["premium"] + run.SLOTS["evening"]["premium"] + run.SLOTS["digest"]["premium"], 6)

    def test_headline_as_string_accepted(self):
        r = top()[0]
        s = synth.parse_synthesis(json.dumps(dict(GOOD, headline="Просто рядок")), synth.texts_for(r), ("uk",))
        self.assertEqual(s["headline"]["uk"], "Просто рядок")

    def test_digest_needs_quotes(self):
        rs = top()[:2]
        q = rs[0].cluster.items[0]
        good = {"headline": "День", "points": [{"uk": f"п{n}", "evidence": [{"id": q.source_id, "quote": q.title}]} for n in range(3)], "watch": ""}
        d = synth.parse_digest(json.dumps(good), rs)
        self.assertEqual(len(d["points"]), 3)
        text = telegram_fmt.render_digest(d, rs, SRC, NOW)
        self.assertIn("Підсумок дня", text)
        bad = dict(good, points=[{"uk": "x", "evidence": [{"id": q.source_id, "quote": "вигадана цитата якої нема"}]}] * 3)
        with self.assertRaises(synth.BadSynthesis):
            synth.parse_digest(json.dumps(bad), rs)


class SplitByModel(unittest.TestCase):
    def test_mixed_exposes_off_ids(self):
        r = top()[0]
        ids = sorted({i.source_id for i in r.cluster.items})
        with self.assertRaises(synth.BadSynthesis) as cm:
            synth.parse_synthesis(json.dumps(dict(GOOD, same_event=False, off_topic=ids[:1], headline={"uk": "", "en": ""})), synth.texts_for(r))
        self.assertEqual(cm.exception.off, tuple(ids[:1]))


class V3(unittest.TestCase):
    def test_image_parsing(self):
        from digest.fetch import parse_feed
        xml = b'''<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>A story</title><link>https://x/1</link><description>d</description><pubDate>Tue, 10 Nov 2026 14:30:00 GMT</pubDate><media:thumbnail url="https://img/a.jpg"/></item>
<item><title>B story</title><link>https://x/2</link><description>&lt;img src="https://img/b.jpg"&gt; text</description><pubDate>Tue, 10 Nov 2026 14:30:00 GMT</pubDate></item>
<item><title>C story</title><link>https://x/3</link><description>d</description><pubDate>Tue, 10 Nov 2026 14:30:00 GMT</pubDate><enclosure url="https://img/c.png" type="image/png"/></item>
<item><title>D story</title><link>https://x/4</link><description>d</description><pubDate>Tue, 10 Nov 2026 14:30:00 GMT></pubDate></item></channel></rss>'''.replace(b"GMT></pubDate>", b"GMT</pubDate>")
        got = [i.image for i in parse_feed(xml, "s", "S")]
        self.assertEqual(got, ["https://img/a.jpg", "https://img/b.jpg", "https://img/c.png", ""])

    def test_headline_checks(self):
        r = top()[0]
        t = synth.texts_for(r)
        long = dict(GOOD, headline={"uk": "я" * 120, "en": "x"})
        with self.assertRaises(synth.BadSynthesis):
            synth.parse_synthesis(json.dumps(long), t)
        num = dict(GOOD, headline={"uk": "Загинули 9999 людей", "en": "9999 died"})
        with self.assertRaises(synth.BadSynthesis):
            synth.parse_synthesis(json.dumps(num), t)
        dot = synth.parse_synthesis(json.dumps(dict(GOOD, headline={"uk": "Заголовок.", "en": "Headline."})), t)
        self.assertEqual(dot["headline"]["uk"], "Заголовок")

    def test_context_needs_evidence(self):
        r = top()[0]
        t = synth.texts_for(r)
        q = r.cluster.items[0]
        ok = dict(GOOD, context={"uk": "Контекст", "en": "Context", "evidence": [{"id": q.source_id, "quote": q.title}]})
        self.assertEqual(synth.parse_synthesis(json.dumps(ok), t)["context"]["uk"], "Контекст")
        bad = dict(GOOD, context={"uk": "Вигадка", "en": "Fiction", "evidence": [{"id": q.source_id, "quote": "цього тексту ніде немає"}]})
        self.assertIsNone(synth.parse_synthesis(json.dumps(bad), t)["context"])

    def test_dedupe_and_pause(self):
        from digest.state import State
        r = top()[0]
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            self.assertFalse(st.is_duplicate(r, NOW))
            st.add(r, NOW, "h")
            self.assertTrue(State(pathlib.Path(d)).is_duplicate(r, NOW))
            from datetime import timedelta
            self.assertFalse(State(pathlib.Path(d)).is_duplicate(r, NOW + timedelta(days=5)))
            self.assertFalse(st.paused())
            st.set_paused(True)
            self.assertTrue(State(pathlib.Path(d)).paused())
            st.set_paused(False)
            self.assertFalse(st.paused())

    def test_control_owner_only(self):
        from digest import control
        from digest.state import State
        ups = {"result": [{"update_id": 5, "message": {"from": {"id": 111}, "chat": {"id": 111}, "text": "/stop"}},
                          {"update_id": 6, "message": {"from": {"id": 999}, "chat": {"id": 999}, "text": "/start"}}]}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(control.publish, "api", side_effect=[ups, {}]) as api:
            st = State(pathlib.Path(d))
            self.assertEqual(control.sync(st, "t", "111"), ["/stop"])
            self.assertTrue(st.paused())
            self.assertEqual((pathlib.Path(d) / "offset.txt").read_text(), "7")

    def test_paused_run_does_nothing(self):
        from digest.state import State
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "ROOT", pathlib.Path(d)), \
             mock.patch.object(run.control, "sync", return_value=[]), mock.patch.object(llm, "generate_json") as g:
            State(pathlib.Path(d, "state")).set_paused(True)
            self.assertEqual(run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--synth", "--publish", "--window", "week", "--sources", Pipeline.SRCFILE]), 0)
            g.assert_not_called()

    def test_publish_uses_preview(self):
        from digest import publish
        with mock.patch.object(publish, "api") as api:
            publish.send("t", "c", "<b>x</b>", "https://site/a")
            params = api.call_args[0][2]
            self.assertIn("https://site/a", params["link_preview_options"])
            self.assertIn("show_above_text", params["link_preview_options"])


class Drip(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        self.t = lambda h, m=0: datetime(2026, 11, 17, h, m, tzinfo=timezone.utc)  # Київ = UTC+2
        self.mk = lambda imp, at: {"created": at.isoformat(), "importance": imp, "headline": f"h{imp}", "html": "x", "preview": None}

    def test_night_blocks_normal_but_not_urgent(self):
        from digest import drip
        night = self.t(22)  # 00:00 за Києвом
        self.assertIsNone(drip.choose([self.mk(7, night)], night, None))
        self.assertEqual(drip.choose([self.mk(9, night)], night, None)["importance"], 9)

    def test_interval_and_priority(self):
        from digest import drip
        now = self.t(10)
        q = [self.mk(6, now), self.mk(8, now)]
        self.assertEqual(drip.choose(q, now, None)["importance"], 8)
        from datetime import timedelta
        self.assertIsNone(drip.choose(q, now, now - timedelta(minutes=5)))
        self.assertIsNotNone(drip.choose(q, now, now - timedelta(minutes=70)))

    def test_one_per_run_and_expiry(self):
        from digest import drip
        from digest.state import State
        now = self.t(10)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(drip, "ROOT", pathlib.Path(d)), \
             mock.patch.object(drip.control, "sync", return_value=[]), mock.patch.object(drip.publish, "env", return_value="v"), \
             mock.patch.object(drip.publish, "send") as send:
            from datetime import timedelta
            st = State(pathlib.Path(d, "state"))
            st.save_queue([self.mk(7, now), self.mk(7, now), self.mk(5, now - timedelta(hours=14))])
            drip.main(["--now", "2026-11-17T10:00"])
            self.assertEqual(send.call_count, 1)
            self.assertEqual(len(State(pathlib.Path(d, "state")).load_queue()), 1)  # одну надіслано, прострочену відкинуто
            drip.main(["--now", "2026-11-17T10:05"])  # інтервал ще не минув
            self.assertEqual(send.call_count, 1)


class SameStory(unittest.TestCase):
    def test_similar_headlines(self):
        from digest.state import similar_headlines as sim
        self.assertTrue(sim("ООН та представники країн обговорюють правила щодо автономної зброї", "ООН розпочала переговори щодо регулювання автономної зброї"))
        self.assertFalse(sim("Атака безпілотників пошкодила Кримський міст", "Естонія закриває кордон з Росією після спроби диверсії"))

    def test_select_skips_same_story(self):
        r = top()[0]
        a = parsed(dict(GOOD, headline={"uk": "ООН обговорює правила щодо автономної зброї", "en": "a"}, importance=8))
        b = parsed(dict(GOOD, headline={"uk": "ООН розпочала переговори щодо регулювання автономної зброї", "en": "b"}, importance=7, region="World"))
        c = parsed(dict(GOOD, headline={"uk": "Каліфорнія готується до штормів", "en": "c"}, importance=6, region="USA"))
        got = synth.select([(r, a), (r, b), (r, c)], 5)
        self.assertEqual(len(got), 2)


class Timeouts(unittest.TestCase):
    def test_timeout_becomes_llmerror_and_busy(self):
        with mock.patch.object(llm, "_call", side_effect=TimeoutError("The read operation timed out")), mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(llm.LLMError) as cm:
                llm.generate_json("s", "p", "m", "k", retries=2)
        self.assertTrue(llm.is_busy(cm.exception))

    def test_timeout_switches_to_fallback(self):
        calls = []

        def fake(system, prompt, model, key, retries=3):
            calls.append(model)
            if model == "main-m":
                raise llm.LLMError("Timeout: The read operation timed out")
            return json.dumps(GOOD)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(llm, "load_key", return_value="k"), \
             mock.patch.object(llm, "generate_json", side_effect=fake), mock.patch.object(run, "ROOT", pathlib.Path(d)):
            run.main(["--fixtures", str(FX), "--now", "2026-11-11T12:00", "--window", "week", "--synth", "--model", "main-m", "--fallback-model", "backup-m", "--sources", Pipeline.SRCFILE])
            self.assertIn("backup-m", calls)
