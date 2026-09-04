#!/usr/bin/env python3
"""How many stations can be made to name their track, and by which route.

The app's whole pitch is that it tells you what is playing. It has two ways to
find out: the title the stream interleaves with the audio, and a scrape of the
station's now-playing page. Only 639 of the catalogue's 2,192 stations have
such a page, so for the other 1,553 the inline title is the only route -- and
nobody has ever counted how many of those actually send one. Where it is
missing the screen simply stays blank, which is honest and useless.

There is a third route nothing has tried. Icecast keeps a JSON status document
at /status-json.xsl on the server root, and Shoutcast keeps one at /stats and
an older HTML table at /7.html. Both name the current track, both are on the
station's own server, and neither involves anyone's directory. If a useful
share of the silent stations answer there, the gap closes without any new
dependency.

This measures that. It writes nothing and changes nothing: one pass over a
sample, one connection and at most two small requests per station, reporting
how many answer by each route.

  python3 probe_now_playing.py                 120 stations with no page
  python3 probe_now_playing.py 300             a bigger sample
  python3 probe_now_playing.py 300 all         sample every station instead

Run it from Actions. A sandbox with a filtering egress proxy will report zero
for all three routes, which measures the sandbox rather than the stations.
"""
import json
import random
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CATALOGUE = "music_worldradio.json"
TIMEOUT = 8
WORKERS = 12
UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"
# Two blocks is enough: a relay that allocates the metadata channel and never
# writes to it looks exactly like a station between tracks for one block.
BLOCKS_TO_READ = 2
SEED = 20260904

STREAM_TITLE = re.compile(rb"StreamTitle='(.*?)';")
METAINT = re.compile(rb"icy-metaint:\s*(\d+)", re.I)


def icy_title(url):
    """The title the stream interleaves with the audio, if it sends one."""
    sock = None
    try:
        parts = urllib.parse.urlsplit(url)
        https = parts.scheme == "https"
        port = parts.port or (443 if https else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        sock = socket.create_connection((parts.hostname, port), TIMEOUT)
        if https:
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=parts.hostname)
        sock.settimeout(TIMEOUT)
        sock.sendall(
            f"GET {path} HTTP/1.0\r\nHost: {parts.netloc}\r\n"
            f"User-Agent: {UA}\r\nIcy-MetaData: 1\r\n\r\n".encode())

        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            chunk = sock.recv(2048)
            if not chunk:
                return None
            buf += chunk
        head, _, body = buf.partition(b"\r\n\r\n")

        found = METAINT.search(head)
        if not found:
            return None
        interval = int(found.group(1))

        for _ in range(BLOCKS_TO_READ):
            while len(body) < interval + 1:
                chunk = sock.recv(4096)
                if not chunk:
                    return None
                body += chunk
            length = body[interval] * 16
            while len(body) < interval + 1 + length:
                chunk = sock.recv(4096)
                if not chunk:
                    return None
                body += chunk
            block = body[interval + 1:interval + 1 + length]
            title = STREAM_TITLE.search(block)
            if title and title.group(1).strip():
                return title.group(1).decode("utf-8", "replace").strip()
            body = body[interval + 1 + length:]
        return None
    except Exception:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def fetch(url, limit=200_000):
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read(limit)
    except Exception:
        return None


def icecast_title(url):
    """Icecast publishes a JSON status document at the server root."""
    parts = urllib.parse.urlsplit(url)
    body = fetch(f"{parts.scheme}://{parts.netloc}/status-json.xsl")
    if not body:
        return None
    try:
        sources = json.loads(body).get("icestats", {}).get("source")
    except Exception:
        return None
    if sources is None:
        return None
    if not isinstance(sources, list):
        sources = [sources]
    # A server can carry several mounts. Any named track proves the route
    # works; matching it to the right mount is the next problem, not this one.
    for source in sources:
        if not isinstance(source, dict):
            continue
        title = (source.get("title") or source.get("yp_currently_playing") or "").strip()
        if title:
            return title
    return None


def shoutcast_title(url):
    """Shoutcast v2 answers in JSON; v1 has a seven-field HTML table."""
    parts = urllib.parse.urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"

    body = fetch(base + "/stats?json=1")
    if body:
        try:
            title = (json.loads(body).get("songtitle") or "").strip()
            if title:
                return title
        except Exception:
            pass

    body = fetch(base + "/7.html", limit=8192)
    if body:
        # Seven comma-separated fields inside the body:
        #   listeners, status, peak, max, unique, bitrate, songtitle
        # The title is last and may itself contain commas, so the split is
        # bounded at six rather than taken by index -- which is how the first
        # run of this probe reported listener counts as song titles and
        # inflated Shoutcast's share from nothing to 8.7%.
        text = re.sub(rb"<[^>]+>", b"", body).decode("utf-8", "replace").strip()
        fields = text.split(",", 6)
        if len(fields) == 7:
            title = fields[6].strip()
            # A title that is only digits is another field bleeding through.
            if title and not title.isdigit():
                return title
    return None


def probe(station):
    """The routes in the order the app would try them: stop at the first."""
    url = station["source"]
    row = {"name": station.get("title", ""), "icy": None, "icecast": None, "shoutcast": None}
    row["icy"] = icy_title(url)
    if row["icy"]:
        return row
    row["icecast"] = icecast_title(url)
    if row["icecast"]:
        return row
    row["shoutcast"] = shoutcast_title(url)
    return row


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    scope = sys.argv[2] if len(sys.argv) > 2 else "nopage"

    catalogue = json.load(open(CATALOGUE))["music"]
    streamable = [s for s in catalogue if str(s.get("source", "")).startswith("http")]
    if scope == "nopage":
        pool = [s for s in streamable if not str(s.get("site") or "").strip()]
        what = "with no now-playing page"
    else:
        pool = streamable
        what = "of every kind"

    random.seed(SEED)
    sample = random.sample(pool, min(size, len(pool)))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool_ex:
        rows = list(pool_ex.map(probe, sample))

    total = len(rows)
    icy = sum(1 for r in rows if r["icy"])
    ice = sum(1 for r in rows if r["icecast"])
    shout = sum(1 for r in rows if r["shoutcast"])
    silent = total - icy - ice - shout

    def line(label, n):
        return f"  {label:<26} {n:4d}   {n / total * 100:5.1f}%"

    print(f"{total} stations sampled, {what}, out of {len(pool)}")
    print()
    print(line("inline ICY title", icy) + "   the only route today")
    print(line("Icecast status page", ice) + "   unused")
    print(line("Shoutcast status page", shout) + "   unused")
    print(line("silent on all three", silent))
    print()
    print(f"  coverage today            {icy / total * 100:5.1f}%")
    print(f"  with the status pages     {(icy + ice + shout) / total * 100:5.1f}%")
    print()

    examples = [r for r in rows if r["icecast"] or r["shoutcast"]][:10]
    if examples:
        print("What the status pages answered:")
        for r in examples:
            route = "icecast" if r["icecast"] else "shoutcast"
            print(f"  [{route:9s}] {r['name'][:32]:34s} {(r['icecast'] or r['shoutcast'])[:46]}")
    else:
        print("No station answered on a status page.")


if __name__ == "__main__":
    main()
