#!/usr/bin/env python3
"""Build the catalogue the app downloads, from the crawl, the probe and the logos.

The published catalogue is a snapshot of 712 stations taken years ago, 44% of
whose streams no longer answer. The crawl has 2721 stations with genres,
listener counts and homepages. This joins them into the shape JsonSource
parses, and it drops anything that did not answer when we asked.

That last part is the point. Shipping 2721 stations because we have 2721 names
would make "half of these don't play" worse, not better, so a station is only
included if station_facts.json records a successful ICY handshake against its
stream. A name without a working stream is not a station.

Nothing that works today is thrown away: a station already in the catalogue
that still answers is carried over even when the crawl never saw it, keeping
the genre it was filed under.

  python3 build_catalogue.py            say what would change
  python3 build_catalogue.py --apply    write music_worldradio.json
"""
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

DIRECTORY = "directory.json"
FACTS = "station_facts.json"
LOGOS = "logos.json"
CATALOGUE = "music_worldradio.json"

# Every row must carry an image, and this is what a station with no logo gets.
#
# Not decoration -- a crash. MediaItemFragmentViewModel reads
# child.description.iconUri!!, and MediaMetadataCompat drops an empty string
# rather than storing it, so a row with "image": "" arrives with a null
# iconUri and the non-null assertion kills the app the moment that category is
# opened. The first build of this catalogue left 1566 rows empty and every
# installed copy, this version and the last, crashed on it.
#
# The app is being fixed too, but a published file reaches phones that will
# never be updated, so this file has to be safe on its own. A neutral mark is
# also the honest answer: it says no logo was found, where the folder of
# image-search results said something false.
PLACEHOLDER = ("https://raw.githubusercontent.com/meoscar/internetradiolist"
               "/main/station_placeholder.png")

# A station carries several genres. Filing it under the rarest makes categories
# of one; filing it under the commonest puts everything in "pop". So take the
# most specific genre that still has enough stations to be worth opening.
MIN_BUCKET = 12

# A station whose every genre is rare lands in a category of its own. Sixty
# folders holding one station each is not a taxonomy, it is scrolling, so
# anything this small is folded into OTHER after the fact.
FOLD_UNDER = 5

# The busiest stations, shown as their own row the way the old catalogue did.
ON_TREND = 20

# Hard-coded in the app in several places -- its own scrape path, its own
# artwork, its own now-playing page. Carried over exactly as it is.
ICRT_ID = "https://www.icrt.com.tw/"


def normalise(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def items_of(doc):
    if isinstance(doc, list):
        return doc
    for key in ("music", "stations", "items", "data"):
        if isinstance(doc.get(key), list):
            return doc[key]
    return []


def load(name, default=None):
    path = pathlib.Path(name)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def row(title, genre, source, image, site, track, station_id):
    """One JsonMusic object, with every field the parser reads."""
    return {
        "id": station_id,
        "title": title,
        "album": genre,
        "artist": "",
        "genre": genre,
        "source": source,
        "image": image,
        "trackNumber": track,
        "totalTrackCount": 0,
        "duration": 0,
        "site": site,
    }


def main(argv):
    apply_changes = "--apply" in argv

    facts = load(FACTS)
    if not facts:
        print(f"{FACTS} is not here; run the ICY harvest first")
        return 1
    directory = load(DIRECTORY, [])
    logos = load(LOGOS, {})
    existing = items_of(load(CATALOGUE, {"music": []}))

    alive = {url for url, fact in facts.items() if fact.get("ok")}
    print(f"{len(facts)} streams probed, {len(alive)} answered\n")

    logo_by_stream = {url: entry["logo"] for url, entry in logos.items()}
    logo_by_name = {}
    for entry in logos.values():
        logo_by_name.setdefault(normalise(entry["name"]), entry["logo"])

    def logo_for(stream, name):
        return logo_by_stream.get(stream) or logo_by_name.get(normalise(name)) or ""

    # ---- what the crawl found, minus everything that did not answer ----

    # The crawl keys its stations by stream URL, but resolve_streams.py rewrites
    # that field afterwards, and two different .pls URLs can resolve to the same
    # stream. Three stations were listed twice because of it.
    crawled, crawled_seen = [], set()
    for station in directory:
        if station["stream"] in alive and station["stream"] not in crawled_seen:
            crawled_seen.add(station["stream"])
            crawled.append(station)
    unmeasured = [s for s in directory if s["stream"] not in facts]
    print(f"{DIRECTORY}: {len(directory)} stations")
    print(f"  {len(crawled):5d}  answered when probed")
    print(f"  {len(directory) - len(crawled) - len(unmeasured):5d}  did not answer, dropped")
    print(f"  {len(unmeasured):5d}  never probed, dropped\n")
    if unmeasured:
        print("  (a station nobody has probed is not evidence of a working stream;")
        print("   run the ICY harvest over directory.json to include these)\n")

    # Genre buckets, counted over the stations that survived rather than over
    # the whole crawl, so the sizes are the sizes the listener will see.
    counts = Counter(g for s in crawled for g in s.get("genres", []))

    def genre_for(station):
        options = [g for g in station.get("genres", []) if g]
        if not options:
            return "OTHER"
        specific = sorted(options, key=lambda g: counts[g])
        for slug in specific:
            if counts[slug] >= MIN_BUCKET:
                return slug.upper()
        return max(options, key=lambda g: counts[g]).upper()

    by_genre = defaultdict(list)
    for station in crawled:
        by_genre[genre_for(station)].append(station)

    # ---- stations already published that still work and the crawl missed ----

    seen = {s["stream"] for s in crawled}
    carried = []
    for item in existing:
        source = (item.get("source") or "").strip()
        if not source or source in seen or item.get("id") == ICRT_ID:
            continue
        if source not in alive:
            continue
        carried.append(item)
        seen.add(source)
    print(f"{CATALOGUE}: {len(existing)} stations")
    print(f"  {len(carried):5d}  still answer and the crawl missed them, kept\n")

    for item in carried:
        by_genre[(item.get("genre") or "OTHER").upper()].append({
            "name": item.get("title", ""),
            "stream": item["source"],
            "page": item.get("site", ""),
            "listeners": 0,
            "_image": item.get("image", ""),
        })

    # Fold away the categories too small to be worth opening. This runs after
    # the carried-over stations have been added, so it judges the buckets the
    # listener will actually see rather than the crawl's own counts.
    folded = 0
    for genre in [g for g, rows in by_genre.items() if len(rows) < FOLD_UNDER]:
        folded += len(by_genre[genre])
        by_genre["OTHER"] += by_genre.pop(genre)
    if folded:
        print(f"{folded} stations folded into OTHER from categories "
              f"under {FOLD_UNDER}\n")

    # ---- assemble ----

    music = []

    icrt = next((i for i in existing if i.get("id") == ICRT_ID), None)
    if icrt:
        music.append(icrt)
        print("ICRT carried over unchanged\n")

    for genre in sorted(by_genre):
        stations = sorted(by_genre[genre],
                          key=lambda s: -(s.get("listeners") or 0))
        for track, station in enumerate(stations, 1):
            name = station["name"]
            # Only a picture the station published counts. What is left of the
            # old field came from an image search on the station's name and is
            # as likely to show something else, so the fallback is the neutral
            # mark rather than that folder.
            image = logo_for(station["stream"], name) or PLACEHOLDER
            music.append(row(
                title=name,
                genre=genre,
                source=station["stream"],
                image=image,
                site=station.get("page") or "",
                track=track,
                station_id=station["stream"],
            ))

    # The busiest stations, listed again under their own heading. The old
    # catalogue had this section and the browse tree still excludes these ids
    # from Recommended, so the prefix has to stay exactly as it was.
    trending = sorted(crawled, key=lambda s: -(s.get("listeners") or 0))[:ON_TREND]
    for track, station in enumerate(trending, 1):
        music.append(row(
            title=station["name"],
            genre="On Trend",
            source=station["stream"],
            image=logo_for(station["stream"], station["name"]) or PLACEHOLDER,
            site=station.get("page") or "",
            track=track,
            station_id=f"ontrendstations_{station['name']}",
        ))

    # ---- report ----

    with_image = sum(1 for r in music if r["image"] and r["image"] != PLACEHOLDER)
    empty = sum(1 for r in music if not r["image"])
    with_site = sum(1 for r in music if r["site"])
    genres = Counter(r["genre"] for r in music)
    text = json.dumps({"music": music}, ensure_ascii=False,
                      separators=(",", ":")) + "\n"

    print(f"new catalogue: {len(music)} rows "
          f"(was {len(existing)}), {len(text) / 1024:.0f} KB")
    print(f"  {with_image:5d}  have a logo the station published "
          f"({with_image * 100 // max(len(music), 1)}%)")
    print(f"  {len(music) - with_image:5d}  show the neutral placeholder")
    print(f"  {empty:5d}  have no image at all (must be 0; a blank crashes "
          f"the app)")
    print(f"  {with_site:5d}  have a now-playing page for the backup scrape")
    print(f"  {len(genres):5d}  categories")
    print("\nbiggest categories:")
    for genre, count in genres.most_common(12):
        print(f"  {count:5d}  {genre}")
    smallest = [g for g, c in genres.items() if c < MIN_BUCKET and g != "On Trend"]
    if smallest:
        print(f"\n{len(smallest)} categories under {MIN_BUCKET} stations: "
              f"{', '.join(sorted(smallest)[:8])}")

    if empty:
        print(f"\nREFUSING to write: {empty} rows have no image, and the app "
              f"asserts iconUri is non-null")
        return 1

    if apply_changes:
        pathlib.Path(CATALOGUE).write_text(text, encoding="utf-8")
        print(f"\nwritten to {CATALOGUE}")
    else:
        print(f"\nnothing written -- run with --apply to replace {CATALOGUE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
