#!/usr/bin/env python3
"""Local guest portal with a strictly limited Home Assistant control surface."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PORT = int(os.environ.get("PORT", "8099"))
WEB_ROOT = Path(os.environ.get("WEB_ROOT", "/www")).resolve()
CORE_API = "http://supervisor/core/api"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

# This is the complete authorization boundary for unauthenticated guests.
CONTROLS = {
    "external-lights": {"entity_id": "switch.domo1_rele1", "title": "Luces externas"},
    "night-lights": {"entity_id": "switch.domo1_rele2", "title": "Luces nocheros"},
    "bridge-light": {"entity_id": "switch.domo1_rele3", "title": "Luz puente"},
    "railing-light": {"entity_id": "switch.domo1_rele4", "title": "Luz baranda"},
    "jacuzzi-bubbles": {"entity_id": "switch.domo1_rele5", "title": "Burbujas del jacuzzi"},
}


def core_request(path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    """Call Home Assistant through the Supervisor proxy without exposing its token."""
    if not TOKEN:
        raise RuntimeError("Supervisor token is unavailable")

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{CORE_API}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


class PortalHandler(SimpleHTTPRequestHandler):
    server_version = "RefugioPortal/1.0"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Avoid logging request bodies or headers that could contain private data.
        print(f"portal: {self.address_string()} {format % args}")

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/api/status":
            self.respond_status()
            return
        self.serve_static()

    def do_POST(self) -> None:
        prefix = "/api/controls/"
        if not self.path.startswith(prefix):
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return

        control_id = self.path.removeprefix(prefix)
        if control_id not in CONTROLS:
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Control no permitido"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 256:
                raise ValueError("Solicitud demasiado grande")
            payload = json.loads(self.rfile.read(length) or b"{}")
            desired_state = payload.get("state")
            if not isinstance(desired_state, bool):
                raise ValueError("El estado debe ser booleano")
        except (ValueError, json.JSONDecodeError):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "Solicitud inválida"})
            return

        control = CONTROLS[control_id]
        service = "turn_on" if desired_state else "turn_off"
        try:
            core_request(
                f"/services/switch/{service}",
                method="POST",
                payload={"entity_id": control["entity_id"]},
            )
            state = core_request(f"/states/{control['entity_id']}")
        except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
            print(f"portal: failed to update {control_id}: {error}")
            self.respond_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "El dispositivo no responde"})
            return

        self.respond_json(
            HTTPStatus.OK,
            {"id": control_id, "state": state.get("state", "unavailable")},
        )

    def do_PUT(self) -> None:
        self.respond_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Método no permitido"})

    def do_DELETE(self) -> None:
        self.respond_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Método no permitido"})

    def serve_static(self) -> None:
        requested = self.path.split("?", 1)[0]
        relative = "index.html" if requested in {"", "/"} else requested.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return
        if not candidate.is_file():
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return

        self.path = f"/{candidate.relative_to(WEB_ROOT)}"
        super().do_GET()

    def translate_path(self, path: str) -> str:
        """Keep SimpleHTTPRequestHandler confined to the packaged web root."""
        relative = path.split("?", 1)[0].lstrip("/")
        return str((WEB_ROOT / relative).resolve())

    def respond_status(self) -> None:
        result = {}
        for control_id, control in CONTROLS.items():
            try:
                state = core_request(f"/states/{control['entity_id']}")
                result[control_id] = state.get("state", "unavailable")
            except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
                print(f"portal: failed to read {control_id}: {error}")
                result[control_id] = "unavailable"
        self.respond_json(HTTPStatus.OK, {"controls": result})

    def respond_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("portal: local guest portal ready")
    ThreadingHTTPServer(("0.0.0.0", PORT), PortalHandler).serve_forever()
