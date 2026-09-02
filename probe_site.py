#!/usr/bin/env python3
"""Look at internet-radio.com before writing anything that parses it.

This repository's catalogue came from that site years ago and has been drifting
since: 44% of the stream URLs no longer answer, the genre field is whatever the
broadcaster typed, and there is no country, no language and no popularity to
browse by. The site itself has all of that, organised, and keeps it current.

Before a crawler can be written, its structure has to be seen -- which pages
list stations, what a station page actually contains, and what robots.txt
permits. Guessing at HTML that cannot be inspected is how you write a parser
that silently returns nothing.

So this fetches a handful of pages and prints what is in them. It writes no
catalogue and parses nothing for keeps; its whole output is a description of
the site, read from the workflow log.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from urllib.parse import urljoin

BASE = "https://www.internet-radio.com/"

# Identifiable, and slow. This catalogue depends on the site staying reachable,
# so nothing here is worth being rate-limited for.
UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"
PAUSE = 2.0
TIMEOUT = 25


def get(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read()
        return response.status, dict(response.headers), body.decode("utf-8", "replace")


def show(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def links(html):
    return re.findall(r'href=["\']([^"\']+)["\']', html, re.I)


def classes(html):
    found = Counter()
    for value in re.findall(r'class=["\']([^"\']+)["\']', html, re.I):
        for name in value.split():
            found[name] += 1
    return found


def probe(url, label, dump_lines=0):
    print(f"\n--- GET {url}")
    try:
        status, headers, html = get(url)
    except urllib.error.HTTPError as exc:
        print(f"    HTTP {exc.code}")
        return None
    except Exception as exc:                       # noqa: BLE001
        print(f"    {type(exc).__name__}: {exc}")
        return None
    finally:
        time.sleep(PAUSE)

    print(f"    {status}  {len(html)} chars  {headers.get('Content-Type','')}")
    for header in ("ETag", "Last-Modified", "Cache-Control"):
        if headers.get(header):
            print(f"    {header}: {headers[header]}")

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title:
        print(f"    <title> {title.group(1).strip()[:120]}")

    found = links(html)
    station = [u for u in found if "/station/" in u]
    listing = [u for u in found if re.search(r"/stations?/", u) and "/station/" not in u]
    print(f"    links: {len(found)} total, {len(station)} to /station/, {len(listing)} to listings")

    if station:
        print("    station links, first 8:")
        for u in station[:8]:
            print(f"      {u}")
    if listing:
        print("    listing links, first 15:")
        for u in sorted(set(listing))[:15]:
            print(f"      {u}")

    top = [f"{name}({count})" for name, count in classes(html).most_common(18)]
    print(f"    classes: {', '.join(top)}")

    # The things worth extracting usually announce themselves in the markup.
    for word in ("bitrate", "listeners", "genre", "country", "language",
                 "now playing", "m3u", ".pls", "og:image", "itemprop"):
        hits = len(re.findall(re.escape(word), html, re.I))
        if hits:
            print(f"    mentions {word!r}: {hits}")

    if dump_lines:
        show(f"{label}: first {dump_lines} non-empty lines of markup")
        shown = 0
        for line in html.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            print(stripped[:200])
            shown += 1
            if shown >= dump_lines:
                break
    return html


def main():
    show("robots.txt -- what we are allowed to do")
    try:
        _, _, robots = get(BASE + "robots.txt")
        print(robots.strip()[:3000])
    except Exception as exc:                       # noqa: BLE001
        print(f"could not read robots.txt: {type(exc).__name__}: {exc}")
        print("treat that as 'do not crawl' until it is readable")
    time.sleep(PAUSE)

    show("home page -- how the site is indexed")
    home = probe(BASE, "home")

    # Follow the site's own listing links rather than inventing URL shapes.
    candidates = []
    if home:
        for href in links(home):
            if re.search(r"/stations?/", href) and "/station/" not in href:
                candidates.append(urljoin(BASE, href))
    candidates = sorted(set(candidates))

    show(f"listing pages -- {len(candidates)} found, probing up to 3")
    listing_html = None
    for url in candidates[:3]:
        html = probe(url, "listing")
        if html and "/station/" in html:
            listing_html = listing_html or html

    show("one listing page in full detail")
    if listing_html:
        station_urls = sorted({urljoin(BASE, u) for u in links(listing_html)
                               if "/station/" in u})
        print(f"{len(station_urls)} station pages linked from it")

        # A listing row carries the fields worth having: genre, bitrate,
        # listeners. Show the markup around the first station link so the
        # parser can be written against what is actually there.
        where = listing_html.find("/station/")
        if where > 0:
            start = max(0, where - 2500)
            show("markup around the first station link on the listing")
            for line in listing_html[start:where + 2500].splitlines():
                if line.strip():
                    print(line.strip()[:200])

        show("one station page")
        if station_urls:
            probe(station_urls[0], "station", dump_lines=0)
            # The station page's own markup, around the parts that matter.
            _, _, page = get(station_urls[0])
            for marker in ("Genre", "Bitrate", "Listeners", "Country", "Language"):
                for match in re.finditer(re.escape(marker), page):
                    chunk = page[match.start() - 200:match.start() + 400]
                    print(f"\n... context for {marker!r} ...")
                    for line in chunk.splitlines():
                        if line.strip():
                            print(line.strip()[:200])
                    break
    else:
        print("no listing page yielded station links -- the shapes above are the")
        print("only evidence available; do not write a parser from guesses")

    return 0


if __name__ == "__main__":
    sys.exit(main())
