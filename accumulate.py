#!/usr/bin/env python3
"""Remember what the stations played, so a week of it can be counted.

live.json is one instant. It is thrown away and rebuilt every quarter of an
hour, so on its own it can never answer "what did radio play this week" -- and
that question is the one nothing else can answer, because a chart built from
what stations actually broadcast is a different thing from a chart built from
what a label promoted.

Ninety-six passes a day over about a hundred and sixty-five stations is roughly
sixteen thousand observations a day. Kept as raw rows that is unmanageable;
kept as counts it is small, because radio repeats. So this folds each pass into
a running tally: how many times a track has been seen, on how many stations,
and when it was first and last heard.

It also answers the second question at the same time. Knowing which tracks a
station plays is what makes it possible to say that one station's music
averages 1987 and another's 2021, which is a fact about a station that no genre
tag carries.

Anything not heard for eight days is dropped, so the file describes a rolling
week and stops growing.

  python3 accumulate.py            fold live.json into week.json
"""
import json
import pathlib
import re
import sys
import time
import unicodedata

LIVE = "live.json"
WEEK = "week.json"

KEEP_DAYS = 8
SECONDS_PER_DAY = 86400

# Junk a station puts through the same field it uses for songs.
NOT_A_TRACK = re.compile(
    r"advert|commercial|jingle|station\s?id|no title|^unknown$|nonstop|non-stop"
    r"|https?://|www\.", re.I)


def normalise(text):
    flat = unicodedata.normalize("NFKD", (text or "").lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", flat)).strip()


def split(raw):
    """"Artist - Title", where the station sent both.

    Only the first separator: titles carry dashes far more often than artist
    names do, so splitting on the last one mangles them.
    """
    line = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", " ", (raw or "")).strip()
    line = re.sub(r"\s+", " ", line)
    i = line.find(" - ")
    if i > 0:
        return line[:i].strip(), line[i + 3:].strip()
    return "", line


def load(name, default):
    path = pathlib.Path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def main(argv):
    live = load(LIVE, None)
    if not live or not live.get("playing"):
        print(f"{LIVE} has nothing to fold in")
        return 0

    week = load(WEEK, {})
    tracks = week.get("tracks", {})
    stations = week.get("stations", {})
    now = int(live.get("at") or time.time())

    added = seen = skipped = 0
    for row in live["playing"]:
        raw = (row.get("track") or "").strip()
        artist, title = split(raw)
        if not title or len(title) < 2 or NOT_A_TRACK.search(raw):
            skipped += 1
            continue
        key = normalise(f"{artist} {title}")
        if len(key) < 3:
            skipped += 1
            continue

        seen += 1
        entry = tracks.get(key)
        if entry is None:
            entry = {"artist": artist, "title": title, "plays": 0,
                     "stations": [], "first": now, "last": now}
            tracks[key] = entry
            added += 1
        entry["plays"] += 1
        entry["last"] = now
        station_id = row.get("id") or ""
        if station_id and station_id not in entry["stations"]:
            entry["stations"].append(station_id)

        # What this station plays, which is what an era is computed from.
        fact = stations.setdefault(station_id, {
            "name": row.get("station", ""), "plays": 0, "tracks": []})
        fact["name"] = row.get("station", "") or fact["name"]
        fact["plays"] += 1
        if key not in fact["tracks"]:
            fact["tracks"].append(key)

    # A rolling week. Without this the file grows for ever and the chart stops
    # being about this week.
    cutoff = now - KEEP_DAYS * SECONDS_PER_DAY
    stale = [k for k, v in tracks.items() if v.get("last", 0) < cutoff]
    for key in stale:
        del tracks[key]
    if stale:
        alive = set(tracks)
        for fact in stations.values():
            fact["tracks"] = [k for k in fact["tracks"] if k in alive]

    week = {"updated": now, "days": KEEP_DAYS,
            "tracks": tracks, "stations": stations}
    text = json.dumps(week, ensure_ascii=False, separators=(",", ":")) + "\n"
    pathlib.Path(WEEK).write_text(text, encoding="utf-8")

    total = sum(v["plays"] for v in tracks.values())
    print(f"folded in {seen} of {len(live['playing'])} "
          f"({skipped} were not tracks)")
    print(f"  {added:6d}  heard for the first time")
    print(f"  {len(stale):6d}  dropped, not heard for {KEEP_DAYS} days")
    print(f"  {len(tracks):6d}  distinct tracks, {total} plays")
    print(f"  {len(stations):6d}  stations")
    print(f"  {len(text) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
