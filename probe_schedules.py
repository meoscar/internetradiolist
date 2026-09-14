#!/usr/bin/env python3
"""The schedule pages of Taiwan's broadcasters, as they really look.

programmes.json wants a weekly grid per station, and a grid is read out
of each broadcaster's own schedule page by a scraper written against that
page. The scrapers are written and tested here, in a sandbox that cannot
reach any of the pages; so this fetches each page once, from Actions,
and keeps a copy under probes/schedules/ for the scraper's test to read.
A page that changes shape is then found by the test, not by every phone
showing the wrong programme.

Copies are capped at 400 KB. A short README beside them says what each
page answered and shows its first words.
"""
import html
import pathlib
import re
import urllib.request

UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Mobile Safari/537.36 icrtradio-catalogue-probe")
TIMEOUT = 20
CAP = 400_000

PAGES = [
    ("ufo-mon", "https://www.uforadio.com.tw/schedule?weekday=1"),
    ("ufo-sat", "https://www.uforadio.com.tw/schedule?weekday=6"),
    ("ufo-sun", "https://www.uforadio.com.tw/schedule?weekday=0"),
    ("hitfm", "https://www.hitoradio.com/newweb/schedule.php"),
    ("bestradio-989", "http://www.bestradio.com.tw/schedule989.htm"),
    ("bestradio-903", "http://www.bestradio.com.tw/schedule903.htm"),
    ("bestradio-983", "http://www.bestradio.com.tw/schedule983.htm"),
    ("bestradio-935", "http://www.bestradio.com.tw/schedule935.htm"),
    ("csbc-onair", "https://www.csbc.com.tw/onair"),
    ("csbc-tpfm", "https://www.csbc.com.tw/tpfm"),
    ("pbs-folder", "https://www.pbs.npa.gov.tw/ch/app/folder/415"),
    ("taipei", "https://www.radio.gov.taipei/cp.aspx?n=97B61132402830D1"),
    ("mradio", "https://www.mradio.com.tw/program-list"),
    ("kiss", "https://www.kiss.com.tw/show/showtime.php"),
    ("baodao", "https://www.baodaoradio.com.tw/web/programme/programme.jsp?cp_id=CP1640750242622"),
    ("cityfm", "https://cityfm.tw/Client/index.aspx"),
    ("asiafm", "https://www.asiafm.com.tw/program/"),
    ("pop917", "https://www.pop917.com/Program_List.aspx"),
    ("family977", "https://www.family977.com.tw/index.php"),
    ("icrt", "https://www.icrt.com.tw/"),
]


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                                   "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(CAP)
        kind = response.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", kind)
        charset = m.group(1) if m else ("big5" if b"big5" in raw[:3000].lower() else "utf-8")
        try:
            return raw.decode(charset, "replace"), kind
        except LookupError:
            return raw.decode("utf-8", "replace"), kind


def main():
    out = pathlib.Path("probes/schedules")
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for label, url in PAGES:
        try:
            body, kind = fetch(url)
        except Exception as e:
            lines.append(f"{label}: {url}\n    {type(e).__name__}: {str(e)[:80]}\n")
            continue
        (out / f"{label}.html").write_text(body, encoding="utf-8")
        plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)))
        plain = re.sub(r"<[^>]+>", " ", plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        lines.append(f"{label}: {url}\n    {kind.split(';')[0]}, {len(body) // 1000} KB\n    {plain[:600]}\n")
    (out / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
