import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from afterglow import DEFAULTS, FRAME_BYTES, Handler, Session
from palette import BLACK, HEIGHT, PLACEMENTS, WIDTH, extract_colors, extract_palettes, matte_bounds


def raw_frame(pixel):
    return bytes(value for y in range(HEIGHT) for x in range(WIDTH) for value in pixel(x, y))


class PaletteTests(unittest.TestCase):
    def test_compressed_letterbox_subtitles_and_asymmetry(self):
        def pixel(x, y):
            if 3 <= y < HEIGHT - 5:
                return 86, 91, 110
            if y == HEIGHT - 3 and 10 <= x < 25:
                return 200, 200, 200
            return 24, 23, 24
        pixels = [pixel(x, y) for y in range(HEIGHT) for x in range(WIDTH)]
        self.assertEqual(matte_bounds(pixels), (0, 3, WIDTH, HEIGHT - 5))

    def test_paired_pillarbox_and_dark_frame(self):
        pixels = [(20, 21, 20) if x < 4 or x >= WIDTH - 5 else (71, 70, 68)
                  for y in range(HEIGHT) for x in range(WIDTH)]
        self.assertEqual(matte_bounds(pixels), (4, 0, WIDTH - 5, HEIGHT))
        self.assertEqual(matte_bounds([(13, 15, 20)] * (WIDTH * HEIGHT)), (0, 0, WIDTH, HEIGHT))
        # A gentle ramp out of the shadows is not a visible bar boundary.
        pixels = [(20, 22, 24) if y in (0, HEIGHT - 1) else (30, 32, 34)
                  for y in range(HEIGHT) for x in range(WIDTH)]
        self.assertEqual(matte_bounds(pixels), (0, 0, WIDTH, HEIGHT))

    def test_solid_and_vivid_samples(self):
        neutral = raw_frame(lambda x, y: (145, 145, 145))
        self.assertEqual(extract_colors(neutral, "center", 100), [[145] * 3] * 9)
        mixed = raw_frame(lambda x, y: (220, 15, 15) if 14 <= x <= 21 else (169, 160, 154))
        subdued = extract_colors(mixed, "center", 0)[4]
        vivid = extract_colors(mixed, "center", 100)[4]
        self.assertGreater(vivid[0] - vivid[1], subdued[0] - subdued[1] + 35)
        self.assertEqual(set(extract_palettes(mixed)), set(PLACEMENTS))

    def test_left_and_right_have_independent_palettes(self):
        split = raw_frame(lambda x, y: (205, 0, 0) if x < WIDTH // 2 else (0, 0, 205))
        palettes = extract_palettes(split)
        self.assertEqual(palettes["left"], extract_colors(split, "left"))
        self.assertEqual(palettes["right"], extract_colors(split, "right"))
        self.assertGreater(palettes["left"][4][0], palettes["left"][4][2])
        self.assertGreater(palettes["right"][4][2], palettes["right"][4][0])


class SessionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "settings.json"
        self.session = Session(self.path)

    def test_persistence_and_partial_invalid_settings(self):
        settings = {"placement": "left", "orientation": "portrait", "mirror": False,
                    "boost": False, "level": 62, "vividness": 83}
        self.session.command(settings)
        self.assertEqual(Session(self.path).settings, settings)
        self.path.write_text('{"placement":"right","vividness":101,"level":false}', encoding="utf-8")
        self.assertEqual(Session(self.path).settings, DEFAULTS | {"placement": "right"})
        self.path.write_bytes(b"\xff invalid")
        self.assertEqual(Session(self.path).settings, DEFAULTS)

    def test_incompatible_invalid_or_unsaved_commands_do_not_mutate_state(self):
        for command in ({}, {"vividness": True}, {"level": 9}, {"unknown": False},
                        {"placement": "top"}, {"orientation": []}, {"boost": "on"},
                        {"mode": "record"}, ["demo"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.session.command(command)
        with patch("afterglow.save_settings", side_effect=OSError), self.assertRaises(OSError):
            self.session.command({"mode": "demo", "level": 70})
        self.assertEqual(self.session.settings, DEFAULTS)
        self.assertEqual(self.session.snapshot()["status"], "idle")
        self.assertEqual(self.session.generation, 0)
        self.assertFalse(self.path.exists())

    def test_browser_transitions_and_frame_expiry(self):
        session = self.session
        initial = session.command({"mode": "browser"})
        generation = initial["generation"]
        self.assertEqual(initial["status"], "waiting")
        self.assertFalse(session.frame("browser", generation - 1, "live", b"\xff" * FRAME_BYTES))
        self.assertTrue(session.frame("browser", generation, "live", b"\x80" * FRAME_BYTES))
        live = session.snapshot(dashboard=True)
        self.assertEqual(live["status"], "live")
        self.assertEqual(live["colors"], [[128] * 3] * 9)
        self.assertTrue(session.frame("browser", generation, "live", b"\x80" * FRAME_BYTES))
        self.assertEqual(session.snapshot(dashboard=True)["revision"], live["revision"])
        with patch("afterglow.time.monotonic", return_value=session.last_frame + 2):
            session.expire_browser_frame()
        self.assertEqual(session.snapshot()["status"], "waiting")
        self.assertEqual(session.snapshot()["colors"], BLACK)
        self.assertEqual(session.command({"mode": "idle"})["status"], "idle")
        self.assertFalse(session.frame("browser", generation, "live", b"\xff" * FRAME_BYTES))

    def test_placement_and_vividness_update_existing_frame(self):
        session = self.session
        default = session.command({"mode": "demo"})
        configured = session.command({"placement": "right"})
        self.assertEqual(configured["generation"], default["generation"])
        self.assertNotEqual(configured["colors"], default["colors"])
        after = session.command({"vividness": 100})
        self.assertNotEqual(after["colors"], configured["colors"])
        snapshot = session.snapshot()
        self.assertEqual(snapshot["colors"], snapshot["palettes"]["right"])


class MemoryConnection:
    def __init__(self, request, on_write=None):
        self.input = io.BytesIO(request)
        self.output = bytearray()
        self.on_write = on_write

    def makefile(self, *_):
        return self.input

    def settimeout(self, *_):
        pass

    def setsockopt(self, *_):
        pass

    def sendall(self, data):
        self.output.extend(data)
        if self.on_write is not None:
            self.on_write(data)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.session = Session(Path(folder.name) / "settings.json")
        self.server = SimpleNamespace(session=self.session, server_port=8765,
                                      stopping=threading.Event())

    def request(self, path, *, method="GET", body=b"", headers=None, on_write=None, client="127.0.0.1"):
        headers = {"Host": "127.0.0.1:8765", "Connection": "close", **(headers or {})}
        if method == "POST":
            headers["Content-Length"] = str(len(body))
        lines = [f"{method} {path} HTTP/1.1", *(f"{key}: {value}" for key, value in headers.items())]
        raw = "\r\n".join(lines).encode() + b"\r\n\r\n" + body
        connection = MemoryConnection(raw, on_write)
        Handler(connection, (client, 63012), self.server)
        header_data, content = connection.output.split(b"\r\n\r\n", 1)
        self.assertIn(b"Content-Security-Policy:", header_data)
        self.assertIn(b"script-src 'self'", header_data)
        self.assertIn(b"X-Content-Type-Options: nosniff", header_data)
        return int(header_data.split(b" ", 2)[1]), bytes(content)

    def test_dashboard_stream_pushes_status_and_receiver_changes(self):
        seen = []

        def on_event(data):
            if not data.startswith(b"data: "):
                return
            seen.append(json.loads(data[6:]))
            if len(seen) == 1:
                self.session.command({"mode": "demo"})
            elif len(seen) == 2:
                with self.session.changed:
                    self.session.receivers += 1
                    self.session.publish(light=False)
            else:
                self.server.stopping.set()

        status, _ = self.request("/api/events", on_write=on_event)
        self.assertEqual(status, 200)
        self.assertEqual([state["status"] for state in seen], ["idle", "demo", "demo"])
        self.assertEqual([state["receivers"] for state in seen], [0, 0, 1])
        self.assertEqual([state["revision"] for state in seen], [0, 1, 2])
        self.assertEqual(self.session.dashboards, 0)

    def test_light_pairing_and_stream_disconnect(self):
        self.assertEqual(self.request("/api/light?key=badkey")[0], 403)
        self.assertEqual(self.request("/api/light?key=%C3%A9")[0], 403)
        client = "192.168.0.15"
        self.assertEqual(self.request("/api/events", client=client)[0], 403)
        self.assertEqual(self.request("/api/info", client=client)[0], 404)
        self.assertEqual(self.request("/api/events", headers={"Host": "rebound.local:8765"})[0], 403)

        def disconnect(data):
            if data.startswith(b"data: "):
                self.assertEqual(self.session.receivers, 1)
                raise BrokenPipeError

        status, content = self.request("/api/light?key=" + self.session.code,
                                       on_write=disconnect, client=client)
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(content[6:])["palettes"]), set(PLACEMENTS))
        self.assertEqual(self.session.receivers, 0)
        self.assertEqual(self.session.dashboard_version, 2)
        self.assertEqual(self.session.version, 0)

    def test_local_only_commands_frames_and_new_assets(self):
        command = b'{"mode":"browser","vividness":82}'
        self.assertEqual(self.request("/api/command", method="POST", body=command)[0], 403)
        desktop = {"X-Afterglow": "desktop"}
        self.assertEqual(self.request("/api/command", method="POST", body=command,
                                      headers=desktop | {"Origin": "http://rebound.local:8765"})[0], 403)
        status, content = self.request("/api/command", method="POST", body=command, headers=desktop)
        self.assertEqual(status, 200)
        generation = json.loads(content)["generation"]
        self.assertEqual(json.loads(content)["vividness"], 82)
        self.assertEqual(self.request("/api/frame", method="POST", body=b"bad", headers=desktop)[0], 400)
        pixels = b"\xc0" * FRAME_BYTES
        self.assertEqual(self.request("/api/frame", method="POST", body=pixels,
                                      headers=desktop | {"X-Generation": str(generation)})[0], 204)
        self.assertEqual(json.loads(self.request("/api/status")[1])["status"], "live")
        with patch("afterglow.lan_addresses", return_value=["192.168.0.16"]):
            _, body = self.request("/api/info")
            self.assertEqual(json.loads(body)["addresses"], ["192.168.0.16"])
            self.assertEqual(json.loads(body)["code"], self.session.code)
        for path in ["/", "/light", "/capture.js", "/capture-worker.js", "/pairing-qr.js", "/style.css"]:
            self.assertEqual(self.request(path)[0], 200)


@unittest.skipUnless(sys.platform == "win32", "Windows capture")
class WindowsCaptureTests(unittest.TestCase):
    def test_focus_switch_and_secondary_monitor_fallback(self):
        import windows_capture as capture

        primary = capture.wt.RECT(0, 0, 1920, 1080)
        secondary = capture.wt.RECT(-1080, 0, 0, 1920)

        def desktop(bounds):
            return b"right" if bounds.left == 0 else b"left"

        with patch.object(capture, "fullscreen_window",
                          side_effect=[(10, 1, primary), (11, 1, primary),
                                       (12, 2, secondary), None]), \
                patch.object(capture, "get_foreground", side_effect=[10, 11, 12]), \
                patch.object(capture, "DxgiSampler", side_effect=OSError) as dxgi, \
                patch.object(capture, "GdiSampler") as gdi, capture.DesktopSampler() as sampler:
            gdi.return_value.read.side_effect = desktop
            self.assertEqual(sampler.sample(), ("live", b"right"))
            self.assertEqual(sampler.sample(), ("live", b"right"))
            self.assertEqual(sampler.sample(), ("live", b"left"))
            self.assertEqual(sampler.sample(), ("waiting", None))
            self.assertEqual([call.args for call in dxgi.call_args_list], [(1,), (2,)])

    def test_rotated_surface_coordinates(self):
        import windows_capture as capture

        for rotation, first, last in ((1, (0, 0), (WIDTH - 1, HEIGHT - 1)),
                                      (2, (0, WIDTH - 1), (HEIGHT - 1, 0)),
                                      (3, (WIDTH - 1, HEIGHT - 1), (0, 0)),
                                      (4, (HEIGHT - 1, 0), (0, WIDTH - 1))):
            cells = list(capture.surface_cells(rotation))
            self.assertEqual(len(set(cells)), WIDTH * HEIGHT)
            self.assertEqual((cells[0], cells[-1]), (first, last))
