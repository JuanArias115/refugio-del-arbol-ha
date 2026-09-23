#!/usr/bin/env python3
"""Local guest portal with a fixed Home Assistant authorization boundary."""

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
# Wiring cannot be changed from a dashboard or through this HTTP service.
GUEST_CIRCUITS = (
    {
        "id": "railing-light", "relay": 2, "entity_id": "switch.domo1_rele2",
        "default_title": "Luz baranda", "icon": "fence",
        "visibility_entity": "input_boolean.portal_domo1_baranda",
        "title_entity": "input_text.portal_domo1_nombre_baranda",
    },
    {
        "id": "night-lights", "relay": 6, "entity_id": "switch.domo1_rele6",
        "default_title": "Luces nocheros", "icon": "moon",
        "visibility_entity": "input_boolean.portal_domo1_nocheros",
        "title_entity": "input_text.portal_domo1_nombre_nocheros",
    },
    {
        "id": "bridge-light", "relay": 7, "entity_id": "switch.domo1_rele7",
        "default_title": "Luz puente", "icon": "bridge",
        "visibility_entity": "input_boolean.portal_domo1_puente",
        "title_entity": "input_text.portal_domo1_nombre_puente",
    },
    {
        "id": "external-lights", "relay": 8, "entity_id": "switch.domo1_rele8",
        "default_title": "Luces externas", "icon": "lightbulb",
        "visibility_entity": "input_boolean.portal_domo1_externas",
        "title_entity": "input_text.portal_domo1_nombre_externas",
    },
)
CIRCUITS_BY_ID = {circuit["id"]: circuit for circuit in GUEST_CIRCUITS}


def core_request(path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    """Call Home Assistant through the Supervisor proxy without exposing its token."""
    if not TOKEN:
        raise RuntimeError("Supervisor token is unavailable")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{CORE_API}{path}", data=body, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def all_states() -> dict[str, dict]:
    try:
        states = core_request("/states")
        return {state["entity_id"]: state for state in states if isinstance(state, dict) and "entity_id" in state}
    except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
        print(f"portal: failed to load Home Assistant states: {error}", flush=True)
        return {}


def title_from_state(circuit: dict, states: dict[str, dict]) -> str:
    state = states.get(circuit["title_entity"], {}).get("state", "")
    if not isinstance(state, str) or state in {"", "unknown", "unavailable"}:
        return circuit["default_title"]
    title = " ".join(state.split())[:42]
    return title or circuit["default_title"]


def guest_controls() -> list[dict]:
    """Read display choices from HA helpers while retaining secure default exposure."""
    states = all_states()
    controls = []
    for circuit in GUEST_CIRCUITS:
        visible = states.get(circuit["visibility_entity"], {}).get("state", "on") != "off"
        if visible:
            controls.append({
                "id": circuit["id"], "relay": circuit["relay"],
                "title": title_from_state(circuit, states), "icon": circuit["icon"],
            })
    return controls


def state_for(circuit: dict) -> str:
    try:
        state = core_request(f"/states/{circuit['entity_id']}")
        return state.get("state", "unavailable")
    except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
        print(f"portal: failed to read {circuit['id']}: {error}", flush=True)
        return "unavailable"


def record_guest_action(circuit: dict, requested: bool) -> None:
    """Make guest actions visible in the native Home Assistant logbook."""
    try:
        core_request(
            "/services/logbook/log", method="POST",
            payload={
                "name": "Portal Refugio del Árbol",
                "message": f"{circuit['default_title']}: {'encendido' if requested else 'apagado'} por huésped",
                "entity_id": circuit["entity_id"],
            },
        )
    except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
        print(f"portal: could not write logbook event: {error}", flush=True)


class PortalHandler(SimpleHTTPRequestHandler):
    server_version = "RefugioPortal/2.1"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        print(f"portal: {self.address_string()} {format % args}", flush=True)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/api/config":
            self.respond_json(HTTPStatus.OK, {"controls": guest_controls()})
            return
        if self.path == "/api/status":
            controls = guest_controls()
            self.respond_json(HTTPStatus.OK, {"controls": {control["id"]: state_for(CIRCUITS_BY_ID[control["id"]]) for control in controls}})
            return
        self.serve_static()

    def do_POST(self) -> None:
        prefix = "/api/controls/"
        if not self.path.startswith(prefix):
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return
        control_id = self.path.removeprefix(prefix)
        allowed_ids = {control["id"] for control in guest_controls()}
        if control_id not in allowed_ids:
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Control no permitido"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 256:
                raise ValueError("Solicitud demasiado grande")
            payload = json.loads(self.rfile.read(length) or b"{}")
            desired_state = payload.get("state")
            if not isinstance(desired_state, bool):
                raise ValueError("El estado debe ser booleano")
        except (ValueError, json.JSONDecodeError):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "Solicitud inválida"})
            return
        circuit = CIRCUITS_BY_ID[control_id]
        try:
            core_request(
                f"/services/switch/{'turn_on' if desired_state else 'turn_off'}",
                method="POST", payload={"entity_id": circuit["entity_id"]},
            )
        except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
            print(f"portal: failed to update {control_id}: {error}", flush=True)
            self.respond_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "El dispositivo no responde"})
            return
        record_guest_action(circuit, desired_state)
        self.respond_json(HTTPStatus.OK, {"id": control_id, "state": "on" if desired_state else "off"})

    def do_PUT(self) -> None:
        self.respond_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Método no permitido"})

    def do_DELETE(self) -> None:
        self.respond_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Método no permitido"})

    def serve_static(self) -> None:
        requested = self.path.split("?", 1)[0]
        relative = "index.html" if requested in {"", "/"} else requested.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in candidate.parents or not candidate.is_file():
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return
        self.path = f"/{candidate.relative_to(WEB_ROOT)}"
        super().do_GET()

    def translate_path(self, path: str) -> str:
        return str((WEB_ROOT / path.split("?", 1)[0].lstrip("/")).resolve())

    def respond_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("portal: local guest portal ready", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), PortalHandler).serve_forever()
