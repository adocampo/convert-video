from __future__ import annotations

import json
import os
import signal as _signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote, urlparse

from clutch import APP_NAME, get_version
from clutch.auth import has_role
from clutch.converter import (
    get_visible_nvidia_gpus,
    parse_gpu_devices,
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
from clutch.updater import get_update_state

if False:  # TYPE_CHECKING
    from clutch.service import ConversionService


def read_web_asset(name: str) -> str:
    return files("clutch.web").joinpath(name).read_text(encoding="utf-8")


def read_web_asset_bytes(name: str) -> bytes:
    return files("clutch.web").joinpath(name).read_bytes()


_changelog_cache: str | None = None


def _read_changelog() -> str:
    """Read CHANGELOG.md bundled inside the package or from the project root."""
    global _changelog_cache
    if _changelog_cache is not None:
        return _changelog_cache
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
                    _changelog_cache = fh.read()
                return _changelog_cache
            except OSError:
                pass
    _changelog_cache = ""
    return _changelog_cache


class ConversionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, request_handler_class, service: ConversionService):
        super().__init__(server_address, request_handler_class)
        self.service = service

    def handle_error(self, request, client_address):
        import sys, traceback
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        error(f"Exception handling request from {client_address}:\n{traceback.format_exc()}")




class ServiceRequestHandler(BaseHTTPRequestHandler):
    server: ConversionHTTPServer

    ASSET_CONTENT_TYPES = {
        "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", "text"),
        "/assets/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8", "text"),
        "/assets/clutch.png": ("clutch.png", "image/png", "bytes"),
        "/favicon.ico": ("favicon.ico", "image/x-icon", "bytes"),
    }


    def _send_json(self, status_code: int, payload: Dict[str, object]):
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
            content = _read_changelog()
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
            if self._is_json_request():
                self._send_json(200, summary)
            else:
                self._redirect_with_message(notice="Settings saved.")
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

    def do_PUT(self):
        path, _query = self._get_request_parts()

        # Auth-related PUT routes
        if self._handle_auth_put(path):
            return

        # Setup redirect
        if self._check_setup_redirect(path):
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


