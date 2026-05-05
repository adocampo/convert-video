from __future__ import annotations

import json
import os
import signal as _signal
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote, urlparse

from clutch import APP_NAME, get_version
from clutch.auth import has_role
from clutch.converter import (
    convert_video,
    get_visible_nvidia_gpus,
    parse_gpu_devices,
    uses_nvenc_encoder,
)
from clutch.iso import display_titles, is_iso_file, scan_iso
from clutch.logs import (
    _clear_old_log_files,
    _collect_system_stats,
    _delete_log_file,
    _download_log_file,
    _list_log_files,
    _read_log_entries,
)
from clutch.mediainfo import VIDEO_EXTENSIONS, get_media_duration_seconds
from clutch.output import debug, error, info, set_log_level
from clutch.scheduler import BIDDING_ZONES
from clutch.store import ConversionJob
from clutch.updater import get_update_state, _fetch_remote_changelog

if False:  # TYPE_CHECKING
    from clutch.service import ConversionService


def _resolve_web_asset(name: str):
    """Resolve a web asset path, handling subdirectory traversal for Python < 3.12."""
    base = files("clutch.web")
    for segment in name.split("/"):
        base = base.joinpath(segment)
    return base


def read_web_asset(name: str) -> str:
    return _resolve_web_asset(name).read_text(encoding="utf-8")


def read_web_asset_bytes(name: str) -> bytes:
    return _resolve_web_asset(name).read_bytes()



def _read_changelog() -> str:
    """Read CHANGELOG.md bundled inside the package or from the project root."""
    import clutch as _pkg
    pkg_dir = os.path.dirname(os.path.abspath(_pkg.__file__))
    candidates = [
        # Bundled inside the clutch package directory
        os.path.join(pkg_dir, "CHANGELOG.md"),
        # Dev layout: src/clutch/__init__.py -> project root
        os.path.join(pkg_dir, "..", "..", "CHANGELOG.md"),
        # Editable install
        os.path.join(pkg_dir, "..", "..", "..", "CHANGELOG.md"),
    ]
    for candidate in candidates:
        norm = os.path.normpath(candidate)
        if os.path.isfile(norm):
            try:
                with open(norm, "r", encoding="utf-8") as fh:
                    return fh.read()
            except OSError:
                pass
    return ""


# Server-side changelog cache (avoids hitting GitHub API on every tab click)
_changelog_cache: dict = {"content": "", "fetched_at": 0.0}
_CHANGELOG_TTL = 3600  # 1 hour


def _get_cached_changelog(force: bool = False) -> str:
    """Return changelog content, fetching from remote with 1h cache."""
    import time as _t
    now = _t.time()
    if not force and _changelog_cache["content"] and (now - _changelog_cache["fetched_at"]) < _CHANGELOG_TTL:
        return _changelog_cache["content"]
    remote = _fetch_remote_changelog()
    if remote:
        _changelog_cache["content"] = remote
        _changelog_cache["fetched_at"] = now
        return remote
    # Remote failed — return cached if available, otherwise local
    if _changelog_cache["content"]:
        return _changelog_cache["content"]
    return _read_changelog()


class ConversionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Maximum bytes to buffer in memory when scanning for multipart boundaries.
    MULTIPART_CHUNK_SIZE = 65536

    def __init__(self, server_address, request_handler_class, service: ConversionService):
        super().__init__(server_address, request_handler_class)
        self.service = service

    def handle_error(self, request, client_address):
        import sys, traceback
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        error(f"Exception handling request from {client_address}:\n{traceback.format_exc()}")


class _ChunkedReader:
    """Wraps a raw socket rfile and decodes HTTP chunked Transfer-Encoding on the fly."""

    def __init__(self, rfile):
        self._rfile = rfile
        self._chunk_remaining = 0
        self._done = False

    def read(self, n: int) -> bytes:
        if self._done:
            return b""
        result = bytearray()
        while len(result) < n and not self._done:
            if self._chunk_remaining == 0:
                # Read the next chunk-size line (hex + optional extension + CRLF)
                line = self._rfile.readline(256)
                if not line:
                    self._done = True
                    break
                size_str = line.split(b";", 1)[0].strip()
                try:
                    chunk_size = int(size_str, 16)
                except ValueError:
                    self._done = True
                    break
                if chunk_size == 0:
                    self._rfile.readline(256)  # trailing CRLF after last chunk
                    self._done = True
                    break
                self._chunk_remaining = chunk_size
            to_read = min(n - len(result), self._chunk_remaining)
            data = self._rfile.read(to_read)
            if not data:
                self._done = True
                break
            result.extend(data)
            self._chunk_remaining -= len(data)
            if self._chunk_remaining == 0:
                self._rfile.readline(256)  # CRLF after chunk data
        return bytes(result)


class _StreamWriter:
    """Writes HTTP chunked Transfer-Encoding frames to a socket wfile.

    Used by the stream-convert protocol to interleave NDJSON event lines
    and raw binary file chunks within a single HTTP response.
    """

    def __init__(self, wfile):
        self._wfile = wfile

    def event(self, obj: dict):
        """Write one NDJSON event line as a single chunked frame."""
        line = json.dumps(obj, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        self._wfile.write(f"{len(data):x}\r\n".encode("ascii"))
        self._wfile.write(data)
        self._wfile.write(b"\r\n")
        self._wfile.flush()

    def raw_chunk(self, data: bytes):
        """Write raw binary bytes as a single chunked frame."""
        if not data:
            return
        self._wfile.write(f"{len(data):x}\r\n".encode("ascii"))
        self._wfile.write(data)
        self._wfile.write(b"\r\n")

    def terminator(self):
        """Write the chunked transfer-encoding end marker."""
        self._wfile.write(b"0\r\n\r\n")
        self._wfile.flush()


class ServiceRequestHandler(BaseHTTPRequestHandler):
    server: ConversionHTTPServer

    ASSET_CONTENT_TYPES = {
        "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", "text"),
        "/assets/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8", "text"),
        "/assets/i18n.js": ("i18n.js", "application/javascript; charset=utf-8", "text"),
        "/assets/lang/en.json": ("lang/en.json", "application/json; charset=utf-8", "text"),
        "/assets/lang/es.json": ("lang/es.json", "application/json; charset=utf-8", "text"),
        "/assets/clutch.png": ("clutch.png", "image/png", "bytes"),
        "/favicon.ico": ("favicon.ico", "image/x-icon", "bytes"),
    }


    def _send_json(self, status_code: int, payload: Dict[str, object]):
        if status_code >= 400:
            msg = payload.get("error", "") if isinstance(payload, dict) else ""
            debug(f"HTTP {self.command} {self.path} {self.address_string()} -> {status_code}: {msg}")
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, body: str):
        encoded = body.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_text(self, status_code: int, body: str, content_type: str):
        encoded = body.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_bytes(self, status_code: int, body: bytes, content_type: str):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _read_form(self) -> Dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[-1] if len(values) == 1 else values for key, values in parsed.items()}

    def _is_multipart_request(self) -> bool:
        ct = self.headers.get("Content-Type") or ""
        return ct.startswith("multipart/form-data")

    def _drain_request_body(self):
        """Read and discard remaining request body to prevent client connection resets.

        When a POST handler sends an error response without consuming the body,
        the leftover bytes confuse the HTTP keep-alive loop and cause the server
        to close the connection.  The client (still sending) then gets a
        connection-abort error instead of reading the error response.

        Call this after sending an error response on upload endpoints.
        """
        try:
            self.wfile.flush()
        except Exception:
            pass
        try:
            te = (self.headers.get("Transfer-Encoding") or "").lower()
            if "chunked" in te:
                reader = _ChunkedReader(self.rfile)
                while reader.read(65536):
                    pass
            else:
                length = int(self.headers.get("Content-Length") or "0")
                while length > 0:
                    chunk = self.rfile.read(min(length, 65536))
                    if not chunk:
                        break
                    length -= len(chunk)
        except Exception:
            pass
        self.close_connection = True

    def _parse_multipart(self, *, max_file_bytes: int = 0, upload_dir: str = "") -> dict:
        """Parse a multipart/form-data request, streaming the file part to disk.

        Returns ``{"fields": {name: value, ...}, "file_path": str, "file_name": str, "file_size": int}``
        where *file_path* is the absolute path of the saved file on disk.
        Raises ``ValueError`` on protocol errors or size violations.
        """
        ct = self.headers.get("Content-Type") or ""
        if "boundary=" not in ct:
            raise ValueError("Missing multipart boundary.")
        boundary = ct.split("boundary=", 1)[1].strip()
        if boundary.startswith('"') and boundary.endswith('"'):
            boundary = boundary[1:-1]
        boundary_bytes = ("--" + boundary).encode("utf-8")
        end_boundary = boundary_bytes + b"--"
        content_length = int(self.headers.get("Content-Length") or "0")
        te = (self.headers.get("Transfer-Encoding") or "").lower()

        # Determine body source: Content-Length framing or chunked TE.
        # Python's urllib may send chunked TE even when the caller sets
        # Content-Length (bpo-16464), so we must handle both.
        if content_length > 0:
            rfile = self.rfile
            remaining = content_length
        elif "chunked" in te:
            rfile = _ChunkedReader(self.rfile)
            remaining = max_file_bytes or (10 * 1024 * 1024 * 1024)  # 10 GiB cap
        else:
            raise ValueError(
                "Missing Content-Length header and no chunked Transfer-Encoding. "
                "The client may be too old — update it or check the request."
            )

        # We stream through the body scanning for boundaries to avoid holding
        # the whole payload in a single Python bytes object when writing the file.
        CHUNK = self.server.MULTIPART_CHUNK_SIZE

        def _read(n: int) -> bytes:
            nonlocal remaining
            to_read = min(n, remaining)
            if to_read <= 0:
                return b""
            data = rfile.read(to_read)
            remaining -= len(data)
            return data

        # Helper: read until we see a full line (CRLF terminated)
        buf = b""

        def _readline() -> bytes:
            nonlocal buf
            while b"\r\n" not in buf:
                chunk = _read(CHUNK)
                if not chunk:
                    line = buf
                    buf = b""
                    return line
                buf += chunk
            idx = buf.index(b"\r\n")
            line = buf[:idx + 2]
            buf = buf[idx + 2:]
            return line

        # Skip preamble until first boundary
        try:
            while True:
                line = _readline()
                if not line:
                    raise ValueError("Unexpected end of multipart stream.")
                if line.rstrip(b"\r\n") == boundary_bytes:
                    break

            fields: Dict[str, str] = {}
            file_path = ""
            file_name = ""
            file_size = 0

            while True:
                # Parse headers for this part
                part_headers: Dict[str, str] = {}
                while True:
                    hline = _readline()
                    if hline in (b"\r\n", b"", b"\n"):
                        break
                    if b":" in hline:
                        hname, hval = hline.decode("utf-8", errors="replace").split(":", 1)
                        part_headers[hname.strip().lower()] = hval.strip()

                disposition = part_headers.get("content-disposition", "")
                # Extract name
                name = ""
                if 'name="' in disposition:
                    name = disposition.split('name="', 1)[1].split('"', 1)[0]

                # Detect file part
                is_file = 'filename="' in disposition
                if is_file:
                    file_name = disposition.split('filename="', 1)[1].split('"', 1)[0]
                    # Sanitize: strip directory components
                    file_name = os.path.basename(file_name)
                    if not file_name:
                        raise ValueError("Uploaded file has no filename.")

                    dest_name = f"{uuid.uuid4().hex[:12]}_{file_name}"
                    tmp_path = os.path.join(upload_dir, dest_name + ".tmp")
                    final_path = os.path.join(upload_dir, dest_name)
                    written = 0

                    try:
                        with open(tmp_path, "wb") as fout:
                            # Stream body bytes, scanning for next boundary
                            while True:
                                # Ensure buf has enough data to detect boundary
                                while len(buf) < len(boundary_bytes) + 4 + CHUNK:
                                    chunk = _read(CHUNK)
                                    if not chunk:
                                        break
                                    buf += chunk

                                # Check for boundary in buffer
                                bpos = buf.find(b"\r\n" + boundary_bytes)
                                if bpos != -1:
                                    # Write everything before the boundary
                                    fout.write(buf[:bpos])
                                    written += bpos
                                    buf = buf[bpos + 2 + len(boundary_bytes):]
                                    break
                                else:
                                    # Safe to write everything except the tail that might contain a partial boundary
                                    safe = len(buf) - (len(boundary_bytes) + 4)
                                    if safe > 0:
                                        if max_file_bytes and written + safe > max_file_bytes:
                                            raise ValueError(
                                                f"File exceeds maximum upload size ({max_file_bytes} bytes)."
                                            )
                                        fout.write(buf[:safe])
                                        written += safe
                                        buf = buf[safe:]
                                    elif not buf:
                                        break

                        if max_file_bytes and written > max_file_bytes:
                            raise ValueError(
                                f"File exceeds maximum upload size ({max_file_bytes} bytes)."
                            )
                        os.rename(tmp_path, final_path)
                        file_path = final_path
                        file_size = written
                    except Exception:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                        raise
                else:
                    # Regular form field — collect value from body until boundary
                    value_parts = []
                    while True:
                        while len(buf) < len(boundary_bytes) + 4 + CHUNK:
                            chunk = _read(CHUNK)
                            if not chunk:
                                break
                            buf += chunk
                        bpos = buf.find(b"\r\n" + boundary_bytes)
                        if bpos != -1:
                            value_parts.append(buf[:bpos])
                            buf = buf[bpos + 2 + len(boundary_bytes):]
                            break
                        else:
                            safe = len(buf) - (len(boundary_bytes) + 4)
                            if safe > 0:
                                value_parts.append(buf[:safe])
                                buf = buf[safe:]
                            elif not buf:
                                break
                    fields[name] = b"".join(value_parts).decode("utf-8", errors="replace")

                # After the boundary, check for end marker or continue
                peek_line = _readline()
                stripped = peek_line.rstrip(b"\r\n")
                if stripped == b"--" or stripped == end_boundary:
                    break
                # Otherwise it's CRLF and next part headers follow

            # Drain any remaining body bytes
            while remaining > 0:
                if not _read(CHUNK):
                    break

            return {"fields": fields, "file_path": file_path, "file_name": file_name, "file_size": file_size}

        except Exception:
            # Drain remaining body so the error response can reach the client
            # instead of causing a connection abort (WinError 10053 etc.)
            while remaining > 0:
                try:
                    if not _read(CHUNK):
                        break
                except Exception:
                    break
            self.close_connection = True
            raise

    def _get_request_parts(self) -> tuple[str, Dict[str, object]]:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        flattened = {key: values[-1] if len(values) == 1 else values for key, values in query.items()}
        return parsed.path, flattened

    def _send_redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _is_json_request(self) -> bool:
        content_type = self.headers.get("Content-Type", "")
        return "application/json" in content_type

    def _redirect_with_message(self, *, notice: str = "", error_message: str = ""):
        if error_message:
            target = f"/?error={quote(error_message)}"
        else:
            target = f"/?notice={quote(notice)}"
        self._send_redirect(target)

    # ── Auth helpers ──

    def _get_client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else ""

    def _get_base_url(self) -> str:
        host = self.headers.get("Host", "localhost")
        scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        return f"{scheme}://{host}"

    def _get_bearer_token(self) -> str:
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        # Fallback: token in query string (for file downloads via <a href>)
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        token_list = qs.get("token")
        if token_list:
            return str(token_list[0]).strip()
        return ""

    def _get_auth_user(self) -> Optional[Dict[str, object]]:
        """Return the authenticated user dict or ``None``."""
        auth = self.server.service.auth
        if not auth.is_auth_enabled():
            return None
        token = self._get_bearer_token()
        if not token:
            return None
        return auth.validate_token(token)

    def _require_role(self, minimum_role: str) -> Optional[Dict[str, object]]:
        """Return the authenticated user if they have at least *minimum_role*, else send an error response."""
        auth = self.server.service.auth
        if not auth.is_auth_enabled():
            # Auth disabled — allow everything
            return {"id": 0, "username": "anonymous", "email": "", "role": "admin"}
        token = self._get_bearer_token()
        if not token:
            self._send_json(401, {"error": "Authentication required."})
            return None
        user = auth.validate_token(token)
        if not user:
            self._send_json(401, {"error": "Invalid or expired token."})
            return None
        if not has_role(user, minimum_role):
            self._send_json(403, {"error": "Insufficient permissions."})
            return None
        return user

    def _is_public_path(self, path: str) -> bool:
        """Paths that never require authentication."""
        if path in self.ASSET_CONTENT_TYPES:
            return True
        if path in {"/health", "/login", "/setup", "/auth/status"}:
            return True
        if path in {"/auth/login", "/auth/setup", "/auth/password-reset", "/auth/password-reset/confirm"}:
            return True
        return False

    def _check_setup_redirect(self, path: str) -> bool:
        """If setup is needed, redirect non-public routes to /setup. Returns True if redirected."""
        if self._is_public_path(path):
            return False
        if not self.server.service.auth.needs_setup():
            return False
        if self._is_json_request() or self._get_bearer_token():
            self._send_json(503, {"error": "Initial setup required.", "setup_required": True})
        else:
            self._send_redirect("/setup")
        return True

    def _handle_auth_get(self, path: str) -> bool:
        """Handle GET requests under ``/auth/*`` and ``/setup`` and ``/login``. Returns True if handled."""
        if path == "/setup":
            if not self.server.service.auth.needs_setup():
                self._send_redirect("/")
                return True
            self._send_html(200, read_web_asset("setup.html"))
            return True

        if path == "/login":
            if not self.server.service.auth.is_auth_enabled():
                self._send_redirect("/")
                return True
            self._send_html(200, read_web_asset("login.html"))
            return True

        if path == "/auth/status":
            auth = self.server.service.auth
            self._send_json(200, {
                "auth_enabled": auth.is_auth_enabled(),
                "setup_required": auth.needs_setup(),
                "user_count": auth.user_count(),
            })
            return True

        if path == "/auth/me":
            user = self._require_role("viewer")
            if not user:
                return True
            self._send_json(200, {"user": user})
            return True

        if path == "/auth/me/preferences":
            user = self._require_role("viewer")
            if not user:
                return True
            prefs = self.server.service.auth.get_user_preferences(user["id"])
            self._send_json(200, prefs)
            return True

        if path == "/auth/users":
            user = self._require_role("admin")
            if not user:
                return True
            self._send_json(200, {"users": self.server.service.auth.list_users()})
            return True

        if path == "/auth/tokens":
            user = self._require_role("viewer")
            if not user:
                return True
            self._send_json(200, {"tokens": self.server.service.auth.list_tokens(user["id"])})
            return True

        if path == "/auth/tokens/all":
            user = self._require_role("admin")
            if not user:
                return True
            self._send_json(200, {"tokens": self.server.service.auth.list_all_tokens()})
            return True

        if path == "/auth/smtp":
            user = self._require_role("admin")
            if not user:
                return True
            self._send_json(200, self.server.service.auth.get_smtp_config_safe())
            return True

        return False

    def _handle_auth_post(self, path: str) -> bool:
        """Handle POST requests under ``/auth/*``. Returns True if handled."""
        auth = self.server.service.auth

        if path == "/auth/setup":
            if not auth.needs_setup():
                self._send_json(409, {"error": "Setup already completed."})
                return True
            try:
                payload = self._read_json()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "Invalid JSON."})
                return True
            if payload.get("skip"):
                auth.skip_auth()
                self._send_json(200, {"message": "Authentication skipped.", "skipped": True})
                return True
            try:
                user = auth.create_user(
                    str(payload.get("username") or "").strip(),
                    str(payload.get("email") or "").strip(),
                    str(payload.get("password") or ""),
                    role="admin",
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            # Enable auth (clear skip flag if was set before)
            auth.enable_auth()
            # Auto-login: generate a token
            _, token = auth.authenticate(
                user["username"],
                str(payload.get("password") or ""),
                client_ip=self._get_client_ip(),
            )
            self._send_json(201, {"user": user, "token": token})
            return True

        if path == "/auth/login":
            try:
                payload = self._read_json()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "Invalid JSON."})
                return True
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            if not username or not password:
                self._send_json(400, {"error": "Username and password are required."})
                return True
            user, token_or_error = auth.authenticate(
                username, password, client_ip=self._get_client_ip()
            )
            if not user:
                self._send_json(401, {"error": token_or_error})
                return True
            self._send_json(200, {"user": user, "token": token_or_error})
            return True

        if path == "/auth/logout":
            token = self._get_bearer_token()
            if token:
                auth.revoke_token(token)
            self._send_json(200, {"message": "Logged out."})
            return True

        if path == "/auth/users":
            user = self._require_role("admin")
            if not user:
                return True
            try:
                payload = self._read_json()
                new_user = auth.create_user(
                    str(payload.get("username") or "").strip(),
                    str(payload.get("email") or "").strip(),
                    str(payload.get("password") or ""),
                    role=str(payload.get("role") or "viewer"),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            # If this is the first user and auth was skipped, re-enable auth
            if auth.user_count() == 1:
                auth.enable_auth()
            self._send_json(201, new_user)
            return True

        if path == "/auth/me/password":
            user = self._require_role("viewer")
            if not user:
                return True
            try:
                payload = self._read_json()
                auth.change_password(
                    user["id"],
                    str(payload.get("old_password") or ""),
                    str(payload.get("new_password") or ""),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            self._send_json(200, {"message": "Password changed. Please log in again."})
            return True

        if path == "/auth/password-reset":
            try:
                payload = self._read_json()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "Invalid JSON."})
                return True
            email = str(payload.get("email") or "").strip()
            if not email:
                self._send_json(400, {"error": "Email is required."})
                return True
            result = auth.create_password_reset(email)
            if result:
                reset_token, reset_user = result
                try:
                    auth.send_password_reset_email(reset_user, reset_token, self._get_base_url())
                except ValueError:
                    pass  # Silently fail — don't reveal whether the email exists
            # Always return success to avoid email enumeration
            self._send_json(200, {"message": "If an account exists with that email, a reset link has been sent."})
            return True

        if path == "/auth/password-reset/confirm":
            try:
                payload = self._read_json()
                auth.confirm_password_reset(
                    str(payload.get("token") or ""),
                    str(payload.get("new_password") or ""),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            self._send_json(200, {"message": "Password has been reset. Please log in."})
            return True

        if path == "/auth/tokens":
            user = self._require_role("viewer")
            if not user:
                return True
            try:
                payload = self._read_json()
                name = str(payload.get("name") or "").strip()
                days = int(payload.get("days") or 365)
                if days < 1 or days > 3650:
                    raise ValueError("Token validity must be between 1 and 3650 days.")
                plain_token, token_info = auth.create_api_token(user["id"], name=name, days=days)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            self._send_json(201, {"token": plain_token, **token_info})
            return True

        if path == "/auth/smtp":
            user = self._require_role("admin")
            if not user:
                return True
            try:
                payload = self._read_json()
                auth.update_smtp_config(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            self._send_json(200, {"message": "SMTP settings saved."})
            return True

        if path == "/auth/smtp/test":
            user = self._require_role("admin")
            if not user:
                return True
            try:
                payload = self._read_json()
                recipient = str(payload.get("recipient") or user.get("email") or "")
                if not recipient:
                    self._send_json(400, {"error": "No recipient email provided."})
                    return True
                auth.test_smtp(recipient)
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            self._send_json(200, {"message": f"Test email sent to {recipient}."})
            return True

        return False

    def _handle_auth_put(self, path: str) -> bool:
        """Handle PUT requests under ``/auth/*``. Returns True if handled."""
        if path == "/auth/me/preferences":
            user = self._require_role("viewer")
            if not user:
                return True
            try:
                payload = self._read_json()
                prefs = self.server.service.auth.update_user_preferences(
                    user["id"],
                    theme=str(payload.get("theme") or ""),
                    language=str(payload.get("language") or ""),
                    date_format=str(payload.get("date_format") or ""),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            self._send_json(200, prefs)
            return True

        if path.startswith("/auth/users/"):
            user = self._require_role("admin")
            if not user:
                return True
            target_id_str = path.rsplit("/", 1)[-1]
            try:
                target_id = int(target_id_str)
            except ValueError:
                self._send_json(400, {"error": "Invalid user ID."})
                return True
            try:
                payload = self._read_json()
                updated = self.server.service.auth.update_user(
                    target_id,
                    username=payload.get("username"),
                    email=payload.get("email"),
                    role=payload.get("role"),
                )
                # Admin set-password (without knowing current password)
                set_password = str(payload.get("set_password") or "").strip()
                if set_password:
                    self.server.service.auth.set_password_admin(target_id, set_password)
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return True
            if not updated:
                self._send_json(404, {"error": "User not found."})
                return True
            self._send_json(200, updated)
            return True
        return False

    def _handle_auth_delete(self, path: str) -> bool:
        """Handle DELETE requests under ``/auth/*``. Returns True if handled."""
        if path.startswith("/auth/users/"):
            user = self._require_role("admin")
            if not user:
                return True
            target_id_str = path.rsplit("/", 1)[-1]
            try:
                target_id = int(target_id_str)
            except ValueError:
                self._send_json(400, {"error": "Invalid user ID."})
                return True
            try:
                deleted = self.server.service.auth.delete_user(target_id)
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return True
            if not deleted:
                self._send_json(404, {"error": "User not found."})
                return True
            self._send_json(200, {"id": target_id, "deleted": True})
            return True

        if path.startswith("/auth/tokens/"):
            user = self._require_role("viewer")
            if not user:
                return True
            token_id_str = path.rsplit("/", 1)[-1]
            try:
                token_id = int(token_id_str)
            except ValueError:
                self._send_json(400, {"error": "Invalid token ID."})
                return True
            # Admin can delete any token; non-admin only their own
            if user.get("role") == "admin":
                deleted = self.server.service.auth.admin_delete_token(token_id)
            else:
                deleted = self.server.service.auth.delete_token_by_id(token_id, user["id"])
            if not deleted:
                self._send_json(404, {"error": "Token not found."})
                return True
            self._send_json(200, {"id": token_id, "deleted": True})
            return True

        return False

    def do_GET(self):
        path, query = self._get_request_parts()

        if path in self.ASSET_CONTENT_TYPES:
            asset_name, content_type, mode = self.ASSET_CONTENT_TYPES[path]
            if mode == "bytes":
                self._send_bytes(200, read_web_asset_bytes(asset_name), content_type)
            else:
                self._send_text(200, read_web_asset(asset_name), content_type)
            return

        # Auth-related GET routes (/setup, /login, /auth/*)
        if self._handle_auth_get(path):
            return

        # Setup redirect (before any protected content)
        if self._check_setup_redirect(path):
            return

        if path in {"/", "/index.html"}:
            if query.get("input_file"):
                user = self._require_role("operator")
                if not user:
                    return
                try:
                    record = self.server.service.submit_jobs_from_payload(query, source="ui")
                except ValueError as exc:
                    self._redirect_with_message(error_message=str(exc))
                    return
                self._redirect_with_message(notice=str(record.get("message") or f"Queued job {record['id']}"))
                return
            self._send_html(200, read_web_asset("dashboard.html"))
            return

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        # All remaining GET routes require at least viewer role
        user = self._require_role("viewer")
        if not user:
            return

        if path == "/system/stats":
            self._send_json(200, _collect_system_stats())
            return

        if path == "/browse":
            try:
                show_hidden_value = str(query.get("show_hidden") or "").strip().lower()
                payload = self.server.service.browse_paths(
                    str(query.get("path") or ""),
                    selection=str(query.get("selection") or "file"),
                    scope=str(query.get("scope") or "allowed"),
                    show_hidden=show_hidden_value in {"1", "true", "yes", "on"},
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, payload)
            return

        if path == "/browse/match":
            import time as _time
            directory = str(query.get("path") or "").strip()
            pattern = str(query.get("pattern") or "").strip()
            recursive_val = str(query.get("recursive") or "").strip().lower()
            recursive = recursive_val in {"1", "true", "yes", "on"}
            debug(f"browse/match: path={directory!r} pattern={pattern!r} recursive={recursive}")
            if not directory:
                self._send_json(400, {"error": "path is required"})
                return
            try:
                from clutch.service import normalize_path
                norm_dir = normalize_path(directory)
                t0 = _time.monotonic()
                matched = self.server.service._collect_directory_input_files(
                    directory, recursive=recursive, filter_pattern=pattern,
                )
                elapsed = _time.monotonic() - t0
                rel_paths = [os.path.relpath(p, norm_dir) for p in matched]
                debug(f"browse/match: {len(rel_paths)} results in {elapsed:.2f}s")
                self._send_json(200, {"matches": rel_paths, "total": len(rel_paths)})
            except ValueError as exc:
                debug(f"browse/match: error — {exc}")
                self._send_json(400, {"error": str(exc)})
                return
            return

        if path == "/config":
            self._send_json(200, self.server.service.get_service_summary())
            return

        if path == "/watchers":
            self._send_json(200, {"watchers": self.server.service.list_watchers()})
            return

        if path == "/presets":
            self._send_json(200, {"presets": self.server.service.list_presets()})
            return

        if path == "/presets/official":
            force = str(query.get("refresh") or "").lower() in {"1", "true", "yes", "on"}
            self._send_json(200, self.server.service.list_official_presets(force_refresh=force))
            return

        if path.startswith("/presets/") and path.endswith("/export"):
            preset_id = path[len("/presets/"):-len("/export")]
            doc = self.server.service.export_preset_as_handbrake(preset_id)
            if doc is None:
                self._send_json(404, {"error": "Preset not found."})
                return
            body = json.dumps(doc, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            safe_name = "".join(c for c in str(doc.get("PresetList", [{}])[0].get("PresetName") or "preset") if c.isalnum() or c in "-_") or "preset"
            self.send_header("Content-Disposition", f'attachment; filename="{safe_name}.json"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/presets/"):
            preset_id = path.rsplit("/", 1)[-1]
            preset = self.server.service.get_preset(preset_id)
            if not preset:
                self._send_json(404, {"error": "Preset not found."})
                return
            self._send_json(200, preset)
            return

        if path == "/jobs":
            self._send_json(200, {"jobs": self.server.service.list_jobs()})
            return

        if path.startswith("/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            record = self.server.service.get_job(job_id)
            if not record:
                self._send_json(404, {"error": "Job not found."})
                return
            self._send_json(200, record)
            return

        if path == "/download":
            file_path = str(query.get("path") or "").strip()
            if not file_path:
                self._send_json(400, {"error": "Missing path parameter."})
                return
            try:
                self.server.service._validate_path(file_path, require_file=True)
            except ValueError as exc:
                self._send_json(403, {"error": str(exc)})
                return
            resolved = os.path.abspath(file_path)
            try:
                file_size = os.path.getsize(resolved)
            except OSError:
                self._send_json(404, {"error": "File not found."})
                return
            import mimetypes
            content_type = mimetypes.guess_type(resolved)[0] or "application/octet-stream"
            safe_name = os.path.basename(resolved).replace('"', '\\"')
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
            self.send_header("Content-Length", str(file_size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(resolved, "rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return

        if path == "/stream-convert/cached":
            self._handle_stream_convert_cached(query)
            return

        if path == "/schedule/prices":
            prices = self.server.service.scheduler.get_cached_prices_list()
            self._send_json(200, {"prices": prices})
            return

        if path == "/system/logs/files":
            user = self._require_role("admin")
            if not user:
                return
            self._send_json(200, {"files": _list_log_files()})
            return

        if path == "/system/logs/download":
            user = self._require_role("admin")
            if not user:
                return
            filename = str(query.get("file") or "").strip()
            if not filename:
                self._send_json(400, {"error": "Missing file parameter."})
                return
            content = _download_log_file(filename)
            if content is None:
                self._send_json(404, {"error": "File not found."})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(filename)}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/system/logs":
            user = self._require_role("admin")
            if not user:
                return
            filename = str(query.get("file") or "").strip()
            level_filter = str(query.get("level") or "").upper()
            search = str(query.get("search") or "").strip()
            try:
                page = max(1, int(query.get("page") or 1))
            except (ValueError, TypeError):
                page = 1
            try:
                limit = max(1, min(5000, int(query.get("limit") or 200)))
            except (ValueError, TypeError):
                limit = 200
            result = _read_log_entries(
                filename=filename, level=level_filter, search=search,
                page=page, limit=limit,
            )
            self._send_json(200, result)
            return

        if path == "/system/tasks":
            user = self._require_role("admin")
            if not user:
                return
            status_filter = str(query.get("status") or "").strip()
            codec_filter = str(query.get("codec") or "").strip()
            search = str(query.get("search") or "").strip()
            try:
                page = max(1, int(query.get("page") or 1))
            except (ValueError, TypeError):
                page = 1
            try:
                limit = max(1, min(500, int(query.get("limit") or 50)))
            except (ValueError, TypeError):
                limit = 50
            result = self.server.service.store.list_tasks(
                page=page, limit=limit,
                status=status_filter, codec=codec_filter, search=search,
            )
            self._send_json(200, result)
            return

        if path == "/system/changelog":
            user = self._require_role("viewer")
            if not user:
                return
            _, query_params = self._get_request_parts()
            force = query_params.get("force") == "true"
            content = _get_cached_changelog(force=force)
            self._send_json(200, {"changelog": content})
            return

        if path == "/config/notifications":
            user = self._require_role("admin")
            if not user:
                return
            self._send_json(200, {"channels": self.server.service.notifications.list_channels()})
            return

        self._send_json(404, {"error": "Not found."})

    def do_POST(self):
        path, _ = self._get_request_parts()

        # Auth-related POST routes
        if self._handle_auth_post(path):
            return

        # Setup redirect
        if self._check_setup_redirect(path):
            return

        if path == "/updates/check":
            user = self._require_role("admin")
            if not user:
                return
            self._send_json(200, self.server.service.get_update_info(force_check=True))
            return

        if path == "/updates/upgrade":
            user = self._require_role("admin")
            if not user:
                return
            try:
                payload = self.server.service.schedule_self_upgrade(self.server.shutdown)
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(202, payload)
            return

        if path == "/debug/fake-upgrade":
            user = self._require_role("admin")
            if not user:
                return
            try:
                payload = self.server.service.schedule_fake_upgrade()
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(202, payload)
            return

        if path.startswith("/jobs/") and path.endswith("/retry"):
            user = self._require_role("operator")
            if not user:
                return
            job_id = path[:-len("/retry")].rsplit("/", 1)[-1]
            try:
                record = self.server.service.retry_job(job_id)
            except ValueError as exc:
                if self._is_json_request():
                    self._send_json(400, {"error": str(exc)})
                else:
                    self._redirect_with_message(error_message=str(exc))
                return
            if not record:
                if self._is_json_request():
                    self._send_json(409, {"error": "Job cannot be retried."})
                else:
                    self._redirect_with_message(error_message="Job cannot be retried.")
                return
            if self._is_json_request():
                self._send_json(200, record)
            else:
                self._redirect_with_message(notice=f"Queued retry for job {job_id}")
            return

        if path.startswith("/jobs/") and path.endswith("/pause"):
            user = self._require_role("operator")
            if not user:
                return
            job_id = path[:-len("/pause")].rsplit("/", 1)[-1]
            try:
                record = self.server.service.pause_job(job_id)
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            if not record:
                self._send_json(409, {"error": "Job cannot be paused."})
                return
            self._send_json(200, record)
            return

        if path.startswith("/jobs/") and path.endswith("/resume"):
            user = self._require_role("operator")
            if not user:
                return
            job_id = path[:-len("/resume")].rsplit("/", 1)[-1]
            try:
                record = self.server.service.resume_job(job_id)
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            if not record:
                self._send_json(409, {"error": "Job cannot be resumed."})
                return
            self._send_json(200, record)
            return

        if path.startswith("/jobs/") and path.endswith("/move-next"):
            user = self._require_role("operator")
            if not user:
                return
            job_id = path[:-len("/move-next")].rsplit("/", 1)[-1]
            record = self.server.service.store.move_to_next(job_id)
            if not record:
                self._send_json(404, {"error": "Job not found."})
                return
            self._send_json(200, record)
            return

        if path.startswith("/jobs/") and path.endswith("/priority"):
            user = self._require_role("operator")
            if not user:
                return
            job_id = path[:-len("/priority")].rsplit("/", 1)[-1]
            try:
                payload = self._read_json()
                priority = int(payload["priority"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                self._send_json(400, {"error": "JSON body with integer 'priority' required."})
                return
            record = self.server.service.store.set_priority(job_id, priority)
            if not record:
                self._send_json(404, {"error": "Job not found."})
                return
            self._send_json(200, record)
            return

        if path == "/config/detect-binaries":
            user = self._require_role("admin")
            if not user:
                return
            from clutch import REQUIRED_BINARIES, detect_all_binaries
            detected = detect_all_binaries()
            self.server.service.binary_paths = {
                name: detected.get(name, "") for name in REQUIRED_BINARIES
            }
            from clutch import set_binary_paths, get_missing_binaries
            set_binary_paths(self.server.service.binary_paths)
            self.server.service.store.save_service_config(
                self.server.service.allowed_roots,
                self.server.service.default_job_settings,
                self.server.service.worker_count,
                self.server.service.gpu_devices,
                self.server.service.scheduler.config.to_dict(),
                self.server.service.log_level,
                self.server.service.log_retention_days,
                self.server.service.default_date_format,
                self.server.service.listen_port,
                self.server.service.binary_paths,
                self.server.service.upload_dir,
                self.server.service.max_upload_size_bytes,
                self.server.service.display_timezone,
            )
            self._send_json(200, {
                "binary_paths": dict(self.server.service.binary_paths),
                "missing_binaries": get_missing_binaries(),
            })
            return

        if path == "/config/notifications":
            user = self._require_role("admin")
            if not user:
                return
            try:
                payload = self._read_json()
                result = self.server.service.notifications.save_channel(payload)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return

        if path == "/config/notifications/test":
            user = self._require_role("admin")
            if not user:
                return
            try:
                payload = self._read_json()
                channel_id = str(payload.get("id") or "").strip()
                if not channel_id:
                    self._send_json(400, {"error": "Missing channel id."})
                    return
                result = self.server.service.notifications.test_channel(channel_id)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return

        if path == "/config":
            user = self._require_role("admin")
            if not user:
                return
            try:
                payload = self._read_json() if self._is_json_request() else self._read_form()
                if not self._is_json_request():
                    allowed_roots = str(payload.get("allowed_roots") or "")
                    payload = {
                        "allowed_roots": [line.strip() for line in allowed_roots.splitlines() if line.strip()],
                        "worker_count": payload.get("worker_count", 1),
                        "gpu_devices": payload.get("gpu_devices", ""),
                        "default_job_settings": {
                            "output_dir": payload.get("default_output_dir", ""),
                            "codec": payload.get("default_codec", "nvenc_h265"),
                            "encode_speed": payload.get("default_encode_speed", "normal"),
                            "audio_passthrough": payload.get("default_audio_passthrough") == "on",
                            "delete_source": payload.get("default_delete_source") == "on",
                            "force": payload.get("default_force") == "on",
                            "verbose": payload.get("default_verbose") == "on",
                            "default_preset_id": payload.get("default_preset_id", ""),
                        },
                    }
                summary = self.server.service.update_service_settings(payload)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except ValueError as exc:
                if self._is_json_request():
                    self._send_json(400, {"error": str(exc)})
                else:
                    self._redirect_with_message(error_message=str(exc))
                return
            restart_pending = summary.pop("_restart_pending", False)
            if self._is_json_request():
                self._send_json(200, summary)
            else:
                self._redirect_with_message(notice="Settings saved.")
            if restart_pending:
                import threading as _threading
                _threading.Thread(
                    target=self.server.service.request_restart_with_port,
                    args=(self.server.service.listen_port, self.server.shutdown),
                    daemon=True,
                ).start()
            return

        if path == "/presets":
            user = self._require_role("admin")
            if not user:
                return
            try:
                payload = self._read_json()
                preset = self.server.service.save_preset(payload)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(201, preset)
            return

        if path == "/presets/import":
            user = self._require_role("admin")
            if not user:
                return
            try:
                document = self._read_json()
                preset = self.server.service.import_preset_from_handbrake(document)
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(201, preset)
            return

        if path == "/watchers":
            user = self._require_role("operator")
            if not user:
                return
            try:
                payload = self._read_json() if self._is_json_request() else self._read_form()
                is_json = self._is_json_request()
                _bool = lambda k, d=False: bool(payload.get(k, d)) if is_json else payload.get(k) == "on"
                _nbool = lambda k: payload.get(k) if (is_json and k in payload and payload[k] is not None) else (True if not is_json and payload.get(k) == "on" else None)
                watcher = self.server.service.add_watcher(
                    str(payload.get("directory") or "").strip(),
                    recursive=_bool("recursive"),
                    poll_interval=float(payload.get("poll_interval") or 5.0),
                    settle_time=float(payload.get("settle_time") or 30.0),
                    delete_source=_bool("delete_source"),
                    output_dir=str(payload.get("output_dir") or "").strip(),
                    codec=str(payload.get("codec") or "").strip(),
                    encode_speed=str(payload.get("encode_speed") or "").strip(),
                    audio_passthrough=_nbool("audio_passthrough"),
                    force=_nbool("force"),
                    preset_id=str(payload.get("preset_id") or "").strip() or None,
                )
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except (TypeError, ValueError) as exc:
                if self._is_json_request():
                    self._send_json(400, {"error": str(exc)})
                else:
                    self._redirect_with_message(error_message=str(exc))
                return
            if self._is_json_request():
                self._send_json(201, watcher)
            else:
                self._redirect_with_message(notice=f"Watcher added: {watcher['directory']}")
            return

        # ── File upload endpoint ────────────────────────────────────────
        if path == "/upload":
            user = self._require_role("operator")
            if not user:
                self._drain_request_body()
                return
            svc = self.server.service
            if not svc.upload_dir:
                self._send_json(409, {"error": "Upload directory is not configured on this server."})
                self._drain_request_body()
                return
            if not self._is_multipart_request():
                self._send_json(400, {"error": "Expected multipart/form-data request."})
                self._drain_request_body()
                return
            try:
                result = self._parse_multipart(
                    max_file_bytes=svc.max_upload_size_bytes,
                    upload_dir=svc.upload_dir,
                )
            except ValueError as exc:
                self._send_json(413 if "exceeds" in str(exc).lower() else 400, {"error": str(exc)})
                return
            except OSError as exc:
                self._send_json(500, {"error": f"Failed to save uploaded file: {exc}"})
                return
            self._send_json(201, {
                "path": result["file_path"],
                "filename": result["file_name"],
                "size": result["file_size"],
            })
            return

        # ── Upload and convert in one step ──────────────────────────────
        if path == "/upload-and-convert":
            ct = self.headers.get("Content-Type", "")
            cl = self.headers.get("Content-Length", "")
            te = self.headers.get("Transfer-Encoding", "")
            debug(
                f"upload-and-convert: Content-Type={ct!r} "
                f"Content-Length={cl or '<missing>'} "
                f"Transfer-Encoding={te or '<none>'} "
                f"from {self.address_string()}"
            )
            user = self._require_role("operator")
            if not user:
                self._drain_request_body()
                return
            svc = self.server.service
            if not svc.upload_dir:
                self._send_json(409, {"error": "Upload directory is not configured on this server."})
                self._drain_request_body()
                return
            if not self._is_multipart_request():
                self._send_json(400, {"error": "Expected multipart/form-data request."})
                self._drain_request_body()
                return
            try:
                result = self._parse_multipart(
                    max_file_bytes=svc.max_upload_size_bytes,
                    upload_dir=svc.upload_dir,
                )
            except ValueError as exc:
                self._send_json(413 if "exceeds" in str(exc).lower() else 400, {"error": str(exc)})
                return
            except OSError as exc:
                self._send_json(500, {"error": f"Failed to save uploaded file: {exc}"})
                return

            fields = result["fields"]
            preset_id = fields.get("preset_id", "").strip()
            payload = {
                "input_file": result["file_path"],
                "output_dir": fields.get("output_dir", "").strip() or svc.upload_dir,
                "codec": fields.get("codec", "").strip() or "nvenc_h265",
                "encode_speed": fields.get("encode_speed", "").strip() or "normal",
                "audio_passthrough": fields.get("audio_passthrough", "").lower() in ("true", "1", "on"),
                "delete_source": fields.get("delete_source", "").lower() in ("true", "1", "on"),
                "verbose": fields.get("verbose", "").lower() in ("true", "1", "on"),
                "force": fields.get("force", "").lower() in ("true", "1", "on"),
            }
            if preset_id:
                payload["preset_id"] = preset_id
            try:
                record = svc.submit_jobs_from_payload(payload, source="upload")
            except ValueError as exc:
                # Clean up the uploaded file if job submission fails
                if result["file_path"] and os.path.exists(result["file_path"]):
                    os.unlink(result["file_path"])
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(201, record)
            return

        # ── Stream-convert: upload, convert, stream result back ─────────
        if path == "/stream-convert":
            self._handle_stream_convert()
            return

        # ── Stream-convert cache check ──────────────────────────────────
        if path == "/stream-convert/check":
            self._handle_stream_convert_check()
            return

        if path != "/jobs":
            self._send_json(404, {"error": "Not found."})
            return

        user = self._require_role("operator")
        if not user:
            return
        try:
            payload = self._read_json() if self._is_json_request() else self._read_form()
            record = self.server.service.submit_jobs_from_payload(
                payload,
                source="api" if self._is_json_request() else "ui",
            )
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return
        except ValueError as exc:
            if self._is_json_request():
                self._send_json(400, {"error": str(exc)})
            else:
                self._redirect_with_message(error_message=str(exc))
            return

        if self._is_json_request():
            self._send_json(201, record)
        else:
            self._redirect_with_message(notice=str(record.get("message") or f"Queued job {record['id']}"))

    # ── Stream-convert handler ──────────────────────────────────────
    _STREAM_CACHE_DIRNAME = ".clutch_cache"

    def _stream_cache_dir(self) -> str:
        """Return the cache directory path (under upload_dir)."""
        svc = self.server.service
        return os.path.join(svc.upload_dir, self._STREAM_CACHE_DIRNAME) if svc.upload_dir else ""

    def _stream_cache_id(self, sha256: str, codec: str, encode_speed: str, audio_passthrough: bool) -> str:
        """Build a cache identifier (filename) from input hash + conversion settings."""
        passthrough_flag = "ap" if audio_passthrough else "ae"
        # Sanitize codec/speed for filesystem safety
        safe_codec = "".join(c for c in codec if c.isalnum() or c in "_-")
        safe_speed = "".join(c for c in encode_speed if c.isalnum() or c in "_-")
        safe_sha = "".join(c for c in sha256 if c in "0123456789abcdefABCDEF")
        return f"{safe_sha}_{safe_codec}_{safe_speed}_{passthrough_flag}.mkv"

    def _handle_stream_convert_check(self):
        """Check whether a converted file is already cached on the server.

        Request: JSON ``{sha256, codec, encode_speed, audio_passthrough}``.
        Response: ``{cached: bool, size: int, cache_id: str}``.
        """
        user = self._require_role("operator")
        if not user:
            return
        try:
            payload = self._read_json()
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return

        sha256 = str(payload.get("sha256") or "").strip().lower()
        codec = str(payload.get("codec") or "").strip() or "nvenc_h265"
        encode_speed = str(payload.get("encode_speed") or "").strip() or "normal"
        passthrough = bool(payload.get("audio_passthrough"))
        if isinstance(payload.get("audio_passthrough"), str):
            passthrough = payload["audio_passthrough"].lower() in ("true", "1", "on")

        if not sha256 or len(sha256) < 32:
            self._send_json(400, {"error": "Missing or invalid 'sha256' field."})
            return

        cache_dir = self._stream_cache_dir()
        if not cache_dir:
            self._send_json(200, {"cached": False, "size": 0, "cache_id": ""})
            return

        cache_id = self._stream_cache_id(sha256, codec, encode_speed, passthrough)
        cache_path = os.path.join(cache_dir, cache_id)
        if os.path.isfile(cache_path):
            self._send_json(200, {
                "cached": True,
                "size": os.path.getsize(cache_path),
                "cache_id": cache_id,
            })
        else:
            self._send_json(200, {"cached": False, "size": 0, "cache_id": cache_id})

    def _handle_stream_convert_cached(self, query: dict):
        """Stream a previously-cached converted file using the stream-convert protocol."""
        user = self._require_role("operator")
        if not user:
            return

        cache_id = str(query.get("cache_id") or "").strip()
        if not cache_id or "/" in cache_id or "\\" in cache_id or ".." in cache_id:
            self._send_json(400, {"error": "Invalid cache_id."})
            return

        cache_dir = self._stream_cache_dir()
        if not cache_dir:
            self._send_json(404, {"error": "Cache not configured."})
            return

        cache_path = os.path.join(cache_dir, cache_id)
        if not os.path.isfile(cache_path):
            self._send_json(404, {"error": "Cached file not found."})
            return

        # Send response headers
        self.send_response(200)
        self.send_header("Content-Type", "application/x-clutch-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        writer = _StreamWriter(self.wfile)
        try:
            file_size = os.path.getsize(cache_path)
            writer.event({"type": "status", "detail": "Cache hit. Streaming cached file."})
            writer.event({"type": "file", "filename": cache_id, "size": file_size})
            with open(cache_path, "rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    writer.event({"type": "binary", "size": len(chunk)})
                    writer.raw_chunk(chunk)
            writer.event({"type": "end", "size": file_size})
            writer.terminator()
        except (BrokenPipeError, ConnectionResetError):
            debug("stream-convert/cached: client disconnected")

    def _handle_stream_convert(self):
        """Upload a file, convert it, and stream the result back as it is produced.

        Tail-stream protocol (multiplexed JSON+binary frames):

          - The body is a sequence of NDJSON frames separated by ``\\n``.
          - ``{"type":"status",...}``      — informational text.
          - ``{"type":"progress",...}``    — encoding progress.
          - ``{"type":"file","size":-1}``  — output is starting; size unknown.
          - ``{"type":"binary","size":N}`` — the next exactly N raw bytes
            after the newline are file data; then NDJSON resumes.
          - ``{"type":"end","size":N}``    — successful completion.
          - ``{"type":"error",...}``       — failure.

        Conversion runs in a background thread; the main thread tails the
        HandBrake temp file and forwards new bytes as binary frames while
        also forwarding progress events from a queue.
        """
        import queue as _queue
        import threading as _threading
        import time as _time

        ct = self.headers.get("Content-Type", "")
        cl = self.headers.get("Content-Length", "")
        te = self.headers.get("Transfer-Encoding", "")
        debug(
            f"stream-convert: Content-Type={ct!r} "
            f"Content-Length={cl or '<missing>'} "
            f"Transfer-Encoding={te or '<none>'} "
            f"from {self.address_string()}"
        )

        user = self._require_role("operator")
        if not user:
            self._drain_request_body()
            return

        svc = self.server.service
        if not svc.upload_dir:
            self._send_json(409, {"error": "Upload directory is not configured on this server."})
            self._drain_request_body()
            return

        if not self._is_multipart_request():
            self._send_json(400, {"error": "Expected multipart/form-data request."})
            self._drain_request_body()
            return

        # Parse the multipart upload
        try:
            result = self._parse_multipart(
                max_file_bytes=svc.max_upload_size_bytes,
                upload_dir=svc.upload_dir,
            )
        except ValueError as exc:
            self._send_json(413 if "exceeds" in str(exc).lower() else 400, {"error": str(exc)})
            return
        except OSError as exc:
            self._send_json(500, {"error": f"Failed to save uploaded file: {exc}"})
            return

        fields = result["fields"]
        input_file = result["file_path"]
        output_dir = fields.get("output_dir", "").strip() or svc.upload_dir
        codec = fields.get("codec", "").strip() or "nvenc_h265"
        encode_speed = fields.get("encode_speed", "").strip() or "normal"
        audio_passthrough = fields.get("audio_passthrough", "").lower() in ("true", "1", "on")
        verbose = fields.get("verbose", "").lower() in ("true", "1", "on")
        sha256 = fields.get("sha256", "").strip().lower()

        if not input_file:
            self._send_json(400, {"error": "No file was uploaded."})
            return

        gpu_device = svc._select_gpu_device(codec, encode_speed)

        # Send response headers — from this point we cannot send a JSON
        # error response; failures are reported via {"type":"error"} frames.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-clutch-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        writer = _StreamWriter(self.wfile)
        writer.event({"type": "status", "detail": "Upload complete. Starting conversion."})

        # ── Set up shared state between threads ────────────────────────
        event_queue: _queue.Queue = _queue.Queue()
        runtime_info: Dict[str, object] = {"temp_file": "", "final_output": ""}
        result_box: Dict[str, object] = {"output_path": "", "error": None}

        last_bucket = -1
        last_update_at = 0.0
        started_at = _time.monotonic()

        def _progress_callback(percent: float, _detail: str):
            nonlocal last_bucket, last_update_at
            bucket = int(percent)
            now = _time.time()
            if bucket == last_bucket and now - last_update_at < 2.0 and percent < 100.0:
                return
            last_bucket = bucket
            last_update_at = now
            message = f"Encoding {percent:.1f}%"
            if 0.0 < percent < 100.0:
                elapsed = max(0.0, _time.monotonic() - started_at)
                eta_seconds = (elapsed * (100.0 - percent) / percent) if elapsed > 0.0 else 0.0
                if eta_seconds > 0.0:
                    minutes, secs = divmod(int(eta_seconds), 60)
                    hours, minutes = divmod(minutes, 60)
                    if hours:
                        message = f"{message} - ETA {hours}h{minutes:02d}m"
                    elif minutes:
                        message = f"{message} - ETA {minutes}m{secs:02d}s"
                    else:
                        message = f"{message} - ETA {secs}s"
            event_queue.put({"type": "progress", "percent": round(percent, 1), "detail": message})

        def _runtime_callback(runtime: dict):
            tf = runtime.get("temp_file") or ""
            if tf:
                runtime_info["temp_file"] = tf

        def _convert_thread():
            try:
                output_path = convert_video(
                    input_file,
                    output_dir,
                    codec,
                    encode_speed,
                    audio_passthrough,
                    verbose,
                    show_progress=False,
                    gpu_device=gpu_device,
                    progress_callback=_progress_callback,
                    runtime_callback=_runtime_callback,
                    emit_logs=True,
                )
                result_box["output_path"] = output_path or ""
                if output_path:
                    runtime_info["final_output"] = output_path
            except Exception as exc:
                result_box["error"] = exc

        worker = _threading.Thread(target=_convert_thread, daemon=True)
        worker.start()

        # ── Drain progress events while waiting for the temp file ──────
        wait_started = _time.monotonic()
        while not runtime_info["temp_file"] and worker.is_alive():
            try:
                while True:
                    writer.event(event_queue.get_nowait())
            except _queue.Empty:
                pass
            if _time.monotonic() - wait_started > 120:
                # Conversion did not produce a temp file in 2 minutes; abort
                break
            _time.sleep(0.2)

        # ── If the conversion finished extremely fast (no tail needed) ─
        if not runtime_info["temp_file"]:
            worker.join()
            self._stream_finalize(
                writer, event_queue, input_file, sha256,
                codec, encode_speed, audio_passthrough,
                result_box, total_streamed=0, file_event_sent=False,
            )
            return

        # Open the temp file with retries (HandBrake may still be initialising)
        temp_file = str(runtime_info["temp_file"])
        fd = None
        open_attempts = 0
        while open_attempts < 50 and worker.is_alive():
            try:
                fd = open(temp_file, "rb")
                break
            except OSError:
                open_attempts += 1
                _time.sleep(0.1)

        if fd is None:
            worker.join()
            self._stream_finalize(
                writer, event_queue, input_file, sha256,
                codec, encode_speed, audio_passthrough,
                result_box, total_streamed=0, file_event_sent=False,
            )
            return

        # File event with size=-1 — we don't know the final size yet
        try:
            writer.event({"type": "file", "filename": "output.mkv", "size": -1})
        except (BrokenPipeError, ConnectionResetError):
            fd.close()
            worker.join()
            return

        # ── Tail loop: forward new bytes + progress events ─────────────
        total_streamed = 0
        idle_iterations = 0
        try:
            while True:
                # Drain any pending progress events
                try:
                    while True:
                        writer.event(event_queue.get_nowait())
                except _queue.Empty:
                    pass

                # Read whatever new bytes are available
                data = fd.read(1024 * 1024)
                if data:
                    writer.event({"type": "binary", "size": len(data)})
                    writer.raw_chunk(data)
                    total_streamed += len(data)
                    idle_iterations = 0
                else:
                    if not worker.is_alive():
                        # Final drain — file may have been renamed; the open
                        # fd still points to the same inode, so read() works.
                        final_data = fd.read()
                        while final_data:
                            writer.event({"type": "binary", "size": len(final_data)})
                            writer.raw_chunk(final_data)
                            total_streamed += len(final_data)
                            final_data = fd.read()
                        break
                    idle_iterations += 1
                    _time.sleep(0.2 if idle_iterations < 50 else 0.5)
        except (BrokenPipeError, ConnectionResetError):
            debug("stream-convert: client disconnected during tail-stream")
            try:
                fd.close()
            except OSError:
                pass
            worker.join()
            # Best-effort cleanup of the uploaded file
            try:
                if os.path.isfile(input_file):
                    os.unlink(input_file)
            except OSError:
                pass
            return
        finally:
            try:
                fd.close()
            except OSError:
                pass

        worker.join()
        self._stream_finalize(
            writer, event_queue, input_file, sha256,
            codec, encode_speed, audio_passthrough,
            result_box, total_streamed=total_streamed, file_event_sent=True,
        )

    def _stream_finalize(
        self,
        writer: "_StreamWriter",
        event_queue,
        input_file: str,
        sha256: str,
        codec: str,
        encode_speed: str,
        audio_passthrough: bool,
        result_box: Dict[str, object],
        *,
        total_streamed: int,
        file_event_sent: bool,
    ):
        """Send remaining progress events, end/error frame, and clean up."""
        import queue as _queue

        # Drain any remaining progress events
        try:
            while True:
                writer.event(event_queue.get_nowait())
        except _queue.Empty:
            pass

        output_path = str(result_box.get("output_path") or "")
        err = result_box.get("error")

        try:
            if err:
                writer.event({"type": "error", "detail": f"Conversion failed: {err}"})
            elif not output_path:
                writer.event({"type": "error", "detail": "Conversion produced no output."})
            else:
                # If we never sent the file event (very fast conversion path),
                # send file + bytes now.
                if not file_event_sent and os.path.isfile(output_path):
                    file_size = os.path.getsize(output_path)
                    writer.event({"type": "file", "filename": os.path.basename(output_path), "size": file_size})
                    with open(output_path, "rb") as fh:
                        while True:
                            chunk = fh.read(1024 * 1024)
                            if not chunk:
                                break
                            writer.event({"type": "binary", "size": len(chunk)})
                            writer.raw_chunk(chunk)
                            total_streamed += len(chunk)
                writer.event({
                    "type": "end",
                    "size": total_streamed,
                    "filename": os.path.basename(output_path),
                })
            writer.terminator()
        except (BrokenPipeError, ConnectionResetError):
            debug("stream-convert: client disconnected during finalize")

        # Cache the result if requested and conversion succeeded
        if output_path and sha256 and not err and os.path.isfile(output_path):
            try:
                cache_dir = self._stream_cache_dir()
                if cache_dir:
                    os.makedirs(cache_dir, exist_ok=True)
                    cache_id = self._stream_cache_id(sha256, codec, encode_speed, audio_passthrough)
                    cache_path = os.path.join(cache_dir, cache_id)
                    if not os.path.isfile(cache_path):
                        try:
                            os.link(output_path, cache_path)
                        except OSError:
                            # Different filesystems; fall back to copy
                            import shutil
                            shutil.copy2(output_path, cache_path)
                        debug(f"stream-convert: cached output as {cache_id}")
            except Exception as exc:
                debug(f"stream-convert: failed to cache output: {exc}")

        # Clean up uploaded input + (non-cached) output
        for path_to_clean in (input_file, output_path):
            try:
                if path_to_clean and os.path.isfile(path_to_clean):
                    os.unlink(path_to_clean)
            except OSError:
                pass

    def do_PUT(self):
        path, _query = self._get_request_parts()

        # Auth-related PUT routes
        if self._handle_auth_put(path):
            return

        # Setup redirect
        if self._check_setup_redirect(path):
            return

        if path.startswith("/presets/"):
            user = self._require_role("admin")
            if not user:
                return
            preset_id = path.rsplit("/", 1)[-1]
            try:
                payload = self._read_json()
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            existing = self.server.service.get_preset(preset_id)
            if not existing:
                self._send_json(404, {"error": "Preset not found."})
                return
            try:
                payload["id"] = preset_id
                preset = self.server.service.save_preset(payload)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, preset)
            return

        if path.startswith("/watchers/"):
            user = self._require_role("operator")
            if not user:
                return
            watcher_id = path.rsplit("/", 1)[-1]
            try:
                payload = self._read_json()
                _nbool = lambda k: payload.get(k) if (k in payload and payload[k] is not None) else None
                watcher = self.server.service.update_watcher(
                    watcher_id,
                    str(payload.get("directory") or "").strip(),
                    recursive=bool(payload.get("recursive", False)),
                    poll_interval=float(payload.get("poll_interval") or 5.0),
                    settle_time=float(payload.get("settle_time") or 30.0),
                    delete_source=bool(payload.get("delete_source", False)),
                    output_dir=str(payload.get("output_dir") or "").strip(),
                    codec=str(payload.get("codec") or "").strip(),
                    encode_speed=str(payload.get("encode_speed") or "").strip(),
                    audio_passthrough=_nbool("audio_passthrough"),
                    force=_nbool("force"),
                    preset_id=str(payload.get("preset_id") or "").strip() or None,
                )
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
                return
            except (TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, watcher)
            return

        self._send_json(404, {"error": "Not found."})

    def do_DELETE(self):
        path, query = self._get_request_parts()

        # Auth-related DELETE routes
        if self._handle_auth_delete(path):
            return

        # Setup redirect
        if self._check_setup_redirect(path):
            return

        if path == "/system/logs/files":
            user = self._require_role("admin")
            if not user:
                return
            filename = str(query.get("file") or "").strip()
            if filename:
                deleted = _delete_log_file(filename)
                if not deleted:
                    self._send_json(404, {"error": "File not found."})
                    return
                self._send_json(200, {"deleted": filename})
            else:
                count = _clear_old_log_files()
                self._send_json(200, {"cleared": count})
            return

        if path.startswith("/config/notifications/"):
            user = self._require_role("admin")
            if not user:
                return
            channel_id = path.rsplit("/", 1)[-1]
            deleted = self.server.service.notifications.delete_channel(channel_id)
            if not deleted:
                self._send_json(404, {"error": "Channel not found."})
                return
            self._send_json(200, {"deleted": channel_id})
            return

        if path == "/jobs":
            user = self._require_role("operator")
            if not user:
                return
            mode = query.get("mode", "all")
            if mode not in ("all", "finished", "queued"):
                mode = "all"
            self._send_json(200, self.server.service.clear_jobs(mode=mode))
            return

        if path.startswith("/presets/"):
            user = self._require_role("admin")
            if not user:
                return
            preset_id = path.rsplit("/", 1)[-1]
            deleted = self.server.service.delete_preset(preset_id)
            if not deleted:
                self._send_json(404, {"error": "Preset not found."})
                return
            self._send_json(200, {"id": preset_id, "deleted": True})
            return

        if path.startswith("/watchers/"):
            user = self._require_role("operator")
            if not user:
                return
            watcher_id = path.rsplit("/", 1)[-1]
            watcher = self.server.service.remove_watcher(watcher_id)
            if not watcher:
                self._send_json(404, {"error": "Watcher not found."})
                return
            self._send_json(200, watcher)
            return

        if not path.startswith("/jobs/"):
            self._send_json(404, {"error": "Not found."})
            return

        job_id = path.rsplit("/", 1)[-1]
        user = self._require_role("operator")
        if not user:
            return
        if query.get("purge") == "1":
            deleted = self.server.service.delete_job(job_id)
            if not deleted:
                self._send_json(409, {"error": "Job cannot be removed while active."})
                return
            self._send_json(200, {"id": job_id, "deleted": True})
            return
        record = self.server.service.cancel_job(job_id)
        if not record:
            self._send_json(409, {"error": "Job cannot be cancelled."})
            return
        self._send_json(200, record)

    def log_message(self, fmt: str, *args):
        info(f"HTTP {self.address_string()} - {fmt % args}")


