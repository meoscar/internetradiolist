#!/usr/bin/env python3
"""Drop the pictures that are a platform's, not the station's.

The harvest takes whatever a station's site offers, and a site on a
hosting platform offers the platform's icon: fifty-two stations came back
with one picture, thirty-seven with another, thirty-seven with the
headphones of a streaming host. Dozens of stations sharing one picture is
the exact thing the scraped folder was thrown out for, and the app's own
mark -- two letters on a colour, different for every station -- is the
better answer for all of them.

Two unrelated stations on one picture is already a platform: a broadcaster
with two streams names them as one, and that case is kept below.

A network sharing one picture is not that. PARTY VIBE RADIO's twenty-five
channels, MRG.fm's fifteen, RadioMonster.FM's seven: one broadcaster, one
mark, and the mark is right on every row. The two cases are told apart by
the names. Stations of one network are named as one -- they share a first
word or a prefix -- and stations that merely share a host are not.

Pictures are compared by a perceptual hash, so the same icon served at two
sizes still counts as one. Runs after every harvest, on the whole index.

  python3 shared_logos.py            say what would go
  python3 shared_logos.py --apply    take it out of logos.json
"""
import json
import pathlib
import re
import sys
import unicodedata
from collections import defaultdict

from PIL import Image

LOGO_INDEX = "logos.json"
OUT_DIR = pathlib.Path("logos")
SHARED_BY = 2          # this many stations on one picture is a platform ...
NETWORK_SHARE = 0.6    # ... unless this share of them are named as one


def without_tile(image, station_id):
    """A small icon set on the station's coloured tile, with the tile painted out.

    The tile is the station's own colour, so two stations wearing the same
    platform icon on their tiles hash differently unless the colour goes
    first. Painted black within a tolerance, since WebP is lossy.
    """
    from find_logos import tile_colour
    r, g, b = tile_colour(station_id)
    image = image.convert("RGB")
    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            pr, pg, pb = pixels[x, y]
            if abs(pr - r) <= 10 and abs(pg - g) <= 10 and abs(pb - b) <= 10:
                pixels[x, y] = (0, 0, 0)
    return image


def ahash(path, station_id=None, on_tile=False):
    """64 bits of the picture's shape: which cells are lighter than average."""
    image = Image.open(path)
    if on_tile and station_id:
        image = without_tile(image, station_id)
    image = image.convert("L").resize((8, 8), Image.LANCZOS)
    pixels = list(image.get_flattened_data()) if hasattr(image, "get_flattened_data") \
        else list(image.getdata())
    average = sum(pixels) / len(pixels)
    return "".join("1" if p > average else "0" for p in pixels)


def words(name):
    folded = unicodedata.normalize("NFKD", (name or "").casefold())
    return [w for w in re.split(r"[^a-z0-9]+", folded) if len(w) >= 2]


# Words that name no network: every station is a radio, most are live.
GENERIC = {
    "radio", "fm", "am", "the", "stream", "live", "hd", "music", "station",
    "online", "web", "net", "com", "and", "by", "of", "de", "la", "le", "el",
    "il", "hq", "sq", "lq", "mp3", "aac", "kbps", "kbit", "channel", "hits",
}


def named_as_one(names):
    """Whether these stations read as one network."""
    if len(names) < 2:
        return True
    needed = NETWORK_SHARE * len(names)
    firsts = defaultdict(int)
    anywhere = defaultdict(int)
    for name in names:
        ws = words(name)
        if ws:
            firsts[ws[0]] += 1
        for w in set(ws):
            if len(w) >= 3 and w not in GENERIC:
                anywhere[w] += 1
    if firsts and max(firsts.values()) >= needed:
        return True
    # A brand anywhere in the name: "Mondello Radio (MRG.fm)", "60sRadio (MRG.fm)".
    if anywhere and max(anywhere.values()) >= needed:
        return True
    # A shared prefix that is not a whole word: "beeClassics", "beeRadio".
    folded = ["".join(words(n)) for n in names]
    folded = [f for f in folded if f]
    if not folded:
        return False
    for length in (6, 5):
        prefixes = defaultdict(int)
        for f in folded:
            if len(f) >= length:
                prefixes[f[:length]] += 1
        if prefixes and max(prefixes.values()) >= needed:
            return True
    return False


def shared_pictures(index):
    """Stream URLs whose picture is a platform's: (stream, group names)."""
    by_picture = defaultdict(list)
    for stream, entry in index.items():
        path = OUT_DIR / entry["logo"].rsplit("/", 1)[-1]
        if not path.exists():
            continue
        try:
            key = ahash(path, stream, "on a tile" in entry.get("from", ""))
            by_picture[key].append(stream)
        except Exception:                          # noqa: BLE001
            continue
    dropped, kept = [], []
    for streams in by_picture.values():
        if len(streams) < SHARED_BY:
            continue
        names = [index[s]["name"] for s in streams]
        if named_as_one(names):
            kept.append(names)
        else:
            dropped.extend((s, names) for s in streams)
    return dropped, kept


def main(argv):
    apply_changes = "--apply" in argv
    index_file = pathlib.Path(LOGO_INDEX)
    index = json.loads(index_file.read_text(encoding="utf-8"))

    dropped, kept = shared_pictures(index)
    groups = {}
    for stream, names in dropped:
        groups.setdefault(id(names), names)

    print(f"{len(index)} logos; {len(dropped)} on {len(groups)} platform pictures, "
          f"{len(kept)} networks left alone\n")
    print("platform pictures, and who was wearing them:")
    for names in sorted(groups.values(), key=len, reverse=True):
        print(f"  {len(names):3d}  " + "; ".join(n[:24] for n in names[:5]))
    print("\nnetworks, kept:")
    for names in sorted(kept, key=len, reverse=True):
        print(f"  {len(names):3d}  " + "; ".join(n[:24] for n in names[:4]))

    if apply_changes:
        for stream, _ in dropped:
            index.pop(stream, None)
        index_file.write_text(
            json.dumps(index, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"\n{LOGO_INDEX}: {len(index)} stations have a logo")
    else:
        print("\nnothing written -- run with --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
