"""Reading the directory site's listing rows, as it writes them."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import crawl_directory as cd  # noqa: E402

ROW = '''
<tr><td>
  <h4><a href="/station/bluecoastfm/">Blue Coast FM</a></h4><br><b>Toto - Africa</b>
  <a class="small text-success" href="https://bluecoast.example/">Website</a>
  <a href="/playlistgenerator/?u=http%3A%2F%2Fa.example%3A8000%2Fstream&amp;t=.m3u">Play</a>
  Genres: <a href="/stations/rock/">Rock</a> <a href="/stations/classic%20rock/">Classic Rock</a> smooth yacht
</td><td>1,234 Listeners<br>128 Kbps</td></tr>
<tr><td><h4>No stream here</h4></td></tr>
<tr><td><h4><a href="/station/x/">Playlist Station</a></h4>
  <a href="/playlistgenerator/?u=http%3A%2F%2Fb.example%2Flive.pls&amp;t=.m3u">Play</a></td></tr>
<tr><td><h4>  </h4><a href="/playlistgenerator/?u=http%3A%2F%2Fc.example%2Fs&amp;t=.m3u">x</a></td></tr>
'''


class Rows(unittest.TestCase):
    def test_a_listing_row_becomes_a_station_with_everything_it_said(self):
        rows = cd.parse_rows(ROW, "rock")
        self.assertEqual(len(rows), 2)
        s = rows[0]
        self.assertEqual(s["name"], "Blue Coast FM")
        self.assertEqual(s["stream"], "http://a.example:8000/stream")
        self.assertEqual(s["page"], "https://www.internet-radio.com/station/bluecoastfm/")
        self.assertEqual(s["now_playing"], "Toto - Africa")
        self.assertEqual(s["homepage"], "https://bluecoast.example/")
        self.assertEqual(s["genres"], ["classic rock", "rock"])
        self.assertEqual(s["tags"], ["smooth", "yacht"])
        self.assertEqual((s["listeners"], s["bitrate"]), (1234, 128))
        self.assertNotIn("needs_resolving", s)

    def test_a_playlist_link_is_marked_for_resolving_and_a_nameless_row_is_dropped(self):
        rows = cd.parse_rows(ROW, "rock")
        self.assertEqual(rows[1]["stream"], "http://b.example/live.pls")
        self.assertTrue(rows[1]["needs_resolving"])
        self.assertEqual(rows[1]["genres"], ["rock"])

    def test_tags_and_entities_are_text(self):
        self.assertEqual(cd.text_of("<b>Rock &amp; Roll</b>"), "Rock & Roll")


class Pages(unittest.TestCase):
    def test_links_under_the_listing_that_end_in_a_number_are_its_pages(self):
        base = "https://www.internet-radio.com/stations/rock/"
        page = '<a href="?page=2">2</a> <a href="/stations/rock/page/3">3</a> <a href="/stations/jazz/2">no</a> <a href="https://elsewhere/4">no</a>'
        self.assertEqual(cd.page_links(page, base), {2: base + "?page=2", 3: base + "page/3"})


class Robots(unittest.TestCase):
    def test_disallowed_paths_are_not_fetched_and_the_budget_holds(self):
        self.assertTrue(cd.allowed(cd.BASE + "stations/rock/"))
        self.assertFalse(cd.allowed(cd.BASE + cd.DISALLOWED[0].lstrip("/")))
        f = cd.Fetcher(budget=0)
        self.assertIsNone(f.get(cd.BASE + "stations/rock/"))
        f = cd.Fetcher(budget=5)
        self.assertIsNone(f.get(cd.BASE + cd.DISALLOWED[0].lstrip("/")))
        self.assertEqual(f.made, 0)


class Decoding(unittest.TestCase):
    class Headers:
        def __init__(self, charset): self.charset = charset
        def get_content_charset(self): return self.charset

    def test_the_declared_charset_then_utf8_then_windows_1252(self):
        self.assertEqual(cd.decode("Rádio".encode("latin-1"), self.Headers("iso-8859-1")), "Rádio")
        self.assertEqual(cd.decode("Rádio".encode("utf-8"), self.Headers(None)), "Rádio")
        self.assertEqual(cd.decode("Rádio".encode("cp1252"), self.Headers(None)), "Rádio")
        self.assertEqual(cd.decode(b"plain", object()), "plain")
        self.assertEqual(cd.decode(b"x", self.Headers("no-such-charset")), "x")


if __name__ == "__main__":
    unittest.main()
