# internetradiolist

Data for the **Nowplay: Radio World** Android app. Everything here is fetched
by the app at runtime; there is nothing to run and nothing to install.

| | |
|---|---|
| `music_worldradio.json` | The station catalogue the app browses. |
| `countries.json` | Which country each station broadcasts from. |
| `logos/` | Station logos, each taken from that station's own website. |
| `albumsPics/`, `*.png` | The images the browse screen draws. |
| branch `live` → `live.json` | What stations are playing, refreshed through the hour. |
| branch `live` → `charts.json` | What has been measured over the past week. |

The `live` branch is force-pushed and is always one commit deep. Do not branch
from it.

These files are published from a private repository on a schedule. Changes made
here directly will be overwritten.
