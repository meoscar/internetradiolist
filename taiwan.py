#!/usr/bin/env python3
"""Taiwan's stations, kept by hand, from what the probe measured.

The catalogue is built from internet-radio.com, which lists one station in
Taiwan. Radio Browser lists 215, and probe_taiwan.py has tried every one of
their streams from GitHub's network. This turns that measurement into the
list the app carries: every station whose stream answered, once each, with
the rows that are not Taiwanese stations left out by name and with the
reason written next to the name.

    python3 taiwan.py            build and report
    python3 taiwan.py --apply    write taiwan.json, and file each under TW in countries.json

What is kept per station: the name as the directory has it, the stream, the
station's own homepage, the favicon the directory recorded, its tags, its
vote count (which orders the list; it is not an audience), the codec, and
whether the stream is an HLS playlist. build_catalogue.py reads taiwan.json
and puts every row under the TAIWAN heading after ICRT; check_stations.py
then watches the streams like every other, and harvest_logos.py asks the
homepages for a logo.

Nothing here reaches the network. The two files it reads are written by the
probe, from Actions, because the sandbox this repository is edited from
cannot reach the directory or the stations.
"""
import json
import pathlib
import re
import sys
import unicodedata

ROWS = "probes/taiwan_radio_browser.json"
STREAMS = "probes/taiwan_streams.json"
OUT = "taiwan.json"
COUNTRIES = "countries.json"

# Rows filed under TW that are not stations in Taiwan, or not stations, by
# the name the directory gives them. Each with its reason, so the next
# person can disagree with one line rather than with a list.
EXCLUDE = {
    "電台測試2": "a test row",
    "https://www.csbc.com.tw": "an address where a name should be",
    "Abdulbasit Abdulsamad": "a recitation feed, not a station in Taiwan",
    "Supreme Master TV": "a television feed",
    "BIG BIG MIX – 乐享音乐": "not a station in Taiwan",
    "福建東南廣播": "broadcasts from Fujian, filed under TW",
    "海峽之聲廣播電台": "broadcasts from Fujian, filed under TW",
    "神州之聲": "broadcasts from Fujian, filed under TW",
    "台海之聲": "broadcasts from Fujian, filed under TW",
    "上海麗都廣播電台 1940's Shanghai Vintage Jazz": "not a station in Taiwan",
    "中國華藝廣播公司 AM873": "broadcasts from Fujian, filed under TW",
}

# Where a station names its records on its own site, by the name the
# directory files it under. The app reads each by the shape of the
# address (NowSources in the app); an address of a shape it does not
# know is a page it will not read, so add one only after adding the
# reader. M Radio's list and 古典音樂台's document were measured on
# 14 September 2026 (probes/taiwan_nowplaying.txt); KISS's log waits on
# the evening's samples.
NOW_SOURCES = {
    "M Radio 全國廣播": "https://api.mradio.tw/api/song/get-recent-songs",
    "Classical 古典音樂台 FM 97.7": "https://www.family977.com.tw/toXML.xml",
}

NOT_A_LETTER = re.compile(r"[^\w]+")


def name_key(name):
    """One key for the spellings a station is filed under: width, case and punctuation folded."""
    folded = unicodedata.normalize("NFKC", name or "").casefold()
    return NOT_A_LETTER.sub("", folded)


def build(rows, streams):
    """The rows to keep, most voted first, and what was dropped with why."""
    kept, dropped = [], []
    seen_streams, seen_names = set(), set()
    ordered = sorted(rows, key=lambda r: -(r.get("votes") or 0))
    for row in ordered:
        name = (row.get("name") or "").strip()
        stream = (row.get("url_resolved") or row.get("url") or "").strip()
        why = None
        if name in EXCLUDE:
            why = EXCLUDE[name]
        elif not stream.startswith("http"):
            why = "no stream address"
        elif stream in seen_streams:
            why = "the same stream, already kept"
        elif name_key(name) in seen_names:
            why = "the same name, already kept"
        elif not (streams.get(stream) or {}).get("reachable"):
            why = "the stream did not answer when probed"
        if why:
            dropped.append((name, why))
            continue
        seen_streams.add(stream)
        seen_names.add(name_key(name))
        answer = streams.get(stream) or {}
        favicon = (row.get("favicon") or "").strip()
        kept.append({
            "name": name,
            "stream": stream,
            "homepage": (row.get("homepage") or "").strip(),
            "favicon": favicon if favicon.startswith("https://") else "",
            "tags": [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()],
            "votes": int(row.get("votes") or 0),
            "codec": (row.get("codec") or "").strip().upper(),
            "hls": bool(answer.get("hls")),
            "site": NOW_SOURCES.get(name, ""),
        })
    return kept, dropped


def with_taiwan(countries, kept):
    """countries.json with every kept stream filed under TW; nothing else touched."""
    out = dict(countries)
    for station in kept:
        out[station["stream"]] = "TW"
    return out


def load(name, default):
    path = pathlib.Path(name)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv):
    apply_changes = "--apply" in argv
    rows = load(ROWS, None)
    streams = load(STREAMS, None)
    if rows is None or streams is None:
        print(f"{ROWS} and {STREAMS} are written by probe_taiwan.py, from Actions; run it first")
        return 1

    kept, dropped = build(rows, streams)
    print(f"{len(rows)} rows filed under TW; {len(kept)} kept, {len(dropped)} dropped")
    reasons = {}
    for _, why in dropped:
        reasons[why] = reasons.get(why, 0) + 1
    for why, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4}  {why}")
    hls = sum(1 for s in kept if s["hls"])
    print(f"{sum(1 for s in kept if s['site'])} name their records on their own site")
    print(f"\n{hls} of the {len(kept)} kept stream HLS; "
          f"{sum(1 for s in kept if s['favicon'])} carry a favicon; "
          f"{sum(1 for s in kept if s['homepage'])} name a homepage")

    if not apply_changes:
        print(f"\nnothing written; run with --apply to write {OUT} and file them in {COUNTRIES}")
        return 0
    pathlib.Path(OUT).write_text(
        json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    countries = with_taiwan(load(COUNTRIES, {}), kept)
    pathlib.Path(COUNTRIES).write_text(
        json.dumps(countries, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}: {len(kept)} stations; {COUNTRIES}: {len(countries)} streams")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
