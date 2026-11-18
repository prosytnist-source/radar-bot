import json, pathlib, tempfile, unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

from digest import evening, fulltext, wipe
from digest.fetch import Item
from digest.state import State

NOW = datetime(2026, 11, 17, 18, 30, tzinfo=timezone.utc)  # 20:30 Київ
BODY = " ".join(f"Sentence number {i} about the strike on the Crimean bridge and what Moscow and Kyiv said." for i in range(30))
PAGE = f"<html><body><nav><p>Home news sport weather menu menu menu menu menu menu menu</p></nav><article><p>{BODY}</p><p>Subscribe to our newsletter today and never miss a story from us.</p></article><footer><p>All rights reserved by the publisher of this site today.</p></footer></body></html>"


def item(sid, country, title="Ukraine strikes Crimean bridge before Trump Xi Putin summit", mins=30):
    return Item(sid, sid.upper(), title, f"https://{sid}.example/a", "Ukraine struck the Crimean bridge ahead of the summit", NOW - timedelta(minutes=mins), country)


class Fulltext(unittest.TestCase):
    def test_extract_keeps_article_drops_chrome(self):
        t = fulltext.extract(PAGE)
        self.assertIn("Crimean bridge", t)
        self.assertNotIn("Subscribe", t)
        self.assertNotIn("menu menu", t)
        self.assertNotIn("All rights", t)

    def test_short_or_failed_page_gives_empty(self):
        self.assertEqual(fulltext.fetch_text("u", 800, get=lambda u: "<p>tiny</p>"), "")
        def boom(u): raise OSError("x")
        self.assertEqual(fulltext.fetch_text("u", 800, get=boom), "")


def texts_for_test():
    return {s: {"item": item(s, c), "text": BODY + f" Unique quote of {s} outlet about the bridge repair plan for 2026.", "src": {"country": c, "type": "public"}}
            for s, c in (("a", "USA"), ("b", "Qatar"), ("c", "India"))}


def good(**kw):
    q = lambda s: {"id": s, "quote": f"Unique quote of {s} outlet about the bridge repair plan"}
    d = {"same_event": True, "importance": 8, "headline": "Міст і самміт", "intro": "Слухай, діло таке.", "h": {"event": "Спершу про міст"},
         "event": [{"text": "Міст пошкоджено.", "evidence": [q("a")]}, {"text": "Ремонт заплановано.", "evidence": [q("b")]}],
         "views": [{"id": s, "text": f"Погляд {s}.", "quote": q(s)["quote"]} for s in "abc"],
         "clash": [{"text": "Розбіжність.", "evidence": [q("a"), q("b")]}], "meaning": ["Схоже, це важливо."], "watch": ["Стежимо."], "advice": "Не поспішай.", "wish": "Тихого вечора."}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


class Parse(unittest.TestCase):
    def test_valid_review(self):
        d = evening.parse(good(), texts_for_test())
        self.assertEqual(len(d["views"]), 3)
        self.assertEqual(d["heads"]["event"], "Спершу про міст")
        self.assertEqual(d["heads"]["views"], "Як це бачать у світі")  # запасний підзаголовок

    def test_uncited_and_wrong_number_dropped(self):
        d = json.loads(good())
        d["event"].append({"text": "Вигаданий факт.", "evidence": [{"id": "a", "quote": "this quote is not in the text at all"}]})
        d["event"].append({"text": "Загинуло 777 людей.", "evidence": [{"id": "a", "quote": "Unique quote of a outlet about the bridge repair plan"}]})
        out = evening.parse(json.dumps(d), texts_for_test())
        self.assertEqual(len(out["event"]), 2)
        self.assertEqual(out["dropped"], 2)

    def test_view_quote_must_come_from_its_own_outlet(self):
        d = json.loads(good())
        d["views"][0]["quote"] = d["views"][1]["quote"]
        with self.assertRaises(evening.BadReview):
            evening.parse(json.dumps(d), texts_for_test())  # лишилось 2 погляди

    def test_clash_needs_two_outlets(self):
        d = json.loads(good())
        d["clash"][0]["evidence"] = d["clash"][0]["evidence"][:1]
        self.assertEqual(evening.parse(json.dumps(d), texts_for_test())["clash"], [])

    def test_html_stripped_and_different_event_rejected(self):
        out = evening.parse(good(intro="<b>Привіт</b>"), texts_for_test())
        self.assertEqual(out["intro"], "Привіт")
        with self.assertRaises(evening.BadReview):
            evening.parse(good(same_event=False), texts_for_test())


class Busy(unittest.TestCase):
    def test_retries_on_503_then_succeeds(self):
        n = {"i": 0}
        def call(s, p, m, k):
            n["i"] += 1
            if n["i"] <= 3:
                raise evening.llm.LLMError("HTTP 503: high demand")
            return good()
        waits = []
        d = evening.generate(texts_for_test(), {}, "k", call=call, sleep=waits.append)
        self.assertEqual(len(d["views"]), 3)
        self.assertEqual(waits, [30, 60])  # перша 503 → запасна модель без очікування

    def test_gives_up_after_waits(self):
        def call(s, p, m, k):
            raise evening.llm.LLMError("HTTP 503: high demand")
        with self.assertRaises(evening.llm.LLMError):
            evening.generate(texts_for_test(), {}, "k", call=call, sleep=lambda s: None)


class Render(unittest.TestCase):
    def test_fit_trims_to_limit(self):
        texts = texts_for_test()
        d = evening.parse(good(), texts)
        d["views"] = [{"id": v["id"], "text": "дуже довго " * 60} for v in d["views"]]
        text = evening.fit(d, texts, NOW, limit=2500)
        self.assertTrue(text is None or len(text) <= 2500)
        short = evening.fit(evening.parse(good(), texts), texts, NOW)
        self.assertIn("Проста порада", short)
        self.assertIn("🇺🇸", short)
        self.assertIn("наш висновок", short)


class Collect(unittest.TestCase):
    def test_collect_dedupes_and_expires(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            self.assertEqual(evening.collect(st, NOW, [item("a", "USA"), item("a", "USA"), item("b", "Qatar")]), 2)
            old = item("c", "India", mins=60 * 50)
            self.assertEqual(evening.collect(st, NOW, [old]), 2)  # старше 40 год — не зберігається


class Pick(unittest.TestCase):
    def test_pick_needs_countries_and_texts(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            cfg = evening.load_cfg()
            by = {s: {"country": c} for s, c in (("a", "USA"), ("b", "Qatar"), ("c", "India"))}
            items = [item("a", "USA"), item("b", "Qatar"), item("c", "India")]
            self.assertIsNotNone(evening.pick_topic(st, NOW, items, by, cfg, get=lambda u: PAGE))
            self.assertIsNone(evening.pick_topic(st, NOW, items, by, cfg, get=lambda u: "<p>x</p>"))  # тексти не прочитано
            two = [item("a", "USA"), item("b", "USA"), item("c", "USA")]
            self.assertIsNone(evening.pick_topic(st, NOW, two, by, cfg, get=lambda u: PAGE))  # одна країна


class Tick(unittest.TestCase):
    def test_window_marker_and_retries(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            cfg = evening.load_cfg()
            self.assertEqual(evening.tick(st, datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc), cfg), "рано")  # 18:00 Київ
            self.assertEqual(evening.tick(st, datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc), cfg), "пізно")  # 23:30 Київ
            calls = []
            with mock.patch.object(evening, "_fetch_focus", lambda: ([], {}, {})), mock.patch.object(evening, "run", lambda *a, **k: calls.append(1) or "перегляд надіслано власнику: x"), mock.patch.object(evening.llm, "load_key", lambda: "k"):
                self.assertIn("перегляд", evening.tick(st, NOW, cfg))
                self.assertEqual(evening.tick(st, NOW + timedelta(minutes=40), cfg), "сьогодні вже було")
            self.assertEqual(len(calls), 1)

    def test_failed_attempt_retries_later_up_to_limit(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            cfg = evening.load_cfg()
            with mock.patch.object(evening, "_fetch_focus", lambda: ([], {}, {})), mock.patch.object(evening, "run", lambda *a, **k: "немає теми"), mock.patch.object(evening.llm, "load_key", lambda: "k"):
                evening.tick(st, NOW, cfg)
                self.assertEqual(evening.tick(st, NOW + timedelta(minutes=5), cfg), "чекаю наступної спроби")
                for m in (20, 40, 60):
                    evening.tick(st, NOW + timedelta(minutes=m), cfg)
                self.assertEqual(evening.tick(st, NOW + timedelta(minutes=80), cfg), "сьогодні спроби вичерпано")


class Wipe(unittest.TestCase):
    def test_batches_cover_all_ids(self):
        seen = []
        def api(method, token, params):
            seen.append(json.loads(params["message_ids"]))
            return {"ok": True}
        self.assertEqual(wipe.wipe("t", "c", api=api, top=250), 250)
        flat = sorted(i for b in seen for i in b)
        self.assertEqual(flat, list(range(1, 251)))
        self.assertTrue(all(len(b) <= 100 for b in seen))

    def test_falls_back_to_single_deletes_when_batch_rejected(self):
        single = []
        def api(method, token, params):
            if method == "deleteMessages":
                raise SystemExit("Telegram: HTTP 400 message can't be deleted")
            i = params["message_id"]
            if i == 1:
                raise SystemExit("service message")
            single.append(i)
            return {"ok": True}
        wipe.wipe("t", "c", api=api, top=21)
        self.assertEqual(sorted(single), list(range(2, 22)))

    def test_needs_exact_confirmation(self):
        self.assertEqual(wipe.main(["--confirm", "так"]), 1)


if __name__ == "__main__":
    unittest.main()


class V51(unittest.TestCase):
    def test_agree_needs_two_outlets_and_is_rendered(self):
        texts = texts_for_test()
        q = lambda s: {"id": s, "quote": f"Unique quote of {s} outlet about the bridge repair plan"}
        d = json.loads(good())
        d["agree"] = [{"text": "Обидва кажуть про міст.", "evidence": [q("a"), q("b")]}, {"text": "Один голос.", "evidence": [q("a")]}]
        out = evening.parse(json.dumps(d), texts)
        self.assertEqual(out["agree"], ["Обидва кажуть про міст."])
        text = evening.fit(out, texts, NOW)
        self.assertIn("Де сходяться", text)
        self.assertIn("• Обидва кажуть про міст.", text)

    def test_view_quote_shown_in_post(self):
        texts = texts_for_test()
        text = evening.fit(evening.parse(good(), texts), texts, NOW)
        self.assertIn("«Unique quote of a outlet about the bridge repair plan»", text)

    def test_exile_outlet_marked_not_russian_flag(self):
        texts = texts_for_test()
        texts["c"]["src"] = {"country": "Netherlands / Russia", "type": "independent_exile"}
        texts["c"]["item"] = item("c", "Netherlands / Russia")
        text = evening.fit(evening.parse(good(), texts), texts, NOW)
        self.assertIn("🕊", text)
        self.assertIn("(незалежне, у вигнанні)", text)
        self.assertNotIn("🇷🇺", text)

    def test_fit_drops_quotes_before_sections(self):
        texts = texts_for_test()
        d = evening.parse(good(), texts)
        full = evening.render(d, texts, NOW)
        text = evening.fit(d, texts, NOW, limit=len(full) - 40)
        self.assertTrue(text is not None and len(text) <= len(full) - 40)
        self.assertIn("Проста порада", text)
