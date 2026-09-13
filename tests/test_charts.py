"""The weekly chart's rules, on a week small enough to read.

Before these rules the chart's number one was a station announcing its own
name; each rule below was added because of a row that reached the top
without being a record radio played.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import charts  # noqa: E402

DAY = 86400
NOW = 1_789_000_000


def track(artist, title, plays, stations, first=NOW - 5 * DAY, last=NOW):
    return {"artist": artist, "title": title, "plays": plays,
            "stations": stations, "first": first, "last": last}


def week():
    tracks = {
        "donna summer i feel love": track("Donna Summer", "I Feel Love", 30, ["s1", "s2"]),
        "lipps inc funkytown": track("Lipps, Inc.", "Funkytown", 20, ["s1", "s2", "s3"]),
        "adele hello": track("Adele", "Hello", 5, ["s1", "s2"], first=NOW - DAY),
        # the reasons for the rules
        "radio maria italia": track("", "RADIO MARIA ITALIA", 900, ["s1"]),
        "nieuws het radionieuws": track("Nieuws", "Het Radionieuws", 60, ["s3"]),
        "unknown pink noise": track("Unknown", "Pink Noise", 50, ["s2"]),
        "toto africa": track("Toto", "Africa", 15, ["s1", "s2"]),
        "funkytown": track("", "Funkytown", 12, ["s1", "s2"]),
    }
    # Six dated records on s1 alone, so it has an era.
    for n in range(6):
        tracks[f"era artist {n} song {n}"] = track(f"Era Artist {n}", f"Song {n}", 3, ["s1"])
    stations = {
        "s1": {"name": "Radio Maria Italia", "plays": 1000, "tracks": list(tracks)},
        "s2": {"name": "Blue Coast FM", "plays": 1000,
               "tracks": [k for k, t in tracks.items() if "s2" in t["stations"]]},
        "s3": {"name": "Night Shift Radio", "plays": 1000,
               "tracks": [k for k, t in tracks.items() if "s3" in t["stations"]]},
    }
    listeners = {
        "s2": {"station": "Blue Coast FM", "first": 40, "first_at": NOW - 3 * DAY,
               "last": 60, "last_at": NOW, "peak": 60},
        "s3": {"station": "Night Shift Radio", "first": 3, "first_at": NOW - 3 * DAY,
               "last": 12, "last_at": NOW, "peak": 12},
    }
    return {"updated": NOW, "days": 8, "tracks": tracks, "stations": stations, "listeners": listeners}


def years():
    known = {"donna summer i feel love": "1977", "lipps inc funkytown": "1979",
             "adele hello": "2015", "radio maria italia": "2015",
             "nieuws het radionieuws": "2000", "unknown pink noise": "2025",
             "funkytown": "1979", "toto africa": "none"}
    for n in range(6):
        known[f"era artist {n} song {n}"] = str(1980 + n)
    return known


class SongsOnly(unittest.TestCase):
    def test_what_the_week_already_knows_to_be_a_stations_string_stays_out(self):
        w = week()
        w["ignored"] = {"donna summer i feel love": NOW}
        tracks, _ = charts.songs_only(w)
        self.assertNotIn("donna summer i feel love", tracks)

    def test_junk_and_constants_leave_the_week_and_the_stations_lists(self):
        tracks, stations = charts.songs_only(week())
        self.assertNotIn("radio maria italia", tracks)      # names its station, and never stops
        self.assertNotIn("unknown pink noise", tracks)      # no artist to speak of
        # A bulletin every hour is 6% of the station's passes: the station's, not a record.
        self.assertNotIn("nieuws het radionieuws", tracks)
        self.assertNotIn("radio maria italia", stations["s1"]["tracks"])


class Chart(unittest.TestCase):
    def setUp(self):
        w = week()
        tracks, stations = charts.songs_only(w)
        self.doc = charts.build(w, tracks, stations, years(), now=NOW)

    def test_the_chart_ranks_dated_records_with_an_artist_played_by_more_than_one_station(self):
        rows = [(r["artist"], r["title"]) for r in self.doc["tracks"]]
        self.assertEqual(rows, [("Donna Summer", "I Feel Love"), ("Lipps, Inc.", "Funkytown"), ("Adele", "Hello")])
        self.assertEqual(self.doc["tracks"][0]["year"], "1977")
        self.assertEqual(self.doc["tracks"][1]["stations"], 3)

    def test_what_is_left_out_and_why(self):
        titles = {r["title"] for r in self.doc["tracks"]}
        self.assertNotIn("Het Radionieuws", titles)   # one station's loop is not radio's week
        self.assertNotIn("Africa", titles)            # iTunes did not confirm it
        self.assertNotIn("Funkytown", {r["title"] for r in self.doc["tracks"] if not r["artist"]})  # no artist

    def test_the_artists_chart_is_held_to_the_same_bar(self):
        self.assertEqual([a["artist"] for a in self.doc["artists"]][:3], ["Donna Summer", "Lipps, Inc.", "Adele"])
        self.assertNotIn("Nieuws", [a["artist"] for a in self.doc["artists"]])
        self.assertNotIn("Unknown", [a["artist"] for a in self.doc["artists"]])

    def test_new_this_week_is_recent_confirmed_and_on_more_than_one_station(self):
        self.assertEqual([r["title"] for r in self.doc["new"]], ["Hello"])

    def test_a_station_with_six_dated_records_has_an_era(self):
        eras = {e["id"]: e for e in self.doc["eras"]}
        self.assertIn("s1", eras)
        # Six era records, the three chart entries, and the artist-less Funkytown iTunes dated.
        self.assertEqual(eras["s1"]["dated"], 10)
        self.assertNotIn("s3", eras)

    def test_climbing_needs_an_audience_to_start_with(self):
        climbing = {c["id"] for c in self.doc["climbing"]}
        self.assertIn("s2", climbing)
        self.assertNotIn("s3", climbing)   # three becoming twelve tells nobody anything

    def test_the_document_is_dated_and_counted(self):
        self.assertEqual(self.doc["at"], NOW)
        self.assertEqual(self.doc["days"], 8)
        self.assertGreater(self.doc["observed"], 0)
        self.assertIsInstance(self.doc["similar"], dict)


if __name__ == "__main__":
    unittest.main()
