"""How many are listening, read off the three kinds of status page."""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import station_status  # noqa: E402


class Icecast(unittest.TestCase):
    def test_the_busiest_mount_on_the_server_is_the_count(self):
        body = json.dumps({"icestats": {"source": [
            {"listeners": 12, "listenurl": "http://a/low"},
            {"listeners": 40, "listenurl": "http://a/high"},
            {"listeners": "many"}, {"listeners": True}, {"listeners": -3}, "junk"]}})
        self.assertEqual(station_status._icecast(body.encode()), 40)

    def test_one_mount_is_not_a_list_and_still_counts(self):
        body = json.dumps({"icestats": {"source": {"listeners": 7}}})
        self.assertEqual(station_status._icecast(body.encode()), 7)

    def test_no_source_or_no_json_is_no_count(self):
        self.assertIsNone(station_status._icecast(b'{"icestats": {}}'))
        self.assertIsNone(station_status._icecast(b"<html>"))
        self.assertIsNone(station_status._icecast(json.dumps({"icestats": {"source": [{"listeners": "x"}]}}).encode()))


class Shoutcast(unittest.TestCase):
    def test_v2_reads_the_current_listeners(self):
        self.assertEqual(station_status._shoutcast_v2(b'{"currentlisteners": 5}'), 5)
        self.assertIsNone(station_status._shoutcast_v2(b'{"currentlisteners": -1}'))
        self.assertIsNone(station_status._shoutcast_v2(b'{"currentlisteners": true}'))
        self.assertIsNone(station_status._shoutcast_v2(b"nope"))

    def test_v1_is_seven_fields_with_the_count_first_and_a_title_that_may_have_commas(self):
        self.assertEqual(station_status._shoutcast_v1(b"<html><body>23,1,50,100,20,128,Toto - Africa, Live</body></html>"), 23)
        self.assertIsNone(station_status._shoutcast_v1(b"An error page, with, some, commas, in, it, here"))
        self.assertIsNone(station_status._shoutcast_v1(b"1,2,3"))


class ListenersOf(unittest.TestCase):
    def fetch_from(self, answers):
        def fake(url, limit=200_000):
            return answers.get(url.rsplit("/", 1)[-1] if "/status-json.xsl" not in url else "status-json.xsl")
        return fake

    def test_icecast_first_then_shoutcast_v2_then_v1(self):
        original = station_status._fetch
        try:
            station_status._fetch = self.fetch_from({"status-json.xsl": b'{"icestats": {"source": {"listeners": 9}}}'})
            self.assertEqual(station_status.listeners_of("http://a.example:8000/stream"), 9)
            station_status._fetch = self.fetch_from({"stats?json=1": b'{"currentlisteners": 4}'})
            self.assertEqual(station_status.listeners_of("http://a.example:8000/stream"), 4)
            station_status._fetch = self.fetch_from({"7.html": b"2,1,9,9,2,128,Song"})
            self.assertEqual(station_status.listeners_of("http://a.example:8000/stream"), 2)
            station_status._fetch = self.fetch_from({})
            self.assertIsNone(station_status.listeners_of("http://a.example:8000/stream"))
        finally:
            station_status._fetch = original

    def test_a_stream_url_with_no_host_is_not_asked(self):
        self.assertIsNone(station_status.listeners_of("not a url"))
        self.assertIsNone(station_status.listeners_of(None))

    def test_the_fetch_itself_swallows_failures(self):
        self.assertIsNone(station_status._fetch("http://127.0.0.1:1/never"))


if __name__ == "__main__":
    unittest.main()
