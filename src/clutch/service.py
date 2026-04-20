from __future__ import annotations

import json
import os
import shutil
import signal as _signal
import sys
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

from clutch import APP_NAME, build_state_dir, get_version
from clutch.auth import AuthStore
from clutch.converter import (
    ConversionDetached,
    RESUME_MIN_DURATION,
    RESUME_SAFETY_MARGIN,
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
from clutch.http_handler import ConversionHTTPServer, ServiceRequestHandler
from clutch.iso import is_iso_file, scan_iso, select_main_title
from clutch.mediainfo import VIDEO_EXTENSIONS, check_already_converted, extract_media_summary, get_media_duration_seconds
from clutch.notifications import NotificationManager
from clutch.output import error as print_error
from clutch.output import debug, info, success, warning, setup_file_logging, set_log_level
from clutch.scheduler import BIDDING_ZONES, ScheduleConfig, ScheduleEngine
from clutch.store import (
    ACTIVE_JOB_STATUSES,
    ConversionJob,
    JobStore,
    format_eta,
    normalize_path,
    path_within_roots,
    record_has_recoverable_runtime,
    utc_now,
)
from clutch.updater import get_update_state, install_latest_version, mark_update_installed
from clutch.watcher import DirectoryWatcher, WorkerHandle

# Re-export for backward compatibility
from clutch.store import format_display_timestamp, local_now_display  # noqa: F401
from clutch.http_handler import read_web_asset, read_web_asset_bytes  # noqa: F401
from urllib import error, request  # noqa: F401


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
        schedule_config: Optional[Dict[str, object]] = None,
    ):
        self.store = JobStore(db_path)
        self.auth = AuthStore(self.store._conn, self.store._lock)
        self.notifications = NotificationManager(self.store)
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
        self._pause_detach_jobs: set[str] = set()
        self._recoverable_job_ids: List[str] = []
        self._recoverable_jobs_lock = threading.Lock()
        self._loaded_persisted_state = False
        self._update_monitor_thread: Optional[threading.Thread] = None
        self._update_lock = threading.Lock()
        self._upgrade_in_progress = False
        self._upgrade_step = 0
        self._upgrade_step_total = 9
        self._upgrade_step_label = ""
        self._restart_requested = False
        self._restart_command = [sys.argv[0], *sys.argv[1:]]
        self.scheduler = ScheduleEngine()
        self._schedule_monitor_thread: Optional[threading.Thread] = None
        self._schedule_paused_jobs: set[str] = set()
        self._schedule_wake_event = threading.Event()
        self._load_persisted_state(
            [os.path.abspath(path) for path in (allowed_roots or [])],
            self.default_job_settings,
            self.worker_count,
            self.gpu_devices,
            schedule_config or {},
        )

    def _load_persisted_state(
        self,
        initial_allowed_roots: List[str],
        initial_default_job_settings: Dict[str, object],
        initial_worker_count: int,
        initial_gpu_devices: List[int],
        initial_schedule_config: Dict[str, object],
    ):
        persisted_config = self.store.load_service_config()
        persisted_watchers = self.store.list_watcher_configs()
        self._loaded_persisted_state = persisted_config is not None or bool(persisted_watchers)

        if persisted_config is None:
            self.allowed_roots = list(initial_allowed_roots)
            self.default_job_settings = self._normalize_default_job_settings(initial_default_job_settings)
            self.worker_count = self._normalize_worker_count(initial_worker_count)
            self.gpu_devices = parse_gpu_devices(initial_gpu_devices)
            self.log_level = "INFO"
            self.log_retention_days = 30
            self.default_date_format = ""
            self.listen_port = 8765
            schedule_cfg = ScheduleConfig.from_dict(initial_schedule_config)
            self.scheduler.update_config(schedule_cfg)
            self.store.save_service_config(
                self.allowed_roots,
                self.default_job_settings,
                self.worker_count,
                self.gpu_devices,
                schedule_cfg.to_dict(),
                self.log_level,
                self.log_retention_days,
                self.default_date_format,
                self.listen_port,
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
            self.log_level = str(persisted_config.get("log_level") or "INFO")
            self.log_retention_days = int(persisted_config.get("log_retention_days") or 30)
            self.default_date_format = str(persisted_config.get("default_date_format") or "")
            self.listen_port = int(persisted_config.get("listen_port") or 8765)
            schedule_raw = persisted_config.get("schedule_config") or {}
            self.scheduler.update_config(ScheduleConfig.from_dict(schedule_raw))

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
                    output_dir=str(watcher_config.get("output_dir") or ""),
                    codec=str(watcher_config.get("codec") or ""),
                    encode_speed=str(watcher_config.get("encode_speed") or ""),
                    audio_passthrough=watcher_config.get("audio_passthrough"),
                    force=watcher_config.get("force"),
                )
                self._watchers[watcher.watcher_id] = watcher

    def has_persisted_configuration(self) -> bool:
        return self._loaded_persisted_state

    def start(self):
        self._service_started = True
        self._prime_recoverable_jobs()
        self._sync_worker_pool()
        self._start_update_monitor()
        self._start_schedule_monitor()

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
                pass
            # Also remove the companion .progress.log created by the converter
            progress_log = f"{path}.progress.log"
            try:
                os.remove(progress_log)
            except OSError:
                pass

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

    def _start_schedule_monitor(self):
        if self._schedule_monitor_thread and self._schedule_monitor_thread.is_alive():
            return
        self._schedule_monitor_thread = threading.Thread(
            target=self._schedule_monitor_loop,
            daemon=True,
            name=f"{APP_NAME}-schedule-monitor",
        )
        self._schedule_monitor_thread.start()

    def _schedule_monitor_loop(self):
        """Background loop that handles schedule-based pause/resume of running jobs
        and periodic price refresh."""
        was_allowed = True
        while not self.stop_event.is_set():
            self._schedule_wake_event.clear()
            cfg = self.scheduler.config
            if cfg.enabled:
                # Refresh prices periodically if price mode is active
                if cfg.mode in ("price", "both") and cfg.price.provider:
                    try:
                        self.scheduler.fetch_prices()
                    except Exception as exc:
                        warning(f"Schedule price refresh failed: {exc}")

                allowed = self.scheduler.is_conversion_allowed()

                # Handle pause_running behavior: SIGSTOP/SIGCONT active jobs
                if cfg.pause_behavior == "pause_running":
                    if not allowed and was_allowed:
                        self._schedule_pause_all_running()
                    elif allowed and not was_allowed:
                        self._schedule_resume_all_paused()

                # block_new: pause all running when transitioning to blocked
                if cfg.pause_behavior == "block_new":
                    if not allowed and was_allowed:
                        self._schedule_pause_all_running()
                    elif allowed and not was_allowed:
                        self._schedule_resume_all_paused()

                if allowed and not was_allowed:
                    # Wake workers so they can pick up queued jobs immediately
                    self._wake_event.set()

                was_allowed = allowed
            else:
                was_allowed = True

            # Wait up to 30s, but wake early if config changed
            self.stop_event.wait(0.1)
            if self.stop_event.is_set():
                break
            self._schedule_wake_event.wait(30)

    def _schedule_pause_all_running(self):
        """Pause all running jobs due to schedule block."""
        for record in self.store.list_active_jobs():
            job_id = str(record["id"])
            status = str(record.get("status") or "")
            if status != "running":
                continue
            with self._job_control_lock:
                active_thread_id = self._active_jobs.get(job_id)
            if active_thread_id is not None:
                request_current_conversion_pause(active_thread_id)
            else:
                request_conversion_pause_by_pid(record.get("process_id"))
            self.store.pause(
                job_id,
                "Paused by schedule. Conversion will resume when the schedule allows.",
                resume_on_start=False,
            )
            self._schedule_paused_jobs.add(job_id)
            info(f"[{job_id[:8]}] Paused by schedule.")

    def _schedule_resume_all_paused(self):
        """Resume jobs that were paused by the schedule."""
        for job_id in list(self._schedule_paused_jobs):
            record = self.store.get(job_id)
            if not record or record.get("status") != "paused":
                self._schedule_paused_jobs.discard(job_id)
                continue
            with self._job_control_lock:
                active_thread_id = self._active_jobs.get(job_id)
            if active_thread_id is not None:
                request_current_conversion_resume(active_thread_id)
                self.store.resume(job_id, "Resumed by schedule.", resume_on_start=False)
                info(f"[{job_id[:8]}] Resumed by schedule.")
            elif record_has_recoverable_runtime(record):
                self.store.resume(
                    job_id,
                    "Waiting for a worker to resume the paused conversion.",
                    resume_on_start=True,
                )
                self._enqueue_recoverable_job(job_id)
                info(f"[{job_id[:8]}] Queued for resume by schedule.")
            self._schedule_paused_jobs.discard(job_id)

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

    def request_restart_with_port(self, new_port: int, shutdown_callback):
        """Schedule a service restart with the updated listen port."""
        cmd = list(self._restart_command)
        # Replace or append --listen-port in the restart command
        found = False
        for i, arg in enumerate(cmd):
            if arg == "--listen-port" and i + 1 < len(cmd):
                cmd[i + 1] = str(new_port)
                found = True
                break
            if arg.startswith("--listen-port="):
                cmd[i] = f"--listen-port={new_port}"
                found = True
                break
        if not found:
            cmd.extend(["--listen-port", str(new_port)])
        with self._update_lock:
            self._restart_command = cmd
            self._restart_requested = True
        info(f"Port changed to {new_port}. Restarting service...")
        self.stop()
        shutdown_callback()

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
            "update_step": self._upgrade_step,
            "update_step_total": self._upgrade_step_total,
            "update_step_label": self._upgrade_step_label,
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
            self._upgrade_step = 0
            self._upgrade_step_label = "Starting upgrade…"

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

    def _set_upgrade_step(self, step: int, label: str):
        with self._update_lock:
            self._upgrade_step = step
            self._upgrade_step_label = label

    def _run_self_upgrade(self, shutdown_callback: Callable[[], None], target_version: str):
        try:
            self._set_upgrade_step(1, "Checking legacy packages…")
            info(f"Starting self-upgrade to {target_version or 'latest'}")

            self._set_upgrade_step(2, "Resolving package…")

            def _on_pipx_line(line: str):
                """Parse pipx output lines to update the progress step."""
                low = line.lower()
                # Strip spinner characters (braille patterns U+2800–U+28FF)
                clean = low.lstrip("\u2800\u2801\u2802\u2803\u2804\u2805\u2806\u2807"
                                   "\u2808\u2809\u280a\u280b\u280c\u280d\u280e\u280f"
                                   "\u2810\u2811\u2812\u2813\u2814\u2815\u2816\u2817"
                                   "\u2818\u2819\u281a\u281b\u281c\u281d\u281e\u281f"
                                   "\u2820\u2821\u2822\u2823\u2824\u2825\u2826\u2827"
                                   "\u2828\u2829\u282a\u282b\u282c\u282d\u282e\u282f"
                                   "\u2830\u2831\u2832\u2833\u2834\u2835\u2836\u2837"
                                   "\u2838\u2839\u283a\u283b\u283c\u283d\u283e\u283f").strip()
                if "determining package name" in clean:
                    self._set_upgrade_step(2, "Resolving package…")
                elif "installing" in clean and "from spec" in clean:
                    self._set_upgrade_step(3, "Installing…")
                elif "installed package" in clean:
                    # e.g. "installed package clutch 1.7.8, ..."
                    import re as _re
                    m = _re.search(r"installed package \S+ ([\d.]+)", clean)
                    ver_label = f" v{m.group(1)}" if m else ""
                    self._set_upgrade_step(4, f"Installed{ver_label}")
                elif "done!" in clean:
                    self._set_upgrade_step(4, "Install complete")

            result = install_latest_version(on_progress=_on_pipx_line)
            if result.returncode != 0:
                raise RuntimeError("Upgrade failed. Check the service logs for details.")

            self._set_upgrade_step(5, "Verifying installation…")
            mark_update_installed(target_version or get_version())

            self._set_upgrade_step(6, "Install complete")
            import time as _time
            for countdown in (3, 2, 1):
                self._set_upgrade_step(6 + (3 - countdown), f"Restarting in {countdown}…")
                _time.sleep(1)

            self._set_upgrade_step(9, "Restarting…")
            info(f"Latest version installed. Restarting {APP_NAME} service...")

            with self._update_lock:
                self._restart_requested = True

            self.stop()
            shutdown_callback()
        except Exception as exc:
            print_error(f"Self-upgrade failed: {exc}")
            with self._update_lock:
                self._upgrade_in_progress = False
                self._upgrade_step = 0
                self._upgrade_step_label = ""

    def schedule_fake_upgrade(self) -> Dict[str, object]:
        """Simulate the full upgrade flow without installing or restarting."""
        with self._update_lock:
            if self._upgrade_in_progress:
                raise ValueError("A service upgrade is already in progress.")
            self._upgrade_in_progress = True
            self._upgrade_step = 0
            self._upgrade_step_label = "Starting upgrade…"

        thread = threading.Thread(
            target=self._run_fake_upgrade,
            daemon=True,
            name=f"{APP_NAME}-fake-upgrade",
        )
        thread.start()
        return {
            "message": "Simulated upgrade started (no install, no restart).",
            "update_info": self.get_update_info(force_check=False),
        }

    def _run_fake_upgrade(self):
        import time as _time
        try:
            self._set_upgrade_step(1, "Checking legacy packages…")
            _time.sleep(1)
            self._set_upgrade_step(2, "Resolving package…")
            _time.sleep(1.5)
            self._set_upgrade_step(3, "Installing…")
            _time.sleep(2)
            self._set_upgrade_step(4, "Installed v999.0.0")
            _time.sleep(1)
            self._set_upgrade_step(5, "Verifying installation…")
            _time.sleep(0.5)
            self._set_upgrade_step(6, "Install complete")
            _time.sleep(0.5)
            for countdown in (3, 2, 1):
                self._set_upgrade_step(6 + (3 - countdown), f"Restarting in {countdown}…")
                _time.sleep(1)
            self._set_upgrade_step(9, "Restarting…")
            _time.sleep(1)
        finally:
            with self._update_lock:
                self._upgrade_in_progress = False
                self._upgrade_step = 0
                self._upgrade_step_label = ""

    def add_watcher(
        self,
        directory: str,
        *,
        recursive: bool,
        poll_interval: float,
        settle_time: float,
        delete_source: bool = False,
        output_dir: str = "",
        codec: str = "",
        encode_speed: str = "",
        audio_passthrough: Optional[bool] = None,
        force: Optional[bool] = None,
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
            output_dir=output_dir,
            codec=codec,
            encode_speed=encode_speed,
            audio_passthrough=audio_passthrough,
            force=force,
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

    def update_watcher(
        self,
        watcher_id: str,
        directory: str,
        *,
        recursive: bool,
        poll_interval: float,
        settle_time: float,
        delete_source: bool = False,
        output_dir: str = "",
        codec: str = "",
        encode_speed: str = "",
        audio_passthrough: Optional[bool] = None,
        force: Optional[bool] = None,
    ) -> Dict[str, object]:
        if not directory.strip():
            raise ValueError("Watcher directory is required.")
        self._validate_path(directory, require_directory=True)
        with self._watchers_lock:
            old_watcher = self._watchers.pop(watcher_id, None)
            if old_watcher is None:
                raise ValueError("Watcher not found.")
            for existing in self._watchers.values():
                if existing.directory == os.path.abspath(directory):
                    self._watchers[watcher_id] = old_watcher
                    raise ValueError(f"Directory is already being watched: {existing.directory}")
        old_watcher.stop()
        new_watcher = DirectoryWatcher(
            self,
            watcher_id,
            directory,
            recursive=recursive,
            poll_interval=poll_interval,
            settle_time=settle_time,
            delete_source=delete_source,
            output_dir=output_dir,
            codec=codec,
            encode_speed=encode_speed,
            audio_passthrough=audio_passthrough,
            force=force,
        )
        with self._watchers_lock:
            self._watchers[watcher_id] = new_watcher
        self.store.save_watcher_config(new_watcher.to_summary())
        if self._service_started:
            new_watcher.start()
        return new_watcher.to_summary()

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

        # Update schedule config if present in payload
        if "schedule_config" in payload:
            schedule_raw = payload.get("schedule_config") or {}
            if isinstance(schedule_raw, dict):
                schedule_cfg = ScheduleConfig.from_dict(schedule_raw)
                self.scheduler.update_config(schedule_cfg)
                # Wake the schedule monitor immediately so it re-evaluates
                self._schedule_wake_event.set()

        # Update log settings if present in payload
        if "log_level" in payload:
            level = str(payload.get("log_level") or "INFO").upper()
            if level in ("DEBUG", "INFO", "WARNING", "ERROR"):
                self.log_level = level
        if "log_retention_days" in payload:
            try:
                days = int(payload.get("log_retention_days") or 30)
                self.log_retention_days = max(1, min(365, days))
            except (TypeError, ValueError):
                pass

        # Update auth mode if present in payload
        if "auth_enabled" in payload:
            if payload.get("auth_enabled"):
                self.auth.enable_auth()
            else:
                self.auth.skip_auth()

        # Update default date format if present in payload
        if "default_date_format" in payload:
            fmt = str(payload.get("default_date_format") or "")
            if fmt in ("", "YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"):
                self.default_date_format = fmt

        # Update listen port if present in payload
        port_changed = False
        if "listen_port" in payload:
            try:
                new_port = int(payload.get("listen_port") or 8765)
                if 1 <= new_port <= 65535 and new_port != self.listen_port:
                    self.listen_port = new_port
                    port_changed = True
            except (TypeError, ValueError):
                pass

        self.store.save_service_config(
            self.allowed_roots,
            self.default_job_settings,
            self.worker_count,
            self.gpu_devices,
            self.scheduler.config.to_dict(),
            self.log_level,
            self.log_retention_days,
            self.default_date_format,
            self.listen_port,
        )
        if worker_count_changed and self._service_started:
            self._sync_worker_pool()

        # Apply log level change at runtime
        set_log_level(self.log_level)

        summary = self.get_service_summary()

        # If port changed, schedule a service restart with the new port
        if port_changed:
            summary["_restart_pending"] = True

        return summary

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

    def _collect_directory_input_files(self, directory: str, *, recursive: bool, filter_pattern: str = "") -> List[str]:
        import time as _time
        normalized_directory = normalize_path(directory)
        matches: List[str] = []
        scanned = 0

        debug(f"filter: dir={normalized_directory!r} recursive={recursive} pattern={filter_pattern!r}")

        # Build a filter function from the pattern
        _filter_fn = None
        if filter_pattern:
            import fnmatch, re
            # If pattern contains glob chars, treat as fnmatch; otherwise case-insensitive substring
            if any(c in filter_pattern for c in ('*', '?', '[')):
                # Normalize [X..Y] range syntax to standard [X-Y] glob ranges
                glob = re.sub(r'\[([^\]]*?)\.\.([^\]]*?)\]',
                              lambda m: '[' + m.group(1) + '-' + m.group(2) + ']',
                              filter_pattern)
                # Fix unclosed brackets — if [ has no matching ], close it
                open_count = 0
                fixed = []
                for ch in glob:
                    if ch == '[':
                        open_count += 1
                    elif ch == ']':
                        open_count -= 1
                    fixed.append(ch)
                if open_count > 0:
                    fixed.append(']')
                    debug(f"filter: auto-closed unclosed bracket in pattern")
                glob = ''.join(fixed)
                # Auto-wrap in wildcards so the pattern matches as "contains"
                if not glob.startswith('*'):
                    glob = '*' + glob
                if not glob.endswith('*'):
                    glob = glob + '*'
                _re = re.compile(fnmatch.translate(glob), re.IGNORECASE)
                debug(f"filter: glob={glob!r} regex={_re.pattern!r}")
                _filter_fn = lambda name: _re.match(name) is not None
            else:
                _lower = filter_pattern.lower()
                debug(f"filter: substring mode, needle={_lower!r}")
                _filter_fn = lambda name: _lower in name.lower()

        t0 = _time.monotonic()

        if recursive:
            # ── Fast path: when a filter is active, scan top-level entries
            # and only recurse into directories whose name matches the
            # pattern (same strategy as CLI --find). ──
            if _filter_fn:
                top_dirs = []
                matching_dirs = []
                try:
                    with os.scandir(normalized_directory) as it:
                        for entry in it:
                            try:
                                if entry.is_dir(follow_symlinks=True):
                                    top_dirs.append(entry.path)
                                    if _filter_fn(entry.name):
                                        matching_dirs.append(entry.path)
                                elif entry.is_file(follow_symlinks=True):
                                    if self._is_browsable_input_file(entry.path):
                                        scanned += 1
                                        if _filter_fn(entry.name):
                                            matches.append(entry.path)
                            except OSError:
                                continue
                except (PermissionError, OSError):
                    pass

                if matching_dirs:
                    debug(f"filter: fast path — {len(matching_dirs)}/{len(top_dirs)} top-level dirs match")
                    for d in sorted(matching_dirs):
                        for root, _, filenames in os.walk(d):
                            for filename in sorted(filenames):
                                filepath = os.path.join(root, filename)
                                if self._is_browsable_input_file(filepath):
                                    scanned += 1
                                    if not _filter_fn(filename):
                                        continue
                                    matches.append(filepath)
                    elapsed = _time.monotonic() - t0
                    if matches:
                        debug(f"filter: recursive scan done in {elapsed:.2f}s — scanned={scanned} matched={len(matches)} first={os.path.basename(matches[0])!r}")
                    else:
                        debug(f"filter: recursive scan done in {elapsed:.2f}s — scanned={scanned} matched=0")
                    return matches

                debug("filter: no top-level dirs matched, falling back to full scan")

            # ── Slow path: no filter, or no top-level dir names matched ──
            from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

            def _list_dir(dirpath):
                """Return (subdirs, files) for one directory."""
                subdirs = []
                files = []
                try:
                    with os.scandir(dirpath) as it:
                        for entry in it:
                            try:
                                if entry.is_dir(follow_symlinks=True):
                                    subdirs.append(entry.path)
                                elif entry.is_file(follow_symlinks=True):
                                    files.append((entry.path, entry.name))
                            except OSError:
                                continue
                except (PermissionError, OSError):
                    pass
                return subdirs, files

            all_files: list[tuple[str, str]] = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                pending = {pool.submit(_list_dir, normalized_directory)}
                while pending:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        subdirs, files = future.result()
                        all_files.extend(files)
                        for sd in subdirs:
                            pending.add(pool.submit(_list_dir, sd))

            for filepath, filename in sorted(all_files):
                if self._is_browsable_input_file(filepath):
                    scanned += 1
                    if _filter_fn and not _filter_fn(filename):
                        continue
                    matches.append(filepath)

            elapsed = _time.monotonic() - t0
            if matches:
                debug(f"filter: recursive scan done in {elapsed:.2f}s — scanned={scanned} matched={len(matches)} first={os.path.basename(matches[0])!r}")
            else:
                debug(f"filter: recursive scan done in {elapsed:.2f}s — scanned={scanned} matched=0")
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
                        scanned += 1
                        if _filter_fn and not _filter_fn(entry.name):
                            continue
                        matches.append(entry_path)
        except PermissionError as exc:
            raise ValueError(f"Permission denied: {normalized_directory}: {exc}") from exc

        matches.sort()
        elapsed = _time.monotonic() - t0
        if matches:
            debug(f"filter: flat scan done in {elapsed:.2f}s — scanned={scanned} matched={len(matches)} first={os.path.basename(matches[0])!r}")
        else:
            debug(f"filter: flat scan done in {elapsed:.2f}s — scanned={scanned} matched=0")
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
        filter_pattern = str(payload.get("filter_pattern") or "").strip()
        matched_paths = self._collect_directory_input_files(input_path, recursive=recursive, filter_pattern=filter_pattern)
        if not matched_paths:
            if filter_pattern:
                raise ValueError(f"No supported video files matching '{filter_pattern}' found in directory: {normalize_path(input_path)}")
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
        # Check if the schedule currently blocks conversions
        if self.scheduler.config.enabled and not self.scheduler.is_conversion_allowed():
            raise ValueError("Cannot resume: schedule is currently blocking conversions.")

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

    def clear_jobs(self, mode: str = "all") -> Dict[str, int]:
        return self.store.clear(mode=mode)

    def get_service_summary(self, *, force_update_check: bool = False) -> Dict[str, object]:
        return {
            "allowed_roots": self.allowed_roots,
            "default_job_settings": self.get_default_job_settings(),
            "watchers": self.list_watchers(),
            "worker_count": self.worker_count,
            "gpu_devices": list(self.gpu_devices),
            "visible_nvidia_gpus": get_visible_nvidia_gpus(),
            "update_info": self.get_update_info(force_check=force_update_check),
            "schedule_config": self.scheduler.config.to_dict(),
            "schedule_status": self.scheduler.get_status(),
            "bidding_zones": BIDDING_ZONES,
            "log_level": self.log_level,
            "log_retention_days": self.log_retention_days,
            "auth_enabled": self.auth.is_auth_enabled(),
            "default_date_format": self.default_date_format,
            "listen_port": self.listen_port,
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
        if paused and active_thread_id is not None:
            with self._job_control_lock:
                self._pause_detach_jobs.add(job_id)
        return paused

    def _request_running_job_resume(self, job_id: str) -> Optional[Dict[str, object]]:
        if os.name == "nt":
            raise ValueError("Pause and resume are only supported on Unix-like systems.")

        record = self.store.get(job_id)
        if not record:
            debug(f"[{job_id[:8]}] Resume: job not found in store.")
            return None

        with self._job_control_lock:
            active_thread_id = self._active_jobs.get(job_id)

        debug(f"[{job_id[:8]}] Resume: active_thread_id={active_thread_id}, status={record.get('status')}, process_id={record.get('process_id')}, temp_file={bool(record.get('temp_file'))}, resume_on_start={record.get('resume_on_start')}")

        if active_thread_id is None:
            has_recoverable = record_has_recoverable_runtime(record)
            debug(f"[{job_id[:8]}] Resume: no active thread, has_recoverable_runtime={has_recoverable}")
            if not has_recoverable:
                # Process is dead but there may be a partial temp file we can resume from.
                # Requeue so the worker picks it up, then restore the temp file metadata.
                temp_file = str(record.get("temp_file") or "").strip()
                log_file = str(record.get("log_file") or "")
                final_output_file = str(record.get("final_output_file") or "")
                debug(f"[{job_id[:8]}] Resume: requeuing, temp_file_exists={bool(temp_file)}, temp_file='{temp_file}'")
                self.store.requeue(
                    job_id,
                    "Re-queued for partial resume." if temp_file else "Re-queued from scratch.",
                )
                if temp_file:
                    self.store.set_runtime(
                        job_id,
                        process_id=None,
                        temp_file=temp_file,
                        log_file=log_file,
                        final_output_file=final_output_file,
                        resume_on_start=False,
                    )
                self._wake_event.set()
                debug(f"[{job_id[:8]}] Resume: wake event set, returning requeued job.")
                return self.store.get(job_id)
            # Keep status as "paused" — the worker will set "running" when it picks this up.
            result = self.store.set_resume_on_start(
                job_id, True,
                message="Waiting for a worker to resume the paused conversion.",
            )
            self._enqueue_recoverable_job(job_id)
            return result
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

    def _consume_pause_detach(self, job_id: str) -> bool:
        with self._job_control_lock:
            if job_id not in self._pause_detach_jobs:
                return False
            self._pause_detach_jobs.discard(job_id)
            return True

    def _should_detach(self, job_id: str) -> bool:
        if self.stop_event.is_set():
            return True
        with self._job_control_lock:
            return job_id in self._pause_detach_jobs

    def _set_active_job(self, job_id: Optional[str]):
        if job_id is None:
            return
        with self._job_control_lock:
            self._active_jobs[job_id] = threading.get_ident()

    def _clear_active_job(self, job_id: str):
        with self._job_control_lock:
            self._active_jobs.pop(job_id, None)
            self._cancel_requested_jobs.discard(job_id)
            self._pause_detach_jobs.discard(job_id)

    def _worker_loop(self, worker_id: str, worker_stop_event: threading.Event):
        info(f"Worker thread started: {worker_id}")
        while not self.stop_event.is_set() and not worker_stop_event.is_set():
            # Schedule gate: wait until conversions are allowed
            if not self.scheduler.is_conversion_allowed():
                debug(f"Worker {worker_id}: schedule gate blocked, waiting.")
                self._wake_event.wait(min(self.worker_poll_interval, 5.0))
                self._wake_event.clear()
                continue

            record = None
            try:
                record = self._claim_recoverable_job()
                if record:
                    debug(f"Worker {worker_id}: claimed recoverable job {str(record['id'])[:8]}, status={record.get('status')}, process_id={record.get('process_id')}")
                if not record:
                    record = self.store.claim_next()
                    if record:
                        debug(f"Worker {worker_id}: claimed queued job {str(record['id'])[:8]}")
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
                output_summary = extract_media_summary(output_path)
                if output_summary:
                    self.store.merge_extra_json(job_id, {"output_media": output_summary})
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
                final = self.store.get(job_id) or record
                self.notifications.notify("job_succeeded", final)
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
                final = self.store.get(job_id) or record
                self.notifications.notify("job_cancelled", final)
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
                final = self.store.get(job_id) or record
                self.notifications.notify("job_failed", final)
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
        debug(f"[{job_id[:8]}] _execute_regular_job: existing_process_id={existing_process_id}, status={record.get('status')}, temp_file={bool(record.get('temp_file'))}, resume_on_start={record.get('resume_on_start')}")
        if existing_process_id and not is_conversion_process_alive(existing_process_id):
            info(f"[{job_id[:8]}] Previous HandBrake process {existing_process_id} is no longer running.")
            if record.get("status") == "paused":
                self.store.resume(job_id, "Previous process ended. Attempting partial resume.", resume_on_start=False)
            self.store.set_runtime(
                job_id,
                process_id=None,
                temp_file=str(record.get("temp_file") or ""),
                log_file=str(record.get("log_file") or ""),
                final_output_file=str(record.get("final_output_file") or ""),
                resume_on_start=False,
            )
            existing_process_id = None
        if existing_process_id:
            if record.get("status") == "paused" and bool(record.get("resume_on_start")):
                self.store.resume(job_id, "Resuming paused conversion.", resume_on_start=False)
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

        # Detect resumable partial encode: temp file exists but process is dead
        resume_partial = ""
        resume_offset = 0.0
        temp_file = str(record.get("temp_file") or "").strip()
        debug(f"[{job_id[:8]}] Resume-partial check: temp_file='{temp_file}', existing_process_id={existing_process_id}, file_exists={os.path.isfile(temp_file) if temp_file else False}")
        if temp_file and not existing_process_id and os.path.isfile(temp_file):
            try:
                partial_dur = get_media_duration_seconds(temp_file)
                if partial_dur > RESUME_MIN_DURATION:
                    resume_partial = temp_file
                    resume_offset = max(0.0, partial_dur - RESUME_SAFETY_MARGIN)
                    info(f"[{job_id[:8]}] Resuming from partial encode ({partial_dur:.0f}s, offset {resume_offset:.0f}s)")
                else:
                    self._remove_temp_artifacts(record)
            except Exception as exc:
                warning(f"[{job_id[:8]}] Could not probe partial encode, starting fresh: {exc}")
                self._remove_temp_artifacts(record)

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
                existing_temp_file=str(record.get("temp_file") or "") if not resume_partial else "",
                existing_output_file=str(record.get("final_output_file") or ""),
                initial_progress=float(record.get("progress_percent") or 0.0),
                resume_existing_process=bool(record.get("resume_on_start")),
                detach_when=lambda: self._should_detach(job_id),
                runtime_callback=lambda runtime: self.store.set_runtime(
                    job_id,
                    process_id=runtime.get("process_id"),
                    temp_file=str(runtime.get("temp_file") or ""),
                    log_file=str(runtime.get("log_file") or ""),
                    final_output_file=str(runtime.get("final_output_file") or ""),
                    resume_on_start=False,
                ),
                output_base_dir=job.output_base_dir,
                resume_partial_file=resume_partial,
                resume_offset_seconds=resume_offset,
            )
        except ConversionDetached:
            if self._consume_pause_detach(job_id):
                self._wake_event.set()
                return "detached", "", "Paused and detached from worker."
            return "detached", "", "Service stopped while the conversion was still running."
        if output_path:
            return "succeeded", output_path, "Conversion successful."
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."
        if self._consume_pause_detach(job_id):
            self._wake_event.set()
            return "detached", "", "Paused and detached from worker."
        if self.stop_event.is_set():
            return "detached", "", "Service stopped while the conversion was still running."
        # If this was a resume attempt that failed to join, requeue for fresh encode
        if resume_partial:
            return "queued", "", "Resume join failed — re-encoding from the beginning."
        return "failed", "", "Conversion failed."

    def _execute_iso_job(self, job_id: str, job: ConversionJob, record: Dict[str, object]) -> tuple[str, str, str]:
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."

        existing_process_id = int(record.get("process_id") or 0) or None
        if existing_process_id and not is_conversion_process_alive(existing_process_id):
            info(f"[{job_id[:8]}] Previous HandBrake process {existing_process_id} is no longer running.")
            if record.get("status") == "paused":
                self.store.resume(job_id, "Previous process ended. Attempting partial resume.", resume_on_start=False)
            self.store.set_runtime(
                job_id,
                process_id=None,
                temp_file=str(record.get("temp_file") or ""),
                log_file=str(record.get("log_file") or ""),
                final_output_file=str(record.get("final_output_file") or ""),
                resume_on_start=False,
            )
            existing_process_id = None
        if existing_process_id:
            if record.get("status") == "paused" and bool(record.get("resume_on_start")):
                self.store.resume(job_id, "Resuming paused conversion.", resume_on_start=False)
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

        # Detect resumable partial encode for ISO jobs
        resume_partial = ""
        resume_offset = 0.0
        temp_file = str(record.get("temp_file") or "").strip()
        if temp_file and not existing_process_id and os.path.isfile(temp_file):
            try:
                partial_dur = get_media_duration_seconds(temp_file)
                if partial_dur > RESUME_MIN_DURATION:
                    resume_partial = temp_file
                    resume_offset = max(0.0, partial_dur - RESUME_SAFETY_MARGIN)
                    info(f"[{job_id[:8]}] Resuming from partial encode ({partial_dur:.0f}s, offset {resume_offset:.0f}s)")
                else:
                    self._remove_temp_artifacts(record)
            except Exception as exc:
                warning(f"[{job_id[:8]}] Could not probe partial encode, starting fresh: {exc}")
                self._remove_temp_artifacts(record)

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
                existing_temp_file=str(record.get("temp_file") or "") if not resume_partial else "",
                existing_output_file=str(record.get("final_output_file") or ""),
                initial_progress=float(record.get("progress_percent") or 0.0),
                resume_existing_process=bool(record.get("resume_on_start")),
                detach_when=lambda: self._should_detach(job_id),
                runtime_callback=lambda runtime: self.store.set_runtime(
                    job_id,
                    process_id=runtime.get("process_id"),
                    temp_file=str(runtime.get("temp_file") or ""),
                    log_file=str(runtime.get("log_file") or ""),
                    final_output_file=str(runtime.get("final_output_file") or ""),
                    resume_on_start=False,
                ),
                output_base_dir=job.output_base_dir,
                resume_partial_file=resume_partial,
                resume_offset_seconds=resume_offset,
            )
        except ConversionDetached:
            if self._consume_pause_detach(job_id):
                self._wake_event.set()
                return "detached", "", "Paused and detached from worker."
            return "detached", "", "Service stopped while the conversion was still running."
        if output_path:
            return "succeeded", output_path, "Conversion successful."
        if self._consume_cancel_request(job_id):
            return "cancelled", "", "Cancelled from the web UI."
        if self._consume_pause_detach(job_id):
            self._wake_event.set()
            return "detached", "", "Paused and detached from worker."
        if self.stop_event.is_set():
            return "detached", "", "Service stopped while the conversion was still running."
        if resume_partial:
            return "queued", "", "Resume join failed — re-encoding from the beginning."
        return "failed", "", "Conversion failed."




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
    schedule_config: Optional[Dict[str, object]] = None,
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
        schedule_config=schedule_config,
    )

    # Set up application file logging
    log_dir = os.path.join(build_state_dir(), "logs")
    setup_file_logging(log_dir, service.log_level, service.log_retention_days)
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

    # Use persisted port if available (UI may have changed it)
    effective_port = service.listen_port if service.has_persisted_configuration() else port
    service.listen_port = effective_port

    server = ConversionHTTPServer((bind_host, effective_port), ServiceRequestHandler, service)
    info(f"Service listening on http://{bind_host}:{effective_port}")
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
