"""The scripts run end to end, in a working directory of their own, with the
network played by the test: what each writes from what it was given."""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import accumulate  # noqa: E402
import build_catalogue as bc  # noqa: E402
import charts  # noqa: E402
import live_now  # noqa: E402
import station_artists  # noqa: E402

DAY = 86400
NOW = 1_789_000_000


class InAWorkingDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)

    def tearDown(self):
        os.chdir(self.was)
        self.dir.cleanup()

    def write(self, name, doc):
        pathlib.Path(name).write_text(json.dumps(doc), encoding="utf-8")

    def read(self, name):
        return json.loads(pathlib.Path(name).read_text(encoding="utf-8"))

    def quietly(self, fn, argv):
        with redirect_stdout(io.StringIO()) as out:
            code = fn(argv)
        return code, out.getvalue()


class BuildCatalogue(InAWorkingDir):
    def setUp(self):
        super().setUp()
        self.write("station_facts.json", {
            "http://a/stream": {"ok": True, "icy-description": "The best of the west coast, all day"},
            "http://b/stream": {"ok": True},
            "http://c/stream": {"ok": True, "content-type": "text/html"},
            "http://d/stream": {"ok": False},
            "http://icrt/stream": {"ok": True},
            "http://e/stream": {"ok": True},
        })
        self.write("directory.json", [
            {"name": "Blue Coast FM", "stream": "http://a/stream", "genres": ["rock"], "listeners": 300,
             "bitrate": 128, "homepage": "https://a.example/", "page": "https://www.internet-radio.com/station/a/"},
            {"name": "Blue Coast FM (64Kbps)", "stream": "http://a2/stream", "genres": ["rock"], "listeners": 5},
            {"name": "Night Shift", "stream": "http://b/stream", "genres": ["rock", "jazz"], "listeners": 20},
            {"name": "Web Page Only", "stream": "http://c/stream", "genres": ["rock"]},
            {"name": "Dead Air", "stream": "http://d/stream", "genres": ["rock"]},
            {"name": "stream", "stream": "http://e/stream", "genres": ["rock"]},
            {"name": "Never Probed", "stream": "http://f/stream", "genres": ["rock"]},
        ] + [{"name": f"Rock Station {n}", "stream": f"http://r{n}/stream", "genres": ["rock"], "listeners": n}
             for n in range(12)])
        facts = self.read("station_facts.json")
        for n in range(12):
            facts[f"http://r{n}/stream"] = {"ok": True}
        self.write("station_facts.json", facts)
        self.write("health.json", {"http://b/stream": {"consecutive_failures": 3}})
        self.write("logos.json", {"http://a/stream": {"name": "Blue Coast FM", "logo": "https://raw.example/logos/bluecoast.webp"}})
        self.write("music_worldradio.json", {"music": [
            {"id": bc.ICRT_ID, "title": "ICRT", "source": "http://icrt/stream", "image": "x", "genre": "TAIWAN"},
            {"id": "old", "title": "Carried Over", "source": "http://carried/stream", "genre": "POP"},
        ]})
        facts = self.read("station_facts.json")
        facts["http://carried/stream"] = {"ok": True}
        self.write("station_facts.json", facts)

    def test_the_catalogue_is_built_from_what_answered_and_nothing_is_written_without_apply(self):
        code, out = self.quietly(bc.main, ["build_catalogue.py"])
        self.assertEqual(code, 0)
        self.assertIn("nothing written", out)
        self.assertEqual(self.read("music_worldradio.json")["music"][0]["title"], "ICRT")

    def test_with_apply_the_rows_are_what_a_listener_can_play(self):
        code, out = self.quietly(bc.main, ["build_catalogue.py", "--apply"])
        self.assertEqual(code, 0)
        music = self.read("music_worldradio.json")["music"]
        titles = [r["title"] for r in music]
        self.assertEqual(titles[0], "ICRT")                        # ICRT first, always
        self.assertIn("Blue Coast FM", titles)
        self.assertIn("Carried Over", titles)                      # still answers, crawl missed it
        self.assertNotIn("Blue Coast FM (64Kbps)", titles)         # same broadcaster, lower bitrate
        self.assertNotIn("Night Shift", titles)                    # retired by the nightly check
        self.assertNotIn("Web Page Only", titles)                  # answered with HTML
        self.assertNotIn("Dead Air", titles)
        self.assertNotIn("stream", titles)                         # no name worth showing
        self.assertNotIn("Never Probed", titles)
        blue = next(r for r in music if r["title"] == "Blue Coast FM" and r["genre"] != "On Trend")
        self.assertEqual(blue["image"], "https://raw.example/logos/bluecoast.webp")
        self.assertEqual(blue["about"], "The best of the west coast, all day")
        self.assertEqual((blue["listeners"], blue["bitrate"], blue["homepage"]), (300, 128, "https://a.example/"))
        self.assertEqual(blue["genre"], "ROCK")
        self.assertTrue(all(r["image"] for r in music))
        self.assertTrue(any(r["genre"] == "On Trend" for r in music))
        self.assertEqual(next(r for r in music if r["genre"] == "On Trend")["title"], "Blue Coast FM")

    def test_taiwans_stations_follow_icrt_under_the_same_heading_unless_the_health_check_retired_them(self):
        self.write("taiwan.json", [
            {"name": "臺北電台", "stream": "https://tpe/live.m3u8", "homepage": "https://www.radio.gov.taipei/",
             "favicon": "https://www.radio.gov.taipei/favicon.png", "tags": ["news"], "votes": 4000, "codec": "AAC", "hls": True},
            {"name": "大千電台", "stream": "http://dachien/stream", "homepage": "", "favicon": "https://d/i.ico",
             "tags": [], "votes": 100, "codec": "MP3", "hls": False},
            {"name": "已停播", "stream": "http://gone/stream", "homepage": "", "favicon": "", "tags": [], "votes": 5,
             "codec": "MP3", "hls": False},
        ])
        health = self.read("health.json")
        health["http://gone/stream"] = {"consecutive_failures": 3}
        self.write("health.json", health)
        code, out = self.quietly(bc.main, ["build_catalogue.py", "--apply"])
        self.assertEqual(code, 0)
        music = self.read("music_worldradio.json")["music"]
        taiwan = [r for r in music if r["genre"] == "TAIWAN"]
        self.assertEqual([r["title"] for r in taiwan], ["ICRT", "臺北電台", "大千電台"])
        self.assertEqual([r["trackNumber"] for r in taiwan[1:]], [2, 3])
        tpe = taiwan[1]
        self.assertEqual((tpe["id"], tpe["source"]), ("https://tpe/live.m3u8", "https://tpe/live.m3u8"))
        self.assertEqual(tpe["image"], "https://www.radio.gov.taipei/favicon.png")   # a picture, not an .ico
        self.assertEqual(taiwan[2]["image"], bc.PLACEHOLDER)
        self.assertEqual((tpe["homepage"], tpe["tags"], tpe["site"]), ("https://www.radio.gov.taipei/", ["news"], ""))
        self.assertNotIn("listeners", tpe)                                          # votes are not an audience
        self.assertIn("2 stations in Taiwan", out)

    def test_no_facts_means_nothing_to_build_from(self):
        pathlib.Path("station_facts.json").unlink()
        code, out = self.quietly(bc.main, ["build_catalogue.py"])
        self.assertEqual(code, 1)

    def test_the_row_carries_only_what_is_known(self):
        r = bc.row("A", "ROCK", "http://a", "img", "", 3, "http://a", tags=("rock", "", " ", "rock"))
        self.assertEqual(r["tags"], ["rock"])
        self.assertNotIn("listeners", r)
        self.assertNotIn("homepage", r)
        self.assertEqual(bc.load("nope.json", {"d": 1}), {"d": 1})
        self.assertEqual(bc.items_of({"data": [1]}), [1])
        self.assertTrue(bc.answered_with_audio({"ok": True}))
        self.assertFalse(bc.answered_with_audio({"ok": True, "content-type": "TEXT/html"}))


class LiveNow(InAWorkingDir):
    def setUp(self):
        super().setUp()
        self.write("music_worldradio.json", {"music": [
            {"id": "https://a.example/", "title": "Blue Coast FM", "source": "http://a/stream", "genre": "rock", "image": "i"},
            {"id": "ontrendstations_Blue", "title": "Blue Coast FM", "source": "http://a/stream", "genre": "On Trend"},
            {"id": "https://b.example/", "title": "Night Shift", "source": "http://b/stream", "genre": "jazz"},
            {"id": "x", "title": "No stream", "source": ""},
        ]})
        self.write("directory.json", [
            {"stream": "http://a/stream", "playlist": "http://a/list.pls", "listeners": 300},
            {"stream": "http://b/stream", "listeners": 20},
        ])
        self.original = live_now.interrogate
        live_now.interrogate = lambda stations: (
            [{"id": "https://a.example/", "station": "Blue Coast FM", "image": "i", "genre": "rock", "track": "Toto - Africa"}],
            {"http://a/stream": 310, "http://b/stream": 25, "http://unknown/stream": 9})

    def tearDown(self):
        live_now.interrogate = self.original
        super().tearDown()

    def test_the_index_keeps_one_row_per_stream_and_the_genre_copy_wins(self):
        by_source = live_now.playable_index(live_now.items_of(self.read("music_worldradio.json")))
        self.assertEqual(list(by_source), ["http://a/stream", "http://b/stream"])
        self.assertEqual(by_source["http://a/stream"]["id"], "https://a.example/")
        self.assertEqual(live_now.playlist_to_stream(self.read("directory.json")),
                         {"http://a/stream": "http://a/stream", "http://a/list.pls": "http://a/stream", "http://b/stream": "http://b/stream"})

    def test_a_pass_writes_what_is_playing_and_who_is_listening_and_the_next_sees_who_rose(self):
        code, out = self.quietly(live_now.main, ["live_now.py", "--no-site", "--stations", "5"])
        self.assertEqual(code, 0)
        live = self.read("live.json")
        self.assertEqual(live["playing"][0]["track"], "Toto - Africa")
        self.assertEqual([r["id"] for r in live["top"]], ["https://a.example/", "https://b.example/"])
        self.assertEqual(live["rising"], [])
        self.assertEqual({g["genre"] for g in live["number_ones"]}, {"rock", "jazz"})
        counts = self.read("counts.json")
        self.assertEqual(counts["counts"]["https://a.example/"]["n"], 310)

        live_now.interrogate = lambda stations: ([], {"http://a/stream": 400, "http://b/stream": 25})
        self.quietly(live_now.main, ["live_now.py", "--no-site"])
        live = self.read("live.json")
        self.assertEqual([(r["id"], r["gained"]) for r in live["rising"]], [("https://a.example/", 90)])

    def test_no_catalogue_is_nothing_to_report_on(self):
        pathlib.Path("music_worldradio.json").unlink()
        code, _ = self.quietly(live_now.main, ["live_now.py", "--no-site"])
        self.assertEqual(code, 1)


class Charts(InAWorkingDir):
    def test_a_run_writes_the_chart_and_asks_itunes_for_the_years_it_lacks(self):
        self.write("week.json", {"updated": NOW, "days": 8, "tracks": {
            "donna summer i feel love": {"artist": "Donna Summer", "title": "I Feel Love", "plays": 30,
                                         "stations": ["s1", "s2"], "first": NOW - DAY, "last": NOW},
        }, "stations": {"s1": {"name": "A", "plays": 100, "tracks": ["donna summer i feel love"]},
                        "s2": {"name": "B", "plays": 100, "tracks": ["donna summer i feel love"]}}})
        answers = {"Donna Summer I Feel Love": {"results": [{"artistName": "Donna Summer", "releaseDate": "1977-07-02T00:00:00Z"}]}}
        original, sleep = charts.urllib.request.urlopen, charts.time.sleep

        class Response:
            def __init__(self, doc): self.status, self.doc = 200, doc
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.doc).encode()

        def fake_open(request, timeout=0):
            term = charts.urllib.parse.unquote_plus(request.full_url.split("term=")[1].split("&")[0])
            return Response(answers.get(term, {"results": []}))
        charts.urllib.request.urlopen = fake_open
        charts.time.sleep = lambda s: None
        try:
            code, out = self.quietly(charts.main, ["charts.py", "--lookups", "5"])
        finally:
            charts.urllib.request.urlopen, charts.time.sleep = original, sleep
        self.assertEqual(code, 0)
        self.assertEqual(self.read("years.json"), {"donna summer i feel love": "1977"})
        doc = self.read("charts.json")
        self.assertEqual(doc["tracks"][0]["title"], "I Feel Love")
        self.assertIn("most played this week", out)

    def test_year_of_trusts_only_an_answer_by_the_artist_asked_about(self):
        original = charts.urllib.request.urlopen

        class Response:
            def __init__(self, doc, status=200): self.status, self.doc = status, doc
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.doc).encode()

        try:
            charts.urllib.request.urlopen = lambda r, timeout=0: Response({"results": [{"artistName": "Sunset Boys", "releaseDate": "2010-01-01"}]})
            self.assertEqual(charts.year_of("Radio DeeJay", "Live"), "none")
            charts.urllib.request.urlopen = lambda r, timeout=0: Response({"results": [{"artistName": "Lipps Inc", "releaseDate": "1979-11-01"}]})
            self.assertEqual(charts.year_of("Lipps, Inc.", "Funkytown"), "1979")
            charts.urllib.request.urlopen = lambda r, timeout=0: Response({"results": [{"artistName": "Lipps Inc", "releaseDate": "soon"}]})
            self.assertEqual(charts.year_of("Lipps, Inc.", "Funkytown"), "none")
            charts.urllib.request.urlopen = lambda r, timeout=0: Response({}, status=503)
            self.assertIsNone(charts.year_of("Lipps, Inc.", "Funkytown"))
            charts.urllib.request.urlopen = lambda r, timeout=0: (_ for _ in ()).throw(OSError("down"))
            self.assertIsNone(charts.year_of("Lipps, Inc.", "Funkytown"))
            self.assertEqual(charts.year_of("", "RADIO MARIA ITALIA"), "none")
            self.assertEqual(charts.year_of("a", ""), "none")   # nothing to ask about
        finally:
            charts.urllib.request.urlopen = original

    def test_no_week_yet_is_nothing_to_chart(self):
        code, _ = self.quietly(charts.main, ["charts.py"])
        self.assertEqual(code, 1)
        pathlib.Path("years.json").write_text("not json")
        self.assertEqual(charts.load("years.json", {}), {})


class AccumulateListeners(InAWorkingDir):
    def test_listener_counts_are_kept_as_a_first_and_a_latest_and_forgotten_after_a_week(self):
        self.write("live.json", {"at": NOW, "playing": [{"id": "s1", "station": "A", "track": "Toto - Africa"}]})
        self.write("counts.json", {"at": NOW, "counts": {"s1": {"n": 40, "station": "A"}, "s2": {"n": -1}, "s3": {"n": "x"}}})
        accumulate.main(["accumulate.py"])
        week = self.read("week.json")
        self.assertEqual(week["listeners"]["s1"], {"station": "A", "first": 40, "first_at": NOW, "last": 40, "last_at": NOW, "peak": 40})
        self.assertNotIn("s2", week["listeners"])

        self.write("live.json", {"at": NOW + DAY, "playing": [{"id": "s1", "station": "A", "track": "Toto - Africa"}]})
        self.write("counts.json", {"at": NOW + DAY, "counts": {"s1": {"n": 55, "station": "A"}}})
        accumulate.main(["accumulate.py"])
        s1 = self.read("week.json")["listeners"]["s1"]
        self.assertEqual((s1["first"], s1["last"], s1["peak"], s1["last_at"]), (40, 55, 55, NOW + DAY))

        self.write("live.json", {"at": NOW + 10 * DAY, "playing": [{"id": "s9", "station": "Z", "track": "Chic - Le Freak"}]})
        self.write("counts.json", {"at": NOW + 10 * DAY, "counts": {"s9": {"n": 3, "station": "Z"}}})
        accumulate.main(["accumulate.py"])
        self.assertNotIn("s1", self.read("week.json")["listeners"])


class StationArtistsMain(InAWorkingDir):
    def test_a_pass_folds_into_the_tally_and_publishes_the_extract(self):
        self.write("live.json", {"at": NOW, "playing": [{"id": "s1", "station": "A", "track": "Toto - Africa"}]})
        station_artists.main(["station_artists.py"])
        self.write("live.json", {"at": NOW + 300, "playing": [{"id": "s1", "station": "A", "track": "Toto - Rosanna"}]})
        code, out = self.quietly(station_artists.main, ["station_artists.py"])
        self.assertEqual(code, 0)
        self.assertEqual(self.read("station_artists.json")["stations"]["s1"]["artists"], [["Toto", 2]])
        self.assertEqual(self.read("artists_tally.json")["stations"]["s1"]["passes"], 2)

    def test_nothing_to_fold_writes_nothing(self):
        self.write("live.json", {"at": NOW, "playing": []})
        self.assertEqual(station_artists.main(["station_artists.py"]), 0)
        self.assertFalse(pathlib.Path("station_artists.json").exists())


if __name__ == "__main__":
    unittest.main()
