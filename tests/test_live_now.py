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


class AsStation(unittest.TestCase):
    by_source = {"http://a/stream": {"id": "https://a.example/", "title": "Blue Coast FM",
                                     "image": "https://a.example/logo.png", "genre": "rock"}}

    def test_a_count_is_told_in_the_apps_own_terms(self):
        entry = live_now.as_station("http://a/stream", {"name": "blue coast", "genre": "pop", "listeners": 42},
                                    self.by_source, {"https://a.example/": "Toto - Africa"})
        self.assertEqual(entry["id"], "https://a.example/")
        self.assertEqual(entry["station"], "Blue Coast FM")
        self.assertEqual(entry["image"], "https://a.example/logo.png")
        self.assertEqual((entry["genre"], entry["listeners"]), ("pop", 42))
        self.assertEqual(entry["track"], "Toto - Africa")

    def test_a_station_we_cannot_play_counts_towards_nothing(self):
        self.assertIsNone(live_now.as_station("http://b/stream", {"name": "B", "genre": "pop", "listeners": 9},
                                              self.by_source, {}))

    def test_no_track_means_no_track_key(self):
        entry = live_now.as_station("http://a/stream", {"name": "x", "genre": "pop", "listeners": 1},
                                    self.by_source, {})
        self.assertNotIn("track", entry)


class Busiest(unittest.TestCase):
    def test_the_stations_most_people_were_listening_to_come_first(self):
        by_source = {f"http://{n}/stream": {"source": f"http://{n}/stream", "title": n} for n in ("a", "b", "c")}
        directory = [{"stream": "http://b/stream", "listeners": 300}, {"stream": "http://c/stream", "listeners": 20}]
        rows = live_now.busiest_stations(by_source, directory, 2)
        self.assertEqual([r["title"] for r in rows], ["b", "c"])
