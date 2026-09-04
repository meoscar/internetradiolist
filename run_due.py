#!/usr/bin/env python3
"""Dispatch whichever scheduled job is overdue, one per call.

GitHub's cron is best-effort and this repository gets about fifteen percent of
its slots. Measured over a hundred runs: the hourly pass fired seven times in
two days instead of forty-eight, and the four weekly jobs -- the chain that
rebuilds the catalogue the app downloads -- did not fire on schedule once.
Re-enabling Actions, toggling the workflow off and on, and pushing commits that
touch the file all changed nothing, because none of them is the problem.

So this stops asking for a time and starts asking a question. The hourly pass
is the one trigger that still fires, several times a day; every run of it ends
by calling this, which looks at when each other job last succeeded and starts
the one that is furthest past due. An unreliable clock becomes a heartbeat, and
"has it been seven days" is a question a heartbeat can answer reliably even
when it beats irregularly.

One per call, in chain order, because the weekly four depend on each other:
asking the stations comes before crawling the directory, which comes before
harvesting logos, which comes before building the catalogue. Dispatching all
four at once would run them in whatever order the runners happened to start.
At three or four heartbeats a day the whole chain still completes inside two.

  python3 run_due.py            start the most overdue job, if any
  python3 run_due.py --dry-run  say what it would start
  python3 run_due.py --force    start the first in the chain regardless

--force exists to exercise the dispatch. Reading when a job last succeeded and
starting one are different permissions and different endpoints, and on a
repository where nothing happens to be overdue the second is never reached --
so the first real test of it would otherwise be a week from now, silently, with
nobody watching. It starts check-stations, which is the cheapest job here and
harmless to run twice.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "meoscar/internetradiolist")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REF = os.environ.get("GITHUB_REF_NAME", "main")

# In the order they have to run. The first one overdue is the one started, so a
# chain half way through does not get its later steps started before its
# earlier ones. Hours, and the inputs a dispatch needs to behave like the
# scheduled run it is standing in for -- find-countries reports instead of
# writing unless asked, and harvest-logos samples forty stations unless told to
# take them all.
# ("workflow", hours between runs, dispatch inputs, judge_by_success)
#
# The last flag says which question to ask. For a job that either works or
# does not, "when did it last succeed" is right: a failed run must not reset
# the clock, or a job that fails once waits another week before anything
# retries it. The live pass is different -- it holds a runner for five hours
# and a newer firing cancels the older one, so cancellations are its normal
# ending and asking about successes would read it as permanently overdue.
DUE = [
    # First, because a gap here is the only one anybody can see: live.json
    # feeding a screen that says what is playing this minute. Every other job
    # on this list can be a day late without a soul noticing.
    ("live-now.yml", 1, {}, False),
    ("check-stations.yml", 24, {}),
    ("charts.yml", 24, {}),
    ("harvest-icy.yml", 24 * 7, {}),
    ("crawl-directory.yml", 24 * 7, {}),
    ("harvest-logos.yml", 24 * 7, {"limit": "0"}),
    ("build-catalogue.yml", 24 * 7, {"apply": "true"}),
    ("find-countries.yml", 24 * 7, {"apply": "true"}),
]


def call(path, method="GET", body=None):
    request = urllib.request.Request(
        f"{API}/repos/{REPO}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "internetradiolist-run-due",
            **({"Content-Type": "application/json"} if body is not None else {}),
        })
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def in_flight(workflow):
    """Is one already queued or running? Then it is not overdue, whatever the
    clock says -- and dispatching would be worse than pointless, because the
    live pass cancels its own older run when a newer one starts, so a heartbeat
    that ignored this would restart it every few hours for ever."""
    for state in ("queued", "in_progress"):
        try:
            runs = call(f"/actions/workflows/{workflow}/runs"
                        f"?status={state}&per_page=1")["workflow_runs"]
        except urllib.error.HTTPError:
            return False
        if runs:
            return True
    return False


def hours_since(workflow, only_success=True):
    """Age of the newest run, or None if there has never been one."""
    query = "?status=success&per_page=1" if only_success else "?per_page=1"
    try:
        runs = call(f"/actions/workflows/{workflow}/runs{query}")["workflow_runs"]
    except urllib.error.HTTPError as err:
        print(f"  {workflow}: cannot read runs ({err.code})")
        return None
    if not runs:
        return None
    when = datetime.strptime(runs[0]["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    return (datetime.now(timezone.utc) - when.replace(tzinfo=timezone.utc)) \
        .total_seconds() / 3600


def main():
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    if not TOKEN and not dry:
        print("no GITHUB_TOKEN")
        return 1

    overdue = []
    for entry in DUE:
        workflow, every, inputs = entry[0], entry[1], entry[2]
        by_success = entry[3] if len(entry) > 3 else True

        if in_flight(workflow):
            print(f"  {workflow:24s} already running")
            continue

        age = hours_since(workflow, by_success)
        if age is None:
            # Never succeeded, so it is as overdue as anything can be.
            print(f"  {workflow:24s} never succeeded            DUE")
            overdue.append((1e9, workflow, inputs))
            continue
        late = age - every
        state = "DUE" if late > 0 else ""
        print(f"  {workflow:24s} {age:6.1f}h ago, every {every:4d}h  {state}")
        if late > 0:
            overdue.append((late, workflow, inputs))

    if not overdue and force:
        print("\nnothing is overdue; --force starting the first in the chain")
        overdue = [(0, DUE[1][0], DUE[1][2])]
    if not overdue:
        print("\nnothing is overdue")
        return 0

    # Chain order, not lateness: the earliest step in DUE that is overdue.
    order = [entry[0] for entry in DUE]
    _, workflow, inputs = min(overdue, key=lambda row: order.index(row[1]))
    print(f"\nstarting {workflow}"
          + (f" with {inputs}" if inputs else "")
          + (" (dry run)" if dry else ""))
    if dry:
        return 0

    body = {"ref": REF}
    if inputs:
        body["inputs"] = inputs
    try:
        call(f"/actions/workflows/{workflow}/dispatches", "POST", body)
    except urllib.error.HTTPError as err:
        print(f"  dispatch refused: {err.code} {err.read()[:200]!r}")
        return 1
    print("  started")
    return 0


if __name__ == "__main__":
    sys.exit(main())
