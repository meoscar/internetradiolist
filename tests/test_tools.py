"""The maintenance tools that run on a schedule, each in a working
directory of its own with the network played by the test."""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import apply_logos  # noqa: E402
import check_stations  # noqa: E402
import crawl_directory as cd  # noqa: E402
import dedupe_stations  # noqa: E402
import find_countries  # noqa: E402
import resolve_streams  # noqa: E402
import run_due  # noqa: E402
import shared_logos  # noqa: E402
import validate_stations  # noqa: E402


class InAWorkingDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.was = os.getcwd()
        self.argv = sys.argv
        os.chdir(self.dir.name)

    def tearDown(self):
        sys.argv = self.argv
        os.chdir(self.was)
        self.dir.cleanup()

    def write(self, name, doc):
        pathlib.Path(name).write_text(json.dumps(doc), encoding="utf-8")

    def read(self, name):
        return json.loads(pathlib.Path(name).read_text(encoding="utf-8"))

    def quietly(self, fn, *args):
        with redirect_stdout(io.StringIO()) as out:
            code = fn(*args)
        return code, out.getvalue()


class Validate(InAWorkingDir):
    def test_a_good_catalogue_passes_and_duplicates_only_warn(self):
        self.write("music.json", {"music": [
            {"title": "A", "source": "http://a/s", "image": "http://a/i", "site": "http://a/"},
            {"title": "A", "source": "http://a/s"}]})
        sys.argv = ["validate_stations.py"]
        code, out = self.quietly(validate_stations.main)
        self.assertEqual(code, 0)
        self.assertIn("警告", out)

    def test_a_missing_source_a_bad_url_and_a_newline_are_errors(self):
        self.write("music.json", {"music": [
            {"title": "A"}, {"title": "B", "source": "ftp://x", "image": "http://a\nb"}, "junk"]})
        sys.argv = ["validate_stations.py", "music.json"]
        code, out = self.quietly(validate_stations.main)
        self.assertEqual(code, 1)
        self.assertIn("缺少必要欄位", out)
        self.assertIn("不是合法網址", out)
        self.assertIn("內含換行", out)
        self.assertIn("不是物件", out)

    def test_a_file_that_is_not_json_or_not_there_or_has_no_stations(self):
        pathlib.Path("bad.json").write_text("{not json", encoding="utf-8")
        pathlib.Path("latin.json").write_bytes(b"\xff\xfe")
        self.write("empty.json", {"nothing": 1})
        for name, expect in (("bad.json", "JSON 解析失敗"), ("latin.json", "UTF-8"),
                             ("missing.json", "檔案不存在"), ("empty.json", "找不到電台陣列")):
            errs, _ = validate_stations.check(name)
            self.assertIn(expect, errs[0], name)
        self.assertEqual(validate_stations.find_items({"x": [{"a": 1}]}), [{"a": 1}])
        sys.argv = ["validate_stations.py"]
        self.assertEqual(self.quietly(validate_stations.main)[0], 1)   # nothing to validate


class CheckStations(InAWorkingDir):
    def setUp(self):
        super().setUp()
        self.original = check_stations.probe

    def tearDown(self):
        check_stations.probe = self.original
        super().tearDown()

    def test_strikes_accumulate_hard_failures_count_double_and_the_dead_are_dropped_on_request(self):
        self.write("music.json", {"music": [
            {"title": "Alive", "source": "http://a/s"}, {"title": "Flaky", "source": "http://b/s"},
            {"title": "Gone", "source": "http://c/s"}]})
        self.write("station_facts.json", {"http://b/s": {"ok": False, "error": "timeout"}})
        answers = {"http://a/s": (True, "audio/mpeg"), "http://b/s": (False, "only 12 bytes"),
                   "http://c/s": (False, "URLError: Connection refused")}
        check_stations.probe = lambda url: (url, *answers[url])
        sys.argv = ["check_stations.py"]
        code, out = self.quietly(check_stations.main)
        self.assertEqual(code, 0)
        health = self.read("health.json")
        self.assertEqual(health["http://a/s"]["consecutive_failures"], 0)
        self.assertEqual(health["http://b/s"]["consecutive_failures"], 2)   # one from the harvest, one tonight
        self.assertEqual(health["http://c/s"]["consecutive_failures"], 2)   # refused counts double
        self.quietly(check_stations.main)
        self.assertEqual(self.read("health.json")["http://c/s"]["consecutive_failures"], 4)
        self.assertIn("would be dropped", self.quietly(check_stations.main)[1])
        sys.argv = ["check_stations.py", "--drop-dead"]
        self.quietly(check_stations.main)
        self.assertEqual([m["title"] for m in self.read("music.json")["music"]], ["Alive"])

    def test_an_hls_playlist_is_a_live_stream_though_it_is_short(self):
        playlist = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=128000\nchunklist.m3u8\n"
        self.assertEqual(check_stations.verdict("application/vnd.apple.mpegurl", playlist), (True, "hls playlist"))
        self.assertEqual(check_stations.verdict("text/plain", b"  \n#EXTM3U\n"), (True, "hls playlist"))
        self.assertEqual(check_stations.verdict("audio/mpeg", b"a" * 4096), (True, "audio/mpeg"))
        self.assertEqual(check_stations.verdict("", b"a" * 4096), (True, "ok"))
        self.assertEqual(check_stations.verdict("audio/mpeg", b"a" * 10), (False, "only 10 bytes"))
        self.assertEqual(check_stations.verdict("text/html", b"<html>" * 1000), (False, "served text/html, not audio"))

    def test_the_probe_reads_a_stream_and_not_a_page(self):
        class Response:
            def __init__(self, body, kind): self.body, self.headers = body, {"Content-Type": kind}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return self.body[:n]
        original = check_stations.urllib.request.urlopen
        try:
            check_stations.urllib.request.urlopen = lambda r, timeout=0: Response(b"a" * 4096, "audio/mpeg")
            self.assertEqual(check_stations.probe("http://a/s")[1:], (True, "audio/mpeg"))
            check_stations.urllib.request.urlopen = lambda r, timeout=0: Response(b"a" * 4096, "text/html")
            self.assertFalse(check_stations.probe("http://a/s")[1])
            check_stations.urllib.request.urlopen = lambda r, timeout=0: Response(b"a" * 10, "audio/mpeg")
            self.assertIn("only 10 bytes", check_stations.probe("http://a/s")[2])
            check_stations.urllib.request.urlopen = lambda r, timeout=0: (_ for _ in ()).throw(OSError("Connection refused"))
            self.assertIn("Connection refused", check_stations.probe("http://a/s")[2])
        finally:
            check_stations.urllib.request.urlopen = original
        self.assertEqual(check_stations.items_of({"other": [{"a": 1}]}), [{"a": 1}])
        self.assertEqual(check_stations.items_of({"x": 1}), [])


class Dedupe(InAWorkingDir):
    def test_the_second_copy_of_a_stream_goes_and_the_original_is_kept_beside_it(self):
        self.write("music.json", {"music": [
            {"title": "A", "source": "http://a/s"}, {"title": "A again", "source": "http://a/s"}, {"title": "no source"}]})
        sys.argv = ["dedupe_stations.py", "music.json"]
        self.assertEqual(self.quietly(dedupe_stations.main)[0], 0)
        self.assertEqual(len(self.read("music.json")["music"]), 3)          # preview only
        sys.argv = ["dedupe_stations.py", "music.json", "--write"]
        self.quietly(dedupe_stations.main)
        self.assertEqual([m["title"] for m in self.read("music.json")["music"]], ["A", "no source"])
        self.assertTrue(pathlib.Path("music.json.bak").exists())
        self.write("list.json", [{"source": "x"}, {"source": "x"}])
        sys.argv = ["dedupe_stations.py", "list.json", "--write"]
        self.quietly(dedupe_stations.main)
        self.assertEqual(self.read("list.json"), [{"source": "x"}])
        sys.argv = ["dedupe_stations.py"]
        self.assertEqual(self.quietly(dedupe_stations.main)[0], 1)


class Countries(InAWorkingDir):
    def test_a_stream_is_the_same_stream_however_it_is_spelled(self):
        k = find_countries.stream_key
        self.assertEqual(k("http://a.example:80/live/"), k("https://A.EXAMPLE/live;stream.nsv"))
        self.assertEqual(k("http://a.example:8000/live/;"), "a.example:8000/live")
        self.assertEqual(k(""), "")
        self.assertEqual(k("http://[::1"), "")
        self.assertEqual(find_countries.name_key("Rádio Nova FM!"), "radionovafm")

    def test_countries_come_by_stream_first_then_by_an_unambiguous_name(self):
        self.write("music_worldradio.json", {"music": [
            {"id": "a", "title": "Blue Coast FM", "source": "http://a/s"},
            {"id": "b", "title": "Night Shift", "source": "http://zzz/s"},
            {"id": "c", "title": "Everywhere Radio", "source": "http://q/s"},
            {"id": "d", "title": "Nobody", "source": "http://n/s"}]})
        rows = [{"countrycode": "us", "name": "Blue Coast FM", "url": "http://a/s"},
                {"countrycode": "GB", "name": "Night Shift", "url": "http://other/s"},
                {"countrycode": "DE", "name": "Everywhere Radio", "url": "http://e1/s"},
                {"countrycode": "FR", "name": "Everywhere Radio", "url": "http://e2/s"},
                {"countrycode": "", "name": "No country", "url": "http://x/s"}]
        original = find_countries.fetch_directory
        find_countries.fetch_directory = lambda: rows
        try:
            code, out = self.quietly(find_countries.main, ["find_countries.py"])
            self.assertEqual(code, 0)
            self.assertFalse(pathlib.Path("countries.json").exists())
            code, out = self.quietly(find_countries.main, ["find_countries.py", "--apply"])
        finally:
            find_countries.fetch_directory = original
        self.assertEqual(self.read("countries.json"), {"a": "US", "b": "GB"})

    def test_the_directory_is_read_page_by_page_and_the_next_server_tried_on_failure(self):
        pages = {("s1", 0): OSError("down"), ("s2", 0): [{"a": 1}] * find_countries.PAGE, ("s2", find_countries.PAGE): [{"b": 2}]}
        original = find_countries.fetch_page

        def fake(server, offset):
            page = pages[(server, offset)]
            if isinstance(page, Exception):
                raise page
            return page
        find_countries.fetch_page = fake
        servers = find_countries.SERVERS
        find_countries.SERVERS = ("s1", "s2")
        try:
            code, rows = None, self.quietly(find_countries.fetch_directory)[0]
            self.assertEqual(len(rows), find_countries.PAGE + 1)
            find_countries.SERVERS = ("s1",)
            with self.assertRaises(SystemExit):
                self.quietly(find_countries.fetch_directory)
        finally:
            find_countries.fetch_page, find_countries.SERVERS = original, servers


class Resolve(InAWorkingDir):
    def test_the_first_url_in_a_playlist(self):
        self.assertEqual(resolve_streams.first_url_in("[playlist]\nFile1=http://a/s\nTitle1=x", "pls"), "http://a/s")
        self.assertEqual(resolve_streams.first_url_in("#EXTM3U\nhttp://b/s\n", "m3u"), "http://b/s")
        self.assertIsNone(resolve_streams.first_url_in("nothing here", "m3u"))

    def test_a_playlist_is_followed_to_its_stream_and_a_chain_is_followed_once_more(self):
        answers = {"http://a/list.pls": (200, {}, "[playlist]\nFile1=http://a/inner.m3u"),
                   "http://a/inner.m3u": (200, {}, "http://a/stream"),
                   "http://r/x.pls": (302, {"location": "http://a/list.pls"}, ""),
                   "http://bad/x.pls": (404, {}, ""), "http://empty/x.m3u": (200, {}, "")}
        original = resolve_streams.fetch
        resolve_streams.fetch = lambda url, deadline, agent=None: answers[url]
        try:
            self.assertEqual(resolve_streams.resolve("http://a/list.pls"), ("http://a/stream", "ok"))
            self.assertEqual(resolve_streams.resolve("http://r/x.pls"), ("http://a/stream", "ok"))
            self.assertEqual(resolve_streams.resolve("http://bad/x.pls"), (None, "HTTP 404"))
            self.assertEqual(resolve_streams.resolve("http://empty/x.m3u"), (None, "no URL inside the playlist"))
            self.assertEqual(resolve_streams.resolve("http://nowhere/x.pls")[0], None)
        finally:
            resolve_streams.fetch = original

    def test_the_directory_is_rewritten_with_what_the_playlists_pointed_at(self):
        self.write("directory.json", [
            {"name": "A", "stream": "http://a/list.pls", "needs_resolving": True},
            {"name": "B", "stream": "http://b/list.pls", "needs_resolving": True},
            {"name": "C", "stream": "http://c/stream"}])
        original = resolve_streams.resolve
        resolve_streams.resolve = lambda url, agent=None: (("http://a/stream", "ok") if "a/" in url else (None, "ConnectionResetError: Reset by peer"))
        try:
            code, out = self.quietly(resolve_streams.main, ["resolve_streams.py", "directory.json"])
        finally:
            resolve_streams.resolve = original
        self.assertEqual(code, 0)
        rows = {r["name"]: r for r in self.read("directory.json")}
        self.assertEqual((rows["A"]["stream"], rows["A"]["playlist"]), ("http://a/stream", "http://a/list.pls"))
        self.assertNotIn("needs_resolving", rows["A"])
        self.assertIn("resolve_error", rows["B"])
        self.write("directory.json", [{"name": "C", "stream": "http://c/stream"}])
        self.assertEqual(self.quietly(resolve_streams.main, ["resolve_streams.py", "directory.json"])[0], 0)

    def test_the_fetch_reads_an_icy_status_line(self):
        import socket, threading
        server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)

        def run():
            c, _ = server.accept(); c.recv(4096)
            c.sendall(b"ICY 200 OK\r\nContent-Type: audio/x-scpls\r\n\r\n[playlist]\nFile1=http://a/s\n"); c.close(); server.close()
        threading.Thread(target=run, daemon=True).start()
        port = server.getsockname()[1]
        status, headers, body = resolve_streams.fetch(f"http://127.0.0.1:{port}/x.pls", resolve_streams.time.monotonic() + 5)
        self.assertEqual((status, headers["content-type"]), (200, "audio/x-scpls"))
        self.assertIn("File1=http://a/s", body)


class RunDue(InAWorkingDir):
    def setUp(self):
        super().setUp()
        self.original = run_due.call
        self.token = run_due.TOKEN
        self.posted = []
        run_due.TOKEN = "t"

    def tearDown(self):
        run_due.call, run_due.TOKEN = self.original, self.token
        super().tearDown()

    def fake_calls(self, ages, running=()):
        from datetime import datetime, timedelta, timezone

        def call(path, method="GET", body=None):
            if method == "POST":
                self.posted.append((path, body))
                return {}
            workflow = path.split("/workflows/")[1].split("/")[0]
            if "status=queued" in path or "status=in_progress" in path:
                return {"workflow_runs": [{}] if workflow in running and "in_progress" in path else []}
            age = ages.get(workflow)
            if age is None:
                return {"workflow_runs": []}
            when = datetime.now(timezone.utc) - timedelta(hours=age)
            return {"workflow_runs": [{"created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ")}]}
        run_due.call = call

    def test_the_most_overdue_in_chain_order_is_started_and_one_already_running_is_left_alone(self):
        self.fake_calls({w: 0.1 for w, *_ in run_due.DUE} | {"charts.yml": 30, "check-stations.yml": 40},
                        running=("live-now.yml",))
        sys.argv = ["run_due.py"]
        code, out = self.quietly(run_due.main)
        self.assertEqual(code, 0)
        self.assertIn("already running", out)
        self.assertEqual(self.posted, [("/actions/workflows/check-stations.yml/dispatches", {"ref": run_due.REF})])

    def test_a_workflow_that_never_ran_is_due_and_inputs_travel_with_the_dispatch(self):
        self.fake_calls({w: 0.1 for w, *_ in run_due.DUE if w != "build-catalogue.yml"})
        sys.argv = ["run_due.py"]
        self.quietly(run_due.main)
        self.assertEqual(self.posted[0][1], {"ref": run_due.REF, "inputs": {"apply": "true"}})

    def test_nothing_overdue_starts_nothing_unless_forced_and_a_dry_run_never_posts(self):
        self.fake_calls({w: 0.1 for w, *_ in run_due.DUE})
        sys.argv = ["run_due.py"]
        self.assertEqual(self.quietly(run_due.main)[0], 0)
        self.assertEqual(self.posted, [])
        sys.argv = ["run_due.py", "--force", "--dry-run"]
        code, out = self.quietly(run_due.main)
        self.assertIn("dry run", out)
        self.assertEqual(self.posted, [])
        sys.argv = ["run_due.py", "--force"]
        self.quietly(run_due.main)
        self.assertEqual(self.posted[0][0], "/actions/workflows/check-stations.yml/dispatches")

    def test_no_token_is_refused_unless_dry(self):
        run_due.TOKEN = ""
        sys.argv = ["run_due.py"]
        self.assertEqual(self.quietly(run_due.main)[0], 1)


class ApplyLogos(InAWorkingDir):
    def test_logos_are_matched_by_stream_then_by_name_and_scraped_pictures_are_cleared(self):
        self.write("logos.json", {"http://a/s": {"name": "Blue Coast FM", "logo": "https://l/blue.webp"},
                                  "http://n/s": {"name": "Night Shift", "logo": "https://l/night.webp"}})
        self.write("music.json", {"music": [
            {"title": "Blue Coast FM", "source": "http://a/s", "image": "old"},
            {"title": "night shift", "source": "http://other/s", "image": "x"},
            {"title": "Unknown", "source": "http://u/s", "image": "https://x/stationPics0719/u.png"},
            {"title": "Kept", "source": "http://k/s", "image": "https://k/own.png"}]})
        code, out = self.quietly(apply_logos.main, ["apply_logos.py"])
        self.assertEqual(self.read("music.json")["music"][0]["image"], "old")
        code, out = self.quietly(apply_logos.main, ["apply_logos.py", "--apply"])
        rows = self.read("music.json")["music"]
        self.assertEqual([r["image"] for r in rows], ["https://l/blue.webp", "https://l/night.webp", "", "https://k/own.png"])
        self.assertEqual(apply_logos.items_of([1]), ([1], None, None))
        self.assertEqual(apply_logos.items_of({"x": 1}), ([], None, None))

    def test_no_index_is_nothing_to_apply(self):
        self.assertEqual(self.quietly(apply_logos.main, ["apply_logos.py"])[0], 1)


class SharedLogos(InAWorkingDir):
    def test_a_network_is_one_name_at_the_front_or_a_brand_anywhere_or_a_shared_prefix(self):
        self.assertTrue(shared_logos.named_as_one(["Radio Maria Italia", "Radio Maria España"]))
        self.assertTrue(shared_logos.named_as_one(["The Rock FM", "Rock Nation", "Big Rock Radio"]))
        self.assertTrue(shared_logos.named_as_one(["Hitradio Ö3", "Hitradio FFH", "Hitradio RTL"]))
        self.assertFalse(shared_logos.named_as_one(["Blue Coast FM", "Night Shift Radio", "Meridian Gold"]))
        self.assertTrue(shared_logos.named_as_one(["Only one"]))
        self.assertFalse(shared_logos.named_as_one(["", "!!"]))
        self.assertEqual(shared_logos.words("Rádio Nova-FM 2"), ["radio", "nova", "fm"])

    def test_stations_wearing_a_platforms_picture_lose_it_and_a_network_keeps_its(self):
        from PIL import Image
        from find_logos import tile_colour
        pathlib.Path("logos").mkdir()
        platform = Image.new("RGB", (16, 16), (200, 200, 200))
        for x in range(8):
            for y in range(16):
                platform.putpixel((x, y), (20, 20, 20))
        platform.save("logos/p1.png"); platform.save("logos/p2.png"); platform.save("logos/p3.png")
        own = Image.new("RGB", (16, 16), (10, 10, 10))
        for x in range(16):
            for y in range(8):
                own.putpixel((x, y), (240, 240, 240))
        own.save("logos/own.png")
        for n in ("n1", "n2"):
            tile = Image.new("RGB", (16, 16), tile_colour(f"http://{n}/s"))
            for x in range(4, 12):
                for y in range(4, 12):
                    tile.putpixel((x, y), (255, 255, 255))
            tile.save(f"logos/{n}.png")
        index = {
            "http://p1/s": {"name": "Blue Coast FM", "logo": "x/p1.png"},
            "http://p2/s": {"name": "Night Shift Radio", "logo": "x/p2.png"},
            "http://p3/s": {"name": "Meridian Gold", "logo": "x/p3.png"},
            "http://own/s": {"name": "Own Picture", "logo": "x/own.png"},
            "http://n1/s": {"name": "Radio Maria Italia", "logo": "x/n1.png", "from": "small icon on a tile"},
            "http://n2/s": {"name": "Radio Maria España", "logo": "x/n2.png", "from": "small icon on a tile"},
            "http://gone/s": {"name": "Missing File", "logo": "x/none.png"},
        }
        self.write("logos.json", index)
        dropped, kept = shared_logos.shared_pictures(index)
        self.assertEqual(sorted(s for s, _ in dropped), ["http://p1/s", "http://p2/s", "http://p3/s"])
        self.assertEqual(kept, [["Radio Maria Italia", "Radio Maria España"]])
        code, out = self.quietly(shared_logos.main, ["shared_logos.py"])
        self.assertEqual(len(self.read("logos.json")), 7)
        code, out = self.quietly(shared_logos.main, ["shared_logos.py", "--apply"])
        self.assertEqual(sorted(self.read("logos.json")), ["http://gone/s", "http://n1/s", "http://n2/s", "http://own/s"])


class CrawlMain(InAWorkingDir):
    def test_the_crawl_walks_the_genres_and_their_pages_within_its_budget(self):
        base = cd.GENRE_INDEX
        row = lambda name, stream, listeners: (
            f'<tr><td><h4><a href="/station/{name}/">{name}</a></h4>'
            f'<a href="/playlistgenerator/?u={stream}&amp;t=.m3u">p</a></td><td>{listeners} Listeners</td></tr>')
        pages = {
            base: '<a href="/stations/rock/">Rock</a> <a href="/stations/jazz/">Jazz</a> <a href="/stations/rock/">again</a>',
            base + "rock/": row("A", "http%3A%2F%2Fa%2Fs", 10) + row("B", "http%3A%2F%2Fb%2Fs", 5) + '<a href="?page=2">2</a>',
            base + "rock/?page=2": row("C", "http%3A%2F%2Fc%2Fs", 1),
            base + "jazz/": row("A", "http%3A%2F%2Fa%2Fs", 30),
        }
        original = cd.Fetcher.get
        cd.Fetcher.get = lambda self, url: (self.__dict__.__setitem__("made", self.made + 1), pages.get(url))[1]
        try:
            code, out = self.quietly(cd.main, ["crawl_directory.py", "--max-requests", "50"])
        finally:
            cd.Fetcher.get = original
        self.assertEqual(code, 0)
        rows = {r["name"]: r for r in self.read("directory.json")}
        self.assertEqual(set(rows), {"A", "B", "C"})
        self.assertEqual(rows["A"]["genres"], ["jazz", "rock"])
        self.assertEqual(rows["A"]["listeners"], 30)
        self.assertIn("3 stations", out)

    def test_no_index_is_nothing_to_do_and_a_genre_cap_holds(self):
        original = cd.Fetcher.get
        cd.Fetcher.get = lambda self, url: None
        try:
            self.assertEqual(self.quietly(cd.main, ["crawl_directory.py"])[0], 1)
        finally:
            cd.Fetcher.get = original
        cd.Fetcher.get = lambda self, url: '<a href="/stations/a/">a</a><a href="/stations/b/">b</a>' if url == cd.GENRE_INDEX else ""
        try:
            code, out = self.quietly(cd.main, ["crawl_directory.py", "--max-genres", "1"])
            self.assertIn("taking the first 1", out)
        finally:
            cd.Fetcher.get = original


if __name__ == "__main__":
    unittest.main()
