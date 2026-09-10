#!/usr/bin/env python3
"""Find a logo for the stations the harvest found nothing for.

harvest_logos.py asks each station's own site, and after a season of weekly
runs 1,249 of the directory's 2,738 stations still have no logo: 184 name no
site at all, and the rest have a site that offers nothing usable -- an SVG,
a 16-pixel favicon, a page where an image should be. The app draws a mark
for those, two letters on a colour, which is honest and the same for half
the list.

Two more places know a station's mark, and both are free to ask:

  Radio Browser     a community directory, CC0, 58,000 stations. A third of
                    ours are in it by name, an eighth by stream URL. Its rows
                    carry a favicon and a homepage, and the homepage is worth
                    as much as the favicon: it feeds the same harvest as the
                    directory's own homepages, for stations that had none.

  Icon services     Google's and DuckDuckGo's favicon caches already hold a
                    rendered, sized icon for most sites -- including sites
                    whose own icon is an SVG, or whose markup this harvester
                    could not read. Asked by hostname; nothing of ours goes
                    with the request but the station's public site.

Each picture found goes through the same gate as the harvest: decodes, at
least 48 pixels, squared to 256, WebP, not blank. Matching Radio Browser by
name is only trusted when the name is unique there and the two directories
agree on the station's site, or ours has none to disagree with: two stations
called "Best 50s Radio" must not swap logos.

  python3 find_logos.py --limit 40      a sample
  python3 find_logos.py                 every station still without a logo
"""
import argparse
import io
import json
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

from PIL import Image

import harvest_logos as harvest
import probe_radio_browser as radio_browser

DIRECTORY = "directory.json"
LOGO_INDEX = "logos.json"
FACTS = "station_facts.json"
OUT_DIR = pathlib.Path("logos")
WORKERS = 8
MIN_SIDE = 48

GOOGLE = "https://www.google.com/s2/favicons?domain={host}&sz=256"
DUCK = "https://icons.duckduckgo.com/ip3/{host}.ico"


def slug_of(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())[:60]


def host_of(url):
    try:
        return (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def keep(raw, slug):
    """Write raw as the station's logo if it passes the gate; the reason if not."""
    try:
        image = harvest.open_image(raw)
    except Exception:                              # noqa: BLE001
        return None, "not an image"
    if min(image.size) < MIN_SIDE:
        return None, f"under {MIN_SIDE}px"
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    buffer = io.BytesIO()
    harvest.square(image).save(buffer, "WEBP", quality=82, method=6)
    if buffer.tell() < 1024:
        return None, "blank"
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{slug}.webp").write_bytes(buffer.getvalue())
    return slug, None


class Finder:
    def __init__(self, rb_by_url, rb_by_name, facts):
        self.rb_by_url = rb_by_url
        self.rb_by_name = rb_by_name
        self.facts = facts
        # Google answers a site it knows nothing about with one globe for
        # all of them. Fetched once, so it can be recognised and refused.
        self.globe = b""
        try:
            self.globe = harvest.fetch(GOOGLE.format(host="nothing-here.invalid"))
        except Exception:                          # noqa: BLE001
            pass

    def radio_browser_row(self, station):
        row = self.rb_by_url.get(radio_browser.normalise(station.get("stream")))
        if row:
            return row, "by stream"
        same_name = self.rb_by_name.get(radio_browser.bare_name(station.get("name")))
        if not same_name or len(same_name) != 1:
            return None, None
        row = same_name[0]
        ours = host_of(station.get("homepage"))
        theirs = host_of(row.get("homepage"))
        if ours and theirs and ours != theirs:
            return None, None
        return row, "by name"

    def sites(self, station, rb_row):
        """Every site we know for the station, best first, deduplicated."""
        found = []
        listed = (station.get("homepage") or "").strip()
        if listed.startswith("http"):
            found.append(listed)
        said = harvest.station_site(
            (self.facts.get(station.get("stream", "")) or {}).get("icy-url"))
        if said:
            found.append(said)
        if rb_row:
            theirs = harvest.station_site(rb_row.get("homepage"))
            if theirs:
                found.append(theirs)
        seen, ordered = set(), []
        for site in found:
            key = host_of(site)
            if key and key not in seen:
                seen.add(key)
                ordered.append(site)
        return ordered

    def find(self, station):
        """(slug, where it came from) or (None, why not)."""
        slug = slug_of(station.get("name"))
        if not slug:
            return None, "no usable name"
        reasons = []

        rb_row, how = self.radio_browser_row(station)

        # 1. Radio Browser's favicon for the station.
        favicon = (rb_row or {}).get("favicon") or ""
        if favicon.startswith("http"):
            try:
                kept, why = keep(harvest.fetch(favicon), slug)
            except Exception as exc:               # noqa: BLE001
                kept, why = None, type(exc).__name__
            if kept:
                return kept, f"radio-browser favicon ({how}): {favicon}"
            reasons.append(f"radio-browser favicon {why}")

        sites = self.sites(station, rb_row)
        if not sites:
            return None, "no site known anywhere"

        # 2. A site the directory did not have, asked the harvest's own way.
        for site in sites:
            if site == (station.get("homepage") or "").strip():
                continue
            found, note = harvest.harvest({**station, "homepage": site})
            if found:
                return found, f"site from {'radio-browser' if rb_row and site == harvest.station_site(rb_row.get('homepage')) else 'stream headers'}: {note}"
            reasons.append(f"{host_of(site)}: {note}")

        # 3. The icon caches, by hostname.
        for site in sites:
            host = host_of(site)
            for name, pattern in (("google", GOOGLE), ("duckduckgo", DUCK)):
                try:
                    raw = harvest.fetch(pattern.format(host=quote(host)))
                except Exception as exc:           # noqa: BLE001
                    reasons.append(f"{name} {type(exc).__name__}")
                    continue
                if name == "google" and self.globe and raw == self.globe:
                    reasons.append("google: unknown site")
                    continue
                kept, why = keep(raw, slug)
                if kept:
                    return kept, f"{name} icon service for {host}"
                reasons.append(f"{name} {why}")

        return None, "; ".join(reasons[:3]) if reasons else "nothing anywhere"


def radio_browser_index():
    print("Radio Browser:")
    base, stats = radio_browser.working_mirror()
    if not base:
        print("  unreachable; going on without it")
        return {}, {}
    rows = radio_browser.download(base, radio_browser.DEFAULT_CAP)
    by_url, by_name = {}, {}
    for row in rows:
        for key in (row.get("url"), row.get("url_resolved")):
            key = radio_browser.normalise(key)
            if key:
                by_url.setdefault(key, row)
        name = radio_browser.bare_name(row.get("name"))
        if name:
            by_name.setdefault(name, []).append(row)
    print(f"  {len(rows)} rows, {len(by_url)} stream URLs, {len(by_name)} names\n")
    return by_url, by_name


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    args = parser.parse_args(argv[1:])

    stations = json.loads(pathlib.Path(DIRECTORY).read_text(encoding="utf-8"))
    index_file = pathlib.Path(LOGO_INDEX)
    index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}
    facts_file = pathlib.Path(FACTS)
    facts = json.loads(facts_file.read_text(encoding="utf-8")) if facts_file.exists() else {}

    missing = [s for s in stations if s.get("stream") and s["stream"] not in index]
    print(f"{len(missing)} of {len(stations)} stations have no logo")
    if args.limit:
        missing = missing[:args.limit]

    by_url, by_name = radio_browser_index()
    finder = Finder(by_url, by_name, facts)
    started = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(finder.find, missing))

    got, reasons, sources = 0, {}, {}
    for station, (slug, note) in zip(missing, results):
        if slug:
            index[station["stream"]] = {
                "name": station["name"],
                "logo": ("https://raw.githubusercontent.com/meoscar/"
                         f"internetradiolist/main/logos/{slug}.webp"),
                "from": note,
            }
            got += 1
            source = note.split(":")[0].split(" for ")[0]
            sources[source] = sources.get(source, 0) + 1
        else:
            head = note.split(";")[0].split(":")[0]
            reasons[head] = reasons.get(head, 0) + 1

    index_file.write_text(
        json.dumps(index, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"\n{got} logos found in {time.time() - started:.0f}s")
    for source, count in sorted(sources.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {source}")
    print("\nstill without, by the first reason:")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {count:4d}  {reason}")
    print(f"\n{LOGO_INDEX}: {len(index)} stations have a logo")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
