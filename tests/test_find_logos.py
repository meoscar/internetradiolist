"""Where a logo is looked for, in what order, and what the run writes."""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from PIL import Image  # noqa: E402
import find_logos  # noqa: E402
import harvest_logos as harvest  # noqa: E402
import probe_radio_browser as radio_browser  # noqa: E402


def png(width, height):
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for x in range(width):
        for y in range(height):
            v = (x * 7 + y * 13) % 256
            pixels[x, y] = (v, (v * 3) % 256, 255 - v) if ((x // 3) + (y // 3)) % 2 else (255 - v, v, v)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class InAWorkingDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)
        self.original_fetch = harvest.fetch
        self.answers = {}
        harvest.fetch = self.fetch

    def tearDown(self):
        harvest.fetch = self.original_fetch
        os.chdir(self.was)
        self.dir.cleanup()

    def fetch(self, url, limit=0):
        if url not in self.answers:
            raise OSError("no such page")
        return self.answers[url]

    def finder(self, by_url=None, by_name=None, facts=None):
        return find_logos.Finder(by_url or {}, by_name or {}, facts or {})


class RadioBrowserRow(InAWorkingDir):
    def test_by_stream_first_then_by_a_name_only_one_station_has_whose_site_agrees(self):
        row = {"name": "Blue Coast FM", "homepage": "https://blue.example/", "favicon": ""}
        f = self.finder(by_url={radio_browser.normalise("http://a/stream"): row})
        self.assertEqual(f.radio_browser_row({"stream": "http://a/stream"}), (row, "by stream"))
        f = self.finder(by_name={"bluecoastfm": [row]})
        self.assertEqual(f.radio_browser_row({"stream": "http://x", "name": "Blue Coast FM", "homepage": ""}), (row, "by name"))
        self.assertEqual(f.radio_browser_row({"stream": "http://x", "name": "Blue Coast FM", "homepage": "https://other.example/"}), (None, None))
        f = self.finder(by_name={"bluecoastfm": [row, dict(row)]})
        self.assertEqual(f.radio_browser_row({"stream": "http://x", "name": "Blue Coast FM"}), (None, None))

    def test_the_sites_known_for_a_station_best_first_one_per_host(self):
        f = self.finder(facts={"http://stream.a.example:8000/s": {"icy-url": "www.a.example"}})
        station = {"stream": "http://stream.a.example:8000/s", "homepage": "https://blue.example/"}
        self.assertEqual(f.sites(station, {"homepage": "https://rb.example/"}), [
            "https://blue.example/", "http://www.a.example", "https://rb.example/", "http://stream.a.example:8000/"])
        # One site per host: www.a.example and a.example are the same place.
        self.assertEqual(f.sites({"stream": "http://a.example/s", "homepage": "http://www.a.example/"}, None),
                         ["http://www.a.example/"])
        self.assertEqual(f.sites({"stream": "", "homepage": ""}, None), [])
        self.assertIsNone(find_logos.Finder.stream_root({"stream": "http://[::1"}))
        self.assertIsNone(find_logos.Finder.stream_root({"stream": "nothing"}))


class Find(InAWorkingDir):
    def test_radio_browsers_favicon_comes_first_when_it_is_a_picture(self):
        row = {"name": "Blue Coast FM", "favicon": "https://rb.example/fav.png"}
        self.answers["https://rb.example/fav.png"] = png(96, 96)
        f = self.finder(by_url={radio_browser.normalise("http://a/s"): row})
        slug, note = f.find({"name": "Blue Coast FM", "stream": "http://a/s"})
        self.assertEqual(slug, "bluecoastfm")
        self.assertTrue(note.startswith("radio-browser favicon (by stream)"), note)

    def test_then_the_stations_own_site_unless_the_weekly_harvest_already_read_it(self):
        self.answers["https://blue.example/"] = b'<meta property="og:image" content="/logo.png">'
        self.answers["https://blue.example/logo.png"] = png(120, 120)
        station = {"name": "Blue Coast FM", "stream": "http://a/s", "homepage": "https://blue.example/"}
        f = self.finder()
        self.assertTrue(f.find(dict(station, harvested=False))[1].startswith("site, its own site"))
        # Already harvested: the listed site is skipped and the stream host's page is the next.
        slug, note = f.find(station)
        self.assertIsNone(slug)

    def test_then_the_icon_services_for_each_host_and_a_globe_is_not_an_icon(self):
        f = self.finder()
        f.globe = b"GLOBE"
        host = "a.example"
        self.answers[find_logos.GOOGLE.format(host=host)] = b"GLOBE"
        self.answers[find_logos.GSTATIC.format(host=host)] = png(30, 30)
        slug, note = f.find({"name": "Blue Coast FM", "stream": f"http://{host}/s", "homepage": ""})
        self.assertEqual(slug, "bluecoastfm")
        self.assertTrue(note.startswith("gstatic icon service on a tile"), note)

    def test_nothing_anywhere_says_why(self):
        f = self.finder()
        self.assertEqual(f.find({"name": "!!", "stream": "http://a/s"}), (None, "no usable name"))
        self.assertEqual(f.find({"name": "A", "stream": "", "homepage": ""}), (None, "no site known anywhere"))
        slug, note = f.find({"name": "A", "stream": "http://a.example/s", "homepage": ""})
        self.assertIsNone(slug)
        self.assertIn("google OSError", note)


class Main(InAWorkingDir):
    def test_a_run_looks_for_the_missing_logos_and_writes_the_index(self):
        # A directory station's own site was read by the weekly harvest already
        # and is not read again; a station only the catalogue knows has not
        # been, and its site is the first place looked.
        pathlib.Path("directory.json").write_text(json.dumps([
            {"name": "Has One", "stream": "http://has/s"},
            {"name": "Nobody", "stream": "http://n/s"}]))
        pathlib.Path("logos.json").write_text(json.dumps({"http://has/s": {"name": "Has One", "logo": "x"}}))
        pathlib.Path("music_worldradio.json").write_text(json.dumps({"music": [
            {"title": "Blue Coast FM", "source": "http://a/s", "site": "https://blue.example/"}]}))
        self.answers["https://blue.example/"] = b'<meta property="og:image" content="/logo.png">'
        self.answers["https://blue.example/logo.png"] = png(120, 120)
        original = find_logos.radio_browser_index
        find_logos.radio_browser_index = lambda: ({}, {})
        try:
            with redirect_stdout(io.StringIO()) as out:
                code = find_logos.main(["find_logos.py", "--only", "coast"])
        finally:
            find_logos.radio_browser_index = original
        self.assertEqual(code, 0)
        index = json.loads(pathlib.Path("logos.json").read_text())
        self.assertIn("http://a/s", index)
        self.assertTrue(index["http://a/s"]["logo"].endswith("/logos/bluecoastfm.webp"))
        self.assertIn("FOUND", out.getvalue())
        self.assertNotIn("http://n/s", index)

    def test_the_radio_browser_index_survives_no_mirror(self):
        original = radio_browser.working_mirror
        radio_browser.working_mirror = lambda: (None, None)
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(find_logos.radio_browser_index(), ({}, {}))
        finally:
            radio_browser.working_mirror = original
        orig_mirror, orig_download = radio_browser.working_mirror, radio_browser.download
        radio_browser.working_mirror = lambda: ("https://rb", {})
        radio_browser.download = lambda base, cap: [{"name": "Blue Coast FM", "url": "http://a/s/", "url_resolved": "https://a/s"}]
        try:
            with redirect_stdout(io.StringIO()):
                by_url, by_name = find_logos.radio_browser_index()
        finally:
            radio_browser.working_mirror, radio_browser.download = orig_mirror, orig_download
        self.assertEqual(set(by_url), {"a/s"})
        self.assertEqual(list(by_name), ["bluecoastfm"])


class RadioBrowserHelpers(unittest.TestCase):
    def test_a_stream_and_a_name_reduced_to_what_two_directories_agree_on(self):
        self.assertEqual(radio_browser.normalise("HTTP://A.Example:80/Live/"), "a.example/Live")
        self.assertEqual(radio_browser.normalise("http://a.example:8000/live"), "a.example:8000/live")
        self.assertEqual(radio_browser.normalise(""), "")
        self.assertEqual(radio_browser.normalise("http://[::1"), "")
        self.assertEqual(radio_browser.bare_name("Radio Grün Weiß"), "radiogrunweiss")
        self.assertEqual(radio_browser.bare_name("RADIO GRUN-WEISS"), "radiogrunweiss")


if __name__ == "__main__":
    unittest.main()
