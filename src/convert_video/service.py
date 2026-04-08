from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Callable, Dict, List, Optional
from urllib import error, request
from urllib.parse import parse_qs, quote, urlparse

from convert_video import APP_NAME, build_state_dir, get_version
from convert_video.converter import (
    ConversionDetached,
    clear_current_conversion_state,
    convert_video,
    find_existing_converted_output,
    get_current_conversion_paused_seconds,
    get_current_conversion_output_size,
    get_visible_nvidia_gpus,
    is_conversion_process_alive,
    parse_gpu_devices,
    request_conversion_pause_by_pid,
    request_conversion_stop_by_pid,
    request_current_conversion_pause,
    request_current_conversion_resume,
    request_current_conversion_stop,
    uses_nvenc_encoder,
)
from convert_video.iso import display_titles, is_iso_file, scan_iso, select_main_title
from convert_video.mediainfo import VIDEO_EXTENSIONS, check_already_converted
from convert_video.output import error as print_error
from convert_video.output import info, success, warning
from convert_video.updater import get_update_state, install_latest_version, mark_update_installed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now_display() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def format_display_timestamp(timestamp: str) -> str:
    if not timestamp:
        return ""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def format_eta(seconds: float) -> str:
    remaining = max(0, int(round(seconds)))
    hours, remainder = divmod(remaining, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def read_web_asset(name: str) -> str:
    return files("convert_video.web").joinpath(name).read_text(encoding="utf-8")


def read_web_asset_bytes(name: str) -> bytes:
    return files("convert_video.web").joinpath(name).read_bytes()


def normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def path_within_roots(path: str, roots: List[str]) -> bool:
    normalized = normalize_path(path)
    return any(normalized == root or normalized.startswith(f"{root}{os.sep}") for root in roots)


ACTIVE_JOB_STATUSES = ("running", "paused", "cancelling")


def record_has_recoverable_runtime(record: Dict[str, object]) -> bool:
    process_id = int(record.get("process_id") or 0)
    return (
        process_id > 0
        and is_conversion_process_alive(process_id)
        and bool(str(record.get("temp_file") or "").strip())
        and bool(str(record.get("log_file") or "").strip())
        and bool(str(record.get("final_output_file") or "").strip())
    )


@dataclass
class ConversionJob:
    input_file: str
    output_dir: str = ""
    codec: str = "nvenc_h265"
    encode_speed: str = "normal"
    audio_passthrough: bool = False
    delete_source: bool = False
    verbose: bool = False
    force: bool = False
    source: str = "api"
    title: Optional[int] = None
    resolution_override: Optional[str] = None
    audio_tracks: List[dict] = field(default_factory=list)
    submitted_display: str = ""

    def to_record(self) -> Dict[str, object]:
        return {
            "input_file": os.path.abspath(self.input_file),
            "output_dir": os.path.abspath(self.output_dir) if self.output_dir else "",
            "codec": self.codec,
            "encode_speed": self.encode_speed,
            "audio_passthrough": int(self.audio_passthrough),
            "delete_source": int(self.delete_source),
            "verbose": int(self.verbose),
            "force": int(self.force),
            "source": self.source,
            "extra_json": json.dumps(
                {
                    "title": self.title,
                    "resolution_override": self.resolution_override,
                    "audio_tracks": self.audio_tracks,
                    "submitted_display": self.submitted_display,
                }
            ),
        }

    @classmethod
    def from_row(cls, row: Dict[str, object]) -> "ConversionJob":
        extra = json.loads(row.get("extra_json") or "{}")
        return cls(
            input_file=row["input_file"],
            output_dir=row["output_dir"],
            codec=row["codec"],
            encode_speed=row["encode_speed"],
            audio_passthrough=bool(row["audio_passthrough"]),
            delete_source=bool(row["delete_source"]),
            verbose=bool(row["verbose"]),
            force=bool(row["force"]),
            source=row["source"],
            title=extra.get("title"),
            resolution_override=extra.get("resolution_override"),
            audio_tracks=extra.get("audio_tracks") or [],
            submitted_display=str(extra.get("submitted_display") or "").strip(),
        )

    @classmethod
    def from_payload(cls, payload: Dict[str, object], source: str = "api") -> "ConversionJob":
        input_file = str(payload.get("input_file") or "").strip()
        if not input_file:
            raise ValueError("'input_file' is required.")

        encode_speed = str(payload.get("encode_speed") or payload.get("speed") or "normal")
        if encode_speed not in {"slow", "normal", "fast"}:
            raise ValueError("'encode_speed' must be one of: slow, normal, fast.")

        title_value = payload.get("title")
        if title_value in (None, ""):
            title = None
        else:
            title = int(title_value)

        audio_tracks = payload.get("audio_tracks") or []
        if not isinstance(audio_tracks, list):
            raise ValueError("'audio_tracks' must be a list.")

        submitted_display = str(payload.get("submitted_display") or "").strip()

        return cls(
            input_file=input_file,
            output_dir=str(payload.get("output_dir") or "").strip(),
            codec=str(payload.get("codec") or "nvenc_h265"),
            encode_speed=encode_speed,
            audio_passthrough=bool(payload.get("audio_passthrough", False)),
            delete_source=bool(payload.get("delete_source", False)),
            verbose=bool(payload.get("verbose", False)),
            force=bool(payload.get("force", False)),
            source=source,
            title=title,
            resolution_override=str(payload.get("resolution_override") or "").strip() or None,
            audio_tracks=audio_tracks,
            submitted_display=submitted_display,
        )


class JobStore:
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(os.path.expanduser(db_path))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._ensure_schema()
        self._recover_stale_jobs()

    def _ensure_schema(self):
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    input_file TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    codec TEXT NOT NULL,
                    encode_speed TEXT NOT NULL,
                    audio_passthrough INTEGER NOT NULL,
                    delete_source INTEGER NOT NULL,
                    verbose INTEGER NOT NULL,
                    force INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    input_size_bytes INTEGER NOT NULL DEFAULT 0,
                    output_size_bytes INTEGER NOT NULL DEFAULT 0,
                    progress_percent REAL NOT NULL DEFAULT 0,
                    message TEXT,
                    output_file TEXT,
                    process_id INTEGER,
                    temp_file TEXT,
                    log_file TEXT,
                    final_output_file TEXT,
                    resume_on_start INTEGER NOT NULL DEFAULT 0,
                    extra_json TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "progress_percent" not in columns:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN progress_percent REAL NOT NULL DEFAULT 0"
                )
            if "input_size_bytes" not in columns:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN input_size_bytes INTEGER NOT NULL DEFAULT 0"
                )
            if "output_size_bytes" not in columns:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN output_size_bytes INTEGER NOT NULL DEFAULT 0"
                )
            if "process_id" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN process_id INTEGER")
            if "temp_file" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN temp_file TEXT")
            if "log_file" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN log_file TEXT")
            if "final_output_file" not in columns:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN final_output_file TEXT")
            if "resume_on_start" not in columns:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN resume_on_start INTEGER NOT NULL DEFAULT 0"
                )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_config (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    allowed_roots_json TEXT NOT NULL,
                    default_job_settings_json TEXT NOT NULL,
                    worker_count INTEGER NOT NULL DEFAULT 1,
                    gpu_devices_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            service_config_columns = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(service_config)").fetchall()
            }
            if "worker_count" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN worker_count INTEGER NOT NULL DEFAULT 1"
                )
            if "gpu_devices_json" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN gpu_devices_json TEXT NOT NULL DEFAULT '[]'"
                )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchers (
                    id TEXT PRIMARY KEY,
                    directory TEXT NOT NULL UNIQUE,
                    recursive INTEGER NOT NULL,
                    poll_interval REAL NOT NULL,
                    settle_time REAL NOT NULL,
                    delete_source INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            watcher_columns = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(watchers)").fetchall()
            }
            if "delete_source" not in watcher_columns:
                self._conn.execute(
                    "ALTER TABLE watchers ADD COLUMN delete_source INTEGER NOT NULL DEFAULT 0"
                )

    def _recover_stale_jobs(self):
        recoverable = 0
        requeued = 0
        cancelled = 0
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN ('running', 'paused', 'cancelling')"
            ).fetchall()
            for row in rows:
                record = dict(row)
                job_id = str(record["id"])
                status = str(record.get("status") or "")

                if status == "cancelling":
                    request_conversion_stop_by_pid(record.get("process_id"))
                    self._conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'cancelled',
                            finished_at = ?,
                            message = ?,
                            process_id = NULL,
                            temp_file = NULL,
                            log_file = NULL,
                            final_output_file = NULL,
                            resume_on_start = 0
                        WHERE id = ?
                        """,
                        (
                            utc_now(),
                            "Service restarted while cancellation was in progress. Job marked as cancelled.",
                            job_id,
                        ),
                    )
                    cancelled += 1
                    continue

                if record_has_recoverable_runtime(record):
                    recoverable += 1
                    continue

                self._conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'queued',
                        started_at = NULL,
                        finished_at = NULL,
                        progress_percent = 0,
                        output_size_bytes = 0,
                        output_file = NULL,
                        process_id = NULL,
                        temp_file = NULL,
                        log_file = NULL,
                        final_output_file = NULL,
                        resume_on_start = 0,
                        message = ?
                    WHERE id = ?
                    """,
                    (
                        "Service restarted after losing the active encoder process. Returned to queue from the beginning.",
                        job_id,
                    ),
                )
                requeued += 1

        if recoverable:
            info(f"Recovered {recoverable} detached conversion(s) that can continue after restart.")
        if requeued:
            warning(
                f"Recovered {requeued} interrupted job(s) from a previous service run."
            )
        if cancelled:
            warning(f"Marked {cancelled} in-progress cancellation(s) as cancelled during service recovery.")

    def submit(self, job: ConversionJob) -> Dict[str, object]:
        job_id = str(uuid.uuid4())
        submitted_at = utc_now()
        if not job.submitted_display:
            job.submitted_display = local_now_display()
        record = job.to_record()
        try:
            input_size_bytes = os.path.getsize(record["input_file"])
        except OSError:
            input_size_bytes = 0
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, status, input_file, output_dir, codec, encode_speed,
                    audio_passthrough, delete_source, verbose, force, source,
                    submitted_at, started_at, finished_at, input_size_bytes, output_size_bytes,
                    progress_percent, message, output_file, process_id, temp_file, log_file,
                    final_output_file, resume_on_start, extra_json
                ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, 0, 0, NULL, NULL, NULL, NULL, NULL, NULL, 0, ?)
                """,
                (
                    job_id,
                    record["input_file"],
                    record["output_dir"],
                    record["codec"],
                    record["encode_speed"],
                    record["audio_passthrough"],
                    record["delete_source"],
                    record["verbose"],
                    record["force"],
                    record["source"],
                    submitted_at,
                    input_size_bytes,
                    record["extra_json"],
                ),
            )
        return self.get(job_id)

    def _hydrate_record(self, row: sqlite3.Row) -> Dict[str, object]:
        record = dict(row)
        try:
            extra = json.loads(record.get("extra_json") or "{}")
        except json.JSONDecodeError:
            extra = {}
        input_size_bytes = int(record.get("input_size_bytes") or 0)
        if input_size_bytes <= 0:
            try:
                input_size_bytes = os.path.getsize(record["input_file"])
            except OSError:
                input_size_bytes = 0
        output_size_bytes = int(record.get("output_size_bytes") or 0)
        compression_percent = None
        if input_size_bytes > 0 and output_size_bytes > 0:
            compression_percent = (1 - (output_size_bytes / input_size_bytes)) * 100
        record["input_size_bytes"] = input_size_bytes
        record["output_size_bytes"] = output_size_bytes
        record["compression_percent"] = compression_percent
        record["submitted_display"] = str(extra.get("submitted_display") or "").strip() or format_display_timestamp(
            str(record.get("submitted_at") or "")
        )
        return record

    def get(self, job_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._hydrate_record(row) if row else None

    def get_latest_for_input(self, input_file: str) -> Optional[Dict[str, object]]:
        normalized_input = os.path.abspath(input_file)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE input_file = ? ORDER BY submitted_at DESC LIMIT 1",
                (normalized_input,),
            ).fetchone()
        return self._hydrate_record(row) if row else None

    def load_service_config(self) -> Optional[Dict[str, object]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT allowed_roots_json, default_job_settings_json, worker_count, gpu_devices_json FROM service_config WHERE singleton = 1"
            ).fetchone()
        if not row:
            return None
        try:
            allowed_roots = json.loads(row["allowed_roots_json"] or "[]")
        except json.JSONDecodeError:
            allowed_roots = []
        try:
            default_job_settings = json.loads(row["default_job_settings_json"] or "{}")
        except json.JSONDecodeError:
            default_job_settings = {}
        try:
            gpu_devices = parse_gpu_devices(json.loads(row["gpu_devices_json"] or "[]"))
        except (json.JSONDecodeError, ValueError):
            gpu_devices = []
        return {
            "allowed_roots": allowed_roots,
            "default_job_settings": default_job_settings,
            "worker_count": int(row["worker_count"] or 1),
            "gpu_devices": gpu_devices,
        }

    def save_service_config(
        self,
        allowed_roots: List[str],
        default_job_settings: Dict[str, object],
        worker_count: int,
        gpu_devices: List[int],
    ):
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO service_config (singleton, allowed_roots_json, default_job_settings_json, worker_count, gpu_devices_json)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    allowed_roots_json = excluded.allowed_roots_json,
                    default_job_settings_json = excluded.default_job_settings_json,
                    worker_count = excluded.worker_count,
                    gpu_devices_json = excluded.gpu_devices_json
                """,
                (
                    json.dumps(list(allowed_roots)),
                    json.dumps(dict(default_job_settings)),
                    int(worker_count),
                    json.dumps(list(gpu_devices)),
                ),
            )

    def list_watcher_configs(self) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, directory, recursive, poll_interval, settle_time, delete_source FROM watchers ORDER BY directory ASC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "directory": row["directory"],
                "recursive": bool(row["recursive"]),
                "poll_interval": float(row["poll_interval"]),
                "settle_time": float(row["settle_time"]),
                "delete_source": bool(row["delete_source"]),
            }
            for row in rows
        ]

    def save_watcher_config(self, watcher: Dict[str, object]):
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO watchers (id, directory, recursive, poll_interval, settle_time, delete_source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    directory = excluded.directory,
                    recursive = excluded.recursive,
                    poll_interval = excluded.poll_interval,
                    settle_time = excluded.settle_time,
                    delete_source = excluded.delete_source
                """,
                (
                    str(watcher["id"]),
                    str(watcher["directory"]),
                    int(bool(watcher["recursive"])),
                    float(watcher["poll_interval"]),
                    float(watcher["settle_time"]),
                    int(bool(watcher.get("delete_source", False))),
                ),
            )

    def delete_watcher_config(self, watcher_id: str):
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM watchers WHERE id = ?", (watcher_id,))

    def list_jobs(self, limit: int = 50) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._hydrate_record(row) for row in rows]

    def list_active_jobs(self) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN ('running', 'paused', 'cancelling') ORDER BY submitted_at ASC"
            ).fetchall()
        return [self._hydrate_record(row) for row in rows]

    def list_recoverable_jobs(self) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE process_id IS NOT NULL
                  AND temp_file IS NOT NULL
                  AND log_file IS NOT NULL
                  AND final_output_file IS NOT NULL
                  AND (
                    status = 'running'
                    OR (status = 'paused' AND resume_on_start = 1)
                  )
                ORDER BY COALESCE(started_at, submitted_at) ASC
                """
            ).fetchall()
        return [
            record for record in (self._hydrate_record(row) for row in rows)
            if record_has_recoverable_runtime(record)
        ]

    def claim_next(self) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY submitted_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            started_at = utc_now()
            updated = self._conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ?, progress_percent = 0, message = ? WHERE id = ? AND status = 'queued'",
                (started_at, "Preparing conversion.", row["id"]),
            )
            if updated.rowcount != 1:
                return None
        return self.get(row["id"])

    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        progress_percent: Optional[float] = None,
        message: Optional[str] = None,
        output_file: Optional[str] = None,
        output_size_bytes: Optional[int] = None,
    ) -> Optional[Dict[str, object]]:
        finished_at = utc_now() if status in {"succeeded", "failed", "skipped", "cancelled"} else None
        if progress_percent is not None:
            progress_percent = max(0.0, min(progress_percent, 100.0))
        if output_size_bytes is not None:
            output_size_bytes = max(0, int(output_size_bytes))
        clears_runtime = status in {"succeeded", "failed", "skipped", "cancelled", "queued"}
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = COALESCE(?, finished_at),
                    progress_percent = COALESCE(?, progress_percent),
                    message = ?,
                    output_file = COALESCE(?, output_file),
                    output_size_bytes = COALESCE(?, output_size_bytes),
                    process_id = CASE WHEN ? THEN NULL ELSE process_id END,
                    temp_file = CASE WHEN ? THEN NULL ELSE temp_file END,
                    log_file = CASE WHEN ? THEN NULL ELSE log_file END,
                    final_output_file = CASE WHEN ? THEN NULL ELSE final_output_file END,
                    resume_on_start = CASE WHEN ? THEN 0 ELSE resume_on_start END
                WHERE id = ?
                """,
                (
                    status,
                    finished_at,
                    progress_percent,
                    message,
                    output_file,
                    output_size_bytes,
                    int(clears_runtime),
                    int(clears_runtime),
                    int(clears_runtime),
                    int(clears_runtime),
                    int(clears_runtime),
                    job_id,
                ),
            )
        return self.get(job_id)

    def update_progress(
        self,
        job_id: str,
        progress_percent: float,
        message: Optional[str] = None,
        output_size_bytes: Optional[int] = None,
    ) -> Optional[Dict[str, object]]:
        progress_percent = max(0.0, min(progress_percent, 100.0))
        if output_size_bytes is not None:
            output_size_bytes = max(0, int(output_size_bytes))
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE jobs
                SET progress_percent = ?,
                    message = CASE WHEN status = 'running' THEN ? ELSE message END,
                    output_size_bytes = COALESCE(?, output_size_bytes)
                WHERE id = ? AND status IN ('running', 'cancelling')
                """,
                (progress_percent, message, output_size_bytes, job_id),
            )
        return self.get(job_id)

    def pause(self, job_id: str, message: str, *, resume_on_start: bool = False) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE jobs SET status = 'paused', message = ?, resume_on_start = ? WHERE id = ? AND status = 'running'",
                (message, int(bool(resume_on_start)), job_id),
            )
            if updated.rowcount != 1:
                return None
        return self.get(job_id)

    def resume(self, job_id: str, message: str, *, resume_on_start: bool = False) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE jobs SET status = 'running', message = ?, resume_on_start = ? WHERE id = ? AND status = 'paused'",
                (message, int(bool(resume_on_start)), job_id),
            )
            if updated.rowcount != 1:
                return None
        return self.get(job_id)

    def request_cancellation(self, job_id: str, message: str) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE jobs SET status = 'cancelling', message = ?, resume_on_start = 0 WHERE id = ? AND status IN ('running', 'paused')",
                (message, job_id),
            )
            if updated.rowcount != 1:
                return None
        return self.get(job_id)

    def set_runtime(
        self,
        job_id: str,
        *,
        process_id: Optional[int],
        temp_file: str,
        log_file: str,
        final_output_file: str,
        resume_on_start: bool = False,
    ) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE jobs
                SET process_id = ?,
                    temp_file = ?,
                    log_file = ?,
                    final_output_file = ?,
                    resume_on_start = ?
                WHERE id = ?
                """,
                (
                    int(process_id) if process_id else None,
                    str(temp_file or "").strip() or None,
                    str(log_file or "").strip() or None,
                    str(final_output_file or "").strip() or None,
                    int(bool(resume_on_start)),
                    job_id,
                ),
            )
        return self.get(job_id)

    def set_resume_on_start(self, job_id: str, enabled: bool) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET resume_on_start = ? WHERE id = ?",
                (int(bool(enabled)), job_id),
            )
        return self.get(job_id)

    def cancel(self, job_id: str) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE jobs SET status = 'cancelled', finished_at = ?, message = ? WHERE id = ? AND status = 'queued'",
                (utc_now(), "Cancelled before execution.", job_id),
            )
            if updated.rowcount != 1:
                return None
        return self.get(job_id)

    def cancel_all_queued(self, message: str) -> int:
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE jobs SET status = 'cancelled', finished_at = ?, message = ? WHERE status = 'queued'",
                (utc_now(), message),
            )
        return updated.rowcount

    def requeue(self, job_id: str, message: str) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            updated = self._conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    progress_percent = 0,
                    message = ?,
                    output_file = NULL,
                    output_size_bytes = 0,
                    process_id = NULL,
                    temp_file = NULL,
                    log_file = NULL,
                    final_output_file = NULL,
                    resume_on_start = 0
                WHERE id = ?
                """,
                (message, job_id),
            )
            if updated.rowcount != 1:
                return None
        return self.get(job_id)

    def delete(self, job_id: str) -> bool:
        with self._lock, self._conn:
            updated = self._conn.execute(
                "DELETE FROM jobs WHERE id = ? AND status NOT IN ('running', 'paused', 'cancelling')",
                (job_id,),
            )
        return updated.rowcount == 1

    def clear(self) -> Dict[str, int]:
        with self._lock, self._conn:
            counts = self._conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
                    SUM(CASE WHEN status = 'paused' THEN 1 ELSE 0 END) AS paused,
                    SUM(CASE WHEN status = 'cancelling' THEN 1 ELSE 0 END) AS cancelling
                FROM jobs
                """
            ).fetchone()
            deleted = self._conn.execute(
                "DELETE FROM jobs WHERE status NOT IN ('running', 'paused', 'cancelling')"
            )
        running_count = int(counts["running"] if counts and counts["running"] else 0)
        paused_count = int(counts["paused"] if counts and counts["paused"] else 0)
        cancelling_count = int(counts["cancelling"] if counts and counts["cancelling"] else 0)
        return {
            "deleted": int(deleted.rowcount),
            "running": running_count,
            "paused": paused_count,
            "cancelling": cancelling_count,
            "active": running_count + paused_count + cancelling_count,
        }


class DirectoryWatcher(threading.Thread):
    def __init__(
        self,
        service: "ConversionService",
        watcher_id: str,
        directory: str,
        *,
        recursive: bool,
        poll_interval: float,
        settle_time: float,
        delete_source: bool,
    ):
        super().__init__(daemon=True)
        self.service = service
        self.watcher_id = watcher_id
        self.directory = os.path.abspath(directory)
        self.recursive = recursive
        self.poll_interval = poll_interval
        self.settle_time = settle_time
        self.delete_source = delete_source
        self.stop_event = threading.Event()
        self._observed: Dict[str, Dict[str, float]] = {}
        self._submitted = set()
        self._seed_existing_files()

    def to_summary(self) -> Dict[str, object]:
        return {
            "id": self.watcher_id,
            "directory": self.directory,
            "recursive": self.recursive,
            "poll_interval": self.poll_interval,
            "settle_time": self.settle_time,
            "delete_source": self.delete_source,
        }

    def stop(self):
        self.stop_event.set()

    def _seed_existing_files(self):
        now = time.time()
        defaults = self.service.get_default_job_settings()
        for path in self._iter_video_files():
            if self.service.should_ignore_watch_path(path, defaults):
                self._submitted.add(path)
                continue
            try:
                stat = os.stat(path)
            except FileNotFoundError:
                continue
            self._observed[path] = {
                "size": float(stat.st_size),
                "mtime": float(stat.st_mtime),
                "last_change": now,
            }

    def _iter_video_files(self) -> List[str]:
        matches = []
        if self.recursive:
            for root, _, filenames in os.walk(self.directory):
                for filename in filenames:
                    if filename.lower().endswith(VIDEO_EXTENSIONS):
                        matches.append(os.path.join(root, filename))
        else:
            try:
                for filename in os.listdir(self.directory):
                    path = os.path.join(self.directory, filename)
                    if os.path.isfile(path) and filename.lower().endswith(VIDEO_EXTENSIONS):
                        matches.append(path)
            except FileNotFoundError:
                return []
        return matches

    def run(self):
        info(f"Watching directory: {self.directory}")
        while not self.service.stop_event.is_set() and not self.stop_event.is_set():
            current_paths = set()
            now = time.time()
            for path in self._iter_video_files():
                current_paths.add(path)
                payload = self.service.get_default_job_settings()
                if path in self._submitted:
                    if self.service.should_ignore_watch_path(path, payload):
                        continue
                    self._submitted.discard(path)
                    self._observed.pop(path, None)
                previous = self._observed.get(path)
                try:
                    stat = os.stat(path)
                except FileNotFoundError:
                    continue

                signature = {"size": float(stat.st_size), "mtime": float(stat.st_mtime)}
                if previous is None or previous["size"] != signature["size"] or previous["mtime"] != signature["mtime"]:
                    signature["last_change"] = now
                    self._observed[path] = signature
                    continue

                if now - previous["last_change"] < self.settle_time:
                    continue

                if self.service.should_ignore_watch_path(path, payload):
                    self._submitted.add(path)
                    self._observed.pop(path, None)
                    continue
                payload["delete_source"] = self.delete_source
                payload["input_file"] = path
                try:
                    record = self.service.submit_job(ConversionJob.from_payload(payload, source="watch"))
                except ValueError as exc:
                    warning(f"Could not enqueue watched file '{path}': {exc}")
                else:
                    self._submitted.add(path)
                    success(f"Enqueued watched file: {record['id']} -> {path}")

            for missing in list(self._observed):
                if missing not in current_paths:
                    self._observed.pop(missing, None)

            self.stop_event.wait(self.poll_interval)


@dataclass
class WorkerHandle:
    worker_id: str
    thread: threading.Thread
    stop_event: threading.Event


class ConversionService:
    def __init__(
        self,
        db_path: str,
        *,
        allowed_roots: Optional[List[str]] = None,
        default_job_settings: Optional[Dict[str, object]] = None,
        worker_count: int = 1,
        gpu_devices: Optional[object] = None,
        worker_poll_interval: float = 1.0,
    ):
        self.store = JobStore(db_path)
        self.allowed_roots = [os.path.abspath(path) for path in (allowed_roots or [])]
        self.default_job_settings = self._normalize_default_job_settings(default_job_settings or {})
        self.worker_count = self._normalize_worker_count(worker_count)
        self.gpu_devices = parse_gpu_devices(gpu_devices)
        self.worker_poll_interval = worker_poll_interval
        self.stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._workers: Dict[str, WorkerHandle] = {}
        self._workers_lock = threading.Lock()
        self._next_worker_index = 1
        self._gpu_assignment_lock = threading.Lock()
        self._gpu_assignment_index = 0
        self._service_started = False
        self._watchers: Dict[str, DirectoryWatcher] = {}
        self._watchers_lock = threading.Lock()
        self._active_jobs: Dict[str, int] = {}
        self._job_control_lock = threading.Lock()
        self._cancel_requested_jobs: set[str] = set()
        self._recoverable_job_ids: List[str] = []
        self._recoverable_jobs_lock = threading.Lock()
        self._loaded_persisted_state = False
        self._update_monitor_thread: Optional[threading.Thread] = None
        self._update_lock = threading.Lock()
        self._upgrade_in_progress = False
        self._restart_requested = False
        self._restart_command = [sys.argv[0], *sys.argv[1:]]
        self._load_persisted_state(
            [os.path.abspath(path) for path in (allowed_roots or [])],
            self.default_job_settings,
            self.worker_count,
            self.gpu_devices,
        )

    def _load_persisted_state(
        self,
        initial_allowed_roots: List[str],
        initial_default_job_settings: Dict[str, object],
        initial_worker_count: int,
        initial_gpu_devices: List[int],
    ):
        persisted_config = self.store.load_service_config()
        persisted_watchers = self.store.list_watcher_configs()
        self._loaded_persisted_state = persisted_config is not None or bool(persisted_watchers)

        if persisted_config is None:
            self.allowed_roots = list(initial_allowed_roots)
            self.default_job_settings = self._normalize_default_job_settings(initial_default_job_settings)
            self.worker_count = self._normalize_worker_count(initial_worker_count)
            self.gpu_devices = parse_gpu_devices(initial_gpu_devices)
            self.store.save_service_config(
                self.allowed_roots,
                self.default_job_settings,
                self.worker_count,
                self.gpu_devices,
            )
        else:
            self.allowed_roots = [os.path.abspath(path) for path in (persisted_config.get("allowed_roots") or [])]
            self.default_job_settings = self._normalize_default_job_settings(
                persisted_config.get("default_job_settings") or {}
            )
            try:
                self.worker_count = self._normalize_worker_count(persisted_config.get("worker_count") or 1)
            except ValueError:
                self.worker_count = 1
            try:
                self.gpu_devices = parse_gpu_devices(persisted_config.get("gpu_devices"))
            except ValueError:
                self.gpu_devices = []

        with self._watchers_lock:
            for watcher_config in persisted_watchers:
                watcher = DirectoryWatcher(
                    self,
                    str(watcher_config["id"]),
                    str(watcher_config["directory"]),
                    recursive=bool(watcher_config["recursive"]),
                    poll_interval=float(watcher_config["poll_interval"]),
                    settle_time=float(watcher_config["settle_time"]),
                    delete_source=bool(watcher_config.get("delete_source", False)),
                )
                self._watchers[watcher.watcher_id] = watcher

    def has_persisted_configuration(self) -> bool:
        return self._loaded_persisted_state

    def start(self):
        self._service_started = True
        self._prime_recoverable_jobs()
        self._sync_worker_pool()
        self._start_update_monitor()

    def stop(self):
        self._service_started = False

        for record in self.store.list_active_jobs():
            job_id = str(record["id"])
            status = str(record.get("status") or "")
            if status == "running":
                with self._job_control_lock:
                    active_thread_id = self._active_jobs.get(job_id)
                if active_thread_id is not None:
                    request_current_conversion_pause(active_thread_id)
                else:
                    request_conversion_pause_by_pid(record.get("process_id"))
                self.store.pause(
                    job_id,
                    "Service stopped. Conversion paused and will resume when the service starts again.",
                    resume_on_start=True,
                )
                continue
            if status == "paused":
                self.store.set_resume_on_start(job_id, False)
                continue
            if status == "cancelling":
                process_id = int(record.get("process_id") or 0)
                if process_id > 0:
                    request_conversion_stop_by_pid(process_id)

        self.stop_event.set()
        self._wake_event.set()
        with self._workers_lock:
            workers = list(self._workers.values())
            for worker in workers:
                worker.stop_event.set()
        with self._watchers_lock:
            watchers = list(self._watchers.values())
        for watcher in watchers:
            watcher.stop()

    def wait(self):
        while True:
            with self._workers_lock:
                workers = list(self._workers.values())
            if not workers:
                break
            for worker in workers:
                worker.thread.join()

    def _prime_recoverable_jobs(self):
        records = self.store.list_recoverable_jobs()
        with self._recoverable_jobs_lock:
            self._recoverable_job_ids = [str(record["id"]) for record in records]
        if records:
            info(f"Queued {len(records)} detached job(s) for recovery after service start.")

    def _enqueue_recoverable_job(self, job_id: str):
        with self._recoverable_jobs_lock:
            if job_id in self._recoverable_job_ids:
                return
            self._recoverable_job_ids.append(job_id)
        self._wake_event.set()

    def _claim_recoverable_job(self) -> Optional[Dict[str, object]]:
        with self._recoverable_jobs_lock:
            if not self._recoverable_job_ids:
                return None
            job_id = self._recoverable_job_ids.pop(0)
        record = self.store.get(job_id)
        if not record or not record_has_recoverable_runtime(record):
            return None
        status = str(record.get("status") or "")
        if status == "paused" and not bool(record.get("resume_on_start")):
            return None
        if status not in {"running", "paused"}:
            return None
        return record

    def _cleanup_runtime_artifacts(self, record: Dict[str, object], *, remove_temp: bool = False):
        for key in ("log_file", "temp_file"):
            if key == "temp_file" and not remove_temp:
                continue
            path = str(record.get(key) or "").strip()
            if not path:
                continue
            try:
                os.remove(path)
            except OSError:
                continue

    def _normalize_worker_count(self, value: object) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Worker count must be an integer.") from exc
        if count < 1:
            raise ValueError("Worker count must be at least 1.")
        return count

    def _select_gpu_device(self, codec: str, encode_speed: str) -> Optional[int]:
        if not self.gpu_devices or not uses_nvenc_encoder(codec, encode_speed):
            return None
        with self._gpu_assignment_lock:
            gpu_device = self.gpu_devices[self._gpu_assignment_index % len(self.gpu_devices)]
            self._gpu_assignment_index += 1
        return gpu_device

    def _sync_worker_pool(self):
        workers_to_start: List[WorkerHandle] = []
        with self._workers_lock:
            stale_worker_ids = [
                worker_id
                for worker_id, worker in self._workers.items()
                if not worker.thread.is_alive()
            ]
            for worker_id in stale_worker_ids:
                self._workers.pop(worker_id, None)

            enabled_workers = [
                worker
                for worker in self._workers.values()
                if not worker.stop_event.is_set()
            ]
            while len(enabled_workers) < self.worker_count:
                worker_id = f"worker-{self._next_worker_index}"
                self._next_worker_index += 1
                stop_event = threading.Event()
                thread = threading.Thread(
                    target=self._worker_loop,
                    args=(worker_id, stop_event),
                    daemon=True,
                    name=f"{APP_NAME}-{worker_id}",
                )
                worker = WorkerHandle(worker_id=worker_id, thread=thread, stop_event=stop_event)
                self._workers[worker_id] = worker
                enabled_workers.append(worker)
                workers_to_start.append(worker)

            if len(enabled_workers) > self.worker_count:
                excess = len(enabled_workers) - self.worker_count
                for worker in sorted(enabled_workers, key=lambda item: item.worker_id, reverse=True)[:excess]:
                    worker.stop_event.set()

        for worker in workers_to_start:
            worker.thread.start()
        self._wake_event.set()

    def _remove_worker_handle(self, worker_id: str):
        should_resync = False
        with self._workers_lock:
            self._workers.pop(worker_id, None)
            enabled_workers = [
                worker for worker in self._workers.values() if not worker.stop_event.is_set()
            ]
            if self._service_started and not self.stop_event.is_set() and len(enabled_workers) < self.worker_count:
                should_resync = True
        if should_resync:
            self._sync_worker_pool()

    def _start_update_monitor(self):
        if self._update_monitor_thread and self._update_monitor_thread.is_alive():
            return
        self._update_monitor_thread = threading.Thread(
            target=self._update_monitor_loop,
            daemon=True,
            name=f"{APP_NAME}-update-monitor",
        )
        self._update_monitor_thread.start()

    def _update_monitor_loop(self):
        while not self.stop_event.is_set():
            try:
                self.get_update_info(force_check=False)
            except Exception as exc:
                warning(f"Could not refresh release status: {exc}")
            if self.stop_event.wait(3600):
                break

    def is_upgrade_in_progress(self) -> bool:
        with self._update_lock:
            return self._upgrade_in_progress

    def should_restart(self) -> bool:
        with self._update_lock:
            return self._restart_requested

    def get_restart_command(self) -> List[str]:
        with self._update_lock:
            return list(self._restart_command)

    def get_update_info(self, *, force_check: bool = False) -> Dict[str, object]:
        state = get_update_state(force=force_check, quiet=True)
        return {
            "local_version": str(state.get("local_version") or get_version()),
            "remote_version": str(state.get("remote_version") or ""),
            "update_available": bool(state.get("update_available", False)),
            "checked_at": str(state.get("checked_at") or ""),
            "changelog": str(state.get("changelog") or ""),
            "last_error": str(state.get("last_error") or ""),
            "update_in_progress": self.is_upgrade_in_progress(),
        }

    def schedule_self_upgrade(self, shutdown_callback: Callable[[], None]) -> Dict[str, object]:
        update_info = self.get_update_info(force_check=False)
        remote_version = str(update_info.get("remote_version") or "")
        if not update_info.get("update_available"):
            raise ValueError("No newer version is available.")

        with self._update_lock:
            if self._upgrade_in_progress:
                raise ValueError("A service upgrade is already in progress.")
            self._upgrade_in_progress = True

        thread = threading.Thread(
            target=self._run_self_upgrade,
            args=(shutdown_callback, remote_version),
            daemon=True,
            name=f"{APP_NAME}-upgrade",
        )
        thread.start()
        return {
            "message": f"Installing {APP_NAME} {remote_version} and restarting the service.",
            "update_info": self.get_update_info(force_check=False),
        }

    def _run_self_upgrade(self, shutdown_callback: Callable[[], None], target_version: str):
        try:
            info(f"Starting self-upgrade to {target_version or 'latest'}")
            result = install_latest_version()
            if result.returncode != 0:
                raise RuntimeError("Upgrade failed. Check the service logs for details.")

            mark_update_installed(target_version or get_version())
            info(f"Latest version installed. Restarting {APP_NAME} service...")

            with self._update_lock:
                self._restart_requested = True

            self.stop()
            shutdown_callback()
        except Exception as exc:
            print_error(f"Self-upgrade failed: {exc}")
            with self._update_lock:
                self._upgrade_in_progress = False

    def add_watcher(
        self,
        directory: str,
        *,
        recursive: bool,
        poll_interval: float,
        settle_time: float,
        delete_source: bool = False,
    ) -> Dict[str, object]:
        if not directory.strip():
            raise ValueError("Watcher directory is required.")
        self._validate_path(directory, require_directory=True)
        watcher_id = str(uuid.uuid4())
        watcher = DirectoryWatcher(
            self,
            watcher_id,
            directory,
            recursive=recursive,
            poll_interval=poll_interval,
            settle_time=settle_time,
            delete_source=delete_source,
        )
        with self._watchers_lock:
            for existing in self._watchers.values():
                if existing.directory == watcher.directory:
                    raise ValueError(f"Directory is already being watched: {watcher.directory}")
            self._watchers[watcher_id] = watcher
        self.store.save_watcher_config(watcher.to_summary())
        if self._service_started:
            watcher.start()
        return watcher.to_summary()

    def start_watchers(self):
        with self._watchers_lock:
            watchers = list(self._watchers.values())
        for watcher in watchers:
            watcher.start()

    def remove_watcher(self, watcher_id: str) -> Optional[Dict[str, object]]:
        with self._watchers_lock:
            watcher = self._watchers.pop(watcher_id, None)
        if watcher is None:
            return None
        watcher.stop()
        self.store.delete_watcher_config(watcher_id)
        return watcher.to_summary()

    def list_watchers(self) -> List[Dict[str, object]]:
        with self._watchers_lock:
            watchers = list(self._watchers.values())
        return [watcher.to_summary() for watcher in watchers]

    def should_ignore_watch_path(self, path: str, job_settings: Optional[Dict[str, object]] = None) -> bool:
        settings = job_settings or self.get_default_job_settings()
        if bool(settings.get("force", False)):
            return False

        normalized = normalize_path(path)
        latest = self.store.get_latest_for_input(normalized)
        if latest and latest["status"] in {"queued", "running", "paused", "cancelling"}:
            return True

        codec = str(settings.get("codec") or "nvenc_h265")
        if check_already_converted(normalized, codec, False, quiet=True) == "skip":
            return True

        output_dir = str(settings.get("output_dir") or "").strip()
        if find_existing_converted_output(normalized, output_dir, codec):
            return True

        if latest and latest["status"] == "succeeded":
            output_file = str(latest.get("output_file") or "").strip()
            if output_file and os.path.exists(output_file):
                return True

        return False

    def _normalize_default_job_settings(self, payload: Dict[str, object]) -> Dict[str, object]:
        normalized = {
            "output_dir": str(payload.get("output_dir") or "").strip(),
            "codec": str(payload.get("codec") or "nvenc_h265"),
            "encode_speed": str(payload.get("encode_speed") or payload.get("speed") or "normal"),
            "audio_passthrough": bool(payload.get("audio_passthrough", False)),
            "delete_source": bool(payload.get("delete_source", False)),
            "verbose": bool(payload.get("verbose", False)),
            "force": bool(payload.get("force", False)),
        }
        if normalized["encode_speed"] not in {"slow", "normal", "fast"}:
            raise ValueError("Default encode speed must be one of: slow, normal, fast.")
        return normalized

    def get_default_job_settings(self) -> Dict[str, object]:
        return dict(self.default_job_settings)

    def update_service_settings(self, payload: Dict[str, object]) -> Dict[str, object]:
        next_worker_count = self.worker_count
        next_gpu_devices = list(self.gpu_devices)
        if "worker_count" in payload:
            next_worker_count = self._normalize_worker_count(payload.get("worker_count"))
        if "gpu_devices" in payload:
            next_gpu_devices = parse_gpu_devices(payload.get("gpu_devices"))

        if "allowed_roots" in payload:
            allowed_roots = payload.get("allowed_roots") or []
            if not isinstance(allowed_roots, list):
                raise ValueError("'allowed_roots' must be a list.")
            normalized_roots = []
            for path in allowed_roots:
                path_str = str(path).strip()
                if not path_str:
                    continue
                normalized = os.path.abspath(path_str)
                if not os.path.exists(normalized):
                    raise ValueError(f"Path does not exist on this machine: {normalized}")
                if not os.path.isdir(normalized):
                    raise ValueError(f"Allowed root must be a directory: {normalized}")
                normalized_roots.append(normalized)
            self.allowed_roots = normalized_roots

        self.default_job_settings = self._normalize_default_job_settings(
            {
                **self.default_job_settings,
                **payload.get("default_job_settings", {}),
            }
        )
        worker_count_changed = next_worker_count != self.worker_count
        self.worker_count = next_worker_count
        self.gpu_devices = next_gpu_devices
        self.store.save_service_config(
            self.allowed_roots,
            self.default_job_settings,
            self.worker_count,
            self.gpu_devices,
        )
        if worker_count_changed and self._service_started:
            self._sync_worker_pool()
        return self.get_service_summary()

    def _validate_path(
        self,
        path: str,
        *,
        allow_missing: bool = False,
        require_file: bool = False,
        require_directory: bool = False,
    ):
        normalized = normalize_path(path)
        if self.allowed_roots and not path_within_roots(normalized, self.allowed_roots):
            raise ValueError(f"Path is outside allowed roots: {normalized}")
        if not allow_missing and not os.path.exists(normalized):
            raise ValueError(f"Path does not exist on this machine: {normalized}")
        if require_file and os.path.exists(normalized) and not os.path.isfile(normalized):
            raise ValueError(f"Input path must be a file: {normalized}")
        if require_directory and os.path.exists(normalized) and not os.path.isdir(normalized):
            raise ValueError(f"Path must be a directory: {normalized}")

    def _is_browsable_input_file(self, path: str) -> bool:
        return path.lower().endswith(VIDEO_EXTENSIONS) or path.lower().endswith(".iso")

    def _collect_directory_input_files(self, directory: str, *, recursive: bool) -> List[str]:
        normalized_directory = normalize_path(directory)
        matches: List[str] = []

        if recursive:
            for root, dirnames, filenames in os.walk(normalized_directory):
                dirnames.sort()
                for filename in sorted(filenames):
                    entry_path = normalize_path(os.path.join(root, filename))
                    if self._is_browsable_input_file(entry_path):
                        matches.append(entry_path)
            return matches

        try:
            with os.scandir(normalized_directory) as scanner:
                for entry in scanner:
                    entry_path = normalize_path(entry.path)
                    try:
                        is_file = entry.is_file()
                    except OSError:
                        continue
                    if is_file and self._is_browsable_input_file(entry_path):
                        matches.append(entry_path)
        except PermissionError as exc:
            raise ValueError(f"Permission denied: {normalized_directory}: {exc}") from exc

        matches.sort()
        return matches

    def _get_default_browser_path(self, restricted_roots: List[str]) -> str:
        preferred_path = normalize_path(os.path.expanduser("~"))

        if restricted_roots:
            if path_within_roots(preferred_path, restricted_roots):
                return preferred_path
            return restricted_roots[0]

        if os.path.isdir(preferred_path):
            return preferred_path
        return os.sep

    def browse_paths(self, path: str, *, selection: str, scope: str, show_hidden: bool = False) -> Dict[str, object]:
        if selection not in {"file", "directory"}:
            raise ValueError("Browse selection must be 'file' or 'directory'.")
        if scope not in {"allowed", "all"}:
            raise ValueError("Browse scope must be 'allowed' or 'all'.")

        restricted_roots = self.allowed_roots if scope == "allowed" and self.allowed_roots else []
        if path.strip():
            current_path = normalize_path(path)
        else:
            current_path = self._get_default_browser_path(restricted_roots)

        if not os.path.exists(current_path):
            raise ValueError(f"Path does not exist on this machine: {current_path}")
        if os.path.isfile(current_path):
            current_path = os.path.dirname(current_path) or os.sep
        if not os.path.isdir(current_path):
            raise ValueError(f"Path must be a directory: {current_path}")
        if restricted_roots and not path_within_roots(current_path, restricted_roots):
            raise ValueError(f"Path is outside allowed roots: {current_path}")

        entries = []
        try:
            with os.scandir(current_path) as scanner:
                for entry in scanner:
                    entry_path = normalize_path(entry.path)
                    if not show_hidden and entry.name.startswith("."):
                        continue
                    try:
                        is_dir = entry.is_dir()
                        is_file = entry.is_file()
                    except OSError:
                        continue

                    if restricted_roots and not path_within_roots(entry_path, restricted_roots):
                        continue
                    if is_dir:
                        entries.append(
                            {
                                "name": entry.name,
                                "path": entry_path,
                                "kind": "directory",
                                "selectable": selection == "directory",
                            }
                        )
                        continue
                    if selection == "directory":
                        continue
                    if not is_file or not self._is_browsable_input_file(entry_path):
                        continue
                    entries.append(
                        {
                            "name": entry.name,
                            "path": entry_path,
                            "kind": "file",
                            "selectable": True,
                        }
                    )
        except PermissionError as exc:
            raise ValueError(f"Permission denied: {current_path}: {exc}") from exc

        entries.sort(key=lambda item: (0 if item["kind"] == "directory" else 1, item["name"].lower()))

        parent = os.path.dirname(current_path.rstrip(os.sep)) or os.sep
        if current_path == os.sep:
            parent = ""
        if restricted_roots and parent and not path_within_roots(parent, restricted_roots):
            parent = ""

        return {
            "path": current_path,
            "parent": parent,
            "entries": entries,
            "selection": selection,
            "scope": scope,
            "roots": restricted_roots or [os.sep],
            "restricted": bool(restricted_roots),
            "show_hidden": bool(show_hidden),
        }

    def submit_job(self, job: ConversionJob) -> Dict[str, object]:
        self._validate_path(job.input_file, require_file=True)
        if job.output_dir:
            output_parent = job.output_dir if os.path.exists(job.output_dir) else os.path.dirname(job.output_dir) or "."
            self._validate_path(output_parent, allow_missing=False, require_directory=True)
        record = self.store.submit(job)
        info(f"Queued job {record['id']} for {job.input_file}")
        self._wake_event.set()
        return record

    def submit_jobs_from_payload(self, payload: Dict[str, object], *, source: str = "api") -> Dict[str, object]:
        input_path = str(payload.get("input_file") or "").strip()
        if not input_path:
            raise ValueError("'input_file' is required.")

        input_kind = str(payload.get("input_kind") or "file").strip().lower() or "file"
        if input_kind not in {"file", "directory"}:
            raise ValueError("'input_kind' must be one of: file, directory.")

        recursive_value = payload.get("recursive", False)
        if isinstance(recursive_value, str):
            recursive = recursive_value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            recursive = bool(recursive_value)

        if input_kind == "file":
            job = ConversionJob.from_payload(payload, source=source)
            return self.submit_job(job)

        self._validate_path(input_path, require_directory=True)
        matched_paths = self._collect_directory_input_files(input_path, recursive=recursive)
        if not matched_paths:
            raise ValueError(f"No supported video files found in directory: {normalize_path(input_path)}")

        first_id = ""
        for matched_path in matched_paths:
            job_payload = dict(payload)
            job_payload["input_file"] = matched_path
            record = self.submit_job(ConversionJob.from_payload(job_payload, source=source))
            if not first_id:
                first_id = str(record["id"])

        directory_label = normalize_path(input_path)
        recursive_label = " recursively" if recursive else ""
        count = len(matched_paths)
        return {
            "count": count,
            "first_id": first_id,
            "input_kind": "directory",
            "input_path": directory_label,
            "recursive": recursive,
            "message": f"Queued {count} job{'s' if count != 1 else ''} from directory{recursive_label}: {directory_label}",
        }

    def list_jobs(self, limit: int = 50) -> List[Dict[str, object]]:
        return self.store.list_jobs(limit=limit)

    def get_job(self, job_id: str) -> Optional[Dict[str, object]]:
        return self.store.get(job_id)

    def cancel_job(self, job_id: str) -> Optional[Dict[str, object]]:
        record = self.store.get(job_id)
        if not record:
            return None
        if record["status"] == "queued":
            cancelled = self.store.cancel(job_id)
            if cancelled:
                return cancelled
            record = self.store.get(job_id)
            if not record:
                return None
        if record["status"] in {"running", "paused"}:
            return self._request_running_job_cancel(job_id)
        return None

    def pause_job(self, job_id: str) -> Optional[Dict[str, object]]:
        record = self.store.get(job_id)
        if not record:
            return None
        if record["status"] != "running":
            return None
        return self._request_running_job_pause(job_id)

    def resume_job(self, job_id: str) -> Optional[Dict[str, object]]:
        record = self.store.get(job_id)
        if not record:
            return None
        if record["status"] != "paused":
            return None
        return self._request_running_job_resume(job_id)

    def retry_job(self, job_id: str) -> Optional[Dict[str, object]]:
        record = self.store.get(job_id)
        if not record:
            return None
        if record["status"] not in {"failed", "cancelled"}:
            return None

        self._validate_path(str(record["input_file"]), require_file=True)
        output_dir = str(record.get("output_dir") or "").strip()
        if output_dir:
            output_parent = output_dir if os.path.exists(output_dir) else os.path.dirname(output_dir) or "."
            self._validate_path(output_parent, allow_missing=False, require_directory=True)

        retried = self.store.requeue(job_id, "Queued for retry.")
        if retried:
            info(f"Queued retry for job {job_id} -> {record['input_file']}")
            self._wake_event.set()
        return retried

    def delete_job(self, job_id: str) -> bool:
        return self.store.delete(job_id)

    def clear_jobs(self) -> Dict[str, int]:
        return self.store.clear()

    def get_service_summary(self, *, force_update_check: bool = False) -> Dict[str, object]:
        return {
            "allowed_roots": self.allowed_roots,
            "default_job_settings": self.get_default_job_settings(),
            "watchers": self.list_watchers(),
            "worker_count": self.worker_count,
            "gpu_devices": list(self.gpu_devices),
            "visible_nvidia_gpus": get_visible_nvidia_gpus(),
            "update_info": self.get_update_info(force_check=force_update_check),
        }

    def _request_running_job_pause(self, job_id: str) -> Optional[Dict[str, object]]:
        if os.name == "nt":
            raise ValueError("Pause and resume are only supported on Unix-like systems.")

        record = self.store.get(job_id)
        if not record:
            return None

        with self._job_control_lock:
            active_thread_id = self._active_jobs.get(job_id)

        if active_thread_id is None:
            if not request_conversion_pause_by_pid(record.get("process_id")):
                raise ValueError("Could not pause the active HandBrake process.")
        elif not request_current_conversion_pause(active_thread_id):
            raise ValueError("Could not pause the active HandBrake process.")

        paused = self.store.pause(job_id, "Paused manually.", resume_on_start=False)
        if not paused and active_thread_id is not None:
            request_current_conversion_resume(active_thread_id)
        return paused

    def _request_running_job_resume(self, job_id: str) -> Optional[Dict[str, object]]:
        if os.name == "nt":
            raise ValueError("Pause and resume are only supported on Unix-like systems.")

        record = self.store.get(job_id)
        if not record:
            return None

        with self._job_control_lock:
            active_thread_id = self._active_jobs.get(job_id)

        if active_thread_id is None:
            if not record_has_recoverable_runtime(record):
                raise ValueError("Paused job is no longer attached to an active worker.")
            resumed = self.store.resume(
                job_id,
                "Waiting for a worker to resume the paused conversion.",
                resume_on_start=True,
            )
            if resumed:
                self._enqueue_recoverable_job(job_id)
            return resumed
        if not request_current_conversion_resume(active_thread_id):
            raise ValueError("Could not resume the active HandBrake process.")

        resumed = self.store.resume(job_id, "Resumed manually.", resume_on_start=False)
        if not resumed:
            request_current_conversion_pause(active_thread_id)
        return resumed

    def _request_running_job_cancel(self, job_id: str) -> Optional[Dict[str, object]]:
        record = self.store.get(job_id)
        if not record:
            return None

        with self._job_control_lock:
            active_thread_id = self._active_jobs.get(job_id)
            self._cancel_requested_jobs.add(job_id)

        if active_thread_id is not None:
            request_current_conversion_stop(active_thread_id)
            return self.store.request_cancellation(job_id, "Cancellation requested.")

        if record_has_recoverable_runtime(record):
            request_conversion_stop_by_pid(record.get("process_id"))
            self._cleanup_runtime_artifacts(record, remove_temp=True)
            return self.store.update_status(job_id, "cancelled", message="Cancelled while detached from the service.")

        return self.store.request_cancellation(job_id, "Cancellation requested.")

    def _consume_cancel_request(self, job_id: str) -> bool:
        with self._job_control_lock:
            if job_id not in self._cancel_requested_jobs:
                return False
            self._cancel_requested_jobs.remove(job_id)
            return True

    def _set_active_job(self, job_id: Optional[str]):
        if job_id is None:
            return
        with self._job_control_lock:
            self._active_jobs[job_id] = threading.get_ident()

    def _clear_active_job(self, job_id: str):
        with self._job_control_lock:
            self._active_jobs.pop(job_id, None)
            self._cancel_requested_jobs.discard(job_id)

    def _worker_loop(self, worker_id: str, worker_stop_event: threading.Event):
        info(f"Worker thread started: {worker_id}")
        while not self.stop_event.is_set() and not worker_stop_event.is_set():
            record = None
            try:
                record = self._claim_recoverable_job()
                if not record:
                    record = self.store.claim_next()
                if not record:
                    self._wake_event.wait(self.worker_poll_interval)
                    self._wake_event.clear()
                    continue
                if self.stop_event.is_set() or worker_stop_event.is_set():
                    if record_has_recoverable_runtime(record):
                        self._enqueue_recoverable_job(str(record["id"]))
                        continue
                    self.store.requeue(
                        record["id"],
                        "Service stopped before this job started. Returned to queue."
                        if self.stop_event.is_set()
                        else "Worker stopped before this job started. Returned to queue.",
                    )
                    continue
                self._execute_job(record)
            except Exception as exc:
                print_error(f"Worker loop error: {exc}")
                # Mark the job as failed if we have a record
                if record:
                    try:
                        self.store.update_status(
                            record["id"], "failed", message=f"Worker error: {exc}"
                        )
                    except Exception:
                        pass
                # Brief pause to avoid tight error loops
                time.sleep(2)
        clear_current_conversion_state()
        self._remove_worker_handle(worker_id)
        info(f"Worker thread stopped: {worker_id}")

    def _execute_job(self, record: Dict[str, object]):
        job_id = record["id"]
        input_file = record.get("input_file", "<unknown>")
        self._set_active_job(job_id)
        try:
            job = ConversionJob.from_row(record)
            info(f"[{job_id[:8]}] Processing: {os.path.basename(job.input_file)}")

            if is_iso_file(job.input_file):
                status, output_path, message = self._execute_iso_job(job_id, job, record)
            else:
                status, output_path, message = self._execute_regular_job(job_id, job, record)

            if status == "succeeded" and output_path:
                runtime_record = self.store.get(job_id) or record
                try:
                    output_size_bytes = os.path.getsize(output_path)
                except OSError:
                    output_size_bytes = 0
                if job.delete_source:
                    try:
                        os.remove(job.input_file)
                    except OSError as exc:
                        warning(f"Could not delete source file '{job.input_file}': {exc}")
                self.store.update_status(
                    job_id,
                    "succeeded",
                    progress_percent=100.0,
                    output_file=output_path,
                    output_size_bytes=output_size_bytes,
                    message=message,
                )
                self._cleanup_runtime_artifacts(runtime_record)
                info(f"[{job_id[:8]}] Succeeded: {os.path.basename(output_path)}")
            elif status == "queued":
                runtime_record = self.store.get(job_id) or record
                self.store.requeue(job_id, message)
                self._cleanup_runtime_artifacts(runtime_record, remove_temp=True)
                warning(f"[{job_id[:8]}] Returned to queue: {message}")
            elif status == "cancelled":
                runtime_record = self.store.get(job_id) or record
                self.store.update_status(job_id, "cancelled", message=message)
                self._cleanup_runtime_artifacts(runtime_record, remove_temp=True)
                warning(f"[{job_id[:8]}] Cancelled: {message}")
            elif status == "skipped":
                self.store.update_status(job_id, "skipped", progress_percent=100.0, message=message)
                info(f"[{job_id[:8]}] Skipped: {message}")
            elif status == "detached":
                info(f"[{job_id[:8]}] Detached: {message}")
            else:
                runtime_record = self.store.get(job_id) or record
                self.store.update_status(job_id, "failed", message=message)
                self._cleanup_runtime_artifacts(runtime_record, remove_temp=True)
                print_error(f"[{job_id[:8]}] Failed: {message}")
        except Exception as exc:
            print_error(f"[{job_id[:8]}] Job error for '{input_file}': {exc}")
            try:
                runtime_record = self.store.get(job_id) or record
                self.store.update_status(job_id, "failed", message=str(exc))
                self._cleanup_runtime_artifacts(runtime_record, remove_temp=True)
            except Exception:
                pass
        finally:
            self._clear_active_job(job_id)

    def _build_progress_callback(self, job_id: str):
        last_bucket = -1
        last_update_at = 0.0
        last_logged_bucket = -1
        started_at = time.monotonic()

        def callback(percent: float, _detail: str):
            nonlocal last_bucket, last_update_at, last_logged_bucket
            bucket = int(percent)
            now = time.time()
            if bucket == last_bucket and now - last_update_at < 2.0 and percent < 100.0:
                return
            last_bucket = bucket
            last_update_at = now
            message = f"Encoding {percent:.1f}%"
            if 0.0 < percent < 100.0:
                paused_seconds = get_current_conversion_paused_seconds()
                elapsed = max(0.0, time.monotonic() - started_at - paused_seconds)
                eta_seconds = (elapsed * (100.0 - percent) / percent) if elapsed > 0.0 else 0.0
                if eta_seconds > 0.0:
                    message = f"{message} - ETA {format_eta(eta_seconds)}"
            self.store.update_progress(
                job_id,
                percent,
                message=message,
                output_size_bytes=get_current_conversion_output_size(),
            )
            log_bucket = int(percent // 5) * 5
            if log_bucket > last_logged_bucket or percent >= 100.0:
                last_logged_bucket = log_bucket
                info(f"[{job_id[:8]}] {message}")

        return callback

    def _execute_regular_job(self, job_id: str, job: ConversionJob, record: Dict[str, object]) -> tuple[str, str, str]:
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."

        existing_process_id = int(record.get("process_id") or 0) or None
        if existing_process_id:
            if record.get("status") == "paused" and bool(record.get("resume_on_start")):
                self.store.resume(job_id, "Resuming conversion after service restart.", resume_on_start=False)
            else:
                self.store.set_resume_on_start(job_id, False)

        if not job.force:
            status = check_already_converted(job.input_file, job.codec, job.force)
            if status == "skip":
                return "skipped", "", "File already converted."

            existing_output = find_existing_converted_output(job.input_file, job.output_dir, job.codec)
            if existing_output:
                output_name = os.path.basename(existing_output)
                return "skipped", "", f"Converted output already exists: {output_name}."

        gpu_device = self._select_gpu_device(job.codec, job.encode_speed)
        if gpu_device is not None:
            info(f"[{job_id[:8]}] Using NVENC GPU {gpu_device}")

        try:
            output_path = convert_video(
                job.input_file,
                job.output_dir,
                job.codec,
                job.encode_speed,
                job.audio_passthrough,
                job.verbose,
                title=job.title,
                resolution_override=job.resolution_override,
                audio_tracks=job.audio_tracks,
                show_progress=False,
                gpu_device=gpu_device,
                progress_callback=self._build_progress_callback(job_id),
                progress_log_path=str(record.get("log_file") or ""),
                existing_process_id=existing_process_id,
                existing_temp_file=str(record.get("temp_file") or ""),
                existing_output_file=str(record.get("final_output_file") or ""),
                initial_progress=float(record.get("progress_percent") or 0.0),
                resume_existing_process=bool(record.get("resume_on_start")),
                detach_when=self.stop_event.is_set,
                runtime_callback=lambda runtime: self.store.set_runtime(
                    job_id,
                    process_id=runtime.get("process_id"),
                    temp_file=str(runtime.get("temp_file") or ""),
                    log_file=str(runtime.get("log_file") or ""),
                    final_output_file=str(runtime.get("final_output_file") or ""),
                    resume_on_start=False,
                ),
            )
        except ConversionDetached:
            return "detached", "", "Service stopped while the conversion was still running."
        if output_path:
            return "succeeded", output_path, "Conversion successful."
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."
        if self.stop_event.is_set():
            return "detached", "", "Service stopped while the conversion was still running."
        return "failed", "", "Conversion failed."

    def _execute_iso_job(self, job_id: str, job: ConversionJob, record: Dict[str, object]) -> tuple[str, str, str]:
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."

        existing_process_id = int(record.get("process_id") or 0) or None
        if existing_process_id:
            if record.get("status") == "paused" and bool(record.get("resume_on_start")):
                self.store.resume(job_id, "Resuming conversion after service restart.", resume_on_start=False)
            else:
                self.store.set_resume_on_start(job_id, False)

        titles = scan_iso(job.input_file)
        if not titles:
            raise RuntimeError(f"No titles found in ISO: {job.input_file}")

        if job.title is None:
            main_title = select_main_title(titles)
        else:
            main_title = next((title for title in titles if title["index"] == job.title), None)
            if main_title is None:
                raise RuntimeError(f"ISO title {job.title} not found in {job.input_file}")

        display_titles(titles, main_title["index"])
        info(f"Selected ISO title {main_title['index']} ({main_title['duration_str']})")
        gpu_device = self._select_gpu_device(job.codec, job.encode_speed)
        if gpu_device is not None:
            info(f"[{job_id[:8]}] Using NVENC GPU {gpu_device}")
        try:
            output_path = convert_video(
                job.input_file,
                job.output_dir,
                job.codec,
                job.encode_speed,
                job.audio_passthrough,
                job.verbose,
                title=main_title["index"],
                resolution_override=job.resolution_override or main_title.get("resolution") or None,
                audio_tracks=job.audio_tracks or main_title.get("audio_tracks", []),
                show_progress=False,
                gpu_device=gpu_device,
                progress_callback=self._build_progress_callback(job_id),
                progress_log_path=str(record.get("log_file") or ""),
                existing_process_id=existing_process_id,
                existing_temp_file=str(record.get("temp_file") or ""),
                existing_output_file=str(record.get("final_output_file") or ""),
                initial_progress=float(record.get("progress_percent") or 0.0),
                resume_existing_process=bool(record.get("resume_on_start")),
                detach_when=self.stop_event.is_set,
                runtime_callback=lambda runtime: self.store.set_runtime(
                    job_id,
                    process_id=runtime.get("process_id"),
                    temp_file=str(runtime.get("temp_file") or ""),
                    log_file=str(runtime.get("log_file") or ""),
                    final_output_file=str(runtime.get("final_output_file") or ""),
                    resume_on_start=False,
                ),
            )
        except ConversionDetached:
            return "detached", "", "Service stopped while the conversion was still running."
        if output_path:
            return "succeeded", output_path, "Conversion successful."
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."
        if self.stop_event.is_set():
            return "detached", "", "Service stopped while the conversion was still running."
        return "failed", "", "Conversion failed."


class ConversionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, request_handler_class, service: ConversionService):
        super().__init__(server_address, request_handler_class)
        self.service = service


class ServiceRequestHandler(BaseHTTPRequestHandler):
    server: ConversionHTTPServer

    ASSET_CONTENT_TYPES = {
        "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8", "text"),
        "/assets/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8", "text"),
        "/assets/clutch.png": ("clutch.png", "image/png", "bytes"),
        "/favicon.ico": ("favicon.ico", "image/x-icon", "bytes"),
    }

    DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>clutch service</title>
    <style>
        :root {
            --bg: #f3efe6;
            --panel: rgba(255, 251, 245, 0.94);
            --line: #d8cfc2;
            --text: #1d2935;
            --muted: #5b6875;
            --accent: #0d6b61;
            --accent-strong: #0a4d46;
            --warn: #aa6d00;
            --fail: #9f2d2d;
            --ok: #22684a;
            --shadow: 0 20px 50px rgba(29, 41, 53, 0.12);
        }

        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
            color: var(--text);
            background:
                radial-gradient(circle at top left, rgba(13, 107, 97, 0.18), transparent 28%),
                radial-gradient(circle at right, rgba(170, 109, 0, 0.12), transparent 22%),
                linear-gradient(180deg, #fbf8f2 0%, var(--bg) 100%);
            min-height: 100vh;
        }

        .shell {
            width: min(1180px, calc(100vw - 32px));
            margin: 24px auto 40px;
            display: grid;
            gap: 18px;
        }

        .hero,
        .panel {
            background: var(--panel);
            border: 1px solid rgba(216, 207, 194, 0.8);
            border-radius: 22px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(14px);
        }

        .hero {
            padding: 26px 28px;
            display: grid;
            gap: 14px;
        }

        .hero h1 {
            margin: 0;
            font-family: "IBM Plex Serif", Georgia, serif;
            font-size: clamp(1.9rem, 4vw, 3.2rem);
            line-height: 1;
            letter-spacing: -0.04em;
        }

        .hero p {
            margin: 0;
            max-width: 70ch;
            color: var(--muted);
            line-height: 1.5;
        }

        .meta {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .chip {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(13, 107, 97, 0.08);
            color: var(--accent-strong);
            font-size: 0.92rem;
        }

        .grid {
            display: grid;
            grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
            gap: 18px;
            align-items: start;
        }

        .panel {
            padding: 22px;
        }

        .stack {
            display: grid;
            gap: 18px;
        }

        .subpanel {
            display: grid;
            gap: 12px;
            padding-top: 4px;
        }

        .subpanel + .subpanel {
            border-top: 1px solid rgba(216, 207, 194, 0.85);
            padding-top: 18px;
        }

        h3 {
            margin: 0;
            font-size: 0.98rem;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            color: var(--accent-strong);
        }

        h2 {
            margin: 0 0 14px;
            font-size: 1.1rem;
            letter-spacing: 0.02em;
            text-transform: uppercase;
        }

        form {
            display: grid;
            gap: 12px;
        }

        .row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        label {
            display: grid;
            gap: 6px;
            font-size: 0.92rem;
            color: var(--muted);
        }

        input,
        select,
        textarea,
        button {
            font: inherit;
        }

        input,
        select,
        textarea {
            width: 100%;
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 12px 14px;
            background: rgba(255, 255, 255, 0.9);
            color: var(--text);
        }

        textarea {
            min-height: 110px;
            resize: vertical;
        }

        .checks {
            display: grid;
            gap: 10px;
            grid-template-columns: 1fr 1fr;
        }

        .check {
            display: flex;
            gap: 10px;
            align-items: center;
            padding: 10px 12px;
            border: 1px solid var(--line);
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.65);
            color: var(--text);
        }

        .check input {
            width: auto;
            margin: 0;
        }

        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }

        button {
            border: 0;
            border-radius: 999px;
            padding: 12px 18px;
            cursor: pointer;
            transition: transform 140ms ease, opacity 140ms ease, background 140ms ease;
        }

        button:hover { transform: translateY(-1px); }
        button:disabled { opacity: 0.55; cursor: wait; transform: none; }

        .primary {
            background: linear-gradient(135deg, var(--accent) 0%, #158677 100%);
            color: #fff;
        }

        .secondary {
            background: rgba(13, 107, 97, 0.12);
            color: var(--accent-strong);
        }

        .ghost {
            background: rgba(29, 41, 53, 0.08);
            color: var(--text);
        }

        .status-line {
            min-height: 1.4em;
            color: var(--muted);
        }

        .status-line.error { color: var(--fail); }
        .status-line.ok { color: var(--ok); }

        .jobs-header {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: center;
            margin-bottom: 14px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.94rem;
        }

        th,
        td {
            text-align: left;
            padding: 12px 10px;
            border-bottom: 1px solid rgba(216, 207, 194, 0.85);
            vertical-align: top;
        }

        th {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
        }

        .path {
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.86rem;
            word-break: break-all;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .queued { background: rgba(170, 109, 0, 0.12); color: var(--warn); }
        .running { background: rgba(13, 107, 97, 0.12); color: var(--accent-strong); }
        .succeeded { background: rgba(34, 104, 74, 0.12); color: var(--ok); }
        .failed { background: rgba(159, 45, 45, 0.12); color: var(--fail); }
        .skipped, .cancelled { background: rgba(29, 41, 53, 0.08); color: var(--muted); }

        .empty {
            color: var(--muted);
            padding: 22px 4px 8px;
        }

        .list-block {
            display: grid;
            gap: 10px;
        }

        .list-item {
            display: grid;
            gap: 8px;
            padding: 12px 14px;
            border-radius: 16px;
            border: 1px solid rgba(216, 207, 194, 0.85);
            background: rgba(255, 255, 255, 0.7);
        }

        .small {
            font-size: 0.86rem;
            color: var(--muted);
        }

        .progress-cell {
            min-width: 170px;
        }

        .progress-track {
            width: 100%;
            height: 10px;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(29, 41, 53, 0.08);
        }

        .progress-fill {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--accent) 0%, #23a28f 100%);
            transition: width 220ms ease;
        }

        .progress-text {
            margin-top: 6px;
            font-size: 0.84rem;
            color: var(--muted);
        }

        .inline-button {
            padding: 8px 12px;
            font-size: 0.85rem;
            background: rgba(159, 45, 45, 0.08);
            color: var(--fail);
        }

        @media (max-width: 920px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 640px) {
            .row,
            .checks {
                grid-template-columns: 1fr;
            }

            .shell {
                width: min(100vw - 20px, 100%);
                margin-top: 10px;
            }

            .panel,
            .hero {
                padding: 18px;
                border-radius: 18px;
            }

            th:nth-child(1), td:nth-child(1),
            th:nth-child(5), td:nth-child(5) {
                display: none;
            }
        }
    </style>
</head>
<body>
    <div class="shell">
        <section class="hero">
            <h1>clutch service</h1>
            <p>Remote control panel for machine A. Use this page from machine B to submit conversions, inspect the queue, and cancel pending jobs without using the CLI.</p>
            <div class="meta" id="service-meta"></div>
        </section>

        <div class="grid">
            <section class="stack">
                <section class="panel">
                    <h2>New Job</h2>
                    <form id="job-form" method="post" action="/jobs">
                        <label>
                            Input file path
                            <input name="input_file" placeholder="/mnt/media-b/incoming/movie.mkv" required>
                        </label>

                        <label>
                            Output directory
                            <input name="output_dir" placeholder="/mnt/media-b/converted">
                        </label>

                        <div class="row">
                            <label>
                                Codec
                                <select name="codec">
                                    <option value="nvenc_h265">nvenc_h265</option>
                                    <option value="nvenc_h264">nvenc_h264</option>
                                    <option value="av1">av1</option>
                                    <option value="x265">x265</option>
                                </select>
                            </label>

                            <label>
                                Speed
                                <select name="encode_speed">
                                    <option value="normal">normal</option>
                                    <option value="slow">slow</option>
                                    <option value="fast">fast</option>
                                </select>
                            </label>
                        </div>

                        <div class="checks">
                            <label class="check"><input type="checkbox" name="audio_passthrough">Audio passthrough</label>
                            <label class="check"><input type="checkbox" name="delete_source">Delete source on success</label>
                            <label class="check"><input type="checkbox" name="force">Force conversion</label>
                            <label class="check"><input type="checkbox" name="verbose">Verbose HandBrake output</label>
                        </div>

                        <div class="actions">
                            <button class="primary" type="submit" id="submit-button">Queue job</button>
                            <button class="secondary" type="button" id="refresh-button">Refresh jobs</button>
                        </div>
                        <div class="status-line" id="form-status"></div>
                    </form>
                </section>

                <section class="panel">
                    <h2>Service Admin</h2>
                    <div class="subpanel">
                        <h3>Default Job Settings</h3>
                        <form id="settings-form" method="post" action="/config">
                            <label>
                                Allowed roots
                                <textarea name="allowed_roots" placeholder="One absolute path per line"></textarea>
                            </label>

                            <label>
                                Default output directory
                                <input name="default_output_dir" placeholder="Leave empty to write next to source">
                            </label>

                            <div class="row">
                                <label>
                                    Default codec
                                    <select name="default_codec">
                                        <option value="nvenc_h265">nvenc_h265</option>
                                        <option value="nvenc_h264">nvenc_h264</option>
                                        <option value="av1">av1</option>
                                        <option value="x265">x265</option>
                                    </select>
                                </label>

                                <label>
                                    Default speed
                                    <select name="default_encode_speed">
                                        <option value="normal">normal</option>
                                        <option value="slow">slow</option>
                                        <option value="fast">fast</option>
                                    </select>
                                </label>
                            </div>

                            <div class="checks">
                                <label class="check"><input type="checkbox" name="default_audio_passthrough">Default audio passthrough</label>
                                <label class="check"><input type="checkbox" name="default_delete_source">Default delete source</label>
                                <label class="check"><input type="checkbox" name="default_force">Default force conversion</label>
                                <label class="check"><input type="checkbox" name="default_verbose">Default verbose mode</label>
                            </div>

                            <div class="actions">
                                <button class="primary" type="submit" id="settings-button">Save settings</button>
                            </div>
                            <div class="status-line" id="settings-status"></div>
                        </form>
                    </div>

                    <div class="subpanel">
                        <h3>Watch Directories</h3>
                        <form id="watcher-form" method="post" action="/watchers">
                            <label>
                                Directory
                                <input name="directory" placeholder="/mnt/media-b/watch" required>
                            </label>
                            <div class="row">
                                <label>
                                    Poll interval
                                    <input name="poll_interval" type="number" min="1" step="1" value="5">
                                </label>
                                <label>
                                    Settle time
                                    <input name="settle_time" type="number" min="1" step="1" value="30">
                                </label>
                            </div>
                            <div class="checks">
                                <label class="check"><input type="checkbox" name="recursive">Recursive watch</label>
                            </div>
                            <div class="actions">
                                <button class="secondary" type="submit" id="watcher-button">Add watcher</button>
                            </div>
                            <div class="status-line" id="watcher-status"></div>
                        </form>
                        <div id="watchers-container" class="list-block"></div>
                    </div>
                </section>
            </section>

            <section class="panel">
                <div class="jobs-header">
                    <h2>Queue</h2>
                    <button class="ghost" type="button" id="toggle-autorefresh">Auto refresh: on</button>
                </div>
                <div id="jobs-container"></div>
            </section>
        </div>
    </div>

    <script>
        const state = {
            autoRefresh: true,
            timerId: null,
        };

        const meta = document.getElementById('service-meta');
        const jobsContainer = document.getElementById('jobs-container');
        const form = document.getElementById('job-form');
        const formStatus = document.getElementById('form-status');
        const settingsForm = document.getElementById('settings-form');
        const settingsStatus = document.getElementById('settings-status');
        const watcherForm = document.getElementById('watcher-form');
        const watcherStatus = document.getElementById('watcher-status');
        const watchersContainer = document.getElementById('watchers-container');
        const submitButton = document.getElementById('submit-button');
        const settingsButton = document.getElementById('settings-button');
        const watcherButton = document.getElementById('watcher-button');
        const refreshButton = document.getElementById('refresh-button');
        const toggleAutoRefreshButton = document.getElementById('toggle-autorefresh');
        const startupParams = new URLSearchParams(window.location.search);

        function escapeHtml(value) {
            return String(value == null ? '' : value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function setFormStatus(message, kind = '') {
            formStatus.textContent = message;
            formStatus.className = kind ? `status-line ${kind}` : 'status-line';
        }

        function setStatus(target, message, kind = '') {
            target.textContent = message;
            target.className = kind ? `status-line ${kind}` : 'status-line';
        }

        async function fetchJson(path, options = {}) {
            const requestOptions = Object.assign({}, options);
            const method = String(requestOptions.method || 'GET').toUpperCase();
            let requestPath = path;

            if (method === 'GET') {
                const separator = path.indexOf('?') !== -1 ? '&' : '?';
                requestPath = `${path}${separator}_ts=${Date.now()}`;
                requestOptions.cache = 'no-store';
            }

            const response = await fetch(requestPath, requestOptions);
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload.error || `Request failed with status ${response.status}`);
            }
            return payload;
        }

        function renderMeta(summary) {
            const chips = [];
            const allowedRootsLabel = summary.allowed_roots.join(', ') || 'unrestricted';
            chips.push(`<span class="chip">Allowed roots: ${escapeHtml(allowedRootsLabel)}</span>`);
            chips.push(`<span class="chip">Watchers: ${escapeHtml(String((summary.watchers || []).length))}</span>`);
            chips.push(`<span class="chip">Worker mode: single queue</span>`);
            meta.innerHTML = chips.join('');
        }

        function applySummaryToForms(summary) {
            const defaults = summary.default_job_settings || {};
            settingsForm.elements.allowed_roots.value = (summary.allowed_roots || []).join('\\n');
            settingsForm.elements.default_output_dir.value = defaults.output_dir || '';
            settingsForm.elements.default_codec.value = defaults.codec || 'nvenc_h265';
            settingsForm.elements.default_encode_speed.value = defaults.encode_speed || 'normal';
            settingsForm.elements.default_audio_passthrough.checked = Boolean(defaults.audio_passthrough);
            settingsForm.elements.default_delete_source.checked = Boolean(defaults.delete_source);
            settingsForm.elements.default_force.checked = Boolean(defaults.force);
            settingsForm.elements.default_verbose.checked = Boolean(defaults.verbose);
        }

        function renderWatchers(watchers) {
            if (!watchers.length) {
                watchersContainer.innerHTML = '<div class="empty">No watchers configured.</div>';
                return;
            }

            watchersContainer.innerHTML = watchers.map((watcher) => `
                <div class="list-item">
                    <div class="path">${escapeHtml(watcher.directory)}</div>
                    <div class="small">recursive: ${escapeHtml(String(watcher.recursive))} | poll: ${escapeHtml(String(watcher.poll_interval))}s | settle: ${escapeHtml(String(watcher.settle_time))}s</div>
                    <div class="actions">
                        <button class="inline-button" type="button" data-remove-watcher="${watcher.id}">Remove</button>
                    </div>
                </div>
            `).join('');

            watchersContainer.querySelectorAll('[data-remove-watcher]').forEach((button) => {
                button.addEventListener('click', async () => {
                    button.disabled = true;
                    try {
                        await fetchJson(`/watchers/${button.dataset.removeWatcher}`, { method: 'DELETE' });
                        setStatus(watcherStatus, 'Watcher removed.', 'ok');
                        await refreshSummary();
                    } catch (error) {
                        setStatus(watcherStatus, error.message, 'error');
                        button.disabled = false;
                    }
                });
            });
        }

        function renderJobs(jobs) {
            if (!jobs.length) {
                jobsContainer.innerHTML = '<div class="empty">No jobs yet.</div>';
                return;
            }

            const rows = jobs.map((job) => {
                const rawProgress = Number(job.progress_percent == null ? 0 : job.progress_percent);
                const progress = Number.isFinite(rawProgress)
                    ? Math.max(0, Math.min(rawProgress, 100))
                    : 0;
                const progressLabel = job.status === 'queued'
                    ? 'Waiting'
                    : job.status === 'running'
                        ? `${progress.toFixed(1)}%`
                        : job.status === 'failed'
                            ? 'Failed'
                            : job.status === 'cancelled'
                                ? 'Cancelled'
                                : job.status === 'skipped'
                                    ? 'Skipped'
                        : progress > 0
                            ? `${progress.toFixed(1)}%`
                            : 'Done';
                const cancelButton = job.status === 'queued'
                    ? `<button class="inline-button" data-cancel-id="${job.id}">Cancel</button>`
                    : '';

                return `
                    <tr>
                        <td>${escapeHtml(job.id.slice(0, 8))}</td>
                        <td><span class="badge ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></td>
                        <td>
                            <div class="path">${escapeHtml(job.input_file)}</div>
                            ${job.output_file ? `<div class="path">out: ${escapeHtml(job.output_file)}</div>` : ''}
                        </td>
                        <td class="progress-cell">
                            <div class="progress-track"><div class="progress-fill" style="width: ${progress.toFixed(1)}%"></div></div>
                            <div class="progress-text">${escapeHtml(progressLabel)}</div>
                        </td>
                        <td>${escapeHtml(job.codec)} / ${escapeHtml(job.encode_speed)}</td>
                        <td>${escapeHtml(job.submitted_at || '')}</td>
                        <td>${escapeHtml(job.message || '')}</td>
                        <td>${cancelButton}</td>
                    </tr>`;
            }).join('');

            jobsContainer.innerHTML = `
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Status</th>
                            <th>Path</th>
                            <th>Progress</th>
                            <th>Profile</th>
                            <th>Submitted</th>
                            <th>Message</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>`;

            jobsContainer.querySelectorAll('[data-cancel-id]').forEach((button) => {
                button.addEventListener('click', async () => {
                    button.disabled = true;
                    try {
                        await fetchJson(`/jobs/${button.dataset.cancelId}`, { method: 'DELETE' });
                        await refreshJobs();
                    } catch (error) {
                        setFormStatus(error.message, 'error');
                        button.disabled = false;
                    }
                });
            });
        }

        async function refreshSummary() {
            const payload = await fetchJson('/config');
            renderMeta(payload);
            applySummaryToForms(payload);
            renderWatchers(payload.watchers || []);
        }

        async function refreshJobs() {
            const payload = await fetchJson('/jobs');
            renderJobs(payload.jobs || []);
        }

        async function refreshAll() {
            try {
                await Promise.all([refreshSummary(), refreshJobs()]);
            } catch (error) {
                setFormStatus(error.message, 'error');
            }
        }

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            submitButton.disabled = true;
            setFormStatus('Queueing job...');
            const formData = new FormData(form);
            const payload = {
                input_file: formData.get('input_file'),
                output_dir: formData.get('output_dir'),
                codec: formData.get('codec'),
                encode_speed: formData.get('encode_speed'),
                audio_passthrough: formData.get('audio_passthrough') === 'on',
                delete_source: formData.get('delete_source') === 'on',
                force: formData.get('force') === 'on',
                verbose: formData.get('verbose') === 'on',
            };

            try {
                const response = await fetchJson('/jobs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                form.reset();
                setFormStatus(`Queued job ${response.id}`, 'ok');
                await refreshJobs();
            } catch (error) {
                setFormStatus(error.message, 'error');
            } finally {
                submitButton.disabled = false;
            }
        });

        settingsForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            settingsButton.disabled = true;
            setStatus(settingsStatus, 'Saving settings...');
            const formData = new FormData(settingsForm);
            const allowedRoots = String(formData.get('allowed_roots') || '')
                .split('\\n')
                .map((value) => value.trim())
                .filter(Boolean);
            const payload = {
                allowed_roots: allowedRoots,
                default_job_settings: {
                    output_dir: formData.get('default_output_dir'),
                    codec: formData.get('default_codec'),
                    encode_speed: formData.get('default_encode_speed'),
                    audio_passthrough: formData.get('default_audio_passthrough') === 'on',
                    delete_source: formData.get('default_delete_source') === 'on',
                    force: formData.get('default_force') === 'on',
                    verbose: formData.get('default_verbose') === 'on',
                },
            };

            try {
                await fetchJson('/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                setStatus(settingsStatus, 'Settings saved.', 'ok');
                await refreshSummary();
            } catch (error) {
                setStatus(settingsStatus, error.message, 'error');
            } finally {
                settingsButton.disabled = false;
            }
        });

        watcherForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            watcherButton.disabled = true;
            setStatus(watcherStatus, 'Adding watcher...');
            const formData = new FormData(watcherForm);
            const payload = {
                directory: formData.get('directory'),
                recursive: formData.get('recursive') === 'on',
                poll_interval: Number(formData.get('poll_interval') || 5),
                settle_time: Number(formData.get('settle_time') || 30),
            };

            try {
                await fetchJson('/watchers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                watcherForm.reset();
                watcherForm.elements.poll_interval.value = '5';
                watcherForm.elements.settle_time.value = '30';
                setStatus(watcherStatus, 'Watcher added.', 'ok');
                await refreshSummary();
            } catch (error) {
                setStatus(watcherStatus, error.message, 'error');
            } finally {
                watcherButton.disabled = false;
            }
        });

        refreshButton.addEventListener('click', () => {
            refreshAll();
        });

        toggleAutoRefreshButton.addEventListener('click', () => {
            state.autoRefresh = !state.autoRefresh;
            toggleAutoRefreshButton.textContent = `Auto refresh: ${state.autoRefresh ? 'on' : 'off'}`;
            if (state.autoRefresh) {
                scheduleRefresh();
            } else if (state.timerId) {
                clearInterval(state.timerId);
                state.timerId = null;
            }
        });

        function scheduleRefresh() {
            if (state.timerId) {
                clearInterval(state.timerId);
            }
            state.timerId = setInterval(() => {
                if (state.autoRefresh) {
                    refreshJobs().catch((error) => {
                        setFormStatus(error.message, 'error');
                    });
                }
            }, 2000);
        }

        if (startupParams.get('notice')) {
            setFormStatus(startupParams.get('notice'), 'ok');
            history.replaceState(null, '', window.location.pathname);
        } else if (startupParams.get('error')) {
            setFormStatus(startupParams.get('error'), 'error');
            history.replaceState(null, '', window.location.pathname);
        }

        refreshAll();
        scheduleRefresh();
    </script>
</body>
</html>
"""

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

    def do_GET(self):
        path, query = self._get_request_parts()

        if path in self.ASSET_CONTENT_TYPES:
            asset_name, content_type, mode = self.ASSET_CONTENT_TYPES[path]
            if mode == "bytes":
                self._send_bytes(200, read_web_asset_bytes(asset_name), content_type)
            else:
                self._send_text(200, read_web_asset(asset_name), content_type)
            return

        if path in {"/", "/index.html"}:
            if query.get("input_file"):
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

        self._send_json(404, {"error": "Not found."})

    def do_POST(self):
        path, _ = self._get_request_parts()

        if path == "/updates/check":
            self._send_json(200, self.server.service.get_update_info(force_check=True))
            return

        if path == "/updates/upgrade":
            try:
                payload = self.server.service.schedule_self_upgrade(self.server.shutdown)
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(202, payload)
            return

        if path.startswith("/jobs/") and path.endswith("/retry"):
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

        if path == "/config":
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
            try:
                payload = self._read_json() if self._is_json_request() else self._read_form()
                watcher = self.server.service.add_watcher(
                    str(payload.get("directory") or "").strip(),
                    recursive=bool(payload.get("recursive", False)) if self._is_json_request() else payload.get("recursive") == "on",
                    poll_interval=float(payload.get("poll_interval") or 5.0),
                    settle_time=float(payload.get("settle_time") or 30.0),
                    delete_source=bool(payload.get("delete_source", False)) if self._is_json_request() else payload.get("delete_source") == "on",
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

    def do_DELETE(self):
        path, query = self._get_request_parts()

        if path == "/jobs":
            self._send_json(200, self.server.service.clear_jobs())
            return

        if path.startswith("/watchers/"):
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


def build_service_db_path() -> str:
    return os.path.join(build_state_dir(), "service.db")


def run_service(
    *,
    bind_host: str,
    port: int,
    db_path: str,
    allowed_roots: Optional[List[str]],
    worker_count: int,
    gpu_devices: List[int],
    watch_dirs: List[str],
    watch_recursive: bool,
    watch_poll_interval: float,
    watch_settle_time: float,
    watch_job_template: Dict[str, object],
):
    import signal as _signal

    # Restore default SIGINT so KeyboardInterrupt is raised properly
    # (the converter's handle_sigint was installed at import time and
    # swallows SIGINT, preventing serve_forever from stopping).
    _signal.signal(_signal.SIGINT, _signal.default_int_handler)

    service = ConversionService(
        db_path,
        allowed_roots=allowed_roots,
        default_job_settings=watch_job_template,
        worker_count=worker_count,
        gpu_devices=gpu_devices,
    )
    if not service.has_persisted_configuration():
        for watch_dir in watch_dirs:
            service.add_watcher(
                watch_dir,
                recursive=watch_recursive,
                poll_interval=watch_poll_interval,
                settle_time=watch_settle_time,
                delete_source=bool(watch_job_template.get("delete_source", False)),
            )
    service.start()
    service.start_watchers()

    server = ConversionHTTPServer((bind_host, port), ServiceRequestHandler, service)
    info(f"Service listening on http://{bind_host}:{port}")
    info(f"Job database: {os.path.abspath(db_path)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        warning(f"Stopping {APP_NAME} service...")
    finally:
        server.server_close()
        service.stop()
        service.wait()

    if service.should_restart():
        restart_command = service.get_restart_command()
        if restart_command and restart_command[0]:
            info(f"Restarting {APP_NAME} service with the upgraded version...")
            try:
                os.execvp(restart_command[0], restart_command)
            except OSError as exc:
                print_error(f"Could not restart {APP_NAME} service automatically: {exc}")


def submit_remote_job(server_url: str, payload: Dict[str, object]) -> Dict[str, object]:
    payload = {**payload}
    payload.setdefault("submitted_display", local_now_display())
    url = f"{server_url.rstrip('/')}/jobs"
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"error": body or str(exc)}
        raise RuntimeError(payload.get("error") or str(exc)) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not reach server '{server_url}': {exc}") from exc
