import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

from digest import gen, synth, telegram_fmt
from digest.drip import interval_minutes
from digest.state import State


class V43(unittest.TestCase):
    def test_plural_uk(self):
        f = telegram_fmt._outlets
        self.assertEqual(f(1, "uk"), "Пишуть 1 видання")
        self.assertEqual(f(2, "uk"), "Пишуть 2 видання")
        self.assertEqual(f(3, "uk"), "Пишуть 3 видання")
        self.assertEqual(f(5, "uk"), "Пишуть 5 видань")
        self.assertEqual(f(11, "uk"), "Пишуть 11 видань")
        self.assertEqual(f(21, "uk"), "Пишуть 21 видання")
        self.assertEqual(f(3, "en"), "Reported by 3 outlets")

    def test_interval_faster(self):
        self.assertEqual(interval_minutes(1), 30.0)
        self.assertEqual(interval_minutes(10), 24.0)
        self.assertEqual(interval_minutes(30), 15.0)

    def test_region_bonus_prefers_ukraine(self):
        self.assertGreater(synth.REGION_BONUS["ukraine-russia"], synth.REGION_BONUS["asia"])
        self.assertEqual(synth.norm_region("Ukraine-Russia"), "ukraine-russia")

    def test_gen_tick_rules(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            calls = []
            run = lambda: calls.append(1) or True
            day = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)  # 12:00 Київ
            self.assertIn("ок", gen.tick(st, day, 60, run))
            self.assertEqual(len(calls), 1)
            self.assertEqual(gen.tick(st, day.replace(minute=30), 60, run), "рано")
            self.assertIn("ок", gen.tick(st, day.replace(hour=11), 60, run))
            self.assertEqual(len(calls), 2)
            # повна черга: не генеруємо
            st.save_queue([{"created": day.isoformat(), "importance": 6, "headline": str(i), "html": "x"} for i in range(gen.MAX_QUEUE)])
            self.assertIn("у черзі вже", gen.tick(st, day.replace(hour=13), 60, run))
            self.assertEqual(len(calls), 2)

    def test_gen_tick_night_is_rarer(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            calls = []
            run = lambda: calls.append(1) or True
            night = datetime(2026, 11, 17, 21, 30, tzinfo=timezone.utc)  # 23:30 Київ
            gen.tick(st, night, 60, run)
            self.assertEqual(gen.tick(st, night.replace(hour=22, minute=40), 60, run), "рано")  # 70 хв: вночі проміжок 3 год
            self.assertEqual(len(calls), 1)

    def test_prompt_demands_self_sufficient(self):
        self.assertIn("SELF-SUFFICIENT", synth.SYSTEM)
        self.assertNotIn("BRIEF MODE", synth.system_for(("uk",), batch=True))


if __name__ == "__main__":
    unittest.main()
