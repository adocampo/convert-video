from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from clutch.mediainfo import VIDEO_EXTENSIONS, check_already_converted
from clutch.output import info, success, warning
from clutch.store import ConversionJob

if TYPE_CHECKING:
    from clutch.service import ConversionService


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
        output_dir: str = "",
        codec: str = "",
        encode_speed: str = "",
        audio_passthrough: Optional[bool] = None,
        force: Optional[bool] = None,
        preset_id: Optional[str] = None,
    ):
        super().__init__(daemon=True)
        self.service = service
        self.watcher_id = watcher_id
        self.directory = os.path.abspath(directory)
        self.recursive = recursive
        self.poll_interval = poll_interval
        self.settle_time = settle_time
        self.delete_source = delete_source
        self.output_dir = (output_dir or "").strip()
        self.codec = (codec or "").strip()
        self.encode_speed = (encode_speed or "").strip()
        self.audio_passthrough = audio_passthrough
        self.force = force
        self.preset_id = (preset_id or None) if preset_id else None
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
            "output_dir": self.output_dir,
            "codec": self.codec,
            "encode_speed": self.encode_speed,
            "audio_passthrough": self.audio_passthrough,
            "force": self.force,
            "preset_id": self.preset_id,
        }

    def _apply_overrides(self, payload: Dict[str, object]):
        """Apply watcher-specific overrides to a job payload."""
        payload["delete_source"] = self.delete_source
        if self.output_dir:
            payload["output_dir"] = self.output_dir
            if self.recursive:
                payload["output_base_dir"] = self.directory
        if self.codec:
            payload["codec"] = self.codec
        if self.encode_speed:
            payload["encode_speed"] = self.encode_speed
        if self.audio_passthrough is not None:
            payload["audio_passthrough"] = self.audio_passthrough
        if self.force is not None:
            payload["force"] = self.force
        if self.preset_id:
            payload["preset_id"] = self.preset_id

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

    def _prune_empty_subdirs(self):
        """Remove empty subdirectories inside the watched directory (bottom-up)."""
        for root, dirs, filenames in os.walk(self.directory, topdown=False):
            if root == self.directory:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
                    info(f"Removed empty directory: {root}")
            except OSError:
                pass

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
                self._apply_overrides(payload)
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

            if self.recursive and self.delete_source:
                self._prune_empty_subdirs()

            self.stop_event.wait(self.poll_interval)


@dataclass
class WorkerHandle:
    worker_id: str
    thread: threading.Thread
    stop_event: threading.Event


