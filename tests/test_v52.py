import json, pathlib, tempfile, unittest
from datetime import date
from digest import chronicle as c, card

WT = """== Події ==
* [[1919]] — [[Акт возз'єднання УНР і ЗУНР|Проголошено Акт злуки УНР і ЗУНР]] у Києві.
* [[1500]] — Подія в Англії без зв'язку.
== Народились ==
* [[1856]] — [[Іван Франко]], український письменник.
* [[1900]] — [[Іван Іванов]], російський актор.
* [[1990]] — [[Живий Українець]], український співак.
== Померли ==
* [[1916]] — [[Іван Франко]], український поет.
"""
SUM = {"Іван Франко": {"title": "Іван Франко", "extract": "Іван Якович Франко (27 серпня 1856 — 28 травня 1916) — український письменник, поет, перекладач і науковець."},
       "Живий Українець": {"title": "Живий Українець", "extract": "Живий Українець (нар. 1990) — український співак."},
       "Акт возз'єднання УНР і ЗУНР": {"title": "Акт злуки", "extract": "Акт злуки — проголошено 22 січня 1919 року у Києві."}}


def fetch(url):
    if "api.php" in url:
        return {"parse": {"wikitext": WT}}
    for k, v in SUM.items():
        if k.replace(" ", "_") in __import__("urllib.parse").parse.unquote(url):
            return v
    raise OSError("no")


class T(unittest.TestCase):
    def test_parse(self):
        items = c.parse_day(WT)
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["kind"], "event")
        self.assertEqual(items[2]["link"], "Іван Франко")

    def test_subsections(self):
        wt = "== Події ==\n=== XX століття ===\n* [[1919]] — Проголошено Акт злуки в Україні, у Києві.\n== Народились ==\n=== XIX століття ===\n* [[1856]] — [[Іван Франко]], український письменник.\n"
        self.assertEqual([i["kind"] for i in c.parse_day(wt)], ["event", "birth"])

    def test_variants(self):
        wt = ("== Події ==\n* '''[[1919]]''' — Проголошено Акт злуки в Україні, у Києві.\n"
              "* [[1918]]&nbsp;— Проголошено незалежність України в Києві.\n"
              "* [[1917]] р. — Створено Українську Центральну Раду в Києві.\n"
              "* {{дата|1916}} — Подія в Україні, у Львові сталась.\n"
              "** [[1915]] – Вступили війська в Україні, у Галичині.\n")
        self.assertGreaterEqual(len(c.parse_day(wt)), 4)

    def test_title_order_and_accents(self):
        sm = {"title": "Амбодик-Максимович Нестор Максимович", "extract": "Не\u0301стор Амбоди\u0301к-Максимович (7 листопада 1744 — 24 липня 1812) — український вчений."}
        cand = {"kind": "birth", "year": 1744, "n": 282, "text": "Нестор Амбодик, український вчений", "link": "x"}
        t, txt = c.write(cand, "figure", sm, None)
        self.assertEqual(t, "Нестор Амбодик-Максимович")
        self.assertNotIn("\u0301", txt)

    def test_candidates(self):
        items = c.parse_day(WT)
        f = c.candidates(items, "figure", date(2026, 1, 22))
        self.assertTrue(all("російськ" not in x["text"] for x in f))
        self.assertEqual(len(c.candidates(items, "fact", date(2026, 1, 22))), 1)

    def test_grounded(self):
        self.assertTrue(c.grounded("Франко народився 1856 року", "Іван Франко 1856"))
        self.assertFalse(c.grounded("Франко народився 1857 року", "Іван Франко 1856"))
        self.assertFalse(c.grounded("Він жив у місті Лондон", "Іван Франко 1856 письменник"))

    def test_figure_skips_living_and_fallback(self):
        r = c.build("figure", date(2026, 1, 22), [], fetch, key=None)
        self.assertEqual(r["title"], "Іван Франко")
        self.assertEqual(r["subtitle"], "1856–1916 · день народження".replace("день народження", r["subtitle"].split(" · ")[1]))
        self.assertIn("Джерело: Вікіпедія", r["caption"])
        self.assertNotIn("Живий", r["caption"])

    def test_llm_rejected_when_invented(self):
        bad = lambda *a, **k: json.dumps({"title": "Франко", "text": "Франко народився 1999 року в місті Париж і прославився на весь світ своїми творами."})
        r = c.build("figure", date(2026, 1, 22), [], fetch, key="k", call=bad)
        self.assertNotIn("1999", r["caption"])

    def test_llm_accepted_when_grounded(self):
        good = lambda *a, **k: json.dumps({"title": "Іван Франко", "text": "Іван Франко — український письменник, поет, перекладач і науковець. Він народився 1856 року й помер 1916 року."})
        r = c.build("figure", date(2026, 1, 22), [], fetch, key="k", call=good)
        self.assertIn("народився 1856", r["caption"])

    def test_used_avoided(self):
        r = c.build("figure", date(2026, 1, 22), ["іван франко"], fetch, key=None)
        self.assertIsNotNone(r)

    def test_fact_and_none(self):
        r = c.build("fact", date(2026, 1, 22), [], fetch, key=None)
        self.assertIn("1919", r["caption"])
        self.assertIsNone(c.build("fact", date(2026, 1, 22), [], lambda u: {"parse": {"wikitext": "== Події ==\n* [[1500]] — Щось в Англії відбулося колись.\n"}}, key=None))

    def test_no_page_raises(self):
        with self.assertRaises(RuntimeError):
            c.build("fact", date(2026, 1, 22), [], lambda u: {}, key=None)

    def test_card(self):
        if not card.available():
            self.skipTest("no Pillow")
        with tempfile.TemporaryDirectory() as d:
            for k, g in (("figure", "person"), ("history", "clock")):
                p = card.render("Іван Франко", pathlib.Path(d) / f"{k}.jpg", subtitle="1856–1916", chips=["Визначні постаті"], kind=k, glyph=g)
                self.assertTrue(pathlib.Path(p).stat().st_size > 5000)




class CatEveningTests(unittest.TestCase):
    def test_captions_fit_22h(self):
        from digest import cat
        bad = ("Доброго", "Добрий ранок", "ранку,", "Понеділок", "П'ятниця", "Перша кава", "Сніданок —")
        for r, sc, ln in cat._pool():
            self.assertFalse(any(w in ln for w in bad), ln)


class AskTests(unittest.TestCase):
    def test_pick_no_repeat_and_all_valid(self):
        from datetime import date
        from digest import askcat
        n = len(askcat.pool())
        self.assertEqual(n, 36)
        base = n * 1000
        seen = {askcat.pick(date.fromordinal(base + i))[0] for i in range(n)}
        self.assertEqual(len(seen), n)
        for sph, q, opts in askcat.pool():
            self.assertEqual(len(opts), 4); self.assertLessEqual(len(q), 300)
            self.assertTrue(all(len(o) <= 100 for o in opts))

    def test_expert_and_weekly(self):
        import json, tempfile, pathlib
        from datetime import datetime, timezone
        from digest import askcat
        from digest.state import State
        d = pathlib.Path(tempfile.mkdtemp()); st = State(d)
        sent = []
        def api(method, token, params=None):
            if method == "sendPoll":
                return {"result": {"message_id": 5}}
            return {"result": {"total_voter_count": 10, "options": [{"voter_count": 6}, {"voter_count": 2}, {"voter_count": 2}, {"voter_count": 0}]}}
        now = datetime(2026, 11, 22, 14, 0, tzinfo=timezone.utc)  # неділя
        askcat.run_ask(st, now, "t", "c", api=api, send_photo=lambda *a: sent.append(a))
        good = lambda s, p, m, k, retries=1, timeout=35: json.dumps({"text": "Найбільше голосів, 60%, за перший варіант. Це наш вибір на сьогодні, тож не поспішайте з висновками й перевіряйте на власному досвіді."})
        msg = askcat.run_expert(st, now, "t", "c", "k", api=api, send_photo=lambda *a: sent.append(a), send=lambda *a: sent.append(a), call=good)
        self.assertIn("голосів 10", msg)
        bad = lambda s, p, m, k, retries=1, timeout=35: json.dumps({"text": "Вісімдесят відсотків і 77% людей згодні, тож це точно найкращий вибір для всіх вас без винятків."})
        st2 = State(pathlib.Path(tempfile.mkdtemp()))
        askcat.run_ask(st2, now, "t", "c", api=api, send_photo=lambda *a: None)
        askcat.run_expert(st2, now, "t", "c", "k", api=api, send_photo=lambda *a: sent.append(a), send=lambda *a: sent.append(a), call=bad)  # цифра 77 не з даних → запасний текст
        self.assertNotIn("77%", str(sent[-1]))
        rep = askcat.weekly_report(st, now)
        self.assertIn("Тижнева статистика", rep); self.assertIn("60% з 10", rep)


class CultureTests(unittest.TestCase):
    def test_build_no_repeat_and_quote(self):
        from digest import culture
        from datetime import date
        pages = ["Іван Котляревський", "Леся Українка", "Список поетів"]
        ext = "Леся Українка (1871–1913) — українська письменниця, поетеса, драматургині та перекладачка. " * 3
        def fetch(url, timeout=20):
            if "categorymembers" in url:
                return {"query": {"categorymembers": [{"title": t} for t in pages]}}
            if "wikiquote" in url:
                return {"parse": {"wikitext": "* Contra spem spero — без надії сподіваюсь і тримаюсь до кінця, і це моє.\n* ще [[x]]"}}
            t = url.rsplit("/", 1)[-1]
            return {"title": "Леся Українка" if "%D0%9B%D0%B5" in t else "Іван Котляревський", "extract": ext, "description": "українська письменниця"}
        r = culture.build(date(2026, 11, 19), [], fetch, None)
        self.assertIn("Культурні діячі", r["chips"]); self.assertTrue(r["caption"].startswith("<b>"))
        self.assertNotIn("Список", r["key"])
        r2 = culture.build(date(2026, 11, 19), [r["key"]], fetch, None)
        self.assertNotEqual(r["key"], r2["key"])
        with self.assertRaises(RuntimeError):
            culture.build(date(2026, 11, 19), [r["key"], r2["key"]], fetch, None)


class BannerTests(unittest.TestCase):
    def test_banner_helper_and_build(self):
        import base64, io, json, os, tempfile
        from PIL import Image
        from digest import cat, fixed
        d = tempfile.mkdtemp()
        def call(url, key, body, t):
            if body is None:
                return {"models": []}
            b = io.BytesIO(); Image.effect_noise((500, 280), 90).convert("RGB").save(b, "JPEG")
            return {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(b.getvalue()).decode()}}]}}]}
        r = cat.build_banners("k", d, call=call)
        self.assertEqual([k for k, _, _ in r], list(cat.BANNERS))
        r1 = cat.build_banners("k", d, only="fuel", call=call)
        self.assertEqual([k for k, _, _ in r1], ["fuel"])
        # без live — звичайна картка
        self.assertEqual(fixed.banner("fuel", "DEFAULT"), "DEFAULT")


class CatBrandTests(unittest.TestCase):
    def test_mark_and_scene(self):
        import os, tempfile
        from PIL import Image
        from digest import cat
        d = tempfile.mkdtemp(); p = os.path.join(d, "a.jpg")
        Image.new("RGB", (1024, 1024), (200, 120, 40)).save(p)
        before = Image.open(p).getpixel((900, 980))
        cat.brand_mark(p)
        self.assertNotEqual(before, Image.open(p).getpixel((900, 980)))
        os.environ["CAT_SCENE"] = "кіт під дощем"
        try:
            seen = []
            def call(url, key, body, t):
                if body: seen.append(str(body))
                import base64, io
                b = io.BytesIO(); Image.effect_noise((400, 400), 90).convert("RGB").save(b, "JPEG")
                return {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(b.getvalue()).decode()}}]}}]}
            cat.build(date(2026, 11, 18), "k", d, call=call, get=lambda u, t=25: b"")
            self.assertTrue(any("кіт під дощем" in x for x in seen))
        finally:
            del os.environ["CAT_SCENE"]


class CatTests(unittest.TestCase):
    def test_theme_rotates(self):
        from digest import cat
        self.assertNotEqual(cat.theme_for(date(2026, 11, 18)), cat.theme_for(date(2026, 11, 19)))
        n = len(cat._pool())
        seen = {cat.theme_for(date.fromordinal(n * 1000 + i))[1] for i in range(n)}
        self.assertEqual(len(seen), n)  # коло без повторів

    def test_generate_and_fallback(self):
        import base64, tempfile
        from digest import cat
        png = base64.b64encode(b"x" * 6000).decode()
        def good(url, key, payload, timeout=60):
            if url.endswith("pageSize=200"):
                return {"models": [{"name": "models/gemini-x-image", "supportedGenerationMethods": ["generateContent"]}]}
            return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": png}}]}}]}
        def bad(url, key, payload, timeout=60):
            raise OSError("no")
        with tempfile.TemporaryDirectory() as d:
            r = cat.build(date(2026, 11, 18), "k", d, call=good, get=lambda u, t=25: b"y" * 6000)
            self.assertIn("ШІ-картинка", r[2]); self.assertIn("Радар", r[1]); self.assertNotIn("Кіт-Радар", r[1])
            def get(u, t=25):
                return json.dumps([{"url": "http://img"}]).encode() if "thecatapi" in u and "img" not in u else b"y" * 6000
            r = cat.build(date(2026, 11, 18), "k", d, call=bad, get=get, allow_photo=True)
            self.assertIn("недоступна", r[2])
            with self.assertRaises(RuntimeError):
                cat.build(date(2026, 11, 18), "k", d, call=bad, get=lambda u, t=25: (_ for _ in ()).throw(OSError("net")))
            jpg = b"\xff\xd8\xff" + b"z" * 6000
            r = cat.build(date(2026, 11, 18), "k", d, call=bad, get=lambda u, t=25: jpg, allow_free=True)
            self.assertIn("Pollinations", r[2])
            with self.assertRaises(RuntimeError):
                cat.build(date(2026, 11, 18), None, d, call=bad, get=lambda u, t=25: (_ for _ in ()).throw(OSError()))


if __name__ == "__main__":
    unittest.main()


class EarlyWaitTests(unittest.TestCase):
    def test_wait_until_target(self):
        from datetime import datetime, timezone
        from digest import fixed
        # 21:50 за Києвом (19:50 UTC, зима) → до 22:00 кота 600 с
        self.assertEqual(fixed.early_wait("cat", datetime(2026, 11, 18, 19, 50, tzinfo=timezone.utc)), 600)
        # занадто рано (понад WAIT_MAX) → не чекаємо
        self.assertEqual(fixed.early_wait("cat", datetime(2026, 11, 18, 19, 30, tzinfo=timezone.utc)), 0)
        # уже після цільового часу → не чекаємо
        self.assertEqual(fixed.early_wait("cat", datetime(2026, 11, 18, 20, 5, tzinfo=timezone.utc)), 0)

    def test_workflow_maps_early_and_backup_crons(self):
        import pathlib
        t = pathlib.Path(".github/workflows/radar-fixed.yml").read_text(encoding="utf-8")
        for k in ("holiday", "rates", "fuel", "figure", "culture", "ask", "fact", "expert", "cat"):
            self.assertIn(f"K={k} ;;", t)
        self.assertIn('"10 19 * * *"|"0 20 * * *") K=cat', t)
