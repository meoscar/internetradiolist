"""The month-long tally of who each station plays."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import station_artists  # noqa: E402

DAY = 86400


def live(at, *rows):
    return {"at": at, "playing": [
        {"id": sid, "station": name, "track": track} for sid, name, track in rows]}


class Fold(unittest.TestCase):
    def test_a_play_is_one_pass_with_the_artist_on(self):
        tally = {}
        station_artists.fold(tally, live(100, ("s1", "Blue Coast FM", "Donna Summer - I Feel Love")), 100)
        fact = tally["stations"]["s1"]
        self.assertEqual(fact["passes"], 1)
        self.assertEqual(fact["artists"]["donna summer"]["plays"], 1)
        self.assertEqual(fact["artists"]["donna summer"]["name"], "Donna Summer")

    def test_the_same_line_two_passes_running_is_one_play(self):
        tally = {}
        for at in (100, 400):
            station_artists.fold(tally, live(at, ("s1", "Blue Coast FM", "Donna Summer - I Feel Love")), at)
        fact = tally["stations"]["s1"]
        self.assertEqual(fact["passes"], 2)
        self.assertEqual(fact["artists"]["donna summer"]["plays"], 1)

    def test_the_same_artist_with_a_new_title_is_a_second_play(self):
        tally = {}
        station_artists.fold(tally, live(100, ("s1", "Blue Coast FM", "Donna Summer - I Feel Love")), 100)
        station_artists.fold(tally, live(400, ("s1", "Blue Coast FM", "Donna Summer - Hot Stuff")), 400)
        self.assertEqual(tally["stations"]["s1"]["artists"]["donna summer"]["plays"], 2)

    def test_junk_and_lines_with_no_artist_count_the_pass_but_not_an_artist(self):
        tally = {}
        station_artists.fold(tally, live(100,
            ("s1", "Radio Maria Italia", "RADIO MARIA ITALIA"),
            ("s2", "Some FM", "Now Playing info goes here"),
            ("s3", "Other FM", "Funkytown")), 100)
        for sid in ("s1", "s2", "s3"):
            self.assertEqual(tally["stations"][sid]["passes"], 1)
            self.assertEqual(tally["stations"][sid]["artists"], {})

    def test_a_row_with_no_station_id_is_ignored(self):
        tally = {}
        station_artists.fold(tally, {"at": 1, "playing": [{"id": "", "track": "A - B"}]}, 1)
        self.assertEqual(tally["stations"], {})


class When(unittest.TestCase):
    """When a station tends to play an artist, from the hours of its plays."""

    def hours(self, **at):
        out = [0] * 24
        for hour, n in at.items():
            out[int(hour[1:])] = n
        return out

    def test_the_hour_of_each_play_is_kept(self):
        tally = {}
        at = 20 * 3600 + 600                       # 20:10 UTC on day zero
        station_artists.fold(tally, live(at, ("s1", "FM", "Donna Summer - I Feel Love")), at)
        station_artists.fold(tally, live(at + 86400 * 2 + 3600, ("s1", "FM", "Donna Summer - Hot Stuff")), at + 86400 * 2 + 3600)
        hours = tally["stations"]["s1"]["artists"]["donna summer"]["hours"]
        self.assertEqual((hours[20], hours[21], sum(hours)), (1, 1, 2))

    def test_plays_bunched_in_the_evening_are_an_evening_band(self):
        self.assertEqual(station_artists.when(self.hours(h20=3, h21=4, h22=2, h9=1)), "20-22")

    def test_too_few_plays_or_plays_at_all_hours_are_no_band(self):
        self.assertIsNone(station_artists.when(self.hours(h20=2, h21=2)), "four plays is too few")
        self.assertIsNone(station_artists.when([1] * 24), "a station that plays them all day has no time")
        self.assertIsNone(station_artists.when(self.hours(h1=2, h7=2, h13=2, h19=2, h22=2)))
        self.assertIsNone(station_artists.when(None))
        self.assertIsNone(station_artists.when([0] * 23), "not a day")

    def test_a_band_can_cross_midnight_and_a_tie_goes_to_the_earlier_hour(self):
        self.assertEqual(station_artists.when(self.hours(h23=3, h0=3, h1=2)), "23-1")
        self.assertEqual(station_artists.when(self.hours(h8=3, h9=3, h14=3, h15=3)), "8-10")

    def test_the_band_is_published_beside_the_count_only_when_there_is_one(self):
        tally = {}
        for day in range(6):
            at = day * 86400 + 20 * 3600
            station_artists.fold(tally, live(at, ("s1", "FM", f"Donna Summer - Song {day}"),
                                             ("s1", "FM", f"Chic - Song {day}")), at)
        # Chic's second line each pass is a new play in the same hour too;
        # spread Chic's plays over the clock instead.
        chic = tally["stations"]["s1"]["artists"]["chic"]
        chic["hours"] = [1] * 24
        chic["plays"] = 24
        doc = station_artists.publish(tally, {}, 0)
        artists = doc["stations"]["s1"]["artists"]
        self.assertEqual(artists[0], ["Chic", 24])
        self.assertEqual(artists[1], ["Donna Summer", 6, "20-22"])


class Prune(unittest.TestCase):
    def test_an_artist_not_heard_for_a_month_is_dropped(self):
        tally = {}
        station_artists.fold(tally, live(0, ("s1", "FM", "Old Artist - Song")), 0)
        station_artists.fold(tally, live(31 * DAY, ("s1", "FM", "New Artist - Song")), 31 * DAY)
        station_artists.prune(tally, 31 * DAY)
        self.assertEqual(list(tally["stations"]["s1"]["artists"]), ["new artist"])

    def test_a_station_not_heard_for_a_month_is_dropped(self):
        tally = {}
        station_artists.fold(tally, live(0, ("s1", "FM", "A - Song")), 0)
        station_artists.prune(tally, 31 * DAY)
        self.assertEqual(tally["stations"], {})

    def test_the_list_per_station_is_bounded_by_plays(self):
        tally = {}
        for n in range(station_artists.KEEP_PER_STATION + 10):
            for at in range(n + 1):
                station_artists.fold(tally, live(at, ("s1", "FM", f"Artist {n} - Song {at}")), at)
        station_artists.prune(tally, 0)
        artists = tally["stations"]["s1"]["artists"]
        self.assertEqual(len(artists), station_artists.KEEP_PER_STATION)
        self.assertNotIn("artist 0", artists)      # heard once, least played
        self.assertIn("artist 89", artists)        # heard ninety times


class Publish(unittest.TestCase):
    def test_sorted_most_played_first_and_only_the_repeated(self):
        tally = {}
        station_artists.fold(tally, live(0, ("s1", "FM", "Once - A")), 0)
        for at in (100, 200):
            station_artists.fold(tally, live(at, ("s1", "FM", f"Twice - Song {at}")), at)
        for at in (300, 400, 500):
            station_artists.fold(tally, live(at, ("s1", "FM", f"Thrice - Song {at}")), at)
        doc = station_artists.publish(tally, {}, 500)
        self.assertEqual(doc["stations"]["s1"]["artists"], [["Thrice", 3], ["Twice", 2]])
        self.assertEqual(doc["stations"]["s1"]["station"], "FM")
        self.assertEqual(doc["days"], 30)

    def test_the_weeks_variety_comes_from_the_week_file(self):
        tally = {}
        station_artists.fold(tally, live(0, ("s1", "FM", "A - B")), 0)
        week = {"stations": {"s1": {"plays": 2500, "tracks": ["a", "b", "c"]}}}
        entry = station_artists.publish(tally, week, 0)["stations"]["s1"]
        self.assertEqual((entry["week_titles"], entry["week_passes"]), (3, 2500))

    def test_a_station_with_nothing_to_say_is_left_out(self):
        tally = {}
        station_artists.fold(tally, live(0, ("s1", "FM", "Funkytown")), 0)
        self.assertEqual(station_artists.publish(tally, {}, 0)["stations"], {})


if __name__ == "__main__":
    unittest.main()
