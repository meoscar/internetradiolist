#!/usr/bin/env python3
"""Which strings in a station's "now playing" field are not songs.

Measured on the week ending 13 September 2026, before any of this existed:
of the ten most-played "tracks", not one was a record. "Now Playing info
goes here" was first, a station's unfilled template, seen 2,586 times. Then
"RADIO MARIA ITALIA", a station announcing itself in the song field, which
iTunes happened to date to 2015, so it sat at the top of the published chart.
Then "Unknown - Pink Noise", "Asculti Focus FM", a smooth-jazz host's
banner, and a Sikh scripture reading that runs for days.

None of that is a keyword problem, and a keyword list was already there and
did not catch it. Three things do, and all three are measurable:

  THE SHARE. A record is three or four minutes long. A station in the
  heaviest rotation plays its biggest hit eight or ten times a day, which is
  thirty minutes of airtime in twenty-four hours: under three percent of the
  station's passes. This week's real songs bear that out: the median record
  was seen in 0.1% of its stations' passes, the 99th percentile in 1.4%.
  Anything seen in three percent of a station's passes or more is not a
  record the station keeps playing, it is the string the station sends.

  THE STATION'S OWN NAME. Thirty-nine "tracks" this week were the name of
  the station that sent them, or contained it.

  THE SHAPES THAT ARE NEVER A SONG. A web address. A social-media handle.
  An empty or "Unknown" artist. A handful of phrases stations put through
  the song field when they have nothing to say: "top of the hour", "this
  station will continue", "be right back".

Everything here is a pure function; the callers decide what to do with the
answer. accumulate.py does not fold a junk string into the week, and prunes
what the share rule catches once there is enough of it to judge; charts.py
will not rank one; live_now.py does not publish one as a station's song.
"""
import re
import unicodedata

# Seen in this fraction of its stations' passes or more, a string is the
# station's, not a record's. A four-minute record played ten times a day is
# on the air 2.8% of the time, and that is the heaviest rotation there is;
# this week's real songs reached 1.4% at the 99th percentile. Above three
# percent there was nothing honest: a news bulletin, a host's show name, a
# scripture reading, and stations announcing themselves.
CONSTANT_SHARE = 0.03

# Below this many observations the share is one lucky sample, not a rate.
CONSTANT_MIN_PLAYS = 40

# A station name this short (after folding) is too generic to be recognised
# inside a song line: "Radio" or "Hits" would match half the catalogue.
STATION_NAME_MIN = 7

NOT_A_SONG = re.compile(
    r"advert|commercial|jingle|station\s?id|no title|nonstop|non-stop"
    r"|https?://|www\."
    # a bare domain or a social handle
    r"|\b[\w-]+\.(?:com|net|org|eu|info|tv|fm|radio|pl|nl|de|it|ro|uk|hr|gr|rs|fr|es)\b"
    r"|facebook|instagram|tiktok|youtube|twitter|whatsapp"
    # the template a station never filled in, and the things it says instead
    r"|now playing info|top of the hour|will continue|be right back"
    r"|stream(?:ing)? live|live stream",
    re.I)

NOT_AN_ARTIST = {"", "unknown", "unknown artist", "various", "various artists",
                 "va", "artist", "radio", "dj", "host", "live", "live now",
                 "now playing"}


def fold(text):
    """Lower-case, no accents, no punctuation, one space between words."""
    flat = unicodedata.normalize("NFKD", (text or "").lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", flat)).strip()


def names_station(artist, title, station):
    """True when the song line is the station announcing itself."""
    name = fold(station)
    if not name:
        return False
    a, t = fold(artist), fold(title)
    if t == name or a == name:
        return True
    if len(name) < STATION_NAME_MIN:
        return False
    return name in f"{a} {t}"


def junk(artist, title, station=""):
    """True when this song line should not be counted, ranked or shown."""
    title = (title or "").strip()
    if len(title) < 2:
        return True
    line = f"{artist or ''} {title}"
    if NOT_A_SONG.search(line):
        return True
    a = fold(artist)
    if a == "":
        # A line with no artist can still be a song ("Funkytown" alone); the
        # callers that need an artist say so themselves. What an absent
        # artist does rule out is a title that is itself one of the
        # non-artist words: "Live", "Unknown".
        if fold(title) in NOT_AN_ARTIST:
            return True
    elif a in NOT_AN_ARTIST:
        return True
    return names_station(artist, title, station)


def constant(plays, observations):
    """True when a track's share of its stations' passes says it never stops.

    plays: how often the track was seen. observations: how many passes its
    stations answered in the same window, summed over those stations.
    """
    if plays < CONSTANT_MIN_PLAYS or observations <= 0:
        return False
    return plays / observations >= CONSTANT_SHARE


def artist_matches(ours, theirs):
    """Whether the artist a lookup returned is the one we asked about.

    Either name inside the other after folding, or a shared word of four or
    more letters: "Lipps, Inc." and "Lipps Inc" agree, "Radio DeeJay" and
    "Sunset Boys" do not. With no artist of our own there is nothing to
    agree with, and the answer is no.
    """
    a, b = fold(ours), fold(theirs)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    words = lambda s: {w for w in s.split() if len(w) >= 4}
    return bool(words(a) & words(b))
