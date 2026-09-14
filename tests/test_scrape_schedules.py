"""Each broadcaster's schedule, read off a copy of its page under probes/schedules/."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import scrape_schedules as ss  # noqa: E402

COPIES = pathlib.Path(__file__).resolve().parent.parent / "probes" / "schedules"


def page(name):
    return (COPIES / f"{name}.html").read_text(encoding="utf-8")


def find(week, day, name):
    return next((s for s in week.get(str(day), []) if s[2] == name), None)


class Helpers(unittest.TestCase):
    def test_a_clock_is_read_in_every_shape_the_sites_write_it(self):
        self.assertEqual(ss.hhmm("19:00"), (19, 0))
        self.assertEqual(ss.hhmm("7:05"), (7, 5))
        self.assertEqual(ss.hhmm("12:00 am"), (0, 0))
        self.assertEqual(ss.hhmm("12:30 PM"), (12, 30))
        self.assertEqual(ss.hhmm("6:30 PM"), (18, 30))
        self.assertEqual(ss.hhmm("05AM"), (5, 0))
        self.assertEqual(ss.hhmm("12PM"), (12, 0))
        self.assertEqual(ss.hhmm("01PM"), (13, 0))
        self.assertIsNone(ss.hhmm("時段"))
        self.assertIsNone(ss.hhmm("25:00"))

    def test_a_table_is_read_with_its_spans(self):
        t = ss.Tables("<table><tr><td rowspan='2'>a</td><td colspan='2'>b</td></tr><tr><td>c</td><td>d</td></tr></table>")
        placed = [(r, c, t.inner(cell)) for r, c, cell in ss.grid(t.tables[0]["rows"])]
        self.assertEqual(placed, [(0, 0, "a"), (0, 1, "b"), (1, 1, "c"), (1, 2, "d")])


class Sites(unittest.TestCase):
    def test_ufo_lists_each_weekday_with_a_time_a_name_and_a_host(self):
        week = ss.ufo({"1": page("ufo-mon"), "6": page("ufo-sat"), "0": page("ufo-sun")})
        self.assertEqual(sorted(week), ["1", "6", "7"])
        self.assertEqual(find(week, 1, "飛碟早餐"), ["07:00", "09:00", "飛碟早餐", "唐湘龍"])
        self.assertEqual(find(week, 7, "夜光家族(重播)"), ["00:00", "02:00", "夜光家族(重播)", "光禹"])
        self.assertEqual(week["1"][0][0], "00:00")
        self.assertTrue(all(len(s) == 4 for day in week.values() for s in day))

    def test_bestradio_puts_the_weekday_column_on_five_days_and_the_others_on_one(self):
        week = ss.bestradio(page("bestradio-989"))
        self.assertEqual(sorted(week, key=int), ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(find(week, 3, "989陽光列車"), ["09:00", "12:00", "989陽光列車", "亭君"])
        self.assertEqual(find(week, 1, "好事愛情歌"), ["00:00", "06:00", "好事愛情歌", "愛情DJ"])
        self.assertEqual(find(week, 6, "好事愛情歌"), ["00:00", "06:00", "好事愛情歌", "愛情DJ"])
        self.assertIsNotNone(find(week, 6, "好事假日瘋音樂"))
        self.assertIsNotNone(find(week, 7, "好事假日瘋音樂"))
        self.assertIsNone(find(week, 6, "989陽光列車"))
        early = find(week, 1, "好事新鮮早報")
        self.assertEqual(early[:2], ["06:00", "09:00"])
        self.assertIn("毛亮傑", early[3])

    def test_hitfm_reads_hours_down_and_days_across_with_spans_for_both(self):
        week = ss.hitfm(page("hitfm"))
        self.assertEqual(find(week, 1, "活力DJ"), ["09:00", "12:00", "活力DJ", "阿娟"])
        self.assertEqual(find(week, 5, "活力DJ"), ["09:00", "12:00", "活力DJ", "阿娟"])
        self.assertIsNone(find(week, 6, "活力DJ"))
        self.assertEqual(find(week, 1, "只想聽音樂")[:2], ["05:00", "06:00"])
        sat = [s for s in week["6"] if s[0] == "09:00"]
        self.assertTrue(sat and "Phoenix" in sat[0][3], sat)

    def test_asiafm_reads_each_station_tab_with_the_event_hours_and_days(self):
        week = ss.asiafm(page("asiafm"), "asia927")
        self.assertEqual(find(week, 1, "非凡操盤手"), ["06:00", "06:30", "非凡操盤手", "葉俊敏"])
        self.assertEqual(find(week, 1, "音樂不打烊")[:2], ["00:00", "06:00"])
        self.assertEqual(sorted(week, key=int), ["1", "2", "3", "4", "5", "6", "7"])
        other = ss.asiafm(page("asiafm"), "asia923")
        self.assertTrue(other and other != week)
        self.assertEqual(ss.asiafm(page("asiafm"), "nowhere"), {})

    def test_csbc_ends_a_show_where_the_next_on_its_day_starts(self):
        week = ss.csbc(page("csbc-tpfm"))
        self.assertEqual(find(week, 5, "悠遊音樂城")[:2], ["00:00", "01:00"])
        self.assertEqual(find(week, 5, "YOYO Live Show")[:2], ["01:00", "03:00"])
        self.assertEqual(sorted(week, key=int), ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(week["5"][-1][1], "24:00")


if __name__ == "__main__":
    unittest.main()
