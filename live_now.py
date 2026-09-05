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

  The stations themselves, for who is listening. Icecast publishes a status
  document and Shoutcast a stats table, both on the server we are already
  connecting to in the same pass, so the count arrives from the same place as
  the track and is true at the same moment.

  internet-radio.com, now only for the stations our pass does not reach. Six
  genre pages, once a quarter of an hour, filling in stations outside the two
  hundred busiest. --no-site runs without it.

That last one used to be the only source of a listener count, and it was the
only thing here that needed somebody else's website every fifteen minutes
rather than once a week. It asked a slightly different question, too: the site
knows what it last saw, and we want what is true now.

The asymmetry is still the whole design. This repository already measured that
site refusing connections from datacentre addresses, and it is the source the
weekly crawl depends on; every request we do not make to it is a risk we do
not take with the crawl.

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
import station_status

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


def interrogate(stations):
    """Ask each station, in parallel, what it is playing and who is listening.

    Both answers come from the station's own server, in the same pass, and
    the second one is why this function replaced what_is_playing: the listener
    count was the last thing in this repository that needed somebody else's
    website every fifteen minutes rather than once a week.

    It is one small HTTP request per station on top of the stream connection
    we were making anyway -- two hundred hosts, four times an hour, one touch
    each. The site pass it replaces was six requests to one host.

    Returns (playing, counts): the stations that named a track, and every
    stream that named a number. A station can do either, both or neither.
    """
    def ask(row):
        stream = row["source"]
        facts = harvest_icy.interrogate(stream)
        title = (facts.get("stream_title") or "").strip()

        entry = None
        if facts.get("ok") and title:
            entry = {
                "id": row.get("id") or stream,
                "station": row.get("title", ""),
                "image": row.get("image", ""),
                "genre": row.get("genre", ""),
                "track": title,
            }
        # Asked even when the stream would not talk to us: a station can
        # refuse the metadata channel and still publish a status document.
        return entry, (stream, station_status.listeners_of(stream))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(ask, stations))

    playing = [entry for entry, _ in answers if entry]
    counts = {stream: n for _, (stream, n) in answers if n is not None}
    return playing, counts


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
    parser.add_argument("--no-site", dest="site", action="store_false",
                        help="do not read internet-radio.com at all; the "
                             "stations' own counts only")
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
    print(f"asking {len(stations)} stations what they are playing "
          f"and who is listening")
    playing, from_stations = interrogate(stations)
    asked = max(len(stations), 1)
    print(f"  {len(playing)} named a track ({len(playing) * 100 // asked}%)")
    print(f"  {len(from_stations)} named a listener count "
          f"({len(from_stations) * 100 // asked}%)")
    tracks = {row["id"]: row["track"] for row in playing}

    # ---- who is being listened to ----
    #
    # The stations first, because they are the ones who know and because
    # asking them costs this repository nothing it does not already spend.
    counts = {}
    for stream, number in from_stations.items():
        row = by_source.get(stream)
        if row is None:
            continue
        counts[stream] = {
            "name": row.get("title", ""),
            "genre": row.get("genre", ""),
            "listeners": number,
            "from": "station",
        }

    # Then the site, for the stations our pass did not reach -- it reads six
    # genre pages and we ask the two hundred busiest, so each covers stations
    # the other does not. Kept until a run shows what it is still adding;
    # --no-site runs without it, which is the point of the comparison below.
    agreed = []
    if args.site:
        fetch = crawl_directory.Fetcher(len(TRENDING_GENRES))
        for stream, fact in live_counts(fetch, resolved).items():
            ours = counts.get(stream)
            if ours is None:
                counts[stream] = dict(fact, **{"from": "site"})
            else:
                agreed.append((ours["listeners"], fact["listeners"]))
        print(f"\n{fetch.made} pages read from the site ({fetch.failed} failed)")
    else:
        print("\nthe site was not asked")

    added = sum(1 for f in counts.values() if f["from"] == "site")
    print(f"  {len(counts)} counts in all: "
          f"{len(counts) - added} from the stations, {added} only the site had")

    # Where both answered, do they agree? A station that says 40 while the
    # site says 2,201 means one of the two is measuring something else, and
    # the chart is built on whichever we believe. Worth knowing before the
    # site pass is dropped, and worth knowing if it is not.
    if agreed:
        close = sum(1 for ours, theirs in agreed
                    if max(ours, theirs) <= 1.25 * max(min(ours, theirs), 1))
        print(f"  {len(agreed)} station{'' if len(agreed) == 1 else 's'} "
              f"answered both ways, {close} of them within 25%")
        for ours, theirs in sorted(agreed, key=lambda p: -abs(p[0] - p[1]))[:3]:
            print(f"      station said {ours:6}   site said {theirs:6}")

    known = sum(1 for stream in counts if stream in by_source)
    print(f"  {known} are stations we can play")

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
