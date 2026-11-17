import json, pathlib, tempfile, unittest
from datetime import date, datetime, timezone
from unittest import mock
from digest import fixed, state as stmod
from digest.calendar_ua import holidays_for, orthodox_easter, nth_weekday

PAGE = """<html><body><h2>Середні ціни за провідними операторами на 16.11.2026 (грн./літр)</h2>
<table><tr><th>Оператор</th><th>А 95+</th><th>А 95</th><th>А 92</th><th>ДП</th><th>Газ</th></tr>
<tr><td>AMIC</td><td></td><td>89,90</td><td>86,90</td><td></td><td>101,96</td><td>63,24</td></tr>
<tr><td>BVS</td><td></td><td>91,90</td><td>88,90</td><td></td><td>106,00</td><td>59,57</td></tr>
<tr><td>Brent Oil</td><td></td><td></td><td>85,50</td><td></td><td>100,90</td><td>62,85</td></tr>
<tr><td>OKKO</td><td></td><td>93,00</td><td>87,00</td><td>83,00</td><td>103,00</td><td>61,00</td></tr></table></body></html>"""
NBU_TODAY = json.dumps([{"cc": "USD", "rate": 41.90}, {"cc": "EUR", "rate": 45.00}, {"cc": "PLN", "rate": 10.50}, {"cc": "JPY", "rate": 0.3}])
NBU_PREV = json.dumps([{"cc": "USD", "rate": 41.80}, {"cc": "EUR", "rate": 45.10}, {"cc": "PLN", "rate": 10.50}])


class Calendar(unittest.TestCase):
    def test_easter(self):
        self.assertEqual(orthodox_easter(2026), date(2026, 4, 12))
        self.assertEqual(orthodox_easter(2027), date(2027, 5, 2))

    def test_days(self):
        self.assertEqual(holidays_for(date(2026, 11, 17))[0][0], "Міжнародний день студентів")
        self.assertTrue(any("Голодомор" in n for n, _ in holidays_for(date(2026, 11, 28))))
        self.assertTrue(any(n == "Трійця (Зелені свята)" for n, _ in holidays_for(date(2026, 5, 31))))
        self.assertEqual(holidays_for(date(2026, 6, 1)), [])
        self.assertEqual(nth_weekday(2026, 5, 6, -1), date(2026, 5, 31))


class Posts(unittest.TestCase):
    def test_fuel_parse(self):
        r = fixed.parse_fuel(PAGE)
        self.assertEqual(r["А-95"], round((86.9 + 88.9 + 85.5 + 87.0) / 4, 2))
        self.assertEqual(r["ДП"], round((101.96 + 106 + 100.9 + 103) / 4, 2))
        self.assertEqual(r["date"], "16.11.2026")
        self.assertNotIn("А-92", r)  # лише 1 оператор — замало

    def test_fuel_implausible_rejected(self):
        bad = PAGE.replace("<th>Газ</th>", "<th>Газ</th><th>Х</th>").replace("<td>63,24</td>", "<td>163,24</td><td>1</td>")
        shifted = PAGE.replace("<th>ДП</th><th>Газ</th>", "<th>Газ</th><th>ДП</th>")  # перепутані місцями колонки
        with self.assertRaises(RuntimeError):
            fixed.parse_fuel(shifted)

    def test_fuel_bad_page_raises(self):
        with self.assertRaises(RuntimeError):
            fixed.parse_fuel("<html>нічого</html>")

    def test_fuel_post_with_delta(self):
        with tempfile.TemporaryDirectory() as d:
            st = stmod.State(pathlib.Path(d))
            (st.dir / "fuel.json").write_text(json.dumps({"А-95": 90.0, "ДП": 99.0}))
            card, text, cur = fixed.fuel_post(date(2026, 11, 17), st, fetch=lambda u: PAGE)
            self.assertIn("▼", text)
            self.assertIn("▲", text)
            self.assertIn("дані на 16.11.2026", text)
            self.assertTrue(card.name == "fuel.jpg" and card.exists())

    def test_rates(self):
        calls = iter([NBU_TODAY, NBU_PREV])
        card, text = fixed.rates_post(date(2026, 11, 17), fetch=lambda u: next(calls))
        self.assertIn("41,90", text)
        self.assertIn("▲ 0,10", text)
        self.assertIn("▼ 0,10", text)
        self.assertNotIn("Злотий: <b>10,50</b> грн (", text)  # без змін — без стрілки
        self.assertTrue(card.exists())

    def test_all_cards_exist(self):
        for n in [f"holiday-{i}.jpg" for i in range(1, 32)] + ["rates.jpg", "fuel.jpg", "silence.jpg"]:
            self.assertTrue((fixed.CARDS / n).exists(), n)


class Run(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.d.name)
        self.p = [mock.patch.object(fixed, "ROOT", self.root), mock.patch.object(fixed.publish, "env", return_value="v"),
                  mock.patch.object(fixed.publish, "send_photo"), mock.patch.object(fixed.publish, "send")]
        self.photo = self.p[2].start()
        self.send = self.p[3].start()
        for x in (self.p[0], self.p[1]):
            x.start()

    def tearDown(self):
        mock.patch.stopall()
        self.d.cleanup()

    def test_due_window(self):
        self.assertTrue(fixed.due("silence", datetime(2026, 11, 17, 7, 0, 30, tzinfo=timezone.utc))[0])  # 09:00:30 Київ
        self.assertFalse(fixed.due("silence", datetime(2026, 11, 17, 7, 2, tzinfo=timezone.utc))[0])     # 09:02 — вже запізно, не публікуємо
        self.assertFalse(fixed.due("holiday", datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc))[0])     # 04:00 — зарано

    def test_posts_once_per_day_and_respects_pause(self):
        fixed.main(["--kind", "silence", "--now", "2026-11-17T07:00"])
        self.assertEqual(self.photo.call_count, 1)
        fixed.main(["--kind", "silence", "--now", "2026-11-17T07:05"])
        self.assertEqual(self.photo.call_count, 1)
        stmod.State(self.root / "state").set_paused(True)
        fixed.main(["--kind", "holiday", "--now", "2026-11-17T04:00"])
        self.assertEqual(self.photo.call_count, 1)

    def test_source_failure_notifies_owner_and_posts_nothing(self):
        with mock.patch.object(fixed, "get", side_effect=OSError("нема мережі")):
            fixed.main(["--kind", "rates", "--now", "2026-11-17T04:30"])
        self.photo.assert_not_called()
        self.send.assert_called_once()
        self.assertIn("не вийшов", self.send.call_args[0][2])
        self.assertFalse((self.root / "state" / "fixed.json").exists())

    def test_no_holiday_skips(self):
        fixed.main(["--kind", "holiday", "--now", "2026-06-01T03:00"])
        self.photo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
