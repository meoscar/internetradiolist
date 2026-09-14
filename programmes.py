#!/usr/bin/env python3
"""programmes.json: what programme each station is on, for the app to say.

Taiwan's broadcasters name their records almost nowhere and their
programmes everywhere. This writes the file the app reads (Programmes in
the app), one entry per station keyed by its stream:

    "live": {"kind": "bcc", "url": ..., "channel": "流行網"}
        a document the app asks every few minutes; only 中廣's kind so far
    "week": {"1": [["19:00", "20:00", "瓏賀哩共", "賀瓏"], ...], ..., "7": [...]}
        a weekly grid, day 1 Monday to 7 Sunday, read by the clock

The live entries are kept by hand below, matched to the streams in
taiwan.json by name. The grids come from each broadcaster's schedule
page, one scraper per site in schedules/, run weekly; a site without a
scraper yet has no grid.

    python3 programmes.py            build and report
    python3 programmes.py --apply    write programmes.json
"""
import json
import pathlib
import sys

TAIWAN = "taiwan.json"
OUT = "programmes.json"

BCC_API = "https://www.bcc.com.tw/webapi/BCCRadioWebAPI/ChannelInfoBat"

# 中廣's document lists its channels by name; the app finds each by these
# words in the name, spaces and case aside, so "中廣 i GO" is found by "igo".
LIVE = {
    "中廣流行網": {"kind": "bcc", "url": BCC_API, "channel": "流行網"},
    "中廣音樂網": {"kind": "bcc", "url": BCC_API, "channel": "音樂網"},
    "中廣新聞網": {"kind": "bcc", "url": BCC_API, "channel": "新聞網"},
    "中廣鄉親網": {"kind": "bcc", "url": BCC_API, "channel": "鄉親"},
    "中廣 I GO": {"kind": "bcc", "url": BCC_API, "channel": "igo"},
}


def build(stations, weeks=None):
    """The file's stations: a live source by name, a week by stream, or both."""
    out = {}
    for station in stations:
        stream = station.get("stream", "")
        entry = {}
        live = LIVE.get(station.get("name", ""))
        if live:
            entry["live"] = dict(live)
        week = (weeks or {}).get(stream)
        if week:
            entry["week"] = week
        if entry and stream:
            out[stream] = entry
    return out


def load(name, default):
    path = pathlib.Path(name)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def main(argv):
    apply_changes = "--apply" in argv
    stations = load(TAIWAN, None)
    if stations is None:
        print(f"{TAIWAN} is not here; run taiwan.py first")
        return 1
    weeks = {}
    for path in sorted(pathlib.Path("schedules").glob("*.json")) if pathlib.Path("schedules").exists() else []:
        weeks.update(load(str(path), {}))
    built = build(stations, weeks)
    live = sum(1 for e in built.values() if "live" in e)
    grids = sum(1 for e in built.values() if "week" in e)
    print(f"{len(built)} stations say their programme: {live} from a live source, {grids} from a weekly grid")
    if not apply_changes:
        print(f"nothing written; run with --apply to write {OUT}")
        return 0
    pathlib.Path(OUT).write_text(
        json.dumps({"stations": built}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
