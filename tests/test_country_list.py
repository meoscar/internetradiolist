"""A country edition's list, from the probe's rows: what is kept, what is dropped and why."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import country_list  # noqa: E402
import build_catalogue  # noqa: E402


def row(name, url, votes=0, **more):
    return {"name": name, "url": url, "url_resolved": url, "votes": votes, **more}


class Build(unittest.TestCase):
    def test_every_reachable_station_is_kept_once_most_voted_first(self):
        rows = [row("B", "http://b", 5), row("A", "http://a", 9), row("A", "http://a2", 1),
                row("C", "http://c", 3), row("D", "http://b", 2)]
        streams = {u: {"reachable": True} for u in ("http://a", "http://a2", "http://b", "http://c")}
        kept, dropped = country_list.build(rows, streams)
        self.assertEqual([s["name"] for s in kept], ["A", "B", "C"])
        self.assertIn(("A", "the same name, already kept"), dropped)
        self.assertIn(("D", "the same stream, already kept"), dropped)

    def test_a_stream_that_did_not_answer_is_dropped_with_the_reason(self):
        kept, dropped = country_list.build([row("Dead", "http://d")], {"http://d": {"reachable": False}})
        self.assertEqual(kept, [])
        self.assertEqual(dropped, [("Dead", "the stream did not answer when probed")])

    def test_what_is_not_a_station_by_its_name_is_dropped_without_a_hand_list(self):
        rows = [row("https://example.com", "http://x"), row("Radio Test 2", "http://y"),
                row("Canal 5 TV", "http://z"), row("Fine FM", "http://f")]
        streams = {u: {"reachable": True} for u in ("http://x", "http://y", "http://z", "http://f")}
        kept, dropped = country_list.build(rows, streams)
        self.assertEqual([s["name"] for s in kept], ["Fine FM"])
        self.assertEqual({why for _, why in dropped}, {"not a radio station, by its name"})

    def test_a_hand_exclusion_wins_with_its_own_reason(self):
        kept, dropped = country_list.build([row("Across the strait", "http://s")],
                                           {"http://s": {"reachable": True}},
                                           {"Across the strait": "broadcasts from elsewhere"})
        self.assertEqual(kept, [])
        self.assertEqual(dropped, [("Across the strait", "broadcasts from elsewhere")])

    def test_the_cap_keeps_the_most_voted_that_answer_and_says_so(self):
        rows = [row(f"S{i}", f"http://{i}", votes=i) for i in range(5)]
        streams = {f"http://{i}": {"reachable": i != 4} for i in range(5)}
        kept, dropped = country_list.build(rows, streams, keep=2)
        self.assertEqual([s["name"] for s in kept], ["S3", "S2"])
        self.assertIn(("S1", "beyond the 2 most voted that answer"), dropped)
        self.assertIn(("S4", "the stream did not answer when probed"), dropped)

    def test_what_a_kept_row_carries(self):
        rows = [row("Fine FM", "http://f", 7, homepage="https://fine.fm", favicon="https://fine.fm/i.png",
                    tags="pop, news ,", codec="mp3")]
        kept, _ = country_list.build(rows, {"http://f": {"reachable": True, "hls": False}})
        self.assertEqual(kept[0], {"name": "Fine FM", "stream": "http://f", "homepage": "https://fine.fm",
                                   "favicon": "https://fine.fm/i.png", "tags": ["pop", "news"],
                                   "votes": 7, "codec": "MP3", "hls": False, "site": ""})

    def test_filed_under_the_code_touches_nothing_else(self):
        out = country_list.filed_under({"http://old": "TW"}, [{"stream": "http://j"}], "JP")
        self.assertEqual(out, {"http://old": "TW", "http://j": "JP"})


class Editions(unittest.TestCase):
    def test_each_country_file_with_a_heading_is_read_and_condemned_streams_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            here = pathlib.Path(d) / "countries"
            here.mkdir()
            (here / "jp.json").write_text(json.dumps([{"name": "A", "stream": "http://a"},
                                                      {"name": "B", "stream": "http://b"}]))
            (here / "zz.json").write_text(json.dumps([{"name": "Z", "stream": "http://z"}]))
            (here / "notes.json").write_text("[]")
            old = build_catalogue.COUNTRIES_DIR
            build_catalogue.COUNTRIES_DIR = str(here)
            try:
                editions = build_catalogue.country_editions(condemned={"http://b"})
            finally:
                build_catalogue.COUNTRIES_DIR = old
        self.assertEqual(editions, [("JP", [{"name": "A", "stream": "http://a"}])])

    def test_every_heading_is_an_upper_case_word_the_app_can_file_under(self):
        for code, heading in build_catalogue.COUNTRY_HEADINGS.items():
            self.assertEqual(len(code), 2)
            self.assertEqual(heading, heading.upper())
            self.assertTrue(heading.isalpha())


if __name__ == "__main__":
    unittest.main()
