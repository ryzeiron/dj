"""Small HTTP server exposing the engine to the browser UI (standard library only)."""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .effects import list_effects
from .engine import Engine
from .fixtures import COLOR_RGB

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


def lan_ip() -> str:
    """Best effort local address, to print a URL usable from a phone."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


class Handler(BaseHTTPRequestHandler):
    engine: Engine
    token: str | None = None
    verbose: bool = False

    server_version = "beamctl"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        if self.verbose:
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) or {}
        except ValueError:
            return {}

    def _authorised(self, query: dict) -> bool:
        if not self.token:
            return True
        given = (query.get("t") or [None])[0]
        if given == self.token:
            return True
        header = self.headers.get("X-Beamctl-Token")
        return header == self.token

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorised(query):
            return self._json({"error": "code d'acces invalide"}, 403)
        path = url.path
        if path.startswith("/api/"):
            return self._api_get(path, query)
        return self._static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if not self._authorised(parse_qs(url.query)):
            return self._json({"error": "code d'acces invalide"}, 403)
        try:
            self._api_post(url.path, self._body())
        except Exception as exc:
            self._json({"error": str(exc)}, 400)

    # -- static files ------------------------------------------------------
    def _static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        target = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not target.startswith(WEB_DIR) or not os.path.isfile(target):
            return self._send(404, b"introuvable", "text/plain; charset=utf-8")
        content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith("javascript"):
            content_type += "; charset=utf-8"
        with open(target, "rb") as handle:
            self._send(200, handle.read(), content_type)

    # -- API ---------------------------------------------------------------
    def _api_get(self, path: str, query: dict) -> None:
        engine = self.engine
        if path == "/api/status":
            return self._json(engine.status())
        if path == "/api/show":
            show = engine.show
            return self._json({
                "config": show.config,
                "fixtures": [f.to_dict() for f in show.sorted_fixtures()],
                "looks": [l.to_dict() for l in show.looks],
                "profiles": show.library.list(),
                "effects": list_effects(),
                "colors": list(COLOR_RGB),
                "conflicts": show.patch_conflicts(),
                "path": show.path,
            })
        return self._json({"error": "route inconnue"}, 404)

    def _api_post(self, path: str, body: dict) -> None:
        engine = self.engine
        show = engine.show

        if path == "/api/master":
            if "dimmer" in body:
                engine.master_dimmer = max(0.0, min(1.0, float(body["dimmer"])))
            if "blackout" in body:
                engine.blackout = bool(body["blackout"])
            if "strobe" in body:
                engine.strobe_momentary = bool(body["strobe"])
            if "strobe_rate" in body:
                engine.strobe_rate = max(1.0, min(25.0, float(body["strobe_rate"])))
            if "freeze" in body:
                engine.freeze = bool(body["freeze"])
            if "solo" in body:
                engine.solo_fixture = body["solo"] or None
            return self._json(engine.status())

        if path == "/api/tempo":
            if body.get("tap"):
                engine.clock.tap()
            if body.get("resync"):
                engine.clock.resync()
            if "bpm" in body:
                engine.clock.set_bpm(float(body["bpm"]))
            if "nudge" in body:
                engine.clock.nudge(float(body["nudge"]))
            show.config["bpm"] = engine.clock.bpm
            return self._json({"bpm": engine.clock.bpm})

        if path == "/api/look/activate":
            ok = engine.activate_look(str(body.get("id", "")))
            return self._json({"ok": ok, "active": engine.active_look_id})

        if path == "/api/look/save":
            look = show.upsert_look(body.get("look") or body)
            show.save()
            return self._json({"look": look.to_dict()})

        if path == "/api/look/delete":
            ok = show.delete_look(str(body.get("id", "")))
            if ok:
                show.save()
            return self._json({"ok": ok})

        if path == "/api/live":
            engine.set_live(body or {})
            return self._json({"live": engine.live})

        if path == "/api/live/clear":
            engine.clear_live()
            return self._json({"live": engine.live})

        if path == "/api/live/store":
            look = engine.store_live_into_look()
            show.save()
            return self._json({"look": look.to_dict() if look else None})

        if path == "/api/patch":
            show.set_patch(body.get("fixtures") or [])
            show.save()
            return self._json({
                "fixtures": [f.to_dict() for f in show.sorted_fixtures()],
                "conflicts": show.patch_conflicts(),
            })

        if path == "/api/output":
            description = engine.set_output(body or {"driver": "dummy"})
            show.save()
            return self._json({"output": description})

        if path == "/api/test":
            if body.get("clear"):
                engine.clear_channel_overrides()
            elif "address" in body:
                value = body.get("value")
                engine.set_channel_override(int(body["address"]),
                                            None if value is None else int(value))
            return self._json({"overrides": engine.channel_overrides})

        if path == "/api/save":
            show.save()
            return self._json({"ok": True, "path": show.path})

        return self._json({"error": "route inconnue"}, 404)


def serve(engine: Engine, host: str = "0.0.0.0", port: int = 8080,
          token: str | None = None, verbose: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,),
                   {"engine": engine, "token": token, "verbose": verbose})
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="http", daemon=True)
    thread.start()
    return httpd
