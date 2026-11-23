import unittest
from digest import fixed


class RubricOff(unittest.TestCase):
    def test_cat_off_does_nothing(self):
        orig = fixed.rubric_mode
        fixed.rubric_mode = lambda kind: "off" if kind == "cat" else orig(kind)
        try:
            self.assertEqual(fixed.main(["--kind", "cat"]), 0)
        finally:
            fixed.rubric_mode = orig


if __name__ == "__main__":
    unittest.main()
