#!/usr/bin/env python3
"""Each broadcaster's weekly schedule, read off its own page into a grid.

programmes.py wants, per station, a week: day 1 (Monday) to 7, each a
list of [from, to, name, host] in "HH:MM". Every broadcaster publishes
that on its site and every site draws it differently: 飛碟 as a list per
weekday, 好事 and Hit FM as a table with rowspans, 亞洲 in a WordPress
timetable, 正聲 as cards with a day and a start. One reader per site,
each tested against a copy of the page kept under probes/schedules/, so
a page that changes shape is found by a test.

    python3 scrape_schedules.py            fetch every page, report
    python3 scrape_schedules.py --apply    also write schedules/<site>.json

Streams are looked up in taiwan.json by the station's name, so the grid
lands on the row the app plays.
"""
import html
import json
import pathlib
import re
import sys
import urllib.request
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Mobile Safari/537.36 icrtradio-catalogue-probe")
TIMEOUT = 20
TAIWAN = "taiwan.json"
OUT_DIR = "schedules"

DAY_WORDS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7,
             "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6, "SUN": 7}


# ---------------------------------------------------------------- helpers

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                                   "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(1_500_000)
        kind = response.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", kind)
        charset = m.group(1) if m else ("big5" if b"big5" in raw[:3000].lower() else "utf-8")
        try:
            return raw.decode(charset, "replace")
        except LookupError:
            return raw.decode("utf-8", "replace")


def text(fragment):
    """The words of a fragment of HTML, one space between them; <br> is a newline."""
    s = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    lines = [re.sub(r"[ \t\r\f\v　]+", " ", line).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def clock(h, m=0):
    return f"{h:02d}:{m:02d}"


def hhmm(s):
    """'7:05', '19:00', '12:00 am', '6:30 PM', '05AM', '12PM' as (h, m); None when it is not a time."""
    s = s.strip().upper()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if h == 12:
            h = 0
        if ap == "PM":
            h += 12
    if not (0 <= h <= 24 and 0 <= mi <= 59):
        return None
    return h, mi


def slot(frm, to, name, host=""):
    return [clock(*frm), clock(*to), name.strip(), host.strip()]


def add(week, day, entry):
    week.setdefault(day, []).append(entry)


def sorted_week(week):
    """Days in order, slots by start; the app reads them in this order."""
    return {str(day): sorted(week[day], key=lambda s: s[0]) for day in sorted(week)}


class Tables(HTMLParser):
    """Every table in a page as rows of cells with their spans and inner HTML.

    Nested tables come out as tables of their own, and the outer cell keeps
    them as part of its inner HTML, which is what the readers want: a cell
    that says "活力DJ" in a table inside a table still says it.
    """

    def __init__(self, page):
        super().__init__(convert_charrefs=False)
        self.page = page
        self.starts = [0] + [m.end() for m in re.finditer(r"\n", page)]
        self.stack = []
        self.tables = []
        self.feed(page)

    def _pos(self):
        line, offset = self.getpos()
        return self.starts[line - 1] + offset

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None, "attrs": dict(attrs), "start": self._pos()})
            return
        if not self.stack:
            return
        t = self.stack[-1]
        if tag == "tr":
            self._close_cell(t)
            t["row"] = []
            t["rows"].append(t["row"])
        elif tag in ("td", "th"):
            if t["row"] is None:
                t["row"] = []
                t["rows"].append(t["row"])
            self._close_cell(t)
            a = dict(attrs)
            t["cell"] = {"rowspan": int(a.get("rowspan") or 1), "colspan": int(a.get("colspan") or 1),
                         "class": a.get("class") or "", "start": self.page.index(">", self._pos()) + 1, "end": None}
            t["row"].append(t["cell"])

    def _close_cell(self, t):
        if t["cell"] is not None and t["cell"]["end"] is None:
            t["cell"]["end"] = self._pos()
        t["cell"] = None

    def handle_endtag(self, tag):
        if not self.stack:
            return
        t = self.stack[-1]
        if tag in ("td", "th"):
            self._close_cell(t)
        elif tag == "tr":
            self._close_cell(t)
            t["row"] = None
        elif tag == "table":
            self._close_cell(t)
            t["end"] = self._pos()
            self.tables.append(self.stack.pop())

    def inner(self, cell):
        return self.page[cell["start"]:cell["end"] if cell["end"] is not None else len(self.page)]

    def html_of(self, table):
        return self.page[table["start"]:table.get("end", len(self.page))]


def grid(rows):
    """Each cell with the row and column it lands on, rowspans and colspans honoured."""
    taken = set()
    placed = []
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in taken:
                c += 1
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    taken.add((r + dr, c + dc))
            placed.append((r, c, cell))
            c += cell["colspan"]
    return placed


# ---------------------------------------------------------------- readers

def ufo(pages):
    """飛碟: one page per weekday (0 Sunday to 6), a list of programmes with a time, a name and a host."""
    week = {}
    for weekday, page in pages.items():
        day = 7 if int(weekday) == 0 else int(weekday)
        for item in re.finditer(r'<li class="program week\d">(.*?)</li>', page, re.S):
            body = item.group(1)
            times = re.search(r'<div class="time">(.*?)</div>', body, re.S)
            name = re.search(r'<div class="name">(.*?)</div>', body, re.S)
            host = re.search(r'<div class="host">(.*?)</div>', body, re.S)
            if not times or not name:
                continue
            stamps = [hhmm(t) for t in text(times.group(1)).split("\n")]
            if len(stamps) < 2 or None in stamps[:2]:
                continue
            add(week, day, slot(stamps[0], stamps[1], text(name.group(1)), text(host.group(1)) if host else ""))
    return sorted_week(week)


# A host written as the last word of the programme: a few characters, Han among them.
HAN_NAME = re.compile(r"^(?=.*[\u4e00-\u9fff])[\u4e00-\u9fffA-Za-z]{1,6}$")


def bestradio(page):
    """好事: a table of three columns (weekdays, Saturday, Sunday), every cell its own hours."""
    tables = Tables(page)
    board = next((t for t in tables.tables if "board-all" in (t["attrs"].get("class") or "")), None)
    if board is None:
        return {}
    week = {}
    columns = {0: [1, 2, 3, 4, 5], 1: [6], 2: [7]}
    for r, c, cell in grid(board["rows"]):
        if r == 0:
            continue
        inner = tables.inner(cell)
        hours = re.search(r'class="DJ-time">\s*(\d{1,2}:\d{2})\s*[~\uff5e-]\s*(\d{1,2}:\d{2})', inner)
        if not hours or 'class="Program"' not in inner:
            continue
        frm, to = hhmm(hours.group(1)), hhmm(hours.group(2))
        if frm is None or to is None:
            continue
        # The hours sit inside the programme's span on some cells and beside
        # it on others, and the host has a span of its own on some cells and
        # is the last word of the programme on others. Take the hours and the
        # host's span out, and what is left is the programme.
        rest = re.sub(r"<!--.*?-->", " ", inner, flags=re.S)
        rest = re.sub(r'<span\s+class="DJ-time">.*?</span>', " ", rest, flags=re.S)
        dj_span = re.search(r'<span\s+class="DJ">(.*?)</span>', rest, re.S)
        host = ""
        if dj_span:
            host = text(dj_span.group(1)).replace("\n", " ").strip()
            rest = rest.replace(dj_span.group(0), " ")
        # A note after the host ("荳子 1530【好事嚴選DJ推薦】...") is not the host.
        host = re.split(r"\s+\d|\u3010", host)[0].strip()
        words = re.split(r"\s+\d{3,4}(?=\D|$)|\u3010", text(rest).replace("\n", " ").strip())[0].strip()
        name = words
        if not host and " " in words:
            head, tail = words.rsplit(" ", 1)
            if HAN_NAME.search(tail):
                name, host = head, tail
        days = []
        for col in range(c, c + cell["colspan"]):
            days += columns.get(col, [])
        for day in days:
            add(week, day, slot(frm, to, name, host))
    return sorted_week(week)


def hitfm(page):
    """Hit FM: the 北部 tab, a table of hours down and days across, spans for length and days."""
    tables = Tables(page)
    head = None
    for t in tables.tables:
        if t["rows"] and "時段" in text(tables.inner(t["rows"][0][0])) if t["rows"][0] else False:
            head = t
            break
    if head is None:
        return {}
    day_of_column = {}
    for c, cell in enumerate(head["rows"][0]):
        word = text(tables.inner(cell)).upper()
        if word in DAY_WORDS:
            day_of_column[c] = DAY_WORDS[word]
    week = {}
    hour_of_row = {}
    for r, c, cell in grid(head["rows"]):
        if c == 0:
            stamp = hhmm(text(tables.inner(cell)))
            if stamp:
                hour_of_row[r] = stamp[0]
    for r, c, cell in grid(head["rows"]):
        if c == 0 or r not in hour_of_row:
            continue
        inner = tables.inner(cell)
        words = text(inner)
        if not words:
            continue
        first = words.split("\n")[0]
        link = re.search(r"<a[^>]*>([^<]+)</a>", inner)
        host = text(link.group(1)).strip() if link else ""
        name = first.split("/")[0].strip() if "/" in first else first.replace(host, "").strip(" -–")
        if not name:
            name = first
        frm = (hour_of_row[r], 0)
        to = (min(hour_of_row[r] + cell["rowspan"], 24), 0)
        for col in range(c, c + cell["colspan"]):
            if col in day_of_column:
                add(week, day_of_column[col], slot(frm, to, name, host))
    return sorted_week(week)


def asiafm(page, tab):
    """亞洲/亞太: a WordPress timetable per station tab, days across, events with their own hours."""
    tables = Tables(page)
    start = page.find(f'id="{tab}"')
    if start < 0:
        return {}
    table = next((t for t in tables.tables if t["start"] > start and "tt_timetable" in (t["attrs"].get("class") or "")), None)
    if table is None:
        return {}
    day_of_column = {}
    for c, cell in enumerate(table["rows"][0]):
        word = text(tables.inner(cell))
        for w, d in DAY_WORDS.items():
            if word.endswith(w) and word.startswith("星期"):
                day_of_column[c] = d
    week = {}
    for r, c, cell in grid(table["rows"][1:]):
        if c == 0 or c not in day_of_column:
            continue
        for event in re.finditer(r'<div class="event_container[^"]*"[^>]*>(.*?)(?=<div class="event_container|<hr>|$)', tables.inner(cell), re.S):
            body = event.group(1)
            title = re.search(r'class="event_header"[^>]*>([^<]*)<', body)
            host = re.search(r"class='before_hour_text'>([^<]*)<", body)
            hours = re.findall(r'class="hours"[^>]*>([^<]*)<', body)
            if not title or len(hours) < 2:
                continue
            frm, to = hhmm(hours[0]), hhmm(hours[1])
            if frm is None or to is None:
                continue
            add(week, day_of_column[c], slot(frm, to, html.unescape(title.group(1)), html.unescape(host.group(1)) if host else ""))
    return sorted_week(week)


def csbc(page):
    """正聲: a section per day, its shows in order with a start; a show ends where the next starts.

    The page writes "am" on every card, the afternoon's included, so the
    half of the day is not read off the card: the cards run in order, and
    the clock turns over once, where an hour is smaller than the one before.
    """
    week = {}
    sections = [(m.group(1), m.start()) for m in re.finditer(r'<div id="([a-z]+)" class="qt-show-schedule-day', page)]
    bounds = [start for _, start in sections] + [len(page)]
    for (_, start), end in zip(sections, bounds[1:]):
        chunk = page[start:end]
        cards = re.findall(r'<h4 class="my-schedule-title">(.*?)</h4>.*?class="my-schedule-time">([^<]*)</span>'
                           r'.*?class="my-schedule-day">([^<]*)<', chunk, re.S)
        if not cards:
            continue
        word = cards[0][2].strip()
        day = DAY_WORDS.get(word[-1]) if word.startswith("週") else None
        if day is None:
            continue
        starts = []
        offset, previous = 0, -1
        for title, stamp, _ in cards:
            when = hhmm(stamp)
            if when is None:
                continue
            hour = when[0] % 12
            if hour < previous:
                offset = 12
            previous = hour
            name = text(title)
            # An hourly card per hour: a two-hour show is two cards with one name.
            if starts and starts[-1][1] == name:
                continue
            starts.append(((hour + offset, when[1]), name))
        for i, (when, title) in enumerate(starts):
            to = starts[i + 1][0] if i + 1 < len(starts) else (24, 0)
            if to == when:
                continue
            add(week, day, slot(when, to, title))
    return sorted_week(week)


# ---------------------------------------------------------------- the sites

SITES = {
    # site: (stations by name in taiwan.json, how to get the grid)
    "ufo": (["飛碟聯播網 飛碟電台"],
            lambda: ufo({str(d): fetch(f"https://www.uforadio.com.tw/schedule?weekday={d}") for d in range(7)})),
    "bestradio-989": (["人人電台 好事聯播網FM98.9"], lambda: bestradio(fetch("http://www.bestradio.com.tw/schedule989.htm"))),
    "bestradio-983": (["好事聯播網 高雄港都", "高雄港都廣播"], lambda: bestradio(fetch("http://www.bestradio.com.tw/schedule983.htm"))),
    "bestradio-935": (["好事聯播網 蓮花電台"], lambda: bestradio(fetch("http://www.bestradio.com.tw/schedule935.htm"))),
    "hitfm": (["Hit FM台北之音廣播"], lambda: hitfm(fetch("https://www.hitoradio.com/newweb/schedule.php"))),
    "asiafm-927": (["AsiaFM 亞洲電台"], lambda: asiafm(fetch("https://www.asiafm.com.tw/program/"), "asia927")),
    "asiafm-923": (["AsiaFM 亞太電台"], lambda: asiafm(fetch("https://www.asiafm.com.tw/program/"), "asia923")),
    "csbc-tpfm": (["正聲廣播電台FM104"], lambda: csbc(fetch("https://www.csbc.com.tw/tpfm"))),
}


def streams_by_name():
    path = pathlib.Path(TAIWAN)
    if not path.exists():
        return {}
    return {s.get("name", ""): s.get("stream", "") for s in json.loads(path.read_text(encoding="utf-8"))}


def main(argv):
    apply_changes = "--apply" in argv
    names = streams_by_name()
    pathlib.Path(OUT_DIR).mkdir(exist_ok=True)
    total = 0
    for site, (stations, read) in SITES.items():
        try:
            week = read()
        except Exception as e:
            print(f"{site}: {type(e).__name__}: {str(e)[:80]}")
            continue
        slots = sum(len(v) for v in week.values())
        streams = [names[n] for n in stations if names.get(n)]
        print(f"{site}: {len(week)} days, {slots} slots -> {len(streams)} station(s)")
        if not slots or not streams:
            continue
        total += len(streams)
        if apply_changes:
            pathlib.Path(OUT_DIR, f"{site}.json").write_text(
                json.dumps({stream: week for stream in streams}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{total} stations with a week" + ("" if apply_changes else "; nothing written without --apply"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
