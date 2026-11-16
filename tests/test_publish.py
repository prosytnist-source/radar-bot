import pathlib, tempfile, unittest
from unittest import mock
from digest import publish


class Pub(unittest.TestCase):
    def test_dry_run_sends_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            pathlib.Path(d, "01-uk.html").write_text("<b>x</b>", encoding="utf-8")
            with mock.patch.object(publish, "env", return_value="v"), mock.patch.object(publish, "send") as s:
                self.assertEqual(publish.main(["--send", d]), 0)
                s.assert_not_called()
                publish.main(["--send", d, "--yes"])
                s.assert_called_once()


if __name__ == "__main__":
    unittest.main()
