#!/usr/bin/env python3
"""Guest portal and authenticated Domo 1 administration panel."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GUEST_PORT = int(os.environ.get("PORT", "8099"))
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "8100"))
GUEST_WEB_ROOT = Path(os.environ.get("WEB_ROOT", "/www")).resolve()
ADMIN_WEB_ROOT = Path(os.environ.get("ADMIN_WEB_ROOT", "/admin")).resolve()
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
SETTINGS_FILE = DATA_DIR / "guest_controls.json"
AUDIT_FILE = DATA_DIR / "audit.jsonl"
CORE_API = "http://supervisor/core/api"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
INGRESS_PROXY_IP = os.environ.get("INGRESS_PROXY_IP", "172.30.32.2")

# The wiring is immutable. The admin panel may only show/hide and rename these
# guest circuits; it cannot expose reserved or maintenance relays.
GUEST_CIRCUITS = (
    {"id": "railing-light", "relay": 2, "entity_id": "switch.domo1_rele2", "default_title": "Luz baranda", "icon": "fence"},
    {"id": "night-lights", "relay": 6, "entity_id": "switch.domo1_rele6", "default_title": "Luces nocheros", "icon": "moon"},
    {"id": "bridge-light", "relay": 7, "entity_id": "switch.domo1_rele7", "default_title": "Luz puente", "icon": "bridge"},
    {"id": "external-lights", "relay": 8, "entity_id": "switch.domo1_rele8", "default_title": "Luces externas", "icon": "lightbulb"},
)
CIRCUITS_BY_ID = {circuit["id"]: circuit for circuit in GUEST_CIRCUITS}
SETTINGS_LOCK = threading.Lock()


def core_request(path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    """Call Home Assistant through the Supervisor proxy without exposing its token."""
    if not TOKEN:
        raise RuntimeError("Supervisor token is unavailable")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{CORE_API}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def default_settings() -> dict:
    return {"controls": [{"id": circuit["id"], "relay": circuit["relay"], "title": circuit["default_title"], "icon": circuit["icon"], "enabled": True} for circuit in GUEST_CIRCUITS]}


def normalize_settings(value: object) -> dict:
    supplied = value.get("controls", []) if isinstance(value, dict) else []
    supplied_by_id = {item.get("id"): item for item in supplied if isinstance(item, dict) and item.get("id") in CIRCUITS_BY_ID}
    controls = []
    for circuit in GUEST_CIRCUITS:
        item = supplied_by_id.get(circuit["id"], {})
        title = item.get("title", circuit["default_title"])
        title = " ".join(title.split())[:42] if isinstance(title, str) else ""
        controls.append({
            "id": circuit["id"],
            "relay": circuit["relay"],
            "title": title or circuit["default_title"],
            "icon": circuit["icon"],
            "enabled": item.get("enabled", True) is True,
        })
    return {"controls": controls}


def load_settings() -> dict:
    with SETTINGS_LOCK:
        try:
            return normalize_settings(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return default_settings()


def save_settings(value: object) -> dict:
    settings = normalize_settings(value)
    with SETTINGS_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS_FILE)
    return settings


def write_audit(event: str, **details: object) -> None:
    record = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **details}
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with AUDIT_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"portal: could not record audit event: {error}", flush=True)


def read_audit(limit: int = 60) -> list[dict]:
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    records = []
    for line in reversed(lines):
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
        except json.JSONDecodeError:
            continue
    return records


def state_for(circuit: dict) -> str:
    try:
        state = core_request(f"/states/{circuit['entity_id']}")
        return state.get("state", "unavailable")
    except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
        print(f"portal: failed to read {circuit['id']}: {error}", flush=True)
        return "unavailable"


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class BaseHandler(SimpleHTTPRequestHandler):
    server_version = "RefugioPortal/2.0"
    web_root = GUEST_WEB_ROOT

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        print(f"portal: {self.address_string()} {format % args}", flush=True)

    def serve_static(self) -> None:
        requested = self.path.split("?", 1)[0]
        relative = "index.html" if requested in {"", "/"} else requested.lstrip("/")
        candidate = (self.web_root / relative).resolve()
        if self.web_root not in candidate.parents or not candidate.is_file():
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return
        self.path = f"/{candidate.relative_to(self.web_root)}"
        super().do_GET()

    def translate_path(self, path: str) -> str:
        relative = path.split("?", 1)[0].lstrip("/")
        return str((self.web_root / relative).resolve())

    def respond_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, maximum_length: int = 8192) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > maximum_length:
            raise ValueError("Solicitud demasiado grande")
        payload = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("Solicitud inválida")
        return payload

    def do_PUT(self) -> None:
        self.respond_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Método no permitido"})

    def do_DELETE(self) -> None:
        self.respond_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Método no permitido"})


class GuestHandler(BaseHandler):
    """Unauthenticated LAN endpoint with a fixed, reduced control surface."""

    def guest_controls(self) -> list[dict]:
        return [control for control in load_settings()["controls"] if control["enabled"]]

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/api/config":
            self.respond_json(HTTPStatus.OK, {"controls": self.guest_controls()})
            return
        if self.path == "/api/status":
            self.respond_json(HTTPStatus.OK, {"controls": {control["id"]: state_for(CIRCUITS_BY_ID[control["id"]]) for control in self.guest_controls()}})
            return
        self.serve_static()

    def do_POST(self) -> None:
        prefix = "/api/controls/"
        if not self.path.startswith(prefix):
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return
        control_id = self.path.removeprefix(prefix)
        control = next((item for item in self.guest_controls() if item["id"] == control_id), None)
        if control is None:
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Control no permitido"})
            return
        try:
            desired_state = self.read_json(256).get("state")
            if not isinstance(desired_state, bool):
                raise ValueError("El estado debe ser booleano")
        except (ValueError, json.JSONDecodeError):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "Solicitud inválida"})
            return
        circuit = CIRCUITS_BY_ID[control_id]
        try:
            core_request(f"/services/switch/{'turn_on' if desired_state else 'turn_off'}", method="POST", payload={"entity_id": circuit["entity_id"]})
        except (HTTPError, URLError, RuntimeError, TimeoutError) as error:
            print(f"portal: failed to update {control_id}: {error}", flush=True)
            write_audit("guest_control_failed", control=control_id, relay=circuit["relay"], requested=desired_state)
            self.respond_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "El dispositivo no responde"})
            return
        write_audit("guest_control", control=control_id, relay=circuit["relay"], requested=desired_state)
        self.respond_json(HTTPStatus.OK, {"id": control_id, "state": "on" if desired_state else "off"})


class AdminHandler(BaseHandler):
    """Ingress-only administration endpoint; it is not exposed on the guest port."""

    web_root = ADMIN_WEB_ROOT

    def allowed(self) -> bool:
        return self.client_address[0] == INGRESS_PROXY_IP

    def reject_external(self) -> None:
        self.respond_json(HTTPStatus.FORBIDDEN, {"error": "Administración disponible solo desde Home Assistant"})

    def admin_name(self) -> str:
        return self.headers.get("X-Remote-User-Display-Name") or self.headers.get("X-Remote-User-Name") or "Administrador"

    def do_GET(self) -> None:
        if not self.allowed():
            self.reject_external()
            return
        if self.path == "/api/admin/status":
            settings = load_settings()
            self.respond_json(HTTPStatus.OK, {"controls": settings["controls"], "states": {circuit["id"]: state_for(circuit) for circuit in GUEST_CIRCUITS}, "admin": self.admin_name()})
            return
        if self.path == "/api/admin/logs":
            self.respond_json(HTTPStatus.OK, {"entries": read_audit()})
            return
        self.serve_static()

    def do_POST(self) -> None:
        if not self.allowed():
            self.reject_external()
            return
        if self.path != "/api/admin/config":
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "No encontrado"})
            return
        try:
            settings = save_settings(self.read_json())
        except (ValueError, json.JSONDecodeError):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "Configuración inválida"})
            return
        write_audit("admin_config", user=self.admin_name(), controls=settings["controls"])
        self.respond_json(HTTPStatus.OK, settings)


def serve(server: PortalServer) -> None:
    server.serve_forever()


if __name__ == "__main__":
    save_settings(load_settings())
    guest_server = PortalServer(("0.0.0.0", GUEST_PORT), GuestHandler)
    admin_server = PortalServer(("0.0.0.0", ADMIN_PORT), AdminHandler)
    threading.Thread(target=serve, args=(guest_server,), daemon=True).start()
    print(f"portal: guest controls ready on port {GUEST_PORT}", flush=True)
    print(f"portal: authenticated admin panel ready on port {ADMIN_PORT}", flush=True)
    serve(admin_server)
