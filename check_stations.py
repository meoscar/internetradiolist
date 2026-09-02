#!/usr/bin/env python3
"""Find the stations that have stopped broadcasting, and eventually drop them.

An internet radio catalogue rots quietly: hosts move, stations close, and the
listener only finds out by tapping one and watching it spin. This connects to
every stream and records what answered.

Nothing is removed on a single failure -- a station can be down for a night
without being gone -- so a running count of consecutive failures is kept in
health.json and a stream is only dropped once it has missed FAILURES_BEFORE_DROP
runs in a row. Anything that answers resets its own count.

Usage:
  python3 check_stations.py                 report only, write health.json
  python3 check_stations.py --drop-dead     also remove stations past the limit
"""
import json
import pathlib
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CATALOGUES = ["music.json", "music_worldradio.json", "music_worldradio_test.json"]
HEALTH_FILE = "health.json"

CONNECT_TIMEOUT = 12
BYTES_WANTED = 8192          # enough to tell a stream from an error page
WORKERS = 24
FAILURES_BEFORE_DROP = 3

# Not every failure means the same thing. A refused connection or a name that
# no longer resolves is the host telling us the station is gone; a timeout or a
# 503 is a station that may be back tonight. Both used to count one strike each,
# so a station that had plainly vanished waited the same three days as one
# having a bad evening. Hard failures count double.
HARD_FAILURE = ("Connection refused", "Name or service not known",
                "nodename nor servname", "No address associated",
                "Temporary failure in name resolution",
                "HTTP Error 404", "HTTP Error 410")

UA = "Mozilla/5.0 (compatible; icrtradio-catalogue-check/1.0)"


def items_of(doc):
    if isinstance(doc, list):
        return doc
    for key in ("music", "stations", "items", "data"):
        if isinstance(doc.get(key), list):
            return doc[key]
    for value in doc.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def probe(url: str) -> tuple[str, bool, str]:
    """True when the URL delivers audio bytes rather than an error or nothing."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT) as response:
            body = response.read(BYTES_WANTED)
            kind = response.headers.get("Content-Type", "")
            if len(body) < 1024:
                return url, False, f"only {len(body)} bytes"
            if kind.startswith("text/"):
                return url, False, f"served {kind}, not audio"
            return url, True, kind or "ok"
    except Exception as exc:                       # noqa: BLE001 - report, never raise
        return url, False, f"{type(exc).__name__}: {exc}"


def seed_from_icy_harvest(urls) -> dict:
    """Start the counter from what harvest_icy.py already measured.

    Waiting three nights before dropping a station is right when the only
    evidence is one probe. It is not right when a second, independent tool has
    already connected to every one of these streams with a different library and
    come back with the same answer -- 53% alive here, 55% there. So the harvest,
    where it also failed, counts as one strike already served.
    """
    facts_file = pathlib.Path("station_facts.json")
    if not facts_file.exists():
        return {}

    facts = json.loads(facts_file.read_text("utf-8"))
    seeded = {}
    for url in urls:
        answer = facts.get(url)
        if answer and not answer.get("ok"):
            seeded[url] = {
                "consecutive_failures": 1,
                "last": f"icy harvest: {answer.get('error', 'no answer')}",
            }
    if seeded:
        print(f"{len(seeded)} streams start on one strike, from the ICY harvest\n")
    return seeded


def main() -> int:
    drop_dead = "--drop-dead" in sys.argv

    urls, first_seen = set(), {}
    for name in CATALOGUES:
        path = pathlib.Path(name)
        if not path.exists():
            continue
        for entry in items_of(json.loads(path.read_text("utf-8"))):
            source = entry.get("source") if isinstance(entry, dict) else None
            if source:
                urls.add(source)
                first_seen.setdefault(source, entry.get("title", "?"))

    print(f"probing {len(urls)} distinct streams\n")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(probe, sorted(urls)))

    health = {}
    if pathlib.Path(HEALTH_FILE).exists():
        health = json.loads(pathlib.Path(HEALTH_FILE).read_text("utf-8"))
    else:
        health = seed_from_icy_harvest(urls)

    alive, newly_failing, past_limit = 0, [], []
    for url, ok, detail in results:
        record = health.get(url, {"consecutive_failures": 0})
        if ok:
            alive += 1
            record = {"consecutive_failures": 0, "last": detail}
        else:
            weight = 2 if any(mark in detail for mark in HARD_FAILURE) else 1
            record = {
                "consecutive_failures": record.get("consecutive_failures", 0) + weight,
                "last": detail,
            }
            newly_failing.append((url, detail, record["consecutive_failures"]))
            if record["consecutive_failures"] >= FAILURES_BEFORE_DROP:
                past_limit.append(url)
        health[url] = record

    # Streams no longer in any catalogue do not need tracking.
    health = {u: r for u, r in health.items() if u in urls}
    pathlib.Path(HEALTH_FILE).write_text(
        json.dumps(health, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8"
    )

    print(f"alive       {alive}")
    print(f"failing     {len(newly_failing)}")
    print(f"past limit  {len(past_limit)}  (failed {FAILURES_BEFORE_DROP}+ runs in a row)\n")
    for url, detail, count in sorted(newly_failing, key=lambda r: -r[2])[:25]:
        print(f"  x{count}  {first_seen.get(url,'?')[:40]:<40} {detail[:60]}")

    if not drop_dead or not past_limit:
        if past_limit and not drop_dead:
            print(f"\n{len(past_limit)} station(s) would be dropped with --drop-dead")
        return 0

    dead = set(past_limit)
    for name in CATALOGUES:
        path = pathlib.Path(name)
        if not path.exists():
            continue
        doc = json.loads(path.read_text("utf-8"))
        if isinstance(doc, list):
            items, container, key = doc, None, None
        else:
            key = next(k for k, v in doc.items() if isinstance(v, list) and v and isinstance(v[0], dict))
            items, container = doc[key], doc
        kept = [m for m in items if m.get("source") not in dead]
        if len(kept) == len(items):
            continue
        out = kept if container is None else {**container, key: kept}
        path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
        print(f"\n{name}: {len(items)} -> {len(kept)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
