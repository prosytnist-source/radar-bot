import json, pathlib, tempfile, unittest
from datetime import datetime, timezone
from unittest import mock
from digest import daily, drip, llm, polish, state as stmod, synth
from test_synth import GOOD, parsed, top


class MinImportance(unittest.TestCase):
    def test_low_importance_dropped(self):
        r = top()[0]
        mk = lambda imp: (r, parsed(dict(GOOD, importance=imp, category="war", region="World", headline={"uk": "Подія " + chr(1040 + imp) * 6 + " " + chr(1072 + imp) * 7, "en": "E" + chr(97 + imp)})))
        got = synth.select([mk(5), mk(6), mk(8)], 5, 3, False, 6)
        self.assertEqual(sorted(s["importance"] for _, s in got), [6, 8])


class Polish(unittest.TestCase):
    def setUp(self):
        self.s = parsed()
        self.s["headline"]["uk"] = "Мостова активівність зросла на 5 відсотків"

    def test_good_edit_applied(self):
        orig = polish.fields(self.s)
        new = dict(orig, headline="Мостова активність зросла на 5 відсотків")
        with mock.patch.object(llm, "generate_json", return_value=json.dumps(new, ensure_ascii=False)):
            self.assertTrue(polish.apply(self.s, "m", "k"))
        self.assertEqual(self.s["headline"]["uk"], "Мостова активність зросла на 5 відсотків")

    def test_changed_number_rejected(self):
        orig = polish.fields(self.s)
        new = dict(orig, headline="Мостова активність зросла на 7 відсотків")
        with mock.patch.object(llm, "generate_json", return_value=json.dumps(new, ensure_ascii=False)):
            self.assertFalse(polish.apply(self.s, "m", "k"))
        self.assertIn("активівність", self.s["headline"]["uk"])

    def test_model_error_keeps_original(self):
        with mock.patch.object(llm, "generate_json", side_effect=llm.LLMError("HTTP 429")):
            self.assertFalse(polish.apply(self.s, "m", "k"))

    def test_missing_key_and_wild_length_rejected(self):
        orig = polish.fields(self.s)
        self.assertFalse(polish.valid(orig, {"headline": "ok"} if len(orig) > 1 else {}))
        self.assertFalse(polish.valid(orig, dict(orig, headline="Дуже " * 80)))


class Daily(unittest.TestCase):
    def test_log_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            st = stmod.State(pathlib.Path(d))
            now = datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc)
            st.log_event("sent", "Перший пост", datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc))
            st.log_event("sent", "Вчорашній", datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc))
            st.log_event("expired", "Застарілий", datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc))
            st.save_queue([{"created": now.isoformat(), "importance": 7, "headline": "h", "html": "x"}])
            text = daily.build(st, now)
            self.assertIn("Опубліковано сьогодні: <b>1</b>", text)
            self.assertIn("08:00 Перший пост", text)
            self.assertNotIn("Вчорашній", text)
            self.assertIn("застаріли: 1", text)
            self.assertIn("У черзі на завтра: 1", text)

    def test_zero_posts_warns(self):
        with tempfile.TemporaryDirectory() as d:
            text = daily.build(stmod.State(pathlib.Path(d)), datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc))
            self.assertIn("жодного поста", text)

    def test_drip_logs_sent_and_expired(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            st = stmod.State(root / "state")
            now = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
            old = (datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)).isoformat()
            st.save_queue([{"created": old, "importance": 7, "headline": "Старий", "html": "x"},
                           {"created": now.isoformat(), "importance": 7, "headline": "Свіжий", "html": "y"}])
            with mock.patch.object(drip, "ROOT", root), mock.patch.object(drip.publish, "send"), mock.patch.object(drip.publish, "env", return_value="v"), mock.patch.object(drip.control, "sync"):
                drip.main(["--now", "2026-11-17T08:00"])
            kinds = sorted((e["kind"], e["headline"]) for e in stmod.State(root / "state").events())
            self.assertEqual(kinds, [("expired", "Старий"), ("sent", "Свіжий")])


if __name__ == "__main__":
    unittest.main()
