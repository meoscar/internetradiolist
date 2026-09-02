#!/usr/bin/env python3
"""Rebuild the catalogue from internet-radio.com's own directory.

What this repository holds is a snapshot taken years ago: a name, a stream URL
and a station page, for 712 stations, 44% of whose streams no longer answer.
There is nothing to browse by -- no genre, no country, no popularity -- which is
why the app opens on a list of strangers.

The site keeps all of that current, and its listing pages give it away a row at
a time. One row carries the stream URL, the station name, its page, its own
homepage, its genres, its live listener count and its bitrate. That is the whole
catalogue, and it does not require visiting a single station page.

robots.txt (read 2026-09-02) disallows /cgi-bin/, /playlist.m3u,
/playlist.xspf, /account/, /register/, /start/, /images/icons/,
/stations/iframe/, /community/members/, /community/help/ and /terms/. It permits
/stations/ and /station/, and sets no crawl delay. This stays inside that, waits
between requests, and identifies itself -- the catalogue depends on the site
staying reachable, which matters more than finishing quickly.

  python3 crawl_directory.py --max-requests 40      a look, not a crawl
  python3 crawl_directory.py                        the whole directory
"""
import argparse
import html
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from urllib.parse import urljoin, unquote

BASE = "https://www.internet-radio.com/"
GENRE_INDEX = BASE + "stations/"
OUT = "directory.json"

UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"
PAUSE = 1.2
TIMEOUT = 30

# Paths robots.txt puts out of bounds. Checked rather than remembered.
DISALLOWED = (
    "/cgi-bin/", "/playlist.m3u", "/playlist.xspf", "/account/", "/register/",
    "/start/", "/images/icons/", "/stations/iframe/", "/community/members/",
    "/community/help/", "/terms/",
)

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
STREAM = re.compile(r"playlistgenerator/\?u=(.*?)&amp;t=\.m3u", re.I)
HEADING = re.compile(r'<h4[^>]*>\s*(?:<a\s+href="(/station/[^"]*)"[^>]*>)?(.*?)(?:</a>)?\s*</h4>', re.I | re.S)
NOW_PLAYING = re.compile(r"</h4>\s*(?:<br\s*/?>)?\s*<b>(.*?)</b>", re.I | re.S)
HOMEPAGE = re.compile(r'<a\s+class="small text-success"\s+href="([^"]+)"', re.I)
GENRES = re.compile(r"Genres:(.*?)</td>", re.I | re.S)
LISTENERS = re.compile(r"([\d,]+)\s*Listeners", re.I)
BITRATE = re.compile(r"(\d+)\s*Kbps", re.I)
TAG = re.compile(r"<[^>]+>")


def allowed(url):
    path = url[len(BASE) - 1:] if url.startswith(BASE) else url
    return not any(path.startswith(bad) for bad in DISALLOWED)


class Fetcher:
    """Every request the crawler makes goes through here, so the pause, the
    budget and the robots.txt check cannot be forgotten at a call site."""

    def __init__(self, budget):
        self.budget = budget
        self.made = 0
        self.failed = 0

    def get(self, url):
        if self.made >= self.budget:
            return None
        if not allowed(url):
            print(f"    robots.txt disallows {url}")
            return None

        self.made += 1
        request = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as exc:                   # noqa: BLE001
            self.failed += 1
            print(f"    {url} -> {type(exc).__name__}: {exc}")
            return None
        finally:
            time.sleep(PAUSE)


def text_of(fragment):
    return html.unescape(TAG.sub(" ", fragment)).strip()


def parse_rows(page, genre_hint):
    """A listing row, as the site writes it, turned into a station."""
    found = []
    for chunk in ROW.findall(page):
        stream = STREAM.search(chunk)
        if not stream:
            continue
        url = html.unescape(unquote(stream.group(1))).strip()
        if not url.startswith(("http://", "https://")):
            continue

        heading = HEADING.search(chunk)
        name = text_of(heading.group(2)) if heading else ""
        page_path = heading.group(1) if heading and heading.group(1) else ""
        if not name:
            continue

        station = {
            "name": name,
            "stream": url,
            "genres": [genre_hint],
        }
        if page_path:
            station["page"] = urljoin(BASE, page_path)

        playing = NOW_PLAYING.search(chunk)
        if playing:
            title = text_of(playing.group(1))
            if title:
                station["now_playing"] = title

        home = HOMEPAGE.search(chunk)
        if home:
            station["homepage"] = html.unescape(home.group(1))

        genres = GENRES.search(chunk)
        if genres:
            words = [w for w in text_of(genres.group(1)).split() if w]
            station["genres"] = sorted({g.lower() for g in [genre_hint] + words if g})

        listeners = LISTENERS.search(chunk)
        if listeners:
            station["listeners"] = int(listeners.group(1).replace(",", ""))

        bitrate = BITRATE.search(chunk)
        if bitrate:
            station["bitrate"] = int(bitrate.group(1))

        # A .pls or .m3u is a playlist pointing at the stream, not the stream.
        # ExoPlayer will not play one, so it is flagged here and resolved by
        # whatever turns this file into the catalogue.
        if re.search(r"\.(pls|m3u8?)(\?|$)", url, re.I):
            station["needs_resolving"] = True

        found.append(station)
    return found


def next_page(page, current):
    """The site's own 'next' link, whatever shape it takes -- not a guess."""
    for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
        target = urljoin(current, html.unescape(href))
        if target == current or not target.startswith(current.split("?")[0]):
            continue
        if re.search(r"(page|p)=\d+|/page/\d+|/\d+/$", target):
            return target
    return None


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-requests", type=int, default=1200)
    parser.add_argument("--max-genres", type=int, default=0, help="0 = all")
    parser.add_argument("--pages-per-genre", type=int, default=4)
    args = parser.parse_args(argv[1:])

    fetch = Fetcher(args.max_requests)

    print(f"genre index: {GENRE_INDEX}")
    index = fetch.get(GENRE_INDEX)
    if not index:
        print("could not read the genre index; nothing to do")
        return 1

    genres = []
    for href in re.findall(r'href=["\'](/stations/[^"\']*)["\']', index, re.I):
        slug = href[len("/stations/"):].strip("/")
        if slug and slug not in genres:
            genres.append(slug)
    print(f"{len(genres)} genres listed")
    if args.max_genres:
        genres = genres[:args.max_genres]
        print(f"taking the first {len(genres)}")

    stations = {}
    for position, slug in enumerate(genres, 1):
        url = urljoin(GENRE_INDEX, f"{slug}/")
        for page_number in range(args.pages_per_genre):
            page = fetch.get(url)
            if not page:
                break

            rows = parse_rows(page, slug)
            for station in rows:
                existing = stations.get(station["stream"])
                if existing:
                    existing["genres"] = sorted(set(existing["genres"]) | set(station["genres"]))
                    # Listener counts move; keep the highest seen.
                    if station.get("listeners", 0) > existing.get("listeners", 0):
                        existing["listeners"] = station["listeners"]
                else:
                    stations[station["stream"]] = station

            print(f"  [{position}/{len(genres)}] {slug} p{page_number + 1}: "
                  f"{len(rows)} rows, {len(stations)} stations so far "
                  f"({fetch.made}/{fetch.budget} requests)")

            if page_number == 0 and position == 1:
                # Learn the pagination shape from the site rather than assume it.
                sample = sorted({h for h in re.findall(r'href=["\']([^"\']+)["\']', page, re.I)
                                 if re.search(r"page", h, re.I)})[:10]
                print(f"    pagination-looking links: {sample or 'none found'}")

            nxt = next_page(page, url)
            if not nxt:
                break
            url = nxt

        if fetch.made >= fetch.budget:
            print("request budget spent; stopping here")
            break

    pathlib.Path(OUT).write_text(
        json.dumps(sorted(stations.values(), key=lambda s: -s.get("listeners", 0)),
                   indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    print(f"\n{OUT}: {len(stations)} stations from {fetch.made} requests "
          f"({fetch.failed} failed)")

    if stations:
        counts = Counter(g for s in stations.values() for g in s["genres"])
        print(f"{len(counts)} distinct genres; top 20:")
        for genre, count in counts.most_common(20):
            print(f"  {count:5d}  {genre}")

        needs = [s for s in stations.values() if s.get("needs_resolving")]
        with_page = [s for s in stations.values() if s.get("page")]
        with_home = [s for s in stations.values() if s.get("homepage")]
        playing = [s for s in stations.values() if s.get("now_playing")]
        print(f"\n{len(with_page):5d} have a station page")
        print(f"{len(with_home):5d} gave their own homepage")
        print(f"{len(playing):5d} were playing something at crawl time")
        print(f"{len(needs):5d} point at a playlist rather than a stream")

        print("\nthree examples:")
        for station in sorted(stations.values(), key=lambda s: -s.get("listeners", 0))[:3]:
            print(f"  {json.dumps(station, ensure_ascii=False)}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
