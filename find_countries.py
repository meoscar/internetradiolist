#!/usr/bin/env python3
"""Which country each station broadcasts from.

The catalogue has never known. The crawl's listing rows carry a name, a genre,
a bitrate and a listener count, and nothing about where the station is, so a map
of what the world is listening to could not be drawn. Guessing from the domain
gets a quarter of them: 690 of 2721, and three quarters of the pins missing
looks like a broken feature rather than a partial one.

Radio Browser is a community-run directory of about fifty thousand stations
with a free API, no key, and a country code on every row. Matching our stations
against it costs one request: the whole list comes down in a single file and
everything after that is a dictionary lookup, which is both faster than asking
about stations one at a time and much kinder to a volunteer-run service.

Two ways to match, in this order:

  The stream URL, normalised. An exact match on where the audio comes from is
  the same station, whatever either directory calls it.

  The name. Weaker, because two stations can share one, so this only counts
  when exactly one Radio Browser row has that name.

  python3 find_countries.py            match and report
  python3 find_countries.py --apply    write countries.json
"""
import json
import pathlib
import sys
import unicodedata
import urllib.request
from collections import Counter
from urllib.parse import urlparse

# Their docs ask bulk users to take the whole list once rather than query per
# station, and to say who is calling.
SERVERS = (
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
)

# The whole list does not come in one response. Asking for /json/stations plain
# returns a thousand rows and no indication that there are forty-eight thousand
# more, which is the kind of limit that looks like an answer.
PAGE = 25000
UA = "WorldRadio-Android/catalogue (https://github.com/meoscar/internetradiolist)"
TIMEOUT = 120

CATALOGUE = "music_worldradio.json"
OUT = "countries.json"


def items_of(doc):
    if isinstance(doc, list):
        return doc
    for key in ("music", "stations", "items", "data"):
        if isinstance(doc.get(key), list):
            return doc[key]
    return []


def stream_key(url):
    """Where the audio comes from, with the parts that vary stripped off.

    The same stream is written http and https, with and without a trailing
    slash, with ;stream.nsv or /; on the end, and with the port spelled out or
    left to the scheme. None of that makes it a different station.
    """
    try:
        bits = urlparse((url or "").strip())
    except ValueError:
        return ""
    host = (bits.hostname or "").lower()
    if not host:
        return ""
    port = bits.port
    if port in (80, 443, None):
        port = ""
    path = (bits.path or "").rstrip("/")
    for tail in (";stream.nsv", ";stream.mp3", ";"):
        if path.endswith(tail):
            path = path[: -len(tail)].rstrip("/")
    return f"{host}:{port}{path}"


def name_key(name):
    flat = unicodedata.normalize("NFKD", (name or "").lower())
    return "".join(c for c in flat if c.isalnum() and not unicodedata.combining(c))


def fetch_page(server, offset):
    url = f"{server}/json/stations?offset={offset}&limit={PAGE}"
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise IOError(f"{url} answered {response.status}")
        return json.loads(response.read().decode("utf-8"))


def fetch_directory():
    last = None
    for server in SERVERS:
        try:
            print(f"reading {server}")
            rows, offset = [], 0
            while True:
                page = fetch_page(server, offset)
                rows.extend(page)
                print(f"  {len(rows)} so far")
                if len(page) < PAGE:
                    return rows
                offset += PAGE
        except Exception as error:                   # noqa: BLE001
            print(f"  {server}: {type(error).__name__}: {error}")
            last = error
    raise SystemExit(f"no Radio Browser server answered ({last})")


def main(argv):
    apply_changes = "--apply" in argv

    catalogue = items_of(json.loads(
        pathlib.Path(CATALOGUE).read_text(encoding="utf-8")))
    print(f"{len(catalogue)} stations in the catalogue\n")

    rows = fetch_directory()
    print(f"{len(rows)} stations in Radio Browser\n")

    by_stream = {}
    by_name = {}
    for row in rows:
        country = (row.get("countrycode") or "").strip().upper()
        if not country or len(country) != 2:
            continue
        fact = {
            "country": country,
            "name": row.get("name", "").strip(),
            "language": (row.get("language") or "").strip(),
        }
        key = stream_key(row.get("url_resolved") or row.get("url") or "")
        if key:
            by_stream.setdefault(key, fact)
        nkey = name_key(row.get("name"))
        if nkey:
            # A name two countries share is not evidence of anything, and gets
            # poisoned to None so it can never be used. Reading .country off
            # that None was this function's own sentinel biting it.
            existing = by_name.get(nkey, "unset")
            if existing == "unset":
                by_name[nkey] = fact
            elif existing is not None and existing["country"] != country:
                by_name[nkey] = None

    found = {}
    by_how = Counter()
    for station in catalogue:
        source = station.get("source") or ""
        hit = by_stream.get(stream_key(source))
        how = "stream"
        if hit is None:
            hit = by_name.get(name_key(station.get("title")))
            how = "name"
        if not hit:
            by_how["no match"] += 1
            continue
        by_how[how] += 1
        found[station["id"]] = hit["country"]

    total = len(catalogue)
    print(f"matched {len(found)} of {total} "
          f"({len(found) * 100 // max(total, 1)}%)")
    for how, count in by_how.most_common():
        print(f"  {count:5d}  by {how}")

    countries = Counter(found.values())
    print(f"\n{len(countries)} countries")
    for code, count in countries.most_common(15):
        print(f"  {code}  {count}")

    if not apply_changes:
        print(f"\nnothing written; run with --apply to write {OUT}")
        return 0

    pathlib.Path(OUT).write_text(
        json.dumps(found, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")
    print(f"\nwrote {OUT}: {len(found)} stations")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
