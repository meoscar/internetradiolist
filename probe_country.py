#!/usr/bin/env python3
"""How much of one country's radio could this app carry, and how well?

probe_taiwan.py asked this for Taiwan, and the answer became the Taiwan
heading the app opens on. A country edition of the app -- Japan first, or
Mexico first, with its own name and icon on Play -- needs the same answer
for its own country, and there is nothing Taiwanese about the question. So
this is that probe with the country as an argument: every station Radio
Browser files under the code, most voted first, and each stream tried the
way the app would try it.

    python3 probe_country.py JP          every station filed under JP
    python3 probe_country.py MX 400      the four hundred most voted only

It writes probes/<cc>_radio_browser.json (the directory's rows, as they
came) and probes/<cc>_streams.json (what each stream answered), which
country_list.py turns into countries/<cc>.json. Run from Actions: the
sandbox this repository is edited from reaches the directory but not the
stations.

What it measures per stream is what probe_taiwan.py measures: reachable,
HLS, an ICY title, a status document.
"""
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import probe_taiwan as taiwan

WORKERS = taiwan.WORKERS


def rows_for(code):
    """Every station Radio Browser files under the code, from the first mirror that answers."""
    last = None
    for mirror in taiwan.MIRRORS:
        try:
            rows = taiwan.get(f"{mirror}/json/stations/bycountrycodeexact/{code}"
                              "?hidebroken=false&order=votes&reverse=true")
            return mirror, rows
        except Exception as e:  # the next mirror
            last = e
    raise SystemExit(f"no Radio Browser mirror answered: {last}")


def main(argv):
    if len(argv) < 2 or len(argv[1]) != 2:
        print(__doc__)
        return 2
    code = argv[1].upper()
    cap = int(argv[2]) if len(argv) > 2 else None
    mirror, rows = rows_for(code)
    if cap:
        rows = rows[:cap]
    with open(f"probes/{code.lower()}_radio_browser.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(taiwan.probe, rows))
    with open(f"probes/{code.lower()}_streams.json", "w", encoding="utf-8") as f:
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

    print(f"Radio Browser ({mirror}): {total} stations filed under {code}, ordered by votes")
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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
