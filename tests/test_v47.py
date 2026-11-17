import pathlib, tempfile, unittest
from datetime import datetime, timedelta, timezone
from digest import gen
from digest.state import State


class Relaxed(unittest.TestCase):
    def test_quiet_hour_triggers_relaxed_and_retries_sooner(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            now = datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)  # 19:00 Київ
            st.set_last_sent(now - timedelta(minutes=90))
            calls = []
            run = lambda *a: calls.append(a) or True
            self.assertIn("послаблений", gen.tick(st, now, 60, run))
            self.assertEqual(calls[-1], (True,))
            self.assertEqual(gen.tick(st, now + timedelta(minutes=10), 60, run), "рано")
            self.assertIn("послаблений", gen.tick(st, now + timedelta(minutes=21), 60, run))

    def test_recent_post_or_queue_means_normal_mode(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            now = datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)
            st.set_last_sent(now - timedelta(minutes=20))
            calls = []
            run = lambda *a: calls.append(a) or True
            self.assertNotIn("послаблений", gen.tick(st, now, 60, run))
            self.assertEqual(calls[-1], ())

    def test_no_relaxed_at_night(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(pathlib.Path(d))
            now = datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)  # 00:00 Київ
            st.set_last_sent(now - timedelta(hours=5))
            self.assertNotIn("послаблений", gen.tick(st, now, 60, lambda *a: True))


if __name__ == "__main__":
    unittest.main()
