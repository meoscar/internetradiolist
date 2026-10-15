#!/usr/bin/env python3
"""One country's stations, from what the probe measured, for a country edition.

taiwan.py does this for Taiwan with a hand-kept exclusion list, because the
owner can read every one of 215 names. For a country edition of the app --
Japan, Spain, Mexico -- nobody here can read two thousand names one by one,
so this keeps what the probe heard and lets the health check take out the
rest over the following nights, the way it does for every other station.

    python3 country_list.py JP                 build and report
    python3 country_list.py JP --apply         write countries/jp.json, and file each under JP in countries.json
    python3 country_list.py MX --keep 400      the four hundred most voted that answer

What is kept per station is what taiwan.json keeps: the name as the
directory has it, the stream, the homepage, the favicon, the tags, the vote
count (which orders the list; it is not an audience), the codec and whether
the stream is HLS. build_catalogue.py reads countries/<cc>.json and puts
every row under the country's own heading, after Taiwan's; check_stations.py
then watches the streams like every other.

Why there is a cap. Radio Browser files three thousand stations under
Mexico. The catalogue is one file every phone downloads, and a heading of
three thousand rows is a list nobody scrolls; the most voted few hundred
that answer are the ones a listener there would name. The cap is an
argument because the right number is a judgment about the country, not a
constant.

Nothing here reaches the network. The two files it reads are written by
probe_country.py, from Actions.
"""
import json
import pathlib
import re
import sys

import taiwan

COUNTRIES = "countries.json"
KEEP = 300

# Rows that are not a station whatever country they are filed under: a test
# row, an address where a name should be, a television feed. The per-country
# exclusions Taiwan needed were about which side of a strait a station
# broadcasts from; nothing automatic can know that, and a country whose
# owner can read the names can write countries/<cc>.exclude.json, a map of
# name to reason, the way taiwan.py carries its own.
NOT_A_STATION = re.compile(r"^(https?://|www\.)|\btest\b|\btelevisi[oó]n\b|\btv\b", re.I)


def excluded(name, by_hand):
    if name in by_hand:
        return by_hand[name]
    if NOT_A_STATION.search(name):
        return "not a radio station, by its name"
    return None


def build(rows, streams, by_hand=None, keep=KEEP):
    """The rows to keep, most voted first, and what was dropped with why."""
    by_hand = by_hand or {}
    kept, dropped = [], []
    seen_streams, seen_names = set(), set()
    ordered = sorted(rows, key=lambda r: -(r.get("votes") or 0))
    for row in ordered:
        name = (row.get("name") or "").strip()
        stream = (row.get("url_resolved") or row.get("url") or "").strip()
        why = excluded(name, by_hand)
        if why:
            pass
        elif not stream.startswith("http"):
            why = "no stream address"
        elif stream in seen_streams:
            why = "the same stream, already kept"
        elif taiwan.name_key(name) in seen_names:
            why = "the same name, already kept"
        elif not (streams.get(stream) or {}).get("reachable"):
            why = "the stream did not answer when probed"
        elif len(kept) >= keep:
            why = f"beyond the {keep} most voted that answer"
        if why:
            dropped.append((name, why))
            continue
        seen_streams.add(stream)
        seen_names.add(taiwan.name_key(name))
        answer = streams.get(stream) or {}
        favicon = (row.get("favicon") or "").strip()
        kept.append({
            "name": name,
            "stream": stream,
            "homepage": (row.get("homepage") or "").strip(),
            "favicon": favicon if favicon.startswith("https://") else "",
            "tags": [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()],
            "votes": int(row.get("votes") or 0),
            "codec": (row.get("codec") or "").strip().upper(),
            "hls": bool(answer.get("hls")),
            "site": "",
        })
    return kept, dropped


def filed_under(countries, kept, code):
    """countries.json with every kept stream filed under the code; nothing else touched."""
    out = dict(countries)
    for station in kept:
        out[station["stream"]] = code
    return out


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args or len(args[0]) != 2:
        print(__doc__)
        return 2
    code = args[0].upper()
    apply_changes = "--apply" in argv
    keep = int(argv[argv.index("--keep") + 1]) if "--keep" in argv else KEEP
    low = code.lower()
    rows = taiwan.load(f"probes/{low}_radio_browser.json", None)
    streams = taiwan.load(f"probes/{low}_streams.json", None)
    if rows is None or streams is None:
        print(f"probes/{low}_radio_browser.json and probes/{low}_streams.json are written by "
              f"probe_country.py {code}, from Actions; run it first")
        return 1
    by_hand = taiwan.load(f"countries/{low}.exclude.json", {})
    kept, dropped = build(rows, streams, by_hand, keep)
    print(f"{len(rows)} rows filed under {code}; {len(kept)} kept, {len(dropped)} dropped")
    reasons = {}
    for _, why in dropped:
        reasons[why] = reasons.get(why, 0) + 1
    for why, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4}  {why}")
    hls = sum(1 for s in kept if s["hls"])
    print(f"\n{hls} of the {len(kept)} kept stream HLS; "
          f"{sum(1 for s in kept if s['favicon'])} carry a favicon; "
          f"{sum(1 for s in kept if s['homepage'])} name a homepage")
    out = f"countries/{low}.json"
    if not apply_changes:
        print(f"\nnothing written; run with --apply to write {out} and file them in {COUNTRIES}")
        return 0
    countries = filed_under(taiwan.load(COUNTRIES, {}), kept, code)
    pathlib.Path("countries").mkdir(exist_ok=True)
    pathlib.Path(out).write_text(
        json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    pathlib.Path(COUNTRIES).write_text(
        json.dumps(countries, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"\nwrote {out}: {len(kept)} stations; {COUNTRIES}: {len(countries)} streams")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
