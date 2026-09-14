#!/usr/bin/env python3
"""Where, if anywhere, Taiwan's broadcasters say what they are playing.

probe_taiwan.py measured the streams: 13 of 156 carry a title, none has a
status document, and the big broadcasters name nothing in the stream. So
the record on, for Taiwan, can only come from what each broadcaster
publishes on its own site, the way ICRT's music log does. This asks.

For each broadcaster below it fetches the homepage and a few pages linked
from it whose address or text suggests a player or a programme, plus the
site's own scripts, and reports three things:

    words     "現正播放", "正在播放", "Now Playing" and their kin, with the
              text around them, which is where a song title would sit
    endpoints addresses in the page or its scripts that look like an API
              (api, json, nowplaying, song, program, onair ...), and what
              a GET on each returned
    embeds    a player hosted elsewhere (hichannel, the Revma relay), which
              means the words live on that host instead

It also listens to the relay streams the big broadcasters use for twenty
metadata blocks rather than the two the first probe read, in case a title
comes late. Nothing is written but probes/taiwan_nowplaying.txt.

Run it from Actions: the sandbox this repository is worked on from cannot
reach any of these sites.
"""
import html
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Mobile Safari/537.36 icrtradio-catalogue-probe")
TIMEOUT = 15
PAGE_LIMIT = 1_500_000
SCRIPT_LIMIT = 400_000
SUBPAGES = 4
SCRIPTS = 6
TRIES = 8
WORKERS = 6

# The broadcasters the listeners vote for, by the sites the directory names
# for them, plus the two hosts that carry many of them.
TARGETS = [
    ("中廣 BCC", ["https://www.bcc.com.tw/"]),
    ("飛碟 UFO", ["https://www.uforadio.com.tw/", "https://www.fm995.com.tw/index.html"]),
    ("Hit FM", ["https://www.hitoradio.com/newweb/onair.php", "https://www.hitoradio.com/"]),
    ("臺北電台", ["http://www.radio.gov.taipei/"]),
    ("古典音樂台 97.7", ["http://www.family977.com.tw/index.php"]),
    ("央廣 RTI", ["https://www.rti.org.tw/"]),
    ("正聲", ["https://www.csbc.com.tw/"]),
    ("城市廣播網", ["http://www.cityfm.tw/"]),
    ("台中廣播 Lucky", ["https://www.fm1007lucky.com/"]),
    ("台北流行音樂 POP", ["https://www.pop917.com/home.aspx"]),
    ("佳音", ["http://www.goodnews.org.tw/"]),
    ("警廣 PBS", ["https://www.pbs.npa.gov.tw/"]),
    ("寶島聯播網", ["https://www.baodaoradio.com.tw/"]),
    ("漢聲", ["https://audio.voh.com.tw/"]),
    ("好事聯播網", ["http://www.bestradio.com.tw/"]),
    ("AsiaFM", ["https://www.asiafm.com.tw/"]),
    ("KISS Radio", ["https://www.kiss.com.tw/"]),
    ("M Radio", ["https://www.mradio.com.tw/"]),
    ("hichannel (中華電信)", ["https://hichannel.hinet.net/radio/index.do"]),
]

# The relay streams: twenty blocks, in case the title comes late.
STREAMS = [
    ("中廣音樂網", "https://n03.rcs.revma.com/ndk05tyy2tzuv"),
    ("中廣流行網", "https://n03.rcs.revma.com/aw9uqyxy2tzuv"),
    ("中廣新聞網", "https://n03.rcs.revma.com/78fm9wyy2tzuv"),
    ("飛碟電台", "https://n10.rcs.revma.com/em90w4aeewzuv"),
    ("飛碟 台中真善美 (icecast)", "http://cast.uforadio.com.tw:8000/tai-stream"),
    ("AsiaFM 亞洲", "https://n13.rcs.revma.com/xpgtqc74hv8uv"),
    ("M Radio", "https://n03.rcs.revma.com/044q61ha7a0uv"),
    ("古典音樂台 97.7", "http://59.120.88.155:8000/live.mp3"),
    ("城市廣播 台南知音", "http://fm971.cityfm.tw:8080/971.mp3"),
    ("台中廣播", "http://211.20.119.101:8081/"),
    ("IC之音", "http://n01a-eu.rcs.revma.com/7mnq8rt7k5zuv"),
]

WORDS = re.compile(r"(現正播放|正在播放|正在播出|現在播放|播放中|即時節目|現正播出|now\s*playing|on\s*air)", re.I)
KEYWORDS = re.compile(r"(api|json|now|playing|song|music|program|schedule|onair|live|current|track|playlist|epg)", re.I)
STATIC = re.compile(r"\.(css|png|jpe?g|gif|svg|woff2?|ttf|ico|mp4|mp3|m3u8|webp|pdf)(\?|$)", re.I)
QUOTED = re.compile(r"""["'](https?://[^"'\s<>]{8,220}|/[^"'\s<>]{4,180})["']""")
SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
LINK = re.compile(r"""<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
IFRAME = re.compile(r"""<(?:iframe|embed|source|audio)[^>]+src=["']([^"']+)["']""", re.I)
TAGS = re.compile(r"<[^>]+>")
PAGE_WORDS = re.compile(r"(onair|on-air|live|listen|player|program|schedule|收聽|節目|播放|即時|線上)", re.I)


def fetch(url, limit=PAGE_LIMIT):
    """(final url, content-type, body text) or (url, error, '')."""
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                                   "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(limit)
            kind = response.headers.get("Content-Type", "")
            charset = "utf-8"
            found = re.search(r"charset=([\w-]+)", kind)
            if found:
                charset = found.group(1)
            elif b"big5" in raw[:3000].lower():
                charset = "big5"
            try:
                text = raw.decode(charset, "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
            return response.geturl(), kind, text
    except urllib.error.HTTPError as e:
        return url, f"HTTP {e.code}", ""
    except Exception as e:
        return url, f"{type(e).__name__}: {str(e)[:80]}", ""


def words_in(text):
    plain = html.unescape(TAGS.sub(" ", text))
    plain = re.sub(r"\s+", " ", plain)
    out = []
    for m in WORDS.finditer(plain):
        a, b = max(0, m.start() - 40), min(len(plain), m.end() + 120)
        out.append(plain[a:b].strip())
        if len(out) >= 6:
            break
    return out


def endpoints_in(text, base):
    seen = []
    for m in QUOTED.finditer(text):
        raw = m.group(1)
        if STATIC.search(raw) or not KEYWORDS.search(raw):
            continue
        full = urllib.parse.urljoin(base, raw)
        if full not in seen:
            seen.append(full)
        if len(seen) >= 25:
            break
    return seen


def same_site(a, b):
    return urllib.parse.urlsplit(a).netloc.split(":")[0].lower().lstrip("www.") == \
        urllib.parse.urlsplit(b).netloc.split(":")[0].lower().lstrip("www.")


def try_get(url):
    final, kind, body = fetch(url, 60_000)
    if not body:
        return f"{kind}"
    snippet = re.sub(r"\s+", " ", TAGS.sub(" ", body) if "html" in kind else body)[:220]
    return f"{kind.split(';')[0]} · {snippet}"


def probe_site(label, starts):
    lines = [f"=== {label}"]
    pages, scripts, endpoints, embeds, words = [], [], [], [], []
    queue = list(starts)
    visited = set()
    while queue and len(pages) < 1 + SUBPAGES + len(starts) - 1:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        final, kind, body = fetch(url)
        if not body:
            lines.append(f"  page {url} -> {kind}")
            continue
        pages.append(final)
        lines.append(f"  page {url} -> {kind.split(';')[0]}, {len(body) // 1000} KB")
        words += [w for w in words_in(body) if w not in words]
        endpoints += [e for e in endpoints_in(body, final) if e not in endpoints]
        for m in IFRAME.finditer(body):
            src = urllib.parse.urljoin(final, m.group(1))
            if src not in embeds and not STATIC.search(src):
                embeds.append(src)
        for m in SCRIPT_SRC.finditer(body):
            src = urllib.parse.urljoin(final, m.group(1))
            if same_site(src, final) and src not in scripts and len(scripts) < SCRIPTS:
                scripts.append(src)
        for m in LINK.finditer(body):
            href, text = urllib.parse.urljoin(final, m.group(1)), TAGS.sub("", m.group(2))
            if href in visited or href in queue or not same_site(href, final):
                continue
            if PAGE_WORDS.search(href) or PAGE_WORDS.search(text):
                queue.append(href)
    for src in scripts:
        _, kind, body = fetch(src, SCRIPT_LIMIT)
        if body:
            endpoints += [e for e in endpoints_in(body, src) if e not in endpoints]
    for w in words[:8]:
        lines.append(f"  words: {w}")
    for e in embeds[:8]:
        lines.append(f"  embed: {e}")
    tried = 0
    for e in endpoints:
        if tried >= TRIES:
            lines.append(f"  ... {len(endpoints) - tried} more endpoint candidates not tried")
            break
        if not re.search(r"(api|json|now|playing|song|onair|program|schedule|current|epg)", e, re.I):
            continue
        tried += 1
        lines.append(f"  GET {e[:120]}\n      -> {try_get(e)}")
    if not words and not embeds and tried == 0:
        lines.append("  nothing that looks like a now-playing source on these pages")
    return "\n".join(lines)


def icy_titles(url, blocks=20):
    """Every distinct title in the first blocks, and how many blocks carried any."""
    sock = None
    try:
        parts = urllib.parse.urlsplit(url)
        https = parts.scheme == "https"
        port = parts.port or (443 if https else 80)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        sock = socket.create_connection((parts.hostname, port), TIMEOUT)
        if https:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
        sock.settimeout(TIMEOUT)
        sock.sendall(f"GET {path} HTTP/1.0\r\nHost: {parts.netloc}\r\nUser-Agent: {UA}\r\nIcy-MetaData: 1\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            chunk = sock.recv(2048)
            if not chunk:
                return "closed before headers"
            buf += chunk
        head, _, body = buf.partition(b"\r\n\r\n")
        found = re.search(rb"icy-metaint:\s*(\d+)", head, re.I)
        if not found:
            names = re.findall(rb"icy-name:\s*([^\r\n]*)", head, re.I)
            return "no metadata channel" + (f" (icy-name {names[0].decode('utf-8', 'replace').strip()})" if names else "")
        interval = int(found.group(1))
        titles, carried = [], 0
        for _ in range(blocks):
            while len(body) < interval + 1:
                chunk = sock.recv(8192)
                if not chunk:
                    return f"stream ended; titles {titles}"
                body += chunk
            length = body[interval] * 16
            while len(body) < interval + 1 + length:
                chunk = sock.recv(8192)
                if not chunk:
                    return f"stream ended; titles {titles}"
                body += chunk
            block = body[interval + 1:interval + 1 + length]
            if length:
                carried += 1
            m = re.search(rb"StreamTitle='(.*?)';", block)
            if m and m.group(1).strip():
                t = m.group(1).decode("utf-8", "replace").strip()
                if t not in titles:
                    titles.append(t)
            body = body[interval + 1 + length:]
        return f"{blocks} blocks read, {carried} carried metadata, titles: {titles or 'none'}"
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:60]}"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def text_of(body, limit=900, after=None):
    plain = re.sub(r"\s+", " ", html.unescape(TAGS.sub(" ", body))).strip()
    if after:
        i = plain.find(after)
        if i >= 0:
            plain = plain[i:]
    return plain[:limit]


def closer_look():
    """The second pass, written after reading the first: where a song title was seen or a poll for one."""
    out = ["=== 古典音樂台 97.7: the function that polls the record on, and what it asks"]
    _, kind, body = fetch("https://www.family977.com.tw/index.php")
    fn = re.search(r"async function updateNowPlaying.*?(?=\n\s*(?:async )?function |updateNowPlaying\(\);)", body, re.S)
    if fn:
        out.append("  " + re.sub(r"\s+", " ", fn.group(0))[:1800])
        asked = re.findall(r"""fetch\(\s*[`"']([^`"']+)""", fn.group(0)) + \
                re.findall(r"""(?:url|src)\s*[:=]\s*[`"']([^`"']+)""", fn.group(0))
        for url in dict.fromkeys(asked):
            full = urllib.parse.urljoin("https://www.family977.com.tw/", url.replace("${timestamp}", "1789474000000"))
            out.append(f"  GET {full[:140]}\n      -> {try_get(full)}")
    else:
        out.append(f"  the function was not found in the page ({kind})")

    out.append("\n=== KISS Radio: the line on the homepage, and the song list page")
    _, kind, body = fetch("https://www.kiss.com.tw/")
    for m in re.finditer(r"(\d{1,2}:\d{2})\s*現在播放[：:]\s*([^<\n]{1,80})", body):
        out.append(f"  homepage says: {m.group(1)} 現在播放：{m.group(2).strip()}")
    for url in ("https://www.kiss.com.tw/service/songlist/", "https://www.kiss.com.tw/show/showtime.php"):
        _, kind, page = fetch(url)
        out.append(f"  {url} -> {kind.split(';')[0]}")
        out.append("      " + text_of(page, 700, after="現在播放"))
        for e in endpoints_in(page, url):
            if re.search(r"(song|play|now|api)", e, re.I) and "kiss.com.tw" in e:
                out.append(f"      endpoint: {e[:140]}")

    out.append("\n=== M Radio: the song history page and what feeds it")
    final, kind, body = fetch("https://www.mradio.com.tw/song-history")
    scripts = [urllib.parse.urljoin(final, m.group(1)) for m in SCRIPT_SRC.finditer(body)]
    found = endpoints_in(body, final)
    for src in [s for s in scripts if same_site(s, final)][:8]:
        _, _, js = fetch(src, SCRIPT_LIMIT)
        found += [e for e in endpoints_in(js, src) if e not in found]
    tried = 0
    for e in found:
        if re.search(r"(api|song|history|play|now)", e, re.I) and "mradio" in e and not STATIC.search(e):
            out.append(f"  GET {e[:140]}\n      -> {try_get(e)}")
            tried += 1
            if tried >= 8:
                break
    if not tried:
        out.append("  no API address in the page or its scripts; the Vue app may build it at runtime")
        out.append("  scripts: " + ", ".join(s[:80] for s in scripts[:6]))

    out.append("\n=== Hit FM: the frames the on-air page embeds")
    for url in ("https://www.hitoradio.com/incInnerNew/innerA.php", "https://www.hitoradio.com/incInnerNew/innerB.php",
                "https://www.hitoradio.com/incInnerNew/innerC.php", "https://www.hitoradio.com/newweb/onair.php"):
        _, kind, page = fetch(url)
        out.append(f"  {url} -> {kind.split(';')[0]}: {text_of(page, 400)}")
        for e in endpoints_in(page, url):
            if re.search(r"(song|now|play|music)", e, re.I) and "hitoradio" in e:
                out.append(f"      endpoint: {e[:140]}")

    out.append("\n=== 中廣 BCC: the on-air page")
    _, kind, page = fetch("http://www.bcc.com.tw/onAir.asp?nid=1")
    out.append("  " + text_of(page, 900))
    for e in endpoints_in(page, "http://www.bcc.com.tw/"):
        if "bcc.com.tw" in e and not STATIC.search(e):
            out.append(f"  endpoint: {e[:140]}")

    out.append("\n=== the two that refused: 央廣 and hichannel")
    for url in ("https://www.rti.org.tw/radio/", "https://www.rti.org.tw/", "http://hichannel.hinet.net/",
                "https://hichannel.hinet.net/radio/index.do"):
        _, kind, page = fetch(url)
        out.append(f"  {url} -> {kind.split(';')[0]}" + (f", {len(page) // 1000} KB" if page else ""))
    return "\n".join(out)


def main():
    print("A closer look, at what the first pass turned up\n")
    print(closer_look())
    print()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        sites = list(pool.map(lambda t: probe_site(*t), TARGETS))
        streams = list(pool.map(lambda s: (s[0], icy_titles(s[1])), STREAMS))
    print("The broadcasters' own sites\n")
    for block in sites:
        print(block)
        print()
    print("The relay streams, listened to for twenty blocks\n")
    for label, answer in streams:
        print(f"  {label:26} {answer}")


if __name__ == "__main__":
    main()
