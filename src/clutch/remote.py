"""Remote client for uploading files and submitting jobs to a Clutch server."""
from __future__ import annotations

import hashlib
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


class _StreamingMultipartBody:
    """Streams a multipart/form-data body from disk without loading the file into memory.

    Reads from three sequential segments: preamble bytes, the file on disk, and footer bytes.
    Reports file upload progress via an optional callback.
    """

    _CHUNK_SIZE = 65536

    def __init__(
        self,
        preamble: bytes,
        file_path: str,
        file_size: int,
        footer: bytes,
        callback: Optional[Callable[[int, int], None]] = None,
    ):
        self._segments: list = [
            ("bytes", preamble),
            ("file", file_path),
            ("bytes", footer),
        ]
        self._total_size = len(preamble) + file_size + len(footer)
        self._file_size = file_size
        self._callback = callback
        # State
        self._seg_idx = 0
        self._seg_offset = 0
        self._fobj: Optional[Any] = None
        self._file_bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        if size == -1 or size is None:
            size = self._total_size
        result = bytearray()
        while len(result) < size and self._seg_idx < len(self._segments):
            seg_type, seg_data = self._segments[self._seg_idx]
            remaining = size - len(result)
            if seg_type == "bytes":
                chunk = seg_data[self._seg_offset:self._seg_offset + remaining]
                self._seg_offset += len(chunk)
                result.extend(chunk)
                if self._seg_offset >= len(seg_data):
                    self._seg_idx += 1
                    self._seg_offset = 0
            else:
                # File segment — stream from disk
                if self._fobj is None:
                    self._fobj = open(seg_data, "rb")
                chunk = self._fobj.read(min(remaining, self._CHUNK_SIZE))
                if not chunk:
                    self._fobj.close()
                    self._fobj = None
                    self._seg_idx += 1
                    self._seg_offset = 0
                else:
                    self._file_bytes_read += len(chunk)
                    result.extend(chunk)
                    if self._callback:
                        self._callback(self._file_bytes_read, self._file_size)
        return bytes(result)

    def __len__(self) -> int:
        return self._total_size

    def close(self):
        if self._fobj is not None:
            self._fobj.close()
            self._fobj = None


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

        Streams the file from disk to avoid loading the entire file into memory.
        Returns the job record dict from the server.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")

        file_size = os.path.getsize(local_path)
        filename = os.path.basename(local_path)
        settings = job_settings or {}

        boundary = uuid.uuid4().hex
        boundary_bytes = f"--{boundary}".encode("utf-8")

        # Build multipart preamble (form fields + file part header)
        parts: list[bytes] = []

        for key, value in settings.items():
            if value is None:
                continue
            parts.append(boundary_bytes + b"\r\n")
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            parts.append(f"{value}\r\n".encode("utf-8"))

        file_header = (
            boundary_bytes + b"\r\n"
            + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
            + b"Content-Type: application/octet-stream\r\n\r\n"
        )
        file_footer = b"\r\n" + boundary_bytes + b"--\r\n"

        preamble = b"".join(parts) + file_header
        total_body_size = len(preamble) + file_size + len(file_footer)

        url = f"{self.server_url}/upload-and-convert"
        hdrs = self._headers({
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })

        req = request.Request(url, method="POST", headers=hdrs)

        body = _StreamingMultipartBody(
            preamble, local_path, file_size, file_footer,
            callback=progress_callback,
        )
        req.data = body
        # Set Content-Length AFTER assigning data — Python's Request.data
        # setter removes any existing Content-Length header (bpo-16464).
        req.add_unredirected_header("Content-length", str(total_body_size))

        try:
            with request.urlopen(req, timeout=600) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw or str(exc)}
            raise RuntimeError(payload.get("error") or str(exc)) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, ConnectionError):
                raise RuntimeError(
                    f"Connection lost during upload to '{self.server_url}'. "
                    "The server may have rejected the request — check the server log for details."
                ) from exc
            raise RuntimeError(f"Could not reach server '{self.server_url}': {exc}") from exc
        finally:
            body.close()

    @staticmethod
    def compute_sha256(local_path: str, callback: Optional[Callable[[int, int], None]] = None) -> str:
        """Compute the SHA-256 hex digest of *local_path*, reporting read progress."""
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")
        total = os.path.getsize(local_path)
        h = hashlib.sha256()
        read = 0
        with open(local_path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
                if callback:
                    callback(read, total)
        return h.hexdigest()

    def check_cached(
        self,
        sha256: str,
        codec: str,
        encode_speed: str,
        audio_passthrough: bool,
    ) -> Dict[str, Any]:
        """Ask the server whether a converted file is already cached.

        Returns ``{cached: bool, size: int, cache_id: str}``.
        """
        body = json.dumps({
            "sha256": sha256,
            "codec": codec,
            "encode_speed": encode_speed,
            "audio_passthrough": audio_passthrough,
        }).encode("utf-8")
        return self._request(
            "POST", "/stream-convert/check",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    def download_cached(
        self,
        cache_id: str,
        local_dest: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        download_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Download a cached converted file via the stream-convert protocol."""
        from urllib.parse import quote

        url = f"{self.server_url}/stream-convert/cached?cache_id={quote(cache_id, safe='')}"
        hdrs = self._headers()
        req = request.Request(url, headers=hdrs, method="GET")
        try:
            resp = request.urlopen(req)
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw or str(exc)}
            raise RuntimeError(payload.get("error") or str(exc)) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach server '{self.server_url}': {exc}") from exc

        try:
            return self._read_stream_response(resp, local_dest, progress_callback, download_callback)
        finally:
            resp.close()

    def stream_convert(
        self,
        local_path: str,
        local_dest: str,
        job_settings: Optional[Dict[str, Any]] = None,
        upload_callback: Optional[Callable[[int, int], None]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        download_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Upload a file, wait for server-side conversion, and stream the result back.

        Uses the ``/stream-convert`` endpoint.  The server converts the file
        synchronously and streams the output back in a single HTTP response.

        *upload_callback(sent, total)* — called during the upload phase.
        *progress_callback(percent, detail)* — called with server conversion progress.
        *download_callback(downloaded, total)* — called during the download phase.

        Returns the local destination path on success.
        Raises ``RuntimeError`` on server-side errors.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")

        file_size = os.path.getsize(local_path)
        filename = os.path.basename(local_path)
        settings = job_settings or {}

        boundary = uuid.uuid4().hex
        boundary_bytes = f"--{boundary}".encode("utf-8")

        # Build multipart preamble
        parts: list[bytes] = []
        for key, value in settings.items():
            if value is None:
                continue
            parts.append(boundary_bytes + b"\r\n")
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            parts.append(f"{value}\r\n".encode("utf-8"))

        file_header = (
            boundary_bytes + b"\r\n"
            + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
            + b"Content-Type: application/octet-stream\r\n\r\n"
        )
        file_footer = b"\r\n" + boundary_bytes + b"--\r\n"
        preamble = b"".join(parts) + file_header
        total_body_size = len(preamble) + file_size + len(file_footer)

        url = f"{self.server_url}/stream-convert"
        hdrs = self._headers({
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })

        req = request.Request(url, method="POST", headers=hdrs)
        stream_body = _StreamingMultipartBody(
            preamble, local_path, file_size, file_footer,
            callback=upload_callback,
        )
        req.data = stream_body
        req.add_unredirected_header("Content-length", str(total_body_size))

        try:
            resp = request.urlopen(req)  # no timeout — conversion can take hours
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw or str(exc)}
            raise RuntimeError(payload.get("error") or str(exc)) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, ConnectionError):
                raise RuntimeError(
                    f"Connection lost during upload to '{self.server_url}'. "
                    "The server may have rejected the request — check the server log."
                ) from exc
            raise RuntimeError(f"Could not reach server '{self.server_url}': {exc}") from exc
        finally:
            stream_body.close()

        # Read the NDJSON+binary response
        try:
            return self._read_stream_response(resp, local_dest, progress_callback, download_callback)
        finally:
            resp.close()

    def _read_stream_response(
        self,
        resp,
        local_dest: str,
        progress_callback: Optional[Callable[[float, str], None]],
        download_callback: Optional[Callable[[int, int], None]],
    ) -> str:
        """Parse the multiplexed stream-convert response.

        The response body is a sequence of NDJSON lines.  Some lines are
        followed by raw binary data:

          * ``{"type":"binary","size":N}`` — read exactly N bytes after
            the newline as raw file data, then resume reading NDJSON.
          * ``{"type":"file","size":-1}``  — output is starting; size unknown.
          * ``{"type":"end","size":N}``    — successful completion.
          * ``{"type":"error",...}``       — failure.
        """
        os.makedirs(os.path.dirname(local_dest) or ".", exist_ok=True)

        fobj = None
        downloaded = 0
        file_size = -1
        try:
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    raise RuntimeError("Server closed connection before completing the response.")
                raw_line = raw_line.rstrip(b"\r\n")
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                etype = event.get("type", "")
                if etype == "progress":
                    if progress_callback:
                        progress_callback(event.get("percent", 0.0), event.get("detail", ""))
                elif etype == "status":
                    if progress_callback:
                        progress_callback(0.0, event.get("detail", ""))
                elif etype == "error":
                    raise RuntimeError(event.get("detail", "Server error during conversion."))
                elif etype == "file":
                    file_size = event.get("size", -1)
                    if fobj is None:
                        fobj = open(local_dest, "wb")
                elif etype == "binary":
                    n = int(event.get("size", 0))
                    if n <= 0:
                        continue
                    if fobj is None:
                        fobj = open(local_dest, "wb")
                    # Read exactly n raw bytes
                    remaining = n
                    while remaining > 0:
                        chunk = resp.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise RuntimeError("Server closed connection mid-binary-frame.")
                        fobj.write(chunk)
                        downloaded += len(chunk)
                        remaining -= len(chunk)
                        if download_callback:
                            download_callback(downloaded, file_size if file_size > 0 else downloaded)
                elif etype == "end":
                    if fobj is None:
                        # Server reported "end" without sending a file
                        raise RuntimeError("Server reported completion but sent no file data.")
                    return local_dest
                # Unknown event types are ignored for forward compatibility
        finally:
            if fobj is not None:
                fobj.close()

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

    def download_file(
        self,
        remote_path: str,
        local_path: str,
        *,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Download a file from the server via GET /download.

        Returns the local file path written.
        """
        from urllib.parse import quote

        url = f"{self.server_url}/download?path={quote(remote_path, safe='')}"
        hdrs = self._headers()
        req = request.Request(url, headers=hdrs, method="GET")

        try:
            with request.urlopen(req, timeout=600) as resp:
                # Read Content-Length if available
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                with open(local_path, "wb") as fobj:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        fobj.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
                return local_path
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw or str(exc)}
            raise RuntimeError(payload.get("error") or str(exc)) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Download failed: {exc}") from exc
