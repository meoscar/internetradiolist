#!/usr/bin/env python3
"""Watch the three now-playing sources Taiwan's broadcasters turned out to
have, for hours, to learn how they behave over a listening evening.

probe_taiwan_nowplaying.py found them; one look each says what they are,
not what they do. 古典音樂台's XML showed the station's own name as the
"current song" twice; KISS's song list said "no record for this hour" for
the three 城市廣播 stations; M Radio's list is real but its cadence is
unknown. So: every five minutes, for as long as the job may run, read

    古典音樂台 97.7   https://www.family977.com.tw/toXML.xml
    M Radio          https://api.mradio.tw/api/song/get-recent-songs
    KISS's list      songlist.php for 大眾, 台南知音, 南投, 苗栗, this hour
    中廣 流行網        ChannelInfoBat, the programme and DJ on now

and write one line per source per pass. What comes out is whether a song
ever appears, how long it lags, and how often it changes. Written to
probes/taiwan_nowplaying_samples.txt when the job ends.

  python3 sample_taiwan_nowplaying.py 330 5     minutes to run, minutes between passes
"""
import datetime
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "icrtradio-catalogue-sampler/1.0 (+https://github.com/meoscar/internetradiolist)"
TIMEOUT = 20


def get(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(300_000)
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(raw) > 3 and raw[1:2] == b"\x00"):
                return raw.decode("utf-16", "replace")
            return raw.decode("utf-8", "replace")
    except Exception as e:
        return f"ERROR {type(e).__name__}: {str(e)[:60]}"


def taipei_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def family977():
    body = get(f"https://www.family977.com.tw/toXML.xml?t={int(time.time() * 1000)}")
    if body.startswith("ERROR"):
        return body
    fields = {k: (re.search(rf"<{k}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{k}>", body, re.S) or [None, ""])[1].strip()
              for k in ("Startime", "title", "composer", "artist", "album", "duration")}
    return " | ".join(f"{k}={v}" for k, v in fields.items())


def mradio():
    body = get("https://api.mradio.tw/api/song/get-recent-songs?nocache=" + str(int(time.time())))
    if body.startswith("ERROR"):
        return body
    try:
        days = json.loads(body)["data"]
        songs = days[0]["songs"][:3]
        return f"{days[0]['date']} " + " ; ".join(f"{s['time']} {s['artist']} - {s['name']}" for s in songs)
    except Exception as e:
        return f"unreadable: {type(e).__name__} {body[:80]}"


def kiss(station):
    now = taipei_now()
    query = urllib.parse.urlencode({"tp": station, "ty": now.year, "tm": f"{now.month:02d}",
                                    "td": f"{now.day:02d}", "th": f"{now.hour:02d}"})
    body = get("https://www.kiss.com.tw/m/songlist.php?" + query)
    if body.startswith("ERROR"):
        return body
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
    if "並沒有紀錄" in plain:
        return "no record for this hour"
    rows = re.findall(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})\s+(.{1,60}?)(?=\s+\d{4}/\d{2}/\d{2} \d{2}:\d{2}|\s*$)", plain[plain.find("線上收聽"):])
    if rows:
        return f"{len(rows)} rows; last: " + " ; ".join(f"{t} {s.strip()}" for t, s in rows[-2:])
    i = plain.find("google_ad_height = 280;")
    return "unparsed: " + plain[i + 24:i + 160] if i >= 0 else "unparsed: " + plain[-160:]


def bcc():
    body = get("https://www.bcc.com.tw/webapi/BCCRadioWebAPI/ChannelInfoBat")
    if body.startswith("ERROR"):
        return body
    try:
        rows = json.loads(body)
        return " ; ".join(f"{r['name']}: {r.get('program', '')} {r.get('time', '')} DJ:{r.get('dj', '')} ({r.get('SecondsToExpire')}s)"
                          for r in rows[:3])
    except Exception as e:
        return f"unreadable: {type(e).__name__} {body[:80]}"


def main(argv):
    minutes = int(argv[1]) if len(argv) > 1 else 330
    every = int(argv[2]) if len(argv) > 2 else 5
    end = time.time() + minutes * 60
    print(f"Sampling every {every} min for {minutes} min; times are Taipei")
    passes = 0
    while True:
        stamp = taipei_now().strftime("%m-%d %H:%M")
        print(f"\n[{stamp}]")
        print(f"  family977  {family977()}")
        print(f"  mradio     {mradio()}")
        for station in ("KISS", "TAINAN", "NANTOU", "MIAOLI"):
            print(f"  kiss {station:7} {kiss(station)}")
        print(f"  bcc        {bcc()}")
        sys.stdout.flush()
        passes += 1
        if time.time() + every * 60 > end:
            break
        time.sleep(every * 60)
    print(f"\n{passes} passes")


if __name__ == "__main__":
    main(sys.argv)
