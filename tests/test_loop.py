import os, pathlib, subprocess, tempfile, unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from unittest import mock
from digest import drip, state as stmod


def sh(cwd, *a):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


class Loop(unittest.TestCase):
    def test_apply_sent_removes_and_logs(self):
        with tempfile.TemporaryDirectory() as d:
            st = stmod.State(pathlib.Path(d))
            now = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
            st.save_queue([{"created": now.isoformat(), "importance": 7, "headline": "A", "html": "x"},
                           {"created": now.isoformat(), "importance": 7, "headline": "B", "html": "y"}])
            drip.apply_sent(st, [({"headline": "A"}, now)])
            self.assertEqual([e["headline"] for e in st.load_queue()], ["B"])
            self.assertEqual(st.last_sent(), now)
            self.assertEqual(st.events()[0]["headline"], "A")

    def test_git_loop_publishes_once_and_pushes(self):
        """Інтеграційно: справжній git (локальний «віддалений» репозиторій), справжній цикл, Telegram підмінено."""
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            sh(d, "git", "init", "-q", "--bare", "-b", "main", "remote.git")
            sh(d, "git", "clone", "-q", "remote.git", "work")
            w = d / "work"
            sh(w, "git", "config", "user.email", "t@t"); sh(w, "git", "config", "user.name", "t")
            (w / "state").mkdir()
            st = stmod.State(w / "state")
            now = datetime.now(timezone.utc)
            st.save_queue([{"created": now.isoformat(), "importance": 9, "headline": "Термінова", "html": "x"}])
            sh(w, "git", "add", "-A"); sh(w, "git", "commit", "-qm", "init"); sh(w, "git", "push", "-q", "origin", "main")
            sent = []
            a = Namespace(max_age=13, dry=False, loop=0.03, git=True, poll=1)
            with mock.patch.object(drip, "ROOT", w), mock.patch.object(drip.control, "sync", return_value=[]), \
                 mock.patch.object(drip.publish, "env", return_value="v"), mock.patch.object(drip.publish, "send", side_effect=lambda *x, **k: sent.append(x)):
                drip.loop(a, poll=0.2)
            self.assertEqual(len(sent), 1)  # рівно один раз, попри кілька циклів
            remote = sh(d, "git", "clone", "-q", "remote.git", "check")
            q = stmod.State(d / "check" / "state").load_queue()
            self.assertEqual(q, [])  # стан запушено: допис прибрано з черги
            self.assertEqual(stmod.State(d / "check" / "state").events()[0]["headline"], "Термінова")

    def test_daily_flag_does_not_break_loop(self):
        """Регресія v4.5: імпорт модуля poll затирав змінну паузи poll, цикл падав на кінці першого кроку."""
        from digest import poll as poll_mod, toprating
        with tempfile.TemporaryDirectory() as d:
            st_dir = pathlib.Path(d) / "state"
            a = Namespace(max_age=13, dry=False, loop=0.03, git=False, poll=1, daily=True)
            with mock.patch.object(drip, "ROOT", pathlib.Path(d)), mock.patch.object(drip.control, "sync", return_value=[]), \
                 mock.patch.object(poll_mod, "tick", return_value="тест") as p1, mock.patch.object(toprating, "tick", return_value="тест") as p2:
                self.assertEqual(drip.loop(a, poll=0.2), 0)
            self.assertTrue(p1.called and p2.called)


if __name__ == "__main__":
    unittest.main()
