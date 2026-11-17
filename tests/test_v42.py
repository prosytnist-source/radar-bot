import tempfile, unittest, pathlib, types
from datetime import datetime, timezone, timedelta
from digest import drip
from digest.state import State

class T(unittest.TestCase):
    def test_drop_before(self):
        d = tempfile.mkdtemp(); st = State(pathlib.Path(d))
        now = datetime(2026, 11, 17, 9, 30, tzinfo=timezone.utc)
        mk = lambda h, t: {"created": t.isoformat(), "importance": 5, "headline": h, "html": "x", "preview": None}
        st.save_queue([mk("old", now - timedelta(hours=8)), mk("new", now - timedelta(hours=1))])
        a = types.SimpleNamespace(max_age=13.0, max_age_urgent=4.0, dry=True, drop_before="2026-11-17T04:40")
        drip.control.sync = lambda *x, **k: None
        sent = []
        drip.publish.send = lambda *x, **k: sent.append(x)
        a.dry = False
        drip.publish.env = lambda k: "x"
        drip.step(a, st, now + timedelta(hours=1))
        self.assertEqual([e["headline"] for e in sent and []], [])
        rest = [e["headline"] for e in st.load_queue()]
        self.assertNotIn("old", rest)
        self.assertEqual(len(sent), 1)
if __name__ == "__main__": unittest.main()
