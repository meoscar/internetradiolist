#!/usr/bin/env python3
"""Could this catalogue be built from Radio Browser instead?

Everything else this repository takes from internet-radio.com is now either
first-hand from the stations or once a week. What is left is the station list
itself -- which stations exist and what their stream URLs are -- and that is a
single point of failure on the thing the app is made of. One markup change,
one Cloudflare rule, one block, and the weekly crawl stops.

Radio Browser is a community-run directory with a public API and, it is said,
a CC0 licence. That "it is said" is why this file exists: nobody here has
measured it. This probe answers the three questions that decide whether a
migration is worth planning, and answers them with numbers rather than with
what somebody remembered:

  1. Is it reachable, and how big is it?
  2. How many of OUR stations are in it?  -- the one that decides everything.
     If half our catalogue is missing, moving to it means deleting half the
     app, and no amount of independence is worth that.
  3. What does a row actually carry?      -- printed as the field names that
     came back, not as the field names anybody expected.

It writes nothing and changes nothing.

  python3 probe_radio_browser.py            the standard pass
  python3 probe_radio_browser.py 20000      stop after this many rows

Run it from Actions. A sandbox with a filtering egress proxy reports zero for
everything, which measures the sandbox and not the directory -- the same trap
probe_now_playing.py carries a warning about, and the reason this was not
simply answered from a laptop.
"""
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

CATALOGUE = "music_worldradio.json"

# Radio Browser asks callers to identify themselves, and rotates DNS across
# volunteer-run mirrors. Named individually rather than through the round
# robin so a failure names the host that failed.
MIRRORS = (
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
)
UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"
TIMEOUT = 30
PAGE = 5_000
DEFAULT_CAP = 60_000

# The fields worth knowing the fill rate of, because the catalogue needs each
# one. Anything the API returns that is not here is printed too -- the point
# is to find out what it carries, not to confirm a guess.
WANTED = ("name", "url", "url_resolved", "homepage", "favicon", "tags",
          "country", "countrycode", "codec", "bitrate", "votes",
          "clickcount", "lastcheckok")


def get(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def working_mirror():
    """The first mirror that answers, and what it says it holds."""
    for base in MIRRORS:
        try:
            started = time.time()
            stats = get(base + "/json/stats")
            took = time.time() - started
            print(f"  {base}  answered in {took:.1f}s")
            return base, stats
        except Exception as failure:
            print(f"  {base}  {type(failure).__name__}: {failure}")
    return None, None


def normalise(url):
    """A stream URL reduced to what two directories could agree on.

    Scheme and a trailing slash are not the station. Case is not either, in
    the host; it can be in the path, and is left alone there because some
    Shoutcast mounts are case-sensitive.
    """
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except Exception:
        return ""
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = (parts.path or "").rstrip("/")
    return f"{host}{port}{path}"


def our_streams():
    doc = json.loads(pathlib.Path(CATALOGUE).read_text(encoding="utf-8"))
    rows = doc if isinstance(doc, list) else doc.get("music", [])
    streams = {}
    for row in rows:
        key = normalise(row.get("source"))
        if key:
            streams.setdefault(key, row.get("title", ""))
    return streams


def download(base, cap):
    """Pages of stations, until the directory runs out or the cap is reached."""
    rows = []
    offset = 0
    while len(rows) < cap:
        url = (f"{base}/json/stations?limit={PAGE}&offset={offset}"
               f"&hidebroken=true")
        try:
            page = get(url)
        except Exception as failure:
            print(f"  page at offset {offset}: "
                  f"{type(failure).__name__}: {failure}")
            break
        if not isinstance(page, list) or not page:
            break
        rows.extend(page)
        offset += len(page)
        print(f"  {len(rows):6d} rows", end="\r", flush=True)
        if len(page) < PAGE:
            break
    print(f"  {len(rows):6d} rows                ")
    return rows


def main(argv):
    cap = int(argv[1]) if len(argv) > 1 else DEFAULT_CAP

    print("Reaching Radio Browser")
    base, stats = working_mirror()
    if base is None:
        print("\nNo mirror answered. If this ran in a sandbox with a "
              "filtering proxy,\nthat is what was measured -- run it from "
              "Actions before concluding anything.")
        return 1

    if isinstance(stats, dict):
        print(f"\nIt says it holds "
              f"{stats.get('stations', '?')} stations, "
              f"{stats.get('countries', '?')} countries, "
              f"{stats.get('tags', '?')} tags")
        print(f"  software version {stats.get('software_version', '?')}, "
              f"status {stats.get('status', '?')}")

    print(f"\nDownloading up to {cap} rows")
    rows = download(base, cap)
    if not rows:
        print("Nothing came back; there is nothing to compare against.")
        return 1

    # ---- what a row carries, as it actually came back ----

    keys = Counter()
    for row in rows:
        if isinstance(row, dict):
            keys.update(row.keys())
    print(f"\nA row carries these fields ({len(keys)} of them):")
    print("  " + ", ".join(sorted(keys)))

    missing = [f for f in WANTED if f not in keys]
    if missing:
        print(f"\n  the catalogue needs these and they are NOT there: "
              f"{', '.join(missing)}")

    print("\nHow often each field the catalogue needs is filled in:")
    total = len(rows)
    for field in WANTED:
        if field not in keys:
            continue
        filled = sum(1 for r in rows
                     if isinstance(r, dict) and str(r.get(field) or "").strip()
                     not in ("", "0", "None"))
        print(f"  {field:14} {filled:6d} / {total}  ({filled * 100 // total:3d}%)")

    # ---- the question that decides it ----

    ours = our_streams()
    theirs = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in ("url_resolved", "url"):
            key = normalise(row.get(field))
            if key:
                theirs.add(key)

    found = [name for key, name in ours.items() if key in theirs]
    share = len(found) * 100 // max(len(ours), 1)
    print(f"\nOur catalogue: {len(ours)} distinct streams")
    print(f"  found in the {total} rows downloaded: {len(found)}  ({share}%)")
    if total >= cap:
        print(f"  -- the download stopped at the cap, so this is a floor, "
              f"not the answer. Re-run with a larger one.")

    absent = [name for key, name in ours.items() if key not in theirs]
    if absent:
        print(f"\n  {len(absent)} of ours were not found. A few of them:")
        for name in absent[:8]:
            print(f"      {name[:60]}")

    print("\nWhat this does not tell you:")
    print("  - the licence. Read it on the site and decide; this probe will")
    print("    not repeat what anybody remembers it to be.")
    print("  - whether their URLs still play. They mark rows broken and we")
    print("    asked for hidebroken=true, but that is their check, not ours;")
    print("    check_stations.py is what would settle it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
