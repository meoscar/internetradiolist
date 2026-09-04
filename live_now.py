#!/usr/bin/env python3
"""What is happening on the radio right now, refreshed every quarter of an hour.

The catalogue answers "what stations exist", which changes weekly at most. This
answers "what is playing" and "what is people are turning to", which changes all
the time, and it is what makes a screen feel alive rather than filed.

Two sources, deliberately weighted:

  The stations themselves, for what is playing. An ICY handshake returns the
  track the station is playing this second, from the station, first-hand. Two
  hundred of them, once every fifteen minutes, is one touch per station per
  quarter hour spread across two hundred different hosts -- nothing to anyone.

  internet-radio.com, for listener counts, and as little of it as will do. Its
  listing rows carry a live count, and six pages give the busiest stations in
  the six biggest genres. Six requests a quarter of an hour is one request
  every two and a half minutes.

That asymmetry is the whole design. This repository already measured that site
refusing connections from datacentre addresses, and it is the source the weekly
crawl depends on; asking it ninety-six times a day for something the stations
will tell us directly would risk the crawl to save nothing.

  python3 live_now.py            build live.json
  python3 live_now.py --stations 40   a smaller pass, for looking at
"""
import argparse
import json
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import crawl_directory
import harvest_icy

CATALOGUE = "music_worldradio.json"
DIRECTORY = "directory.json"
OUT = "live.json"
COUNTS = "counts.json"

# Stations asked what they are playing. The busiest, because those are the ones
# anybody is listening to and the ones a "right now" screen should show.
STATIONS = 200
WORKERS = 40

# Genres whose first listing page is read for live listener counts. Six, and the
# six biggest, so the pass stays small and still covers most listeners.
TRENDING_GENRES = ("pop", "rock", "dance", "oldies", "house", "jazz")

# How many entries each section of the file carries. The ticker keeps every
# station that answered rather than a top slice: at about 250 bytes a row the
# whole set is a few tens of kilobytes, and a screen that cycles through 160
# stations takes far longer to repeat itself than one cycling through 40.
TICKER = 250
RISING = 12


def load(name, default=None):
    path = pathlib.Path(name)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def items_of(doc):
    if isinstance(doc, list):
        return doc
    for key in ("music", "stations", "items", "data"):
        if isinstance(doc.get(key), list):
            return doc[key]
    return []


def playable_index(catalogue):
    """Catalogue rows by the stream they play, one row per stream.

    Twenty stations are in the catalogue twice: once under their genre and
    again under On Trend, which was a hand-picked list. Both copies point at
    the same stream, so asking both wastes a twentieth of the pass and puts
    the same station in the ticker twice. The genre copy wins -- its id is the
    stream URL, which is what everything else keys on.
    """
    by_source = {}
    for row in catalogue:
        source = row.get("source") or ""
        if not source.startswith("http"):
            continue
        kept = by_source.get(source)
        if kept is None or (not str(kept.get("id", "")).startswith("http")
                            and str(row.get("id", "")).startswith("http")):
            by_source[source] = row
    return by_source


def playlist_to_stream(directory):
    """The site links a .pls; the catalogue plays what the .pls points at.

    A listing row names a playlist file, and the crawl already followed each
    one and wrote down where it led. Without this map every listener count we
    read is about a URL the app has never heard of, so nothing on a "most
    listened to" tile could be tapped.
    """
    resolved = {}
    for station in directory:
        stream = station.get("stream")
        if not stream:
            continue
        resolved[stream] = stream
        if station.get("playlist"):
            resolved[station["playlist"]] = stream
    return resolved


def busiest_stations(by_source, directory, limit):
    """The published stations, ordered by how many people the crawl last saw."""
    listeners = {s["stream"]: s.get("listeners") or 0 for s in directory}
    rows = list(by_source.values())
    rows.sort(key=lambda r: -listeners.get(r["source"], 0))
    return rows[:limit]


def what_is_playing(stations):
    """Ask each station, in parallel, what it is playing."""
    def ask(row):
        facts = harvest_icy.interrogate(row["source"])
        title = (facts.get("stream_title") or "").strip()
        if not facts.get("ok") or not title:
            return None
        return {
            "id": row.get("id") or row["source"],
            "station": row.get("title", ""),
            "image": row.get("image", ""),
            "genre": row.get("genre", ""),
            "track": title,
        }

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(ask, stations))
    return [a for a in answers if a]


def live_counts(fetch, resolved):
    """Listener counts from the site's own listing rows, six pages of them.

    Keyed by the stream the app would play, not by the playlist file the site
    links to, so a count can be joined to a station we can actually offer.
    """
    counts = {}
    for slug in TRENDING_GENRES:
        page = fetch.get(f"{crawl_directory.GENRE_INDEX}{slug}/")
        if not page:
            continue
        for station in crawl_directory.parse_rows(page, slug):
            if station.get("listeners") is None:
                continue
            stream = resolved.get(station["stream"], station["stream"])
            counts[stream] = {
                "name": station["name"],
                "genre": slug,
                "listeners": station["listeners"],
            }
    return counts


def as_station(stream, fact, by_source, tracks):
    """One entry of a listener chart, told in the app's own terms.

    The count and the genre come from the site. Everything the screen shows --
    the id to play, the name, the logo, and the track it is playing this
    minute -- comes from our own catalogue and our own pass, when we have it.
    A station we cannot play still counts towards nothing: it is dropped,
    because a tile that cannot be tapped is worse than one fewer tile.
    """
    row = by_source.get(stream)
    if row is None:
        return None
    entry = {
        "id": row.get("id") or stream,
        "station": row.get("title") or fact["name"],
        "image": row.get("image", ""),
        "genre": fact["genre"],
        "listeners": fact["listeners"],
    }
    track = tracks.get(entry["id"])
    if track:
        entry["track"] = track
    return entry


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", type=int, default=STATIONS)
    args = parser.parse_args(argv[1:])

    catalogue = items_of(load(CATALOGUE, {"music": []}))
    directory = load(DIRECTORY, [])
    if not catalogue:
        print(f"{CATALOGUE} is not here; nothing to report on")
        return 1

    previous = load(OUT, {})
    started = time.time()

    # ---- what is playing, from the stations ----

    by_source = playable_index(catalogue)
    resolved = playlist_to_stream(directory)
    stations = busiest_stations(by_source, directory, args.stations)
    print(f"asking {len(stations)} stations what they are playing")
    playing = what_is_playing(stations)
    print(f"  {len(playing)} answered with a track "
          f"({len(playing) * 100 // max(len(stations), 1)}%)")
    tracks = {row["id"]: row["track"] for row in playing}

    # ---- who is being listened to, from the site, sparingly ----

    fetch = crawl_directory.Fetcher(len(TRENDING_GENRES))
    counts = live_counts(fetch, resolved)
    known = sum(1 for stream in counts if stream in by_source)
    print(f"\n{len(counts)} live listener counts from {fetch.made} pages "
          f"({fetch.failed} failed); {known} are stations we can play")

    # Rising, not top. The busiest stations are the same every hour; the ones
    # people are turning to in the last fifteen minutes are not.
    charted = {}
    for stream, fact in counts.items():
        entry = as_station(stream, fact, by_source, tracks)
        if entry:
            charted[stream] = entry

    before = {row["id"]: row.get("listeners", 0)
              for row in previous.get("rising", []) + previous.get("top", [])}
    rising = []
    for stream, entry in charted.items():
        was = before.get(entry["id"])
        if was is None or entry["listeners"] <= was:
            continue
        rising.append(dict(entry, gained=entry["listeners"] - was))
    rising.sort(key=lambda r: -r["gained"])
    rising = rising[:RISING]

    # The busiest station in each genre we looked at. This is what "#1" should
    # have meant all along: not the first row of a list, but the one most people
    # are listening to, which is a different station on a different day.
    number_ones = {}
    for entry in charted.values():
        best = number_ones.get(entry["genre"])
        if best is None or entry["listeners"] > best["listeners"]:
            number_ones[entry["genre"]] = entry

    top = sorted(charted.values(), key=lambda r: -r["listeners"])[:RISING]

    live = {
        # Unix seconds. The app shows "x minutes ago" from this rather than
        # claiming to be live: GitHub's schedules run late under load and
        # sometimes not at all, and a stale figure presented as current is
        # worse than an honest one.
        "at": int(time.time()),
        "every_minutes": 15,
        "playing": playing[:TICKER],
        "rising": rising,
        "number_ones": sorted(number_ones.values(), key=lambda r: -r["listeners"]),
        "top": top,
    }

    pathlib.Path(OUT).write_text(
        json.dumps(live, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    # Every count this pass saw, which is far more than live.json publishes.
    #
    # The file above carries the handful of entries a screen can use, and the
    # app downloads it every few minutes, so it is not the place to put a
    # column of several hundred numbers nothing on screen reads. But those
    # numbers are the only record of how a station's audience moved, and
    # thrown away each pass the best question they can answer is "since the
    # last quarter of an hour". accumulate.py folds this into a series in the
    # same job, seconds later; nothing else ever fetches it.
    pathlib.Path(COUNTS).write_text(
        json.dumps({
            "at": live["at"],
            "counts": {entry["id"]: {"n": entry["listeners"],
                                     "station": entry["station"]}
                       for entry in charted.values()},
        }, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    text = pathlib.Path(OUT).read_text(encoding="utf-8")
    print(f"\n{OUT}: {len(text) / 1024:.1f} KB in {time.time() - started:.0f}s")
    print(f"  {len(live['playing']):3d}  stations naming a track")
    print(f"  {len(live['rising']):3d}  gaining listeners since the last pass")
    print(f"  {len(live['number_ones']):3d}  genre leaders")
    if not previous:
        print("\n  (nothing to compare against yet, so nothing is rising;")
        print("   the next pass will have a previous one to measure from)")

    if playing:
        print("\nplaying right now:")
        for row in playing[:6]:
            print(f"  {row['station'][:30]:30}  {row['track'][:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
