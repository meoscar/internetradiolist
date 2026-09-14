#!/usr/bin/env python3
"""Ask a station's own server how many people are listening.

Where this number comes from today: six listing pages on internet-radio.com,
once every fifteen minutes. It works, and it is the last thing in this
repository that needs that site every quarter of an hour rather than once a
week. It also answers a slightly different question from the one we ask --
the site knows what it last saw, we want what is true now -- and it only
covers the stations that reach the top of six genre pages.

The stations themselves know exactly, and say so without being asked twice.
Icecast publishes a JSON status document at /status-json.xsl on the server
root; Shoutcast v2 answers /stats?json=1 and v1 keeps a seven-field table at
/7.html. All three are on the station's own host, and live_now.py is already
connecting to that host in the same pass to ask what is playing.

  listeners_of(url) -> int | None

None means the station did not answer, which is not zero. A station shown as
"0 listening" would be a claim; 388 rows of the catalogue already have no
count at all and every reader treats absent as unknown.

probe_now_playing.py has its own copy of the title-reading half of this. That
copy is deliberately left alone: it is a measuring instrument whose numbers
have been quoted, and rewriting it would change what those numbers meant.
"""
import json
import re
import urllib.parse
import urllib.request

TIMEOUT = 8
UA = "icrtradio-catalogue/1.0 (+https://github.com/meoscar/internetradiolist)"


def _fetch(url, limit=200_000):
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read(limit)
    except Exception:
        return None


def _icecast(body):
    """Icecast's status document. A server can carry several mounts."""
    try:
        sources = json.loads(body).get("icestats", {}).get("source")
    except Exception:
        return None
    if sources is None:
        return None
    if not isinstance(sources, list):
        sources = [sources]
    # The busiest mount on the host. Matching a count to the exact mount we
    # play needs the mount path, and a station whose host serves one stream --
    # which is nearly all of them -- gives the same answer either way. Taking
    # the largest rather than the sum: a sum would count a station's own relay
    # twice and report an audience it does not have.
    best = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = source.get("listeners")
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value < 0:
            continue
        if best is None or value > best:
            best = value
    return best


def _icecast_title(body):
    """The record on the busiest mount, as the same document names it."""
    try:
        sources = json.loads(body).get("icestats", {}).get("source")
    except Exception:
        return None
    if sources is None:
        return None
    if not isinstance(sources, list):
        sources = [sources]
    best, best_title = None, None
    for source in sources:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("yp_currently_playing") or "").strip()
        if not title or title.isdigit():
            continue
        value = source.get("listeners")
        value = value if isinstance(value, int) and not isinstance(value, bool) else -1
        if best is None or value > best:
            best, best_title = value, title
    return best_title


def _shoutcast_v2(body):
    try:
        value = json.loads(body).get("currentlisteners")
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _shoutcast_v2_title(body):
    try:
        title = str(json.loads(body).get("songtitle") or "").strip()
    except Exception:
        return None
    return title if title and not title.isdigit() else None


def _shoutcast_v1_title(body):
    """The seventh field. A title that is only digits is another field
    bleeding through an error page, not a song."""
    text = re.sub(rb"<[^>]+>", b"", body).decode("utf-8", "replace").strip()
    fields = text.split(",", 6)
    if len(fields) != 7 or not fields[0].strip().isdigit():
        return None
    title = fields[6].strip()
    return title if title and not title.isdigit() else None


def _shoutcast_v1(body):
    """Seven comma-separated fields, listeners first.

      listeners, status, peak, max, unique, bitrate, songtitle

    The title is last and may contain commas, which is why probe_now_playing
    bounds its split at six. The count is field zero and needs no such care --
    but it does need checking that it is a number, because a server that
    answers this path with an error page produces seven fields of prose.
    """
    text = re.sub(rb"<[^>]+>", b"", body).decode("utf-8", "replace").strip()
    fields = text.split(",", 6)
    if len(fields) != 7:
        return None
    head = fields[0].strip()
    if not head.isdigit():
        return None
    return int(head)


def status_of(url):
    """What the station's own server says about itself right now: how many
    are listening, and the record on -- {"listeners", "title", "via"}, each
    None where the server would not say.

    Three documents, tried in order, the first that answers either question
    taken: a host serves one kind of server. The title is the third route to
    a song the app has, after the stream's inline title and ICRT's log, and
    the one for stations whose stream carries no metadata channel at all --
    measured on a sample of 400: 2.3% of the catalogue answers only here."""
    empty = {"listeners": None, "title": None, "via": None}
    try:
        parts = urllib.parse.urlsplit(url)
        if not parts.netloc:
            return empty
        base = f"{parts.scheme}://{parts.netloc}"
    except Exception:
        return empty

    body = _fetch(base + "/status-json.xsl")
    if body:
        count, title = _icecast(body), _icecast_title(body)
        if count is not None or title:
            return {"listeners": count, "title": title, "via": "icecast"}

    body = _fetch(base + "/stats?json=1")
    if body:
        count, title = _shoutcast_v2(body), _shoutcast_v2_title(body)
        if count is not None or title:
            return {"listeners": count, "title": title, "via": "shoutcast"}

    body = _fetch(base + "/7.html", limit=8192)
    if body:
        count, title = _shoutcast_v1(body), _shoutcast_v1_title(body)
        if count is not None or title:
            return {"listeners": count, "title": title, "via": "shoutcast"}

    return empty


def listeners_of(url):
    """How many people are on this station right now, or None if it will not say."""
    return status_of(url)["listeners"]


def title_of(url):
    """The record the station's own server says is on, or None if it will not say."""
    return status_of(url)["title"]
