#!/usr/bin/env python3
"""Take each station's logo from the station, and make it a thumbnail.

The pictures in stationPics0719 came from scraping an image search for the
station's name years ago, which is why so many of them show something else
entirely. They also average 125KB for something drawn at about 50 pixels: 746
files, 93MB, and a listener scrolling the list downloads megabytes of it.

Broadcasters publish their own branding on their own site, in three places a
browser already knows to look:

    <meta property="og:image">        the image they chose for sharing
    <link rel="apple-touch-icon">     usually a clean square mark
    <link rel="icon">                 the favicon

That is the logo the station picked, not a search result that mentioned its
name. The crawl has a homepage for 922 of them.

Each one found is fetched, decoded to prove it is an image, squared, resized to
256 and written as WebP -- about 10KB rather than 125KB. Stations without a
usable logo get no entry and keep whatever they have; a blank is better than
another wrong picture.

  python3 harvest_logos.py --limit 40      a sample, to look at
  python3 harvest_logos.py                 everything with a homepage
"""
import argparse
import html
import io
import json
import pathlib
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from PIL import Image

DIRECTORY = "directory.json"
LOGO_INDEX = "logos.json"
FACTS = "station_facts.json"
OUT_DIR = pathlib.Path("logos")
SIZE = 256
TIMEOUT = 20
WORKERS = 12
MAX_IMAGE_BYTES = 8 * 1024 * 1024

UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"

# Hosts that are a platform, a placeholder, or nothing at all -- never the
# station whose mark we are after. A station whose icy-url reads shoutcast.com
# would be handed the SHOUTcast logo, and dozens of stations sharing one
# picture is the exact complaint the scraped folder was thrown out for.
NOT_A_STATION_SITE = (
    "shoutcast.com", "localhost", "127.0.0.1", "example.com",
    "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "radio.co", "live365.com", "zeno.fm", "laut.fm",
    "mixlr.com", "streema.com", "tunein.com", "mytuner-radio.com",
)


def station_site(url):
    """A URL worth asking for a logo, or None.

    The directory lists a homepage for only some stations. The ones it does
    not, the stream itself often names: icy-url is a field the broadcaster
    fills in, and station_facts.json has already collected it for every
    station that answered a handshake. It is a much rougher field than the
    directory's -- half of it is a platform's front page, a Facebook group,
    "http://www." or literally localhost -- so it is worth exactly as much as
    what is filtered out of it.
    """
    site = (url or "").strip()
    if not site:
        return None
    if not site.startswith(("http://", "https://")):
        site = "http://" + site
    try:
        host = (urlparse(site).hostname or "").lower()
    except ValueError:
        return None
    if not host or "." not in host.strip("."):
        return None
    if any(host == bad or host.endswith("." + bad) for bad in NOT_A_STATION_SITE):
        return None
    return site

OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
OG_IMAGE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)
LINK_ICON = re.compile(
    r'<link[^>]+rel=["\']([^"\']*icon[^"\']*)["\'][^>]*>', re.I)
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
SIZES = re.compile(r'sizes=["\'](\d+)x\d+["\']', re.I)


def fetch(url, limit=MAX_IMAGE_BYTES):
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Language": "en"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read(limit)


def logo_candidates(page, base):
    """Every logo the page offers, best first."""
    found = []

    for pattern in (OG_IMAGE, OG_IMAGE_REVERSED):
        match = pattern.search(page)
        if match:
            found.append(urljoin(base, html.unescape(match.group(1))))
            break

    # An apple-touch-icon is meant to be a square app-sized mark, which is
    # exactly the shape wanted here. Prefer the largest declared.
    icons = []
    for tag in LINK_ICON.finditer(page):
        whole = tag.group(0)
        href = HREF.search(whole)
        if not href:
            continue
        size = SIZES.search(whole)
        weight = int(size.group(1)) if size else (
            180 if "apple" in tag.group(1).lower() else 32)
        icons.append((weight, urljoin(base, html.unescape(href.group(1)))))
    found += [url for _, url in sorted(icons, key=lambda pair: -pair[0])]

    # Every site has this whether it advertises it or not.
    parts = urlparse(base)
    found.append(f"{parts.scheme}://{parts.netloc}/favicon.ico")

    seen, ordered = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def square(image):
    """Centre-crop to a square, then resize. Logos are usually square already."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side)).resize(
        (SIZE, SIZE), Image.LANCZOS)


def harvest(station):
    """(slug, note). slug is None when nothing usable was found."""
    homepage = station.get("homepage") or ""
    if not homepage.startswith("http"):
        return None, "no homepage"

    slug = re.sub(r"[^a-z0-9]", "", station["name"].lower())[:60]
    if not slug:
        return None, "no usable name"

    try:
        page = fetch(homepage, 512 * 1024).decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return None, f"homepage: {type(exc).__name__}"

    # Why each candidate was turned down, so the tally at the end of a run can
    # say which. "No usable image" covered four different situations, and they
    # call for four different answers: a site with nothing to take, a site whose
    # only mark is a 32-pixel favicon, an image that will not decode, and a
    # blank spacer. Counting them together is why nobody could tell whether the
    # 48-pixel floor was the binding constraint.
    tried = 0
    too_small = 0
    unreadable = 0
    blank = 0

    for candidate in logo_candidates(page, homepage):
        tried += 1
        try:
            raw = fetch(candidate)
            image = Image.open(io.BytesIO(raw))
            image.load()
        except Exception:                          # noqa: BLE001
            unreadable += 1
            continue

        # A 16x16 favicon upscaled to 256 is a smear. Below 48 is not a logo,
        # and the generated initials mark the app draws instead is at least
        # sharp -- which is the comparison that matters, not blank against
        # something.
        if min(image.size) < 48:
            too_small += 1
            continue

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.mode else "RGB")

        # Encode first and look at the result. The 48-pixel floor above rejects
        # an image that is too small to be a logo, but not one that is large and
        # blank -- a 512x512 transparent spacer passes it, and the first run
        # produced a 200-byte file that way. WebP of a flat colour is tiny; a
        # logo is not.
        buffer = io.BytesIO()
        square(image).save(buffer, "WEBP", quality=82, method=6)
        if buffer.tell() < 1024:
            blank += 1
            continue

        OUT_DIR.mkdir(exist_ok=True)
        (OUT_DIR / f"{slug}.webp").write_bytes(buffer.getvalue())
        return slug, candidate

    if tried == 0:
        return None, "page names no image at all"
    if too_small and too_small >= max(unreadable, blank):
        return None, "only images under 48px"
    if unreadable >= max(too_small, blank):
        return None, "images would not decode"
    return None, "images were blank"


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument(
        "--missing", action="store_true",
        help="only stations that have no logo yet")
    args = parser.parse_args(argv[1:])

    path = pathlib.Path(DIRECTORY)
    if not path.exists():
        print(f"{DIRECTORY} is not here; run the crawl first")
        return 1

    stations = json.loads(path.read_text(encoding="utf-8"))

    # Two sources, in order of how much they can be trusted. The directory's
    # homepage field is the station's own site as the listing has it. For the
    # stations it has no homepage for -- 641 of the ones still without a logo,
    # measured -- the stream headers often carry one the broadcaster typed in
    # themselves, which is rougher and has to be filtered, but is the only
    # thing standing between those stations and no picture at all.
    facts = {}
    facts_path = pathlib.Path(FACTS)
    if facts_path.exists():
        facts = json.loads(facts_path.read_text(encoding="utf-8"))

    with_home, from_stream = [], []
    for station in stations:
        listed = (station.get("homepage") or "").strip()
        if listed.startswith("http"):
            with_home.append(station)
            continue
        said = station_site((facts.get(station.get("stream", "")) or {}).get("icy-url"))
        if said:
            from_stream.append({**station, "homepage": said})

    print(f"{len(with_home)} of {len(stations)} stations publish a homepage; "
          f"{len(from_stream)} more name a site in their stream headers")

    with_home += from_stream

    # The weekly run asks every station on purpose: a broadcaster who changes
    # their logo is only found by asking again. But a run meant to close the
    # gap, or to measure why it is not closing, should ask the stations that
    # have nothing -- and with --limit alone it spends its whole budget
    # re-fetching the front of the list, which is exactly the part that already
    # worked. A 200-station sample taken that way returned 123 logos and
    # changed four files.
    if args.missing:
        known = {}
        index_path = pathlib.Path(LOGO_INDEX)
        if index_path.exists():
            known = json.loads(index_path.read_text(encoding="utf-8"))
        before = len(with_home)
        with_home = [s for s in with_home if s.get("stream") not in known]
        print(f"{len(with_home)} of those {before} have no logo yet")

    if args.limit:
        with_home = with_home[:args.limit]
    started = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(harvest, with_home))

    # Written to its own file rather than back into directory.json. Two
    # workflows editing the same file is a merge conflict waiting for the first
    # time they overlap, and the first time was this one -- the crawl finished
    # while this was running and the logos never got pushed. A station's logo
    # keyed by its stream URL composes with the directory instead of racing it.
    index_file = pathlib.Path(LOGO_INDEX)
    index = {}
    if index_file.exists():
        index = json.loads(index_file.read_text(encoding="utf-8"))

    got, reasons = 0, {}
    for station, (slug, note) in zip(with_home, results):
        if slug:
            index[station["stream"]] = {
                "name": station["name"],
                "logo": ("https://raw.githubusercontent.com/meoscar/"
                         f"internetradiolist/main/logos/{slug}.webp"),
                "from": note,
            }
            station["logo"] = index[station["stream"]]["logo"]
            got += 1
        else:
            reasons[note] = reasons.get(note, 0) + 1

    index_file.write_text(
        json.dumps(index, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"\n{got} logos in {time.time() - started:.0f}s")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {reason}")

    if OUT_DIR.exists():
        sizes = [f.stat().st_size for f in OUT_DIR.glob("*.webp")]
        if sizes:
            print(f"\n{len(sizes)} files, {sum(sizes) / 1024:.0f} KB total, "
                  f"{sum(sizes) // len(sizes) / 1024:.1f} KB each on average")
            print("stationPics0719 for comparison: 746 files, 93 MB, 125 KB each")

    print(f"\n{LOGO_INDEX}: {len(index)} stations have a logo")
    print("\nwhere the first few came from:")
    for entry in list(index.values())[:8]:
        print(f"  {entry['name'][:34]:34} {entry['from'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
