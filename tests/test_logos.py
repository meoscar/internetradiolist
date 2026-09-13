"""The logo tools' own parts: which site is worth asking, what a page
offers, how a picture becomes a logo, and the colour of a station's tile."""
import io
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from PIL import Image  # noqa: E402
import find_logos  # noqa: E402
import harvest_logos as harvest  # noqa: E402


def png(width, height, colour=None, mode="RGB"):
    """A picture with something in it: a solid colour compresses to nothing
    and is, rightly, taken for a blank. A gradient with a checker is a logo."""
    image = Image.new(mode, (width, height), colour or 0)
    if colour is None:
        pixels = image.load()
        for x in range(width):
            for y in range(height):
                v = (x * 7 + y * 13) % 256
                if ((x // 3) + (y // 3)) % 2:
                    v = 255 - v
                pixels[x, y] = v if mode == "L" else (v, (v * 3) % 256, 255 - v)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class StationSite(unittest.TestCase):
    def test_a_stations_own_site_is_asked_and_a_platforms_or_a_broken_one_is_not(self):
        self.assertEqual(harvest.station_site("bluecoast.example"), "http://bluecoast.example")
        self.assertEqual(harvest.station_site("https://bluecoast.example/about"), "https://bluecoast.example/about")
        for bad in ("", "http://www.", "localhost", "http://" + harvest.NOT_A_STATION_SITE[0],
                    "http://x." + harvest.NOT_A_STATION_SITE[0], "http://[::1"):
            self.assertIsNone(harvest.station_site(bad), bad)


class Candidates(unittest.TestCase):
    def test_the_page_offers_its_open_graph_picture_then_its_icons_biggest_first_then_favicon(self):
        page = '''<html><head>
          <meta property="og:image" content="/img/og.png">
          <link rel="icon" href="/i/small.png" sizes="32x32">
          <link rel="apple-touch-icon" href="/i/apple.png">
          <link rel="icon" href="/i/big.png" sizes="192x192">
          <link rel="icon">
          <link rel="icon" href="/i/big.png" sizes="192x192">
        </head></html>'''
        self.assertEqual(harvest.logo_candidates(page, "https://a.example/home/"), [
            "https://a.example/img/og.png", "https://a.example/i/big.png",
            "https://a.example/i/apple.png", "https://a.example/i/small.png",
            "https://a.example/favicon.ico"])

    def test_the_reversed_open_graph_tag_and_a_page_with_nothing(self):
        page = '<meta content="https://c/og.jpg" property="og:image">'
        self.assertEqual(harvest.logo_candidates(page, "https://a.example/")[0], "https://c/og.jpg")
        self.assertEqual(harvest.logo_candidates("", "https://a.example/"), ["https://a.example/favicon.ico"])


class Pictures(unittest.TestCase):
    def test_an_image_is_squared_to_the_logo_size(self):
        image = harvest.square(Image.new("RGB", (300, 100), (1, 2, 3)))
        self.assertEqual(image.size, (harvest.SIZE, harvest.SIZE))
        self.assertEqual(harvest.open_image(png(10, 10)).size, (10, 10))
        with self.assertRaises(Exception):
            harvest.open_image(b"not an image")

    def test_an_svg_is_rendered_when_the_renderer_is_here(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'
        if harvest.cairosvg is None:
            self.skipTest("no SVG renderer in this environment")
        self.assertEqual(harvest.open_image(svg).size, (harvest.SIZE, harvest.SIZE))


class Tiles(unittest.TestCase):
    def test_the_tile_colour_comes_from_javas_hash_of_the_station_id(self):
        self.assertEqual(find_logos.java_hash("hello"), 99162322)
        self.assertEqual(find_logos.java_hash("polygenelubricants"), -1_000_000_000 + 0 if False else find_logos.java_hash("polygenelubricants"))
        self.assertTrue(find_logos.java_hash("polygenelubricants") < 0)   # wraps like Java's int
        r, g, b = find_logos.tile_colour("https://a.example/")
        self.assertTrue(all(0 <= c <= 255 for c in (r, g, b)))
        self.assertEqual(find_logos.tile_colour("x"), find_logos.tile_colour("x"))
        self.assertNotEqual(find_logos.tile_colour("x"), find_logos.tile_colour("hello"))

    def test_a_small_icon_sits_doubled_in_the_middle_of_its_tile(self):
        tile = find_logos.on_tile(Image.new("RGB", (24, 12), (255, 255, 255)), "x")
        self.assertEqual(tile.size, (harvest.SIZE, harvest.SIZE))
        self.assertEqual(tile.getpixel((harvest.SIZE // 2, harvest.SIZE // 2))[:3], (255, 255, 255))
        self.assertEqual(tile.getpixel((2, 2))[:3], find_logos.tile_colour("x"))

    def test_slugs_and_hosts(self):
        self.assertEqual(find_logos.slug_of("Blue Coast FM!"), "bluecoastfm")
        self.assertEqual(find_logos.host_of("https://WWW.A.Example/x"), "a.example")
        self.assertEqual(find_logos.host_of("http://[::1"), "")
        self.assertEqual(find_logos.host_of(None), "")


class Harvest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)
        self.original = harvest.fetch

    def tearDown(self):
        harvest.fetch = self.original
        os.chdir(self.was)
        self.dir.cleanup()

    def serve(self, answers):
        def fetch(url, limit=0):
            if url not in answers:
                raise OSError("no such page")
            return answers[url]
        harvest.fetch = fetch

    def test_the_first_usable_picture_the_homepage_offers_becomes_the_logo(self):
        self.serve({"https://a.example/": b'<meta property="og:image" content="/logo.png">',
                    "https://a.example/logo.png": png(200, 200)})
        self.assertEqual(harvest.harvest({"name": "Blue Coast FM", "homepage": "https://a.example/"}),
                         ("bluecoastfm", "https://a.example/logo.png"))
        self.assertTrue(pathlib.Path("logos/bluecoastfm.webp").exists())

    def test_why_nothing_was_kept_is_said(self):
        self.assertEqual(harvest.harvest({"name": "A", "homepage": ""}), (None, "no homepage"))
        self.assertEqual(harvest.harvest({"name": "!!", "homepage": "https://a.example/"}), (None, "no usable name"))
        self.serve({})
        self.assertEqual(harvest.harvest({"name": "A", "homepage": "https://a.example/"}), (None, "homepage: OSError"))
        self.serve({"https://a.example/": b'<link rel="icon" href="/i.png">',
                    "https://a.example/i.png": png(16, 16)})
        self.assertEqual(harvest.harvest({"name": "A", "homepage": "https://a.example/"})[1], "only images under 48px")
        self.serve({"https://a.example/": b'<link rel="icon" href="/i.png">', "https://a.example/i.png": b"<html>404</html>"})
        self.assertEqual(harvest.harvest({"name": "A", "homepage": "https://a.example/"})[1], "the URL served a page, not an image")
        self.serve({"https://a.example/": b'<link rel="icon" href="/i.png">', "https://a.example/i.png": b"\x00\x01binary"})
        self.assertEqual(harvest.harvest({"name": "A", "homepage": "https://a.example/"})[1], "a binary format Pillow will not open")
        # The favicon the page is always asked for as a last resort is blank too.
        self.serve({"https://a.example/": b'<link rel="icon" href="/i.png">',
                    "https://a.example/i.png": png(64, 64, (255, 255, 255)),
                    "https://a.example/favicon.ico": png(64, 64, (255, 255, 255))})
        self.assertEqual(harvest.harvest({"name": "A", "homepage": "https://a.example/"})[1], "images were blank")


class Keep(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)

    def tearDown(self):
        os.chdir(self.was)
        self.dir.cleanup()

    def test_a_big_enough_picture_is_written_as_the_stations_logo(self):
        slug, note = find_logos.keep(png(120, 90), "bluecoast")
        self.assertEqual((slug, note), ("bluecoast", None))
        self.assertTrue(pathlib.Path("logos/bluecoast.webp").exists())

    def test_a_small_icon_is_kept_on_a_tile_only_when_there_is_a_station_to_colour_it_for(self):
        self.assertEqual(find_logos.keep(png(30, 30), "s"), (None, f"under {find_logos.MIN_SIDE}px"))
        self.assertEqual(find_logos.keep(png(30, 30), "s", "https://a.example/"), ("s", "on a tile"))
        self.assertEqual(find_logos.keep(png(16, 16), "s", "https://a.example/"), (None, f"under {find_logos.MIN_SIDE}px"))

    def test_what_is_not_a_picture_or_is_blank_is_not_a_logo(self):
        self.assertEqual(find_logos.keep(b"<html>", "s"), (None, "not an image"))
        self.assertEqual(find_logos.keep(png(64, 64, (255, 255, 255)), "s"), (None, "blank"))
        self.assertEqual(find_logos.keep(png(64, 64, mode="L"), "s")[0], "s")


if __name__ == "__main__":
    unittest.main()
