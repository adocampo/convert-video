#!/usr/bin/env python3
import argparse
import concurrent.futures
import contextlib
import glob
import io
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from typing import List
from tqdm import tqdm

from convert_video import APP_NAME, get_version
from convert_video.output import info, warning, error, deleted, skip, success
from convert_video.mediainfo import VIDEO_EXTENSIONS, show_source_info, check_already_converted
from convert_video.converter import (
    install_signal_handlers, convert_video, confirm_prompt, poweroff_with_countdown,
    find_existing_converted_output, parse_gpu_devices, request_all_conversion_stops,
)
from convert_video.service import build_service_db_path, run_service, submit_remote_job
from convert_video.scheduler import parse_schedule_rule
from convert_video.updater import (
    check_for_updates,
    get_update_changelog,
    get_update_state,
    mark_cli_notice_shown,
    upgrade,
)
from convert_video.iso import is_iso_file, scan_iso, select_main_title, display_titles

install_signal_handlers()

_DOUBLE_PRESS_INTERVAL = 1.5


class MultiProgressRenderer:
    BAR_FORMAT = "{percentage:3.0f}%|{bar}| [{elapsed}<{remaining}]"

    def __init__(self, total_jobs: int, worker_slots: int):
        self.total_jobs = max(1, total_jobs)
        self.worker_slots = max(1, worker_slots)
        self.enabled = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._order: list[str] = []
        self._started_at = time.monotonic()
        self._last_render_at = 0.0
        self._cursor_hidden = False
        self._closed = False
        self._initialized = False
        self._prev_line_count = 0
        self._pending_completions: list[str] = []

    def start_job(self, input_file: str):
        with self._lock:
            job = self._jobs.setdefault(
                input_file,
                {
                    "label": os.path.basename(input_file) or input_file,
                    "progress": 0.0,
                    "status": "pending",
                    "detail": "Waiting",
                    "started_at": None,
                    "updated_at": time.monotonic(),
                },
            )
            if input_file not in self._order:
                self._order.append(input_file)
            job["status"] = "running"
            job["detail"] = "Starting"
            if job.get("started_at") is None:
                job["started_at"] = time.monotonic()
            job["updated_at"] = time.monotonic()
        self.render(force=True)

    def update_job(self, input_file: str, percent: float, detail: str = ""):
        with self._lock:
            job = self._jobs.setdefault(
                input_file,
                {
                    "label": os.path.basename(input_file) or input_file,
                    "progress": 0.0,
                    "status": "running",
                    "detail": "Starting",
                    "started_at": time.monotonic(),
                    "updated_at": time.monotonic(),
                },
            )
            if input_file not in self._order:
                self._order.append(input_file)
            job["status"] = "running"
            job["progress"] = max(0.0, min(float(percent), 100.0))
            job["detail"] = self._normalize_detail(detail)
            if job.get("started_at") is None:
                job["started_at"] = time.monotonic()
            job["updated_at"] = time.monotonic()
        self.render(force=False)

    def finish_job(self, input_file: str, status: str, detail: str = ""):
        with self._lock:
            job = self._jobs.setdefault(
                input_file,
                {
                    "label": os.path.basename(input_file) or input_file,
                    "progress": 0.0,
                    "status": status,
                    "detail": detail,
                    "started_at": time.monotonic(),
                    "updated_at": time.monotonic(),
                },
            )
            if input_file not in self._order:
                self._order.append(input_file)
            job["status"] = status
            if status in {"succeeded", "skipped"}:
                job["progress"] = 100.0
            job["detail"] = self._normalize_detail(detail or status)
            job["updated_at"] = time.monotonic()

            # Build a completion line matching single-file output style
            label = str(job.get("label") or "")
            started_at = job.get("started_at")
            elapsed_text = ""
            if started_at is not None:
                elapsed_text = tqdm.format_interval(time.monotonic() - float(started_at))

            from convert_video.output import (
                GREEN_COLOR, RED_COLOR, BLUE_COLOR, YELLOW_COLOR, RESET_COLOR,
            )
            if status == "succeeded":
                tag = f"[{GREEN_COLOR} OK {RESET_COLOR}]"
                if elapsed_text:
                    line = f"{tag} Conversion successful [{elapsed_text}] {label}"
                else:
                    line = f"{tag} Conversion successful: {label}"
            elif status == "skipped":
                tag = f"[{BLUE_COLOR}SKIP{RESET_COLOR}]"
                reason = detail or "Already converted"
                line = f"{tag} {reason}: {label}"
            elif status == "failed":
                tag = f"[{RED_COLOR}FAIL{RESET_COLOR}]"
                if elapsed_text:
                    line = f"{tag} Conversion failed [{elapsed_text}]: {label}"
                else:
                    line = f"{tag} Conversion failed: {label}"
            elif status == "aborted":
                tag = f"[{YELLOW_COLOR}WARN{RESET_COLOR}]"
                reason = detail or "Cancelled"
                line = f"{tag} {reason}: {label}"
            else:
                line = f"[{status.upper():^4}] {detail}: {label}"
            self._pending_completions.append(line)
        self.render(force=True)

    def close(self):
        with self._lock:
            if self._closed:
                return
            # Flush pending completions and clear the live progress block
            if self.enabled and self._initialized:
                pending = list(self._pending_completions)
                self._pending_completions.clear()
                if self._prev_line_count > 1:
                    sys.stdout.write(f"\x1b[{self._prev_line_count - 1}F")
                else:
                    sys.stdout.write("\r")
                sys.stdout.write("\x1b[J")
                for line in pending:
                    sys.stdout.write(line + "\n")
            if self.enabled and self._cursor_hidden:
                sys.stdout.write("\x1b[?25h")
                sys.stdout.flush()
                self._cursor_hidden = False
            self._closed = True

    def _normalize_detail(self, detail: str) -> str:
        text = str(detail or "").strip()
        if not text:
            return ""
        if "ETA" in text:
            return ""
        if len(text) > 42:
            return f"{text[:39]}..."
        return text

    def _format_meter(self, percent: float, elapsed: float, width: int) -> str:
        clamped = max(0.0, min(percent, 100.0))
        return tqdm.format_meter(
            clamped,
            100.0,
            max(0.0, elapsed),
            ncols=max(24, width),
            bar_format=self.BAR_FORMAT,
        )

    def _build_lines(self) -> list[str]:
        completed_statuses = {"succeeded", "skipped", "failed", "aborted"}
        done = 0
        running = 0
        failed = 0
        skipped = 0
        progress_total = 0.0

        jobs = [self._jobs[key] for key in self._order]
        for job in jobs:
            progress_total += max(0.0, min(float(job.get("progress") or 0.0), 100.0))
            status = str(job.get("status") or "pending")
            if status in completed_statuses:
                done += 1
            if status == "running":
                running += 1
            elif status == "failed":
                failed += 1
            elif status == "skipped":
                skipped += 1

        pending = max(0, self.total_jobs - done - running)
        overall_percent = progress_total / self.total_jobs
        terminal_width = shutil.get_terminal_size(fallback=(100, 20)).columns
        # 8 chars for "Overall " prefix
        overall_width = max(28, terminal_width - 8)
        overall_meter = self._format_meter(overall_percent, time.monotonic() - self._started_at, overall_width)

        lines = [
            f"Overall {overall_meter}",
            f"Done {done}/{self.total_jobs} | Running {running} | Pending {pending} | Skipped {skipped} | Failed {failed}",
        ]

        active_jobs = [
            self._jobs[key]
            for key in self._order
            if str(self._jobs[key].get("status") or "") == "running"
        ]

        # 4 chars indent on the progress line
        lane_meter_width = max(24, terminal_width - 4)
        for idx, job in enumerate(active_jobs):
            label = str(job.get("label") or "")
            # Full filename on its own line
            lines.append(f"{idx + 1:>2}. {label}")
            # Progress bar on the next line, using full width
            percent = max(0.0, min(float(job.get("progress") or 0.0), 100.0))
            elapsed = time.monotonic() - float(job.get("started_at") or time.monotonic())
            meter = self._format_meter(percent, elapsed, lane_meter_width)
            lines.append(f"    {meter}")

        return lines

    def render(self, *, force: bool):
        with self._lock:
            self._render_locked(force=force)

    def _render_locked(self, *, force: bool):
        if self._closed:
            return
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and now - self._last_render_at < 0.1:
            return

        pending = list(self._pending_completions)
        self._pending_completions.clear()

        lines = self._build_lines()
        if not self._cursor_hidden:
            sys.stdout.write("\x1b[?25l")
            self._cursor_hidden = True
        if self._initialized:
            # Move cursor to the top of the previous block
            if self._prev_line_count > 1:
                sys.stdout.write(f"\x1b[{self._prev_line_count - 1}F")
            else:
                sys.stdout.write("\r")
            # Erase from cursor to end of screen
            sys.stdout.write("\x1b[J")
            # Print completed job lines (they scroll up permanently)
            for completion_line in pending:
                sys.stdout.write(completion_line + "\n")
        # Write the new live block
        for index, line in enumerate(lines):
            sys.stdout.write(line)
            if index < len(lines) - 1:
                sys.stdout.write("\n")
        sys.stdout.flush()
        self._prev_line_count = len(lines)
        self._last_render_at = now
        self._initialized = True


def get_thread_count() -> int:
    """Calculate 50% of available CPU threads, minimum 1."""
    total = os.cpu_count() or 2
    threads = total // 2
    return max(threads, 1)


def get_job_gpu_device(job_index: int, gpu_devices: list[int]) -> int | None:
    if not gpu_devices:
        return None
    return gpu_devices[job_index % len(gpu_devices)]


def check_dependency(command: str):
    try:
        subprocess.run([command, '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        error(f"{command} is required but not installed.")
        sys.exit(1)


def find_video_files(pattern: str) -> List[str]:
    """Find video files recursively in directories matching a glob pattern."""
    cwd = os.getcwd()
    matched_dirs = []

    if pattern == "*":
        matched_dirs = [cwd]
    else:
        search_pattern = os.path.join(cwd, pattern)
        for match in glob.glob(search_pattern):
            if os.path.isdir(match):
                matched_dirs.append(match)

    files = []
    for d in matched_dirs:
        for root, _, filenames in os.walk(d):
            for f in filenames:
                if f.lower().endswith(VIDEO_EXTENSIONS):
                    files.append(os.path.join(root, f))
    return files


def process_local_input(
    input_file: str,
    *,
    output_dir: str,
    codec: str,
    speed: str,
    audio_passthrough: bool,
    verbose: bool,
    delete_source: bool,
    force: bool,
    gpu_device: int | None = None,
    stop_requested: threading.Event | None = None,
    show_progress: bool = True,
    renderer: MultiProgressRenderer | None = None,
) -> str:
    use_combined_progress = renderer is not None
    emit_logs = not use_combined_progress
    effective_verbose = verbose if not use_combined_progress else False

    try:
        if stop_requested is not None and stop_requested.is_set():
            if emit_logs:
                warning(f"Skipping pending file after interruption: '{input_file}'")
            if renderer is not None:
                renderer.finish_job(input_file, "aborted", "Cancelled before start")
            return "aborted"

        if renderer is not None:
            renderer.start_job(input_file)
            if gpu_device is not None:
                renderer.update_job(input_file, 0.0, f"GPU {gpu_device} selected")

        if is_iso_file(input_file):
            if emit_logs:
                titles = scan_iso(input_file)
            else:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    titles = scan_iso(input_file)
            if not titles:
                if emit_logs:
                    warning(f"No titles found in ISO: {input_file}")
                if renderer is not None:
                    renderer.finish_job(input_file, "failed", "No titles found")
                return "failed"

            main_title = select_main_title(titles)
            if emit_logs:
                display_titles(titles, main_title['index'])
                info(f"Selected title {main_title['index']} ({main_title['duration_str']})")
            elif renderer is not None:
                renderer.update_job(input_file, 0.0, f"Title {main_title['index']} selected")

            if stop_requested is not None and stop_requested.is_set():
                if emit_logs:
                    warning(f"Skipping pending ISO after interruption: '{input_file}'")
                if renderer is not None:
                    renderer.finish_job(input_file, "aborted", "Cancelled before encode")
                return "aborted"

            conversion_ok = convert_video(
                input_file,
                output_dir,
                codec,
                speed,
                audio_passthrough,
                effective_verbose,
                title=main_title['index'],
                resolution_override=main_title.get('resolution') or None,
                audio_tracks=main_title.get('audio_tracks', []),
                show_progress=show_progress and not use_combined_progress,
                gpu_device=gpu_device,
                progress_callback=(lambda percent, detail: renderer.update_job(input_file, percent, detail)) if renderer is not None else None,
                emit_logs=emit_logs,
            )
            if conversion_ok:
                if delete_source:
                    try:
                        os.remove(input_file)
                        if emit_logs:
                            deleted(f"Deleted source: {input_file}")
                    except OSError as exc:
                        if emit_logs:
                            warning(f"Could not delete source file '{input_file}': {exc}")
                if renderer is not None:
                    renderer.finish_job(input_file, "succeeded", "Done")
                return "succeeded"
            if stop_requested is not None and stop_requested.is_set():
                if renderer is not None:
                    renderer.finish_job(input_file, "aborted", "Cancelled")
                return "aborted"
            if renderer is not None:
                renderer.finish_job(input_file, "failed", "Failed")
            return "failed"

        if not force:
            if emit_logs:
                status = check_already_converted(input_file, codec, force, quiet=False)
            else:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    status = check_already_converted(input_file, codec, force, quiet=True)
            if status == 'skip':
                if renderer is not None:
                    renderer.finish_job(input_file, "skipped", "Already converted")
                return "skipped"

            existing_output = find_existing_converted_output(input_file, output_dir, codec)
            if existing_output:
                if emit_logs:
                    basename = os.path.basename(input_file)
                    output_name = os.path.basename(existing_output)
                    skip(f"'{basename}' already has a current converted output '{output_name}'. Use --force to override.")
                if renderer is not None:
                    renderer.finish_job(input_file, "skipped", "Existing converted output")
                return "skipped"

        if stop_requested is not None and stop_requested.is_set():
            if emit_logs:
                warning(f"Skipping pending file after interruption: '{input_file}'")
            if renderer is not None:
                renderer.finish_job(input_file, "aborted", "Cancelled before encode")
            return "aborted"

        conversion_ok = convert_video(
            input_file,
            output_dir,
            codec,
            speed,
            audio_passthrough,
            effective_verbose,
            show_progress=show_progress and not use_combined_progress,
            gpu_device=gpu_device,
            progress_callback=(lambda percent, detail: renderer.update_job(input_file, percent, detail)) if renderer is not None else None,
            emit_logs=emit_logs,
        )
        if conversion_ok:
            if delete_source:
                try:
                    os.remove(input_file)
                    if emit_logs:
                        deleted(f"Deleted source: {input_file}")
                except OSError as exc:
                    if emit_logs:
                        warning(f"Could not delete source file '{input_file}': {exc}")
            if renderer is not None:
                renderer.finish_job(input_file, "succeeded", "Done")
            return "succeeded"
        if stop_requested is not None and stop_requested.is_set():
            if renderer is not None:
                renderer.finish_job(input_file, "aborted", "Cancelled")
            return "aborted"
        if renderer is not None:
            renderer.finish_job(input_file, "failed", "Failed")
        return "failed"
    except Exception as exc:
        if emit_logs:
            error(f"Unexpected error while converting '{input_file}': {exc}")
        if renderer is not None:
            renderer.finish_job(input_file, "failed", str(exc))
        return "failed"


def run_local_conversions(input_files: List[str], args, speed: str) -> dict[str, int]:
    summary = {
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
        "aborted": 0,
    }

    if args.workers == 1:
        for index, input_file in enumerate(input_files):
            status = process_local_input(
                input_file,
                output_dir=args.output,
                codec=args.codec,
                speed=speed,
                audio_passthrough=args.audio_passthrough,
                verbose=args.verbose,
                delete_source=args.delete_source,
                force=args.force,
                gpu_device=get_job_gpu_device(index, args.gpu_devices),
                show_progress=True,
            )
            summary[status] += 1
        return summary

    if args.verbose:
        warning("--verbose is disabled with multiple workers so the combined progress display stays readable.")

    stop_requested = threading.Event()
    renderer = MultiProgressRenderer(total_jobs=len(input_files), worker_slots=args.workers)
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    last_signal_at = 0.0

    def parallel_signal_handler(signum, frame):
        nonlocal last_signal_at
        now = time.time()
        if now - last_signal_at < _DOUBLE_PRESS_INTERVAL:
            print()
            error("Double Ctrl+C detected. Aborting all conversions...")
            request_all_conversion_stops()
            os._exit(1)

        last_signal_at = now
        stop_requested.set()
        print()
        warning("Ctrl+C: stopping active conversions and skipping pending files (press again quickly to abort all)...")
        request_all_conversion_stops()

    signal.signal(signal.SIGINT, parallel_signal_handler)
    signal.signal(signal.SIGTERM, parallel_signal_handler)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(
                    process_local_input,
                    input_file,
                    output_dir=args.output,
                    codec=args.codec,
                    speed=speed,
                    audio_passthrough=args.audio_passthrough,
                    verbose=args.verbose,
                    delete_source=args.delete_source,
                    force=args.force,
                    gpu_device=get_job_gpu_device(index, args.gpu_devices),
                    stop_requested=stop_requested,
                    show_progress=False,
                    renderer=renderer,
                )
                for index, input_file in enumerate(input_files)
            ]

            for future in concurrent.futures.as_completed(futures):
                if future.cancelled():
                    summary["aborted"] += 1
                    continue
                status = future.result()
                summary[status] += 1
    finally:
        renderer.close()
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Convert video files using HandBrakeCLI and preserve all audio and subtitle tracks."
    )

    # ── Input / Output ───────────────────────
    io_group = parser.add_argument_group("input/output")
    io_group.add_argument("input_files", nargs="*", default=[], help="Video files or directories to convert.")
    io_group.add_argument("-o", "--output", default="", help="Output directory for converted files.")
    io_group.add_argument("--find", nargs="?", const="*", default=None, metavar="PATTERN",
                          help="Recursively search for video files in directories matching the pattern, "
                               "or current directory if no pattern is given.")
    io_group.add_argument("-r", "--recursive", action="store_true",
                          help="Recursively search directories for video files matching the given patterns.")
    io_group.add_argument("-ds", "--delete-source", action="store_true",
                          help="Delete the original source file after a successful conversion.")

    # ── Encoding ─────────────────────────────
    enc_group = parser.add_argument_group("encoding")
    enc_group.add_argument("-c", "--codec", default="nvenc_h265",
                           help="Video codec: nvenc_h265 (default), nvenc_h264, av1, x265.")
    enc_group.add_argument("-s", "--slow", action="store_true", help="Use slow encoding speed.")
    enc_group.add_argument("-f", "--fast", action="store_true", help="Use fast encoding speed.")
    enc_group.add_argument("-n", "--normal", action="store_true", help="Use normal encoding speed (default).")
    enc_group.add_argument("-ap", "--audio-passthrough", action="store_true",
                           help="Pass through original audio tracks.")
    enc_group.add_argument("--force", action="store_true",
                           help="Force conversion even if file is already in the target codec.")
    enc_group.add_argument("--gpus", default="",
                           help="Comma-separated NVENC GPU indices to use. Example: 0,1 rotates jobs across GPU 0 and GPU 1.")

    # ── Behaviour ────────────────────────────
    beh_group = parser.add_argument_group("behaviour")
    beh_group.add_argument("-y", "--yes", action="store_true",
                           help="Automatically accept transcoding without prompts.")
    beh_group.add_argument("--verbose", action="store_true",
                           help="Show verbose output from HandBrakeCLI.")
    beh_group.add_argument("-w", "--workers", type=int, default=1,
                           help="Number of local conversion workers to run in parallel (default: 1).")
    beh_group.add_argument("-po", "--poweroff", action="store_true",
                           help="Power off the system after conversion.")
    beh_group.add_argument("--server-url", default="",
                           help="Submit matching jobs to a remote clutch service instead of converting locally.")

    service_group = parser.add_argument_group("service")
    service_group.add_argument("--serve", action="store_true",
                               help="Run the HTTP conversion service on this machine.")
    service_group.add_argument("--listen-host", default="127.0.0.1",
                               help="Bind host for the service (default: 127.0.0.1).")
    service_group.add_argument("--listen-port", type=int, default=8765,
                               help="Bind port for the service (default: 8765).")
    service_group.add_argument("--service-db", default=build_service_db_path(),
                               help="SQLite database path for the service queue.")
    service_group.add_argument("--allow-root", action="append", default=[],
                               help="Allowed filesystem root for service input/output paths. Repeat as needed.")
    service_group.add_argument("--watch-dir", action="append", default=[],
                               help="Directory to watch and enqueue automatically when running with --serve.")
    service_group.add_argument("--watch-recursive", action="store_true",
                               help="Watch directories recursively when using --watch-dir.")
    service_group.add_argument("--watch-poll-interval", type=float, default=5.0,
                               help="Polling interval in seconds for watched directories.")
    service_group.add_argument("--watch-settle-time", type=float, default=30.0,
                               help="Seconds a watched file must remain unchanged before enqueueing.")

    # ── Schedule ─────────────────────────────
    sched_group = parser.add_argument_group("schedule")
    sched_group.add_argument("--schedule", action="append", default=[], metavar="RULE",
                             help="Manual schedule rule, e.g. 'mon-fri 22:00-08:00' or '00:00-06:00'. Repeat for more rules.")
    sched_group.add_argument("--schedule-mode", default="allow", choices=["allow", "block"],
                             help="Whether --schedule rules define when conversions are ALLOWED or BLOCKED (default: allow).")
    sched_group.add_argument("--price-provider", default="", choices=["", "energy_charts", "entsoe"],
                             help="Electricity price provider for automatic schedule.")
    sched_group.add_argument("--price-country", default="",
                             help="Bidding zone code for price provider (e.g. ES, DE-LU, FR).")
    sched_group.add_argument("--price-limit", type=float, default=0.0,
                             help="Maximum electricity price in EUR/MWh. Conversions pause above this price.")
    sched_group.add_argument("--price-cheapest-hours", type=int, default=0,
                             help="Only convert during the N cheapest hours of the day.")
    sched_group.add_argument("--entsoe-api-key", default="",
                             help="ENTSO-E Transparency Platform API security token (free registration).")
    sched_group.add_argument("--schedule-priority", default="both_must_allow",
                             choices=["manual_first", "price_first", "both_must_allow"],
                             help="How manual and price schedules interact (default: both_must_allow).")
    sched_group.add_argument("--schedule-pause-behavior", default="block_new",
                             choices=["block_new", "pause_running"],
                             help="Whether to block new jobs or pause running ones when schedule blocks (default: block_new).")

    # ── Info ─────────────────────────────────
    info_group = parser.add_argument_group("info")
    info_group.add_argument("-si", "--source-info", action="store_true",
                            help="Show source information about a single video file.")
    info_group.add_argument("-v", "--version", action="store_true",
                            help="Show the installed version.")
    info_group.add_argument("--update", action="store_true",
                            help="Check if a newer version is available on GitHub.")
    info_group.add_argument("--upgrade", action="store_true",
                            help="Upgrade to the latest version from GitHub.")

    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1.")
    try:
        args.gpu_devices = parse_gpu_devices(args.gpus)
    except ValueError as exc:
        parser.error(str(exc))

    # Handle --update / --upgrade before dependency checks
    if args.update:
        local_ver, remote_ver, update_available = check_for_updates()
        print(f"  Current version : {local_ver}")
        if remote_ver:
            print(f"  Latest version  : {remote_ver}")
            if update_available:
                changelog = get_update_changelog(local_ver, remote_ver)
                if changelog:
                    print()
                    print(changelog)
                    print()
                print(f"  Run '{APP_NAME} --upgrade' to install the new version.")
            else:
                info("Already up to date.")
        sys.exit(0)

    if args.upgrade:
        upgrade()
        sys.exit(0)

    daily_update_state = get_update_state(force=False, quiet=True)
    if daily_update_state.get("update_available") and daily_update_state.get("cli_notice_date") != daily_update_state.get("checked_date"):
        warning(
            f"A newer {APP_NAME} release is available: "
            f"{daily_update_state.get('local_version')} -> {daily_update_state.get('remote_version')}. "
            f"Run '{APP_NAME} --update' to review the changelog or '--upgrade' to install it."
        )
        mark_cli_notice_shown()

    if args.version:
        print(f"{APP_NAME} {get_version()}")
        sys.exit(0)

    if args.serve:
        check_dependency("HandBrakeCLI")
        check_dependency("mediainfo")
        check_dependency("mkvpropedit")

        allowed_roots = [os.path.abspath(path) for path in args.allow_root]
        for watch_dir in args.watch_dir:
            if not os.path.isdir(watch_dir):
                error(f"Watch directory '{watch_dir}' does not exist.")
                sys.exit(1)
        if args.watch_dir and not allowed_roots:
            allowed_roots = [os.path.abspath(path) for path in args.watch_dir]

        # Build schedule config from CLI flags
        schedule_config = None
        has_schedule = bool(args.schedule) or bool(args.price_provider)
        if has_schedule:
            manual_rules = [parse_schedule_rule(rule, args.schedule_mode).to_dict() for rule in args.schedule]
            mode = "manual"
            if args.schedule and args.price_provider:
                mode = "both"
            elif args.price_provider:
                mode = "price"

            price_strategy = "threshold"
            if args.price_cheapest_hours > 0:
                price_strategy = "cheapest_n"

            schedule_config = {
                "enabled": True,
                "mode": mode,
                "priority": args.schedule_priority,
                "pause_behavior": args.schedule_pause_behavior,
                "manual_rules": manual_rules,
                "price": {
                    "provider": args.price_provider,
                    "api_key": args.entsoe_api_key,
                    "bidding_zone": args.price_country,
                    "strategy": price_strategy,
                    "threshold_eur_mwh": args.price_limit,
                    "cheapest_hours": args.price_cheapest_hours,
                },
            }

        run_service(
            bind_host=args.listen_host,
            port=args.listen_port,
            db_path=args.service_db,
            allowed_roots=allowed_roots,
            worker_count=args.workers,
            gpu_devices=args.gpu_devices,
            watch_dirs=args.watch_dir,
            watch_recursive=args.watch_recursive,
            watch_poll_interval=args.watch_poll_interval,
            watch_settle_time=args.watch_settle_time,
            watch_job_template={
                "output_dir": args.output,
                "codec": args.codec,
                "encode_speed": "slow" if args.slow else "fast" if args.fast else "normal",
                "audio_passthrough": args.audio_passthrough,
                "delete_source": args.delete_source,
                "verbose": args.verbose,
                "force": args.force,
            },
            schedule_config=schedule_config,
        )
        sys.exit(0)

    # Runtime dependency checks (only needed for actual conversion)
    if not args.server_url:
        check_dependency("HandBrakeCLI")
        check_dependency("mediainfo")
        check_dependency("mkvpropedit")

    if not args.server_url:
        print(f"Using {args.workers} worker(s) for local transcoding.")
        if args.gpu_devices:
            print(f"Using NVENC GPU device(s): {', '.join(str(device) for device in args.gpu_devices)}")

    # Determine encoding speed
    if args.slow:
        speed = "slow"
    elif args.fast:
        speed = "fast"
    else:
        speed = "normal"

    # Handle --source-info: show info and exit
    if args.source_info:
        if not args.input_files:
            error("No input file provided for --source-info.")
            sys.exit(1)
        show_source_info(args.input_files[0])
        sys.exit(0)

    # Collect input files
    input_files = []
    if args.find is not None:
        input_files = find_video_files(args.find)
    else:
        for item in args.input_files:
            if os.path.isfile(item):
                if item.lower().endswith(VIDEO_EXTENSIONS):
                    input_files.append(item)
                else:
                    warning(f"Skipping non-video file: '{os.path.basename(item)}'")
            elif os.path.isdir(item):
                if args.recursive:
                    for root, _, filenames in os.walk(item):
                        for f in sorted(filenames):
                            if f.lower().endswith(VIDEO_EXTENSIONS):
                                input_files.append(os.path.join(root, f))
                else:
                    error(f"Directory '{item}' requires -r/--recursive option.")
                    sys.exit(1)
            else:
                # Try glob expansion (e.g. wildcards passed via noglob alias)
                matches = sorted(glob.glob(item))
                if not matches and args.recursive:
                    # Try recursive glob: convert pattern to **/pattern
                    base = os.path.dirname(item) or '.'
                    pattern = os.path.basename(item)
                    matches = sorted(glob.glob(os.path.join(base, '**', pattern), recursive=True))
                if matches:
                    for f in matches:
                        if os.path.isfile(f):
                            if f.lower().endswith(VIDEO_EXTENSIONS):
                                input_files.append(f)
                        elif os.path.isdir(f) and args.recursive:
                            for root, _, filenames in os.walk(f):
                                for fn in sorted(filenames):
                                    if fn.lower().endswith(VIDEO_EXTENSIONS):
                                        input_files.append(os.path.join(root, fn))
                        else:
                            warning(f"Not a file, skipping: '{f}'")
                else:
                    warning(f"No matches found for: '{item}'")

    if not input_files:
        error("No input files provided.")
        sys.exit(1)

    if args.server_url:
        if args.workers != 1:
            warning("--workers does not change remote submission order; jobs are still queued one by one on the server.")
        if args.gpu_devices:
            warning("--gpus does not change remote job placement; the server uses its own GPU configuration.")
        for input_file in input_files:
            payload = {
                "input_file": input_file,
                "output_dir": args.output,
                "codec": args.codec,
                "encode_speed": speed,
                "audio_passthrough": args.audio_passthrough,
                "delete_source": args.delete_source,
                "verbose": args.verbose,
                "force": args.force,
            }
            try:
                record = submit_remote_job(args.server_url, payload)
            except RuntimeError as exc:
                error(str(exc))
                sys.exit(1)
            success(f"Remote job submitted: {record['id']} -> {record['input_file']}")
        sys.exit(0)

    # Validate output directory
    if args.output:
        if not os.path.isdir(args.output):
            error(f"Output directory '{args.output}' does not exist.")
            sys.exit(1)
        if not os.access(args.output, os.W_OK):
            error(f"No write permission in output directory '{args.output}'.")
            sys.exit(1)

    # Display matching files
    print("Matching files:")
    for f in input_files:
        print(f"  {f}")

    # Confirmation prompt
    if not args.yes:
        if not confirm_prompt():
            sys.exit(0)

    # Start transcoding
    print("Starting transcoding...")

    summary = run_local_conversions(input_files, args, speed)

    if summary["skipped"]:
        skip(f"{summary['skipped']} file(s) skipped (already converted).")
    if summary["aborted"]:
        warning(f"{summary['aborted']} file(s) interrupted or not started due to cancellation.")
    if summary["failed"]:
        error(f"{summary['failed']} file(s) failed during conversion.")
    if summary["succeeded"]:
        success(f"{summary['succeeded']} file(s) converted successfully.")

    if summary["aborted"]:
        warning("Process interrupted.")
    else:
        success("Process complete.")

    # Power off if requested
    if args.poweroff and not summary["aborted"]:
        poweroff_with_countdown()


if __name__ == "__main__":
    main()
