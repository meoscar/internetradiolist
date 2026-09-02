#!/usr/bin/env python3
"""Point the published catalogue at the logos, and away from the scraped ones.

687 of the 712 rows the app downloads carry an image URL inside
stationPics0719. That folder is 746 files scraped from an image search for each
station's name years ago, and measuring it settles what it is worth: eight
unrelated stations share one identical file, six share another, the largest
entry is 6MB for something drawn at fifty pixels, and two stations share an
identical 857-byte stub.

So each row is repointed at the logo taken from the station's own site, and a
row with no logo has its image cleared rather than left aimed at that folder.
A blank shows the app's placeholder. Showing nothing is honest; showing another
station's picture is not, and that is the complaint this started from.

Matching is by stream URL first and by normalised name second -- the crawl and
the published catalogue overlap on only 167 streams, but many of the rest are
the same station at a URL that has since moved.

The folder itself is not touched. Copies of the app already installed build
those URLs from the station name themselves, and deleting it would empty their
lists with no way to reach them.

  python3 apply_logos.py            say what would change
  python3 apply_logos.py --apply    change it
"""
import json
import pathlib
import re
import sys

CATALOGUES = ["music.json", "music_worldradio.json"]
LOGO_INDEX = "logos.json"
SCRAPED = "stationPics0719"


def normalise(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def items_of(doc):
    if isinstance(doc, list):
        return doc, None, None
    for key in ("music", "stations", "items", "data"):
        if isinstance(doc.get(key), list):
            return doc[key], doc, key
    return [], None, None


def main(argv):
    apply_changes = "--apply" in argv

    index_file = pathlib.Path(LOGO_INDEX)
    if not index_file.exists():
        print(f"{LOGO_INDEX} is not here; run the logo harvest first")
        return 1
    index = json.loads(index_file.read_text(encoding="utf-8"))

    by_stream = {url: entry["logo"] for url, entry in index.items()}
    by_name = {}
    for entry in index.values():
        by_name.setdefault(normalise(entry["name"]), entry["logo"])
    print(f"{len(by_stream)} logos, {len(by_name)} distinct station names\n")

    for name in CATALOGUES:
        path = pathlib.Path(name)
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        rows, container, key = items_of(doc)

        matched_stream = matched_name = cleared = kept = 0
        for row in rows:
            current = (row.get("image") or "").strip()
            logo = by_stream.get((row.get("source") or "").strip())
            if logo:
                matched_stream += 1
            else:
                logo = by_name.get(normalise(row.get("title")))
                if logo:
                    matched_name += 1

            if logo:
                row["image"] = logo
            elif SCRAPED in current:
                # No logo, and what is there came from the image search.
                row["image"] = ""
                cleared += 1
            else:
                kept += 1

        still_scraped = sum(1 for r in rows if SCRAPED in (r.get("image") or ""))
        print(f"{name}: {len(rows)} stations")
        print(f"  {matched_stream:5d}  logo matched by stream URL")
        print(f"  {matched_name:5d}  logo matched by name")
        print(f"  {cleared:5d}  cleared (was a scraped picture, no logo found)")
        print(f"  {kept:5d}  left as they were")
        print(f"  {still_scraped:5d}  still pointing at {SCRAPED}")

        if apply_changes:
            out = rows if container is None else {**container, key: rows}
            path.write_text(
                json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8")
            print(f"  written ({path.stat().st_size:,} bytes)")
        print()

    if not apply_changes:
        print("nothing written -- run with --apply to change the catalogue")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
