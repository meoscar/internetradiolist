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


class Titles(unittest.TestCase):
    """The record on, from the same three documents that carry the count."""

    def test_icecast_names_the_record_on_its_busiest_mount(self):
        body = json.dumps({"icestats": {"source": [
            {"listeners": 3, "title": "Chic - Le Freak"},
            {"listeners": 40, "yp_currently_playing": "Toto - Africa"},
            {"listeners": 900, "title": "12345"}]}}).encode()
        self.assertEqual(station_status._icecast_title(body), "Toto - Africa")
        one = json.dumps({"icestats": {"source": {"title": "Chic - Le Freak"}}}).encode()
        self.assertEqual(station_status._icecast_title(one), "Chic - Le Freak")
        self.assertIsNone(station_status._icecast_title(b"<html>"))
        self.assertIsNone(station_status._icecast_title(json.dumps({"icestats": {}}).encode()))

    def test_shoutcast_v2_and_v1_name_the_record_and_never_a_number(self):
        self.assertEqual(station_status._shoutcast_v2_title(b'{"songtitle": " Toto - Africa "}'), "Toto - Africa")
        self.assertIsNone(station_status._shoutcast_v2_title(b'{"songtitle": "128"}'))
        self.assertIsNone(station_status._shoutcast_v2_title(b"nope"))
        self.assertEqual(station_status._shoutcast_v1_title(b"<html><body>12,1,40,100,10,128,Toto - Africa, Live</body></html>"),
                         "Toto - Africa, Live")
        self.assertIsNone(station_status._shoutcast_v1_title(b"12,1,40,100,10,128,128"))
        self.assertIsNone(station_status._shoutcast_v1_title(b"Not Found"))

    def test_a_body_that_was_never_text_names_nothing(self):
        noise = "12,1,40,100,10,128,\ufffdd\ufffdN\x00\x11XZ=j\ufffd".encode("utf-8", "surrogatepass")
        self.assertIsNone(station_status._shoutcast_v1_title(noise))
        self.assertIsNone(station_status._shoutcast_v2_title(b'{"songtitle": "\\u0007ring"}'))
        self.assertIsNone(station_status._icecast_title(
            json.dumps({"icestats": {"source": {"title": "\ufffd\ufffd"}}}).encode()))
        self.assertIsNone(station_status._text("\x00"))
        self.assertIsNone(station_status._text(""))
        self.assertIsNone(station_status._text("2024"))
        self.assertEqual(station_status._text("Toto -\tAfrica"), "Toto -\tAfrica")

    def test_status_of_answers_both_questions_from_the_first_document_that_speaks(self):
        answers = {
            "http://a/status-json.xsl": json.dumps({"icestats": {"source": {"listeners": 7, "title": "Toto - Africa"}}}).encode(),
            "http://b/status-json.xsl": None,
            "http://b/stats?json=1": b'{"currentlisteners": 3, "songtitle": "Chic - Le Freak"}',
            "http://c/status-json.xsl": None, "http://c/stats?json=1": None,
            "http://c/7.html": b"9,1,40,100,10,128,Adele - Hello",
            "http://d/status-json.xsl": None, "http://d/stats?json=1": None, "http://d/7.html": None,
        }
        original = station_status._fetch
        station_status._fetch = lambda url, limit=0: answers.get(url)
        try:
            self.assertEqual(station_status.status_of("http://a/stream"), {"listeners": 7, "title": "Toto - Africa", "via": "icecast"})
            self.assertEqual(station_status.status_of("http://b/stream"), {"listeners": 3, "title": "Chic - Le Freak", "via": "shoutcast"})
            self.assertEqual(station_status.status_of("http://c/stream"), {"listeners": 9, "title": "Adele - Hello", "via": "shoutcast"})
            self.assertEqual(station_status.status_of("http://d/stream"), {"listeners": None, "title": None, "via": None})
            self.assertEqual(station_status.title_of("http://c/stream"), "Adele - Hello")
            self.assertEqual(station_status.listeners_of("http://a/stream"), 7)
            self.assertEqual(station_status.status_of("not a url")["via"], None)
        finally:
            station_status._fetch = original


if __name__ == "__main__":
    unittest.main()
