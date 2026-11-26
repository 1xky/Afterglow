"""Local desktop capture host and phone light receiver."""

import argparse
import hmac
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import webbrowser

from palette import (BLACK, DEFAULT_VIVIDNESS, HEIGHT, PLACEMENTS, WIDTH,
                     demo_frame, extract_palettes)

WEB = Path(__file__).resolve().with_name("web")
NATIVE = sys.platform == "win32"
POLL = .083
FRAME_BYTES = WIDTH * HEIGHT * 3
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
SETTINGS_PATH = Path(__file__).resolve().with_name("afterglow-settings.json")
DEFAULTS = {"placement": "center", "orientation": "auto", "mirror": True,
            "boost": True, "level": 100, "vividness": DEFAULT_VIVIDNESS}
CHOICES = {"mode": ("idle", "demo", "browser", "windows") if NATIVE
           else ("idle", "demo", "browser"),
           "placement": tuple(PLACEMENTS), "orientation": ("auto", "landscape", "portrait")}
DARK_PALETTES = dict.fromkeys(PLACEMENTS, BLACK)
DEMO_FRAME = demo_frame()
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/light": ("light.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/desktop.js": ("desktop.js", "text/javascript; charset=utf-8"),
    "/capture-worker.js": ("capture-worker.js", "text/javascript; charset=utf-8"),
    "/capture.js": ("capture.js", "text/javascript; charset=utf-8"),
    "/pairing-qr.js": ("pairing-qr.js", "text/javascript; charset=utf-8"),
    "/light.js": ("light.js", "text/javascript; charset=utf-8"),
    "/gradient.js": ("gradient.js", "text/javascript; charset=utf-8"),
}
GUIDES = {f"/guides/{placement}-{orientation}.mp4":
          WEB / "guides" / f"{placement}-{orientation}.mp4"
          for placement in PLACEMENTS for orientation in ("landscape", "portrait")}


def lan_addresses():
    addresses = set()
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            # UDP connect chooses an interface without sending traffic.
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
        except OSError:
            pass
    if NATIVE:
        try:
            output = subprocess.check_output(
                ["ipconfig.exe"], timeout=2, creationflags=subprocess.CREATE_NO_WINDOW)
            addresses.update(
                item.decode() for item in re.findall(
                    rb"IPv4[^:\r\n]*:\s*(\d{1,3}(?:\.\d{1,3}){3})", output))
        except (OSError, subprocess.SubprocessError):
            pass
    usable = []
    for address in addresses:
        parsed = ipaddress.IPv4Address(address)
        if not (parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast):
            usable.append(parsed)
    return [str(address) for address in sorted(usable, key=lambda ip: (ip.is_link_local, ip))]


def open_dashboard(url):
    if sys.platform == "darwin":
        for name in ("Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium"):
            for folder in (Path("/Applications"), Path.home() / "Applications"):
                application = folder / (name + ".app")
                if application.is_dir():
                    subprocess.Popen(["open", "-a", str(application), url])
                    return
    elif sys.platform.startswith("linux"):
        for command in ("google-chrome", "google-chrome-stable", "chromium",
                        "chromium-browser", "brave-browser", "microsoft-edge", "brave"):
            executable = shutil.which(command)
            if executable:
                subprocess.Popen([executable, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    webbrowser.open(url)


def valid_setting(key, value):
    if key in CHOICES:
        return value in CHOICES[key]
    if key in ("mirror", "boost"):
        return type(value) is bool
    minimum = 10 if key == "level" else 0
    return type(value) is int and minimum <= value <= 100


def load_settings(path):
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULTS.copy()
    if not isinstance(saved, dict):
        return DEFAULTS.copy()
    return {key: saved[key] if key in saved and valid_setting(key, saved[key]) else default
            for key, default in DEFAULTS.items()}


def save_settings(path, settings):
    # Write beside the destination so the replacement is atomic on the same filesystem.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".afterglow-", suffix=".tmp", delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(settings, file, indent=2)
            file.write("\n")
            file.close()
            temporary.replace(path)
        finally:
            file.close()
            temporary.unlink(missing_ok=True)


class Session:
    def __init__(self, settings_path=SETTINGS_PATH):
        alphabet = "23456789abcdefghjkmnpqrstuvwxyz"
        self.code = "".join(secrets.choice(alphabet) for _ in range(8))
        self.changed = threading.Condition()
        self.mode = "idle"
        self.status = "idle"
        self.palettes = DARK_PALETTES
        self.raw = None
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.version = 0
        self.dashboard_version = 0
        self.generation = 0
        self.last_frame = 0.0
        self.receivers = 0
        self.dashboards = 0

    def publish(self, light=True):
        if light:
            self.version += 1
        self.dashboard_version += 1
        self.changed.notify_all()

    def snapshot(self, dashboard=False):
        data = {"mode": self.mode, "status": self.status,
                "colors": self.palettes[self.settings["placement"]], **self.settings}
        if dashboard:
            return data | {"receivers": self.receivers, "revision": self.dashboard_version,
                           "generation": self.generation}
        return data | {"palettes": self.palettes}

    def command(self, fields):
        if not isinstance(fields, dict):
            raise ValueError("Expected an object.")
        if fields.keys() - (DEFAULTS.keys() | {"mode"}) or not fields:
            raise ValueError("Unknown setting.")
        for key, value in fields.items():
            if not valid_setting(key, value):
                raise ValueError("Invalid " + key + ".")

        with self.changed:
            settings = self.settings | {key: fields[key] for key in DEFAULTS.keys() & fields.keys()}
            settings_changed = settings != self.settings
            if settings_changed:
                save_settings(self.settings_path, settings)
                vividness_changed = settings["vividness"] != self.settings["vividness"]
                self.settings = settings
                if vividness_changed and "mode" not in fields:
                    raw = DEMO_FRAME if self.mode == "demo" else self.raw
                    if raw is not None:
                        self.palettes = extract_palettes(raw, settings["vividness"])
            if "mode" in fields:
                self.mode = fields["mode"]
                self.generation += 1
                self.last_frame = 0
                self.raw = None
                if self.mode == "demo":
                    self.status = "demo"
                    self.palettes = extract_palettes(DEMO_FRAME, settings["vividness"])
                else:
                    self.status = "idle" if self.mode == "idle" else "waiting"
                    self.palettes = DARK_PALETTES
            if settings_changed or "mode" in fields:
                self.publish()
            return self.snapshot(dashboard=True)

    def capture_config(self):
        with self.changed:
            return self.mode, self.generation

    def frame(self, mode, generation, status, raw=None):
        with self.changed:
            if (mode, generation) != (self.mode, self.generation):
                return False
            if raw is not None:
                self.last_frame = time.monotonic()
            if status == self.status and raw == self.raw:
                return True
            if raw != self.raw:
                self.raw = bytes(raw) if raw is not None else None
                palettes = (extract_palettes(raw, self.settings["vividness"])
                            if raw is not None else DARK_PALETTES)
            else:
                palettes = self.palettes
            if status != self.status or palettes != self.palettes:
                self.status, self.palettes = status, palettes
                self.publish()
            return True

    def expire_browser_frame(self):
        with self.changed:
            if (self.mode == "browser" and self.status == "live"
                    and time.monotonic() - self.last_frame > 1.25):
                self.status, self.raw, self.palettes = "waiting", None, DARK_PALETTES
                self.publish()


def capture_loop(session, stop):
    if not NATIVE:
        while not stop.wait(.2):
            session.expire_browser_frame()
        return
    from windows_capture import DesktopSampler

    while not stop.is_set():
        try:
            with DesktopSampler() as sampler:
                sampled_generation = None
                while not stop.is_set():
                    started = time.monotonic()
                    mode, generation = session.capture_config()
                    if mode == "windows":
                        if generation != sampled_generation:
                            sampler.reset()
                            sampled_generation = generation
                        status, raw = sampler.sample()
                        session.frame(mode, generation, status, raw)
                    else:
                        if sampled_generation is not None:
                            sampler.reset()
                            sampled_generation = None
                        if mode == "browser":
                            session.expire_browser_frame()
                    stop.wait(max(.01, POLL - (time.monotonic() - started)))
        except OSError:
            mode, generation = session.capture_config()
            if mode == "windows":
                session.frame(mode, generation, "unavailable")
            elif mode == "browser":
                session.expire_browser_frame()
            stop.wait(.75)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, settings_path=SETTINGS_PATH):
        self.session = Session(settings_path)
        self.stopping = threading.Event()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass

    def local_request(self):
        host = self.headers.get("Host", "")
        return self.client_address[0] == "127.0.0.1" and host.lower() in {
            f"{name}:{self.server.server_port}" for name in LOCAL_HOSTS}

    def common_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "script-src 'self'; style-src 'self'; connect-src 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")

    def respond(self, status, data=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, data, status=HTTPStatus.OK):
        self.respond(status, json.dumps(data).encode(), "application/json")

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        session = self.server.session
        if path == "/api/status" and self.local_request():
            with session.changed:
                state = session.snapshot(dashboard=True)
            self.json_response(state)
        elif path == "/api/events":
            if self.local_request():
                self.event_stream(dashboard=True)
            else:
                self.respond(HTTPStatus.FORBIDDEN)
        elif path == "/api/info" and self.local_request():
            self.json_response({"windows": NATIVE, "port": self.server.server_port,
                                "addresses": lan_addresses(), "code": session.code,
                                "width": WIDTH, "height": HEIGHT})
        elif path == "/api/light":
            supplied = parse_qs(parsed.query).get("key", [""])[0]
            if supplied.isascii() and hmac.compare_digest(supplied, session.code):
                self.event_stream()
            else:
                self.respond(HTTPStatus.FORBIDDEN)
        elif path in GUIDES and self.local_request():
            self.guide_video(GUIDES[path])
        elif path in STATIC:
            if path == "/" and not self.local_request():
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/light")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            filename, mime = STATIC[path]
            self.respond(HTTPStatus.OK, (WEB / filename).read_bytes(), mime)
        else:
            self.respond(HTTPStatus.NOT_FOUND)

    def do_HEAD(self):
        path = urlsplit(self.path).path
        if path in GUIDES and self.local_request():
            self.guide_video(GUIDES[path], head=True)
        else:
            self.respond(HTTPStatus.NOT_FOUND)

    def guide_video(self, path, head=False):
        try:
            with path.open("rb") as video:
                video.seek(0, 2)
                size = video.tell()
                start, end = 0, size - 1
                status, content_range = HTTPStatus.OK, None
                request_range = re.fullmatch(r"bytes=([0-9]{0,19})-([0-9]{0,19})",
                                             self.headers.get("Range", ""))
                if request_range and any(request_range.groups()):
                    first, last = request_range.groups()
                    if first:
                        start = int(first)
                        if last:
                            end = min(end, int(last))
                    else:
                        start = max(0, size - int(last))
                    if start <= end:
                        status = HTTPStatus.PARTIAL_CONTENT
                        content_range = f"bytes {start}-{end}/{size}"
                    else:
                        status = HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
                        content_range = f"bytes */{size}"
                length = max(0, end - start + 1)
                self.send_response(status)
                self.common_headers()
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if content_range:
                    self.send_header("Content-Range", content_range)
                self.end_headers()
                if length and not head:
                    video.seek(start)
                    self.wfile.write(video.read(length))
        except FileNotFoundError:
            self.respond(HTTPStatus.NOT_FOUND)
        except (ConnectionError, TimeoutError):
            pass

    def do_POST(self):
        origin = self.headers.get("Origin")
        if (not self.local_request() or origin not in
                (None, "http://" + self.headers.get("Host", ""))
                or self.headers.get("X-Afterglow") != "desktop"):
            self.close_connection = True
            self.respond(HTTPStatus.FORBIDDEN)
            return
        session = self.server.session
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= size <= FRAME_BYTES:
                raise ValueError("Invalid body length.")
            body = self.rfile.read(size)
            if self.path == "/api/command":
                try:
                    state = session.command(json.loads(body))
                except OSError:
                    self.json_response({"error": "Could not save Afterglow settings."},
                                       HTTPStatus.INTERNAL_SERVER_ERROR)
                else:
                    self.json_response(state)
            elif self.path == "/api/frame":
                if len(body) != FRAME_BYTES:
                    raise ValueError("Invalid frame.")
                generation = int(self.headers.get("X-Generation", "-1"))
                session.frame("browser", generation, "live", body)
                self.respond(HTTPStatus.NO_CONTENT)
            else:
                self.respond(HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.close_connection = True
            self.json_response({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def event_stream(self, dashboard=False):
        session = self.server.session
        counter = "dashboards" if dashboard else "receivers"
        version = "dashboard_version" if dashboard else "version"
        with session.changed:
            count = getattr(session, counter)
            accepted = count < 12
            if accepted:
                setattr(session, counter, count + 1)
                if not dashboard:
                    session.publish(light=False)
        if not accepted:
            self.respond(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self.close_connection = True
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.send_response(HTTPStatus.OK)
            self.common_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            revision = -1
            while not self.server.stopping.is_set():
                with session.changed:
                    session.changed.wait_for(lambda: revision != getattr(session, version)
                                             or self.server.stopping.is_set(), 2)
                    if self.server.stopping.is_set():
                        break
                    next_revision = getattr(session, version)
                    data = session.snapshot(dashboard) if revision != next_revision else None
                    revision = next_revision
                event = ("data: " + json.dumps(data, separators=(",", ":")) if data is not None
                         else ": keepalive" if dashboard else "event: heartbeat\ndata: {}")
                self.wfile.write((event + "\n\n").encode())
                self.wfile.flush()
        except (ConnectionError, TimeoutError, OSError):
            pass
        finally:
            with session.changed:
                setattr(session, counter, getattr(session, counter) - 1)
                if not dashboard:
                    session.publish(light=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if NATIVE:
        from windows_capture import enable_dpi_awareness
        enable_dpi_awareness()
    try:
        server = Server(("0.0.0.0", args.port))
    except OSError as error:
        raise SystemExit(f"Afterglow could not open port {args.port}. {error}") from error

    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Afterglow is running at {url}\nKeep this window open. Press Ctrl+C to quit.",
          flush=True)
    worker = threading.Thread(target=capture_loop, args=(server.session, server.stopping),
                              daemon=True)
    worker.start()
    try:
        if not args.no_open:
            try:
                open_dashboard(url)
            except OSError:
                print(f"Open {url} in Chrome, Brave, or Edge.", flush=True)
        server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        with server.session.changed:
            server.session.changed.notify_all()
        server.server_close()
        worker.join(2)


if __name__ == "__main__":
    main()
