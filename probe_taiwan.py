#!/usr/bin/env python3
"""How much of Taiwan's radio could this app carry, and how well?

The catalogue has one station in Taiwan: ICRT. That is what internet-radio.com
holds, and the app's owner lives in Taiwan. Before planning anything -- a
hand-kept list, a merge from Radio Browser, per-station now-playing routes --
the questions are how many Taiwanese stations a public directory knows, how
many of those streams answer, and how many say what they are playing. This
asks Radio Browser for every station filed under TW and tries each stream
the way the app would.

What it measures per stream:

    reachable    the stream answered with audio, or an HLS playlist
    hls          the stream is an HLS playlist (.m3u8), which ExoPlayer plays
                 but which carries no ICY title, so the record on cannot come
                 from the stream
    icy          an ICY StreamTitle in the first blocks
    status       the station's own Icecast or Shoutcast status document
    nothing      plays, names nothing

It writes probes/taiwan.txt (the summary, and every station with what it
answered), probes/taiwan_radio_browser.json (the rows as they came) and
probes/taiwan_streams.json (what each stream answered, by address), which
taiwan.py reads to build the hand-kept list. Nothing else changes.

Radio Browser's licence for the directory itself is not verified here; the
numbers say what is technically possible, not what may be shipped.

Its first run read the same forty bytes of noise as "the record on" at
twenty stations behind one host that serves the audio at every path,
/7.html included; the status route now insists a title be text.

  python3 probe_taiwan.py            every TW station
  python3 probe_taiwan.py 40         the first 40 by votes

Run it from Actions: the sandbox this repository is edited from cannot reach
either Radio Browser or the stations, and reports zero for everything.
"""
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import probe_now_playing as routes

MIRRORS = (
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
)
UA = routes.UA
TIMEOUT = 20
WORKERS = 8

HLS = re.compile(r"\.m3u8(\?|$)", re.I)


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def taiwan_rows():
    """Every station Radio Browser files under Taiwan, from the first mirror that answers."""
    last = None
    for mirror in MIRRORS:
        try:
            rows = get(f"{mirror}/json/stations/bycountrycodeexact/TW?hidebroken=false&order=votes&reverse=true")
            return mirror, rows
        except Exception as e:  # the next mirror
            last = e
    raise SystemExit(f"no Radio Browser mirror answered: {last}")


def head_bytes(url):
    """The first bytes and the headers, for a stream that is not ICY-probed."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.headers, response.read(4096)


def probe(row):
    url = (row.get("url_resolved") or row.get("url") or "").strip()
    out = {"name": row.get("name", "").strip(), "url": url, "hls": bool(HLS.search(url)),
           "reachable": False, "icy": None, "status": None, "content_type": ""}
    if not url.startswith("http"):
        return out
    if out["hls"]:
        try:
            headers, body = head_bytes(url)
            out["content_type"] = headers.get("Content-Type", "")
            out["reachable"] = body.lstrip().startswith(b"#EXTM3U")
        except Exception:
            pass
        return out
    out["icy"] = routes.icy_title(url)
    if out["icy"]:
        out["reachable"] = True
        return out
    try:
        headers, body = head_bytes(url)
        out["content_type"] = headers.get("Content-Type", "")
        out["reachable"] = len(body) > 0
    except Exception:
        return out
    out["status"] = routes.icecast_title(url) or routes.shoutcast_title(url)
    return out


def main():
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    mirror, rows = taiwan_rows()
    if cap:
        rows = rows[:cap]
    with open("probes/taiwan_radio_browser.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(probe, rows))
    with open("probes/taiwan_streams.json", "w", encoding="utf-8") as f:
        json.dump({r["url"]: {k: r[k] for k in ("reachable", "hls", "icy", "status", "content_type")}
                   for r in results if r["url"]}, f, ensure_ascii=False, indent=1)

    total = len(results)
    reachable = [r for r in results if r["reachable"]]
    hls = [r for r in reachable if r["hls"]]
    icy = [r for r in reachable if r["icy"]]
    status = [r for r in reachable if r["status"]]
    nothing = [r for r in reachable if not r["icy"] and not r["status"] and not r["hls"]]

    def pct(n):
        return f"{n:4} ({100 * n / total:.0f}%)" if total else "0"

    print(f"Radio Browser ({mirror}): {total} stations filed under TW, ordered by votes")
    print(f"  reachable now          {pct(len(reachable))}")
    print(f"    HLS playlists        {pct(len(hls))}   play, no title in the stream")
    print(f"    ICY title            {pct(len(icy))}")
    print(f"    status document      {pct(len(status))}")
    print(f"    plays, names nothing {pct(len(nothing))}")
    print(f"  not reachable          {pct(total - len(reachable))}")
    print()
    codecs = Counter((r.get("codec") or "?").upper() for r in rows)
    print("codecs as filed:", ", ".join(f"{c} {n}" for c, n in codecs.most_common()))
    tags = Counter(t.strip() for r in rows for t in (r.get("tags") or "").split(",") if t.strip())
    print("tags as filed:", ", ".join(f"{t} {n}" for t, n in tags.most_common(25)))
    print()
    print("every station, most voted first:")
    for row, r in zip(rows, results):
        route = ("ICY: " + r["icy"]) if r["icy"] else ("status: " + r["status"]) if r["status"] \
            else "HLS, plays" if (r["hls"] and r["reachable"]) else "plays, names nothing" if r["reachable"] \
            else "no answer"
        print(f"  {row.get('votes', 0):5} votes  {r['name'][:38]:38}  {(row.get('codec') or '?'):5} {route[:70]}")


if __name__ == "__main__":
    main()
