#!/usr/bin/env python3
"""Ask every station what it is, and write down what it answers.

The catalogue knows a name, a stream URL and a web page, which is not enough to
build a browsable app: 712 stations sorted into no categories is a list of
strangers. The stations themselves know more than that, and say so in the
handshake -- Icecast and SHOUTcast return icy-name, icy-genre and
icy-description as response headers before a byte of audio, filled in by whoever
runs the station.

This connects to every stream, records those headers, and where the server
offers inline metadata also reads the first StreamTitle so we know which
stations announce their tracks at all. Nothing is inferred and nothing is
guessed; that is a later step's job, working from this file.

  python3 harvest_icy.py                 all catalogues -> station_facts.json
  python3 harvest_icy.py music.json      one catalogue

Why raw sockets rather than urllib: SHOUTcast v1 answers "ICY 200 OK" instead of
a valid HTTP status line, and urllib raises BadStatusLine before any header is
readable. That is a large minority of these stations, so the status line has to
be parsed by hand.
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

CATALOGUES = ["music.json", "music_worldradio.json"]
FACTS_FILE = "station_facts.json"

CONNECT_TIMEOUT = 12
READ_DEADLINE = 25          # a whole station, headers plus one metadata block
MAX_REDIRECTS = 3
# 24 was sized for the 833 streams of the published catalogue. The crawled
# directory is 2721, and a run where most of them time out at 12s would need
# most of an hour at that width.
WORKERS = 48

# This file used to be advisory -- a browsable-by field nobody depended on.
# Once build_catalogue.py started reading it to decide whether a station ships
# at all, "ok: false" stopped meaning "this station is dead" and started
# meaning "this station did not answer one TCP connection inside twelve
# seconds," which a healthy stream can fail to do for reasons that have
# nothing to do with whether it is still broadcasting. Only stations that
# fail every attempt end up not-ok; one bad connection surrounded by good
# ones no longer costs a station its place in the catalogue for a week.
RETRY_ATTEMPTS = 3
RETRY_DELAY = 3

UA = "Mozilla/5.0 (compatible; icrtradio-catalogue-facts/1.0)"

# The fields a station operator fills in. icy-metaint is the server telling us
# how often it will interleave a title into the audio -- its presence is the
# answer to "does this station announce its tracks".
WANTED = (
    "icy-name", "icy-genre", "icy-description", "icy-url",
    "icy-br", "icy-pub", "icy-sr", "icy-metaint",
    "content-type", "server",
)

STREAM_TITLE = re.compile(rb"StreamTitle='(.*?)';")


def items_of(doc):
    if isinstance(doc, list):
        return doc
    for key in ("music", "stations", "items", "data"):
        if isinstance(doc.get(key), list):
            return doc[key]
    return []


def connect(url, timeout):
    parts = urlsplit(url)
    https = parts.scheme == "https"
    host = parts.hostname
    port = parts.port or (443 if https else 80)
    path = urlunsplit(("", "", parts.path or "/", parts.query, ""))

    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    if https:
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)

    request = (
        f"GET {path} HTTP/1.0\r\n"
        f"Host: {parts.netloc}\r\n"
        f"User-Agent: {UA}\r\n"
        f"Icy-MetaData: 1\r\n"
        f"Accept: */*\r\n"
        f"Connection: close\r\n\r\n"
    )
    sock.sendall(request.encode("latin-1"))
    return sock


def read_headers(sock, deadline):
    """Return (status_code, headers, leftover_body_bytes)."""
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        if time.monotonic() > deadline or len(buffer) > 32768:
            raise TimeoutError("no end of headers")
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("closed before headers ended")
        buffer += chunk

    head, _, body = buffer.partition(b"\r\n\r\n")
    lines = head.decode("latin-1", "replace").split("\r\n")

    # "HTTP/1.0 200 OK" or SHOUTcast v1's "ICY 200 OK". Both put the code second.
    pieces = lines[0].split()
    status = int(pieces[1]) if len(pieces) > 1 and pieces[1].isdigit() else 0

    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if value:
            headers[name.strip().lower()] = value.strip()
    return status, headers, body


def read_first_title(sock, metaint, body, deadline):
    """The title the server interleaves into the audio, if it sends one."""
    # Skip metaint bytes of audio, then a length byte, then that many 16-byte
    # blocks of metadata.
    while len(body) < metaint + 1:
        if time.monotonic() > deadline:
            return None
        chunk = sock.recv(8192)
        if not chunk:
            return None
        body += chunk

    length = body[metaint] * 16
    if length == 0:
        return ""                       # a title slot, currently empty

    while len(body) < metaint + 1 + length:
        if time.monotonic() > deadline:
            return None
        chunk = sock.recv(8192)
        if not chunk:
            return None
        body += chunk

    block = body[metaint + 1:metaint + 1 + length]
    found = STREAM_TITLE.search(block)
    return found.group(1).decode("utf-8", "replace").strip() if found else None


def interrogate(url):
    """Everything the station is willing to say about itself, or why it did not."""
    deadline = time.monotonic() + READ_DEADLINE
    seen = url

    for _ in range(MAX_REDIRECTS + 1):
        sock = None
        try:
            sock = connect(seen, CONNECT_TIMEOUT)
            status, headers, body = read_headers(sock, deadline)

            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                seen = headers["location"]
                continue
            if status not in (200, 0):
                return {"ok": False, "error": f"HTTP {status}"}

            facts = {name: headers[name] for name in WANTED if headers.get(name)}
            facts["ok"] = True
            if seen != url:
                facts["resolved"] = seen

            metaint = headers.get("icy-metaint")
            if metaint and metaint.isdigit():
                title = read_first_title(sock, int(metaint), body, deadline)
                if title is not None:
                    facts["stream_title"] = title
            return facts
        except Exception as exc:                   # noqa: BLE001 - record, never raise
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    return {"ok": False, "error": "too many redirects"}


def interrogate_with_retries(url):
    """interrogate(), but a single failed connection is not the final answer.

    A retry immediately after the same failure mostly re-hits the same problem
    -- the same overloaded host, the same mid-handshake reset -- so this waits
    between attempts rather than hammering the stream three times in a row.
    The last attempt's facts are what gets recorded either way; only whether
    it took more than one try is added, for the run's own summary.
    """
    for attempt in range(RETRY_ATTEMPTS):
        facts = interrogate(url)
        if facts.get("ok") or attempt == RETRY_ATTEMPTS - 1:
            if attempt:
                facts["attempts"] = attempt + 1
            return facts
        time.sleep(RETRY_DELAY)
    return facts  # unreachable; keeps type checkers happy


def main(argv):
    names = argv[1:] or CATALOGUES

    sources = {}
    for name in names:
        path = pathlib.Path(name)
        if not path.exists():
            print(f"{name}: not here, skipping")
            continue
        for item in items_of(json.loads(path.read_text(encoding="utf-8"))):
            # The published catalogue calls them source/title; the crawled
            # directory calls them stream/name. Same two things.
            url = (item.get("source") or item.get("stream") or "").strip()
            if url:
                sources.setdefault(url, item.get("title") or item.get("name") or "")

    print(f"asking {len(sources)} stations, {WORKERS} at a time")
    urls = list(sources)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(interrogate_with_retries, urls))

    facts = {}
    for url, answer in zip(urls, answers):
        answer["title"] = sources[url]
        facts[url] = answer

    pathlib.Path(FACTS_FILE).write_text(
        json.dumps(facts, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    reachable = [f for f in facts.values() if f.get("ok")]
    with_genre = [f for f in reachable if f.get("icy-genre")]
    with_name = [f for f in reachable if f.get("icy-name")]
    with_desc = [f for f in reachable if f.get("icy-description")]
    announce = [f for f in reachable if f.get("icy-metaint")]
    titled = [f for f in reachable if f.get("stream_title")]
    saved_by_retry = [f for f in reachable if f.get("attempts")]

    total = len(facts) or 1
    def line(label, rows):
        print(f"  {len(rows):4d}  {len(rows) * 100 // total:3d}%  {label}")

    print(f"\n{FACTS_FILE}: {len(facts)} stations")
    line("answered at all", reachable)
    line("gave a name", with_name)
    line("gave a genre", with_genre)
    line("gave a description", with_desc)
    line("offer inline metadata (icy-metaint)", announce)
    line("named a track on connect", titled)
    if saved_by_retry:
        print(f"\n  {len(saved_by_retry):4d}  needed a second or third attempt "
              f"to answer at all")

    if with_genre:
        print("\ngenre strings, most common first:")
        counts = {}
        for f in with_genre:
            counts[f["icy-genre"]] = counts.get(f["icy-genre"], 0) + 1
        for genre, count in sorted(counts.items(), key=lambda kv: -kv[1])[:25]:
            print(f"  {count:4d}  {genre}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
