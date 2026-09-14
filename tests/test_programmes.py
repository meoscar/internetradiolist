"""programmes.json: which stations say their programme, and how."""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import programmes  # noqa: E402


class Build(unittest.TestCase):
    def test_a_live_source_is_matched_by_name_and_a_week_by_stream(self):
        stations = [
            {"name": "中廣流行網", "stream": "https://n03.rcs.revma.com/aw9uqyxy2tzuv"},
            {"name": "飛碟聯播網 飛碟電台", "stream": "https://n10.rcs.revma.com/em90w4aeewzuv"},
            {"name": "臺北電台", "stream": "https://tpe/live.m3u8"},
            {"name": "中廣 I GO", "stream": ""},
        ]
        week = {"1": [["07:00", "09:00", "飛碟早餐", "唐湘龍"]]}
        built = programmes.build(stations, {"https://n10.rcs.revma.com/em90w4aeewzuv": week})
        self.assertEqual(set(built), {"https://n03.rcs.revma.com/aw9uqyxy2tzuv", "https://n10.rcs.revma.com/em90w4aeewzuv"})
        self.assertEqual(built["https://n03.rcs.revma.com/aw9uqyxy2tzuv"],
                         {"live": {"kind": "bcc", "url": programmes.BCC_API, "channel": "流行網"}})
        self.assertEqual(built["https://n10.rcs.revma.com/em90w4aeewzuv"], {"week": week})

    def test_every_bcc_channel_has_words_the_app_can_find_it_by(self):
        for name, live in programmes.LIVE.items():
            self.assertEqual(live["kind"], "bcc", name)
            self.assertTrue(live["channel"], name)
            self.assertNotIn(" ", live["channel"], name)


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
            code = programmes.main(["programmes.py", *args])
        return code, out.getvalue()

    def test_without_taiwan_it_says_so(self):
        self.assertEqual(self.run_main()[0], 1)

    def test_apply_writes_the_file_with_the_grids_found_in_schedules(self):
        pathlib.Path("taiwan.json").write_text(json.dumps([
            {"name": "中廣音樂網", "stream": "https://n03.rcs.revma.com/ndk05tyy2tzuv"},
            {"name": "好事聯播網", "stream": "http://best/stream"}]), encoding="utf-8")
        pathlib.Path("schedules").mkdir()
        pathlib.Path("schedules/bestradio.json").write_text(json.dumps(
            {"http://best/stream": {"6": [["10:00", "12:00", "週末好事", ""]]}}), encoding="utf-8")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("nothing written", out)
        code, out = self.run_main("--apply")
        self.assertEqual(code, 0)
        doc = json.loads(pathlib.Path("programmes.json").read_text(encoding="utf-8"))
        self.assertEqual(set(doc["stations"]), {"https://n03.rcs.revma.com/ndk05tyy2tzuv", "http://best/stream"})
        self.assertEqual(doc["stations"]["http://best/stream"]["week"]["6"][0][2], "週末好事")
        self.assertIn("1 from a live source, 1 from a weekly grid", out)


if __name__ == "__main__":
    unittest.main()
