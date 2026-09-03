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

# Stations asked what they are playing. The busiest, because those are the ones
# anybody is listening to and the ones a "right now" screen should show.
STATIONS = 200
WORKERS = 40

# Genres whose first listing page is read for live listener counts. Six, and the
# six biggest, so the pass stays small and still covers most listeners.
TRENDING_GENRES = ("pop", "rock", "dance", "oldies", "house", "jazz")

# How many entries each section of the file carries.
TICKER = 40
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


def busiest_stations(catalogue, directory, limit):
    """The published stations, ordered by how many people the crawl last saw."""
    listeners = {s["stream"]: s.get("listeners") or 0 for s in directory}
    rows = [r for r in catalogue if (r.get("source") or "").startswith("http")]
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


def live_counts(fetch):
    """Listener counts from the site's own listing rows, six pages of them."""
    counts = {}
    for slug in TRENDING_GENRES:
        page = fetch.get(f"{crawl_directory.GENRE_INDEX}{slug}/")
        if not page:
            continue
        for station in crawl_directory.parse_rows(page, slug):
            if station.get("listeners") is None:
                continue
            counts[station["stream"]] = {
                "name": station["name"],
                "genre": slug,
                "listeners": station["listeners"],
            }
    return counts


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

    stations = busiest_stations(catalogue, directory, args.stations)
    print(f"asking {len(stations)} stations what they are playing")
    playing = what_is_playing(stations)
    print(f"  {len(playing)} answered with a track "
          f"({len(playing) * 100 // max(len(stations), 1)}%)")

    # ---- who is being listened to, from the site, sparingly ----

    fetch = crawl_directory.Fetcher(len(TRENDING_GENRES))
    counts = live_counts(fetch)
    print(f"\n{len(counts)} live listener counts from {fetch.made} pages "
          f"({fetch.failed} failed)")

    # Rising, not top. The busiest stations are the same every hour; the ones
    # people are turning to in the last fifteen minutes are not.
    before = {row["id"]: row.get("listeners", 0)
              for row in previous.get("rising", []) + previous.get("top", [])}
    rising = []
    for stream, fact in counts.items():
        was = before.get(stream)
        if was is None or fact["listeners"] <= was:
            continue
        rising.append({
            "id": stream,
            "station": fact["name"],
            "genre": fact["genre"],
            "listeners": fact["listeners"],
            "gained": fact["listeners"] - was,
        })
    rising.sort(key=lambda r: -r["gained"])
    rising = rising[:RISING]

    # The busiest station in each genre we looked at. This is what "#1" should
    # have meant all along: not the first row of a list, but the one most people
    # are listening to, which is a different station on a different day.
    number_ones = {}
    for stream, fact in counts.items():
        best = number_ones.get(fact["genre"])
        if best is None or fact["listeners"] > best["listeners"]:
            number_ones[fact["genre"]] = {
                "id": stream,
                "station": fact["name"],
                "genre": fact["genre"],
                "listeners": fact["listeners"],
            }

    top = sorted(
        ({"id": s, **{k: v for k, v in f.items() if k != "name"},
          "station": f["name"]} for s, f in counts.items()),
        key=lambda r: -r["listeners"])[:RISING]

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
