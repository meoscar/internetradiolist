"""The ICY handshake, against a server that speaks like a station."""
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import harvest_icy  # noqa: E402


def serve(head, body=b""):
    """One connection answered with head then body, then closed."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def run():
        client, _ = server.accept()
        seen = b""
        while b"\r\n\r\n" not in seen:
            chunk = client.recv(1024)
            if not chunk:
                break
            seen += chunk
        client.sendall(head.encode("latin-1") + body)
        client.close()
        server.close()
    threading.Thread(target=run, daemon=True).start()
    return server.getsockname()[1]


def stream(metaint, title):
    audio = b"a" * metaint
    if title is None:
        return audio + b"\x00"
    text = f"StreamTitle='{title}';".encode()
    blocks = (len(text) + 15) // 16
    return audio + bytes([blocks]) + text.ljust(blocks * 16, b"\x00")


class Interrogate(unittest.TestCase):
    def test_headers_and_the_first_title_are_read_from_an_icy_server(self):
        port = serve("ICY 200 OK\r\nicy-name: Blue Coast FM\r\nicy-genre: Rock\r\nicy-metaint: 32\r\nicy-br: 128\r\n\r\n",
                     stream(32, "Toto - Africa"))
        facts = harvest_icy.interrogate(f"http://127.0.0.1:{port}/stream")
        self.assertTrue(facts["ok"])
        self.assertEqual(facts["icy-name"], "Blue Coast FM")
        self.assertEqual(facts["stream_title"], "Toto - Africa")
        self.assertEqual(facts["icy-br"], "128")

    def test_an_empty_slot_is_an_empty_title(self):
        port = serve("HTTP/1.0 200 OK\r\nicy-metaint: 16\r\n\r\n", stream(16, None))
        self.assertEqual(harvest_icy.interrogate(f"http://127.0.0.1:{port}/")["stream_title"], "")

    def test_a_redirect_is_followed_and_remembered(self):
        target = serve("ICY 200 OK\r\nicy-metaint: 16\r\n\r\n", stream(16, "Chic - Le Freak"))
        port = serve(f"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{target}/live\r\n\r\n")
        facts = harvest_icy.interrogate(f"http://127.0.0.1:{port}/")
        self.assertEqual(facts["stream_title"], "Chic - Le Freak")
        self.assertEqual(facts["resolved"], f"http://127.0.0.1:{target}/live")

    def test_a_refusal_and_a_closed_port_are_recorded_not_raised(self):
        port = serve("HTTP/1.0 404 Not Found\r\n\r\n")
        self.assertEqual(harvest_icy.interrogate(f"http://127.0.0.1:{port}/"), {"ok": False, "error": "HTTP 404"})
        closed = socket.socket(); closed.bind(("127.0.0.1", 0)); p = closed.getsockname()[1]; closed.close()
        facts = harvest_icy.interrogate(f"http://127.0.0.1:{p}/")
        self.assertFalse(facts["ok"])
        self.assertIn("error", facts)


class Retries(unittest.TestCase):
    def test_a_failure_is_tried_again_and_a_success_says_how_many_tries(self):
        answers = iter([{"ok": False, "error": "x"}, {"ok": True}])
        original, sleep = harvest_icy.interrogate, harvest_icy.time.sleep
        harvest_icy.interrogate = lambda url: next(answers)
        harvest_icy.time.sleep = lambda s: None
        try:
            self.assertEqual(harvest_icy.interrogate_with_retries("u"), {"ok": True, "attempts": 2})
        finally:
            harvest_icy.interrogate, harvest_icy.time.sleep = original, sleep

    def test_three_failures_are_the_last_failure(self):
        original, sleep = harvest_icy.interrogate, harvest_icy.time.sleep
        harvest_icy.interrogate = lambda url: {"ok": False, "error": "x"}
        harvest_icy.time.sleep = lambda s: None
        try:
            self.assertEqual(harvest_icy.interrogate_with_retries("u"), {"ok": False, "error": "x", "attempts": 3})
        finally:
            harvest_icy.interrogate, harvest_icy.time.sleep = original, sleep


class Main(unittest.TestCase):
    def test_every_stream_in_the_catalogues_is_asked_once_and_the_facts_carry_its_title(self):
        original = harvest_icy.interrogate_with_retries
        harvest_icy.interrogate_with_retries = lambda url: {"ok": True, "icy-genre": "Rock", "stream_title": "X"}
        was = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                pathlib.Path("music.json").write_text(json.dumps({"music": [
                    {"source": "http://a/stream", "title": "A"}, {"source": "http://a/stream", "title": "A again"},
                    {"source": "", "title": "no stream"}]}))
                harvest_icy.main(["harvest_icy.py", "music.json", "missing.json"])
                facts = json.loads(pathlib.Path("station_facts.json").read_text())
                self.assertEqual(list(facts), ["http://a/stream"])
                self.assertEqual(facts["http://a/stream"]["title"], "A")
            finally:
                os.chdir(was)
                harvest_icy.interrogate_with_retries = original

    def test_items_of_reads_every_shape_a_catalogue_takes(self):
        self.assertEqual(harvest_icy.items_of([1]), [1])
        self.assertEqual(harvest_icy.items_of({"stations": [2]}), [2])
        self.assertEqual(harvest_icy.items_of({"x": 1}), [])


if __name__ == "__main__":
    unittest.main()
