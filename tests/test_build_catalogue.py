"""What a station is called, and what it says about itself."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import build_catalogue as bc  # noqa: E402


class Names(unittest.TestCase):
    def test_a_hosts_default_name_is_no_name(self):
        for raw in ("stream", "This is my server name", "FastCast4u.com AutoDJ", "Unknown", "", "x"):
            self.assertIsNone(bc.station_name(raw), raw)

    def test_a_name_that_is_only_a_url_goes_and_one_with_a_url_stuck_on_keeps_the_name(self):
        self.assertIsNone(bc.station_name("https://example.com/"))
        self.assertEqual(bc.station_name("Blue Coast FM - www.bluecoast.fm"), "Blue Coast FM")

    def test_a_name_whose_decode_failed_is_dropped_rather_than_shown_broken(self):
        self.assertIsNone(bc.station_name("R�dio Nova"))

    def test_bitrate_variants_are_one_broadcaster_and_accents_do_not_matter(self):
        self.assertEqual(bc.base_name("Radio X (128Kbps)"), bc.base_name("Radio X HQ"))
        self.assertEqual(bc.base_name("Rádio Nova"), "radionova")

    def test_a_station_written_in_its_own_alphabet_keeps_a_key(self):
        self.assertEqual(bc.base_name("Радио Нестандарт"), "радионестандарт")


class About(unittest.TestCase):
    def test_a_real_sentence_is_kept_even_when_it_names_the_station(self):
        self.assertEqual(
            bc.about_for("Pirate Radio", "The legend of Limassol's pirate radio is back, all day, all night"),
            "The legend of Limassol's pirate radio is back, all day, all night")

    def test_the_panels_furniture_is_not_a_description(self):
        for said in ("Stream #1", "Blue Coast FM", "This is my server description", "AutoDJ stream 24/7", "short"):
            self.assertEqual(bc.about_for("Blue Coast FM", said), "", said)

    def test_utf8_read_as_latin1_is_undone(self):
        self.assertEqual(bc.readable("Dein Sender fÃ¼r Jung und Alt"), "Dein Sender für Jung und Alt")
        self.assertEqual(bc.readable("Already fine"), "Already fine")


if __name__ == "__main__":
    unittest.main()
