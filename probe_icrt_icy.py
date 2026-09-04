#!/usr/bin/env python3
"""Listen to one stream's inline metadata for a while, and print what arrives.

ICRT is the last station still getting its song title from a scraped web page,
and the app carries HtmlUnit -- a headless browser and a JavaScript engine,
about twenty megabytes -- for that one station. If its stream names its own
tracks, all of that stops being load-bearing.

The harvest already found icy-metaint on it, so the server does interleave
metadata; the first StreamTitle it read was empty. That is one sample at one
instant, which is not enough to conclude either way: an empty title happens
between tracks and during ads as readily as it happens on a relay that never
fills it in.

So this stays connected and prints every metadata block for a minute or two.
An empty title repeated for two minutes says the relay does not publish one. A
title appearing says the scraper can go.

  python3 probe_icrt_icy.py                        the ICRT stream, 120s
  python3 probe_icrt_icy.py <url> <seconds>
"""
import re
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit, urlunsplit

DEFAULT_URL = "https://stream.rcs.revma.com/nkdfurztxp3vv"
DEFAULT_SECONDS = 120
UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"

STREAM_TITLE = re.compile(rb"StreamTitle='(.*?)';")
MAX_REDIRECTS = 3


def connect(url):
    parts = urlsplit(url)
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    path = urlunsplit(("", "", parts.path or "/", parts.query, ""))

    sock = socket.create_connection((parts.hostname, port), timeout=20)
    sock.settimeout(20)
    if https:
        sock = ssl.create_default_context().wrap_socket(
            sock, server_hostname=parts.hostname)

    sock.sendall(
        f"GET {path} HTTP/1.0\r\nHost: {parts.netloc}\r\n"
        f"User-Agent: {UA}\r\nIcy-MetaData: 1\r\nAccept: */*\r\n"
        f"Connection: close\r\n\r\n".encode("latin-1"))
    return sock


def read_headers(sock):
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("closed before the headers ended")
        buffer += chunk
    head, _, body = buffer.partition(b"\r\n\r\n")
    lines = head.decode("latin-1", "replace").split("\r\n")
    pieces = lines[0].split()
    status = int(pieces[1]) if len(pieces) > 1 and pieces[1].isdigit() else 0
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if value:
            headers[name.strip().lower()] = value.strip()
    return status, headers, body


def main(argv):
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    seconds = int(argv[2]) if len(argv) > 2 else DEFAULT_SECONDS

    for _ in range(MAX_REDIRECTS + 1):
        sock = connect(url)
        status, headers, body = read_headers(sock)
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            sock.close()
            url = headers["location"]
            print(f"redirected to {url}")
            continue
        break
    else:
        print("too many redirects")
        return 1

    print(f"{url}\nHTTP {status}")
    for name in ("content-type", "icy-name", "icy-genre", "icy-description",
                 "icy-br", "icy-metaint", "server"):
        if headers.get(name):
            print(f"  {name}: {headers[name]}")

    metaint = headers.get("icy-metaint")
    if not (metaint and metaint.isdigit()):
        print("\nno icy-metaint: this stream carries no inline metadata at all")
        return 0
    metaint = int(metaint)

    print(f"\nlistening for {seconds}s, printing every metadata block\n")
    deadline = time.time() + seconds
    started = time.time()
    blocks = empty = 0
    titles = []

    while time.time() < deadline:
        # Skip metaint bytes of audio.
        remaining = metaint - len(body)
        while remaining > 0:
            chunk = sock.recv(min(remaining, 8192))
            if not chunk:
                print("stream ended")
                break
            remaining -= len(chunk)
        if remaining > 0:
            break
        body = b""

        length_byte = sock.recv(1)
        if not length_byte:
            print("stream ended")
            break
        length = length_byte[0] * 16
        blocks += 1

        if length == 0:
            empty += 1
            continue

        block = b""
        while len(block) < length:
            chunk = sock.recv(length - len(block))
            if not chunk:
                break
            block += chunk

        found = STREAM_TITLE.search(block)
        title = found.group(1).decode("utf-8", "replace").strip() if found else ""
        stamp = f"{time.time() - started:6.1f}s"
        if title:
            titles.append(title)
            print(f"  {stamp}  StreamTitle: {title}")
        else:
            empty += 1
            print(f"  {stamp}  (empty)  raw: {block[:80]!r}")

    sock.close()
    print(f"\n{blocks} metadata blocks, {len(titles)} with a title, {empty} empty")
    if titles:
        print("\ndistinct titles seen:")
        for title in dict.fromkeys(titles):
            print(f"  {title}")
        print("\nThe stream names its own tracks. The scraper is not needed.")
    else:
        print("\nEvery block was empty for the whole window. This relay does not")
        print("publish track titles, and the scrape stays for this station.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
