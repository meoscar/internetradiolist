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


class SilentStations(unittest.TestCase):
    by_source = {
        "http://a/stream": {"source": "http://a/stream", "title": "A"},
        "http://b/stream": {"source": "http://b/stream", "title": "B"},
        "http://c/stream": {"source": "http://c/stream", "title": "C"},
        "http://d/stream": {"source": "http://d/stream", "title": "D"},
    }
    directory = [{"stream": "http://a/stream", "listeners": 900}, {"stream": "http://b/stream", "listeners": 50},
                 {"stream": "http://c/stream", "listeners": 200}, {"stream": "http://d/stream", "listeners": 5}]
    facts = {"http://a/stream": {"icy-metaint": "16000"}, "http://b/stream": {"ok": True},
             "http://c/stream": {"ok": True}, "http://d/stream": {}}

    def test_the_stations_with_no_metadata_channel_are_asked_too_busiest_first_and_not_twice(self):
        busiest = live_now.busiest_stations(self.by_source, self.directory, 1)
        self.assertEqual([r["title"] for r in busiest], ["A"])
        silent = live_now.silent_stations(self.by_source, self.directory, self.facts, 10, already=busiest)
        self.assertEqual([r["title"] for r in silent], ["C", "B", "D"])
        self.assertEqual([r["title"] for r in live_now.silent_stations(self.by_source, self.directory, self.facts, 1)], ["C"])
        self.assertEqual(live_now.silent_stations(self.by_source, self.directory, {}, 10), [])


class Interrogate(unittest.TestCase):
    def setUp(self):
        self.icy, self.status = live_now.harvest_icy.interrogate, live_now.station_status.status_of

    def tearDown(self):
        live_now.harvest_icy.interrogate, live_now.station_status.status_of = self.icy, self.status

    def test_the_streams_word_first_and_the_status_document_where_the_stream_is_silent(self):
        live_now.harvest_icy.interrogate = lambda url: {
            "http://a/stream": {"ok": True, "stream_title": "Toto - Africa"},
            "http://b/stream": {"ok": True, "stream_title": ""},
            "http://c/stream": {"ok": False},
            "http://d/stream": {"ok": True, "stream_title": ""},
        }[url]
        live_now.station_status.status_of = lambda url: {
            "http://a/stream": {"listeners": 40, "title": "Chic - Le Freak", "via": "icecast"},
            "http://b/stream": {"listeners": 3, "title": "Adele - Hello", "via": "shoutcast"},
            "http://c/stream": {"listeners": None, "title": "Now Playing info goes here", "via": "shoutcast"},
            "http://d/stream": {"listeners": 9, "title": None, "via": "icecast"},
        }[url]
        rows = [{"source": s, "id": s, "title": n} for s, n in
                [("http://a/stream", "A"), ("http://b/stream", "B"), ("http://c/stream", "C"), ("http://d/stream", "D")]]
        playing, counts = live_now.interrogate(rows)
        self.assertEqual({p["id"]: p["track"] for p in playing},
                         {"http://a/stream": "Toto - Africa", "http://b/stream": "Adele - Hello"})
        self.assertEqual(counts, {"http://a/stream": 40, "http://b/stream": 3, "http://d/stream": 9})


if __name__ == "__main__":
    unittest.main()
