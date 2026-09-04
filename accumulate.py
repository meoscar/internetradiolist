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
COUNTS = "counts.json"

KEEP_DAYS = 8
SECONDS_PER_DAY = 86400

# What the tail costs, measured rather than feared. The first real pass wrote
# 321 bytes per track, and the pass runs ninety-six times a day over about a
# hundred and sixty-five stations, which is roughly sixteen thousand
# observations a day. Left unbounded that is eighteen megabytes by day eight,
# force-pushed ninety-six times a day: about 1.7 GB of pushes daily to carry a
# file whose useful part is the top forty rows.
#
# Nearly all of that is tracks heard once and never again, which cannot appear
# in a chart however long they are kept. So the tail is dropped on a sliding
# scale: heard once and not heard again for a day, or twice and not for three
# days, and it goes. Anything genuinely popular is heard every few hours and
# never comes close to these.
ONCE_AFTER_DAYS = 1
TWICE_AFTER_DAYS = 3

# A last defence if a day is unusually varied. The chart needs forty rows; this
# is three orders of magnitude more than that.
MAX_TRACKS = 20000

# A station's era is the median year of what it plays, and a median over a few
# hundred samples is the same number as a median over thousands. Keeping every
# key a station has ever played is the second-largest thing in this file.
MAX_TRACKS_PER_STATION = 400

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

    # A rolling week, and a tail that is dropped sooner the less it was heard.
    week_ago = now - KEEP_DAYS * SECONDS_PER_DAY
    once_ago = now - ONCE_AFTER_DAYS * SECONDS_PER_DAY
    twice_ago = now - TWICE_AFTER_DAYS * SECONDS_PER_DAY

    def spent(entry):
        last = entry.get("last", 0)
        if last < week_ago:
            return True
        if entry["plays"] <= 1 and last < once_ago:
            return True
        return entry["plays"] <= 2 and last < twice_ago

    stale = [k for k, v in tracks.items() if spent(v)]
    for key in stale:
        del tracks[key]

    # And a ceiling, in case a day is unusually varied. Most played wins.
    capped = 0
    if len(tracks) > MAX_TRACKS:
        keep = sorted(tracks.items(), key=lambda kv: -kv[1]["plays"])[:MAX_TRACKS]
        capped = len(tracks) - len(keep)
        tracks = dict(keep)

    if stale or capped:
        alive = set(tracks)
        for fact in stations.values():
            fact["tracks"] = [k for k in fact["tracks"] if k in alive]

    # A median over four hundred records is the same number as a median over
    # four thousand, and this list is the second largest thing in the file.
    trimmed = 0
    for fact in stations.values():
        if len(fact["tracks"]) > MAX_TRACKS_PER_STATION:
            trimmed += len(fact["tracks"]) - MAX_TRACKS_PER_STATION
            fact["tracks"] = fact["tracks"][-MAX_TRACKS_PER_STATION:]

    # ---- how many people are listening, over time ----
    #
    # live.json can only ever say "gaining since the last pass", because the
    # counts it compares against are thrown away every quarter of an hour. The
    # interesting question is the slower one -- which stations are being found
    # this week -- and answering it costs one number per station per pass, kept
    # as a first and a latest rather than as a series, because the shape of the
    # curve between them is not what anybody is asking.
    counts = load(COUNTS, {})
    audience = week.get("listeners", {})
    heard_at = int(counts.get("at") or now)
    for station_id, seen in (counts.get("counts") or {}).items():
        listeners = seen.get("n")
        if not isinstance(listeners, int) or listeners < 0:
            continue
        known = audience.get(station_id)
        if known is None:
            audience[station_id] = {
                "station": seen.get("station", ""),
                "first": listeners, "first_at": heard_at,
                "last": listeners, "last_at": heard_at,
                "peak": listeners,
            }
            continue
        known["station"] = seen.get("station") or known.get("station", "")
        known["last"] = listeners
        known["last_at"] = heard_at
        known["peak"] = max(known.get("peak", listeners), listeners)

    # A station that has not been seen in a week is not trending; it is gone.
    forgotten = [k for k, v in audience.items()
                 if v.get("last_at", 0) < week_ago]
    for key in forgotten:
        del audience[key]

    week = {"updated": now, "days": KEEP_DAYS,
            "tracks": tracks, "stations": stations, "listeners": audience}
    text = json.dumps(week, ensure_ascii=False, separators=(",", ":")) + "\n"
    pathlib.Path(WEEK).write_text(text, encoding="utf-8")

    total = sum(v["plays"] for v in tracks.values())
    print(f"folded in {seen} of {len(live['playing'])} "
          f"({skipped} were not tracks)")
    print(f"  {added:6d}  heard for the first time")
    print(f"  {len(stale):6d}  dropped as tail or older than {KEEP_DAYS} days")
    if capped:
        print(f"  {capped:6d}  over the {MAX_TRACKS} ceiling, least played")
    if trimmed:
        print(f"  {trimmed:6d}  station samples over {MAX_TRACKS_PER_STATION}")
    print(f"  {len(tracks):6d}  distinct tracks, {total} plays")
    print(f"  {len(stations):6d}  stations")
    print(f"  {len(audience):6d}  stations with a listener count being tracked"
          f" ({len(forgotten)} dropped)")
    print(f"  {len(text) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
