"""Token-protected loopback HTTP server for the ForgeOS local control UI."""

from __future__ import annotations

import hmac
import html
import json
import secrets
import threading
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .control import ForgeControlService
from .errors import ForgeConflictError, ForgeError, ForgeNotFoundError

MAX_REQUEST_BYTES = 1_048_576


class ForgeWebServer:
    """Serve one ForgeControlService on an authenticated loopback endpoint."""

    def __init__(
        self,
        control: ForgeControlService,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str | None = None,
    ) -> None:
        if host != "127.0.0.1":
            raise ValueError("ForgeOS V1 UI only permits the 127.0.0.1 loopback address")
        if not 0 <= port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        self.control = control
        self.token = token or secrets.token_urlsafe(32)
        self._httpd = ThreadingHTTPServer((host, port), _handler_type(control, self.token))
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={quote(self.token, safe='')}"

    def serve_forever(self) -> None:
        self._httpd.serve_forever(poll_interval=0.1)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("ForgeOS Web server is already started")
        self._thread = threading.Thread(
            target=self.serve_forever,
            name="forge-web",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._thread is not None:
            self._httpd.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self._httpd.server_close()


def _handler_type(control: ForgeControlService, token: str) -> type[BaseHTTPRequestHandler]:
    class ForgeRequestHandler(BaseHTTPRequestHandler):
        server_version = "ForgeOS"
        sys_version = ""

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _dispatch(self, method: str) -> None:
            try:
                self._route(method)
            except ForgeNotFoundError as exc:
                self._error(HTTPStatus.NOT_FOUND, "not_found", str(exc))
            except ForgeConflictError as exc:
                self._error(HTTPStatus.CONFLICT, "conflict", str(exc))
            except (ForgeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
            except Exception:
                self._error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "internal_error",
                    "The local ForgeOS server encountered an unexpected error.",
                )

        def _route(self, method: str) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/") or "/"
            if method == "GET" and path == "/healthz":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if method == "GET" and path == "/":
                supplied = parse_qs(parsed.query).get("token", [""])[0]
                if not _token_matches(supplied, token):
                    self._error(HTTPStatus.FORBIDDEN, "forbidden", "Missing UI access token.")
                    return
                document = _asset("index.html").replace(
                    "__FORGE_TOKEN__", html.escape(token, quote=True)
                )
                self._content(HTTPStatus.OK, "text/html; charset=utf-8", document.encode())
                return
            if method == "GET" and path in {
                "/assets/app.js",
                "/assets/operator.js",
                "/assets/pilot.js",
                "/assets/styles.css",
            }:
                name = path.rsplit("/", 1)[1]
                content_type = (
                    "text/javascript; charset=utf-8"
                    if name.endswith(".js")
                    else ("text/css; charset=utf-8")
                )
                self._content(HTTPStatus.OK, content_type, _asset(name).encode())
                return
            if not path.startswith("/api/"):
                raise ForgeNotFoundError(f"route not found: {path}")
            if not _token_matches(self.headers.get("X-ForgeOS-Token", ""), token):
                self._error(HTTPStatus.FORBIDDEN, "forbidden", "Invalid API access token.")
                return

            parts = [unquote(part) for part in path.split("/") if part]
            if method == "GET":
                self._api_get(parts)
            elif method == "POST":
                self._api_post(parts, self._json_body())
            else:
                raise ForgeNotFoundError(f"route not found: {path}")

        def _api_get(self, parts: list[str]) -> None:
            if parts == ["api", "status"]:
                self._json(HTTPStatus.OK, control.status())
                return
            if parts == ["api", "doctor"]:
                self._json(HTTPStatus.OK, control.doctor())
                return
            if parts == ["api", "diagnostics", "export"]:
                self._json_download("forgeos-diagnostics.json", control.diagnostic_bundle())
                return
            if parts == ["api", "operations"]:
                self._json(HTTPStatus.OK, control.operations_status())
                return
            if parts == ["api", "operator"]:
                self._json(HTTPStatus.OK, control.operator_status())
                return
            if parts == ["api", "policies"]:
                self._json(HTTPStatus.OK, control.list_policies())
                return
            if parts == ["api", "migration"]:
                self._json(HTTPStatus.OK, control.migration_status())
                return
            if parts == ["api", "tasks"]:
                self._json(HTTPStatus.OK, control.list_tasks())
                return
            if parts == ["api", "memories"]:
                status = parse_qs(urlsplit(self.path).query).get("status", [None])[0]
                self._json(HTTPStatus.OK, control.list_memories(status))
                return
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                self._json(HTTPStatus.OK, control.task_detail(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "report":
                self._json(HTTPStatus.OK, control.task_report(parts[2]))
                return
            if (
                len(parts) == 5
                and parts[:2] == ["api", "tasks"]
                and parts[3:] == ["report", "export"]
            ):
                self._json_download(
                    f"{parts[2]}-task-report.json",
                    control.task_report(parts[2]),
                )
                return
            if parts == ["api", "audit"]:
                query = parse_qs(urlsplit(self.path).query)
                self._json(
                    HTTPStatus.OK,
                    control.audit_events(
                        task_id=query.get("task_id", [None])[0],
                        event_type=query.get("event_type", [None])[0],
                        actor=query.get("actor", [None])[0],
                        after_sequence=int(query.get("after_sequence", [0])[0]),
                        limit=int(query.get("limit", [100])[0]),
                    ),
                )
                return
            if parts == ["api", "jobs"]:
                self._json(HTTPStatus.OK, {"jobs": [job.to_dict() for job in control.jobs.list()]})
                return
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                self._json(HTTPStatus.OK, control.jobs.get(parts[2]).to_dict())
                return
            raise ForgeNotFoundError(f"API route not found: {'/'.join(parts)}")

        def _api_post(self, parts: list[str], payload: dict[str, Any]) -> None:
            if parts == ["api", "project", "init"]:
                self._json(HTTPStatus.CREATED, control.initialize(payload))
                return
            if parts == ["api", "tasks"]:
                self._json(HTTPStatus.CREATED, control.create_task(payload))
                return
            if parts == ["api", "memories"]:
                self._json(HTTPStatus.CREATED, control.create_memory(payload))
                return
            if parts == ["api", "policies"]:
                self._json(HTTPStatus.CREATED, control.create_policy(payload))
                return
            if parts == ["api", "release", "check"]:
                self._json(HTTPStatus.OK, control.release_check())
                return
            if parts == ["api", "operations", "integrity-scan"]:
                self._json(HTTPStatus.OK, control.integrity_scan())
                return
            if parts == ["api", "operations", "recover"]:
                self._json(HTTPStatus.OK, control.recover())
                return
            if parts == ["api", "migration", "apply"]:
                self._json(HTTPStatus.OK, control.migration_apply())
                return
            if len(parts) == 4 and parts[:2] == ["api", "memories"]:
                memory_id, operation = parts[2], parts[3]
                if operation == "accept":
                    self._json(
                        HTTPStatus.OK,
                        control.decide_memory(memory_id, payload, accepted=True),
                    )
                    return
                if operation == "reject":
                    self._json(
                        HTTPStatus.OK,
                        control.decide_memory(memory_id, payload, accepted=False),
                    )
                    return
                raise ForgeNotFoundError(f"memory operation not found: {operation}")
            if len(parts) == 4 and parts[:2] == ["api", "policies"] and parts[3] == "retire":
                self._json(HTTPStatus.OK, control.retire_policy(parts[2], payload))
                return
            if len(parts) != 4 or parts[:2] != ["api", "tasks"]:
                raise ForgeNotFoundError(f"API route not found: {'/'.join(parts)}")
            task_id, operation = parts[2], parts[3]
            if operation == "run":
                self._json(HTTPStatus.ACCEPTED, control.submit_run(task_id, payload))
            elif operation == "validate":
                self._json(HTTPStatus.ACCEPTED, control.submit_validation(task_id))
            elif operation == "review":
                self._json(HTTPStatus.OK, control.review(task_id, payload))
            elif operation == "accept":
                self._json(HTTPStatus.OK, control.accept(task_id, payload))
            elif operation == "interrupt":
                self._json(HTTPStatus.ACCEPTED, control.interrupt(task_id))
            elif operation == "steer":
                self._json(HTTPStatus.OK, control.steer(task_id, payload))
            elif operation == "policy-check":
                self._json(HTTPStatus.OK, control.policy_check(task_id))
            elif operation == "cancel":
                self._json(HTTPStatus.ACCEPTED, control.cancel(task_id, payload))
            else:
                raise ForgeNotFoundError(f"task operation not found: {operation}")

        def _json_body(self) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                raise ValueError("Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValueError("Content-Length is required")
            length = int(raw_length)
            if not 0 <= length <= MAX_REQUEST_BYTES:
                raise ValueError(f"request body exceeds {MAX_REQUEST_BYTES} bytes")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self._content(status, "application/json; charset=utf-8", body)

        def _json_download(self, filename: str, value: dict[str, Any]) -> None:
            body = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
            self._content(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                body,
                extra_headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        def _error(self, status: HTTPStatus, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message[:2_000]}})

        def _content(
            self,
            status: HTTPStatus,
            content_type: str,
            body: bytes,
            *,
            extra_headers: Mapping[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

    return ForgeRequestHandler


def _asset(name: str) -> str:
    return files("forgeos").joinpath("web", name).read_text(encoding="utf-8")


def _token_matches(supplied: str, expected: str) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied, expected)
