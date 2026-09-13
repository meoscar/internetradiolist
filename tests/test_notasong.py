"""The junk rules, on the strings that were at the top of the chart."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import notasong  # noqa: E402


class Junk(unittest.TestCase):
    def test_the_unfilled_template_is_not_a_song(self):
        self.assertTrue(notasong.junk("", "Now Playing info goes here"))

    def test_a_station_announcing_itself_is_not_a_song(self):
        self.assertTrue(notasong.junk("", "RADIO MARIA ITALIA", "Radio Maria Italia"))
        self.assertTrue(notasong.junk("Radio DeeJay", "Live", "Radio Deejay"))
        self.assertTrue(notasong.junk("", "Radioacacia.nl --- Studio 1", "RadioAcacia.nl"))
        self.assertTrue(notasong.junk("RADIO", "FUSION", "RADIO FUSION"))

    def test_a_short_station_name_is_not_matched_inside_a_title(self):
        # "Hits" is in half the catalogue's song lines.
        self.assertFalse(notasong.junk("Robbie Williams", "Greatest Hits Live", "Hits"))

    def test_an_unknown_artist_is_not_a_song(self):
        self.assertTrue(notasong.junk("Unknown", "Pink Noise"))
        self.assertTrue(notasong.junk("Various Artists", "Chill Mix"))

    def test_a_web_address_or_handle_is_not_a_song(self):
        self.assertTrue(notasong.junk("", "facebook.com/Radioparty.Official"))
        self.assertTrue(notasong.junk("", "tiktok.com/@radioparty.pl"))
        self.assertTrue(notasong.junk("RadioParty.pl", "najlepsze party w sieci"))
        self.assertTrue(notasong.junk("wellsfargo.com", "Ein bisschen Verbraucherinformationen"))

    def test_the_things_a_station_says_instead_of_a_song(self):
        self.assertTrue(notasong.junk("", "ToP of the Hour"))
        self.assertTrue(notasong.junk("Be Right Back!", "THIS STATION WILL CONTINUE AFTER"))
        self.assertTrue(notasong.junk("", "Swadesh FM Live Streaming"))

    def test_a_record_is_a_song(self):
        self.assertFalse(notasong.junk("Donna Summer", "Love To Love You Baby", "Retro Wave One"))
        self.assertFalse(notasong.junk("Lipps, Inc.", "Funkytown", "Blue Coast FM"))
        self.assertFalse(notasong.junk("Toto", "Africa", "Radio Africa"))

    def test_a_title_alone_can_still_be_a_song(self):
        self.assertFalse(notasong.junk("", "Funkytown"))

    def test_a_title_alone_that_is_only_a_word_like_live_is_not(self):
        self.assertTrue(notasong.junk("", "Live"))


class Constant(unittest.TestCase):
    def test_a_string_seen_in_every_pass_is_the_stations(self):
        self.assertTrue(notasong.constant(plays=2584, observations=2584))

    def test_a_hit_in_heavy_rotation_is_not(self):
        # Funkytown: 86 plays over 16 stations' 40,000 passes.
        self.assertFalse(notasong.constant(plays=86, observations=40000))
        # The 99th percentile of real songs this week, 1.4%.
        self.assertFalse(notasong.constant(plays=36, observations=2553))

    def test_a_stuck_stream_on_two_variants_is(self):
        # "Kuca za spas", 1,560 plays on two streams of the same station.
        self.assertTrue(notasong.constant(plays=1560, observations=5100))

    def test_a_news_bulletin_every_hour_is(self):
        # "Het Radionieuws", 94 plays on one station's 2,553 passes: 3.7%.
        self.assertTrue(notasong.constant(plays=94, observations=2553))

    def test_too_few_observations_to_judge(self):
        self.assertFalse(notasong.constant(plays=3, observations=3))
        self.assertFalse(notasong.constant(plays=39, observations=40))


class ArtistMatch(unittest.TestCase):
    def test_punctuation_and_case_do_not_matter(self):
        self.assertTrue(notasong.artist_matches("Lipps, Inc.", "Lipps Inc"))

    def test_a_collaboration_still_names_the_artist(self):
        self.assertTrue(notasong.artist_matches("Adele", "Adele feat. Someone"))

    def test_a_different_artist_does_not(self):
        self.assertFalse(notasong.artist_matches("Radio DeeJay", "Sunset Boys"))

    def test_no_artist_of_ours_matches_nobody(self):
        self.assertFalse(notasong.artist_matches("", "Anyone"))


if __name__ == "__main__":
    unittest.main()
