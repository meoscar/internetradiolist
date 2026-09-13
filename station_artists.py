#!/usr/bin/env python3
"""Who each station plays, counted over a month, for the app to read.

The live pass is a sample: one look at two hundred stations every few
minutes for part of each hour. As a claim about this minute it is late and
full of holes, and the app is right not to say "now" from it. As a record
of what was heard it is simply true, and a month of it says something no
single look can: this station played Donna Summer forty times, that one
never did. That is a fact a listener can act on, and the app puts it next
to their own history -- "the artists you hear most, and the stations that
play them" -- without either side leaving the phone it is on.

Two files. artists_tally.json is the working tally and is carried forward
from pass to pass on the live branch like week.json; station_artists.json
is the small, sorted, junk-free extract the app downloads.

What a "play" is here: one pass in which the station was heard playing a
line by that artist, and not the same line as the pass before. A record
that spans two passes counts once; a stream stuck on one title for a day
counts once. Nothing here is about right now, so nothing here claims it.

Each play also keeps its hour, so a month of them can say when a station
tends to play an artist -- "usually 20-22", in UTC, for the app to shift
into the listener's clock. A notice that a followed artist was on twelve
minutes ago is too late to catch the record; "this station usually plays
them in the evening" is something to act on tomorrow. Published only when
the plays are many enough and bunched enough to mean it.

  python3 station_artists.py           fold live.json in, write both files
"""
import json
import pathlib
import sys
import time

import notasong

LIVE = "live.json"
WEEK = "week.json"
TALLY = "artists_tally.json"
OUT = "station_artists.json"

KEEP_DAYS = 30
DAY = 86400

# The tally keeps more than it publishes, so an artist that drops out of
# the top of the list this week can climb back next week with history.
KEEP_PER_STATION = 80
PUBLISH_PER_STATION = 25

# Heard once in a month is not "plays": it is a sample the station's
# playlist happened to land on while we were looking.
MIN_PLAYS_PUBLISHED = 2

# When a station tends to play an artist, as a band of hours (UTC).
#
# The tally cannot say "now" and says so; what a month of it can say is
# "usually in the evening", which is the one form of "when" a listener
# can act on. A band is published only when it means something: at
# least this many plays, and at least this share of them inside the
# densest three-hour window. Otherwise the artist is played at all
# hours, or too rarely to tell, and nothing is claimed.
WHEN_MIN_PLAYS = 5
WHEN_WIDTH = 3
WHEN_SHARE = 0.4


def load(name, default):
    path = pathlib.Path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def split(raw):
    """"Artist - Title" on the first separator, as accumulate.py splits it."""
    line = " ".join((raw or "").split())
    i = line.find(" - ")
    return (line[:i].strip(), line[i + 3:].strip()) if i > 0 else ("", line)


def fold(tally, live, now):
    """One pass of live.json into the tally. Returns how many rows counted."""
    stations = tally.setdefault("stations", {})
    counted = 0
    for row in live.get("playing") or []:
        station_id = row.get("id") or ""
        if not station_id:
            continue
        artist, title = split(row.get("track"))
        fact = stations.setdefault(station_id, {
            "station": "", "passes": 0, "last": now, "artists": {}})
        fact["station"] = row.get("station") or fact["station"]
        fact["passes"] += 1
        fact["last"] = now

        # The same line as the pass before is the same record still going,
        # or a stream that never changes. Either way it is not a second play.
        line = notasong.fold(f"{artist} {title}")
        if line == fact.get("line"):
            continue
        fact["line"] = line

        if not artist or notasong.junk(artist, title, fact["station"]):
            continue
        key = notasong.fold(artist)
        if not key:
            continue
        seen = fact["artists"].setdefault(key, {"name": artist, "plays": 0, "last": now})
        seen["name"] = artist
        seen["plays"] += 1
        seen["last"] = now
        hours = seen.setdefault("hours", [0] * 24)
        hours[(now // 3600) % 24] += 1
        counted += 1
    return counted


def prune(tally, now):
    """A rolling month, and a bounded list per station."""
    cutoff = now - KEEP_DAYS * DAY
    stations = tally.get("stations", {})
    for station_id in list(stations):
        fact = stations[station_id]
        if fact.get("last", 0) < cutoff:
            del stations[station_id]
            continue
        artists = {k: a for k, a in fact["artists"].items() if a.get("last", 0) >= cutoff}
        if len(artists) > KEEP_PER_STATION:
            keep = sorted(artists.items(), key=lambda kv: -kv[1]["plays"])[:KEEP_PER_STATION]
            artists = dict(keep)
        fact["artists"] = artists


def when(hours, min_plays=WHEN_MIN_PLAYS, width=WHEN_WIDTH, share=WHEN_SHARE):
    """The hours an artist is usually played in, as "20-22" (UTC, both ends
    in), or None when the plays are too few or too spread out to say.

    The densest window of `width` hours, around the clock, so "23-1" is a
    band too. Among equally dense windows the one that starts on an hour
    with a play wins, then the earliest: six plays at nine o'clock are
    "9-11", not "7-9" with two empty hours in front."""
    if not hours or len(hours) != 24:
        return None
    total = sum(hours)
    if total < min_plays:
        return None
    best, start = -1, 0
    for i in range(24):
        inside = sum(hours[(i + k) % 24] for k in range(width))
        if inside > best or (inside == best and hours[i] > 0 and hours[start] == 0):
            best, start = inside, i
    if best / total < share:
        return None
    return f"{start}-{(start + width - 1) % 24}"


def row(a):
    """One published artist: name, plays, and the band when there is one."""
    out = [a["name"], a["plays"]]
    band = when(a.get("hours"))
    if band:
        out.append(band)
    return out


def publish(tally, week, now):
    """The extract the app reads: per station, who it plays and how often."""
    week_stations = (week or {}).get("stations", {})
    out = {}
    for station_id, fact in tally.get("stations", {}).items():
        ranked = sorted(fact["artists"].values(), key=lambda a: (-a["plays"], a["name"]))
        artists = [row(a) for a in ranked
                   if a["plays"] >= MIN_PLAYS_PUBLISHED][:PUBLISH_PER_STATION]
        entry = {"station": fact["station"], "passes": fact["passes"], "artists": artists}
        seen = week_stations.get(station_id)
        if seen:
            # How varied the station's week was: distinct titles against
            # passes heard. A station with 400 titles in 2,500 passes has a
            # playlist; one with 12 has a loop.
            entry["week_titles"] = len(seen.get("tracks", []))
            entry["week_passes"] = seen.get("plays", 0)
        if artists or seen:
            out[station_id] = entry
    return {"at": now, "days": KEEP_DAYS, "stations": out}


def main(argv):
    live = load(LIVE, None)
    if not live or not live.get("playing"):
        print(f"{LIVE} has nothing to fold in")
        return 0
    now = int(live.get("at") or time.time())
    tally = load(TALLY, {})
    counted = fold(tally, live, now)
    prune(tally, now)
    tally["updated"] = now
    pathlib.Path(TALLY).write_text(
        json.dumps(tally, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    doc = publish(tally, load(WEEK, {}), now)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    pathlib.Path(OUT).write_text(text, encoding="utf-8")

    artists = sum(len(s["artists"]) for s in doc["stations"].values())
    print(f"artists: {counted} plays counted this pass; "
          f"{len(doc['stations'])} stations, {artists} artists published, "
          f"{len(text) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
