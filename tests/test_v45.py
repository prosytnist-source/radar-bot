import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from digest import card, deliver, images, poll, publish, run, telegram_fmt, toprating
from digest.cluster import Cluster
from digest.fetch import Item
from digest.rank import Ranked
from digest.state import State

NOW = datetime(2026, 11, 17, 8, 30, tzinfo=timezone.utc)  # 10:30 Київ
CFG = poll.load_topics()


def st_tmp():
    d = tempfile.mkdtemp()
    return State(pathlib.Path(d))


class Images(unittest.TestCase):
    def test_key_ignores_query(self):
        self.assertEqual(images.key("https://X.com/a/b.jpg?w=800"), images.key("https://x.com/a/b.jpg?w=200"))

    def test_used_roundtrip_and_prune(self):
        st = st_tmp()
        u = images.Used(st)
        u.add("https://x.com/a.jpg", NOW - timedelta(days=40))
        u.add("https://x.com/b.jpg?z=1", NOW)
        u2 = images.Used(st)
        self.assertTrue(u2.has("https://x.com/b.jpg"))
        self.assertFalse(u2.has("https://x.com/a.jpg"))

    def test_pick_photo_skips_used_and_state(self):
        by_id = {"bbc": {"image_ok": True}, "dw": {"image_ok": True}, "xin": {"image_ok": True, "type": "state"}}
        its = [Item("bbc", "BBC", "t", "https://bbc/a", "", NOW, image="https://bbc/1.jpg"), Item("dw", "DW", "t", "https://dw/a", "", NOW - timedelta(minutes=5), image="https://dw/2.jpg"),
               Item("xin", "Xinhua", "t", "https://xin/a", "", NOW, image="https://xin/3.jpg")]
        r = Ranked(Cluster(items=its, vec={}), 1, 3, 3, False)
        self.assertEqual(run.pick_photo(r, by_id)["image"], "https://bbc/1.jpg")
        st = st_tmp()
        u = images.Used(st)
        u.add("https://bbc/1.jpg", NOW)
        self.assertEqual(run.pick_photo(r, by_id, images.Used(st))["image"], "https://dw/2.jpg")
        self.assertIsNone(run.pick_photo(r, by_id, images.Used(st), {images.key("https://dw/2.jpg")}))  # державне не береться


class PhotoCheck(unittest.TestCase):
    def test_check_rejects_blank_and_falls_to_next(self):
        by_id = {"npr": {"image_ok": True}, "bbc": {"image_ok": True}}
        its = [Item("npr", "NPR", "t", "https://npr/a", "", NOW, image="https://npr/blank.png"), Item("bbc", "BBC", "t", "https://bbc/a", "", NOW - timedelta(minutes=5), image="https://bbc/real.jpg")]
        r = Ranked(Cluster(items=its, vec={}), 1, 2, 2, False)
        self.assertEqual(run.pick_photo(r, by_id, check=lambda u: "real" in u)["image"], "https://bbc/real.jpg")
        self.assertIsNone(run.pick_photo(r, by_id, check=lambda u: False))  # годящої нема → піде картка

    def test_usable_rejects_blank_white_image(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), (255, 255, 255)).save(buf, "PNG")
        noisy = io.BytesIO()
        im = Image.new("RGB", (800, 600))
        px = im.load()
        for x in range(800):
            for y in range(600):
                px[x, y] = ((x * 7) % 256, (y * 5) % 256, (x * y) % 256)
        im.save(noisy, "PNG")

        class R:
            def __init__(s, data): s.data, s.headers = data, {"Content-Type": "image/png"}
            def read(s, n): return s.data
            def __enter__(s): return s
            def __exit__(s, *a): return False
        with mock.patch.object(images, "urlopen", return_value=R(buf.getvalue() + b"0" * 9000)):
            self.assertFalse(images.usable("https://x/blank.png"))
        with mock.patch.object(images, "urlopen", return_value=R(noisy.getvalue())):
            self.assertTrue(images.usable("https://x/real.png"))


class Deliver(unittest.TestCase):
    def test_photo_used_once_then_card(self):
        st = st_tmp()
        e = {"html": "<b>x</b>", "preview": "https://bbc/1.jpg", "credit": "<i>Фото</i>", "card": None}
        with mock.patch.object(deliver.publish, "send") as send, mock.patch.object(deliver, "send_card_text", return_value=True) as sc, mock.patch.object(deliver, "photo_ok", return_value=True):
            deliver.send_entry(e, "t", "c", st, NOW)
            self.assertEqual(send.call_args[0][3], "https://bbc/1.jpg")
            self.assertIn("Фото", send.call_args[0][2])
            e2 = dict(e, card={"title": "T"})
            deliver.send_entry(e2, "t", "c", st, NOW)  # те саме фото вдруге → картка
            sc.assert_called_once()

    def test_blank_photo_becomes_card(self):
        e = {"html": "x", "preview": "https://npr/blank.png", "credit": "c", "card": {"title": "T"}}
        with mock.patch.object(deliver.publish, "send") as send, mock.patch.object(deliver, "send_card_text", return_value=True) as sc, mock.patch.object(deliver, "photo_ok", return_value=False):
            deliver.send_entry(e, "t", "c", st_tmp(), NOW)
            sc.assert_called_once()
            send.assert_not_called()

    def test_no_photo_no_card_lib_falls_back_to_text(self):
        with mock.patch.object(deliver.publish, "send") as send, mock.patch.object(card, "available", return_value=False):
            deliver.send_entry({"html": "x", "preview": None, "card": {"title": "T"}}, "t", "c", st_tmp(), NOW)
            send.assert_called_once()

    def test_short_text_is_caption_long_is_separate(self):
        with mock.patch.object(deliver.publish, "send_photo") as sp, mock.patch.object(deliver.publish, "send") as s:
            deliver.send_card_text("t", "c", {"title": "T"}, "коротко")
            sp.assert_called_once()
            s.assert_not_called()
            deliver.send_card_text("t", "c", {"title": "T"}, "я" * 1500)
            s.assert_called_once()


class CardRender(unittest.TestCase):
    def test_render_file(self):
        out = pathlib.Path(tempfile.mkdtemp()) / "c.jpg"
        card.render("Дуже довгий заголовок " * 5, out, "Підзаголовок", ["США", "Японія"], "top")
        self.assertGreater(out.stat().st_size, 10000)


class Poll(unittest.TestCase):
    def api_factory(self):
        calls = []

        def api(method, token, params=None):
            calls.append((method, params))
            if method == "sendPoll":
                return {"result": {"message_id": 77}}
            if method == "stopPoll":
                return {"result": {"total_voter_count": 5, "options": [{"voter_count": i} for i in range(len(CFG["topics"]))]}}
            return {"result": {}}
        return api, calls

    def test_cfg_valid(self):
        self.assertLessEqual(len([x for x in CFG["topics"] if x.get("poll", True)]) + CFG["poll"]["dynamic"], 10)
        for t in CFG["topics"]:
            self.assertLessEqual(len(t["option"]), 100)

    def test_send_once_per_day_then_close(self):
        st = st_tmp()
        api, calls = self.api_factory()
        with mock.patch.object(deliver, "send_card_text", return_value=True):
            self.assertEqual(poll.tick(st, NOW, CFG, api, "t", "c"), "опитування надіслано")
            self.assertEqual(poll.tick(st, NOW + timedelta(minutes=5), CFG, api, "t", "c"), "опитування триває")
            late = NOW.replace(hour=18, minute=55)  # 20:55 Київ
            self.assertIn("закрито", poll.tick(st, late, CFG, api, "t", "c"))
            self.assertEqual(poll.tick(st, late + timedelta(minutes=1), CFG, api, "t", "c"), "рано")  # сьогодні вже було
        w = poll.weekly(st, late)
        order = [json.loads(c[1]["options"]) for c in calls if c[0] == "sendPoll"][0]
        self.assertEqual(sum(w.values()), sum(range(len(order))))  # голоси записані за варіантами в порядку, у якому їх показали
        self.assertEqual([c[0] for c in calls].count("sendPoll"), 1)

    def test_not_before_10(self):
        st = st_tmp()
        api, _ = self.api_factory()
        early = NOW.replace(hour=6)  # 08:30 Київ
        self.assertEqual(poll.tick(st, early, CFG, api, "t", "c"), "рано")

    def test_paused(self):
        st = st_tmp()
        st.set_paused(True)
        self.assertEqual(poll.tick(st, NOW, CFG), "пауза")


class Dynamic(unittest.TestCase):
    def _state_with_posts(self):
        st = st_tmp()
        for i, h in enumerate(["Україна та Росія завдали ударів по мостах", "Переговори в Женеві відкрилися", "Французькі військові діють в Україні", "Удари по мостах: нові подробиці"]):
            at = NOW - timedelta(hours=i + 1)
            st.published.append({"t": at.isoformat(), "links": [f"https://x/{i}"], "tokens": ["bridge", "strike", "kyiv", f"w{i}"], "headline": h})
            st.log_event("sent", h, at)
        st.pub_file.write_text(json.dumps(st.published, ensure_ascii=False), encoding="utf-8")
        return st

    def test_options_static_plus_stories_deduped_and_shuffled_by_day(self):
        st = self._state_with_posts()
        opts, dyn = poll.build_options(st, NOW, CFG)
        texts = [o["text"] for o in opts]
        self.assertEqual(len(dyn), 3)  # 4 постів, але два — про мости: лишається 3 історії
        self.assertEqual(sum(1 for t in texts if t.startswith("Історія дня")), 3)
        self.assertEqual(len(opts), 6 + 3)
        self.assertTrue(all(len(t) <= 100 for t in texts))
        again, _ = poll.build_options(st, NOW + timedelta(minutes=5), CFG)
        self.assertEqual([o["id"] for o in again], [o["id"] for o in opts])  # у межах дня порядок той самий
        nextday, _ = poll.build_options(st, NOW + timedelta(days=1), CFG)
        self.assertNotEqual([o["id"] for o in nextday][:6], [o["id"] for o in opts][:6])

    def test_themes_not_in_poll(self):
        opts, _ = poll.build_options(st_tmp(), NOW, CFG)
        self.assertNotIn("war", [o["id"] for o in opts])

    def test_story_matching_and_voters(self):
        topic = {"id": "s", "title": "x", "kind": "story", "links": ["https://x/0"], "tokens": ["bridge", "strike", "kyiv", "crimea"]}
        by_id = {}
        self.assertTrue(toprating.matches(topic, Item("a", "A", "t", "https://x/0", "", NOW), by_id))
        self.assertTrue(toprating.matches(topic, Item("b", "B", "Strike on Crimea bridge near Kyiv", "https://y", "", NOW), by_id))
        self.assertFalse(toprating.matches(topic, Item("b", "B", "Budget vote in Paris", "https://y", "", NOW), by_id))
        st = st_tmp()
        poll._save(st, {"days": {"2026-11-17": {"counts": {"china": 1, "usa": 1, "war": 1}, "total": 1}}})
        self.assertEqual(poll.voters(st, NOW), 1)  # одна людина, хоч обрала три варіанти
        o, fv = toprating.order_topics(CFG["topics"], {"china": 1, "usa": 1, "war": 1}, {"war": 5}, 3, None, voters=1)
        self.assertFalse(fv)  # голосів-людей замало: тема за власною статистикою

    def test_dynamic_topics_from_recent_days(self):
        st = st_tmp()
        poll._save(st, {"days": {"2026-11-17": {"counts": {}, "total": 2, "dynamic": {"story-2026-11-17-1": {"title": "Т", "links": ["l"], "tokens": ["a"]}}},
                                 "2026-11-10": {"counts": {}, "total": 2, "dynamic": {"story-2026-11-10-1": {"title": "Старе", "links": [], "tokens": []}}}}})
        self.assertEqual([t["id"] for t in poll.dynamic_topics(st, NOW)], ["story-2026-11-17-1"])


class Top(unittest.TestCase):
    T = CFG["topics"]

    def test_votes_win_and_no_repeat(self):
        votes = {"china": 5, "usa": 3}
        o, fv = toprating.order_topics(self.T, votes, {}, 3, None)
        self.assertTrue(fv)
        self.assertEqual(o[0]["id"], "china")
        o, _ = toprating.order_topics(self.T, votes, {}, 3, "china")  # вчора вже була — сьогодні наступна
        self.assertEqual(o[0]["id"], "usa")

    def test_no_votes_uses_own_stats_silently(self):
        o, fv = toprating.order_topics(self.T, {}, {"war": 9, "peace": 2}, 3, None)
        self.assertFalse(fv)
        self.assertEqual(o[0]["id"], "war")

    def test_matches(self):
        by_id = {"xin": {"country": "China"}, "bbc": {"country": "UK"}}
        china = [t for t in self.T if t["id"] == "china"][0]
        war = [t for t in self.T if t["id"] == "war"][0]
        self.assertTrue(toprating.matches(china, Item("xin", "X", "a", "l", "", NOW), by_id))
        self.assertFalse(toprating.matches(china, Item("bbc", "B", "a", "l", "", NOW), by_id))
        self.assertTrue(toprating.matches(war, Item("bbc", "B", "Drone strike on Kyiv", "l", "", NOW), by_id))

    def test_render_top_mentions_votes_only_when_real(self):
        d = {"headline": "Що пишуть", "points": [{"uk": "пункт", "by": "xin"}], "watch": ""}
        its = [Item("xin", "Xinhua", "a", "https://x/1", "", NOW, country="China")]
        rs = [Ranked(Cluster(items=its, vec={}), 1, 1, 1, True)]
        by_id = {"xin": {"country": "China", "type": "state"}}
        t = {"title": "Китай"}
        self.assertIn("за вашим вибором", telegram_fmt.render_top(d, rs, by_id, t, NOW, True))
        self.assertNotIn("вибором", telegram_fmt.render_top(d, rs, by_id, t, NOW, False))

    def test_run_sends_and_marks_day(self):
        st = st_tmp()
        by_id = {"xin": {"country": "China"}, "cgtn": {"country": "China"}}
        mk = lambda sid, title, sn: Item(sid, sid, title, f"https://{sid}/{title[:3]}", sn, NOW, country="China")
        items = [mk("xin", "Ukraine talks open in Geneva today", "Ukraine delegation arrives for the talks"), mk("cgtn", "Ukraine talks open in Geneva", "Talks on Ukraine begin in Geneva today"),
                 mk("xin", "Kyiv drone strike damages power grid", "Kyiv power grid damaged by drones overnight"), mk("cgtn", "Drone strike on Kyiv hits power grid", "Overnight drones struck Kyiv power grid")]
        sent = []
        resp = {"headline": "Китайські видання про Україну", "points": [
            {"uk": f"п{n}", "evidence": [{"id": "xin", "quote": "Ukraine talks open in Geneva today"}]} for n in range(3)], "watch": ""}
        with mock.patch.object(toprating.llm, "generate_json", return_value=json.dumps(resp)):
            msg = toprating.run(st, NOW, items, by_id, CFG, "k", sender=lambda spec, text: sent.append((spec, text)))
        self.assertIn("опубліковано", msg)
        self.assertEqual(sent[0][0]["title"], "Топ-рейтинг")
        self.assertEqual(json.loads((st.dir / "top.json").read_text())["day"], "2026-11-17")

    def test_tick_time_window(self):
        st = st_tmp()
        self.assertEqual(toprating.tick(st, NOW, CFG), "рано")
        late = NOW.replace(hour=21, minute=45)  # 23:45 Київ
        self.assertEqual(toprating.tick(st, late, CFG), "пізно")


if __name__ == "__main__":
    unittest.main()
