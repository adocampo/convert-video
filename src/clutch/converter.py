import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Callable, Optional

if os.name != "nt":
    import fcntl
    import pty
    import select
    import termios

from tqdm import tqdm

from clutch import get_binary_path
from clutch.output import (
    info, warning, error, success, skip, debug,
)
from clutch.mediainfo import check_already_converted, get_resolution, get_audio_info, get_mediainfo_json

EXTERNAL_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".idx", ".sub"}
LANGUAGE_CODE_ALIASES = {
    "en": "eng",
    "es": "spa",
    "ca": "cat",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "ja": "jpn",
    "ko": "kor",
    "zh": "zho",
    "ru": "rus",
}

LANGUAGE_NAME_ALIASES = {
    "castellano": "spa",
    "espanol": "spa",
    "spanish": "spa",
    "ingles": "eng",
    "english": "eng",
    "catala": "cat",
    "catalan": "cat",
    "frances": "fra",
    "french": "fra",
    "aleman": "deu",
    "german": "deu",
    "italiano": "ita",
    "italian": "ita",
    "portugues": "por",
    "portuguese": "por",
    "japones": "jpn",
    "japanese": "jpn",
    "korean": "kor",
    "coreano": "kor",
    "chinese": "zho",
    "chino": "zho",
    "russian": "rus",
    "ruso": "rus",
}

# Global references for cleanup on signal
_STATE_UNSET = object()
_conversion_state_lock = threading.Lock()
_conversion_states: dict[int, dict[str, object]] = {}
_last_sigint_time: float = 0.0
_DOUBLE_PRESS_INTERVAL = 1.5  # seconds


def _get_conversion_state(thread_id: Optional[int] = None) -> dict[str, object]:
    key = thread_id if thread_id is not None else threading.get_ident()
    with _conversion_state_lock:
        state = _conversion_states.get(key)
        if state is None:
            state = {
                "temp_file": None,
                "process": None,
                "pid": None,
                "interrupted": False,
                "paused": False,
                "paused_at": None,
                "paused_seconds": 0.0,
            }
            _conversion_states[key] = state
        return dict(state)


def _update_conversion_state(
    thread_id: Optional[int] = None,
    *,
    temp_file=_STATE_UNSET,
    process=_STATE_UNSET,
    pid=_STATE_UNSET,
    interrupted=_STATE_UNSET,
    paused=_STATE_UNSET,
    paused_at=_STATE_UNSET,
    paused_seconds=_STATE_UNSET,
) -> dict[str, object]:
    key = thread_id if thread_id is not None else threading.get_ident()
    with _conversion_state_lock:
        state = _conversion_states.setdefault(
            key,
            {
                "temp_file": None,
                "process": None,
                "pid": None,
                "interrupted": False,
                "paused": False,
                "paused_at": None,
                "paused_seconds": 0.0,
            },
        )
        if temp_file is not _STATE_UNSET:
            state["temp_file"] = temp_file
        if process is not _STATE_UNSET:
            state["process"] = process
        if pid is not _STATE_UNSET:
            state["pid"] = int(pid) if pid else None
        if interrupted is not _STATE_UNSET:
            state["interrupted"] = bool(interrupted)
        if paused is not _STATE_UNSET:
            state["paused"] = bool(paused)
        if paused_at is not _STATE_UNSET:
            state["paused_at"] = paused_at
        if paused_seconds is not _STATE_UNSET:
            state["paused_seconds"] = max(0.0, float(paused_seconds or 0.0))
        return dict(state)


def _is_conversion_interrupted(thread_id: Optional[int] = None) -> bool:
    return bool(_get_conversion_state(thread_id).get("interrupted"))


def _clear_conversion_interrupt(thread_id: Optional[int] = None):
    _update_conversion_state(thread_id, interrupted=False)


def clear_current_conversion_state(thread_id: Optional[int] = None):
    key = thread_id if thread_id is not None else threading.get_ident()
    with _conversion_state_lock:
        _conversion_states.pop(key, None)


def _debug_run(
    cmd: list,
    *,
    encoding: str = "utf-8",
    errors: str = "replace",
    check: bool = False,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """subprocess.run wrapper that always logs the command + full output at DEBUG level."""
    debug(f"$ {' '.join(str(a) for a in cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding=encoding,
        errors=errors,
        check=check,
        **({"timeout": timeout} if timeout is not None else {}),
    )
    for stream_name, stream_text in (("stdout", result.stdout), ("stderr", result.stderr)):
        text = (stream_text or "").strip()
        if not text:
            continue
        lines = text.splitlines()
        header = f"[exit {result.returncode}] {stream_name}"
        if len(lines) > 50:
            debug(f"{header} ({len(lines)} lines, showing last 50):")
            for line in lines[-50:]:
                debug(f"  {line}")
        else:
            debug(f"{header}:")
            for line in lines:
                debug(f"  {line}")
    return result


def _spawn_conversion_process(args, *, stdout=None, stderr=None) -> subprocess.Popen:
    debug(f"HandBrakeCLI command: {' '.join(str(a) for a in args)}")
    kwargs = {
        "stdout": stdout,
        "stderr": stderr,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    return subprocess.Popen(args, **kwargs)


def is_conversion_process_alive(process_id: Optional[int]) -> bool:
    pid = int(process_id or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _signal_process_id(process_id: Optional[int], sig: int) -> bool:
    pid = int(process_id or 0)
    if pid <= 0 or not is_conversion_process_alive(pid):
        return False

    try:
        if os.name != "nt":
            os.killpg(os.getpgid(pid), sig)
        else:
            os.kill(pid, sig)
    except Exception:
        return False
    return True


def _signal_process_tree(process: Optional[subprocess.Popen], sig: int) -> bool:
    if process is None or process.poll() is not None:
        return False

    return _signal_process_id(process.pid, sig)


def _stop_process_tree(process: Optional[subprocess.Popen]) -> bool:
    if process is None or process.poll() is not None:
        return False

    try:
        if os.name != "nt":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            return False
    return True


def request_conversion_stop_by_pid(process_id: Optional[int]) -> bool:
    if os.name != "nt":
        return _signal_process_id(process_id, signal.SIGKILL)
    pid = int(process_id or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def _pause_process_tree(process: Optional[subprocess.Popen]) -> bool:
    if os.name == "nt":
        return False
    return _signal_process_tree(process, signal.SIGSTOP)


def _resume_process_tree(process: Optional[subprocess.Popen]) -> bool:
    if os.name == "nt":
        return False
    return _signal_process_tree(process, signal.SIGCONT)


def request_conversion_pause_by_pid(process_id: Optional[int]) -> bool:
    if os.name == "nt":
        return False
    return _signal_process_id(process_id, signal.SIGSTOP)


def request_conversion_resume_by_pid(process_id: Optional[int]) -> bool:
    if os.name == "nt":
        return False
    return _signal_process_id(process_id, signal.SIGCONT)


def attach_conversion_runtime(
    thread_id: Optional[int] = None,
    *,
    pid: Optional[int],
    temp_file: str,
    paused: bool = False,
    paused_at: Optional[float] = None,
    paused_seconds: float = 0.0,
):
    _update_conversion_state(
        thread_id,
        temp_file=temp_file,
        process=None,
        pid=pid,
        interrupted=False,
        paused=paused,
        paused_at=paused_at,
        paused_seconds=paused_seconds,
    )


def _get_terminal_size() -> tuple[int, int]:
    """Return terminal rows and columns, falling back to a sensible default."""
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.lines, size.columns


def _set_pty_window_size(fd: int):
    """Apply the current terminal size to a PTY file descriptor."""
    rows, cols = _get_terminal_size()
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def handle_sigint(signum, frame):
    """Handle Ctrl+C: single press skips current file, double press exits."""
    global _last_sigint_time
    now = time.time()

    if now - _last_sigint_time < _DOUBLE_PRESS_INTERVAL:
        # Double Ctrl+C — abort everything
        print()
        error("Double Ctrl+C detected. Aborting all conversions...")
        request_all_conversion_stops()
        with _conversion_state_lock:
            temp_files = [
                str(state.get("temp_file") or "")
                for state in _conversion_states.values()
                if state.get("temp_file")
            ]
        for temp_file in temp_files:
            _remove_temp_and_log(temp_file)
        os._exit(1)

    # Single Ctrl+C — skip current file
    _last_sigint_time = now
    print()
    warning("Ctrl+C: skipping current file (press again quickly to abort all)...")
    request_current_conversion_stop()


def install_signal_handlers():
    """Register SIGINT/SIGTERM handlers for safe conversion interruption."""
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)


def request_current_conversion_stop(thread_id: Optional[int] = None) -> bool:
    """Ask a conversion to stop and report whether a live process was signalled."""
    state = _update_conversion_state(thread_id, interrupted=True)
    process = state.get("process")
    if isinstance(process, subprocess.Popen):
        return _stop_process_tree(process)
    return request_conversion_stop_by_pid(state.get("pid"))


def request_current_conversion_pause(thread_id: Optional[int] = None) -> bool:
    """Pause a live conversion and report whether the process was signalled."""
    state = _get_conversion_state(thread_id)
    if state.get("paused"):
        return True

    process = state.get("process")
    if not isinstance(process, subprocess.Popen):
        if not request_conversion_pause_by_pid(state.get("pid")):
            return False
    elif not _pause_process_tree(process):
        return False

    _update_conversion_state(
        thread_id,
        paused=True,
        paused_at=time.monotonic(),
    )
    return True


def request_current_conversion_resume(thread_id: Optional[int] = None) -> bool:
    """Resume a paused conversion and report whether the process was signalled."""
    state = _get_conversion_state(thread_id)
    if not state.get("paused"):
        return False

    process = state.get("process")
    if not isinstance(process, subprocess.Popen):
        if not request_conversion_resume_by_pid(state.get("pid")):
            return False
    elif not _resume_process_tree(process):
        return False

    paused_at = state.get("paused_at")
    paused_seconds = float(state.get("paused_seconds") or 0.0)
    if isinstance(paused_at, (int, float)):
        paused_seconds += max(0.0, time.monotonic() - float(paused_at))

    _update_conversion_state(
        thread_id,
        paused=False,
        paused_at=None,
        paused_seconds=paused_seconds,
    )
    return True


def request_all_conversion_stops() -> bool:
    """Ask every tracked conversion to stop and report whether any live process was signalled."""
    with _conversion_state_lock:
        states = []
        for state in _conversion_states.values():
            state["interrupted"] = True
            states.append(dict(state))

    stopped_any = False
    for state in states:
        process = state.get("process")
        if isinstance(process, subprocess.Popen):
            stopped_any = _stop_process_tree(process) or stopped_any
        else:
            stopped_any = request_conversion_stop_by_pid(state.get("pid")) or stopped_any
    return stopped_any


def get_current_conversion_output_size(thread_id: Optional[int] = None) -> int:
    """Return the current temporary output size for the active conversion."""
    temp_file = _get_conversion_state(thread_id).get("temp_file")
    if not temp_file or not os.path.exists(temp_file):
        return 0
    try:
        return os.path.getsize(temp_file)
    except OSError:
        return 0


def get_current_conversion_paused_seconds(thread_id: Optional[int] = None) -> float:
    """Return the total paused time for the active conversion."""
    state = _get_conversion_state(thread_id)
    paused_seconds = float(state.get("paused_seconds") or 0.0)
    paused_at = state.get("paused_at")
    if state.get("paused") and isinstance(paused_at, (int, float)):
        paused_seconds += max(0.0, time.monotonic() - float(paused_at))
    return paused_seconds


def parse_gpu_devices(value: object) -> list[int]:
    """Parse a GPU device selection into a normalized list of unique indices."""
    if value is None:
        return []

    raw_items: list[str] = []
    if isinstance(value, int):
        raw_items = [str(value)]
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"auto", "any", "default"}:
            return []
        raw_items = [item for item in re.split(r"[\s,;]+", text) if item]
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            raw_items.extend(part for part in re.split(r"[\s,;]+", text) if part)
    else:
        raise ValueError("GPU devices must be provided as an index, a list, or a comma-separated string.")

    devices: list[int] = []
    seen: set[int] = set()
    for item in raw_items:
        lowered = item.lower()
        if lowered in {"auto", "any", "default"}:
            if len(raw_items) == 1:
                return []
            raise ValueError("Automatic GPU selection cannot be combined with explicit GPU indices.")
        try:
            index = int(item)
        except ValueError as exc:
            raise ValueError(f"Invalid GPU index: {item}") from exc
        if index < 0:
            raise ValueError("GPU indices must be zero or greater.")
        if index in seen:
            continue
        seen.add(index)
        devices.append(index)
    return devices


def get_visible_nvidia_gpus() -> list[dict[str, object]]:
    """Return visible NVIDIA GPUs detected through nvidia-smi."""
    try:
        result = _debug_run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"],
            check=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    devices: list[dict[str, object]] = []
    seen: set[int] = set()
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        if index in seen:
            continue
        seen.add(index)
        name = parts[1].removeprefix("NVIDIA ") if len(parts) > 1 else "Unknown"
        memory = parts[2] if len(parts) > 2 else ""
        devices.append({"index": index, "name": name, "memory": memory})
    return devices


def uses_nvenc_encoder(codec: str, encode_speed: str) -> bool:
    """Return whether the current settings route the encode through NVENC."""
    normalized_speed = str(encode_speed or "").strip().lower()
    normalized_codec = str(codec or "").strip().lower()
    if normalized_speed == "normal":
        return True
    if normalized_speed == "fast":
        return normalized_codec.startswith("nvenc_")
    return False


def generate_unique_filename(base_name: str, extension: str, output_path: str) -> str:
    counter = 1
    output_file = os.path.join(output_path, f"{base_name}.{extension}")
    while os.path.exists(output_file):
        match = re.search(r"\((\d+)\)$", base_name)
        if match:
            counter = int(match.group(1)) + 1
            base_name = base_name[:-len(match.group(0))]
        base_name += f" ({counter})"
        output_file = os.path.join(output_path, f"{base_name}.{extension}")
    return output_file


def _remove_temp_and_log(temp_filepath: str):
    """Remove a temp file and its companion .progress.log from disk."""
    for path in (temp_filepath, f"{temp_filepath}.progress.log"):
        try:
            os.remove(path)
        except OSError:
            pass


def _read_last_error_lines(log_path: str, max_lines: int = 30) -> str:
    """Read the last meaningful non-progress lines from a HandBrakeCLI log file."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    meaningful = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"Encoding:.*?\d+\.\d+ %", stripped):
            continue
        meaningful.append(stripped)
    if not meaningful:
        return ""
    return "\n".join(meaningful[-max_lines:])


def _cleanup_sibling_temps(final_output: str, base_name: str, output_dir: str):
    """Remove orphaned .tmp. files for the same base name after a successful conversion."""
    if not output_dir or not os.path.isdir(output_dir):
        return
    prefix = f"{base_name}.tmp."
    for entry in os.scandir(output_dir):
        if entry.is_file() and entry.name.startswith(prefix) and entry.path != final_output:
            try:
                os.remove(entry.path)
            except OSError:
                pass


RESUME_MIN_DURATION = 60.0
RESUME_SAFETY_MARGIN = 5.0


def _join_with_mkvmerge(partial_file: str, remainder_file: str, output_file: str) -> bool:
    """Join a partial encode with its remainder using mkvmerge append mode."""
    cmd = [get_binary_path("mkvmerge"), "-o", output_file, partial_file, "+", remainder_file]
    try:
        result = _debug_run(cmd)
        # mkvmerge returns 0 on success, 1 on warnings (still OK)
        return result.returncode in (0, 1)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        debug(f"mkvmerge join raised {type(exc).__name__}: {exc}")
        return False


def build_output_subdir(input_file: str, output_dir: str, base_dir: str = "") -> str:
    if output_dir:
        abs_output = os.path.abspath(output_dir)
        if base_dir:
            # Preserve subdirectory structure relative to base_dir
            abs_input_dir = os.path.dirname(os.path.abspath(input_file))
            abs_base = os.path.abspath(base_dir)
            rel = os.path.relpath(abs_input_dir, abs_base)
            if rel and rel != ".":
                return os.path.join(abs_output, rel)
        return abs_output
    return os.path.dirname(os.path.abspath(input_file))


def build_default_output_path(input_file: str, output_dir: str) -> str:
    output_subdir = build_output_subdir(input_file, output_dir)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    if output_dir:
        return os.path.join(output_subdir, f"{base_name}.mkv")
    return os.path.join(output_subdir, f"{base_name}_converted.mkv")


def output_is_current_for_input(input_file: str, output_file: str) -> bool:
    try:
        return os.path.getmtime(output_file) >= os.path.getmtime(input_file)
    except OSError:
        return False


def find_existing_converted_output(input_file: str, output_dir: str, codec: str) -> str:
    candidate = build_default_output_path(input_file, output_dir)
    if os.path.abspath(candidate) == os.path.abspath(input_file):
        return ""
    if not os.path.exists(candidate):
        return ""
    if not output_is_current_for_input(input_file, candidate):
        return ""
    if check_already_converted(candidate, codec, False, quiet=True) != "skip":
        return ""
    return candidate


def preserve_audio_titles(input_file: str, output_file: str, *, emit_logs: bool = True):
    """Copy audio track titles from input to output using mkvpropedit."""
    audio_tracks = get_audio_info(input_file)
    for i, track in enumerate(audio_tracks):
        title = track.get("Title", "Stereo")
        track_num = i + 1
        try:
            _debug_run(
                [get_binary_path("mkvpropedit"), output_file,
                 "--edit", f"track:a{track_num}",
                 "--set", f"name={title}"],
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            debug(f"mkvpropedit audio title track {track_num} failed: {type(e).__name__}: {e}")
            if emit_logs:
                warning(f"Could not set audio title for track {track_num}: {e}")


def _normalize_subtitle_language(language_token: str) -> str:
    token = (language_token or "").strip().lower().replace("_", "-")
    if not token:
        return "und"

    # Normalize accents so aliases like "castellano"/"español" map consistently.
    folded = "".join(
        ch for ch in unicodedata.normalize("NFKD", token) if not unicodedata.combining(ch)
    )
    folded = folded.replace("_", "-")

    if folded in LANGUAGE_NAME_ALIASES:
        return LANGUAGE_NAME_ALIASES[folded]

    primary = folded.split("-", 1)[0]
    if primary in LANGUAGE_NAME_ALIASES:
        return LANGUAGE_NAME_ALIASES[primary]
    if len(primary) == 2 and primary.isalpha():
        return LANGUAGE_CODE_ALIASES.get(primary, primary)
    if len(primary) == 3 and primary.isalpha():
        return primary
    return "und"


def _find_external_subtitles(input_file: str) -> list[tuple[str, str]]:
    input_dir = os.path.dirname(os.path.abspath(input_file))
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    base_folded = base_name.casefold()
    discovered: list[tuple[str, str]] = []

    try:
        entries = list(os.scandir(input_dir))
    except OSError:
        return discovered

    for entry in entries:
        if not entry.is_file():
            continue
        stem, ext = os.path.splitext(entry.name)
        ext_lower = ext.lower()
        if ext_lower not in EXTERNAL_SUBTITLE_EXTENSIONS:
            continue

        # For VobSub pairs, use .idx as the control file and skip plain .sub.
        if ext_lower == ".sub":
            idx_pair = os.path.join(input_dir, f"{stem}.idx")
            if os.path.exists(idx_pair):
                continue

        stem_folded = stem.casefold()
        language = "und"
        if stem_folded == base_folded:
            language = "und"
        elif stem_folded.startswith(f"{base_folded}.") or stem_folded.startswith(f"{base_folded}_"):
            suffix = stem[len(base_name) + 1:]
            if not suffix or "." in suffix:
                continue
            language = _normalize_subtitle_language(suffix)
        else:
            continue

        discovered.append((entry.path, language))

    discovered.sort(key=lambda item: os.path.basename(item[0]).casefold())
    return discovered


def mux_external_subtitles(input_file: str, output_file: str, *, emit_logs: bool = True):
    subtitles = _find_external_subtitles(input_file)
    if not subtitles:
        return

    if emit_logs:
        info(f"Adding {len(subtitles)} external subtitle track(s) to output.")
        listed = ", ".join(
            f"{os.path.basename(path)}[{language}]" for path, language in subtitles
        )
        debug(f"External subtitle matches: {listed}")

    # Read the HandBrake encoding application from the output file BEFORE mkvmerge
    # overwrites the container metadata, so we can restore it afterwards.
    _original_writing_app: str = ""
    try:
        _minfo = get_mediainfo_json(output_file)
        _general = next(
            (t for t in (_minfo.get("media", {}).get("track") or []) if t.get("@type") == "General"),
            {},
        )
        for _key in ("Encoded_Application", "Writing_Application", "Encoded_Library"):
            _val = _general.get(_key, "").strip()
            if _val:
                _original_writing_app = _val
                break
    except Exception:
        pass

    merged_output = f"{output_file}.subs.tmp.mkv"
    command = [get_binary_path("mkvmerge"), "-o", merged_output, output_file]
    for subtitle_path, language in subtitles:
        command.extend(["--language", f"0:{language}", subtitle_path])

    try:
        result = _debug_run(command)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        debug(f"mkvmerge subtitle mux raised {type(exc).__name__}: {exc}")
        if emit_logs:
            warning(f"Could not add external subtitles (mkvmerge error): {exc}")
        try:
            os.remove(merged_output)
        except OSError:
            pass
        return

    if result.returncode not in (0, 1):
        if emit_logs:
            detail = (result.stderr or "").strip()
            if detail:
                warning(f"Could not add external subtitles: {detail}")
            else:
                warning("Could not add external subtitles: mkvmerge failed.")
        try:
            os.remove(merged_output)
        except OSError:
            pass
        return

    try:
        os.replace(merged_output, output_file)
    except OSError as exc:
        if emit_logs:
            warning(f"External subtitles were generated but could not replace output file: {exc}")
        try:
            os.remove(merged_output)
        except OSError:
            pass
        return

    # Restore the original HandBrake writing-app so skip detection still works
    # on the next run (mkvmerge overwrites it with its own signature).
    if _original_writing_app:
        propedit_cmd = [
            get_binary_path("mkvpropedit"), output_file,
            "--set", f"writing-app={_original_writing_app}",
        ]
        try:
            _debug_run(propedit_cmd)
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            debug(f"mkvpropedit raised {type(exc).__name__}: {exc}")


class ConversionDetached(RuntimeError):
    """Raised when a service worker intentionally detaches from a live encode."""


def _consume_log_output(
    log_path: str,
    *,
    process: Optional[subprocess.Popen],
    process_id: Optional[int],
    line_handler: Callable[[str], None],
    detach_when: Optional[Callable[[], bool]] = None,
):
    buf = b""
    offset = 0

    def flush_buffer(chunk_buffer: bytes) -> bytes:
        while b"\r" in chunk_buffer or b"\n" in chunk_buffer:
            idx_r = chunk_buffer.find(b"\r")
            idx_n = chunk_buffer.find(b"\n")
            if idx_r == -1:
                idx = idx_n
            elif idx_n == -1:
                idx = idx_r
            else:
                idx = min(idx_r, idx_n)
            line = chunk_buffer[:idx].decode("utf-8", errors="replace")
            chunk_buffer = chunk_buffer[idx + 1:]
            if line:
                line_handler(line)
        return chunk_buffer

    def read_available() -> None:
        nonlocal buf, offset
        if not os.path.exists(log_path):
            return
        with open(log_path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
        if not chunk:
            return
        offset += len(chunk)
        buf += chunk
        buf = flush_buffer(buf)

    while True:
        read_available()

        if detach_when is not None and detach_when():
            raise ConversionDetached("Conversion detached from the service worker.")

        process_running = process.poll() is None if process is not None else is_conversion_process_alive(process_id)
        if not process_running:
            read_available()
            break

        time.sleep(0.1)

    if buf:
        line_handler(buf.decode("utf-8", errors="replace"))


def confirm_prompt() -> bool:
    """Interactive confirmation prompt. Returns True to proceed, False to cancel."""
    while True:
        warning("Continue with transcoding? [Y(yes)/N(no)] (default Y): ")
        key = None
        try:
            import tty
            import termios
        except ImportError:
            tty = None
            termios = None

        if tty is not None and termios is not None:
            try:
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    key = sys.stdin.read(1)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except (termios.error, ValueError, OSError):
                key = None

        if key is None:
            # Fallback for non-TTY environments and platforms without termios.
            key = input().strip()
            if not key:
                key = "y"

        if key in ('\x1b',):  # Escape
            info("\nOperation cancelled by user (Escape).")
            return False
        elif key in ('', '\r', '\n', 'Y', 'y', 'S', 's'):
            print()
            return True
        elif key in ('N', 'n'):
            info("\nOperation cancelled.")
            return False
        else:
            print(f"\r\033[2K", end="")
            error("Invalid option. Try again.")
            time.sleep(0.7)
            print(f"\r\033[2K", end="")


def _extract_progress_percent(line: str) -> Optional[float]:
    match = re.search(r"Encoding:.*? (\d+\.\d+) %", line)
    if not match:
        return None
    return float(match.group(1))


def _consume_pty_output(
    master_fd: int,
    process: subprocess.Popen,
    line_handler: Callable[[str], None],
):
    buf = b""

    def flush_buffer(chunk_buffer: bytes) -> bytes:
        while b"\r" in chunk_buffer or b"\n" in chunk_buffer:
            idx_r = chunk_buffer.find(b"\r")
            idx_n = chunk_buffer.find(b"\n")
            if idx_r == -1:
                idx = idx_n
            elif idx_n == -1:
                idx = idx_r
            else:
                idx = min(idx_r, idx_n)
            line = chunk_buffer[:idx].decode("utf-8", errors="replace")
            chunk_buffer = chunk_buffer[idx + 1:]
            if line:
                line_handler(line)
        return chunk_buffer

    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            buf = flush_buffer(buf)
        elif process.poll() is not None:
            while True:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    buf = flush_buffer(buf)
                else:
                    break
            break

    if buf:
        line_handler(buf.decode("utf-8", errors="replace"))


def convert_video(input_file: str, output_dir: str, codec: str, encode_speed: str,
                   audio_passthrough: bool, verbose: bool,
                   title: int = None, resolution_override: str = None,
                   audio_tracks: list = None, show_progress: bool = True,
                   gpu_device: Optional[int] = None,
                   progress_callback: Optional[Callable[[float, str], None]] = None,
                   emit_logs: bool = True,
                   progress_log_path: str = "",
                   existing_process_id: Optional[int] = None,
                   existing_temp_file: str = "",
                   existing_output_file: str = "",
                   initial_progress: float = 0.0,
                   resume_existing_process: bool = False,
                   detach_when: Optional[Callable[[], bool]] = None,
                   runtime_callback: Optional[Callable[[dict[str, object]], None]] = None,
                   output_base_dir: str = "",
                   resume_partial_file: str = "",
                   resume_offset_seconds: float = 0.0) -> str:
    thread_id = threading.get_ident()

    is_iso = title is not None
    is_resume = bool(resume_partial_file and resume_offset_seconds > 0)
    media_info_data: dict | None = None

    if not is_iso:
        # Reuse one mediainfo JSON payload for resolution/audio decisions.
        media_info_data = get_mediainfo_json(input_file)

    if resolution_override:
        resolution = resolution_override
    else:
        resolution = get_resolution(input_file, data=media_info_data)
        if not resolution:
            return ""

    # Build audio parameters
    audio_params = []
    if audio_passthrough:
        audio_params = [
            "--audio-lang-list", "all",
            "--all-audio",
            "--audio-copy-mask", "eac3,ac3,aac,truehd,dts,dtshd,mp2,mp3,opus,vorbis,flac,alac",
            "--aencoder", "copy",
            "--audio-fallback", "opus",
        ]
    elif is_iso:
        # For ISO sources mediainfo cannot inspect tracks;
        # use audio info gathered during the scan to set per-track mixdown.
        from clutch.iso import _channels_to_mixdown
        if audio_tracks:
            track_list = []
            encoder_list = []
            bitrate_list = []
            mixdown_list = []
            for at in audio_tracks:
                mix, br = _channels_to_mixdown(at['channels'])
                track_list.append(str(at['index']))
                encoder_list.append("opus")
                bitrate_list.append(str(br))
                mixdown_list.append(mix)
            audio_params = [
                "--audio", ",".join(track_list),
                "--aencoder", ",".join(encoder_list),
                "--ab", ",".join(bitrate_list),
                "--mixdown", ",".join(mixdown_list),
                "--audio-copy-mask", "",
            ]
        else:
            # Fallback: no track info available, encode all tracks
            audio_params = [
                "--audio-lang-list", "all",
                "--all-audio",
                "--aencoder", "opus",
                "--ab", "256",
                "--mixdown", "5point1",
                "--audio-copy-mask", "",
            ]
    else:
        audio_info = get_audio_info(input_file, data=media_info_data)
        if audio_info:
            track_list = []
            encoder_list = []
            bitrate_list = []
            mixdown_list = []
            for i, track in enumerate(audio_info):
                channels = int(track["Channels"])
                if channels == 2:
                    mix, br = "stereo", 128
                elif channels in [6, 7]:
                    mix, br = "5point1", 256
                elif channels == 8:
                    mix, br = "7point1", 320
                else:
                    mix, br = "dpl2", 160
                track_list.append(str(i + 1))
                encoder_list.append("opus")
                bitrate_list.append(str(br))
                mixdown_list.append(mix)
            audio_params = [
                "--audio", ",".join(track_list),
                "--aencoder", ",".join(encoder_list),
                "--ab", ",".join(bitrate_list),
                "--mixdown", ",".join(mixdown_list),
                "--audio-copy-mask", "",
            ]
        else:
            audio_params = [
                "--audio", "1",
                "--aencoder", "ac3",
                "--ab", "256",
                "--mixdown", "5point1",
                "--audio-copy-mask", "",
            ]

    # Determine output path and create temp file
    output_subdir = build_output_subdir(input_file, output_dir, base_dir=output_base_dir)

    os.makedirs(output_subdir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    # HandBrakeCLI always outputs Matroska (-f mkv)
    extension = "mkv"

    if existing_output_file:
        final_output = existing_output_file
    elif output_dir:
        final_output = generate_unique_filename(base_name, extension, output_subdir)
    else:
        final_output = generate_unique_filename(f"{base_name}_converted", extension, output_subdir)

    if existing_temp_file:
        temp_filepath = existing_temp_file
    else:
        with tempfile.NamedTemporaryFile(
            dir=output_subdir, prefix=f"{base_name}.tmp.{extension}.", delete=False
        ) as tf:
            temp_filepath = tf.name
    _update_conversion_state(
        thread_id,
        temp_file=temp_filepath,
        process=None,
        pid=existing_process_id,
        interrupted=False,
        paused=False,
        paused_at=None,
        paused_seconds=0.0,
    )

    # Build HandBrakeCLI command
    hb_params = [
        get_binary_path("HandBrakeCLI"),
        "-i", input_file,
        "-o", temp_filepath,
        "--all-subtitles",
        "-f", "mkv",
    ]
    if is_resume:
        hb_params.extend(["--start-at", f"duration:{resume_offset_seconds:.3f}"])
    if title is not None:
        hb_params += ["--title", str(title)]
    hb_params += audio_params

    if encode_speed == "slow":
        hb_params.extend(["--preset", "H.265 MKV 2160p60 4K"])
    elif encode_speed == "normal":
        hb_params.extend(["--preset", "H.265 NVENC 2160p 4K"])
    elif encode_speed == "fast":
        hb_params.extend([
            "-e", codec,
            "-w", resolution.split("x")[0],
            "-l", resolution.split("x")[1],
            "-q", "30",
            "--vb", "1000",
        ])

    if gpu_device is not None and uses_nvenc_encoder(codec, encode_speed):
        hb_params.extend(["--encopts", f"gpu={int(gpu_device)}"])

    try:
        elapsed_text = None
        last_progress = max(0.0, float(initial_progress or 0.0))
        process: Optional[subprocess.Popen] = None
        log_path = progress_log_path or f"{temp_filepath}.progress.log"
        hb_error_detail = ""

        def report_progress(percent: float, detail: str):
            nonlocal last_progress
            clamped = max(0.0, min(percent, 100.0))
            if clamped < last_progress:
                return
            last_progress = clamped
            if progress_callback is not None:
                progress_callback(clamped, detail)

        def should_detach() -> bool:
            if detach_when is None or not detach_when():
                return False
            request_current_conversion_pause(thread_id)
            return True

        report_progress(0.0, "Starting conversion.")

        if _is_conversion_interrupted(thread_id):
            _clear_conversion_interrupt(thread_id)
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            _update_conversion_state(
                thread_id,
                temp_file=None,
                process=None,
                paused=False,
                paused_at=None,
                paused_seconds=0.0,
            )
            if emit_logs:
                skip(f"Conversion skipped: {os.path.basename(input_file)}")
            report_progress(last_progress, "Conversion skipped.")
            return ""

        if verbose:
            # Verbose mode: show full HandBrakeCLI output
            process = _spawn_conversion_process(hb_params)
            _update_conversion_state(thread_id, process=process, pid=process.pid)
            process.wait()
            conversion_succeeded = process.returncode == 0
            _update_conversion_state(thread_id, process=None, pid=None)
        elif show_progress:
            # Progress bar mode — use a pseudo-terminal on Unix so HandBrakeCLI
            # sees a real TTY and emits progress updates; on Windows fall back
            # to a progress-log approach.
            conversion_succeeded = False
            if emit_logs:
                print(f"Converting: {os.path.basename(input_file)}")
            with tqdm(
                total=100,
                dynamic_ncols=True,
                leave=False,
                bar_format="{percentage:3.0f}%|{bar}| [{elapsed}<{remaining}]",
            ) as pbar:
                hb_error_lines = []

                def handle_line(line: str):
                    percent = _extract_progress_percent(line)
                    if percent is None:
                        stripped = line.strip()
                        if stripped:
                            hb_error_lines.append(stripped)
                        return
                    increment = percent - pbar.n
                    if increment > 0:
                        pbar.update(increment)
                    report_progress(percent, line)

                if os.name != "nt":
                    master_fd, slave_fd = pty.openpty()
                    _set_pty_window_size(slave_fd)
                    process = _spawn_conversion_process(
                        hb_params,
                        stdout=slave_fd,
                        stderr=slave_fd,
                    )
                    os.close(slave_fd)
                    _update_conversion_state(thread_id, process=process, pid=process.pid)

                    def handle_resize(signum, frame):
                        """Redraw the progress bar and propagate window size changes."""
                        if process.poll() is not None:
                            return
                        try:
                            _set_pty_window_size(master_fd)
                        except OSError:
                            return
                        pbar.refresh()

                    old_winch_handler = signal.getsignal(signal.SIGWINCH)
                    signal.signal(signal.SIGWINCH, handle_resize)

                    try:
                        _consume_pty_output(master_fd, process, handle_line)
                    finally:
                        signal.signal(signal.SIGWINCH, old_winch_handler)
                        try:
                            os.close(master_fd)
                        except OSError:
                            pass
                else:
                    # Windows: use a log file for progress output
                    win_log_path = f"{temp_filepath}.progress.log"
                    with open(win_log_path, "ab", buffering=0) as log_handle:
                        process = _spawn_conversion_process(
                            hb_params,
                            stdout=log_handle,
                            stderr=log_handle,
                        )
                        _update_conversion_state(thread_id, process=process, pid=process.pid)
                        _consume_log_output(
                            win_log_path,
                            process=process,
                            process_id=process.pid,
                            line_handler=handle_line,
                        )

                process.wait()
                _update_conversion_state(thread_id, process=None, pid=None)
                conversion_succeeded = process.returncode == 0
                if not conversion_succeeded and hb_error_lines:
                    hb_error_detail = "\n".join(hb_error_lines[-30:])
                elapsed_text = tqdm.format_interval(pbar.format_dict["elapsed"])
        elif progress_callback is not None:
            if emit_logs:
                info(f"Converting: {os.path.basename(input_file)}")
            conversion_succeeded = False
            if existing_process_id:
                attach_conversion_runtime(
                    thread_id,
                    pid=existing_process_id,
                    temp_file=temp_filepath,
                    paused=resume_existing_process,
                    paused_at=time.monotonic() if resume_existing_process else None,
                )
                if resume_existing_process:
                    request_current_conversion_resume(thread_id)
            else:
                with open(log_path, "ab", buffering=0) as log_handle:
                    process = _spawn_conversion_process(
                        hb_params,
                        stdout=log_handle,
                        stderr=log_handle,
                    )
                    _update_conversion_state(thread_id, process=process, pid=process.pid)
                    if runtime_callback is not None:
                        runtime_callback(
                            {
                                "process_id": process.pid,
                                "temp_file": temp_filepath,
                                "log_file": log_path,
                                "final_output_file": final_output,
                            }
                        )
                    _consume_log_output(
                        log_path,
                        process=process,
                        process_id=process.pid,
                        line_handler=lambda line: (
                            lambda percent: report_progress(percent, line)
                            if percent is not None else None
                        )(_extract_progress_percent(line)),
                        detach_when=should_detach if detach_when is not None else None,
                    )
                    process.wait()
                    conversion_succeeded = process.returncode == 0
                    if not conversion_succeeded:
                        hb_error_detail = _read_last_error_lines(log_path)
            if existing_process_id:
                _consume_log_output(
                    log_path,
                    process=None,
                    process_id=existing_process_id,
                    line_handler=lambda line: (
                        lambda percent: report_progress(percent, line)
                        if percent is not None else None
                    )(_extract_progress_percent(line)),
                    detach_when=should_detach if detach_when is not None else None,
                )
                conversion_succeeded = last_progress >= 99.9 and os.path.exists(temp_filepath)
                if not conversion_succeeded:
                    hb_error_detail = _read_last_error_lines(log_path)
            _update_conversion_state(thread_id, process=None, pid=None)
        else:
            if emit_logs:
                info(f"Converting: {os.path.basename(input_file)}")
            process = _spawn_conversion_process(hb_params, stderr=subprocess.PIPE)
            _update_conversion_state(thread_id, process=process, pid=process.pid)
            _, stderr_data = process.communicate()
            conversion_succeeded = process.returncode == 0
            if not conversion_succeeded and stderr_data:
                hb_error_detail = stderr_data.decode("utf-8", errors="replace").strip()
                if hb_error_detail:
                    lines = hb_error_detail.splitlines()
                    hb_error_detail = "\n".join(lines[-30:])
            _update_conversion_state(thread_id, process=None, pid=None)

        # Check if this conversion was interrupted by Ctrl+C
        if _is_conversion_interrupted(thread_id):
            _clear_conversion_interrupt(thread_id)
            _remove_temp_and_log(temp_filepath)
            _update_conversion_state(
                thread_id,
                temp_file=None,
                process=None,
                pid=None,
                paused=False,
                paused_at=None,
                paused_seconds=0.0,
            )
            if emit_logs:
                skip(f"Conversion skipped: {os.path.basename(input_file)}")
            report_progress(last_progress, "Conversion skipped.")
            return ""

        if conversion_succeeded:
            if is_resume:
                # Join the partial file with the freshly-encoded remainder
                joined_temp = f"{temp_filepath}.joined"
                try:
                    join_ok = _join_with_mkvmerge(resume_partial_file, temp_filepath, joined_temp)
                except Exception:
                    join_ok = False
                if join_ok:
                    _remove_temp_and_log(resume_partial_file)
                    _remove_temp_and_log(temp_filepath)
                    try:
                        shutil.move(joined_temp, final_output)
                    except OSError:
                        join_ok = False
                if not join_ok:
                    # Stitching failed — clean up and signal requeue for fresh encode
                    _remove_temp_and_log(resume_partial_file)
                    _remove_temp_and_log(temp_filepath)
                    try:
                        os.remove(joined_temp)
                    except OSError:
                        pass
                    if emit_logs:
                        warning("Could not join partial files — will re-encode from the beginning.")
                    _update_conversion_state(
                        thread_id, temp_file=None, process=None, pid=None,
                        interrupted=False, paused=False, paused_at=None, paused_seconds=0.0,
                    )
                    report_progress(0.0, "Join failed, re-encoding from the beginning.")
                    return ""
            else:
                shutil.move(temp_filepath, final_output)
                if not hb_error_detail:
                    hb_error_detail = _read_last_error_lines(log_path)
                _remove_temp_and_log(temp_filepath)  # clean up the progress log
            # Validate the output file is not empty (HandBrakeCLI may exit 0 with 0-byte output)
            try:
                output_size = os.path.getsize(final_output)
            except OSError:
                output_size = 0
            if output_size == 0:
                try:
                    os.remove(final_output)
                except OSError:
                    pass
                _update_conversion_state(
                    thread_id, temp_file=None, process=None, pid=None,
                    interrupted=False, paused=False, paused_at=None, paused_seconds=0.0,
                )
                if emit_logs:
                    error(f"Conversion produced empty file: {os.path.basename(input_file)}")
                    if hb_error_detail:
                        error(f"HandBrakeCLI output:\n{hb_error_detail}")
                report_progress(last_progress, "Conversion failed (empty output).")
                return ""
            _update_conversion_state(
                thread_id,
                temp_file=None,
                process=None,
                pid=None,
                interrupted=False,
                paused=False,
                paused_at=None,
                paused_seconds=0.0,
            )
            if emit_logs:
                if is_resume:
                    success(f"Resumed conversion joined successfully: {os.path.basename(final_output)}")
                elif elapsed_text:
                    success(f"Conversion successful [{elapsed_text}]")
                else:
                    success(f"Conversion successful: {os.path.basename(final_output)}")
            # Preserve audio track titles from original file
            preserve_audio_titles(input_file, final_output, emit_logs=emit_logs)
            # Add external sidecar subtitles that match the source filename.
            mux_external_subtitles(input_file, final_output, emit_logs=emit_logs)
            # Clean up any orphaned temp files from previous attempts
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            _cleanup_sibling_temps(final_output, base_name, os.path.dirname(final_output))
            report_progress(100.0, "Conversion successful.")
            return final_output
        else:
            if not hb_error_detail:
                hb_error_detail = _read_last_error_lines(log_path)
            _remove_temp_and_log(temp_filepath)
            _update_conversion_state(
                thread_id,
                temp_file=None,
                process=None,
                pid=None,
                interrupted=False,
                paused=False,
                paused_at=None,
                paused_seconds=0.0,
            )
            if emit_logs:
                if elapsed_text:
                    error(f"Conversion failed [{elapsed_text}]: {os.path.basename(input_file)}")
                else:
                    error(f"Conversion failed: {os.path.basename(input_file)}")
                if hb_error_detail:
                    error(f"HandBrakeCLI output:\n{hb_error_detail}")
            report_progress(last_progress, "Conversion failed.")
            return ""
    except ConversionDetached:
        if process is not None:
            _update_conversion_state(thread_id, process=None, pid=process.pid)
        raise
    except FileNotFoundError:
        if emit_logs:
            error("HandBrakeCLI not found.")
        _remove_temp_and_log(temp_filepath)
        _update_conversion_state(
            thread_id,
            temp_file=None,
            process=None,
            pid=None,
            interrupted=False,
            paused=False,
            paused_at=None,
            paused_seconds=0.0,
        )
        report_progress(last_progress, "HandBrakeCLI not found.")
        return ""
    except subprocess.CalledProcessError as e:
        if emit_logs:
            error(f"Error during conversion: {e}")
        _remove_temp_and_log(temp_filepath)
        _update_conversion_state(
            thread_id,
            temp_file=None,
            process=None,
            pid=None,
            interrupted=False,
            paused=False,
            paused_at=None,
            paused_seconds=0.0,
        )
        report_progress(last_progress, f"Conversion error: {e}")
        return ""


def poweroff_with_countdown():
    """Power off the system after a 10-second countdown, cancellable with Ctrl+C."""
    print("Powering off in 10 seconds (press Ctrl+C to cancel)... ", end="", flush=True)
    cancelled = False

    def cancel_handler(signum, frame):
        nonlocal cancelled
        cancelled = True

    old_handler = signal.signal(signal.SIGINT, cancel_handler)
    try:
        for count in range(10, 0, -1):
            if cancelled:
                break
            print(f"{count} ", end="", flush=True)
            time.sleep(1)
    finally:
        signal.signal(signal.SIGINT, old_handler)

    if cancelled:
        print(f"\r\033[2KPower off cancelled by user.")
    else:
        print("Powering off the system...")
        subprocess.run(["sudo", "systemctl", "poweroff"])
