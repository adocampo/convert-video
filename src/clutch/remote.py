"""Remote client for uploading files and submitting jobs to a Clutch server."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from urllib import error, request


class _ProgressFileWrapper:
    """Wraps a file object to report read progress via a callback."""

    def __init__(self, fobj, total_size: int, callback: Optional[Callable[[int, int], None]] = None):
        self._fobj = fobj
        self._total = total_size
        self._read_bytes = 0
        self._callback = callback

    def read(self, size: int = -1) -> bytes:
        data = self._fobj.read(size)
        self._read_bytes += len(data)
        if self._callback:
            self._callback(self._read_bytes, self._total)
        return data

    def __len__(self):
        return self._total


class RemoteClient:
    """HTTP client for interacting with a remote Clutch server."""

    def __init__(self, server_url: str, token: Optional[str] = None):
        self.server_url = server_url.rstrip("/")
        if not self.server_url.startswith(("http://", "https://")):
            self.server_url = "http://" + self.server_url
        self.token = token

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        url = f"{self.server_url}{path}"
        hdrs = self._headers(headers)
        req = request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw or str(exc)}
            raise RuntimeError(payload.get("error") or str(exc)) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach server '{self.server_url}': {exc}") from exc

    def health(self) -> Dict[str, Any]:
        """Check server connectivity via GET /health."""
        return self._request("GET", "/health")

    def get_config(self) -> Dict[str, Any]:
        """Retrieve server configuration via GET /config."""
        return self._request("GET", "/config")

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Retrieve a single job record via GET /jobs/{id}."""
        return self._request("GET", f"/jobs/{job_id}")

    def upload_and_convert(
        self,
        local_path: str,
        job_settings: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Upload a local file and submit a conversion job in one request.

        Returns the job record dict from the server.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")

        file_size = os.path.getsize(local_path)
        filename = os.path.basename(local_path)
        settings = job_settings or {}

        boundary = uuid.uuid4().hex
        boundary_bytes = f"--{boundary}".encode("utf-8")

        # Build multipart body parts
        parts: list[bytes] = []

        # Add form fields
        for key, value in settings.items():
            if value is None:
                continue
            parts.append(boundary_bytes + b"\r\n")
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            parts.append(f"{value}\r\n".encode("utf-8"))

        # File part header
        file_header = (
            boundary_bytes + b"\r\n"
            + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
            + b"Content-Type: application/octet-stream\r\n\r\n"
        )
        file_footer = b"\r\n" + boundary_bytes + b"--\r\n"

        # Calculate total body size for Content-Length
        preamble = b"".join(parts)
        total_body_size = len(preamble) + len(file_header) + file_size + len(file_footer)

        # Build body as a readable object
        url = f"{self.server_url}/upload-and-convert"
        hdrs = self._headers({
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(total_body_size),
        })

        # Assemble body: preamble + file header + file content + footer
        # For progress tracking, we use a custom body that reads from file
        body_parts = preamble + file_header

        req = request.Request(url, method="POST", headers=hdrs)

        # Build full body with progress callback
        with open(local_path, "rb") as fobj:
            # Read file content
            file_data = fobj.read()

        full_body = body_parts + file_data + file_footer

        if progress_callback:
            # Wrap in a progress-tracking object
            class _BodyReader:
                def __init__(self, data: bytes, callback: Callable):
                    self._data = data
                    self._pos = 0
                    self._callback = callback
                    self._file_start = len(body_parts)
                    self._file_end = self._file_start + file_size

                def read(self, size: int = -1) -> bytes:
                    if size == -1:
                        chunk = self._data[self._pos:]
                        self._pos = len(self._data)
                    else:
                        chunk = self._data[self._pos:self._pos + size]
                        self._pos += len(chunk)
                    # Report file upload progress
                    file_progress = max(0, min(self._pos - self._file_start, file_size))
                    self._callback(file_progress, file_size)
                    return chunk

                def __len__(self):
                    return len(self._data)

            req.data = _BodyReader(full_body, progress_callback)
        else:
            req.data = full_body

        try:
            with request.urlopen(req, timeout=600) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw or str(exc)}
            raise RuntimeError(payload.get("error") or str(exc)) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach server '{self.server_url}': {exc}") from exc

    def poll_jobs(
        self,
        job_ids: List[str],
        *,
        interval: float = 2.0,
        on_update: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Poll job statuses until all reach a terminal state.

        Calls *on_update* with the full list of job records on each tick.
        Returns the final list of job records.
        """
        terminal = {"succeeded", "failed", "cancelled", "skipped"}
        while True:
            records = []
            for jid in job_ids:
                try:
                    records.append(self.get_job(jid))
                except RuntimeError:
                    records.append({"id": jid, "status": "unknown"})
            if on_update:
                on_update(records)
            if all(r.get("status") in terminal for r in records):
                return records
            if stop_check and stop_check():
                return records
            time.sleep(interval)
