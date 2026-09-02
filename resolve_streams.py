#!/usr/bin/env python3
"""Turn playlist links into the stream they point at.

The directory hands out a .pls or .m3u for most stations rather than the audio
URL -- 49 of the first 51 crawled. ExoPlayer plays neither: a .pls is an INI
file, a plain .m3u is a list of URLs, and only .m3u8 (HLS) is a format it
understands. Putting those into the catalogue unresolved would ship a list of
stations that spin forever, which is the failure this whole exercise exists to
remove.

A playlist is one small text file naming the stream, so this reads it and keeps
the first URL inside, holding on to the playlist URL in case it is needed again.

Every station is a different host, so these run in parallel -- the politeness
that governs the crawler is about not overloading one site, and none of it
applies here.

  python3 resolve_streams.py                 directory.json in place
  python3 resolve_streams.py other.json
"""
import json
import pathlib
import re
import socket
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit

TIMEOUT = 15
WORKERS = 24
MAX_BYTES = 64 * 1024
MAX_REDIRECTS = 3

UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"

PLS_FILE = re.compile(r"^\s*File\d+\s*=\s*(\S+)", re.I | re.M)


def fetch(url, deadline):
    """Read a small text file, tolerating servers that answer 'ICY 200 OK'.

    The hosts serving these playlists are the streaming servers themselves, and
    a good number of them are SHOUTcast v1, whose status line is not valid HTTP.
    urllib raises BadStatusLine on those before a byte is readable.
    """
    parts = urlsplit(url)
    https = parts.scheme == "https"
    port = parts.port or (443 if https else 80)
    path = urlunsplit(("", "", parts.path or "/", parts.query, ""))

    sock = socket.create_connection((parts.hostname, port), timeout=TIMEOUT)
    try:
        sock.settimeout(TIMEOUT)
        if https:
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=parts.hostname)

        sock.sendall(
            f"GET {path} HTTP/1.0\r\nHost: {parts.netloc}\r\n"
            f"User-Agent: {UA}\r\nAccept: */*\r\nConnection: close\r\n\r\n"
            .encode("latin-1"))

        buffer = b""
        while len(buffer) < MAX_BYTES and time.monotonic() < deadline:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buffer += chunk
    finally:
        try:
            sock.close()
        except OSError:
            pass

    head, _, body = buffer.partition(b"\r\n\r\n")
    lines = head.decode("latin-1", "replace").split("\r\n")
    pieces = lines[0].split()
    status = int(pieces[1]) if len(pieces) > 1 and pieces[1].isdigit() else 0

    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if value:
            headers[name.strip().lower()] = value.strip()
    return status, headers, body.decode("utf-8", "replace")


def first_url_in(playlist, kind):
    if kind == "pls":
        found = PLS_FILE.search(playlist)
        if found:
            return found.group(1).strip()
    for line in playlist.splitlines():
        line = line.strip()
        if line.startswith(("http://", "https://")):
            return line
    return None


def resolve(url):
    """(resolved_url, note). resolved_url is None when it could not be read."""
    deadline = time.monotonic() + TIMEOUT * 2
    here = url

    for _ in range(MAX_REDIRECTS + 1):
        try:
            status, headers, body = fetch(here, deadline)
        except Exception as exc:                   # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"

        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            here = headers["location"]
            continue
        if status not in (200, 0):
            return None, f"HTTP {status}"

        kind = "pls" if re.search(r"\.pls(\?|$)", here, re.I) else "m3u"
        inner = first_url_in(body, kind)
        if not inner:
            return None, "no URL inside the playlist"
        # A playlist naming another playlist is rare but does happen.
        if re.search(r"\.(pls|m3u)(\?|$)", inner, re.I) and inner != here:
            here = inner
            continue
        return inner, "ok"

    return None, "playlist chain too deep"


def main(argv):
    path = pathlib.Path(argv[1] if len(argv) > 1 else "directory.json")
    stations = json.loads(path.read_text(encoding="utf-8"))

    pending = [s for s in stations if s.get("needs_resolving")]
    print(f"{len(pending)} of {len(stations)} stations point at a playlist")
    if not pending:
        return 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda s: resolve(s["stream"]), pending))

    fixed = 0
    reasons = {}
    for station, (inner, note) in zip(pending, results):
        if inner:
            station["playlist"] = station["stream"]
            station["stream"] = inner
            station.pop("needs_resolving", None)
            fixed += 1
        else:
            station["resolve_error"] = note
            reasons[note.split(":")[0]] = reasons.get(note.split(":")[0], 0) + 1

    path.write_text(
        json.dumps(stations, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    print(f"{fixed} resolved, {len(pending) - fixed} not")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}  {reason}")

    print("\nthree resolved:")
    for station in [s for s in pending if s.get("playlist")][:3]:
        print(f"  {station['name']}")
        print(f"    was {station['playlist']}")
        print(f"    now {station['stream']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
