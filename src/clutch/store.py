from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from clutch.converter import RESUME_MIN_DURATION, is_conversion_process_alive
from clutch.mediainfo import extract_media_summary, get_media_duration_seconds
from clutch.output import info, warning


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
    return files("clutch.web").joinpath(name).read_text(encoding="utf-8")


def read_web_asset_bytes(name: str) -> bytes:
    return files("clutch.web").joinpath(name).read_bytes()


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
    output_base_dir: str = ""

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
                    "output_base_dir": os.path.abspath(self.output_base_dir) if self.output_base_dir else "",
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
            output_base_dir=str(extra.get("output_base_dir") or "").strip(),
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
            output_base_dir=str(payload.get("output_base_dir") or "").strip(),
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
            if "priority" not in columns:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
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
            if "schedule_config_json" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN schedule_config_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "log_level" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN log_level TEXT NOT NULL DEFAULT 'INFO'"
                )
            if "log_retention_days" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN log_retention_days INTEGER NOT NULL DEFAULT 30"
                )
            if "default_date_format" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN default_date_format TEXT NOT NULL DEFAULT ''"
                )
            if "listen_port" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN listen_port INTEGER NOT NULL DEFAULT 8765"
                )
            if "binary_paths_json" not in service_config_columns:
                self._conn.execute(
                    "ALTER TABLE service_config ADD COLUMN binary_paths_json TEXT NOT NULL DEFAULT '{}'"
                )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchers (
                    id TEXT PRIMARY KEY,
                    directory TEXT NOT NULL UNIQUE,
                    recursive INTEGER NOT NULL,
                    poll_interval REAL NOT NULL,
                    settle_time REAL NOT NULL,
                    delete_source INTEGER NOT NULL DEFAULT 0,
                    output_dir TEXT NOT NULL DEFAULT '',
                    codec TEXT NOT NULL DEFAULT '',
                    encode_speed TEXT NOT NULL DEFAULT '',
                    audio_passthrough INTEGER,
                    force INTEGER
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
            for col, definition in [
                ("output_dir", "TEXT NOT NULL DEFAULT ''"),
                ("codec", "TEXT NOT NULL DEFAULT ''"),
                ("encode_speed", "TEXT NOT NULL DEFAULT ''"),
                ("audio_passthrough", "INTEGER"),
                ("force", "INTEGER"),
            ]:
                if col not in watcher_columns:
                    self._conn.execute(f"ALTER TABLE watchers ADD COLUMN {col} {definition}")

            # Notification channels (Phase 4)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_channels (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    events_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )

    def _remove_temp_artifacts(self, record: Dict[str, object]):
        """Physically delete temp file and its companion progress log from disk."""
        for key in ("temp_file", "log_file"):
            path = str(record.get(key) or "").strip()
            if not path:
                continue
            try:
                os.remove(path)
            except OSError:
                pass
            progress_log = f"{path}.progress.log"
            try:
                os.remove(progress_log)
            except OSError:
                pass

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
                    self._remove_temp_artifacts(record)
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

                # Check if the partial temp file has enough content to resume
                temp_file = str(record.get("temp_file") or "").strip()
                partial_duration = 0.0
                if temp_file and os.path.isfile(temp_file):
                    try:
                        partial_duration = get_media_duration_seconds(temp_file)
                    except Exception:
                        partial_duration = 0.0

                if partial_duration > RESUME_MIN_DURATION:
                    # Keep the partial temp file for resume — only clear runtime state
                    resume_offset = max(0.0, partial_duration - RESUME_SAFETY_MARGIN)
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
                            log_file = NULL,
                            final_output_file = NULL,
                            resume_on_start = 0,
                            message = ?
                        WHERE id = ?
                        """,
                        (
                            f"Service recovered: partial encode ({partial_duration:.0f}s) will resume from {resume_offset:.0f}s.",
                            job_id,
                        ),
                    )
                    info(f"[{job_id[:8]}] Keeping partial encode ({partial_duration:.0f}s) for resume.")
                    requeued += 1
                    continue

                # No usable partial — clean up and requeue from scratch
                self._remove_temp_artifacts(record)
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
        # Enrich extra_json with input media summary
        try:
            extra = json.loads(record["extra_json"] or "{}")
        except json.JSONDecodeError:
            extra = {}
        try:
            input_summary = extract_media_summary(record["input_file"])
        except Exception:
            input_summary = {}
        if input_summary:
            extra["input_media"] = input_summary
        record["extra_json"] = json.dumps(extra)
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
        record["input_media"] = extra.get("input_media") or None
        record["output_media"] = extra.get("output_media") or None
        return record

    def get(self, job_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._hydrate_record(row) if row else None

    def merge_extra_json(self, job_id: str, updates: Dict[str, object]):
        """Merge key-value pairs into the extra_json field of a job."""
        with self._lock:
            row = self._conn.execute("SELECT extra_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return
            try:
                extra = json.loads(row["extra_json"] or "{}")
            except json.JSONDecodeError:
                extra = {}
            extra.update(updates)
            with self._conn:
                self._conn.execute(
                    "UPDATE jobs SET extra_json = ? WHERE id = ?",
                    (json.dumps(extra), job_id),
                )

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
                "SELECT allowed_roots_json, default_job_settings_json, worker_count, gpu_devices_json, schedule_config_json, log_level, log_retention_days, default_date_format, listen_port, binary_paths_json FROM service_config WHERE singleton = 1"
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
            gpu_devices = json.loads(row["gpu_devices_json"] or "[]")
        except (json.JSONDecodeError, ValueError):
            gpu_devices = []
        try:
            schedule_config = json.loads(row["schedule_config_json"] or "{}")
        except json.JSONDecodeError:
            schedule_config = {}
        try:
            binary_paths = json.loads(row["binary_paths_json"] or "{}")
        except json.JSONDecodeError:
            binary_paths = {}
        return {
            "allowed_roots": allowed_roots,
            "default_job_settings": default_job_settings,
            "worker_count": int(row["worker_count"] or 1),
            "gpu_devices": gpu_devices,
            "schedule_config": schedule_config,
            "log_level": str(row["log_level"] or "INFO"),
            "log_retention_days": int(row["log_retention_days"] or 30),
            "default_date_format": str(row["default_date_format"] or ""),
            "listen_port": int(row["listen_port"] or 8765),
            "binary_paths": binary_paths,
        }

    def save_service_config(
        self,
        allowed_roots: List[str],
        default_job_settings: Dict[str, object],
        worker_count: int,
        gpu_devices: List[int],
        schedule_config: Optional[Dict[str, object]] = None,
        log_level: str = "INFO",
        log_retention_days: int = 30,
        default_date_format: str = "",
        listen_port: int = 8765,
        binary_paths: Optional[Dict[str, str]] = None,
    ):
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO service_config (singleton, allowed_roots_json, default_job_settings_json, worker_count, gpu_devices_json, schedule_config_json, log_level, log_retention_days, default_date_format, listen_port, binary_paths_json)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    allowed_roots_json = excluded.allowed_roots_json,
                    default_job_settings_json = excluded.default_job_settings_json,
                    worker_count = excluded.worker_count,
                    gpu_devices_json = excluded.gpu_devices_json,
                    schedule_config_json = excluded.schedule_config_json,
                    log_level = excluded.log_level,
                    log_retention_days = excluded.log_retention_days,
                    default_date_format = excluded.default_date_format,
                    listen_port = excluded.listen_port,
                    binary_paths_json = excluded.binary_paths_json
                """,
                (
                    json.dumps(list(allowed_roots)),
                    json.dumps(dict(default_job_settings)),
                    int(worker_count),
                    json.dumps(list(gpu_devices)),
                    json.dumps(schedule_config or {}),
                    str(log_level),
                    int(log_retention_days),
                    str(default_date_format),
                    int(listen_port),
                    json.dumps(binary_paths or {}),
                ),
            )

    def list_watcher_configs(self) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, directory, recursive, poll_interval, settle_time, delete_source, output_dir, codec, encode_speed, audio_passthrough, force FROM watchers ORDER BY directory ASC"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "directory": row["directory"],
                "recursive": bool(row["recursive"]),
                "poll_interval": float(row["poll_interval"]),
                "settle_time": float(row["settle_time"]),
                "delete_source": bool(row["delete_source"]),
                "output_dir": str(row["output_dir"] or ""),
                "codec": str(row["codec"] or ""),
                "encode_speed": str(row["encode_speed"] or ""),
                "audio_passthrough": None if row["audio_passthrough"] is None else bool(row["audio_passthrough"]),
                "force": None if row["force"] is None else bool(row["force"]),
            }
            for row in rows
        ]

    def save_watcher_config(self, watcher: Dict[str, object]):
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO watchers (id, directory, recursive, poll_interval, settle_time, delete_source, output_dir, codec, encode_speed, audio_passthrough, force)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    directory = excluded.directory,
                    recursive = excluded.recursive,
                    poll_interval = excluded.poll_interval,
                    settle_time = excluded.settle_time,
                    delete_source = excluded.delete_source,
                    output_dir = excluded.output_dir,
                    codec = excluded.codec,
                    encode_speed = excluded.encode_speed,
                    audio_passthrough = excluded.audio_passthrough,
                    force = excluded.force
                """,
                (
                    str(watcher["id"]),
                    str(watcher["directory"]),
                    int(bool(watcher["recursive"])),
                    float(watcher["poll_interval"]),
                    float(watcher["settle_time"]),
                    int(bool(watcher.get("delete_source", False))),
                    str(watcher.get("output_dir") or ""),
                    str(watcher.get("codec") or ""),
                    str(watcher.get("encode_speed") or ""),
                    None if watcher.get("audio_passthrough") is None else int(bool(watcher["audio_passthrough"])),
                    None if watcher.get("force") is None else int(bool(watcher["force"])),
                ),
            )

    def delete_watcher_config(self, watcher_id: str):
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM watchers WHERE id = ?", (watcher_id,))

    def list_jobs(self, limit: int = 50) -> List[Dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM jobs WHERE status IN ('running', 'paused', 'cancelling', 'queued')
                UNION
                SELECT * FROM (
                    SELECT * FROM jobs WHERE status NOT IN ('running', 'paused', 'cancelling', 'queued')
                    ORDER BY submitted_at DESC LIMIT ?
                )
                ORDER BY submitted_at DESC
                """,
                (limit,),
            ).fetchall()
        return [self._hydrate_record(row) for row in rows]

    def list_tasks(
        self,
        *,
        page: int = 1,
        limit: int = 50,
        status: str = "",
        codec: str = "",
        search: str = "",
    ) -> Dict[str, object]:
        """Return historical task records with filtering and pagination."""
        conditions: List[str] = []
        params: list = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if codec:
            conditions.append("codec = ?")
            params.append(codec)
        if search:
            conditions.append("(input_file LIKE ? OR output_file LIKE ? OR message LIKE ?)")
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM jobs" + where, params
            ).fetchone()[0]

            offset = (page - 1) * limit
            rows = self._conn.execute(
                "SELECT * FROM jobs" + where + " ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        entries = []
        for row in rows:
            r = self._hydrate_record(row)
            entries.append({
                "id": r["id"],
                "status": r.get("status"),
                "input_file": r.get("input_file"),
                "output_file": r.get("output_file"),
                "codec": r.get("codec"),
                "input_size_bytes": r.get("input_size_bytes"),
                "output_size_bytes": r.get("output_size_bytes"),
                "compression_percent": r.get("compression_percent"),
                "submitted_at": r.get("submitted_at"),
                "submitted_display": r.get("submitted_display"),
                "started_at": r.get("started_at"),
                "finished_at": r.get("finished_at"),
                "message": r.get("message"),
            })

        return {"tasks": entries, "total": total, "page": page, "limit": limit}

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

    def set_priority(self, job_id: str, priority: int) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            self._conn.execute("UPDATE jobs SET priority = ? WHERE id = ? AND status = 'queued'", (priority, job_id))
        return self.get(job_id)

    def move_to_next(self, job_id: str) -> Optional[Dict[str, object]]:
        """Set the given job's priority so it will be picked next."""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT MAX(priority) as max_p FROM jobs WHERE status = 'queued'").fetchone()
            max_priority = int(row["max_p"] or 0) if row else 0
            self._conn.execute(
                "UPDATE jobs SET priority = ? WHERE id = ? AND status = 'queued'",
                (max_priority + 1, job_id),
            )
        return self.get(job_id)

    def claim_next(self) -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY priority DESC, submitted_at ASC LIMIT 1"
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

    def set_resume_on_start(self, job_id: str, enabled: bool, message: str = "") -> Optional[Dict[str, object]]:
        with self._lock, self._conn:
            if message:
                self._conn.execute(
                    "UPDATE jobs SET resume_on_start = ?, message = ? WHERE id = ?",
                    (int(bool(enabled)), message, job_id),
                )
            else:
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

    def clear(self, mode: str = "all") -> Dict[str, int]:
        if mode == "finished":
            target_statuses = ('succeeded', 'failed', 'cancelled', 'skipped')
        elif mode == "queued":
            target_statuses = ('queued',)
        else:
            target_statuses = ('queued', 'succeeded', 'failed', 'cancelled', 'skipped')
        placeholders = ','.join('?' for _ in target_statuses)
        with self._lock, self._conn:
            counts = self._conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
                    SUM(CASE WHEN status = 'paused' THEN 1 ELSE 0 END) AS paused,
                    SUM(CASE WHEN status = 'cancelling' THEN 1 ELSE 0 END) AS cancelling,
                    SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued
                FROM jobs
                """
            ).fetchone()
            deleted = self._conn.execute(
                f"DELETE FROM jobs WHERE status IN ({placeholders})",
                target_statuses,
            )
        running_count = int(counts["running"] if counts and counts["running"] else 0)
        paused_count = int(counts["paused"] if counts and counts["paused"] else 0)
        cancelling_count = int(counts["cancelling"] if counts and counts["cancelling"] else 0)
        queued_count = int(counts["queued"] if counts and counts["queued"] else 0)
        return {
            "deleted": int(deleted.rowcount),
            "running": running_count,
            "paused": paused_count,
            "cancelling": cancelling_count,
            "queued": queued_count,
            "active": running_count + paused_count + cancelling_count,
        }


