#!/usr/bin/env python3
"""Is the album art on the Now Playing screen the right album?

The app shows the station's own now-playing string as the title, and an iTunes
lookup underneath it as the cover, the album, the year and the genre. Those two
come from different places and nothing checks that they agree: the app sends
the whole raw string to iTunes as a search term, asks for one result, and
believes it.

iTunes is a search engine. It nearly always returns something. So a station
ident, an ad break, a show name or a DJ's chatter comes back as a real song by
a real artist, and the screen states it as fact underneath the correct title.

This measures that, on real strings this repository collected from real
stations, and compares it with the fix: split artist from title, ask for
several candidates, and require the answer to actually resemble the question.

  python3 probe_artwork.py                     read titles from live.json
  python3 probe_artwork.py --limit 60          fewer, for a quick look
"""
import argparse
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

ENDPOINT = "https://itunes.apple.com/search"
PAUSE = 0.35          # Apple asks for ~20 calls a minute; this is well under.
TIMEOUT = 10


# ---- what the app does today, transcribed from ArtworkLookup.java ----

BRACKETS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
RUNTIME = re.compile(r"\s+\d{1,2}:\d{2}(:\d{2})?\s*$")
SEPARATORS = re.compile(r"[\-–—|]{2,}")


def normalise(raw):
    if not raw:
        return None
    s = raw.strip()
    marker = s.find("Now Playing : ")
    if marker >= 0:
        s = s[marker + len("Now Playing : "):]
    s = BRACKETS.sub(" ", s)
    s = RUNTIME.sub("", s)
    s = SEPARATORS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 4 or len(s) > 160:
        return None
    low = s.lower()
    if ("advert" in low or "commercial" in low
            or low == "unknown" or "no title" in low):
        return None
    return s


# ---- how well an answer matches the question ----

def words(text):
    """Comparable words: no accents, no punctuation, no filler."""
    flat = unicodedata.normalize("NFKD", text.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    flat = re.sub(r"[^a-z0-9Ѐ-ӿ一-鿿 ]+", " ", flat)
    drop = {"the", "a", "an", "feat", "ft", "and", "de", "la", "le", "el"}
    return {w for w in flat.split() if len(w) > 1 and w not in drop}


def agreement(query, candidate):
    """How much of what the station said appears in what iTunes answered."""
    asked, got = words(query), words(candidate)
    if not asked:
        return 0.0
    return len(asked & got) / len(asked)


def search(term, limit):
    url = (f"{ENDPOINT}?term={urllib.parse.quote(term)}"
           f"&entity=song&limit={limit}")
    request = urllib.request.Request(url, headers={
        "User-Agent": "WorldRadio-Android/probe"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 200:
            return []
        return json.loads(response.read().decode("utf-8")).get("results", [])


def described(hit):
    return f"{hit.get('artistName','')} {hit.get('trackName','')}".strip()


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--source", default="live.json")
    args = parser.parse_args(argv[1:])

    live = json.loads(pathlib.Path(args.source).read_text(encoding="utf-8"))
    titles = [row["track"] for row in live.get("playing", [])]
    if args.limit:
        titles = titles[:args.limit]
    print(f"{len(titles)} now-playing strings, as stations actually sent them\n")

    rejected = kept = 0
    scores = []
    worst = []

    for raw in titles:
        term = normalise(raw)
        if not term:
            rejected += 1
            continue
        kept += 1
        try:
            hits = search(term, 5)
        except Exception as error:                       # noqa: BLE001
            print(f"  ! {term[:50]}: {error}")
            continue
        finally:
            time.sleep(PAUSE)

        if not hits:
            scores.append((term, None, 0.0, None))
            continue

        # What the app does today: results[0], unconditionally.
        today = hits[0]
        score_today = agreement(term, described(today))

        # What it should do: the best of several, and only if it agrees.
        best = max(hits, key=lambda h: agreement(term, described(h)))
        score_best = agreement(term, described(best))

        scores.append((term, today, score_today, best))
        if score_today < 0.5:
            worst.append((term, described(today), score_today,
                          described(best), score_best))

    answered = [s for s in scores if s[1] is not None]
    print(f"{rejected} strings rejected before searching (idents, ads, junk)")
    print(f"{kept} searched, {len(answered)} got an answer from iTunes\n")

    for floor in (0.9, 0.7, 0.5, 0.34):
        good = sum(1 for _, _, s, _ in answered if s >= floor)
        print(f"  agreement >= {floor:.2f}: {good:3d}  "
              f"({good * 100 // max(len(answered), 1)}% of answers)")

    improved = sum(1 for t, _, s, b in answered
                   if b is not None and agreement(t, described(b)) > s)
    print(f"\n  {improved} would be better with the best of five rather than "
          f"the first")
    print(f"  {len(worst)} answers agree with the station's string by less "
          f"than half -- these are the wrong covers\n")

    for term, today, score, better, bscore in worst[:20]:
        print(f"  station said : {term[:58]}")
        print(f"  itunes says  : {today[:58]}   ({score:.2f})")
        if better and bscore > score:
            print(f"  best of five : {better[:58]}   ({bscore:.2f})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
