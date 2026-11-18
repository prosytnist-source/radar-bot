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


if __name__ == "__main__":
    unittest.main()
