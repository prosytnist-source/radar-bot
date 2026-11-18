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
