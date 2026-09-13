"""harvest_logos.main: which stations are asked, in what order, and what
is written. The asking itself (harvest) is played by the test."""

import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import harvest_logos as harvest  # noqa: E402


class HarvestMain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)
        self.original = harvest.harvest
        self.asked = []

        def fake(station):
            self.asked.append(station["name"])
            if station["name"] == "Blue Coast FM":
                return "blue-coast-fm", "https://blue.example/logo.png"
            return None, "no usable picture"
        harvest.harvest = fake

    def tearDown(self):
        harvest.harvest = self.original
        os.chdir(self.was)
        self.dir.cleanup()

    def write(self, name, data):
        pathlib.Path(name).write_text(json.dumps(data), encoding="utf-8")

    def run_main(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = harvest.main(["harvest_logos.py", *args])
        return code, out.getvalue()

    def directory(self):
        self.write("directory.json", [
            {"name": "Blue Coast FM", "stream": "http://a/stream", "homepage": "https://blue.example/"},
            {"name": "Night Shift Radio", "stream": "http://b/stream", "homepage": ""},
            {"name": "Silent FM", "stream": "http://c/stream"},
        ])

    def test_without_a_directory_it_says_so_and_stops(self):
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("run the crawl first", out)
        self.assertEqual(self.asked, [])

    def test_stations_with_a_homepage_are_asked_and_the_logo_index_is_written(self):
        self.directory()
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.asked, ["Blue Coast FM"])
        index = json.loads(pathlib.Path("logos.json").read_text())
        self.assertEqual(list(index), ["http://a/stream"])
        self.assertEqual(index["http://a/stream"]["logo"],
                         "https://raw.githubusercontent.com/meoscar/internetradiolist/main/logos/blue-coast-fm.webp")
        self.assertEqual(index["http://a/stream"]["from"], "https://blue.example/logo.png")
        self.assertIn("1 of 3 stations publish a homepage; 0 more name a site", out)
        self.assertIn("1 logos in", out)
        self.assertIn("logos.json: 1 stations have a logo", out)

    def test_a_site_named_in_the_stream_headers_stands_in_for_a_missing_homepage(self):
        self.directory()
        self.write("station_facts.json", {
            "http://b/stream": {"icy-url": "https://night.example/"},
            "http://c/stream": {"icy-url": "https://www.facebook.com/silentfm"},
        })
        code, out = self.run_main()
        self.assertEqual(self.asked, ["Blue Coast FM", "Night Shift Radio"])
        self.assertIn("1 more name a site in their stream headers", out)
        self.assertIn("1  no usable picture", out)

    def test_missing_asks_only_the_stations_without_a_logo_and_keeps_the_ones_that_have(self):
        self.directory()
        self.write("logos.json", {"http://a/stream": {"name": "Blue Coast FM", "logo": "x", "from": "y"}})
        self.write("station_facts.json", {"http://b/stream": {"icy-url": "https://night.example/"}})
        code, out = self.run_main("--missing")
        self.assertEqual(self.asked, ["Night Shift Radio"])
        self.assertIn("1 of those 2 have no logo yet", out)
        index = json.loads(pathlib.Path("logos.json").read_text())
        self.assertEqual(index["http://a/stream"]["logo"], "x", "what was known is kept")

    def test_limit_takes_the_front_of_the_list(self):
        self.directory()
        self.write("station_facts.json", {"http://b/stream": {"icy-url": "https://night.example/"}})
        self.run_main("--limit", "1")
        self.assertEqual(self.asked, ["Blue Coast FM"])


if __name__ == "__main__":
    unittest.main()
