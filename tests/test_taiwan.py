"""Taiwan's list, from the probe's rows: what is kept, what is dropped and why."""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import taiwan  # noqa: E402


def row(name, url, votes=0, **more):
    return {"name": name, "url": url, "url_resolved": url, "votes": votes, **more}


class Build(unittest.TestCase):
    def test_every_reachable_station_is_kept_once_most_voted_first(self):
        rows = [
            row("Hit FM台北之音廣播", "https://a/hit.m3u8", 100, codec="unknown",
                tags="music, pop", homepage="https://hitoradio.com/", favicon="https://hitoradio.com/i.png"),
            row("臺北電台", "https://b/live.m3u8", 4000),
            row("Hit FM 台北之音廣播", "https://a2/hit.m3u8", 50),
            row("臺北電台AM", "https://b/live.m3u8", 30),
            row("Classical 古典音樂台 FM 97.7", "http://c/stream", 3000),
        ]
        streams = {
            "https://a/hit.m3u8": {"reachable": True, "hls": True},
            "https://b/live.m3u8": {"reachable": True, "hls": True},
            "https://a2/hit.m3u8": {"reachable": True, "hls": True},
            "http://c/stream": {"reachable": False, "hls": False},
        }
        kept, dropped = taiwan.build(rows, streams)
        self.assertEqual([s["name"] for s in kept], ["臺北電台", "Hit FM台北之音廣播"])
        self.assertEqual(kept[1], {
            "name": "Hit FM台北之音廣播", "stream": "https://a/hit.m3u8",
            "homepage": "https://hitoradio.com/", "favicon": "https://hitoradio.com/i.png",
            "tags": ["music", "pop"], "votes": 100, "codec": "UNKNOWN", "hls": True})
        self.assertEqual(dict(dropped), {
            "Classical 古典音樂台 FM 97.7": "the stream did not answer when probed",
            "Hit FM 台北之音廣播": "the same name, already kept",
            "臺北電台AM": "the same stream, already kept",
        })

    def test_rows_that_are_not_stations_in_taiwan_are_left_out_by_name_with_a_reason(self):
        rows = [row("電台測試2", "http://t/s", 90), row("福建東南廣播", "http://f/s", 80),
                row("no address", "", 70), row("大千電台", "http://d/s", 60)]
        streams = {u: {"reachable": True, "hls": False} for u in ("http://t/s", "http://f/s", "http://d/s")}
        kept, dropped = taiwan.build(rows, streams)
        self.assertEqual([s["name"] for s in kept], ["大千電台"])
        self.assertEqual(dropped, [
            ("電台測試2", "a test row"),
            ("福建東南廣播", "broadcasts from Fujian, filed under TW"),
            ("no address", "no stream address")])

    def test_a_favicon_is_kept_only_over_https_and_a_name_key_folds_width_case_and_punctuation(self):
        rows = [row("A", "https://a/s", favicon="http://a/i.ico")]
        kept, _ = taiwan.build(rows, {"https://a/s": {"reachable": True}})
        self.assertEqual(kept[0]["favicon"], "")
        self.assertEqual(taiwan.name_key("Ｈｉｔ FM 台北之音－廣播"), taiwan.name_key("hit fm台北之音廣播"))

    def test_the_kept_streams_are_filed_under_tw_and_nothing_else_moves(self):
        out = taiwan.with_taiwan({"http://x/s": "GB"}, [{"stream": "https://a/s"}])
        self.assertEqual(out, {"http://x/s": "GB", "https://a/s": "TW"})


class Main(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)

    def tearDown(self):
        os.chdir(self.was)
        self.dir.cleanup()

    def run_main(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            code = taiwan.main(["taiwan.py", *args])
        return code, out.getvalue()

    def test_without_the_probes_it_says_who_writes_them(self):
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("probe_taiwan.py", out)

    def test_apply_writes_the_list_and_files_them_in_countries(self):
        pathlib.Path("probes").mkdir()
        pathlib.Path("probes/taiwan_radio_browser.json").write_text(json.dumps(
            [row("臺北電台", "https://b/live.m3u8", 4000, tags="news")]), encoding="utf-8")
        pathlib.Path("probes/taiwan_streams.json").write_text(json.dumps(
            {"https://b/live.m3u8": {"reachable": True, "hls": True}}), encoding="utf-8")
        pathlib.Path("countries.json").write_text(json.dumps({"http://x/s": "GB"}), encoding="utf-8")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("nothing written", out)
        self.assertFalse(pathlib.Path("taiwan.json").exists())
        code, out = self.run_main("--apply")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(pathlib.Path("taiwan.json").read_text())[0]["name"], "臺北電台")
        self.assertEqual(json.loads(pathlib.Path("countries.json").read_text()),
                         {"http://x/s": "GB", "https://b/live.m3u8": "TW"})


if __name__ == "__main__":
    unittest.main()
