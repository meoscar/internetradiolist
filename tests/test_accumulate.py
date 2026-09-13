"""Folding passes into the week: what is counted, what is dropped."""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import accumulate  # noqa: E402

DAY = 86400


class InAWorkingDir(unittest.TestCase):
    """accumulate.py reads and writes files in the current directory."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        os.chdir(self.dir.name)

    def tearDown(self):
        os.chdir(self.was)
        self.dir.cleanup()

    def fold(self, at, *rows):
        pathlib.Path("live.json").write_text(json.dumps({"at": at, "playing": [
            {"id": sid, "station": name, "track": track} for sid, name, track in rows]}))
        accumulate.main(["accumulate.py"])
        return json.loads(pathlib.Path("week.json").read_text())

    def test_a_song_is_counted_per_pass_with_its_station(self):
        week = self.fold(1000, ("s1", "Blue Coast FM", "Donna Summer - I Feel Love"))
        week = self.fold(1300, ("s1", "Blue Coast FM", "Donna Summer - I Feel Love"))
        entry = week["tracks"]["donna summer i feel love"]
        self.assertEqual((entry["plays"], entry["stations"]), (2, ["s1"]))
        self.assertEqual(week["stations"]["s1"]["plays"], 2)

    def test_junk_is_refused_at_the_door(self):
        week = self.fold(1000,
            ("s1", "Radio Maria Italia", "RADIO MARIA ITALIA"),
            ("s2", "Some FM", "Now Playing info goes here"),
            ("s3", "Other FM", "Unknown - Pink Noise"),
            ("s4", "Blue Coast FM", "Toto - Africa"))
        self.assertEqual(list(week["tracks"]), ["toto africa"])

    def test_a_string_the_station_sends_every_pass_is_pruned_once_there_is_enough_of_it(self):
        for n in range(45):
            week = self.fold(1000 + 300 * n, ("s1", "Loop FM", "Neverne Bebe - Kuca za spas"))
        self.assertNotIn("neverne bebe kuca za spas", week["tracks"])
        self.assertEqual(week["stations"]["s1"]["tracks"], [])
        # And it stays out: pruned and forgotten, it came back the next pass
        # at one and climbed to thirty-nine between prunings.
        self.assertIn("neverne bebe kuca za spas", week["ignored"])

    def test_a_string_once_found_to_be_the_stations_is_forgotten_after_a_week_without_it(self):
        for n in range(45):
            week = self.fold(1000 + 300 * n, ("s1", "Loop FM", "Neverne Bebe - Kuca za spas"))
        week = self.fold(1000 + 300 * 45 + 9 * DAY, ("s1", "Loop FM", "Chic - Le Freak"))
        self.assertNotIn("neverne bebe kuca za spas", week["ignored"])

    def test_heard_once_and_not_again_for_a_day_is_dropped(self):
        self.fold(1000, ("s1", "FM", "Toto - Africa"))
        week = self.fold(1000 + 2 * DAY, ("s1", "FM", "Chic - Le Freak"))
        self.assertNotIn("toto africa", week["tracks"])
        self.assertIn("chic le freak", week["tracks"])

    def test_nothing_to_fold_leaves_the_week_alone(self):
        self.fold(1000, ("s1", "FM", "Toto - Africa"))
        pathlib.Path("live.json").write_text(json.dumps({"at": 2000, "playing": []}))
        accumulate.main(["accumulate.py"])
        self.assertIn("toto africa", json.loads(pathlib.Path("week.json").read_text())["tracks"])


class Split(unittest.TestCase):
    def test_artist_and_title_on_the_first_dash_with_brackets_dropped(self):
        self.assertEqual(accumulate.split("Toto - Africa (Live) - 1982"), ("Toto", "Africa - 1982"))
        self.assertEqual(accumulate.split("Funkytown"), ("", "Funkytown"))
        self.assertEqual(accumulate.normalise("Lipps, Inc. — Funkytown"), "lipps inc funkytown")


if __name__ == "__main__":
    unittest.main()
