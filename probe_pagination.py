#!/usr/bin/env python3
"""Two guesses failed. Look at the evidence instead.

The crawler walks 200 genre listings and comes back with ~1140 stations, one
page's worth each, and two attempts at finding the "next page" link have both
changed nothing. And 207 playlists refuse to resolve, 192 of them with a
connection reset, which a retry as a player user agent did not recover a single
one of -- so that guess was wrong too.

Rather than a third guess, this prints what is actually there:

  * every distinct first path segment linked from /stations/, in case the
    directory is indexed by something other than genre;
  * the bottom of one genre listing, where a pagination control would live,
    with every anchor in it;
  * and for a handful of the resets, what happens at the socket -- whether the
    connection is refused, established then dropped, or answered and then cut,
    which are three different problems wearing the same error message.

It writes nothing.
"""
import collections
import html
import json
import pathlib
import re
import socket
import ssl
import sys
import time
import urllib.request
from urllib.parse import urljoin, urlsplit, urlunsplit

BASE = "https://www.internet-radio.com/"
UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"
PAUSE = 2.0


def get(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html", "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    finally:
        time.sleep(PAUSE)


def show(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def how_the_site_is_indexed():
    show("what /stations/ links to, by first path segment")
    page = get(BASE + "stations/")
    segments = collections.Counter()
    for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
        target = urljoin(BASE, html.unescape(href))
        if not target.startswith(BASE):
            continue
        rest = target[len(BASE):].strip("/")
        segments[rest.split("/")[0] or "(root)"] += 1
    for name, count in segments.most_common(20):
        print(f"  {count:4d}  /{name}/")

    show("the whole navigation, so other index dimensions are visible")
    for href in sorted({html.unescape(h) for h in
                        re.findall(r'href=["\'](/[^"\']*)["\']', page, re.I)
                        if not h.startswith("/stations/")})[:40]:
        print(f"  {href}")


def bottom_of_a_listing(slug="pop"):
    url = f"{BASE}stations/{slug}/"
    show(f"the bottom of {url} -- where pagination would be")
    page = get(url)
    print(f"{len(page)} chars, {len(re.findall(r'<tr', page, re.I))} table rows")

    rows = len(re.findall(r"playlistgenerator", page, re.I))
    print(f"{rows} playlist-generator links (two per station, so ~{rows // 2} stations)")

    tail = page[-9000:]
    print("\n-- every anchor in the last 9000 characters --")
    for match in re.finditer(r"<a\b[^>]*>.*?</a>", tail, re.I | re.S):
        flat = re.sub(r"\s+", " ", match.group(0))
        print(f"  {flat[:220]}")

    print("\n-- anything mentioning page, next, more or pagination --")
    for word in ("pagination", "next", "page", "more", "showing", "results"):
        for match in re.finditer(re.escape(word), page, re.I):
            chunk = re.sub(r"\s+", " ", page[max(0, match.start() - 160):match.start() + 240])
            print(f"  [{word}] {chunk[:300]}")
            break


def what_a_reset_really_is():
    facts = pathlib.Path("directory.json")
    if not facts.exists():
        print("no directory.json; nothing to retry")
        return

    urls = [s["stream"] for s in json.loads(facts.read_text(encoding="utf-8"))
            if "Reset" in (s.get("resolve_error") or "")][:6]
    show(f"what happens on the wire for {len(urls)} of the resets")

    for url in urls:
        print(f"\n--- {url}")
        parts = urlsplit(url)
        https = parts.scheme == "https"
        port = parts.port or (443 if https else 80)
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        try:
            sock = socket.create_connection((parts.hostname, port), timeout=15)
            print("    tcp connected")
            sock.settimeout(15)
            if https:
                sock = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=parts.hostname)
                print("    tls established")

            # Deliberately plain: no Connection header, HTTP/1.1, browser-ish.
            # If this works where the crawler's request did not, the difference
            # is in the request, not in the host.
            sock.sendall(
                f"GET {path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
                f"User-Agent: Mozilla/5.0\r\nAccept: */*\r\n\r\n".encode("latin-1"))
            print("    request sent")

            first = sock.recv(4096)
            print(f"    {len(first)} bytes back: {first[:200]!r}")
            sock.close()
        except Exception as exc:                   # noqa: BLE001
            print(f"    {type(exc).__name__}: {exc}")


def main():
    how_the_site_is_indexed()
    bottom_of_a_listing()
    what_a_reset_really_is()
    return 0


if __name__ == "__main__":
    sys.exit(main())
