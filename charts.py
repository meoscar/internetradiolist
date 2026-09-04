#!/usr/bin/env python3
"""What radio actually played this week, and how old each station's music is.

Two things, from the same tally, because they need the same lookups.

THE CHART. Built from what stations broadcast rather than from what a label
promoted, which as far as I can tell nobody else publishes. A week of quarter-
hourly passes over a hundred and sixty-five stations is on the order of a
hundred thousand observations, and counting them is the whole trick: no
simultaneity is needed, which matters because measuring it showed that two
stations almost never play the same record at the same instant. Over a week
they play the same records constantly.

THE ERA. iTunes knows when a record came out. The median release year of what a
station plays is a fact about that station that no genre tag carries: "this one
averages 1987" says more than "OLDIES", and it is sortable, so the most
nostalgic station in the catalogue becomes a thing you can find.

Release years are looked up once and remembered for ever, and each run does a
bounded number of them, because Apple asks for about twenty requests a minute
and returned 429 for a third of them when this repository ignored that. So the
year coverage starts thin and fills in over the following runs.

  python3 charts.py                 build charts.json
  python3 charts.py --lookups 0     no network, use only the years already known
"""
import argparse
import json
import math
import pathlib
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

WEEK = "week.json"
YEARS = "years.json"
OUT = "charts.json"

ENDPOINT = "https://itunes.apple.com/search"
PAUSE = 3.0            # what Apple publishes, and 429s below it
TIMEOUT = 10
LOOKUPS = 300          # per run; the cache is permanent so coverage accrues

TOP_TRACKS = 40
TOP_ARTISTS = 25
TOP_STATIONS = 30

# Enough of a station's music dated before calling its era anything.
MIN_DATED = 6
# Enough plays before a track is worth looking a year up for.
MIN_PLAYS_FOR_LOOKUP = 2

# Two stations that play the same records are alike, and nothing else in this
# repository can say so: a genre tag is what somebody typed, and this is what
# was actually broadcast. The thresholds are what stop it saying so on no
# evidence -- a station heard playing four tracks shares one of them with
# somebody by chance, and that is not a recommendation.
MIN_TRACKS_FOR_SIMILAR = 12
MIN_SHARED_TRACKS = 2
SIMILAR_PER_STATION = 8

# Who is being found. On Trend answers "gaining since the last quarter of an
# hour", which is mostly the ordinary breathing of an audience; this answers
# "gaining over days", which is a different and slower thing. A station has to
# have been watched long enough for the difference to be a trend rather than a
# time of day, and to have had an audience to start with -- three listeners
# becoming twelve is a 300% rise and tells nobody anything.
MIN_TREND_HOURS = 36
MIN_LISTENERS_BEFORE = 25
CLIMBING = 20


def load(name, default):
    path = pathlib.Path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def year_of(artist, title):
    """The release year iTunes gives for this record, or None.

    Returns the string "none" for a confident miss so it is remembered and not
    asked again every run; a network failure returns None and is retried.
    """
    term = f"{artist} {title}".strip()
    if len(term) < 3:
        return "none"
    url = (f"{ENDPOINT}?term={urllib.parse.quote(term)}"
           f"&entity=song&limit=1")
    request = urllib.request.Request(url, headers={
        "User-Agent": "WorldRadio-Android/charts"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                return None
            results = json.loads(response.read().decode("utf-8")).get("results")
    except Exception:                                # noqa: BLE001
        return None
    if not results:
        return "none"
    released = results[0].get("releaseDate") or ""
    if len(released) < 4 or not released[:4].isdigit():
        return "none"
    return released[:4]


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookups", type=int, default=LOOKUPS)
    args = parser.parse_args(argv[1:])

    week = load(WEEK, None)
    if not week or not week.get("tracks"):
        print(f"{WEEK} has nothing in it yet; the live pass has to run first")
        return 1

    tracks = week["tracks"]
    stations = week.get("stations", {})
    years = load(YEARS, {})
    print(f"{len(tracks)} distinct tracks this week, "
          f"{sum(t['plays'] for t in tracks.values())} plays, "
          f"{len(stations)} stations")
    print(f"{len(years)} release years already known\n")

    # ---- fill in some years, within the budget ----

    wanted = [k for k, t in sorted(tracks.items(), key=lambda kv: -kv[1]["plays"])
              if k not in years and t["plays"] >= MIN_PLAYS_FOR_LOOKUP]
    asked = learned = 0
    for key in wanted[:max(args.lookups, 0)]:
        track = tracks[key]
        answer = year_of(track["artist"], track["title"])
        asked += 1
        time.sleep(PAUSE)
        if answer is None:
            continue                                 # transient; ask again later
        years[key] = answer
        if answer != "none":
            learned += 1
    if asked:
        print(f"asked iTunes about {asked} tracks, dated {learned}")
        pathlib.Path(YEARS).write_text(
            json.dumps(years, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8")
    print(f"{len(wanted) - asked} still undated; the next run takes more\n")

    # ---- the chart ----
    #
    # Measured before shipping this, on the first week this ever ran: of the
    # ten highest-play "tracks", not one was a song. "Now Playing info goes
    # here" -- a station's own unfilled template. "Asculti Focus FM" -- a
    # station announcing itself. A Quran reading, a phone-in show's episode
    # title, a DJ's set name. All thirteen minutes-of-airtime real, none of
    # them a track a chart should claim is popular.
    #
    # The dated ones looked completely different: Jackson 5, Aretha Franklin,
    # a Sgambati piano suite. iTunes either recognises a real recording or it
    # does not, and "does not" turned out to correlate almost perfectly with
    # "this was never a song" -- far better than any keyword list this file
    # could maintain. So the chart only ranks what iTunes confirmed, the same
    # bar the eras below already cleared without anyone deciding to apply it
    # here too.
    dated_tracks = {k: t for k, t in tracks.items()
                     if years.get(k, "none") != "none"}
    ordered = sorted(dated_tracks.items(),
                     key=lambda kv: (-kv[1]["plays"], -len(kv[1]["stations"])))
    top_tracks = []
    for key, track in ordered[:TOP_TRACKS]:
        top_tracks.append({
            "artist": track["artist"],
            "title": track["title"],
            "plays": track["plays"],
            "stations": len(track["stations"]),
            "year": years[key],
        })
    print(f"{len(dated_tracks)} of {len(tracks)} tracks confirmed by iTunes; "
          f"the chart only ranks those")

    artists = Counter()
    for track in tracks.values():
        if track["artist"]:
            artists[track["artist"]] += track["plays"]
    top_artists = [{"artist": a, "plays": n} for a, n in
                   artists.most_common(TOP_ARTISTS)]

    # New: first heard in the last two days, and heard enough since to mean it.
    # Same confirmation bar as the main chart -- an unconfirmed string is not
    # more trustworthy for being recent.
    fresh_after = week["updated"] - 2 * 86400
    rising = sorted(
        ({"artist": t["artist"], "title": t["title"], "plays": t["plays"],
          "stations": len(t["stations"]), "year": years[k]}
         for k, t in dated_tracks.items()
         if t.get("first", 0) >= fresh_after and t["plays"] >= 3),
        key=lambda r: -r["plays"])[:20]

    # ---- the eras ----

    eras = []
    for station_id, fact in stations.items():
        dated = [int(years[k]) for k in fact["tracks"]
                 if years.get(k, "none") != "none"]
        if len(dated) < MIN_DATED:
            continue
        eras.append({
            "id": station_id,
            "station": fact["name"],
            "year": int(statistics.median(dated)),
            "dated": len(dated),
            "plays": fact["plays"],
        })
    eras.sort(key=lambda e: e["year"])

    # ---- stations that play the same records ----
    #
    # Not every shared track is worth the same. A record on forty stations
    # says nothing about any two of them; one on three says they are drawing
    # from the same place. So each shared track is worth the reciprocal of how
    # many stations play it, and the total is divided by the geometric mean of
    # what each station has to offer -- otherwise the station that plays the
    # most is everyone's closest neighbour, which is a fact about its playlist
    # length and not about its music.
    rarity = {k: 1.0 / max(1, len(set(t["stations"]))) for k, t in tracks.items()}
    played = {sid: set(f["tracks"]) for sid, f in stations.items()}
    mass = {sid: sum(rarity.get(k, 0.0) for k in ks) for sid, ks in played.items()}

    # The first run of this put "Dance UK Radio danceradiouk aac+" at the top
    # of "Dance UK Radio danceradiouk", on ten shared tracks. Correct, and
    # useless: the catalogue carries bitrate variants as separate stations, and
    # the same station again is the one recommendation nobody needs.
    def same_station(a, b):
        squash = lambda s: "".join(c for c in s.lower() if c.isalnum())
        one, two = squash(stations[a]["name"]), squash(stations[b]["name"])
        if not one or not two:
            return False
        return one in two or two in one

    similar = {}
    for station_id, mine in played.items():
        if len(mine) < MIN_TRACKS_FOR_SIMILAR or mass[station_id] <= 0:
            continue
        scored = []
        for other, theirs in played.items():
            if other == station_id or mass[other] <= 0:
                continue
            if same_station(station_id, other):
                continue
            shared = mine & theirs
            if len(shared) < MIN_SHARED_TRACKS:
                continue
            score = sum(rarity[k] for k in shared) / math.sqrt(
                mass[station_id] * mass[other])
            scored.append((score, len(shared), other))
        if not scored:
            continue
        scored.sort(reverse=True)
        similar[station_id] = [
            {"id": other, "station": stations[other]["name"], "shared": shared}
            for _, shared, other in scored[:SIMILAR_PER_STATION]
        ]

    # ---- who is being found this week ----

    climbing = []
    for station_id, watched in (week.get("listeners") or {}).items():
        span = watched.get("last_at", 0) - watched.get("first_at", 0)
        before, now_listening = watched.get("first", 0), watched.get("last", 0)
        if span < MIN_TREND_HOURS * 3600 or before < MIN_LISTENERS_BEFORE:
            continue
        if now_listening <= before:
            continue
        climbing.append({
            "id": station_id,
            "station": watched.get("station", ""),
            "listeners": now_listening,
            "gained": now_listening - before,
            "grew": round((now_listening - before) / before, 3),
            "days": round(span / 86400, 1),
        })
    climbing.sort(key=lambda r: -r["grew"])
    climbing = climbing[:CLIMBING]

    charts = {
        "at": int(time.time()),
        "days": week.get("days", 8),
        "observed": sum(t["plays"] for t in tracks.values()),
        "tracks": top_tracks,
        "artists": top_artists,
        "new": rising,
        "eras": eras[:TOP_STATIONS],
        "eras_newest": list(reversed(eras[-TOP_STATIONS:])),
        "similar": similar,
        "climbing": climbing,
    }
    text = json.dumps(charts, ensure_ascii=False, separators=(",", ":")) + "\n"
    pathlib.Path(OUT).write_text(text, encoding="utf-8")

    print(f"{OUT}: {len(text) / 1024:.1f} KB")
    print(f"  {len(top_tracks):4d}  chart entries")
    print(f"  {len(top_artists):4d}  artists")
    print(f"  {len(rising):4d}  new this week")
    print(f"  {len(eras):4d}  stations with a datable era")
    print(f"  {len(similar):4d}  stations with a neighbour that plays the same records")
    print(f"  {len(climbing):4d}  stations gaining listeners over days\n")

    if top_tracks:
        print("most played this week:")
        for i, row in enumerate(top_tracks[:10], 1):
            year = f" ({row['year']})" if "year" in row else ""
            print(f"  {i:2d}. {row['artist'][:22]:24} {row['title'][:26]:28}"
                  f" {row['plays']:4d} plays on {row['stations']}{year}")
    if eras:
        print("\noldest music:")
        for row in eras[:5]:
            print(f"  {row['year']}  {row['station'][:38]:40} "
                  f"({row['dated']} dated)")
        print("newest music:")
        for row in reversed(eras[-5:]):
            print(f"  {row['year']}  {row['station'][:38]:40} "
                  f"({row['dated']} dated)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
