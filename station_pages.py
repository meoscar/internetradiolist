"""A page each station can link to: "listen to us on Android".

Stations want listeners, and 2,000 of them each have a website with a
"listen" button that goes to a player of their own. This writes one small
page per station, in the app's colours, saying: this station, on Android,
with what it is playing and who the artist is; and a link to the app on
Play. A station that puts that link on its site sends its own listeners to
the app, which is the one kind of marketing that costs nothing and is not
a post.

What a page carries is the station's own name, logo, genre and site, which
the station published itself, and the app's link. Not the catalogue: no
list, no other stations, no counts. This is the line the owner drew between
"a page a station would want" and "somebody else's data as a public site",
and the generator stays on this side of it.

    python3 station_pages.py            # writes for-stations/<slug>.html
    python3 station_pages.py --limit 5  # a few, to look at

Output is not committed and not published by this script. Where to host
the pages, or whether to, is decided by the owner; GitHub Pages on this
repository would serve for-stations/ for nothing.
"""
import argparse
import html
import json
import pathlib
import re

PLAY = "https://play.google.com/store/apps/details?id=com.meoscar.icrtradio"
OUT = pathlib.Path(__file__).parent / "for-stations"


def slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "station"


def page(station):
    name = html.escape(station["title"].split("#")[0].strip())
    genre = html.escape(station.get("genre", "").title())
    logo = html.escape(station.get("image", ""))
    site = html.escape(station.get("site", ""))
    site_line = f'<a href="{site}">{site}</a>' if site else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} on Android</title>
<style>
  body {{ margin:0; background:#0D1117; color:#E9F0F7; font:16px/1.55 Roboto, system-ui, sans-serif; }}
  main {{ max-width:560px; margin:0 auto; padding:56px 24px; text-align:center; }}
  img {{ width:160px; height:160px; border-radius:24px; object-fit:cover; background:#161B22; }}
  h1 {{ font-size:32px; margin:24px 0 6px; letter-spacing:-.02em; }}
  .genre {{ color:#93A2B5; letter-spacing:.08em; text-transform:uppercase; font-size:12px; }}
  p {{ color:#A3B1C2; max-width:36em; margin:20px auto; }}
  .cta {{ display:inline-block; background:#F0AD4E; color:#17120A; font-weight:700; padding:14px 22px;
    border-radius:12px; text-decoration:none; margin-top:8px; }}
  .site {{ margin-top:36px; font-size:13px; }} .site a {{ color:#93A2B5; }}
</style></head>
<body><main>
  {f'<img src="{logo}" alt="">' if logo else ''}
  <h1>{name}</h1>
  <div class="genre">{genre}</div>
  <p>Listen on Android with Nowplay: the song that is playing, who the artist is, and what {name} is playing right now on your home screen.</p>
  <a class="cta" href="{PLAY}">Get Nowplay on Google Play</a>
  <div class="site">{site_line}</div>
</main></body></html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    data = json.load(open(pathlib.Path(__file__).parent / "music_worldradio.json"))
    stations = data["music"] if isinstance(data, dict) else data
    if args.limit:
        stations = stations[:args.limit]
    OUT.mkdir(exist_ok=True)
    seen = set()
    for station in stations:
        s = slug(station["title"])
        n = 2
        while s in seen:
            s = f"{slug(station['title'])}-{n}"
            n += 1
        seen.add(s)
        (OUT / f"{s}.html").write_text(page(station), encoding="utf-8")
    print(f"wrote {len(seen)} pages into {OUT}")


if __name__ == "__main__":
    main()
