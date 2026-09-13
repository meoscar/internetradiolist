"""The song line as live_now.py reads it before deciding whether to publish."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import live_now  # noqa: E402


class SplitLine(unittest.TestCase):
    def test_artist_and_title_on_the_first_dash(self):
        self.assertEqual(live_now.split_line("Toto - Africa - Live"), ("Toto", "Africa - Live"))

    def test_a_title_alone(self):
        self.assertEqual(live_now.split_line("Funkytown"), ("", "Funkytown"))


if __name__ == "__main__":
    unittest.main()
